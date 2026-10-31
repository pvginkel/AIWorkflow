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
or a gone GitHub origin is skipped. Given `--slice`, plan and run fail on a
pending phase's Target that config.yaml declares and the pod has not cloned,
and on nothing kc cannot place. Plan, after the sync, refuses a slice whose
`slice.md` front matter `needs:` a slice that has not completed. The phase
pointers and the devlock
follow, and the retired spec-tree guard: its removal from the spec repo's git
dir, over real git. The run baseline runs `kc project setup` before its build,
from the repo root under the run loop's setup timeout; setup never decides: a
red or timed-out one is a warning line under a green build and part of a red
build's message. A failure is data — its check, its fact, its fix and the
output it captured — read on stderr as one message, or with `--json` as one
object on stdout, pass or fail, with the notes a pass carries; no profile
checks the session's plugin copy any more. The kc/manifest checks and the rest
of clean-tree are not covered here.

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


def _main(profile, subproc, slice_=None, as_json=False):
    """main() for one profile (and `--slice`, `--json`) with `kc` on PATH and
    a stubbed subprocess: (exit_code, stdout, stderr), exit_code None when it
    passed."""
    stdout, stderr = io.StringIO(), io.StringIO()
    kc_on_path = types.SimpleNamespace(which=lambda name: "/usr/local/bin/kc")
    argv = types.SimpleNamespace(profile=profile, slice=slice_, json=as_json)
    parser = types.SimpleNamespace(
        add_argument=lambda *a, **k: None, parse_args=lambda: argv)
    fake_argparse = types.SimpleNamespace(ArgumentParser=lambda **k: parser)
    with patched(preflight, subprocess=subproc, shutil=kc_on_path,
                 argparse=fake_argparse):
        with contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(stderr):
            try:
                preflight.main()
            except SystemExit as exit_:
                return exit_.code, stdout.getvalue(), stderr.getvalue()
    return None, stdout.getvalue(), stderr.getvalue()


def run_main(profile, subproc, slice_=None):
    """main() as `_main` gives it, as (exit_code, stderr)."""
    code, _, stderr = _main(profile, subproc, slice_)
    return code, stderr


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
              "devlock_lease": None, "push": True, "push_deploys": True}
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


def test_an_untracked_run_lock_is_not_uncommitted_work():
    """The run loop's lock, live or left by a close-out that predates its
    deletion, is no change a pull could clobber: the spec repo still syncs,
    in both profiles, with no second look — quoted paths included."""
    locks = ("?? slices/completed/057_x/run.lock\n"
             "?? \"slices/062 a b/run.lock\"\n")
    for strict in (None, {APP.resolve()}):
        subproc = scripted_subprocess(repo_rules("0\t3", dirty=locks))
        slept = []
        with synced(subproc), patched(preflight, _sleep=slept.append):
            preflight.check_synced(APP, None, strict)
        assert subproc.called("merge", "--ff-only", "@{u}"), strict
        assert slept == [], strict


def test_beside_a_run_lock_any_other_change_is_still_refused():
    """Only the lock is passed over: an untracked file of another name, or a
    tracked run.lock modified, is uncommitted work as before."""
    for dirty, listed in (
            ("?? slices/completed/057_x/run.lock\n?? notes.md\n",
             "by hand.\n?? notes.md\n"),
            (" M slices/057_x/run.lock\n",
             "by hand.\n M slices/057_x/run.lock\n")):
        subproc = scripted_subprocess(repo_rules("0\t3", dirty=dirty))
        with synced(subproc):
            code, message = refused(preflight.check_synced, APP, None)
        assert code == 1 and "uncommitted" in message, dirty
        assert message.endswith(listed), dirty
        assert not subproc.called("merge"), dirty


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
                       "them.\nCommit or stash them, or pull by hand.\n"
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
    """The number the brief names, the folder's name a skill's `<slice>` is
    read as, and its path all find the one folder."""
    with tempfile.TemporaryDirectory() as tmp:
        _, _, cfg = a_slice_layout(tmp, "../Sib")
        folder = cfg.spec_repo / "slices" / "007_widget"
        for given in ("7", "007", "007_widget", str(folder)):
            assert preflight.find_slice(cfg, given) == folder, given


