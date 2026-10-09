"""Tests for preflight's control-plane and origin-sync checks, the optional
pointers, and how all of them are wired into main.

`check_kc_status`: a broken control plane is an *environment* fault (exit 2),
it is checked before the repo is resolved, and triage — which dispatches
nothing — is deliberately exempt. `check_synced` / `sync_roots`: which
checkouts the environment syncs, and what fast-forward, rebase, ahead-only,
dirty, detached, no upstream and a dead remote each do. A repo on a run loop's
phase branch — live run, bailed run, no slice folder — is refused before either
the sync or the clean-tree check acts on it. The phase pointers and the devlock
follow, and the spec-tree guard: its install into the spec repo's git dir, and
the hook itself, end to end over real git. The kc/manifest/baseline checks and
the rest of clean-tree are not covered here.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_preflight.py` or via pytest.
"""

import contextlib
import fcntl
import importlib.util
import io
import json
import os
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

# The sync also walks the workflow's scratch clones under /work/scratch. The
# suite points that root at a directory that does not exist, so no test sees
# the pod's own clones; the tests about them patch in a root of their own.
preflight.github_target.SCRATCH_ROOT = (Path(tempfile.gettempdir())
                                        / "preflight-suite-no-scratch")
# The plugin check reads Claude Code's installed_plugins.json, which on the
# operator's machine names a real install; no test but its own may see it.
preflight.run_loop.INSTALLED_PLUGINS = (Path(tempfile.gettempdir())
                                        / "preflight-suite-no-home"
                                        / "installed_plugins.json")


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
    the project's contract can fix — and it is not retried, nor blamed on
    anyone: the message says what to check."""
    subproc = scripted_subprocess(repo_rules(
        "0\t0", first=[("fetch", (128, "", "fatal: could not read Username\n"))]))
    slept = []
    with synced(subproc), patched(preflight, _sleep=slept.append):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 2 and "origin" in message
    assert "could not read Username" in message
    assert "network, credentials" in message
    assert "environment's fault" not in message
    assert sum(argv_has(("fetch",), argv) for argv in subproc.calls) == 1
    assert slept == []


RACE = (1, "", "error: cannot lock ref 'refs/remotes/origin/main': is at "
               "1a2b3c but expected 4d5e6f\n"
               "error: incorrect old value provided\n")


class racing_subprocess(scripted_subprocess):
    """A scripted_subprocess whose first `races` fetches lose git's ref-update
    race to another session, and whose later fetches go through."""

    def __init__(self, races, rules=()):
        super().__init__(rules)
        self.races = races

    def run(self, argv, **kwargs):
        if argv_has(("fetch",), list(argv)) and self.races:
            self.races -= 1
            self.calls.append(list(argv))
            return subprocess.CompletedProcess(argv, *RACE)
        return super().run(argv, **kwargs)


def test_a_fetch_that_loses_the_ref_race_is_retried_and_the_sync_goes_on():
    """Another session fetching the same clone moved the ref first; a moment
    later the fetch goes through, and the repo syncs as usual."""
    subproc = racing_subprocess(1, repo_rules("0\t3"))
    slept = []
    with synced(subproc), patched(preflight, _sleep=slept.append):
        preflight.check_synced(APP, None)
    assert sum(argv_has(("fetch",), argv) for argv in subproc.calls) == 2
    assert slept == [1]
    assert subproc.called("merge", "--ff-only", "@{u}")


def test_a_ref_race_that_persists_fails_naming_the_race():
    """Three attempts, then exit 2 with a message that names the race — not
    the network or credentials an agent would otherwise go and check."""
    subproc = racing_subprocess(5, repo_rules("0\t0"))
    slept = []
    with synced(subproc), patched(preflight, _sleep=slept.append):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 2
    assert sum(argv_has(("fetch",), argv) for argv in subproc.calls) == 3
    assert slept == [1, 2]
    assert "ref-update race" in message and "3 times" in message
    assert "rerun" in message
    assert "incorrect old value provided" in message
    assert "environment's fault" not in message


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


def test_a_branch_without_an_upstream_is_refused():
    """No upstream is not "in sync": skipped, the repo would report green
    having synced nothing, so it is refused (exit 1) naming the repo and the
    branch — and nothing is fetched, there is no remote to fetch from."""
    subproc = scripted_subprocess(repo_rules(
        "0\t0", first=[(("symbolic-ref",), (0, "feature/x\n", "")),
                       (("rev-parse", "@{u}"), (128, "", "no upstream\n"))]))
    with synced(subproc):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 1
    assert "App" in message and "feature/x" in message and "upstream" in message
    assert "--set-upstream-to=origin/feature/x" in message, (
        "a branch that is no run's keeps the set-upstream advice")
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


def _git(*args, cwd=None):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _origin_and_clone(tmp, clone):
    """A bare origin with one commit on main, a clone of it at `clone`, and
    a seed checkout to move origin on with. Returns the seed."""
    bare = Path(tmp) / "origin.git"
    seed = Path(tmp) / "seed"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("clone", "-q", str(bare), str(seed))
    _git("checkout", "-q", "-b", "main", cwd=seed)
    (seed / "README").write_text("one\n")
    _git("add", "README", cwd=seed)
    _git("commit", "-qm", "one", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    _git("clone", "-q", str(bare), str(clone))
    return seed


def test_sync_roots_appends_the_marked_scratch_clones_only():
    """A `github:` Target's clone carries the workflow's mark and is synced
    like a sibling; a clone someone made by hand under the scratch root is
    not the workflow's to pull."""
    with tempfile.TemporaryDirectory() as tmp:
        work = _checkout(Path(tmp) / "work" / "App").parent
        scratch = work / "scratch"
        for name in ("Marked", "Hand"):
            _git("init", "-q", str(scratch / name))
        _git("config", preflight.github_target.MARK_KEY, "acme/Marked",
             cwd=scratch / "Marked")
        with patched(preflight.github_target, SCRATCH_ROOT=scratch):
            roots = preflight.sync_roots(work / "App", None)
    assert [str(p) for p in roots] == [str(work / "App"),
                                       str(scratch / "Marked")]


