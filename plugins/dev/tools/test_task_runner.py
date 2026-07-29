"""Tests for task_runner.Runner — the bounded task loop as a state machine.

Sessions, git, kc's project list, and the deterministic test gate are faked:
each test scripts the sequence of (role, outcome) verdicts it expects the
runner to request — plus the gate's green/red sequence — and asserts on
transitions, caps, state.json, and bail-outs. No kc session is created, no
claude process is spawned, and no real suite runs.

Run: `python3 plugins/dev/tools/test_task_runner.py` or via pytest.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location(
    "task_runner", Path(__file__).resolve().parent / "task_runner.py"
)
task_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(task_runner)
Runner = task_runner.Runner
Bailout = task_runner.Bailout

# The runner reads the component set from `kc project list` in run(). The suite
# has no kc, so that seam is stubbed with a single component whose cwd is the
# repo root — every session the loop would spawn is faked anyway.
PROJECT = "app"
task_runner.load_project_dirs = lambda cwd: {PROJECT: Path(cwd)}


class FakeGit:
    """Answers the git queries the runner makes; records mutations."""

    def __init__(self):
        self.calls = []
        self.branches = set()
        self.head = "abc123"
        self.diff_files = ""  # what `diff --name-only` reports

    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "main"
        if args[0] == "diff" and "--name-only" in args:
            return self.diff_files
        if args[0] == "rev-parse":
            return self.head
        if args[0] == "merge-base":
            return "base123"
        if args[0] == "status":
            return ""
        if args[0] == "branch" and args[1] == "--list":
            return args[2] if args[2] in self.branches else ""
        if args[0] == "checkout" and args[1] == "-b":
            self.branches.add(args[2])
            return ""
        if args[0] == "branch" and args[1] == "-D":
            self.branches.discard(args[2])
            return ""
        return ""

    def mutations(self, verb):
        return [c for c in self.calls if c[0] == verb]


class ScriptedRunner(Runner):
    """Runner with _spawn replaced by a script of (role, verdict) steps and
    the test gate replaced by a scripted green/red sequence (default green
    once the sequence is exhausted)."""

    def __init__(self, slice_dir, script, resume=False, gates=None):
        super().__init__(Path(slice_dir), resume=resume)
        self.script = list(script)
        self.spawned = []
        self.prompts = []
        self.gates = list(gates or [])
        self.gate_calls = []
        self.fake_git = FakeGit()
        self.git = self.fake_git

    def _run_gate(self, task_id, ts, task_dir, project):
        ts["gate_runs"] += 1
        green = self.gates.pop(0) if self.gates else True
        self.gate_calls.append((task_id, green))
        log_path = task_dir / f"gate_r{ts['gate_runs']}.log"
        if green:
            ts["gate_green_commit"] = self.git("rev-parse", "HEAD")
            ts["gate_green_log"] = str(log_path)
        self._record(task_id, "gate", ts["gate_runs"],
                     "green" if green else "red", "", None, 0)
        return green, log_path

    def _spawn(self, role, prompt, cwd, verdict_path, task_id, round_,
               agent=None, model=None, display=None):
        # Mirror the real _spawn's reattach consumption so resume tests
        # exercise the same record lifecycle.
        prompt, resume_session = self._resolve_reattach(
            role, task_id, prompt, Path(verdict_path), "[t]")
        assert self.script, f"unexpected extra spawn: {role} (task {task_id})"
        want_role, verdict = self.script.pop(0)
        self.prompts.append((role, prompt))
        assert role == want_role, (
            f"expected spawn of {want_role}, runner asked for {role} "
            f"(task {task_id}, round {round_})"
        )
        self.spawned.append((role, task_id, round_, verdict["outcome"],
                             resume_session,
                             model or task_runner.MODELS.get(role)))
        self._record(task_id, role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1)
        return verdict, "sess-test"


class SpawningRunner(ScriptedRunner):
    """ScriptedRunner with the REAL _spawn — `run_kc_session` is faked instead,
    so everything inside _spawn (verdict reading, nudges, the session-limit
    wait) is exercised. A script step is the usual (role, verdict dict), or
    (role, text) for a session that produced only that text and no verdict."""

    def __init__(self, slice_dir, script, **kw):
        super().__init__(slice_dir, script, **kw)
        self.sleeps = []
        self.sessions = []
        self.session_prompts = []
        self._pending = None

    def _sleep(self, seconds):
        self.sleeps.append(seconds)

    def _spawn(self, role, prompt, cwd, verdict_path, task_id, round_,
               agent=None, model=None, display=None):
        self._pending = (role, Path(verdict_path))
        verdict, session = Runner._spawn(
            self, role, prompt, cwd, Path(verdict_path), task_id, round_,
            agent=agent, model=model, display=display)
        self.prompts.append((role, prompt))
        self.spawned.append((role, task_id, round_, verdict["outcome"], None,
                             model or task_runner.MODELS.get(role)))
        return verdict, session

    def run_kc_session(self, prompt, cwd, timeout, agent=None, model=None,
                       resume_session=None, extra_env=None, progress=None,
                       on_session=None):
        role, verdict_path = self._pending
        assert self.script, f"unexpected extra session: {role}"
        want_role, payload = self.script.pop(0)
        assert role == want_role, (
            f"expected a {want_role} session, runner ran {role}")
        self.sessions.append((role, payload))
        self.session_prompts.append((role, prompt))
        result = task_runner.SessionResult()
        result.session_id = f"sess-{len(self.sessions)}"
        if on_session:
            on_session(result.session_id)
        if payload is TIMED_OUT:
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, str):
            result.result_text = payload
            return 1, result
        verdict_path.write_text(json.dumps(payload))
        result.result_text = payload.get("summary", "")
        return 0, result


SESSION_LIMIT_TEXT = ("You've hit your session limit · resets 10:10pm "
                      "(Europe/Amsterdam)")
TIMED_OUT = object()   # a script step whose session never returns


def make_slice(tmp, tasks=("01_first",), project=PROJECT, grade=None):
    slice_dir = Path(tmp) / "074_test_slice"
    (slice_dir / "tasks").mkdir(parents=True)
    (slice_dir / "slice.md").write_text("# test slice\n")
    (slice_dir / "acceptance_criteria.json").write_text('{"criteria": []}\n')
    for name in tasks:
        tdir = slice_dir / "tasks" / name
        tdir.mkdir()
        meta = {
            "id": name.split("_")[0], "slug": name.split("_", 1)[1], "project": project,
            "title": f"task {name}", "summary": "test task",
        }
        if grade:
            meta["grade"] = grade
        (tdir / "task.json").write_text(json.dumps(meta))
        (tdir / "plan.md").write_text("plan\n")
    return slice_dir


def run_to_exit(runner):
    try:
        runner.run()
    except SystemExit as e:
        return e.code
    raise AssertionError("runner.run() did not exit")


class patched:
    """Swap module attributes for the duration of a `with` block — the tests
    run under pytest and standalone, so no fixtures."""

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


def ledger_entry(id_="G-001", status="OK", file="app/src/store.py",
                 line=42, repaired=False):
    """One entry as grounding_check.py's --json reports it."""
    return {"id": id_, "claim": "a claim", "file": file, "cited_line": line,
            "cited_end": line, "anchor": "ANCHOR", "status": status,
            "new_line": None, "repaired": repaired}