def test_a_slice_that_names_no_folder_fails():
    """Exit 1, naming what was looked for and where."""
    with tempfile.TemporaryDirectory() as tmp:
        app, _, cfg = a_slice_layout(tmp, "../Sib")
        code, message = refused(preflight.strict_repos, app, cfg, "8")
    assert code == 1
    assert "`--slice 8`" in message and "8 or 008" in message
    assert str(cfg.spec_repo) in message and "slices/backlog/" in message


def test_slice_under_triage_is_a_usage_error():
    """`--slice` names the plan whose Targets plan and run check; triage
    reads no plan, so it is refused by argparse (exit 2) before anything
    runs."""
    stderr = io.StringIO()
    argv = ["preflight.py", "--for", "triage", "--slice", "7"]
    with patched(preflight.sys, argv=argv), \
            contextlib.redirect_stderr(stderr):
        try:
            preflight.main()
            raise AssertionError("expected SystemExit")
        except SystemExit as exit_:
            assert exit_.code == 2
    assert ("--slice applies to --for plan and --for run only"
            in stderr.getvalue())


def test_plan_hands_the_sync_its_strict_repos_and_run_hands_it_none():
    """main's wiring: under plan the target and spec repos block, plus what
    the `--slice` plan targets; under run every repo does (None), `--slice`
    or not."""
    with tempfile.TemporaryDirectory() as tmp:
        app, sib, cfg = a_slice_layout(tmp, "../Sib")
        handed = []
        quiet = {name: (lambda *a, **k: None) for name in (
            "check_kc", "check_kc_status", "check_manifest", "check_pointer",
            "remove_spec_tree_guard", "check_phase_pointers",
            "check_devlock", "check_clean_tree", "check_baseline_build")}
        for profile, slice_ in (("plan", "7"), ("plan", None), ("run", None),
                                ("run", "7")):
            with patched(preflight, repo_root=lambda: app,
                         load_config=lambda root: cfg,
                         check_synced=lambda r, c, strict: handed.append(strict),
                         **quiet):
                code, _ = run_main(profile, fake_subprocess(), slice_)
            assert code is None, profile
    both = {app.resolve(), cfg.spec_repo.resolve()}
    assert handed == [both | {sib.resolve()}, both, None, None]


# -- a Target declared but not cloned ----------------------------------------
#
# A repo added to `.kubecoder/config.yaml` while the environment runs is
# cloned at the next pod start; until then a Target naming it passed here and
# the run loop took it for a wrong path.

CLONE_PLAN = """# Slice 007 — the rotator

### P1 — rotated once ✅ DONE
Target: {done}

### P2 — rotate the secrets
Target: {pending}

### P3 — a scratch clone, the loop's to make
Target: github:acme/Widget

### P4 — a component, the plan loop's to name
Target: frontend
"""


def a_cloning_layout(tmp, pending, done="../Sib"):
    """work/App (the target repo), work/Sib beside it, and a spec repo whose
    slice 007 plan has a done phase on `done` and a pending one on
    `pending`. Returns (app, cfg)."""
    work = Path(tmp) / "work"
    app = _checkout(work / "App")
    _checkout(work / "Sib")
    spec = a_spec_repo(work, "007_widget")
    (spec / "slices" / "007_widget" / "plan.md").write_text(
        CLONE_PLAN.format(done=done, pending=pending))
    return app, a_config(spec_repo=spec)


def declared(*dirs):
    """What `run_loop.declared_repo_dirs` answers with `dirs` declared."""
    return lambda: {Path(d).resolve(): f"https://github.com/acme/{Path(d).name}"
                    for d in dirs}


def kc_never_asked():
    raise AssertionError("kc must not be asked")


def kc_down():
    raise ValueError("`kc env describe --output=json` failed (rc=1)")


def cloning_main(profile, app, cfg, slice_, declares):
    """main() with every check but the clone check stubbed out, and kc's
    declared repos answered by `declares`. Returns (exit_code, stderr)."""
    quiet = {name: (lambda *a, **k: None) for name in (
        "check_kc", "check_kc_status", "check_manifest", "check_pointer",
        "remove_spec_tree_guard", "check_phase_pointers", "check_devlock",
        "check_clean_tree", "check_synced", "check_baseline_build")}
    with patched(preflight, repo_root=lambda: app,
                 load_config=lambda root: cfg, **quiet), \
            patched(preflight.run_loop, declared_repo_dirs=declares):
        return run_main(profile, fake_subprocess(), slice_)