def test_a_marked_scratch_clone_behind_origin_is_fast_forwarded():
    """End to end over real git: the scratch clone gets exactly the siblings'
    sync."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        _origin_and_clone(Path(tmp) / "app", work / "App")
        clone = work / "scratch" / "Widget"
        seed = _origin_and_clone(Path(tmp) / "widget", clone)
        _git("config", preflight.github_target.MARK_KEY, "acme/Widget",
             cwd=clone)
        (seed / "README").write_text("two\n")
        _git("commit", "-qam", "two", cwd=seed)
        _git("push", "-q", "origin", "main", cwd=seed)
        with patched(preflight.github_target, SCRATCH_ROOT=work / "scratch"):
            preflight.check_synced(work / "App", None)
        assert (clone / "README").read_text() == "two\n"


def test_plan_and_run_sync_the_environment_and_triage_does_not():
    """Intake pulls nothing. In run the sync sits after the clean-tree refusal
    (a dirty target hears that established message first) and before the
    baseline build, which must build the freshly pulled base."""
    assert "synced" in preflight.PROFILES["plan"]
    assert "synced" not in preflight.PROFILES["triage"]
    run = preflight.PROFILES["run"]
    assert (run.index("clean_tree") < run.index("synced")
            < run.index("baseline_build"))


# -- a run loop's phase branch -----------------------------------------------

@contextlib.contextmanager
def held_run_lock(lock, note):
    """Hold `lock` the way the run loop's SliceLock does — an exclusive flock
    on a read-write fd, the holder's note written into it — for the block."""
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, note.encode())
        yield
    finally:
        os.close(fd)


def a_spec_repo(tmp, *slices):
    """A spec repo on disk with these slice folders (paths under `slices/`)
    and a git dir for the spec-tree lease's files."""
    spec = Path(tmp) / "Specs"
    for rel in slices:
        (spec / "slices" / rel).mkdir(parents=True)
    (spec / "slices").mkdir(parents=True, exist_ok=True)
    (spec / ".git").mkdir()
    return spec


def on_branch(branch, spec):
    """Every repo answers `branch` to symbolic-ref, and the spec repo its git
    dir; nothing else is scripted — an upstream included, so a check that
    reached the sync would fetch."""
    return scripted_subprocess([
        ("symbolic-ref", (0, f"{branch}\n", "")),
        (("rev-parse", "--absolute-git-dir"), (0, f"{spec / '.git'}\n", "")),
    ])


