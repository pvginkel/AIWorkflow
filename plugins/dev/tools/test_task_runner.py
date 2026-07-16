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
import sys
import tempfile
from pathlib import Path

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

    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "main"
        if args[0] == "rev-parse":
            return "abc123"
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
        if green:
            ts["gate_green_commit"] = self.git("rev-parse", "HEAD")
        self._record(task_id, "gate", ts["gate_runs"],
                     "green" if green else "red", "", None, 0)
        return green, task_dir / f"gate_r{ts['gate_runs']}.log"

    def _spawn(self, role, prompt, cwd, verdict_path, task_id, round_,
               agent=None, resume_session=None):
        # Mirror the real _spawn's reattach consumption so resume tests
        # exercise the same record lifecycle.
        prompt, resume_session = self._resolve_reattach(
            role, task_id, prompt, Path(verdict_path), resume_session, "[t]")
        assert self.script, f"unexpected extra spawn: {role} (task {task_id})"
        want_role, verdict = self.script.pop(0)
        self.prompts.append((role, prompt))
        assert role == want_role, (
            f"expected spawn of {want_role}, runner asked for {role} "
            f"(task {task_id}, round {round_})"
        )
        self.spawned.append((role, task_id, round_, verdict["outcome"],
                             resume_session))
        self._record(task_id, role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1)
        return verdict, "sess-test"


def make_slice(tmp, tasks=("01_first",), project=PROJECT):
    slice_dir = Path(tmp) / "074_test_slice"
    (slice_dir / "tasks").mkdir(parents=True)
    (slice_dir / "slice.md").write_text("# test slice\n")
    (slice_dir / "acceptance_criteria.json").write_text('{"criteria": []}\n')
    for name in tasks:
        tdir = slice_dir / "tasks" / name
        tdir.mkdir()
        (tdir / "task.json").write_text(json.dumps({
            "id": name.split("_")[0], "slug": name.split("_", 1)[1], "project": project,
            "title": f"task {name}", "summary": "test task",
        }))
        (tdir / "plan.md").write_text("plan\n")
    return slice_dir


def run_to_exit(runner):
    try:
        runner.run()
    except SystemExit as e:
        return e.code
    raise AssertionError("runner.run() did not exit")


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
                  V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["phase"] == "done"
        assert state["tasks"]["01_first"]["status"] == "merged"
        assert state["tasks"]["02_second"]["status"] == "merged"
        # a green gate spawns NO session and the merge trusts the verified
        # commit: exactly one gate run per task, no test-fixer anywhere
        assert r.gate_calls == [("01_first", True), ("02_second", True)]
        assert not any(role == "test-fixer" for role, *_ in r.spawned)
        merges = r.fake_git.mutations("merge")
        assert len(merges) == 2 and all("--ff-only" in m for m in merges)
        assert not (slice_dir / "bailout.json").exists()


def test_red_gate_spawns_fixer_then_confirms_green():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["fixer_clean"], V["review_signoff"],
                  V["checkpoint"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[False, True])
        assert run_to_exit(r) == 0
        assert not r.script
        # the fixer's `clean` was confirmed by a gate re-run, not trusted
        assert r.gate_calls == [("01_first", False), ("01_first", True)]
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["test_rounds"] == 1


def test_fixer_escalation_routes_fix_to_same_writer():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["fixer_issues"], V["writer_done"],
                  V["review_signoff"], V["checkpoint"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[False, True])
        assert run_to_exit(r) == 0
        # the escalation fix round resumed the original writer session
        fix_spawn = r.spawned[2]
        assert fix_spawn[0] == "code-writer" and fix_spawn[4] == "sess-test"
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["01_first"]["test_rounds"] == 1