def test_a_slice_whose_plan_targets_a_declared_uncloned_repo_fails_plan_and_run():
    """An environment fault (exit 2), naming the phase, the repo and the
    fix; the done phase's Target, declared and missing too, is not named."""
    with tempfile.TemporaryDirectory() as tmp:
        app, cfg = a_cloning_layout(tmp, "../SecretRotator", done="../Gone")
        rotator = app.parent / "SecretRotator"
        for profile in ("plan", "run"):
            code, message = cloning_main(
                profile, app, cfg, "7",
                declared(rotator, app.parent / "Gone"))
            assert code == 2, profile
            assert "declares but has not cloned" in message.splitlines()[0]
            assert ("- phase P2: Target `../SecretRotator` is declared but "
                    "not cloned") in message
            assert (f"git clone https://github.com/acme/SecretRotator "
                    f"{rotator.resolve()}") in message
            assert f"kc project setup` in {rotator.resolve()}" in message
            assert "phase P1" not in message, "a done phase is not checked"


def test_a_missing_target_preflight_cannot_place_passes():
    """Not declared, or kc not answering: the loop names it, as before."""
    with tempfile.TemporaryDirectory() as tmp:
        app, cfg = a_cloning_layout(tmp, "../SecretRotator")
        for declares in (declared(app.parent / "Elsewhere"), kc_down):
            for profile in ("plan", "run"):
                code, message = cloning_main(profile, app, cfg, "7", declares)
                assert code is None, (profile, message)


def test_a_cloned_target_and_a_done_phase_ask_kc_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        app, cfg = a_cloning_layout(tmp, "../Sib", done="../Gone")
        for profile in ("plan", "run"):
            code, message = cloning_main(profile, app, cfg, "7",
                                         kc_never_asked)
            assert code is None, (profile, message)


def test_without_a_slice_the_clone_check_reads_no_plan():
    with tempfile.TemporaryDirectory() as tmp:
        app, cfg = a_cloning_layout(tmp, "../SecretRotator")
        for profile in ("plan", "run"):
            code, message = cloning_main(profile, app, cfg, None,
                                         kc_never_asked)
            assert code is None, (profile, message)


def test_the_clone_check_runs_before_the_tree_and_sync_checks():
    """In run before the clean tree, in plan before the sync: the missing
    repo is the first thing to fix, and no repo is synced for a slice that
    cannot run."""
    run, plan = preflight.PROFILES["run"], preflight.PROFILES["plan"]
    assert run.index("targets_cloned") == run.index("clean_tree") - 1
    assert plan.index("targets_cloned") == plan.index("synced") - 1
    assert "targets_cloned" not in preflight.PROFILES["triage"]


# -- check_ready_to_plan -----------------------------------------------------

def a_needing_layout(tmp, front, *others):
    """A spec repo holding slice 031 in the backlog, whose slice.md front
    matter carries the line `front`, beside the slice folders `others`
    (paths under `slices/`). Returns the config."""
    spec = a_spec_repo(tmp, "backlog/031_widget", *others)
    (spec / "slices" / "backlog" / "031_widget" / "slice.md").write_text(
        f"---\nissue: KC-31\n{front}\n---\n\n# Widget\n\nThe widget.\n")
    return a_config(spec_repo=spec)


def failure_of(fn, *args):
    """Run a check expected to fail; return its Failure."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            fn(*args)
    except preflight.Failure as failure:
        return failure
    raise AssertionError(f"{fn.__name__} passed where it should have failed")


def test_a_slice_that_needs_an_unfinished_slice_is_not_ready_to_plan():
    """Exit 1: each slice `needs:` names that is not under completed/ is
    named with where it is — running, in the backlog, or nowhere — the
    completed one is not, and the fix gives both ways out."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = a_needing_layout(tmp, "needs: [028, 29, 030, 041]",
                               "028_running", "backlog/029_queued",
                               "completed/030_done")
        failure = failure_of(preflight.check_ready_to_plan, cfg, "31")
    assert failure.code == 1 and failure.check == "ready_to_plan"
    assert failure.fact.startswith("Slice 031_widget must follow")
    lines = failure.fact.splitlines()[1:]
    assert lines == [
        "- 028, at slices/028_running, not completed",
        "- 029, at slices/backlog/029_queued, not completed",
        "- 041, under none of slices/, slices/backlog/ or slices/completed/"]
    assert "once each of them has completed" in failure.fix
    assert "take that slice off the `needs:` line" in failure.fix