def ledger_report(entries=(), *, legacy=False, summary=None):
    """A grounding_check.py --json report (the runner's integration contract)."""
    if legacy:
        return {"legacy": True, "stamp": None, "entries": [], "tier": 0,
                "summary": "grounding: legacy ledger — no mechanical check"}
    return {
        "legacy": False, "stamp": {"MyApp": "1a2b3c4d5e6f7890"},
        "entries": list(entries), "tier": 0,
        "summary": summary or ("grounding: verified at MyApp@1a2b3c4d5e6f "
                               "(0 commits since); 2 entries cited by task 01"),
    }


V = {
    "writer_done": ("code-writer", {"outcome": "done", "summary": "built"}),
    "fixer_clean": ("test-fixer", {"outcome": "clean", "summary": "fixed"}),
    "fixer_issues": ("test-fixer", {"outcome": "issues", "summary": "3 fails"}),
    "review_signoff": ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
    "review_issues": ("code-reviewer", {"outcome": "issues", "summary": "gaps"}),
    "verify_clean": ("test-agent", {"outcome": "clean", "summary": "all green"}),
    "checkpoint": ("consult", {"outcome": "proceed", "summary": "holds"}),
}


def test_happy_path_two_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "02_second"))
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["phase"] == "done"
        assert state["tasks"]["01_first"]["status"] == "merged"
        assert state["tasks"]["02_second"]["status"] == "merged"
        # the checkpoint judges the REMAINING breakdown: it fires after task
        # 01 and is skipped after the final task
        assert sum(1 for role, *_ in r.spawned if role == "consult") == 1
        # a green gate spawns NO session and the merge trusts the verified
        # commit: exactly one gate run per task, no test-fixer anywhere
        assert r.gate_calls == [("01_first", True), ("02_second", True)]
        assert not any(role == "test-fixer" for role, *_ in r.spawned)
        merges = r.fake_git.mutations("merge")
        assert len(merges) == 2 and all("--ff-only" in m for m in merges)
        assert not (slice_dir / "bailout.json").exists()


def test_reviewer_dispatch_states_the_green_gate():
    """The reviewer is told tests and lints already pass, with the commit and the
    log backing it, so it does not re-run the suite the runner just ran."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "code-reviewer")
        assert "ran GREEN on this exact commit" in prompt
        assert r.fake_git.head[:12] in prompt
        assert "gate_r1.log" in prompt
        assert f"kc project test --project {PROJECT}" in prompt
        assert "Do not re-run the suite or the linter" in prompt
        # but targeted probing stays explicitly open — the gate says the tests
        # pass, never that they are any good
        assert "vacuous" in prompt


def test_gate_line_never_claims_a_stale_green():
    """A green recorded against a DIFFERENT commit is not evidence about this one:
    the dispatch says unverified rather than passing on a stale pass."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])

        green = {"gate_green_commit": "deadbeefcafe0", "gate_green_log": "/g/gate_r1.log"}
        assert "ran GREEN" in r._gate_line(green, "deadbeefcafe0", PROJECT)
        # HEAD moved past the green run
        assert "no green run recorded" in r._gate_line(green, "0ther000head0", PROJECT)
        # gate never ran, and the pre-gate_green_log state shape
        assert "no green run recorded" in r._gate_line({}, "abc123", PROJECT)
        assert "no green run recorded" in r._gate_line(
            {"gate_green_commit": "abc123"}, "abc123", PROJECT)


def test_red_gate_spawns_fixer_then_confirms_green():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["fixer_clean"], V["review_signoff"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[False, True])
        assert run_to_exit(r) == 0
        assert not r.script
        # the fixer's `clean` was confirmed by a gate re-run, not trusted
        assert r.gate_calls == [("01_first", False), ("01_first", True)]
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["test_rounds"] == 1


def test_fixer_escalation_routes_fix_to_fresh_writer():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["fixer_issues"], V["writer_done"],
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[False, True])
        assert run_to_exit(r) == 0
        # the escalation fix round is a FRESH session (never a resume) whose
        # prompt carries the task identity it can no longer inherit
        fix_spawn = r.spawned[2]
        assert fix_spawn[0] == "code-writer" and fix_spawn[4] is None
        fix_prompt = r.prompts[2][1]
        assert "01_first" in fix_prompt and "test_results_r1.md" in fix_prompt
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["test_rounds"] == 1


