"""Tests for preflight's control-plane and origin-sync checks, the optional
pointers, and how all of them are wired into main.

`check_kc_status`: a broken control plane is an *environment* fault (exit 2),
it is checked before the repo is resolved, and triage — which dispatches
nothing — is deliberately exempt. `check_synced` / `sync_roots`: which
checkouts the environment syncs, and what fast-forward, rebase, ahead-only,
dirty, detached and a dead remote each do. The phase pointers and the devlock
follow. The kc/manifest/clean-tree/baseline checks are not covered here.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_preflight.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import types
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parent / "preflight.py"
)
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


class patched:
    """Swap module attributes for a `with` block (this file also runs
    standalone, so no fixtures)."""

    def __init__(self, module, **attrs):
        self.module = module
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        for name, value in self.attrs.items():
            self.saved[name] = getattr(self.module, name)
            setattr(self.module, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.module, name, value)
        return False


class fake_subprocess:
    """Stands in for the `subprocess` module: records argv, replays a result."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.result = (returncode, stdout, stderr)
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        code, out, err = self.result
        return subprocess.CompletedProcess(argv, code, out, err)


def argv_has(tokens, argv):
    """Do these tokens appear in argv, in order (not necessarily adjacent)?"""
    rest = iter(argv)
    return all(any(token == seen for seen in rest) for token in tokens)