def test_a_slice_whose_needs_have_all_completed_is_ready_to_plan():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = a_needing_layout(tmp, "needs: 030", "completed/030_done")
        preflight.check_ready_to_plan(cfg, "031")


def test_a_slice_that_needs_nothing_is_ready_to_plan():
    """No `needs:` line, an empty one, one outside the front matter, no
    front matter, no slice.md, no `--slice`: nothing to wait for, though
    028 is pending throughout."""
    with tempfile.TemporaryDirectory() as tmp:
        for front in ("owner: someone", "needs:", "needs: []"):
            cfg = a_needing_layout(Path(tmp) / front.replace(":", ""), front,
                                   "028_running")
            preflight.check_ready_to_plan(cfg, "31")
        slice_md = cfg.spec_repo / "slices" / "backlog" / "031_widget" / "slice.md"
        slice_md.write_text("---\nissue: KC-31\n---\n\nneeds: 028\n")
        preflight.check_ready_to_plan(cfg, "31")
        slice_md.write_text("# Widget\n\nneeds: 028\n")
        preflight.check_ready_to_plan(cfg, "31")
        slice_md.unlink()
        preflight.check_ready_to_plan(cfg, "31")
        preflight.check_ready_to_plan(cfg, None)


def test_a_needs_line_that_names_no_slice_number_fails():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = a_needing_layout(tmp, "needs: 028, auth", "completed/028_done")
        failure = failure_of(preflight.check_ready_to_plan, cfg, "31")
    assert failure.code == 1 and failure.check == "ready_to_plan"
    assert "`auth`, which is not a slice number" in failure.fact
    assert "`needs: 028, 031`" in failure.fix


def test_the_ready_check_runs_under_plan_alone_after_the_sync():
    """After the sync, so a slice completed in another environment reads as
    completed; run and triage never ask it."""
    plan = preflight.PROFILES["plan"]
    assert plan.index("ready_to_plan") > plan.index("synced")
    assert "ready_to_plan" not in preflight.PROFILES["run"]
    assert "ready_to_plan" not in preflight.PROFILES["triage"]


def test_under_json_a_slice_not_ready_to_plan_is_one_failure_object():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = a_needing_layout(tmp, "needs: 028", "028_running")
        quiet = {name: (lambda *a, **k: None) for name in (
            "check_kc", "check_kc_status", "check_manifest", "check_pointer",
            "remove_spec_tree_guard", "check_targets_cloned", "check_synced")}
        with patched(preflight, repo_root=lambda: Path(tmp),
                     load_config=lambda root: cfg, **quiet):
            code, stdout, stderr = _main("plan", fake_subprocess(), "31",
                                         as_json=True)
    report = json.loads(stdout)
    assert code == 1 and stderr == ""
    assert report["result"] == "fail" and report["check"] == "ready_to_plan"
    assert "- 028, at slices/028_running, not completed" in report["fact"]


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

SETUP = ["kc", "project", "setup"]
BUILD = ["kc", "project", "build"]


class kc_verbs:
    """Stands in for the `subprocess` module under the baseline: answers each
    `kc project <verb>` from `answers` by verb — `(rc, stdout, stderr)`, or an
    exception to raise — `(0, "", "")` by default, and records every call's
    argv in `.calls` and its keyword arguments in `.kwargs`."""

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, **answers):
        self.answers = answers
        self.calls = []
        self.kwargs = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        answer = self.answers.get(argv[2], (0, "", ""))
        if isinstance(answer, BaseException):
            raise answer
        return subprocess.CompletedProcess(argv, *answer)