def test_fix_limit_consult_proceed_to_review():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            V["fixer_issues"], V["writer_done"],    # round 1 + fix
            V["fixer_issues"], V["writer_done"],    # round 2 + fix
            V["fixer_issues"],                      # round 3 → the cap
            ("consult", {"outcome": "proceed_to_review", "summary": "close"}),
            V["review_signoff"], V["checkpoint"], V["verify_clean"],
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
                  V["review_signoff"], V["checkpoint"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, gates=[True, False, True])
        assert run_to_exit(r) == 0
        assert not r.script
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["test_rounds"] == 1 and ts["review_rounds"] == 2
        # last gate green verified HEAD, so the merge did not re-run it
        assert len(r.gate_calls) == 3


def test_review_limit_merge_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND * 3,                # rounds 1-3 → the cap
            ("consult", {"outcome": "merge_flagged", "summary": "cosmetic"}),
            V["checkpoint"], V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        state = json.loads((slice_dir / "state.json").read_text())
        assert len(state["flagged_findings"]) == 1
        assert state["flagged_findings"][0]["task"] == "01_first"


def test_review_cap_consult_can_buy_a_confirming_round():
    """The defect slice 082 hit 4 times: a Major raised in the final review round
    had its fix written but never re-reviewed, and the consult's only options were
    to merge it unseen or kill the slice. The consult can now buy the round that
    confirms the fix — and when the reviewer signs off, NOTHING is flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND * 3,                # rounds 1-3 → the cap
            ("consult", {"outcome": "another_round", "summary": "fix looks in"}),
            V["review_signoff"],                    # round 4 confirms the fix
            V["checkpoint"], V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["status"] == "merged"
        assert ts["review_rounds"] == 4 and ts["review_grants"] == 1
        # the whole point: a reviewer saw the fix, so this is NOT a flagged merge
        assert state["flagged_findings"] == []


def test_review_grants_run_out_and_the_task_merges_flagged():
    """The grant is bounded: a writer/reviewer pair that never converges still
    terminates. Once the grants are spent the consult is no longer offered the
    option, so it cannot spin the loop forever."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        grant = ("consult", {"outcome": "another_round", "summary": "one more"})
        script = [
            V["writer_done"],
            *REVIEW_ISSUE_ROUND * 3,                # rounds 1-3 → the cap
            grant, *REVIEW_ISSUE_ROUND,             # grant 1 → round 4, still bad
            grant, *REVIEW_ISSUE_ROUND,             # grant 2 → round 5, still bad
            # grants exhausted: another_round is withheld, so merge_flagged/bail only
            ("consult", {"outcome": "merge_flagged", "summary": "enough"}),
            V["checkpoint"], V["verify_clean"],
        ]
        r = ScriptedRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = json.loads((slice_dir / "state.json").read_text())
        ts = state["tasks"]["01_first"]
        assert ts["review_rounds"] == 5 and ts["review_grants"] == 2
        assert len(state["flagged_findings"]) == 1
        # the CAP consults only — NOT the end-of-task checkpoint consult, which
        # also has role "consult" and would make these assertions vacuous
        caps = [p for role, p in r.prompts
                if role == "consult" and "did not sign off" in p]
        assert len(caps) == 3, "expected a consult at the cap and at each grant"
        assert "another_round" in caps[0] and "another_round" in caps[1], (
            "while grants remain, the consult must be able to buy a round"
        )
        assert "another_round" not in caps[2], (
            "grants were spent — the option must be withheld, or the consult "
            "could keep buying rounds forever"
        )


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
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
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
        script2 = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                   V["verify_clean"]]
        r2 = ScriptedRunner(slice_dir, script2, resume=True)
        assert run_to_exit(r2) == 0
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["verification_rounds"] == 2
        assert state["tasks"]["01_first"]["status"] == "merged"
        # task 01 was NOT re-run: writer/review/checkpoint/verify
        assert len(r2.spawned) == 4