def test_grade_routes_initial_writer_round_only():
    """A graded task runs its FIRST writer round on the grade's model; every
    later writer round and the reviewer stay on the default. A Fable round 1
    gets no origin note — the redo license is Sonnet-specific."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, grade="gnarly")
        script = [V["writer_done"], V["review_issues"], V["writer_done"],
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        writers = [s for s in r.spawned if s[0] == "code-writer"]
        assert writers[0][5] == "fable"
        assert writers[1][5] == "opus"
        reviewers = [s for s in r.spawned if s[0] == "code-reviewer"]
        assert all(s[5] == "opus" for s in reviewers)
        fix_prompt = [p for role, p in r.prompts if role == "code-writer"][1]
        assert "Round 1 of this task" not in fix_prompt


def test_mechanical_grade_routes_round_one_to_sonnet_with_origin_note():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, grade="mechanical")
        script = [V["writer_done"], V["review_issues"], V["writer_done"],
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        writers = [s for s in r.spawned if s[0] == "code-writer"]
        assert [w[5] for w in writers] == ["sonnet", "opus"]
        fix_prompt = [p for role, p in r.prompts if role == "code-writer"][1]
        assert "graded mechanical and ran on Sonnet" in fix_prompt


def test_ungraded_task_runs_default_model_without_origin_note():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_issues"], V["writer_done"],
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        writers = [s for s in r.spawned if s[0] == "code-writer"]
        assert [w[5] for w in writers] == ["opus", "opus"]
        fix_prompt = [p for role, p in r.prompts if role == "code-writer"][1]
        assert "Round 1 of this task" not in fix_prompt


def test_writer_dispatch_carries_the_grounding_trust_line():
    """The initial dispatch runs the drift checker scoped to this task's plan
    citations and states the result as fact, so the writer re-derives nothing
    the ledger already establishes."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        calls = []

        def fake_check(sdir, *, task=None, repair=False, prune=False):
            calls.append((Path(sdir).name, task, repair))
            return ledger_report([ledger_entry("G-007")])

        script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner, run_check=fake_check):
            assert run_to_exit(r) == 0
        # scoped to the task (--task NN) and repairing, exactly once
        assert calls == [("074_test_slice", "01", True)]
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "verified at MyApp@1a2b3c4d5e6f;" in prompt
        assert "Treat cited entries as verified fact" in prompt
        assert "0 commits since" in prompt, "the checker's own summary rides along"


def test_writer_dispatch_names_drifted_entries_and_does_not_bail():
    """MISSING/GONE at dispatch scopes the writer's distrust to exactly those
    entries — it never stops the task (tier-2 escalation is preflight's job)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        def fake_check(sdir, *, task=None, repair=False, prune=False):
            return ledger_report([
                ledger_entry("G-001"),
                ledger_entry("G-012", status="MISSING",
                             file="app/src/env.py"),
                ledger_entry("G-013", status="GONE", file="lib/gone.go"),
            ])

        script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner, run_check=fake_check):
            assert run_to_exit(r) == 0
        assert not (slice_dir / "bailout.json").exists()
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert ("G-012 (app/src/env.py, MISSING), "
                "G-013 (lib/gone.go, GONE)") in prompt
        assert "Treat exactly those as unverified" in prompt
        assert "Treat cited entries as verified fact" not in prompt


def test_unreportable_or_legacy_ledger_falls_back_to_the_unverified_line():
    """A pre-ledger grounding.md and a checker that produced no report at all
    are the same dispatch-time fact: no mechanical check ran."""
    for fake in (lambda *a, **kw: ledger_report(legacy=True),
                 lambda *a, **kw: None):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir = make_slice(tmp)
            script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
            r = ScriptedRunner(slice_dir, script)
            with patched(task_runner, run_check=fake):
                assert run_to_exit(r) == 0
            prompt = next(p for role, p in r.prompts if role == "code-writer")
            assert "predates the ledger format" in prompt
            assert "Deterministic fact from the runner" not in prompt


def test_repaired_ledger_is_committed_and_the_check_runs_once_per_task():
    """`--repair` rewrote line numbers → the runner commits the ledger by name
    in the specs repo. A second initial dispatch (the blocked-writer retry)
    reuses the same fact: one check, one commit."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        checks, commits = [], []

        def fake_check(sdir, *, task=None, repair=False, prune=False):
            checks.append(task)
            return ledger_report([ledger_entry("G-002", status="MOVED",
                                               repaired=True)])

        def fake_commit(sdir, message):
            commits.append((Path(sdir).name, message))
            return True

        script = [
            ("code-writer", {"outcome": "blocked", "summary": "stuck"}),
            ("consult", {"outcome": "retry", "summary": "worth one more"}),
            V["writer_done"], V["review_signoff"], V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner, run_check=fake_check,
                     commit_ledger=fake_commit):
            assert run_to_exit(r) == 0
        assert checks == ["01"], "the checker runs once per task, not per round"
        assert commits == [("074_test_slice",
                            "grounding: repair drifted citations "
                            "(task 01 dispatch)")]


def test_unrepaired_ledger_is_not_committed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        commits = []
        script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(
            task_runner,
            run_check=lambda *a, **kw: ledger_report(
                [ledger_entry("G-001"), ledger_entry("G-002", status="MISSING")]),
            commit_ledger=lambda sdir, message: commits.append(message),
        ):
            assert run_to_exit(r) == 0
        assert commits == [], "nothing was rewritten, so nothing may be committed"


def test_fix_rounds_carry_no_grounding_freshness_line():
    """Only the initial implementation dispatch carries the line: a fix round's
    contract is to re-open the sources its fixes touch."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_issues"], V["writer_done"],
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner,
                     run_check=lambda *a, **kw: ledger_report(
                         [ledger_entry("G-001")])):
            assert run_to_exit(r) == 0
        writer_prompts = [p for role, p in r.prompts if role == "code-writer"]
        assert "Treat cited entries as verified fact" in writer_prompts[0]
        assert "Deterministic fact from the runner" not in writer_prompts[1]


def test_checkpoint_gets_the_whole_ledger_drift_paragraph():
    """After a merge the checkpoint consult is handed the checker's reading of
    the WHOLE ledger (no --repair) — which cited sources the merge moved is
    exactly what decides whether the remaining breakdown still holds."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "02_second"))
        calls = []

        def fake_check(sdir, *, task=None, repair=False, prune=False):
            calls.append((task, repair))
            if task is None:
                return ledger_report(
                    [ledger_entry("G-001"),
                     ledger_entry("G-004", status="MOVED",
                                  file="app/src/sync.py", line=88),
                     ledger_entry("G-009", status="GONE", file="lib/old.go")],
                    summary="grounding: verified at MyApp@1a2b3c4d5e6f "
                            "(3 commits since); 9 entries: 7 OK, 1 MOVED, 1 GONE")
            return ledger_report([ledger_entry("G-001")])

        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner, run_check=fake_check):
            assert run_to_exit(r) == 0
        assert (None, False) in calls, "the checkpoint check never repairs"
        checkpoint = next(p for role, p in r.prompts if role == "consult")
        assert "Deterministic drift input for the remaining tasks:" in checkpoint
        assert "1 MOVED, 1 GONE" in checkpoint
        assert "G-004 MOVED  app/src/sync.py:88" in checkpoint
        assert "G-009 GONE  lib/old.go" in checkpoint
        assert "G-001" not in checkpoint, "OK entries are not drift"