def no_upstream_advice(message):
    return "--set-upstream-to" not in message and "`-u`" not in message


HOLDER = "host: env-b\npid: 4242\nstarted: 2026-09-24T10:00:00+00:00\n"


def test_a_live_runs_phase_branch_names_the_run_and_says_wait():
    """KubeCoder slice 232: the shared spec tree sat on slice 231's phase
    branch while 231 ran, and preflight advised tracking or pushing it —
    advice that changes a live run's branch. Now it names the run (its folder,
    run.lock's holder, the spec tree's lease holder) and says to wait, and it
    does so before the upstream check: this branch answers one, yet nothing
    is fetched."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "231_spec_tree_lease")
        (spec / ".git" / "dev-spec-tree.holder").write_text(
            "slice 231 P1 (phase/231-P1)\npid: 4242\n")
        lock = spec / "slices" / "231_spec_tree_lease" / "run.lock"
        subproc = on_branch("phase/231-P1", spec)
        with held_run_lock(lock, HOLDER), synced(subproc, roots=(spec,)):
            code, message = refused(preflight.check_synced, spec,
                                    a_config(spec_repo=spec))
            still_held = preflight.run_lock_holder(lock)
            note_after = lock.read_text()
    assert code == 1
    assert "`Specs`" in message and "phase/231-P1" in message
    assert "231_spec_tree_lease" in message
    assert "host: env-b" in message and "pid: 4242" in message
    assert "slice 231 P1 (phase/231-P1)" in message
    assert "live" in message and "Wait" in message
    assert no_upstream_advice(message)
    assert not subproc.called("fetch")
    assert note_after == HOLDER, "the probe must not truncate the holder's note"
    assert still_held == HOLDER.strip(), "the probe must not take the lock away"


def test_a_phase_branch_whose_run_is_gone_says_to_check_the_base_back_out():
    """run.lock with a note but no flock is a run that bailed (the flock goes
    with the process). A code repo's doc-phase branch here: the slice folder
    is still found in the spec repo, and the stale note is left as it was."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "231_spec_tree_lease")
        lock = spec / "slices" / "231_spec_tree_lease" / "run.lock"
        lock.write_text(HOLDER)
        subproc = on_branch("phase/231-docs", spec)
        with synced(subproc):
            code, message = refused(preflight.check_synced, APP,
                                    a_config(spec_repo=spec))
        note_after = lock.read_text()
    assert code == 1
    assert "`App`" in message and "phase/231-docs" in message
    assert "not running" in message and "log.txt" in message
    assert "base branch back out" in message
    assert "pid: 4242" not in message, "a dead run's note names no one"
    assert no_upstream_advice(message)
    assert note_after == HOLDER


def test_a_phase_branch_with_no_slice_folder_gets_the_generic_refusal():
    """No folder to find a run.lock in — so preflight cannot say whether the
    run is live, only what kind of branch it is and both ways out."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "backlog/230_other", "completed/229_older")
        subproc = on_branch("phase/231-P2", spec)
        with synced(subproc, roots=(spec,)):
            code, message = refused(preflight.check_synced, spec,
                                    a_config(spec_repo=spec))
    assert code == 1
    assert "phase/231-P2" in message and "slice 231" in message
    assert "not a branch to push or track" in message
    assert no_upstream_advice(message)


def test_the_slice_folder_is_found_in_backlog_and_completed_too():
    """`slices/` holds a running slice, but a phase branch can outlive the
    move — the folder is looked up in all three."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "240_running", "backlog/241_queued",
                           "completed/242_done")
        found = [preflight.find_slice_dir(spec, n)
                 for n in ("240", "241", "242", "24")]
    assert [d.name if d else None for d in found] == [
        "240_running", "241_queued", "242_done", None]