def test_verification_findings_proceed_flagged_completes():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
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
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
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
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        inserted = {"done": False}

        class AmendingRunner(ScriptedRunner):
            def _spawn(self, role, *a, **kw):
                if role == "consult" and not inserted["done"]:
                    inserted["done"] = True
                    new = slice_dir / "tasks" / "02_inserted"
                    new.mkdir()
                    (new / "task.json").write_text(json.dumps(
                        {"id": "02", "slug": "inserted",
                         "project": PROJECT, "title": "inserted",
                         "summary": "added by checkpoint"}))
                return super()._spawn(role, *a, **kw)

        script = [
            V["writer_done"], V["review_signoff"],
            ("consult", {"outcome": "amend", "summary": "added a task"}),
            V["writer_done"], V["review_signoff"],
            ("consult", {"outcome": "proceed", "summary": "holds"}),
            V["verify_clean"],
        ]
        r = AmendingRunner(slice_dir, script)
        assert run_to_exit(r) == 0
        state = json.loads((slice_dir / "state.json").read_text())
        assert state["tasks"]["02_inserted"]["status"] == "merged"


def test_letter_suffix_inserts_between_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first", "01a_inserted",
                                           "02_second"))
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["checkpoint"],
                  V["writer_done"], V["review_signoff"], V["checkpoint"],
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


def test_run_gate_runs_the_command_and_logs():
    """The real _run_gate: exit code decides green/red, output lands in
    gate_r<N>.log, and only a green run stamps gate_green_commit. The gate
    argv is the seam — the suite points it at a stub instead of putting a fake
    `kc` on PATH."""
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

        stub.write_text("import sys\nprint('GATE RED: x')\nsys.exit(1)\n")
        green, log = Runner._run_gate(r, "01_first", ts, task_dir, PROJECT)
        assert not green and ts["gate_runs"] == 2
        assert ts["gate_green_commit"] == "abc123", "red must not re-stamp"
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
            "code-writer", "01_first", "orig", vp, None, "[x]")
        assert resume == "sess-crashed" and "interrupted" in prompt
        assert r._reattach is None, "the reattach record must be consumed"

        # consults never reattach
        r._reattach = {"task": None, "role": "consult", "session": "s2"}
        assert r._resolve_reattach("consult", None, "orig", vp, None, "[x]") \
            == ("orig", None)

        # an intentional resume (writer fix round) is never overridden
        r._reattach = {"task": "01_first", "role": "code-writer",
                       "session": "s3"}
        assert r._resolve_reattach(
            "code-writer", "01_first", "orig", vp, "sess-fix", "[x]") \
            == ("orig", "sess-fix")

        # a different task/role does not match
        r._reattach = {"task": "02_other", "role": "test-fixer",
                       "session": "s4"}
        assert r._resolve_reattach(
            "code-writer", "01_first", "orig", vp, None, "[x]") \
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
        script = [V["writer_done"], V["review_signoff"], V["checkpoint"],
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


def test_reviewer_reattach_at_cap_resumes_without_consult():
    """A run killed mid-reviewer leaves that round already counted. On resume
    the cap check must not fire a limit consult in the reattach's place, and
    the round counter must not advance again — the interrupted reviewer
    session resumes its own round (the slice 084 task 04 crash shape)."""
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
                "review_grants": 1, "last_writer_commit": "abc123"}},
            "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        script = [V["review_signoff"], V["checkpoint"], V["verify_clean"]]
        r = ScriptedRunner(slice_dir, script, resume=True)
        r.fake_git.branches.add("task/074-01")
        assert run_to_exit(r) == 0
        assert not r.script
        role, task, round_, outcome, resume = r.spawned[0]
        assert role == "code-reviewer" and round_ == 4
        assert resume == "sess-crashed", "the interrupted session must resume"
        assert not any("did not sign off" in p for prole, p in r.prompts
                       if prole == "consult"), "no cap consult may fire"
        final = json.loads((slice_dir / "state.json").read_text())
        ts = final["tasks"]["01_first"]
        assert ts["review_rounds"] == 4 and ts["status"] == "merged"


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


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