def test_checkpoint_drift_paragraph_is_omitted_when_the_checker_says_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "02_second"))
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        with patched(task_runner, run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 0
        checkpoint = next(p for role, p in r.prompts if role == "consult")
        assert "Deterministic drift input" not in checkpoint


def test_grounding_line_shapes():
    """The line-shape selector itself: no report / legacy → unverified; any
    MISSING or GONE → the drift shape; otherwise the trust shape (a repaired
    MOVED is not drift the writer must re-check — the line numbers are fixed)."""
    line = task_runner.grounding_line
    assert "predates the ledger format" in line(None)
    assert "predates the ledger format" in line(ledger_report(legacy=True))
    trust = line(ledger_report([ledger_entry("G-001"),
                                ledger_entry("G-002", status="MOVED",
                                             repaired=True)]))
    assert "Treat cited entries as verified fact" in trust
    drift = line(ledger_report([ledger_entry("G-005", status="GONE")]))
    assert "G-005 (app/src/store.py, GONE)" in drift


def test_fix_limit_consult_proceed_to_review():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            V["fixer_issues"], V["writer_done"],    # round 1 + fix
            V["fixer_issues"], V["writer_done"],    # round 2 + fix
            V["fixer_issues"],                      # round 3 → the cap
            ("consult", {"outcome": "proceed_to_review", "summary": "close"}),
            V["review_signoff"], V["verify_clean"],
        ]
        # four red gates (initial + one per fix); the merge gate re-runs
        # because HEAD was never verified green, and lands green
        r = ScriptedRunner(slice_dir, script, gates=[False] * 4)
        assert run_to_exit(r) == 0
        assert not r.script
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["test_rounds"] == 3
        assert r.gate_calls[-1] == ("01_first", True)  # the merge re-check


def test_merge_gate_blocks_red():
    """A red gate can stall a task but never ship: signoff or not, the merge
    re-runs the gate when HEAD is unverified and bails on red."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            V["fixer_issues"], V["writer_done"],
            V["fixer_issues"], V["writer_done"],
            V["fixer_issues"],
            ("consult", {"outcome": "proceed_to_review", "summary": "go"}),
            V["review_signoff"],
        ]
        r = ScriptedRunner(slice_dir, script, gates=[False] * 5)
        assert run_to_exit(r) == 3
        assert not r.script
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "gate_red"
        assert bail["task"] == "01_first"


REVIEW_ISSUE_ROUND = [V["review_issues"], V["writer_done"]]


def test_post_review_fix_red_gate_gets_one_fixer_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"],
                  V["review_issues"], V["writer_done"],   # review round 1 + fix
                  V["fixer_clean"],                       # post-fix gate was red
                  V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[True, False, True])
        assert run_to_exit(r) == 0
        assert not r.script
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["test_rounds"] == 1 and ts["review_rounds"] == 2
        # last gate green verified HEAD, so the merge did not re-run it
        assert len(r.gate_calls) == 3


def test_review_funding_consult_merges_and_cards():
    """From round 2 on, an `issues` verdict goes to a funding consult BEFORE
    any writer round is spent. `merge` ends the loop with the findings carded
    — no writer round, no further review."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND,                    # round 1: fix is automatic
            V["review_issues"],                     # round 2 → funding consult
            ("consult", {"outcome": "merge", "summary": "advisory only"}),
            V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["status"] == "merged"
        assert ts["review_rounds"] == 2 and ts["writer_rounds"] == 2
        assert len(state["flagged_findings"]) == 1
        flagged = state["flagged_findings"][0]
        assert flagged["task"] == "01_first"
        assert flagged["review"].endswith("code_review_r2.md")
        fund = next(p for role, p in r.prompts
                    if role == "consult" and "funding bar" in p)
        assert "Review round 2" in fund and "fix_round" in fund
        # round 2, no prose bump → the blocking bar, and no prose fact
        assert "harm the product" in fund
        assert "touched no production code" not in fund


def test_review_funding_consult_can_fund_a_fix_round():
    """`fix_round` spends a writer round; the NEXT review round verifies the
    fix — a signoff there merges clean, nothing flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND,                    # round 1: fix is automatic
            V["review_issues"],                     # round 2 → funding consult
            ("consult", {"outcome": "fix_round", "summary": "real breakage"}),
            V["writer_done"],
            V["review_signoff"],                    # round 3 confirms the fix
            V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["status"] == "merged"
        assert ts["review_rounds"] == 3 and ts["writer_rounds"] == 3
        # a reviewer saw the funded fix, so this is NOT a flagged merge
        assert state["flagged_findings"] == []


def test_review_funding_bar_rises_then_budget_forces_merge():
    """The bar the consult is handed escalates per round (blocking →
    Blocker-grade → critical-only), and at the backstop cap the fund option
    disappears: a consult that keeps funding still terminates."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        fund = ("consult", {"outcome": "fix_round", "summary": "keep going"})
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND,                     # round 1: automatic
            V["review_issues"], fund, V["writer_done"],   # round 2
            V["review_issues"], fund, V["writer_done"],   # round 3
            V["review_issues"], fund, V["writer_done"],   # round 4
            V["review_issues"],                      # round 5 = the backstop
            ("consult", {"outcome": "merge", "summary": "budget spent"}),
            V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["review_rounds"] == 5 and ts["writer_rounds"] == 5
        assert len(state["flagged_findings"]) == 1
        # single-task slice → no checkpoint consult; all consults are funding
        consults = [p for role, p in r.prompts if role == "consult"]
        assert len(consults) == 4
        assert "harm the product" in consults[0]       # round-2 bar
        assert "Blocker-grade" in consults[1]          # round-3 bar
        assert "`critical` verdict" in consults[2]     # round-4 bar
        assert "exhausted" in consults[3] and "fix_round" not in consults[3], (
            "at the backstop cap the fund option must be withheld, or the "
            "consult could keep buying rounds forever"
        )