def setup_timed_out(output=None):
    return subprocess.TimeoutExpired(
        SETUP, preflight.run_loop.SETUP_TIMEOUT, output=output)


def baseline(subproc):
    """check_baseline_build in /work/MyApp over `subproc`. Returns
    (exit_code, stdout, stderr) — exit_code None when it passed."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with patched(preflight, subprocess=subproc), \
            contextlib.redirect_stdout(stdout), \
            contextlib.redirect_stderr(stderr):
        try:
            preflight.check_baseline_build(Path("/work/MyApp"))
        except SystemExit as exit_:
            return exit_.code, stdout.getvalue(), stderr.getvalue()
    return None, stdout.getvalue(), stderr.getvalue()


def numbered(name, count):
    return "".join(f"{name} line {n}\n" for n in range(1, count + 1))


def test_a_green_baseline_build_passes_silently():
    subproc = kc_verbs(setup=(0, "root: ok\n", ""), build=(0, "root: ok\n", ""))
    assert baseline(subproc) == (None, "", "")
    assert subproc.calls == [SETUP, BUILD]


def test_setup_runs_from_the_repo_root_before_the_build_under_its_timeout():
    """The run loop's own bound on a hung setup; the build keeps none."""
    subproc = kc_verbs()
    baseline(subproc)
    assert subproc.calls == [SETUP, BUILD]
    setup, build = subproc.kwargs
    assert setup["cwd"] == build["cwd"] == "/work/MyApp"
    assert setup["timeout"] == preflight.run_loop.SETUP_TIMEOUT
    assert setup["capture_output"] and setup["text"]
    assert "timeout" not in build


def test_a_manifest_with_no_build_statement_passes():
    """kc exits 3 (KC-81) when no component has a build statement — nothing
    ran, so there is no baseline to break (Ansible slice 026)."""
    subproc = kc_verbs(build=(
        3, "root: no build statements — skipped\n"
           "ansible: no build statements — skipped\n", ""))
    assert baseline(subproc) == (None, "", "")


def test_a_repo_with_no_setup_and_a_green_build_passes_silently():
    """Exit 3 from setup is a repo that defines none — not red."""
    subproc = kc_verbs(setup=(3, "root: no setup statements — skipped\n", ""))
    assert baseline(subproc) == (None, "", "")
    assert subproc.calls == [SETUP, BUILD]


def test_a_red_setup_under_a_green_build_passes_with_one_warning_line():
    """Setup does not decide, the build does — as in the run loop's
    `_setup_targets`; what setup could not install is the phase gates'."""
    subproc = kc_verbs(setup=(1, "npm ERR! code E404\nnpm ERR! 404 pg\n\n", ""))
    code, stdout, stderr = baseline(subproc)
    assert code is None and stderr == ""
    assert stdout.count("\n") == 1, "one line"
    assert stdout.startswith("warning: ")
    assert "`kc project setup` failed (exit 1)" in stdout
    assert "`kc project build` was green, so the run goes on" in stdout
    assert stdout.rstrip("\n").endswith("(setup's last line: npm ERR! 404 pg)")


def test_a_timed_out_setup_under_a_green_build_passes_with_a_warning():
    """A hung setup is killed at SETUP_TIMEOUT; its partial output arrives
    as bytes, or not at all."""
    timeout = preflight.run_loop.SETUP_TIMEOUT
    for output, last in ((b"resolving deps\nfetching pg\n",
                          " (setup's last line: fetching pg)"),
                         (None, "")):
        subproc = kc_verbs(setup=setup_timed_out(output))
        code, stdout, stderr = baseline(subproc)
        assert code is None and stderr == "", output
        assert subproc.calls == [SETUP, BUILD]
        assert stdout.count("\n") == 1, output
        assert stdout.startswith(
            f"warning: `kc project setup` timed out after {timeout}s, ")
        assert "`kc project build` was green" in stdout
        assert stdout.rstrip("\n").endswith(
            "could not install" + last), stdout


def test_a_red_baseline_build_is_the_projects_to_fix():
    code, stdout, message = baseline(kc_verbs(build=(1, "ansible: FAILED\n", "")))
    assert code == 1 and stdout == ""
    assert message.startswith(
        "Baseline `kc project build` failed — the suite must be green before "
        "a slice runs")
    assert "ansible: FAILED" in message