def test_a_dirty_target_on_a_live_phase_branch_hears_wait_not_stash():
    """The clean-tree check runs before the sync, and its "commit or stash"
    is exactly wrong for a live run's writer mid-phase in the target repo."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "231_spec_tree_lease")
        lock = spec / "slices" / "231_spec_tree_lease" / "run.lock"
        subproc = scripted_subprocess([
            ("symbolic-ref", (0, "phase/231-P3\n", "")),
            (("status", "--porcelain"), (0, " M app.py\n", "")),
        ])
        with held_run_lock(lock, HOLDER), patched(preflight, subprocess=subproc):
            code, message = refused(preflight.check_clean_tree, APP,
                                    a_config(spec_repo=spec))
    assert code == 1
    assert "live" in message and "stash" not in message


# -- one live call -----------------------------------------------------------

# -- check_baseline_build ----------------------------------------------------

def test_a_green_baseline_build_passes_silently():
    subproc = fake_subprocess(0, "root: ok\n")
    with patched(preflight, subprocess=subproc):
        preflight.check_baseline_build(Path("/work/MyApp"))
    assert subproc.calls == [["kc", "project", "build"]]


def test_a_manifest_with_no_build_statement_passes():
    """kc exits 3 (KC-81) when no component has a build statement — nothing
    ran, so there is no baseline to break (Ansible slice 026)."""
    subproc = fake_subprocess(
        3, "root: no build statements — skipped\n"
           "ansible: no build statements — skipped\n")
    with patched(preflight, subprocess=subproc):
        preflight.check_baseline_build(Path("/work/MyApp"))


def test_a_red_baseline_build_is_the_projects_to_fix():
    subproc = fake_subprocess(1, "ansible: FAILED\n")
    stderr = io.StringIO()
    with patched(preflight, subprocess=subproc):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.check_baseline_build(Path("/work/MyApp"))
                raise AssertionError("expected SystemExit")
            except SystemExit as exit_:
                assert exit_.code == 1
    assert "ansible: FAILED" in stderr.getvalue()


def test_against_the_real_kc_status():
    """Pins the invocation to the actual CLI rather than only to the stub: in a
    healthy pod the check passes silently. Skipped where `kc` is absent, or
    where the environment really is unhealthy (that is the check working)."""
    if shutil.which("kc") is None:
        return
    if subprocess.run(["kc", "status"], capture_output=True).returncode != 0:
        return
    preflight.check_kc_status()


# -- check_plugin_current ----------------------------------------------------

OURS = preflight.run_loop.plugin_version()


def installed_plugins(tmp, version):
    """installed_plugins.json in `tmp` naming `version` for this plugin (None:
    no entry for it), and the install root its paths sit under."""
    path = Path(tmp) / "installed_plugins.json"
    root = Path(tmp) / "cache" / "aiworkflow" / "dev"
    plugins = {"kubecoder@kubecoder-config": [
        {"scope": "user", "installPath": "/elsewhere", "version": "0.8"}]}
    if version is not None:
        plugins["dev@aiworkflow"] = [{
            "scope": "user", "version": version,
            "installPath": str(root / version)}]
    path.write_text(json.dumps({"version": 2, "plugins": plugins}))
    return path, root


def plugin_line(profile):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        preflight.check_plugin_current(profile)
    return stdout.getvalue()


def test_a_stale_session_plugin_names_the_installed_loop():
    """The session runs another version than the installed one: the line
    names the installed copy of the loop the profile's command launches."""
    for profile, script in (("plan", "plan_loop.py"), ("run", "run_loop.py")):
        with tempfile.TemporaryDirectory() as tmp:
            path, root = installed_plugins(tmp, "0.0.1")
            with patched(preflight.run_loop, INSTALLED_PLUGINS=path):
                line = plugin_line(profile)
        assert str(root / "0.0.1" / "tools" / script) in line, line
        assert f"this session's plugin is {OURS}" in line
        assert "the installed one is 0.0.1" in line
        assert "every launch and relaunch" in line
        assert line.count("\n") == 1, "one line"


def test_a_matching_or_unknown_installed_plugin_prints_nothing():
    for version in (OURS, None, "absent"):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = installed_plugins(tmp, version)
            if version == "absent":
                path.unlink()
            with patched(preflight.run_loop, INSTALLED_PLUGINS=path):
                assert plugin_line("run") == "", version