def test_prose_only_fix_range_bumps_the_bar():
    """A fix range that touched no production code (tests and docs only) is
    stated to the consult as a deterministic fact and applies the next
    round's bar a step early — the slice 099 task 03 shape."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        class MovingHeadRunner(ScriptedRunner):
            def _spawn(self, role, *a, **kw):
                out = super()._spawn(role, *a, **kw)
                if role == "code-writer":
                    self.fake_git.head = f"h{len(self.spawned)}"
                return out

        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND,                    # round 1: fix is automatic
            V["review_issues"],                     # round 2 → funding consult
            ("consult", {"outcome": "merge", "summary": "prose convergence"}),
            V["verify_clean"],
        ]
        r = MovingHeadRunner(slice_dir, script)
        r.fake_git.diff_files = "app/tests/test_x.py\ndocs/topic.md"
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        fund = next(p for role, p in r.prompts
                    if role == "consult" and "funding bar" in p)
        assert "touched no production code" in fund
        assert "Blocker-grade" in fund, "round 2 must be judged at the round-3 bar"


def test_production_paths_classification():
    """Tests, markdown, docs/ and manual/ trees, and Go test twins are
    non-production; everything else — including docstring-only code edits —
    counts as production."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])
        r.fake_git.diff_files = "\n".join([
            "app/src/store.py",
            "app/tests/test_store.py",
            "lib/internal/sync/sync_test.go",
            "docs/conventions/task-workflow.md",
            "manual/docs/reference/config.md",
            "README.md",
        ])
        assert r._production_paths("a..b") == ["app/src/store.py"]
        r.fake_git.diff_files = "app/tests/test_store.py"
        assert r._production_paths("a..b") == []


def test_missing_task_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [("code-writer",
                   {"outcome": "missing-task",
                    "summary": "needs a seeding endpoint elsewhere"})]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing-task"
        assert bail["task"] == "01_first"


def test_findings_bail_then_resume_runs_new_task():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"],
                  ("test-agent", {"outcome": "findings", "summary": "2 fails"}),
                  ("consult", {"outcome": "fix_tasks",
                               "summary": "real regressions"})]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "test_findings"
        assert (slice_dir / "test_findings.md").exists()

        # orchestrator authors a fix task, then relaunches with --resume
        fix = slice_dir / "tasks" / "02_fix_findings"
        fix.mkdir()
        (fix / "task.json").write_text(json.dumps(
            {"id": "02", "slug": "fix_findings", "project": PROJECT,
             "title": "fix findings", "summary": "fix"}))
        script2 = [V["writer_done"], V["review_signoff"],
                   V["verify_clean"]]
        r2 = ScriptedRunner(slice_dir, script2, resume=True)
        assert run_to_exit(r2) == 0
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["verification_rounds"] == 2
        assert state["tasks"]["01_first"]["status"] == "merged"
        # task 01 was NOT re-run: writer/review/verify (final-task
        # checkpoint skipped)
        assert len(r2.spawned) == 3


def test_verification_findings_proceed_flagged_completes():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"],
                  ("test-agent", {"outcome": "findings",
                                  "summary": "one dormant residual"}),
                  ("consult", {"outcome": "proceed_flagged",
                               "summary": "pre-existing, config-gated"})]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["phase"] == "done"
        assert len(state["flagged_findings"]) == 1
        flagged = state["flagged_findings"][0]
        assert flagged["task"] is None
        assert flagged["review"].endswith("test_findings.md")
        assert not (slice_dir / "bailout.json").exists()


def test_verification_round_cap_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"],
                  ("test-agent", {"outcome": "findings", "summary": "fails"}),
                  ("consult", {"outcome": "fix_tasks", "summary": "blocks"})]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 3
        # pretend three verification rounds already happened
        state = json.loads((slice_dir / "state.json").read_text())
        state["verification_rounds"] = 3
        (slice_dir / "state.json").write_text(json.dumps(state))
        r2 = ScriptedRunner(slice_dir, [], resume=True)
        assert run_to_exit(r2) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "verification_limit"