def test_a_green_setup_under_a_red_build_carries_setups_last_lines():
    """A green setup tells the reader the red is not install state."""
    subproc = kc_verbs(setup=(0, numbered("setup", 30), ""),
                       build=(1, numbered("build", 50), ""))
    code, _, message = baseline(subproc)
    assert code == 1
    prose = message.splitlines()[0]
    assert "ran green before it, so the red is not install state" in prose
    assert "fix setup's own failure first" not in message
    assert "`kc project setup` → GREEN (exit 0):" in message
    assert "setup line 30" in message and "setup line 11" in message
    assert "setup line 10\n" not in message
    assert "`kc project build` → RED (exit 1):" in message
    assert "build line 50" in message and "build line 11" in message
    assert "build line 10\n" not in message
    assert message.index("setup line 30") < message.index("build line 11")


def test_a_red_setup_under_a_red_build_names_setup_as_the_first_fix():
    subproc = kc_verbs(setup=(1, numbered("setup", 30), "npm ERR! 404 pg\n"),
                       build=(1, "TS2307: Cannot find module 'pg'\n", ""))
    code, stdout, message = baseline(subproc)
    assert code == 1 and stdout == ""
    fact, fix = message.splitlines()[:2]
    assert fact.startswith("Baseline `kc project build` failed")
    assert fact.endswith("`kc project setup`, run before it, failed (exit 1).")
    assert fix.startswith("Fix setup's own failure first")
    assert fix.endswith("Then fix the baseline, or narrow the manifest's build list.")
    assert "`kc project setup` → RED (exit 1):" in message
    assert "npm ERR! 404 pg" in message and "setup line 12" in message
    assert "setup line 11\n" not in message
    assert "TS2307: Cannot find module 'pg'" in message
    assert (message.index("npm ERR! 404 pg")
            < message.index("`kc project build` → RED")
            < message.index("TS2307"))


def test_a_timed_out_setup_under_a_red_build_says_so():
    timeout = preflight.run_loop.SETUP_TIMEOUT
    subproc = kc_verbs(setup=setup_timed_out("fetching pg\n"),
                       build=(1, "TS2307: Cannot find module 'pg'\n", ""))
    code, _, message = baseline(subproc)
    assert code == 1
    fact, fix = message.splitlines()[:2]
    assert fact.endswith(
        f"`kc project setup`, run before it, timed out after {timeout}s.")
    assert fix.startswith("Fix setup's own failure first")
    assert f"`kc project setup` → timed out after {timeout}s:" in message
    assert "fetching pg" in message and "TS2307" in message


def test_against_the_real_kc_status():
    """Pins the invocation to the actual CLI rather than only to the stub: in a
    healthy pod the check passes silently. Skipped where `kc` is absent, or
    where the environment really is unhealthy (that is the check working)."""
    if shutil.which("kc") is None:
        return
    if subprocess.run(["kc", "status"], capture_output=True).returncode != 0:
        return
    preflight.check_kc_status()


# -- the output: a failure as data, --json ------------------------------------

def run_json(profile, subproc, slice_=None):
    """main() under --json: (exit_code, the object on stdout, stderr)."""
    code, stdout, stderr = _main(profile, subproc, slice_, as_json=True)
    return code, json.loads(stdout), stderr


def test_a_failure_under_json_is_one_object_on_stdout_and_nothing_on_stderr():
    """The check that failed, the fact it found, the fix and the output it
    captured, each a field a stage renders into an `action` document; the
    exit code is the failure's, as without --json."""
    code, report, stderr = run_json("run", fake_subprocess(1, DAEMON_DOWN))
    assert code == 2 and stderr == "", stderr
    assert report["result"] == "fail" and report["profile"] == "run"
    assert report["code"] == 2 and report["check"] == "kc_status"
    assert "broken control plane" in report["fact"]
    assert report["fix"].startswith("Mend the half")
    assert "connection refused" in report["output"]
    assert report["notes"] == []
    assert preflight.NOTES is None, "a --json run leaves printing as it was"


