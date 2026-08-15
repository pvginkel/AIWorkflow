"""Tests for plan_loop.PlanLoop — the structural write→review round.

Sessions and git are faked: each test scripts the sequence of (role, verdict)
pairs it expects the loop to request and asserts on transitions, exits, and
the persisted plan_state.json. No kc session is created, no claude process
is spawned.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_plan_loop.py` or via pytest.
"""

import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "plan_loop", Path(__file__).resolve().parent / "plan_loop.py"
)
plan_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_loop)
PlanLoop = plan_loop.PlanLoop
VERDICTS = plan_loop.VERDICTS

PLAN_HEADER = """\
# Test slice — plan

Slice 099 in one line.

## Requirements / rulings

1. The operator's first requirement, verbatim.

## Ordering constraints

None.
"""

PHASE_BLOCK = """
## Phases

### P1 — First phase

Target: app

Outcome: the thing works.
"""


class ScriptedLoop(PlanLoop):
    """PlanLoop with _spawn replaced by a script of steps.

    A step is `(role, verdict)` or `(role, verdict, effect)`, where `effect`
    is called with the loop and stands in for what the session would have
    written to the slice folder. The scripted spawn writes the verdict file
    like a real session would — the GO gate re-reads it from disk.
    """

    def __init__(self, slice_dir, script, fixes_applied=False):
        super().__init__(Path(slice_dir), fixes_applied=fixes_applied)
        self.script = list(script)
        self.spawned = []   # (role, round, outcome)
        self.prompts = []   # (role, prompt)
        self.git_calls = []  # every git invocation, as its argv tuple

    def _assert_agents(self):
        pass

    def git(self, *args):
        self.git_calls.append(args)
        if args[0] == "status":
            return ""
        if args == ("rev-parse", "--show-toplevel"):
            return "/specs"
        if args[0] == "rev-parse":
            return "sha123"
        return ""

    def _spawn(self, role, prompt, verdict_path, round_):
        assert self.script, f"unexpected extra spawn: {role} r{round_}"
        step = self.script.pop(0)
        want_role, verdict = step[0], step[1]
        assert role == want_role, (
            f"expected spawn of {want_role}, loop asked for {role} r{round_}"
        )
        assert verdict["outcome"] in VERDICTS[role]
        Path(verdict_path).write_text(json.dumps(verdict))
        self.prompts.append((role, prompt))
        self.spawned.append((role, round_, verdict["outcome"]))
        self._record(role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1)
        if len(step) > 2:
            step[2](self)
        return verdict


def make_slice(tmp, phases=False):
    slice_dir = Path(tmp) / "099_test_slice"
    slice_dir.mkdir(parents=True)
    (slice_dir / "slice.md").write_text("# test slice\n")
    (slice_dir / "plan.md").write_text(
        PLAN_HEADER + (PHASE_BLOCK if phases else ""))
    return slice_dir


def write_phases(loop):
    """What a done writer pass leaves behind: the plan completed with
    phases, and verification.json authored."""
    loop.plan_path.write_text(PLAN_HEADER + PHASE_BLOCK)
    (loop.slice_dir / "verification.json").write_text('{"items": []}\n')


def run_to_exit(loop):
    try:
        loop.run()
    except SystemExit as e:
        return e.code
    raise AssertionError("run() must exit")


def load_state(slice_dir):
    return json.loads((slice_dir / "plan_state.json").read_text())


W_DONE = ("plan-writer", {"outcome": "done", "summary": "written"},
          write_phases)
W_Q = ("plan-writer", {"outcome": "questions", "summary": "need a ruling"})
R_GO = ("plan-reviewer", {"outcome": "go", "summary": "clean"})
R_ISSUES = ("plan-reviewer", {"outcome": "issues",
                              "summary": "two blocking"})
R_Q = ("plan-reviewer", {"outcome": "questions",
                         "summary": "undecided semantics"})


def test_fresh_slice_happy_path():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        assert not loop.script
        assert [s[0] for s in loop.spawned] == ["plan-writer", "plan-reviewer"]
        state = load_state(slice_dir)
        assert state["phase"] == "done"
        assert state["review_rounds"] == 1
        writer_prompt = loop.prompts[0][1]
        assert "requirements/rulings section is" in writer_prompt
        assert "preserve it verbatim" in writer_prompt
        assert "Target:" in writer_prompt