def test_checkpoint_amend_picks_up_inserted_task():
    """The checkpoint after a non-final task can amend the remaining
    breakdown; after the slice's final task it is skipped entirely (it has
    no remaining breakdown to judge — and 21/21 final-task checkpoints in
    the measured corpus chose `proceed`)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "02_second"))

        inserted = {"done": False}

        class AmendingRunner(ScriptedRunner):
            def _spawn(self, role, *a, **kw):
                if role == "consult" and not inserted["done"]:
                    inserted["done"] = True
                    new = slice_dir / "tasks" / "03_inserted"
                    new.mkdir()
                    (new / "task.json").write_text(json.dumps(
                        {"id": "03", "slug": "inserted",
                         "project": PROJECT, "title": "inserted",
                         "summary": "added by checkpoint"}))
                return super()._spawn(role, *a, **kw)

        script = [
            V["writer_done"], V["review_signoff"],
            ("consult", {"outcome": "amend", "summary": "added a task"}),
            V["writer_done"], V["review_signoff"],
            ("consult", {"outcome": "proceed", "summary": "holds"}),
            V["writer_done"], V["review_signoff"],   # 03: final → no checkpoint
            V["verify_clean"],
        ]
        r = AmendingRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["03_inserted"]["status"] == "merged"


def test_letter_suffix_inserts_between_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "01a_inserted",
                                           "02_second"))
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        order = [s[1] for s in r.spawned if s[0] == "code-writer"]
        assert order == ["01_first", "01a_inserted", "02_second"]


def test_writer_leftovers_nudge_then_bail():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [V["writer_done"]])
        nudges = []
        r._nudge = lambda prompt, cwd, session_id, label: nudges.append(label)
        real_call = r.fake_git.__call__

        def dirty_after_spawn(*args, check=True):
            if args[0] == "status" and r.spawned:
                return " M stray.py"
            return real_call(*args, check=check)

        r.git = dirty_after_spawn
        assert run_to_exit(r) == 3
        assert nudges, "expected a commit nudge before bailing"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "uncommitted" in bail["details"]


def test_session_limit_waits_then_redispatches_the_same_round():
    """A session the account's limit window killed did no work: the runner
    sleeps until the stated reset and dispatches the SAME round again — no
    nudge, no consult into the same wall, no round spent (the slice 110 task
    07 stall)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            ("code-writer", SESSION_LIMIT_TEXT),   # killed by the window
            V["writer_done"],                      # the same round, redispatched
            V["review_signoff"], V["verify_clean"],
        ]
        r = SpawningRunner(slice_dir, script)
        with patched(task_runner, run_kc_session=r.run_kc_session,
                     run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 0
        assert not r.script, "not every scripted session was consumed"
        assert len(r.sleeps) == 1 and 0 < r.sleeps[0] <= 12 * 3600
        assert [role for role, _ in r.sessions] == [
            "code-writer", "code-writer", "code-reviewer", "test-agent"], (
            "no nudge and no consult may be dispatched into the same wall")
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert writer_prompts[0] == writer_prompts[1], (
            "the redispatch is the same round, dispatched fresh")
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["writer_rounds"] == 1 and ts["status"] == "merged"
        limits = [h for h in state["history"] if h["outcome"] == "session_limit"]
        assert len(limits) == 1
        assert limits[0]["role"] == "code-writer" and limits[0]["round"] == 1
        assert "session limit" in limits[0]["summary"]


def test_session_limit_in_review_spends_no_round_and_keeps_the_scope():
    """The review loop is where a dead round costs most: it must not move the
    funding bar, and the redispatched round must review exactly what it would
    have reviewed."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"],
                  ("code-reviewer", SESSION_LIMIT_TEXT),
                  V["review_signoff"], V["verify_clean"]]
        r = SpawningRunner(slice_dir, script)
        with patched(task_runner, run_kc_session=r.run_kc_session,
                     run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 0
        assert not r.script
        reviews = [p for role, p in r.session_prompts if role == "code-reviewer"]
        assert len(reviews) == 2 and reviews[0] == reviews[1]
        assert "review round 1" in reviews[1]
        assert not any(role == "consult" for role, _ in r.sessions)
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["review_rounds"] == 1
        assert ts["reviewed_head"] == "abc123"


def test_repeated_session_limits_keep_waiting_on_a_bounded_fallback():
    """A notice with no parseable reset falls back to a fixed short wait, and
    hitting the window again just waits again — each wait bounded and logged."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        vague = "You've hit your session limit. Try again later."
        script = [("code-writer", vague), ("code-writer", vague),
                  V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = SpawningRunner(slice_dir, script)
        with patched(task_runner, run_kc_session=r.run_kc_session,
                     run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 0
        assert r.sleeps == [task_runner.SESSION_LIMIT_FALLBACK] * 2
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["writer_rounds"] == 1
        assert len([h for h in state["history"]
                    if h["outcome"] == "session_limit"]) == 2


def test_consult_log_names_its_call_site():
    """Every consult logs the decision point it serves — back-to-back
    consults in log.txt are otherwise indistinguishable (slice 099 cost
    real diagnosis time on exactly that)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "02_second"))
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = SpawningRunner(slice_dir, script)
        with patched(task_runner, run_kc_session=r.run_kc_session,
                     run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 0
        log = (slice_dir / "log.txt").read_text()
        assert "[consult: checkpoint] session starting" in log
        assert "[consult] session starting" not in log


def test_session_limit_reset_parsing():
    """The notice's 12-hour clock, its IANA zone, and the day it means."""
    parse = task_runner.parse_session_limit_reset
    now = datetime(2026, 7, 24, 21, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    later = parse(SESSION_LIMIT_TEXT, now=now)
    assert (later.day, later.hour, later.minute) == (24, 22, 10)
    assert later.tzinfo == ZoneInfo("Europe/Amsterdam")
    # a reset that already passed today is tomorrow's
    morning = parse("You've hit your session limit · resets 7:30am "
                    "(Europe/Amsterdam)", now=now)
    assert (morning.day, morning.hour, morning.minute) == (25, 7, 30)
    # the 12-hour clock's corners, and a bare hour
    assert parse("resets 12:05am (Europe/Amsterdam)", now=now).hour == 0
    assert parse("resets 12:05pm (Europe/Amsterdam)", now=now).hour == 12
    assert parse("resets 11pm (Europe/Amsterdam)", now=now).hour == 23
    # unparseable: no stated time, or a zone this host cannot resolve
    assert parse("You've hit your session limit", now=now) is None
    assert parse("resets 9pm (Mars/Olympus)", now=now) is None


def test_session_limit_notice_detection():
    """Only the API's own notice counts — an agent merely talking about limits
    must still be routed as an ordinary missing-verdict failure."""
    notice = task_runner.session_limit_notice
    result = task_runner.SessionResult()
    result.result_text = f"  {SESSION_LIMIT_TEXT}  "
    assert notice(result) == SESSION_LIMIT_TEXT
    result.result_text = "You’ve hit your session limit · resets 1am (UTC)"
    assert notice(result) is not None, "the typographic apostrophe is the same notice"
    result.result_text = "I stopped because the tests hit a limit"
    assert notice(result) is None
    result.result_text = ""
    assert notice(result) is None


def test_run_gate_runs_the_command_and_logs():
    """The real _run_gate: exit code decides green/red, output lands in
    gate_r<N>.log, and only a green run stamps gate_green_commit (and the log
    path the reviewer's gate line cites). The gate argv is the seam — the
    suite points it at a stub instead of putting a fake `kc` on PATH."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])
        r.state = {"tasks": {}, "history": [], "in_flight": None}
        r.repo_root = Path(tmp)
        ts = r._task_state("01_first")
        task_dir = slice_dir / "tasks" / "01_first"
        stub = Path(tmp) / "gate_stub.py"
        r._gate_argv = lambda project: [sys.executable, str(stub), project]

        stub.write_text("print('GATE GREEN')\n")
        green, log = Runner._run_gate(r, "01_first", ts, task_dir, PROJECT)
        assert green and "GATE GREEN" in log.read_text()
        assert log.name == "gate_r1.log"
        assert ts["gate_green_commit"] == "abc123"
        assert ts["gate_green_log"] == str(log)

        stub.write_text("import sys\nprint('GATE RED: x')\nsys.exit(1)\n")
        green, log = Runner._run_gate(r, "01_first", ts, task_dir, PROJECT)
        assert not green and ts["gate_runs"] == 2
        assert ts["gate_green_commit"] == "abc123", "red must not re-stamp"
        assert ts["gate_green_log"].endswith("gate_r1.log")
        assert [h["outcome"] for h in r.state["history"]
                if h["role"] == "gate"] == ["green", "red"]

        # kc's usage exit (2) means it rejected the component name — the name
        # came from kc's own project list, so that is a runner bug, not a red
        # suite, and must never be reported as a plain gate failure.
        stub.write_text("import sys\nsys.exit(2)\n")
        try:
            Runner._run_gate(r, "01_first", ts, task_dir, PROJECT)
        except Bailout as bail:
            assert bail.reason == "protocol_failure"
        else:
            raise AssertionError("a rejected project name must bail")


def test_gate_runs_from_the_repo_root():
    """kc resolves .kubecoder/project.yaml against its own cwd with no upward
    tree-walk, and resolves the component's cwd itself from --project. Running
    the gate from the component dir would make kc miss the manifest — a
    permanently red gate."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])
        r.state = {"tasks": {}, "history": [], "in_flight": None}
        r.repo_root = Path(tmp)
        ts = r._task_state("01_first")
        task_dir = slice_dir / "tasks" / "01_first"
        stub = Path(tmp) / "cwd_stub.py"
        stub.write_text("import os\nprint(os.getcwd())\n")
        r._gate_argv = lambda project: [sys.executable, str(stub)]

        green, log = Runner._run_gate(r, "01_first", ts, task_dir, PROJECT)
        assert green
        assert log.read_text().strip() == str(Path(tmp).resolve())


def test_gate_argv_names_the_component():
    """The default argv is the project contract's own seam: `kc project test
    --project <name>` — never a hardcoded per-repo script path."""
    with tempfile.TemporaryDirectory() as tmp:
        r = ScriptedRunner(make_slice(tmp), [])
        assert Runner._gate_argv(r, "backend") == [
            "kc", "project", "test", "--project", "backend"]


def test_reattach_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])
        vp = Path(tmp) / "verdict.json"

        r._reattach = {"task": "01_first", "role": "code-writer",
                       "session": "sess-crashed"}
        prompt, resume = r._resolve_reattach(
            "code-writer", "01_first", "orig", vp, "[x]")
        assert resume == "sess-crashed" and "interrupted" in prompt
        assert r._reattach is None, "the reattach record must be consumed"

        # consults never reattach
        r._reattach = {"task": None, "role": "consult", "session": "s2"}
        assert r._resolve_reattach("consult", None, "orig", vp, "[x]") \
            == ("orig", None)

        # a different task/role does not match
        r._reattach = {"task": "02_other", "role": "test-fixer",
                       "session": "s4"}
        assert r._resolve_reattach(
            "code-writer", "01_first", "orig", vp, "[x]") \
            == ("orig", None)


def test_resume_preserves_worktree_for_reattach():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        state = {
            "slice": slice_dir.name, "created_at": "t", "phase": "tasks",
            "base_branch": "main", "verification_rounds": 0, "consult_seq": 0,
            "in_flight": {"task": "01_first", "role": "code-writer",
                          "round": 1, "session": "sess-crashed",
                          "verdict_path": "x", "started_at": "t"},
            "flagged_findings": [],
            "tasks": {"01_first": {
                "status": "in_progress", "stage": "writer",
                "branch": "task/074-01", "writer_session": None,
                "writer_rounds": 1, "test_rounds": 0, "review_rounds": 0,
                "last_writer_commit": "abc123"}},
            "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        script = [V["writer_done"], V["review_signoff"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, resume=True)
        r.fake_git.branches.add("task/074-01")
        assert run_to_exit(r) == 0
        # the in-flight record was loaded for reattach and the crashed
        # session's uncommitted work was NOT reset away
        assert ("reset", "--hard", "HEAD") not in r.fake_git.calls
        final = json.loads((slice_dir / "state.json").read_text())
        assert final["in_flight"] is None
        assert final["tasks"]["01_first"]["status"] == "merged"


def test_reviewer_reattach_resumes_without_advancing_the_round():
    """A run killed mid-reviewer leaves that round already counted. On resume
    the round counter must not advance again and no funding consult may fire
    in the reattach's place — the interrupted reviewer session resumes its
    own round (the slice 084 task 04 crash shape)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        state = {
            "slice": slice_dir.name, "created_at": "t", "phase": "tasks",
            "base_branch": "main", "verification_rounds": 0, "consult_seq": 5,
            "in_flight": {"task": "01_first", "role": "code-reviewer",
                          "round": 4, "session": "sess-crashed",
                          "verdict_path": "x", "started_at": "t"},
            "flagged_findings": [],
            "tasks": {"01_first": {
                "status": "in_progress", "stage": "review",
                "branch": "task/074-01", "writer_session": "sess-w",
                "writer_rounds": 6, "test_rounds": 6, "review_rounds": 4,
                "last_writer_commit": "abc123"}},
            "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        script = [V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, resume=True)
        r.fake_git.branches.add("task/074-01")
        assert run_to_exit(r) == 0
        assert not r.script
        role, task, round_, outcome, resume, _model = r.spawned[0]
        assert role == "code-reviewer" and round_ == 4
        assert resume == "sess-crashed", "the interrupted session must resume"
        assert not any(prole == "consult" for prole, p in r.prompts), (
            "no funding consult may fire in the reattached round's place")
        final = json.loads((slice_dir / "state.json").read_text())
        ts = final["tasks"]["01_first"]
        assert ts["review_rounds"] == 4 and ts["status"] == "merged"


def test_reattach_resumes_the_interrupted_round_number():
    """A crash mid-round-2 leaves review_rounds at 1 (round 2 was never
    banked); the reattached dispatch must still be round 2 — the in-flight
    record's number — and its scope the fix range round 1 left behind."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        state = {
            "slice": slice_dir.name, "created_at": "t", "phase": "tasks",
            "base_branch": "main", "verification_rounds": 0, "consult_seq": 1,
            "in_flight": {"task": "01_first", "role": "code-reviewer",
                          "round": 2, "session": "sess-crashed",
                          "verdict_path": "x", "started_at": "t"},
            "flagged_findings": [],
            "tasks": {"01_first": {
                "status": "in_progress", "stage": "review",
                "branch": "task/074-01", "writer_session": "sess-w",
                "writer_rounds": 2, "test_rounds": 0, "review_rounds": 1,
                "reviewed_head": "h1", "last_writer_commit": "abc123"}},
            "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedRunner(slice_dir, [V["review_signoff"], V["verify_clean"]],
                           resume=True)
        r.fake_git.branches.add("task/074-01")
        assert run_to_exit(r) == 0
        assert r.spawned[0][2] == 2, "the interrupted round keeps its number"
        final = json.loads((slice_dir / "state.json").read_text())
        assert final["tasks"]["01_first"]["review_rounds"] == 2


def test_review_round2_gets_delta_prompt():
    """Round 1 reviews the whole branch; once fix commits move HEAD, round 2
    is scoped to the fix range <round-1 HEAD>..HEAD instead of re-reading the
    complete branch diff."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        class MovingHeadRunner(ScriptedRunner):
            # every code-writer round lands commits, so HEAD moves
            def _spawn(self, role, *a, **kw):
                out = super()._spawn(role, *a, **kw)
                if role == "code-writer":
                    self.fake_git.head = f"h{len(self.spawned)}"
                return out

        script = [V["writer_done"],
                  V["review_issues"], V["writer_done"],
                  V["review_signoff"],
                  V["verify_clean"]]
        r = MovingHeadRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert len(reviews) == 2
        assert "complete branch diff" in reviews[0]
        assert "Re-review" in reviews[1] and "h1..HEAD" in reviews[1]
        assert "code_review_r1.md" in reviews[1]
        # the re-run gate is green on the FIXED head, and the delta round is told
        # so — a fix round is where re-running the suite is most tempting
        assert "ran GREEN on this exact commit" in reviews[1]
        assert "h3"[:12] in reviews[1]
        # the review-fix writer prompt is self-contained (fresh session)
        fix_prompt = r.prompts[2][1]
        assert "01_first" in fix_prompt and "code_review_r1.md" in fix_prompt
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["reviewed_head"] == "h3"


def test_review_round2_unchanged_head_falls_back_to_full_prompt():
    """When no commits landed between review rounds there is no fix range
    (a blocked-reviewer retry has the same shape), so round 2 must fall back
    to the full-review prompt rather than scope to an empty diff."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], *REVIEW_ISSUE_ROUND,
                  V["review_signoff"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)   # FakeGit HEAD never moves
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert len(reviews) == 2
        assert all("complete branch diff" in p for p in reviews), (
            "an unchanged HEAD must never produce a delta-scoped review"
        )


def test_dead_review_round_advances_nothing():
    """A review round that produced no verdict and no review file reviewed
    nothing: it may not spend a round, and above all it may not stamp
    reviewed_head — the retried round must be scoped exactly as the dead one
    was, not cold-restarted over the whole branch (slice 110 task 07)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        class MovingHeadRunner(ScriptedRunner):
            def _spawn(self, role, *a, **kw):
                out = super()._spawn(role, *a, **kw)
                if role == "code-writer":
                    self.fake_git.head = f"h{len(self.spawned)}"
                return out

        script = [
            V["writer_done"],                        # head → h1
            V["review_issues"], V["writer_done"],    # round 1, fix → head h3
            ("code-reviewer", {"outcome": "blocked", "summary": "died"}),
            ("consult", {"outcome": "retry", "summary": "run it again"}),
            V["review_issues"],                      # the retried round 2
            ("consult", {"outcome": "merge", "summary": "advisory only"}),
            V["verify_clean"],
        ]
        r = MovingHeadRunner(slice_dir, script)
        r.fake_git.diff_files = "app/src/store.py"   # a real fix round
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert "complete branch diff" in reviews[0]
        assert reviews[1] == reviews[2], (
            "the retried round must review the same range as the dead one")
        assert "h1..HEAD" in reviews[2] and "review round 2" in reviews[2]
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["review_rounds"] == 2, "the dead round spent nothing"
        assert ts["reviewed_head"] == "h3"
        # the dead round funded nothing either: the funding consult that ran
        # judged round 2, at round 2's bar
        fund = next(p for role, p in r.prompts
                    if role == "consult" and "funding bar" in p)
        assert "Review round 2" in fund and "harm the product" in fund


def test_timed_out_review_round_resumes_as_the_same_round():
    """A bail mid-review leaves the round unbanked, so the resumed run
    re-dispatches that round number — a killed round never eats review budget
    (nor pushes the next `issues` verdict into a funding consult early)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = SpawningRunner(slice_dir, [V["writer_done"],
                                       ("code-reviewer", TIMED_OUT)])
        with patched(task_runner, run_kc_session=r.run_kc_session,
                     run_check=lambda *a, **kw: None):
            assert run_to_exit(r) == 3
        assert json.loads(
            (slice_dir / "bailout.json").read_text())["reason"] == "timeout"
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["review_rounds"] == 0
        assert "reviewed_head" not in state["tasks"]["01_first"]

        r2 = ScriptedRunner(slice_dir, [V["review_signoff"], V["verify_clean"]],
                            resume=True)
        r2.fake_git.branches.add("task/074-01")
        assert run_to_exit(r2) == 0
        assert r2.spawned[0][:3] == ("code-reviewer", "01_first", 1)
        final = json.loads((slice_dir / "state.json").read_text())
        assert final["tasks"]["01_first"]["review_rounds"] == 1


def test_orchestrator_session_recorded_from_env():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        prev = os.environ.get("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "orch-sess-1"
        try:
            assert run_to_exit(r) == 0
        finally:
            if prev is None:
                os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            else:
                os.environ["CLAUDE_CODE_SESSION_ID"] = prev
        state = json.loads((slice_dir / "state.json").read_text())
        orch = state["orchestrator"]
        assert orch["session"] == "orch-sess-1"
        assert orch["transcript"].endswith("orch-sess-1.jsonl")


def test_dirty_worktree_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        r = ScriptedRunner(slice_dir, [])
        dirty = FakeGit()
        real_call = dirty.__call__

        def dirty_call(*args, check=True):
            if args[0] == "status":
                return " M somefile.py"
            return real_call(*args, check=check)

        r.git = dirty_call
        assert run_to_exit(r) == 2
        assert not (slice_dir / "bailout.json").exists()


def test_protocol_failure_detail_reports_rc_and_verdict_separately():
    detail = task_runner._protocol_failure_detail
    # The regression: a valid verdict written before a SIGTERM (rc=143) must be
    # reported as a killed process, never as a verdict-protocol violation.
    msg = detail("code-writer", 143, {"outcome": "done"}, "verdict.json",
                 valid=True, nudged=False)
    assert "rc=143" in msg
    assert "valid outcome 'done'" in msg
    assert "invalid outcome" not in msg

    # A genuinely bad outcome is still called out as invalid.
    bad = detail("code-writer", 0, {"outcome": "banana"}, "verdict.json",
                 valid=False, nudged=False)
    assert "rc=0" in bad
    assert "invalid outcome 'banana'" in bad

    # A missing/unparseable verdict is distinct from an invalid one.
    missing = detail("code-writer", 1, None, "verdict.json",
                     valid=False, nudged=True)
    assert "missing/unparseable" in missing
    assert "invalid outcome" not in missing
    assert "(after one nudge)" in missing


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