def test_without_json_the_message_is_the_fact_then_the_fix_then_the_output():
    code, stdout, stderr = _main("run", fake_subprocess(1, DAEMON_DOWN))
    assert code == 2 and stdout == ""
    lines = stderr.splitlines()
    assert "broken control plane" in lines[0]
    assert lines[1].startswith("Mend the half")
    assert "connection refused" in stderr.split(lines[1], 1)[1]


def test_a_dirty_tree_fails_as_clean_tree_with_its_status_as_the_output():
    subproc = fake_subprocess(0, " M app.py\n")
    with patched(preflight, subprocess=subproc), \
            contextlib.redirect_stderr(io.StringIO()):
        try:
            preflight.check_clean_tree(Path("/work/App"))
            raise AssertionError("expected a Failure")
        except preflight.Failure as failure:
            assert failure.code == 1 and failure.check == "clean_tree"
            assert "/work/App has uncommitted changes" in failure.fact
            assert failure.fix.startswith("Commit or stash them")
            assert failure.output == " M app.py"


def triage_stubs(calls, notes=()):
    """The triage profile's checks stubbed: each records its name, and the
    guard's removal makes the notes in `notes` as the real one does."""
    def guard(cfg):
        calls.append("remove_spec_tree_guard")
        for text in notes:
            preflight.note("spec_tree_guard", text, warning=False)
    return {"check_kc": lambda: calls.append("check_kc"),
            "repo_root": lambda: Path("/work/App"),
            "load_config": lambda root: None,
            "check_pointer": lambda cfg, key: calls.append(key),
            "remove_spec_tree_guard": guard}


def test_a_pass_under_json_is_one_object_with_its_notes():
    """A note is printed as its line without --json, and is an entry of the
    object's `notes` with it — never both."""
    removed = "removed the retired spec-tree guard /work/Specs/.git/hooks/pre-commit"
    calls = []
    with patched(preflight, **triage_stubs(calls, [removed])):
        code, report, stderr = run_json("triage", fake_subprocess())
    assert code is None and stderr == ""
    assert report == {"result": "pass", "profile": "triage", "notes": [
        {"check": "spec_tree_guard", "note": removed}]}
    with patched(preflight, **triage_stubs([], [removed])):
        code, stdout, _ = _main("triage", fake_subprocess())
    assert code is None and stdout == removed + "\n"


def test_a_run_pass_under_json_says_what_the_runs_pushes_are():
    """`/dev:run-slice` asks first before a push that deploys while Pilot's
    auto pilot is off, so the run profile's pass says whether the run pushes
    and whether its push deploys; the other profiles' passes do not."""
    for over, said in (({}, {"enabled": True, "deploys": True}),
                       ({"push_deploys": False}, {"enabled": True, "deploys": False}),
                       ({"push": False, "push_deploys": False},
                        {"enabled": False, "deploys": False})):
        cfg = a_config(**over)
        with patched(preflight, run_profile=lambda args, cfg=cfg: cfg):
            code, report, stderr = run_json("run", fake_subprocess())
        assert code is None and stderr == ""
        assert report == {"result": "pass", "profile": "run", "notes": [], "push": said}
    with patched(preflight, run_profile=lambda args: a_config()):
        _, report, _ = run_json("plan", fake_subprocess())
    assert "push" not in report


def test_a_repo_planning_passes_over_is_a_note_of_the_sync_under_json():
    subproc = scripted_subprocess(repo_rules("2\t3", first=[
        (("/work/Sib", "rebase", "@{u}"), CONFLICT)]))
    with patched(preflight, NOTES=[]):
        said = planned(subproc, (APP, SIB, OTHER), strict=(APP,))
        notes = preflight.NOTES
    assert said == "", "under --json nothing is printed as it is made"
    assert [n["check"] for n in notes] == ["synced"], notes
    assert notes[0]["note"].startswith("`Sib` "), notes
    assert "planning goes on" in notes[0]["note"]


def test_no_profile_checks_the_sessions_plugin_copy():
    """The stale-plugin line went with Pilot launching the plugin: no
    profile names a plugin check, and preflight has none to run."""
    for profile, checks in preflight.PROFILES.items():
        assert not any("plugin" in c for c in checks), profile
    assert not hasattr(preflight, "check_plugin_current")


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