def test_the_plugin_line_comes_last_and_only_for_plan_and_run():
    """Printed after every other check, so a failing check's message is
    never joined by it; triage launches no loop and never checks."""
    stubs = ["check_kc", "check_kc_status", "repo_root", "check_manifest",
             "load_config", "check_pointer", "check_spec_tree_guard",
             "check_phase_pointers", "check_devlock", "check_clean_tree",
             "check_synced", "check_baseline_build", "check_plugin_current"]
    for profile in ("triage", "plan", "run"):
        calls = []
        recorders = {name: (lambda *a, _n=name, _c=calls, **k: _c.append(_n))
                     for name in stubs}
        with patched(preflight, **recorders):
            code, _ = run_main(profile, fake_subprocess())
        assert code is None, profile
        if profile == "triage":
            assert "check_plugin_current" not in calls
        else:
            assert calls[-1] == "check_plugin_current", (profile, calls)


# -- the spec-tree guard -----------------------------------------------------

GUARD = preflight.GUARD_SOURCE.read_bytes()
GUARD_V = preflight.guard_version(GUARD.decode())


@contextlib.contextmanager
def plain_git():
    """Real git, isolated from the machine's config (a global
    `core.hooksPath` would move the hook out from under the tests) and with
    an identity to commit as. Set in os.environ, because the check and the
    hook both run git as subprocesses that inherit it."""
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    saved = {k: os.environ.get(k)
             for k in (*env, "DEV_PHASE_BRANCH", "GIT_CEILING_DIRECTORIES")}
    os.environ.update(env)
    os.environ.pop("DEV_PHASE_BRANCH", None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def a_git_spec_repo(tmp):
    """A real spec repo with one commit on main."""
    spec = Path(tmp) / "Specs"
    spec.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(spec)], check=True)
    (spec / "README").write_text("specs\n")
    subprocess.run(["git", "-C", str(spec), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(spec), "commit", "-qm", "one"],
                   check=True)
    return spec


def install_guard(spec):
    """The check over a real spec repo; returns its hook path."""
    preflight.check_spec_tree_guard(a_config(spec_repo=spec))
    return spec / ".git" / "hooks" / "pre-commit"


def test_the_guard_is_installed_where_there_is_no_hook():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hook = spec / ".git" / "hooks" / "pre-commit"
        hook.unlink(missing_ok=True)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            install_guard(spec)
        assert hook.read_bytes() == GUARD
        assert os.access(hook, os.X_OK)
        assert stderr.getvalue() == "", "silent on success"
        assert not [p for p in hook.parent.iterdir()
                    if p.name.startswith(".pre-commit.")], "no temp left"


def test_an_older_guard_is_replaced():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hook = spec / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\n# aiworkflow spec-tree guard "
                        f"v{GUARD_V - 1}\nexit 0\n")
        install_guard(spec)
        assert hook.read_bytes() == GUARD
        assert os.access(hook, os.X_OK)


def test_a_same_or_newer_guard_is_left_byte_for_byte():
    """The git dir is shared by every environment, and they run different
    plugin versions: an older plugin must not take a newer guard back."""
    if shutil.which("git") is None:
        return
    for version in (GUARD_V, 99):
        with tempfile.TemporaryDirectory() as tmp, plain_git():
            spec = a_git_spec_repo(tmp)
            hook = spec / ".git" / "hooks" / "pre-commit"
            theirs = (f"#!/bin/sh\n# aiworkflow spec-tree guard v{version}\n"
                      "# another environment's copy\nexit 0\n")
            hook.write_text(theirs)
            install_guard(spec)
            assert hook.read_text() == theirs, version


def test_a_hook_the_plugin_did_not_write_is_refused_not_overwritten():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hook = spec / ".git" / "hooks" / "pre-commit"
        theirs = "#!/bin/sh\nexec lint-staged\n"
        hook.write_text(theirs)
        code, message = refused(preflight.check_spec_tree_guard,
                                a_config(spec_repo=spec))
        assert code == 1
        assert str(hook) in message
        assert "never overwrites a hook it did not write" in message
        assert hook.read_text() == theirs


