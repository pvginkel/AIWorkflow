"""Tests for preflight's control-plane and origin-sync checks, the optional
pointers, and how all of them are wired into main.

`check_kc_status`: a broken control plane is an *environment* fault (exit 2),
it is checked before the repo is resolved, and triage — which dispatches
nothing — is deliberately exempt. `check_synced` / `sync_roots`: which
checkouts the environment syncs, and what fast-forward, rebase, ahead-only,
dirty, detached, no upstream and a dead remote each do, and the second look a
dirty tree gets. A repo on a run loop's phase branch — live run, bailed run, no
slice folder — is refused before either the sync or the clean-tree check acts
on it. Under plan, only the target, the spec repo and what the `--slice` plan
targets block; any other repo's refusal is a warning line, and a vanished repo
or a gone GitHub origin is skipped. The phase pointers and the devlock
follow, and the retired spec-tree guard: its removal from the spec repo's git
dir, over real git. The kc/manifest/baseline checks and the rest of clean-tree
are not covered here.

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
    repo's. A list of answers is given out one call at a time, its last one
    repeated — a repo that changes between two looks."""

    def __init__(self, rules=()):
        self.rules = [((m,) if isinstance(m, str) else tuple(m), r)
                      for m, r in rules]
        self.calls = []

    def run(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        for tokens, answer in self.rules:
            if argv_has(tokens, argv):
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                return subprocess.CompletedProcess(argv, *answer)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def called(self, *tokens):
        return any(argv_has(tokens, argv) for argv in self.calls)


def run_main(profile, subproc, slice_=None):
    """main() for one profile (and `--slice`) with `kc` on PATH and a stubbed
    subprocess. Returns (exit_code, stderr) — exit_code None when it passed
    silently."""
    stderr = io.StringIO()
    kc_on_path = types.SimpleNamespace(which=lambda name: "/usr/local/bin/kc")
    argv = types.SimpleNamespace(profile=profile, slice=slice_)
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
    repo set is `sync_roots`' business, so no filesystem is touched here —
    and with no real wait: a test that counts the waits patches `_sleep`
    again inside."""
    return patched(preflight, subprocess=subproc,
                   sync_roots=lambda root, cfg: list(roots),
                   _sleep=lambda seconds: None)


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


# -- a dirty tree, looked at twice -------------------------------------------

DIRTY = (0, " M app.py\n", "")
CLEAN = (0, "", "")


def test_a_tree_dirty_for_a_moment_is_synced_on_the_second_look():
    """Another process's pull caught mid-checkout: dirty at the first look,
    clean one wait later — so the repo syncs, in both profiles, on the
    counts of the second look (here it gained a commit: a rebase, not the
    first look's fast-forward)."""
    for strict in (None, {APP.resolve()}):
        subproc = scripted_subprocess(repo_rules("0\t3", first=[
            ("rev-list", [(0, "0\t3", ""), (0, "1\t4", "")]),
            (("status", "--porcelain"), [DIRTY, CLEAN])]))
        slept, out = [], io.StringIO()
        with synced(subproc), patched(preflight, _sleep=slept.append), \
                contextlib.redirect_stdout(out):
            preflight.check_synced(APP, None, strict)
        assert slept == [preflight.DIRTY_RECHECK_WAIT], strict
        assert subproc.called("rebase", "@{u}"), strict
        assert not subproc.called("merge"), strict
        assert out.getvalue() == "", strict


def test_a_tree_the_other_process_brought_level_is_left_alone():
    """Dirty and behind at the first look, level with origin at the second:
    whatever was pulling finished the job, and nothing is left to do."""
    for strict in (None, {APP.resolve()}):
        subproc = scripted_subprocess(repo_rules("0\t3", first=[
            ("rev-list", [(0, "0\t3", ""), (0, "0\t0", "")]),
            (("status", "--porcelain"), DIRTY)]))
        with synced(subproc):
            preflight.check_synced(APP, None, strict)
        assert not subproc.called("merge") and not subproc.called("rebase")


def test_a_tree_still_dirty_under_a_held_index_lock_is_told_to_wait_not_stash():
    """Another git process is working in the repo — its index.lock was there
    at the first look, the second, or both — and "commit or stash" would
    capture its half-applied work. Exit 1 naming the lock, in both profiles;
    the path git answers is relative to the repo."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _checkout(Path(tmp) / "App")
        lock = repo / ".git" / "index.lock"
        looks = ((True, lambda s: None), (True, lambda s: lock.unlink()),
                 (False, lambda s: lock.write_text("")))
        for strict in (None, {repo.resolve()}):
            for held_first, during_wait in looks:
                lock.unlink(missing_ok=True)
                if held_first:
                    lock.write_text("")
                subproc = scripted_subprocess(repo_rules(
                    "0\t3", dirty=" M app.py\n", first=[
                        (("--git-path", "index.lock"),
                         (0, ".git/index.lock\n", ""))]))
                with synced(subproc, roots=(repo,)), \
                        patched(preflight, _sleep=during_wait):
                    code, message = refused(preflight.check_synced, repo,
                                            None, strict)
                assert code == 1
                assert "another git process" in message
                assert str(lock) in message
                assert "so don't" in message and "wait for it to finish" in message
                assert "Commit or stash" not in message
                assert not subproc.called("merge")
                assert not subproc.called("rebase")


def test_a_tree_still_dirty_with_no_index_lock_gets_the_established_refusal():
    """No git process at work, and still dirty after the wait: someone's own
    uncommitted work, refused as it always was — looked at twice first."""
    subproc = scripted_subprocess(repo_rules("0\t3", dirty=" M app.py\n"))
    slept = []
    with synced(subproc), patched(preflight, _sleep=slept.append):
        code, message = refused(preflight.check_synced, APP, None)
    assert code == 1
    assert message == ("`App` (/work/App) is 3 behind origin/main and has "
                       "uncommitted changes — preflight will not pull over "
                       "them. Commit or stash, or pull by hand, then retry.\n"
                       " M app.py\n")
    assert slept == [preflight.DIRTY_RECHECK_WAIT]
    assert sum(argv_has(("rev-list",), argv) for argv in subproc.calls) == 2
    assert sum(argv_has(("status",), argv) for argv in subproc.calls) == 2


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
    and a git dir."""
    spec = Path(tmp) / "Specs"
    for rel in slices:
        (spec / "slices" / rel).mkdir(parents=True)
    (spec / "slices").mkdir(parents=True, exist_ok=True)
    (spec / ".git").mkdir()
    return spec


def on_branch(branch, spec):
    """Every repo answers `branch` to symbolic-ref; nothing else is scripted
    — an upstream included, so a check that reached the sync would fetch."""
    return scripted_subprocess([
        ("symbolic-ref", (0, f"{branch}\n", "")),
    ])


def no_upstream_advice(message):
    return "--set-upstream-to" not in message and "`-u`" not in message


HOLDER = "host: env-b\npid: 4242\nstarted: 2026-09-24T10:00:00+00:00\n"


def test_a_live_runs_phase_branch_names_the_run_and_says_wait():
    """KubeCoder slice 232: the shared spec tree sat on slice 231's phase
    branch while 231 ran, and preflight advised tracking or pushing it —
    advice that changes a live run's branch. Now it names the run (its folder
    and run.lock's holder) and says to wait, and it does so before the
    upstream check: this branch answers one, yet nothing is fetched."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "231_contract_slimming")
        lock = spec / "slices" / "231_contract_slimming" / "run.lock"
        subproc = on_branch("phase/231-P1", spec)
        with held_run_lock(lock, HOLDER), synced(subproc, roots=(spec,)):
            code, message = refused(preflight.check_synced, spec,
                                    a_config(spec_repo=spec))
            still_held = preflight.run_lock_holder(lock)
            note_after = lock.read_text()
    assert code == 1
    assert "`Specs`" in message and "phase/231-P1" in message
    assert "231_contract_slimming" in message
    assert "host: env-b" in message and "pid: 4242" in message
    assert "spec tree's lease" not in message
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
        spec = a_spec_repo(tmp, "231_contract_slimming")
        lock = spec / "slices" / "231_contract_slimming" / "run.lock"
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
        spec = a_spec_repo(tmp, "231_contract_slimming")
        lock = spec / "slices" / "231_contract_slimming" / "run.lock"
        subproc = scripted_subprocess([
            ("symbolic-ref", (0, "phase/231-P3\n", "")),
            (("status", "--porcelain"), (0, " M app.py\n", "")),
        ])
        with held_run_lock(lock, HOLDER), patched(preflight, subprocess=subproc):
            code, message = refused(preflight.check_clean_tree, APP,
                                    a_config(spec_repo=spec))
    assert code == 1
    assert "live" in message and "stash" not in message


# -- planning: the repos that block it, the ones it passes over --------------

SIB = Path("/work/Sib")
OTHER = Path("/work/Other")
CONFLICT = (1, "", "CONFLICT (content): in app.py\n")


def planned(subproc, roots, strict, cfg=None):
    """check_synced under plan over `roots`, the repos in `strict` blocking;
    returns what it printed (it must not bail)."""
    out = io.StringIO()
    with synced(subproc, roots=roots), contextlib.redirect_stdout(out):
        preflight.check_synced(roots[0], cfg, {p.resolve() for p in strict})
    return out.getvalue()


def passed_over(said, name):
    """One warning line for `name`, saying why planning went on."""
    assert said.count("\n") == 1, said
    assert said.startswith(f"warning: `{name}` "), said
    assert "plan targets no part of" in said and "planning goes on" in said
    assert "`/dev:run-slice`'s preflight refuses it" in said


def test_under_plan_a_sibling_whose_rebase_conflicts_is_a_warning_and_the_sync_goes_on():
    """A repo no Target of the slice names cannot hold planning up: its
    refusal becomes one `warning:` line — the refusal's first line and why
    it was passed over, not git's output — and the repos after it sync."""
    subproc = scripted_subprocess(repo_rules("2\t3", first=[
        (("/work/Sib", "rebase", "@{u}"), CONFLICT)]))
    said = planned(subproc, (APP, SIB, OTHER), strict=(APP,))
    passed_over(said, "Sib")
    assert "do not rebase onto origin/main" in said and "CONFLICT" not in said
    assert subproc.called("/work/Sib", "rebase", "--abort")
    assert subproc.called("/work/Other", "rebase", "@{u}")


def test_under_plan_a_sibling_dirty_and_behind_is_a_warning_and_the_sync_goes_on():
    """Typically a sibling another process is pulling, or someone's work in
    progress there — neither is the plan's to settle."""
    subproc = scripted_subprocess(repo_rules("0\t3", first=[
        (("/work/Sib", "status", "--porcelain"), (0, " M x.py\n", ""))]))
    said = planned(subproc, (APP, SIB, OTHER), strict=(APP,))
    passed_over(said, "Sib")
    assert "uncommitted changes" in said and "x.py" not in said
    assert not subproc.called("/work/Sib", "merge")
    assert subproc.called("/work/Other", "merge", "--ff-only", "@{u}")


def test_under_plan_a_sibling_on_a_live_runs_phase_branch_is_a_warning():
    """A run working in a repo the plan does not touch: one line, naming the
    run's lock — the holder's note stays out of it — and nothing fetched."""
    with tempfile.TemporaryDirectory() as tmp:
        spec = a_spec_repo(tmp, "231_contract_slimming")
        lock = spec / "slices" / "231_contract_slimming" / "run.lock"
        subproc = scripted_subprocess(repo_rules("0\t3", first=[
            (("/work/Sib", "symbolic-ref"), (0, "phase/231-P1\n", ""))]))
        with held_run_lock(lock, HOLDER):
            said = planned(subproc, (APP, SIB, OTHER), strict=(APP, spec),
                           cfg=a_config(spec_repo=spec))
    passed_over(said, "Sib")
    assert "phase/231-P1" in said and "run is live" in said
    assert f"({lock} is held)." in said and "pid: 4242" not in said
    assert not subproc.called("/work/Sib", "fetch")
    assert subproc.called("/work/Other", "merge", "--ff-only", "@{u}")


def test_under_plan_the_same_refusal_in_the_target_or_spec_repo_still_fails():
    """The repos planning reads and writes block it — with the run profile's
    code and message, byte for byte."""
    specs = Path("/work/Specs")
    for repo in (APP, specs):
        outcomes = []
        for strict in (None, {APP.resolve(), specs.resolve()}):
            subproc = scripted_subprocess(repo_rules("2\t3", first=[
                ((str(repo), "rebase", "@{u}"), CONFLICT)]))
            with synced(subproc, roots=(APP, specs)):
                outcomes.append(refused(preflight.check_synced, APP, None,
                                        strict))
        assert outcomes[0] == outcomes[1], repo
        assert outcomes[0][0] == 1 and f"`{repo.name}`" in outcomes[0][1]


PLAN = """# Slice 007 — the widget

### P1 — the widget's model ✅ DONE
Target: {target}

### P2 — a malformed repo Target, the plan loop's to name
Target: github:not-a-repo
"""


def a_slice_layout(tmp, target):
    """work/App (the target repo) and work/Sib beside it, and a spec repo
    holding slice 007, whose plan's (done) P1 targets `target`. Returns
    (app, sib, cfg)."""
    work = Path(tmp) / "work"
    app, sib = _checkout(work / "App"), _checkout(work / "Sib")
    spec = a_spec_repo(work, "007_widget")
    (spec / "slices" / "007_widget" / "plan.md").write_text(
        PLAN.format(target=target))
    return app, sib, a_config(spec_repo=spec)


def test_a_slice_whose_plan_targets_a_sibling_makes_that_sibling_block():
    """`--slice`: a sibling a Target names — a done phase's counts too — is
    one the plan may touch, so its refusal fails planning as under run."""
    with tempfile.TemporaryDirectory() as tmp:
        app, sib, cfg = a_slice_layout(tmp, "../Sib")
        strict = preflight.strict_repos(app, cfg, "7")
        assert strict == {app.resolve(), cfg.spec_repo.resolve(),
                          sib.resolve()}
        subproc = scripted_subprocess(repo_rules("2\t3", first=[
            ((str(sib), "rebase", "@{u}"), CONFLICT)]))
        with synced(subproc, roots=(app, sib)):
            code, message = refused(preflight.check_synced, app, cfg, strict)
    assert code == 1 and "`Sib`" in message and "do not rebase" in message


def test_a_slice_whose_plan_targets_a_github_repo_makes_its_scratch_clone_block():
    with tempfile.TemporaryDirectory() as tmp:
        app, sib, cfg = a_slice_layout(tmp, "github:acme/Widget")
        scratch = Path(tmp) / "work" / "scratch"
        clone = _checkout(scratch / "Widget")
        with patched(preflight.github_target, SCRATCH_ROOT=scratch):
            strict = preflight.strict_repos(app, cfg, "7")
        assert strict == {app.resolve(), cfg.spec_repo.resolve(),
                          clone.resolve()}
        subproc = scripted_subprocess(repo_rules("2\t3", first=[
            ((str(clone), "rebase", "@{u}"), CONFLICT)]))
        with synced(subproc, roots=(app, sib, clone)):
            code, message = refused(preflight.check_synced, app, cfg, strict)
    assert code == 1 and "`Widget`" in message


def test_a_slice_whose_plan_targets_a_component_leaves_the_siblings_warned():
    """A `kc project list` component is taken to live in the target repo —
    a component in a sibling is not looked up — so a sibling's refusal is
    still only a warning."""
    with tempfile.TemporaryDirectory() as tmp:
        app, sib, cfg = a_slice_layout(tmp, "frontend")
        strict = preflight.strict_repos(app, cfg, "7")
        assert strict == {app.resolve(), cfg.spec_repo.resolve()}
        subproc = scripted_subprocess(repo_rules("2\t3", first=[
            ((str(sib), "rebase", "@{u}"), CONFLICT)]))
        said = planned(subproc, (app, sib), strict=strict, cfg=cfg)
    passed_over(said, "Sib")


def test_a_slice_number_finds_its_zero_padded_folder_and_a_path_is_taken_as_given():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, cfg = a_slice_layout(tmp, "../Sib")
        folder = cfg.spec_repo / "slices" / "007_widget"
        for given in ("7", "007", str(folder)):
            assert preflight.find_slice(cfg, given) == folder, given


def test_a_slice_that_names_no_folder_fails():
    """Exit 1, naming what was looked for and where."""
    with tempfile.TemporaryDirectory() as tmp:
        app, _, cfg = a_slice_layout(tmp, "../Sib")
        code, message = refused(preflight.strict_repos, app, cfg, "8")
    assert code == 1
    assert "`--slice 8`" in message and "8 or 008" in message
    assert str(cfg.spec_repo) in message and "slices/backlog/" in message


def test_slice_with_another_profile_is_a_usage_error():
    """`--slice` says which repos planning blocks on; no other profile has
    such a set, so it is refused by argparse (exit 2) before anything runs."""
    for profile in ("triage", "run"):
        stderr = io.StringIO()
        argv = ["preflight.py", "--for", profile, "--slice", "7"]
        with patched(preflight.sys, argv=argv), \
                contextlib.redirect_stderr(stderr):
            try:
                preflight.main()
                raise AssertionError("expected SystemExit")
            except SystemExit as exit_:
                assert exit_.code == 2, profile
        assert "--slice applies to --for plan only" in stderr.getvalue()


def test_plan_hands_the_sync_its_strict_repos_and_run_hands_it_none():
    """main's wiring: under plan the target and spec repos block, plus what
    the `--slice` plan targets; under run every repo does (None)."""
    with tempfile.TemporaryDirectory() as tmp:
        app, sib, cfg = a_slice_layout(tmp, "../Sib")
        handed = []
        quiet = {name: (lambda *a, **k: None) for name in (
            "check_kc", "check_kc_status", "check_manifest", "check_pointer",
            "remove_spec_tree_guard", "check_phase_pointers",
            "check_devlock", "check_clean_tree", "check_baseline_build",
            "check_plugin_current")}
        for profile, slice_ in (("plan", "7"), ("plan", None), ("run", None)):
            with patched(preflight, repo_root=lambda: app,
                         load_config=lambda root: cfg,
                         check_synced=lambda r, c, strict: handed.append(strict),
                         **quiet):
                code, _ = run_main(profile, fake_subprocess(), slice_)
            assert code is None, profile
    both = {app.resolve(), cfg.spec_repo.resolve()}
    assert handed == [both | {sib.resolve()}, both, None]


FETCH_HEAD_GONE = (128, "", "error: cannot open '.git/FETCH_HEAD': No such "
                            "file or directory\n")


def test_under_plan_a_repo_that_vanished_mid_fetch_is_skipped_silently():
    """A transient /work dir removed while the sync fetched it: nothing left
    to sync and nothing to say, strict or not. Under run it is the fetch
    failure it always was."""
    with tempfile.TemporaryDirectory() as tmp:
        gone = Path(tmp) / "Gone"  # no longer there by the time it is looked at
        rules = [((str(gone), "fetch"), FETCH_HEAD_GONE)]
        for strict in ((APP,), (APP, gone)):
            subproc = scripted_subprocess(repo_rules("0\t3", first=rules))
            said = planned(subproc, (APP, gone, OTHER), strict=strict)
            assert said == "", strict
            assert subproc.called("/work/Other", "merge", "--ff-only", "@{u}")
        subproc = scripted_subprocess(repo_rules("0\t3", first=rules))
        with synced(subproc, roots=(APP, gone)):
            code, message = refused(preflight.check_synced, APP, None)
    assert code == 2 and "FETCH_HEAD" in message


NOT_FOUND = (128, "", "remote: Repository not found.\nfatal: repository "
                      "'https://github.com/acme/Gone/' not found\n")


def test_under_plan_a_repo_whose_github_origin_is_gone_is_skipped_with_one_warning():
    """The repo was deleted or moved on GitHub — no retry brings it back, so
    planning goes on past it, strict or not, with one line saying so; a
    marked scratch clone's line says how to unmark it. Under run it is the
    exit-2 fetch failure it always was."""
    with tempfile.TemporaryDirectory() as tmp:
        gone = _checkout(Path(tmp) / "Gone")
        rules = [((str(gone), "fetch"), NOT_FOUND)]
        for strict in ((APP,), (APP, gone)):
            subproc = scripted_subprocess(repo_rules("0\t3", first=rules))
            said = planned(subproc, (APP, gone, OTHER), strict=strict)
            assert said.count("\n") == 1, said
            assert said.startswith(f"warning: `Gone` ({gone}) was not synced")
            assert '"Repository not found"' in said
            assert "deleted or moved on GitHub" in said
            assert "--unset" not in said
            assert subproc.called("/work/Other", "merge", "--ff-only", "@{u}")
        marked = [*rules, ((str(gone), "config", "--get",
                            preflight.github_target.MARK_KEY),
                           (0, "acme/Gone\n", ""))]
        said = planned(scripted_subprocess(repo_rules("0\t3", first=marked)),
                       (APP, gone), strict=(APP,))
        assert said.count("\n") == 1
        assert (f"`git -C {gone} config --unset aiworkflow.scratchClone` "
                f"unmarks it") in said
        subproc = scripted_subprocess(repo_rules("0\t3", first=rules))
        with synced(subproc, roots=(APP, gone)):
            code, message = refused(preflight.check_synced, APP, None)
    assert code == 2 and "Repository not found" in message


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
             "load_config", "check_pointer", "remove_spec_tree_guard",
             "check_phase_pointers", "check_devlock", "check_clean_tree",
             "strict_repos", "check_synced", "check_baseline_build",
             "check_plugin_current"]
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


# -- the retired spec-tree guard ---------------------------------------------

@contextlib.contextmanager
def plain_git():
    """Real git, isolated from the machine's config (a global
    `core.hooksPath` would move the hook out from under the tests) and with
    an identity to commit as. Set in os.environ, because the check runs git
    as a subprocess that inherits it."""
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    saved = {k: os.environ.get(k) for k in (*env, "GIT_CEILING_DIRECTORIES")}
    os.environ.update(env)
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


# What 0.9.86–0.9.92 installed, as far as the removal reads it: the marker
# line, a version after it.
OLD_GUARD = ("#!/bin/sh\n# aiworkflow spec-tree guard v1\n"
             "# refuses a commit on a phase branch it was not named for\n"
             "exit 1\n")


def remove_guard(spec):
    """The removal over a real spec repo; returns what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        preflight.remove_spec_tree_guard(a_config(spec_repo=spec))
    return out.getvalue()


def test_the_retired_guard_is_removed_and_said_once():
    """A phase on the spec repo works in a worktree, whose commits run the
    shared git dir's hooks — the guard would refuse every one. The removal
    says so in one line; a second preflight finds nothing to do and is
    silent again."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hook = spec / ".git" / "hooks" / "pre-commit"
        hook.write_text(OLD_GUARD)
        said = remove_guard(spec)
        assert not hook.exists()
        assert said.count("\n") == 1
        assert said.startswith(f"removed the retired spec-tree guard {hook}")
        assert remove_guard(spec) == ""


def test_a_hook_that_is_not_the_guard_is_left_alone():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hook = spec / ".git" / "hooks" / "pre-commit"
        theirs = "#!/bin/sh\nexec lint-staged\n"
        hook.write_text(theirs)
        assert remove_guard(spec) == ""
        assert hook.read_text() == theirs


def test_no_hook_and_no_git_repo_are_nothing_to_do():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        (spec / ".git" / "hooks" / "pre-commit").unlink(missing_ok=True)
        assert remove_guard(spec) == ""
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = Path(tmp) / "Specs"
        spec.mkdir()
        os.environ["GIT_CEILING_DIRECTORIES"] = tmp
        assert remove_guard(spec) == ""
    assert remove_guard(None) == ""


def test_the_guard_is_removed_where_core_hookspath_points():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        spec = a_git_spec_repo(tmp)
        hooks = Path(tmp) / "shared-hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text(OLD_GUARD)
        subprocess.run(["git", "-C", str(spec), "config", "core.hooksPath",
                        str(hooks)], check=True)
        remove_guard(spec)
        assert not (hooks / "pre-commit").exists()
        # relative: to the repo, where git runs its hooks
        (spec / "githooks").mkdir()
        (spec / "githooks" / "pre-commit").write_text(OLD_GUARD)
        subprocess.run(["git", "-C", str(spec), "config", "core.hooksPath",
                        "githooks"], check=True)
        remove_guard(spec)
        assert not (spec / "githooks" / "pre-commit").exists()


def test_every_profile_removes_the_guard():
    """Triage too: it commits into the spec repo like every other command."""
    for profile in ("triage", "plan", "run"):
        assert "spec_tree_guard" in preflight.PROFILES[profile], profile


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