def test_the_loop_creates_and_commits_the_close_out_report_first():
    """The plan loop is the first to run on a slice, so it is the one that
    creates close-out.md — before the first dispatch, committed by name —
    and every dispatch names it. A rerun leaves the existing report alone."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        report = slice_dir / "close-out.md"
        seen_at_spawn = []

        def writer_effect(loop):
            seen_at_spawn.append(report.exists())
            write_phases(loop)

        loop = ScriptedLoop(slice_dir, [(*W_DONE[:2], writer_effect), R_ISSUES])
        assert run_to_exit(loop) == 4
        assert seen_at_spawn == [True], "the report predates the first dispatch"
        assert report.read_text().startswith("# Close-out — slice 099 test_slice\n")
        assert ("add", str(report)) in loop.git_calls
        commits = [c for c in loop.git_calls if c[:1] == ("commit",)]
        assert commits == [("commit", "-m", "slice 099: close-out report")]
        for role, prompt in loop.prompts:
            assert f"close-out report is {report}" in prompt, role
        # The rerun (fix pass) finds the report and neither recreates nor
        # recommits it; the writer's fix dispatch names it too.
        report.write_text(report.read_text() + "\n### Q1 — planning asked\n")
        rerun = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(rerun) == 0
        assert "### Q1 — planning asked" in report.read_text()
        assert not [c for c in rerun.git_calls if c[:1] == ("commit",)]
        assert f"close-out report is {report}" in rerun.prompts[0][1]


def test_report_creation_failure_is_a_bail_not_a_traceback():
    """The report's git work runs under the loop's bail handler: a failing
    commit in the shared spec tree writes plan_bailout.json (exit 3)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        class GitFailsToCommit(ScriptedLoop):
            def git(self, *args):
                if args[:1] == ("commit",):
                    raise plan_loop.Bailout(
                        "protocol_failure", details="git commit failed: index.lock")
                return super().git(*args)

        loop = GitFailsToCommit(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "index.lock" in bail["details"]
        assert not loop.spawned, "nothing is dispatched without the report"


def test_announce_lines_mark_pass_starts(capsys):
    """stdout carries one terse timestamped line per pass start and the
    final verdict — the watching caller's progress feed."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
        assert lines, "the loop announced nothing"
        assert all(re.match(r"^\[\d\d:\d\d:\d\d\] ", ln) for ln in lines)
        joined = "\n".join(lines)
        assert "plan-writer r1" in joined
        assert "plan-reviewer r1" in joined
        assert "plan complete" in joined


def test_review_issues_exit_for_adjudication_then_one_fix_pass():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
        assert run_to_exit(loop) == 4
        state = load_state(slice_dir)
        assert state["phase"] == "adjudicating"
        assert state["pending_review"] == 1
        # Rerun without --fixes-applied: exactly one writer fix pass, no
        # confirming review.
        loop2 = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(loop2) == 0
        assert not loop2.script
        assert [s[0] for s in loop2.spawned] == ["plan-writer"]
        assert load_state(slice_dir)["review_rounds"] == 1
        fix_prompt = loop2.prompts[0][1]
        assert "plan_review_r1.md" in fix_prompt
        assert "rulings recorded in plan.md supersede" in fix_prompt


def test_fixes_applied_flag_skips_the_fix_pass():
    """--fixes-applied is the session's declaration that it applied the
    accepted fixes itself. It is the ONLY thing that suppresses the pass."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
        assert run_to_exit(loop) == 4
        # The interactive session adjudicates, records the ruling AND applies
        # the fix itself, then says so on the rerun.
        plan = slice_dir / "plan.md"
        plan.write_text(
            plan.read_text()
            .replace("1. The operator's first requirement, verbatim.",
                     "1. The operator's first requirement, verbatim.\n"
                     "- Ruling (2026-07-31): split P1.")
            .replace("Outcome: the thing works.",
                     "Outcome: the thing works, in two steps."))
        loop2 = ScriptedLoop(slice_dir, [], fixes_applied=True)
        assert run_to_exit(loop2) == 0
        assert not loop2.spawned, "no session may be spawned"
        assert load_state(slice_dir)["phase"] == "done"


def test_fixes_applied_outside_adjudication_is_a_usage_error():
    """The flag answers a pending adjudication. Passed with none pending, the
    session is confused about the loop's state — say so rather than accept a
    declaration about nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [], fixes_applied=True)
        assert run_to_exit(loop) == 2
        assert not loop.spawned


def test_plan_edits_during_adjudication_still_dispatch_the_fix_pass():
    """Regression, Triage #460 + #511 — the loop must not infer "the fixes
    are in" from the plan's content.

    The adjudication procedure REQUIRES the rulings to be written before the
    rerun, and a reversed ruling routinely falsifies an ordering or
    not-in-scope bullet, so those edits are normal plan maintenance. The old
    hash heuristic read every one of them as applied fixes, set phase=done
    and exited 0 with the unfixed phases — silently. Nested `####`
    subheadings inside the rulings section were a second way in: the strip
    stopped at the first one, so the rest of the rulings counted too.
    """
    edits = {
        "flat rulings only": lambda t: t.replace(
            "1. The operator's first requirement, verbatim.",
            "1. The operator's first requirement, verbatim.\n"
            "- Ruling (2026-08-02): both mechanisms overturned; use the "
            "existing watch."),
        "rulings carrying #### subheadings": lambda t: t.replace(
            "1. The operator's first requirement, verbatim.",
            "#### Shape\n\n1. The operator's first requirement, verbatim.\n\n"
            "#### The daemon\n\n- Ruling (2026-08-06): keep the poll."),
        "ordering constraints rewritten": lambda t: t.replace(
            "## Ordering constraints\n\nNone.",
            "## Ordering constraints\n\nP1 before P2."),
        "a not-in-scope bullet falsified by a ruling": lambda t: t.replace(
            "## Ordering constraints",
            "## Not in scope\n\n- The codegen change (declined).\n\n"
            "## Ordering constraints"),
    }
    for label, edit in edits.items():
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir = make_slice(tmp)
            loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
            assert run_to_exit(loop) == 4
            plan = slice_dir / "plan.md"
            plan.write_text(edit(plan.read_text()))
            loop2 = ScriptedLoop(slice_dir, [W_DONE])
            assert run_to_exit(loop2) == 0
            assert [s[0] for s in loop2.spawned] == ["plan-writer"], (
                f"{label}: the fix pass it feeds was suppressed")
            assert "rulings recorded in plan.md supersede" in \
                loop2.prompts[0][1]


def test_writer_questions_pause_and_resume():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_Q])
        assert run_to_exit(loop) == 4
        state = load_state(slice_dir)
        assert state["pending_questions"].endswith("plan_questions_r1.md")
        loop2 = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop2) == 0
        resumed_prompt = loop2.prompts[0][1]
        assert "plan_questions_r1.md" in resumed_prompt
        assert "rulings section now holds the answers" in resumed_prompt
        assert load_state(slice_dir)["pending_questions"] is None


def test_reviewer_questions_route_to_adjudication_like_issues():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_Q])
        assert run_to_exit(loop) == 4
        state = load_state(slice_dir)
        assert state["phase"] == "adjudicating"
        assert state["pending_review"] == 1
        loop2 = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(loop2) == 0
        assert [s[0] for s in loop2.spawned] == ["plan-writer"]
        assert "plan_review_r1.md" in loop2.prompts[0][1]


def test_existing_phased_plan_enters_at_review():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, phases=True)
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert loop.spawned[0][0] == "plan-reviewer"


def test_writer_blocked_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(
            slice_dir,
            [("plan-writer", {"outcome": "blocked", "summary": "no repo"})])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "blocked"


def test_go_without_verdict_on_file_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)

        def eat_verdict(loop):
            (slice_dir / "plan_review_result_r1.json").unlink()

        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO + (eat_verdict,)])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "without the review on file" in bail["details"]


def test_go_with_unparseable_plan_bails():
    """A GO whose plan is not a drivable phase queue must not exit 0 — the
    run loop's preflight would reject it later and colder."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        # the writer reports done but leaves the seeded header (no phases)
        w_no_phases = ("plan-writer", {"outcome": "done", "summary": "done"})
        loop = ScriptedLoop(slice_dir, [w_no_phases, R_GO])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "plan_doc"
        assert "phases" in bail["details"]


def test_rerun_after_done_stays_done():
    """Post-GO corrections are the session's own plan edits — a rerun of a
    completed loop spawns nothing and exits 0."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        loop2 = ScriptedLoop(slice_dir, [])
        assert run_to_exit(loop2) == 0
        assert not loop2.spawned


def test_missing_slice_md_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "099_test_slice"
        slice_dir.mkdir()
        (slice_dir / "plan.md").write_text(PLAN_HEADER)
        loop = ScriptedLoop(slice_dir, [])
        assert run_to_exit(loop) == 2


def test_missing_plan_md_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "099_test_slice"
        slice_dir.mkdir()
        (slice_dir / "slice.md").write_text("# s\n")
        loop = ScriptedLoop(slice_dir, [])
        assert run_to_exit(loop) == 2


class DirtyGitLoop(ScriptedLoop):
    """ScriptedLoop whose specs-repo status reports scripted porcelain -z
    output, exercising the real dirty-path parsing."""

    def __init__(self, slice_dir, script, porcelain=""):
        super().__init__(slice_dir, script)
        self.porcelain = porcelain

    def git(self, *args):
        if args[0] == "status":
            return self.porcelain
        return super().git(*args)


def test_dirty_slice_folder_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = DirtyGitLoop(slice_dir, [],
                            porcelain=" M specs/099/notes.md\0")
        assert run_to_exit(loop) == 2


def test_loop_owned_files_pass_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        porcelain = ("?? specs/099/plan_log.txt\0"
                     "?? specs/099/plan_state.json\0"
                     "?? specs/099/plan_bailout.json\0")
        loop = DirtyGitLoop(slice_dir, [W_DONE, R_GO], porcelain=porcelain)
        assert run_to_exit(loop) == 0


def test_dirty_paths_parse_spaces_and_renames():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        porcelain = ("R  specs/099/new name.md\0specs/099/old.md\0"
                     " M specs/099/plan_log.txt\0"
                     "?? specs/099/a file.md\0")
        loop = DirtyGitLoop(slice_dir, [], porcelain=porcelain)
        dirty = loop._slice_dirty_paths()
        assert dirty == ["specs/099/new name.md", "specs/099/a file.md"]


def test_dispatch_passes_model_and_effort_explicitly():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        calls = []

        loop = PlanLoop(slice_dir)
        loop._assert_agents = lambda: None
        loop.git = lambda *args: ("" if args[0] == "status"
                                  else "/specs"
                                  if args == ("rev-parse", "--show-toplevel")
                                  else "sha123")

        def fake_session(prompt, cwd, timeout, agent=None, model=None,
                         effort=None, resume_session=None, extra_env=None,
                         progress=None, on_session=None):
            calls.append((agent, model, effort))
            result = plan_loop.run_loop_result = type(
                "R", (), {"session_id": "sess-1", "result_text": "",
                          "is_error": False})()
            # write the verdict a real session would
            if agent == "plan-writer":
                write_phases(loop)
                (slice_dir / "plan_writer_result_r1.json").write_text(
                    '{"outcome": "done", "summary": "ok"}')
            else:
                (slice_dir / "plan_review_result_r1.json").write_text(
                    '{"outcome": "go", "summary": "ok"}')
            return 0, result

        original = plan_loop.run_kc_session
        plan_loop.run_kc_session = fake_session
        try:
            code = run_to_exit(loop)
        finally:
            plan_loop.run_kc_session = original
        assert code == 0
        assert calls == [("plan-writer", "opus", "xhigh"),
                         ("plan-reviewer", "opus", "xhigh")]


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    failures = 0
    for _fn in _tests:
        try:
            _fn()
            print(f"ok  {_fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {_fn.__name__}: {e}")
    print(f"\n{len(_tests) - failures} passed, {failures} failed")
    if failures:
        sys.exit(1)