class scripted_subprocess:
    """Stands in for the `subprocess` module across a multi-command sequence:
    records every argv in `.calls` and answers each call from `(matcher,
    (rc, stdout, stderr))` rules, first match wins, `(0, "", "")` by default.

    A matcher is a token or a tuple of tokens that must appear in the argv in
    order — `"fetch"` answers every fetch, `("/work/Specs", "rebase")` only one
    repo's."""

    def __init__(self, rules=()):
        self.rules = [((m,) if isinstance(m, str) else tuple(m), r)
                      for m, r in rules]
        self.calls = []

    def run(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        for tokens, (code, out, err) in self.rules:
            if argv_has(tokens, argv):
                return subprocess.CompletedProcess(argv, code, out, err)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def called(self, *tokens):
        return any(argv_has(tokens, argv) for argv in self.calls)


def run_main(profile, subproc):
    """main() for one profile with `kc` on PATH and a stubbed subprocess.
    Returns (exit_code, stderr) — exit_code None when it passed silently."""
    stderr = io.StringIO()
    kc_on_path = types.SimpleNamespace(which=lambda name: "/usr/local/bin/kc")
    argv = types.SimpleNamespace(profile=profile)
    parser = types.SimpleNamespace(
        add_argument=lambda *a, **k: None, parse_args=lambda: argv)
    fake_argparse = types.SimpleNamespace(ArgumentParser=lambda **k: parser)
    with patched(preflight, subprocess=subproc, shutil=kc_on_path,
                 argparse=fake_argparse):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.main()
            except SystemExit as exit_:
                return exit_.code, stderr.getvalue()
    return None, stderr.getvalue()


HEALTHY = ("worker daemon:  ok (reachable)\n"
           "controller:     ok (reachable, authenticated)\n"
           "environment:    MyApp-1 (running)\n")
DAEMON_DOWN = ("worker daemon:  FAILED (unreachable: connection refused)\n"
               "controller:     ok (reachable, authenticated)\n")


# -- check_kc_status ---------------------------------------------------------

def test_a_healthy_control_plane_passes_silently():
    subproc = fake_subprocess(0, HEALTHY)
    with patched(preflight, subprocess=subproc):
        preflight.check_kc_status()
    assert subproc.calls == [["kc", "status"]]


def test_a_broken_control_plane_is_an_environment_failure():
    """Exit 2, not 1: the project is not the one asked to fix it."""
    subproc = fake_subprocess(1, DAEMON_DOWN)
    stderr = io.StringIO()
    with patched(preflight, subprocess=subproc):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.check_kc_status()
                raise AssertionError("expected SystemExit")
            except SystemExit as exit_:
                assert exit_.code == 2
    assert "connection refused" in stderr.getvalue(), (
        "the report must be relayed — it says which half is down")


def test_a_precondition_failure_speaks_through_stderr():
    """`kc status` prints its health report to stdout but a broken/outdated pod
    (unset env token) to stderr; preflight relays whichever spoke."""
    subproc = fake_subprocess(
        1, "", "kc status is not configured for this pod: "
               "KUBECODER_ENV_TOKEN unset (broken or outdated pod)")
    stderr = io.StringIO()
    with patched(preflight, subprocess=subproc):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.check_kc_status()
                raise AssertionError("expected SystemExit")
            except SystemExit:
                pass
    assert "KUBECODER_ENV_TOKEN unset" in stderr.getvalue()


# -- profile membership ------------------------------------------------------

def test_plan_and_run_gate_on_the_control_plane_and_triage_does_not():
    """Triage dispatches nothing and touches no kc surface — gating intake on
    live controller reachability would fail work that needs none of it."""
    assert "kc_status" in preflight.PROFILES["plan"]
    assert "kc_status" in preflight.PROFILES["run"]
    assert "kc_status" not in preflight.PROFILES["triage"]


def test_run_gates_on_both_procedure_doc_pointers():
    """The run loop resolves its test and doc phases through these pointers;
    a missing one is caught here, before any session is spawned."""
    assert "phase_pointers" in preflight.PROFILES["run"]
    assert "test_phase.strategy" in preflight.POINTERS
    assert "doc_phase.plan" in preflight.POINTERS


def test_triage_never_shells_out_to_kc_status():
    """A broken control plane cannot stop intake: triage goes straight from the
    PATH check to the repo (here a failing `git rev-parse`, its own exit 2)."""
    subproc = fake_subprocess(1, DAEMON_DOWN)
    code, message = run_main("triage", subproc)
    assert subproc.calls == [["git", "rev-parse", "--show-toplevel"]]
    assert code == 2 and "control plane" not in message


def test_the_control_plane_is_checked_before_the_repo_is_resolved():
    """Neither environment check needs the repo, and the whole run is doomed
    without a control plane — so it fails there, not on a later git/kc call."""
    for profile in ("plan", "run"):
        subproc = fake_subprocess(1, DAEMON_DOWN)
        code, message = run_main(profile, subproc)
        assert code == 2, f"{profile}: expected exit 2, got {code}"
        assert subproc.calls == [["kc", "status"]], (
            f"{profile}: nothing may run after the control plane fails")
        assert "control plane" in message


# -- optional phases ---------------------------------------------------------

def a_config(**over):
    """A ProjectConfig with nothing on disk — these checks are about which
    fields the profile consults, not about the files they name."""
    fields = {"root": Path("/repo"), "path": Path("/repo/.aiworkflowrc"),
              "spec_repo": None, "design_philosophy": None,
              "test_phase": True, "test_strategy": None,
              "doc_phase": True, "doc_plan": None,
              "devlock_lease": None, "push": True}
    fields.update(over)
    return preflight.project_config.ProjectConfig(**fields)


def refused(fn, *args):
    """Run a check expected to bail; return (code, message)."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            fn(*args)
    except SystemExit as e:
        return e.code, err.getvalue()
    raise AssertionError(f"{fn.__name__} passed where it should have bailed")


def test_a_switched_off_phase_is_not_gated_on_a_procedure_doc():
    """The point of the switch: a project that runs no doc phase must not be
    made to name the doc it would have executed."""
    preflight.check_phase_pointers(
        a_config(test_phase=False, doc_phase=False))


def test_a_phase_that_does_run_still_needs_its_doc():
    """Switching the *other* phase off changes nothing for this one — the
    forgotten-pointer signal survives the phases becoming optional."""
    code, message = refused(preflight.check_phase_pointers,
                            a_config(doc_phase=False))
    assert code == 1 and "test_phase.strategy" in message
    code, message = refused(preflight.check_phase_pointers,
                            a_config(test_phase=False))
    assert code == 1 and "doc_phase.plan" in message


def test_an_unnamed_lease_is_checked_for_nothing():
    preflight.check_devlock(a_config())


def test_a_lease_with_nowhere_to_live_bails():
    """A typo'd lease path would take a lock nothing else contends for —
    coordinating nothing, and looking exactly like coordination."""
    code, message = refused(
        preflight.check_devlock,
        a_config(devlock_lease=Path("/nonexistent/scripts/.devlock.lock")))
    assert code == 1 and "devlock.lease" in message


# -- synced with origin ------------------------------------------------------

APP = Path("/work/App")


def repo_rules(counts, dirty="", first=()):
    """What a healthy repo answers: its upstream, its ahead/behind counts and
    its porcelain status (`symbolic-ref` and everything else take the stub's
    default rc 0). `first` goes in front, for the one call a test breaks."""
    return [*first,
            (("rev-parse", "@{u}"), (0, "origin/main\n", "")),
            ("rev-list", (0, counts, "")),
            (("status", "--porcelain"), (0, dirty, ""))]


def synced(subproc, roots=(APP,)):
    """Patch preflight for a `check_synced` run over a fixed repo list — the
    repo set is `sync_roots`' business, so no filesystem is touched here."""
    return patched(preflight, subprocess=subproc,
                   sync_roots=lambda root, cfg: list(roots))


def test_a_repo_already_at_its_origin_is_left_alone():
    """The common case: fetch to learn where origin stands, then nothing —
    silent, and no working tree is inspected or moved."""
    subproc = scripted_subprocess(repo_rules("0\t0"))
    with synced(subproc):
        preflight.check_synced(APP, None)
    assert subproc.called("fetch", "origin")
    assert not subproc.called("status")
    assert not subproc.called("merge") and not subproc.called("rebase")


def test_a_clean_repo_that_is_only_behind_fast_forwards():
    """Nothing local to preserve, so the base moves up to origin without
    writing a merge commit."""
    subproc = scripted_subprocess(repo_rules("0\t3"))
    with synced(subproc):
        preflight.check_synced(APP, None)
    assert subproc.called("merge", "--ff-only", "@{u}")
    assert not subproc.called("rebase")


def test_local_commits_are_rebased_onto_the_moved_base():
    """Behind *and* ahead: the operator's commits are replayed on top rather
    than merged, keeping the branch the linear base the run loop expects."""
    subproc = scripted_subprocess(repo_rules("2\t3"))
    with synced(subproc):
        preflight.check_synced(APP, None)
    assert subproc.called("rebase", "@{u}")
    assert not subproc.called("merge")


def test_a_rebase_that_conflicts_is_aborted_and_handed_back():
    """Preflight resolves nothing: it puts the repo back where it stood and
    names what the operator has to settle."""
    subproc = scripted_subprocess(repo_rules(
        "2\t3", first=[("rebase", (1, "", "CONFLICT (content): in app.py\n"))]))
    with synced(subproc):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 1
    assert subproc.called("rebase", "--abort")
    assert "App" in message and "origin/main" in message


def test_uncommitted_changes_are_never_pulled_over():
    """The one thing a syncing preflight must not do — the operator's dirty
    tree stays theirs, exit 1 for them to resolve."""
    subproc = scripted_subprocess(repo_rules("0\t3", dirty=" M app.py\n"))
    with synced(subproc):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 1 and "uncommitted" in message
    assert not subproc.called("merge") and not subproc.called("rebase")


def test_a_fetch_that_fails_is_an_environment_failure():
    """Exit 2, not 1: an unreachable remote is network or credentials, nothing
    the project's contract can fix."""
    subproc = scripted_subprocess(repo_rules(
        "0\t0", first=[("fetch", (128, "", "fatal: could not read Username\n"))]))
    with synced(subproc):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 2 and "origin" in message
    assert "could not read Username" in message


def test_a_detached_head_is_skipped_and_the_next_repo_still_syncs():
    """Nothing to pull onto — and one such checkout must not stop the
    environment's other repos from being brought up to date."""
    detached = Path("/work/Spike")
    subproc = scripted_subprocess([
        (("/work/Spike", "symbolic-ref"), (1, "", "")),
        *repo_rules("0\t0"),
    ])
    with synced(subproc, roots=(detached, APP)):
        preflight.check_synced(detached, None)
    assert not subproc.called("/work/Spike", "fetch")
    assert subproc.called("/work/App", "fetch")


def test_a_branch_without_an_upstream_is_skipped():
    """No upstream, nothing to pull from — not even a fetch is worth the
    round trip."""
    subproc = scripted_subprocess(repo_rules(
        "0\t0", first=[(("rev-parse", "@{u}"), (128, "", "no upstream\n"))]))
    with synced(subproc):
        preflight.check_synced(APP, None)
    assert not subproc.called("fetch")


def test_unpushed_commits_alone_are_left_where_they_are():
    """Ahead but not behind: those commits are the operator's, and the run loop
    pushes at its test phase — preflight neither pushes nor rewrites them."""
    subproc = scripted_subprocess(repo_rules("2\t0"))
    with synced(subproc):
        preflight.check_synced(APP, None)
    assert not subproc.called("merge") and not subproc.called("rebase")


def _checkout(path):
    (path / ".git").mkdir(parents=True)
    return path


def test_sync_roots_is_the_target_then_the_environments_other_checkouts():
    """In a KubeCoder pod every repo of the environment sits beside the target,
    so the siblings are the set; a directory without a `.git` and a plain file
    are not checkouts, and the target is not repeated among them."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name in ("App", "Zebra", "Beta"):
            _checkout(work / name)
        (work / "Worktree").mkdir()
        (work / "Worktree" / ".git").write_text("gitdir: /work/App/.git/wt\n")
        (work / "notes").mkdir()
        (work / "pull-all.sh").write_text("")
        roots = preflight.sync_roots(work / "App", None)
    assert [p.name for p in roots] == ["App", "Beta", "Worktree", "Zebra"]


def test_sync_roots_adds_a_spec_repo_only_when_it_is_not_already_a_sibling():
    """`spec_repo` is usually `../Specs` — already a sibling, and syncing it
    twice would be the second pull's error message. Elsewhere it is appended."""
    with tempfile.TemporaryDirectory() as tmp:
        work = _checkout(Path(tmp) / "work" / "App").parent
        _checkout(work / "Specs")
        outside = _checkout(Path(tmp) / "elsewhere" / "Specs")
        beside = preflight.sync_roots(
            work / "App", a_config(spec_repo=work / "Specs"))
        elsewhere = preflight.sync_roots(
            work / "App", a_config(spec_repo=outside))
    assert [str(p) for p in beside] == [str(work / "App"), str(work / "Specs")]
    assert [str(p) for p in elsewhere] == [
        str(work / "App"), str(work / "Specs"), str(outside)]


def test_plan_and_run_sync_the_environment_and_triage_does_not():
    """Intake pulls nothing. In run the sync sits after the clean-tree refusal
    (a dirty target hears that established message first) and before the
    baseline build, which must build the freshly pulled base."""
    assert "synced" in preflight.PROFILES["plan"]
    assert "synced" not in preflight.PROFILES["triage"]
    run = preflight.PROFILES["run"]
    assert (run.index("clean_tree") < run.index("synced")
            < run.index("baseline_build"))


# -- one live call -----------------------------------------------------------

def test_against_the_real_kc_status():
    """Pins the invocation to the actual CLI rather than only to the stub: in a
    healthy pod the check passes silently. Skipped where `kc` is absent, or
    where the environment really is unhealthy (that is the check working)."""
    if shutil.which("kc") is None:
        return
    if subprocess.run(["kc", "status"], capture_output=True).returncode != 0:
        return
    preflight.check_kc_status()


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