def test_the_guard_goes_where_core_hookspath_points():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hooks = Path(tmp) / "shared-hooks"
        subprocess.run(["git", "-C", str(spec), "config", "core.hooksPath",
                        str(hooks)], check=True)
        install_guard(spec)
        assert (hooks / "pre-commit").read_bytes() == GUARD
        assert not (spec / ".git" / "hooks" / "pre-commit").exists()
        # relative: to the repo, where git runs its hooks
        subprocess.run(["git", "-C", str(spec), "config", "core.hooksPath",
                        "githooks"], check=True)
        install_guard(spec)
        assert (spec / "githooks" / "pre-commit").read_bytes() == GUARD


def test_a_spec_repo_that_is_no_git_repo_gets_no_guard():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = Path(tmp) / "Specs"
        spec.mkdir()
        os.environ["GIT_CEILING_DIRECTORIES"] = tmp
        preflight.check_spec_tree_guard(a_config(spec_repo=spec))
        assert list(Path(tmp).rglob("*pre-commit*")) == []


def test_a_plugin_without_a_readable_versioned_guard_is_a_broken_install():
    """Exit 2: nothing the project can fix, and nothing is installed."""
    with tempfile.TemporaryDirectory() as tmp:
        unmarked = Path(tmp) / "spec-tree-guard.sh"
        unmarked.write_text("#!/bin/sh\nexit 0\n")
        for source in (unmarked, Path(tmp) / "missing.sh"):
            with patched(preflight, GUARD_SOURCE=source):
                code, message = refused(preflight.check_spec_tree_guard,
                                        a_config(spec_repo=Path(tmp)))
            assert code == 2 and str(source) in message
            assert "plugin install is broken" in message


def commit(spec, name, **env):
    """A real `git commit` of one new file, with these env vars on top;
    returns (rc, stderr) and whether HEAD moved."""
    before = subprocess.run(["git", "-C", str(spec), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout
    (spec / name).write_text(name + "\n")
    subprocess.run(["git", "-C", str(spec), "add", name], check=True)
    done = subprocess.run(["git", "-C", str(spec), "commit", "-qm", name],
                          capture_output=True, text=True,
                          env={**os.environ, **env})
    after = subprocess.run(["git", "-C", str(spec), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout
    if done.returncode != 0:
        subprocess.run(["git", "-C", str(spec), "rm", "-q", "--cached",
                        name], check=True)
        (spec / name).unlink()
    return done.returncode, done.stderr, before != after


def test_the_guard_refuses_a_commit_on_a_phase_branch_not_its_own():
    """End to end: the hook preflight installs, under real commits. Main and
    a detached HEAD pass; a phase branch passes only for the session that
    names it in DEV_PHASE_BRANCH. Refused, a session hears which case it is:
    a live run holding the tree (its holder note, and the lease to wait on)
    or a branch a stopped run left."""
    if shutil.which("git") is None or shutil.which("flock") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        install_guard(spec)
        git_dir = spec / ".git"
        rc_, _, moved = commit(spec, "on-main")
        assert rc_ == 0 and moved, "main is no phase's"

        branch = "phase/054-P1"
        subprocess.run(["git", "-C", str(spec), "checkout", "-qb", branch],
                       check=True)
        rc_, err, moved = commit(spec, "stray")
        assert rc_ != 0 and not moved
        assert "no run holds the tree" in err
        rc_, _, moved = commit(spec, "own", DEV_PHASE_BRANCH=branch)
        assert rc_ == 0 and moved
        rc_, err, moved = commit(spec, "other",
                                 DEV_PHASE_BRANCH="phase/055-P2")
        assert rc_ != 0 and not moved

        lease = git_dir / "dev-spec-tree.lock"
        (git_dir / "dev-spec-tree.holder").write_text(
            f"slice 054 P1 ({branch})\npid: 1\nhost: env-b\n")
        fd = os.open(lease, os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            rc_, err, moved = commit(spec, "while-held")
            assert rc_ != 0 and not moved
            assert f"slice 054 P1 ({branch})" in err
            assert f"flock -s '{lease.resolve()}'" in err, err
            rc_, _, moved = commit(spec, "own-while-held",
                                   DEV_PHASE_BRANCH=branch)
            assert rc_ == 0 and moved, "the run's own commit while it holds"
        finally:
            os.close(fd)

        subprocess.run(["git", "-C", str(spec), "checkout", "-q", "--detach"],
                       check=True)
        rc_, _, moved = commit(spec, "detached")
        assert rc_ == 0 and moved


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
