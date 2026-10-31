"""Tests for plan_loop.PlanLoop — the structural write→review round.

Sessions and git are faked: each test scripts the sequence of (role, verdict)
pairs it expects the loop to request and asserts on transitions, exits, and
the persisted plan_state.json. No kc session is created, no claude process
is spawned.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_plan_loop.py` or via pytest.
"""

import contextlib
import fcntl
import importlib.util
import io
import json
import os
import re
import subprocess
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
# The run loop's module, as the plan loop imported it: the seams below and
# the guards' globals are read there.
run_loop = plan_loop.run_loop

# spawn_flags (the run loop's, shared) copies the promoted MCP servers out of
# the user-level ~/.claude.json. That seam is stubbed with a home that does
# not exist, so no test reads or writes the operator's own files; the one test
# that asserts the flags points it at a throwaway home of its own.
run_loop._user_home = lambda: Path(tempfile.gettempdir()) / "planloop-no-home"

# The version guard reads Claude Code's installed_plugins.json, which on the
# machine running the suite names whatever is installed there — not this
# tree's version. Pointed at a file that does not exist, the guard fails open;
# the tests that exercise it write their own (`installed`).
run_loop.INSTALLED_PLUGINS = (Path(tempfile.gettempdir()) / "planloop-no-home"
                              / "installed_plugins.json")
# The suite's loops run from this checkout, which the guard lets pass as a
# --plugin-dir run's (run_loop.runs_from_checkout). Stood in for an install
# here, so the guard's tests see it bail; the test of a checkout moves it.
run_loop.PLUGINS_HOME = run_loop.TOOLS_DIR.parent.parent

# Pilot's halt file is the host's (`/work/...`): a pod running the suite while
# a halt holds would halt every loop in it. Pointed at a file that does not
# exist; the tests of the halt make one of their own (`halt_file`).
run_loop.HALT_FILE = (Path(tempfile.gettempdir()) / "planloop-no-home"
                      / "quota-limit-halt-requested")

# The GO check's tool scan reads the pod's tool containers from `kc env
# describe`; stubbed as running `python` alone. Its service scan reads the
# pod's services from the same describe; stubbed as running none.
run_loop.running_tools = lambda: {"python"}
run_loop.running_services = lambda: set()

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

    def __init__(self, slice_dir, script, step=None, spec_top="/specs",
                 nudge_effect=None):
        super().__init__(Path(slice_dir), step=step)
        self.script = list(script)
        self.spawned = []   # (role, round, outcome)
        self.prompts = []   # (role, prompt)
        self.nudges = []    # (role, prompt), each a resume of the session
        # What a nudged session does, given the loop: a hand-back fixed, or
        # nothing.
        self.nudge_effect = nudge_effect
        self.git_calls = []  # every git invocation, as its argv tuple
        self.branch = "main"  # what the spec repo is checked out on
        # What `rev-parse --show-toplevel` answers.
        self.spec_top = spec_top

    def _assert_agents(self):
        pass

    def git(self, *args):
        self.git_calls.append(args)
        if args[0] == "status":
            return ""
        if args == ("rev-parse", "--show-toplevel"):
            return self.spec_top
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return self.branch
        if args[0] == "rev-parse":
            return "sha123"
        return ""

    def _spawn(self, role, prompt, verdict_path, round_):
        # The real _spawn's preamble, kept in step: the spec tree is shared,
        # and a dispatch onto someone else's branch commits the plan there.
        self._assert_on_base()
        self._assert_current()
        assert self.script, f"unexpected extra spawn: {role} r{round_}"
        step = self.script.pop(0)
        want_role, verdict = step[0], step[1]
        assert role == want_role, (
            f"expected spawn of {want_role}, loop asked for {role} "
            f"r{round_}"
        )
        assert verdict["outcome"] in VERDICTS[role]
        Path(verdict_path).write_text(json.dumps(verdict))
        self.prompts.append((role, prompt))
        self.spawned.append((role, round_, verdict["outcome"]))
        self._session = "sess-test"
        self._record(role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1)
        if len(step) > 2:
            step[2](self)
        return verdict

    def _nudge(self, prompt, session_id, label, role):
        assert session_id == "sess-test"
        self.nudges.append((role, prompt))
        if self.nudge_effect is not None:
            self.nudge_effect(self)


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


def asks_questions(*questions):
    """What a writer's `questions` pass leaves: its hand-back, for the round
    the loop drew."""
    def effect(loop):
        w = loop.state["writer_rounds"]
        (loop.slice_dir / f"plan_questions_r{w}.json").write_text(
            json.dumps({"questions": list(questions)}))
    return effect


def finds(*findings):
    """What a review that does not `go` leaves beside its prose: the
    findings that need a ruling, for the round the loop drew."""
    def effect(loop):
        r = loop.state["review_rounds"]
        (loop.slice_dir / f"plan_review_r{r}.json").write_text(
            json.dumps({"findings": list(findings)}))
    return effect


QUESTION = {
    "headline": "Keep the sessions in Postgres or in Redis",
    "body": "The plan stores a session per sign-in. Postgres is already a "
            "service here; Redis is not.",
    "options": [{"label": "Postgres", "line": "one store, no new service"},
                {"label": "Redis", "line": "faster expiry, a new service"}],
    "recommend": "Postgres",
}
BLOCKING = {
    "class": "blocking",
    "headline": "Requirement 1 has no criterion",
    "body": "slice.md's requirement 1 is in no item of verification.json.",
    "proposal": "verification.json carries requirement 1 as a criterion, in "
                "the operator's words.",
}
OPERATOR = {
    "class": "operator",
    "headline": "Slice 031 and this plan build the login page differently",
    "body": "Both plans carry the login page; each specifies it otherwise.",
    "options": [{"label": "As 031 says", "line": "a form with a magic link"},
                {"label": "As this plan says", "line": "a password form"}],
}

W_DONE = ("plan-writer", {"outcome": "done", "summary": "written"},
          write_phases)
W_Q = ("plan-writer", {"outcome": "questions", "summary": "need a ruling"},
       asks_questions(QUESTION))
R_GO = ("plan-reviewer", {"outcome": "go", "summary": "clean"})
R_ISSUES = ("plan-reviewer", {"outcome": "issues",
                              "summary": "two blocking"}, finds(BLOCKING))
R_Q = ("plan-reviewer", {"outcome": "questions",
                         "summary": "undecided semantics"}, finds(OPERATOR))


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
    creates the report — its store, before the first dispatch, committed by
    name — and every dispatch names it. A rerun leaves the existing store
    alone."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        report = slice_dir / "close-out.md"
        store = slice_dir / "close-out.json"
        seen_at_spawn = []

        def writer_effect(loop):
            seen_at_spawn.append(store.exists())
            write_phases(loop)

        loop = ScriptedLoop(slice_dir, [(*W_DONE[:2], writer_effect), R_ISSUES])
        assert run_to_exit(loop) == 4
        assert seen_at_spawn == [True], "the report predates the first dispatch"
        assert not (slice_dir / "close-out-record.md").exists(), "the run renders it"
        assert not report.exists()
        assert json.loads(store.read_text())["entries"] == []
        assert ("add", str(store)) in loop.git_calls
        commits = [c for c in loop.git_calls if c[:1] == ("commit",)]
        assert commits == [("commit", "-m", "slice 099: close-out report")]
        for role, prompt in loop.prompts:
            assert f"close-out report is {report}" in prompt, role
        # The rerun (fix pass) finds the store and neither recreates nor
        # recommits it; the writer's fix dispatch names it too.
        close_out.append_entry(slice_dir, "decision", "planning asked", "b",
                               consequence="the rollout waits on it")
        rerun = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(rerun) == 0
        assert "D1 — planning asked" in close_out.list_view(slice_dir)
        assert not [c for c in rerun.git_calls if c[:1] == ("commit",)]
        assert f"close-out report is {report}" in rerun.prompts[0][1]


def test_the_loop_renders_no_report_at_any_exit():
    """What planning appends stays in the store — at a questions exit, at a
    bail, at exit 0 — and nothing is rendered beside it: the report is the
    run's to render, so a stop leaves no close-out.md or record in the
    folder, which the promotion would otherwise find untracked."""
    def appends(what):
        def effect(loop):
            write_phases(loop)
            asks_questions(QUESTION)(loop)
            close_out.append_entry(loop.slice_dir, "event", what, "b",
                                   consequence="none")
        return effect

    def nothing_rendered():
        return not any((slice_dir / name).exists()
                       for name in ("close-out.md", "close-out-record.md"))

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [("plan-writer", {"outcome": "questions",
                                                         "summary": "q"},
                                         appends("asked the operator"))])
        assert run_to_exit(loop) == 4
        assert "E1 — asked the operator" in close_out.list_view(slice_dir)
        assert nothing_rendered()
        assert commits(loop) == [("commit", "-m", "slice 099: close-out report")]
        assert "close-out rendered" not in (slice_dir / "plan_log.txt").read_text()

        def fails(loop):
            appends("the run bailed")(loop)
            raise plan_loop.Bailout("protocol_failure", details="scripted")

        loop = ScriptedLoop(slice_dir, [("plan-writer", {"outcome": "done"}, fails)])
        assert run_to_exit(loop) == 3
        assert "E2 — the run bailed" in close_out.list_view(slice_dir)
        assert nothing_rendered()
        assert not commits(loop)


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
        # The rerun once the findings are ruled: exactly one writer fix pass, no
        # confirming review.
        loop2 = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(loop2) == 0
        assert not loop2.script
        assert [s[0] for s in loop2.spawned] == ["plan-writer"]
        assert load_state(slice_dir)["review_rounds"] == 1
        fix_prompt = loop2.prompts[0][1]
        assert "plan_review_r1.md" in fix_prompt
        assert "rulings recorded in plan.md supersede" in fix_prompt


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
        assert state["pending_questions"].endswith("plan_questions_r1.json")
        loop2 = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop2) == 0
        resumed_prompt = loop2.prompts[0][1]
        assert "plan_questions_r1.json" in resumed_prompt
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


# -- exit 4: the hand-backs as a document Pilot reads -------------------------

asks = plan_loop.asks


def quiet(loop):
    """The loop run to its exit with stdout and stderr captured: (code,
    stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_to_exit(loop)
    return code, out.getvalue(), err.getvalue()


def test_writer_questions_exit_with_a_document_for_the_session_to_register():
    """A `questions` pass puts its hand-back to the operator as a document
    in asks/, rendered through asks.py — a decision where the writer gave
    options, its recommendation kept — names it on stdout and in the exit
    record, carries the plan task as `step`, and commits nothing of it: the
    session commits what it registers."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_Q], step="t7")
        code, out, err = quiet(loop)
        assert code == 4
        document = slice_dir / "asks" / "1-plan-questions.md"
        assert f"document: {document}" in out.splitlines()
        assert "QUESTIONS PENDING (plan-writer r1)" in err
        record = load_state(slice_dir)["exit"]
        assert record["code"] == 4
        assert record["reason"] == "questions"
        assert record["document"] == str(document)
        store = asks.load(document)
        assert store["title"] == "Slice 099: the plan-writer's questions"
        assert store["step"] == "t7"
        assert "pass r1 on slice 099's plan" in store["context"][0]
        assert [(e["id"], e["kind"], e["headline"], e.get("recommend"))
                for e in store["entries"]] == [
            ("D1", "decision", QUESTION["headline"], "Postgres")]
        assert {bid: (b["kind"], b["lines"]) for bid, b in
                asks.read_back(document.read_text()).items()} == {
            "D1": ("decision", {})}
        assert commits(loop) == [("commit", "-m", "slice 099: close-out report")]


def test_review_findings_put_one_ask_each_and_leave_the_advisory_in_the_review():
    """A blocking finding goes as a decision on the reviewer's disposition,
    an operator-decidable one as a decision on its options with no winner
    named, or as a question where it gives none; an advisory note stays in
    the prose review."""
    advisory = {"class": "advisory", "headline": "P1 runs long",
                "body": "It could split."}
    open_fact = {"class": "operator", "headline": "Which tenant owns the data",
                 "body": "Neither slice.md nor the code says."}
    review = ("plan-reviewer", {"outcome": "issues", "summary": "x"},
              finds(OPERATOR, BLOCKING, advisory, open_fact))
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        code, out, _ = quiet(ScriptedLoop(slice_dir, [W_DONE, review]))
        assert code == 4
        document = slice_dir / "asks" / "1-plan-review.md"
        assert f"document: {document}" in out.splitlines()
        store = asks.load(document)
        assert store["title"] == "Slice 099: the plan review's findings"
        assert store["summary"] == ("Slice 099's plan waits on 3 rulings "
                                    "before the plan loop can go on")
        assert "plan_review_r1.md" in store["context"][0]
        assert "step" not in store
        entries = [{k: e.get(k) for k in ("id", "kind", "headline",
                                         "proposal", "recommend")}
                   for e in store["entries"]]
        assert entries == [
            {"id": "D1", "kind": "decision", "headline": OPERATOR["headline"],
             "proposal": None, "recommend": None},
            {"id": "D2", "kind": "decision", "headline": BLOCKING["headline"],
             "proposal": BLOCKING["proposal"], "recommend": None},
            {"id": "Q1", "kind": "question", "headline": open_fact["headline"],
             "proposal": None, "recommend": None}]
        assert load_state(slice_dir)["exit"]["reason"] == "review"


def test_the_plan_task_is_kept_for_the_reruns_that_do_not_give_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        assert quiet(ScriptedLoop(slice_dir, [W_Q], step="t3"))[0] == 4
        code, _, _ = quiet(ScriptedLoop(slice_dir, [W_DONE, R_ISSUES]))
        assert code == 4
        assert asks.load(slice_dir / "asks" / "2-plan-review.md")["step"] == "t3"
        assert load_state(slice_dir)["step"] == "t3"


def test_a_faulty_hand_back_is_nudged_once_then_put():
    """A hand-back the operator cannot be shown goes back to the session
    that wrote it, once, with its faults; fixed, the exit goes on."""
    missing = ("plan-writer", {"outcome": "questions", "summary": "q"})
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [missing],
                            nudge_effect=asks_questions(QUESTION))
        assert quiet(loop)[0] == 4
        assert [role for role, _ in loop.nudges] == ["plan-writer"]
        nudge = loop.nudges[0][1]
        assert "plan_questions_r1.json cannot go to the operator" in nudge
        assert "- plan_questions_r1.json is not there" in nudge
        assert (slice_dir / "asks" / "1-plan-questions.md").exists()


def test_a_hand_back_still_faulty_after_its_nudge_bails():
    headed = dict(QUESTION, body="Context.\n\n## A heading\n\nMore.")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "questions", "summary": "q"},
             asks_questions(headed))])
        assert quiet(loop)[0] == 3
        assert len(loop.nudges) == 1
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert bail["details"].startswith(
            "plan-writer's hand-back plan_questions_r1.json cannot go to the "
            "operator after a nudge:\n- questions 1: ")
        assert "heading" in bail["details"]
        assert not (slice_dir / "asks").exists()
        assert load_state(slice_dir)["exit"] == {
            "code": 3, "ts": load_state(slice_dir)["exit"]["ts"],
            "reason": "protocol_failure"}


def test_read_handback_names_every_fault():
    def faults(role, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handback.json"
            path.write_text(data if isinstance(data, str) else json.dumps(data))
            return plan_loop.read_handback(role, path)

    assert faults("plan-writer", "{not json")[1][0].startswith(
        "handback.json is no JSON")
    assert faults("plan-writer", {"questions": "one"})[1] == [
        'handback.json is no {"questions": [...]}']
    assert faults("plan-writer", {"questions": []})[1] == [
        "handback.json holds no question that needs a ruling"]
    _, found = faults("plan-writer", {"questions": [
        dict(QUESTION, recommend="MySQL"),
        {"headline": "x", "body": "y", "why": "z"},
        {"headline": "", "body": "y"}]})
    assert len(found) == 3
    assert "recommend: MySQL" in found[0] and found[0].startswith("questions 1:")
    assert found[1] == "questions 2: no field why"
    assert found[2].startswith("questions 3:")
    entries, found = faults("plan-reviewer", {"findings": [
        {"class": "blocking", "headline": "h", "body": "b"},
        {"class": "nit", "headline": "h", "body": "b"},
        {"class": "advisory", "headline": "h", "body": "b"}]})
    assert entries == []
    assert found == [
        "findings 1: a blocking finding says its disposition, as a "
        "`proposal` or `options`",
        "findings 2: `class` is blocking, operator or advisory, not 'nit'"]
    entries, found = faults("plan-reviewer", {"findings": [
        {"class": "advisory", "headline": "h", "body": "b"}]})
    assert (entries, found) == (
        [], ["handback.json holds no finding that needs a ruling"])
    entries, found = faults("plan-writer", {"questions": [
        {"headline": "Name the queue", "body": "b",
         "options": ["jobs", "work"]}]})
    assert found == []
    assert entries == [{"kind": "decision", "headline": "Name the queue",
                        "body": "b", "options": ["jobs", "work"]}]


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


def test_the_rendered_report_passes_preflight_and_the_store_does_not():
    """close-out.md is the loop's own render, left modified by an exit that
    commits nothing — the rerun after a questions exit must not refuse on
    it. The store is an agent's commit: left uncommitted, it is caught."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = DirtyGitLoop(slice_dir, [W_DONE, R_GO],
                            porcelain=" M specs/099/close-out.md\0")
        assert run_to_exit(loop) == 0
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = DirtyGitLoop(slice_dir, [],
                            porcelain=" M specs/099/close-out.json\0")
        assert run_to_exit(loop) == 2


def test_dirty_paths_parse_spaces_and_renames():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        porcelain = ("R  specs/099/new name.md\0specs/099/old.md\0"
                     " M specs/099/plan_log.txt\0"
                     "?? specs/099/a file.md\0")
        loop = DirtyGitLoop(slice_dir, [], porcelain=porcelain)
        dirty = loop._slice_dirty_paths()
        assert dirty == ["specs/099/new name.md", "specs/099/a file.md"]


def test_the_loops_lock_is_not_uncommitted_work():
    """plan.lock stays in the slice folder, emptied, once a loop lets it go
    — untracked, and the loop's own, so the rerun does not refuse on it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = DirtyGitLoop(slice_dir, [W_DONE, R_GO],
                            porcelain="?? specs/099/plan.lock\0")
        assert loop._slice_dirty_paths() == []
        assert run_to_exit(loop) == 0


# -- one plan loop per slice --------------------------------------------------
#
# A project's environments share the spec repo's mount, so the flock on
# plan.lock reaches across them where `ps` does not. A second loop is refused
# before it reads or writes anything, naming the holder from the lock's note.

@contextlib.contextmanager
def environment_id(value):
    """The pod's KUBECODER_ENVIRONMENT_ID for the block; None unsets it."""
    saved = os.environ.pop("KUBECODER_ENVIRONMENT_ID", None)
    if value is not None:
        os.environ["KUBECODER_ENVIRONMENT_ID"] = value
    try:
        yield
    finally:
        os.environ.pop("KUBECODER_ENVIRONMENT_ID", None)
        if saved is not None:
            os.environ["KUBECODER_ENVIRONMENT_ID"] = saved


def held_by(slice_dir, name, environment):
    """`name` in the slice folder, held as a live loop in `environment`
    holds it — a SliceLock of its own, beside the loop under test."""
    lock = run_loop.SliceLock(slice_dir / name)
    with environment_id(environment):
        assert lock.acquire() is None
    return lock


def folder_bytes(slice_dir):
    return {p.name: p.read_bytes() for p in slice_dir.iterdir()
            if p.is_file() and not p.name.endswith(".lock")}


def test_a_second_plan_loop_on_the_slice_is_refused_naming_the_holder():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        # what the first loop has written so far
        (slice_dir / "plan_state.json").write_text('{"phase": "writing"}\n')
        (slice_dir / "plan_log.txt").write_text("[03:00:00] the first loop\n")
        before = folder_bytes(slice_dir)
        first = held_by(slice_dir, "plan.lock", "env-a")
        try:
            loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                assert run_to_exit(loop) == 2
            text = err.getvalue()
            assert "another plan loop is running this slice" in text
            assert "  environment: env-a" in text
            assert f"  host: {run_loop.socket.gethostname()}" in text
            assert f"  pid: {os.getpid()}" in text
            assert "  heartbeat: " in text
            assert "another environment" in text
            # nothing read, dispatched or written
            assert not loop.spawned and not loop.git_calls
            assert folder_bytes(slice_dir) == before
            assert run_loop.lock_held(slice_dir / "plan.lock")
        finally:
            first.release()


def test_a_plan_loop_under_a_live_run_is_refused_and_lets_its_lock_go():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        before = folder_bytes(slice_dir)
        run = held_by(slice_dir, "run.lock", "env-b")
        try:
            loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                assert run_to_exit(loop) == 2
            text = err.getvalue()
            assert f"{slice_dir / 'run.lock'} is held — a run loop is " \
                   "running this slice" in text
            assert "  environment: env-b" in text
            assert "rewrites the queue it is executing" in text
            assert not loop.spawned and not loop.git_calls
            assert folder_bytes(slice_dir) == before
            assert not run_loop.lock_held(slice_dir / "plan.lock")
        finally:
            run.release()
        # the run over, the loop walks in
        assert run_to_exit(ScriptedLoop(slice_dir, [W_DONE, R_GO])) == 0


def test_the_plan_loop_records_its_driver_and_lets_the_lock_go_at_every_exit():
    """plan_state.json says where the loop runs, on every run, and the lock
    is held for the whole run and free after it — whatever the exit. The
    loop only probes run.lock: it never creates it."""
    def look(loop):
        seen.append((run_loop.lock_held(slice_dir / "plan.lock"),
                     load_state(slice_dir)["driver"]))
        write_phases(loop)

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        seen = []
        with environment_id("env-a"):
            loop = ScriptedLoop(slice_dir, [(*W_DONE[:2], look), R_GO])
            assert run_to_exit(loop) == 0
        driver = load_state(slice_dir)["driver"]
        assert seen == [(True, driver)]
        assert driver == {"environment": "env-a",
                          "host": run_loop.socket.gethostname(),
                          "pid": os.getpid(), "started": driver["started"]}
        assert not run_loop.lock_held(slice_dir / "plan.lock")
        assert (slice_dir / "plan.lock").read_text() == ""
        assert not (slice_dir / "run.lock").exists()

    def interrupt(loop):
        raise KeyboardInterrupt

    blocked = ("plan-writer", {"outcome": "blocked", "summary": "no"})
    for script, code in [([W_Q], 4), ([blocked], 3),
                         ([(*W_DONE[:2], interrupt)], 130)]:
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir = make_slice(tmp)
            loop = ScriptedLoop(slice_dir, script)
            with contextlib.redirect_stderr(io.StringIO()), \
                    environment_id(None):
                assert run_to_exit(loop) == code
            assert not run_loop.lock_held(slice_dir / "plan.lock"), code
            assert (slice_dir / "plan.lock").read_text() == "", code
            assert load_state(slice_dir)["driver"]["environment"] is None

    # a rerun's driver replaces the one before it
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with contextlib.redirect_stderr(io.StringIO()), \
                environment_id("env-a"):
            assert run_to_exit(ScriptedLoop(slice_dir, [W_Q])) == 4
        first = load_state(slice_dir)["driver"]
        with environment_id("env-b"):
            assert run_to_exit(ScriptedLoop(slice_dir, [W_DONE, R_GO])) == 0
        rerun = load_state(slice_dir)["driver"]
        assert first["environment"] == "env-a"
        assert rerun["environment"] == "env-b"
        assert rerun["started"] != first["started"]


def status_lines(slice_dir):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        plan_loop.cmd_status(type("Args", (), {"slice_dir": str(slice_dir)})())
    return out.getvalue().splitlines()


def test_status_names_the_driver_and_whether_it_runs():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with contextlib.redirect_stderr(io.StringIO()), \
                environment_id("env-a"):
            assert run_to_exit(ScriptedLoop(slice_dir, [W_Q])) == 4
        driver = load_state(slice_dir)["driver"]
        named = (f"driver: env env-a  host {driver['host']}  "
                 f"pid {driver['pid']}  started {driver['started']}")
        assert status_lines(slice_dir)[1] == f"  {named} — not running"
        live = held_by(slice_dir, "plan.lock", "env-a")
        try:
            beat = run_loop.note_fields(
                (slice_dir / "plan.lock").read_text())["heartbeat"]
            assert status_lines(slice_dir)[1] == \
                f"  {named} — running, heartbeat {beat}"
        finally:
            live.release()
        # a plan_state.json from before the record
        state = load_state(slice_dir)
        del state["driver"]
        (slice_dir / "plan_state.json").write_text(json.dumps(state))
        assert status_lines(slice_dir)[1] == \
            "  driver: (not recorded) — not running"


def test_dispatch_passes_model_and_effort_explicitly():
    """Both planning dispatches carry the trim and the promoted MCP servers —
    `spawn_flags` is the run loop's, shared, so the planners spawn with
    fieldnotes and nothing else of the operator's."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        calls = []
        home = Path(tmp) / "home"
        home.mkdir()
        (home / ".claude.json").write_text(json.dumps({"mcpServers": {
            "fieldnotes": {"type": "http", "url": "https://fn.invalid/mcp"},
            "youtrack": {"type": "http", "url": "https://yt.invalid/mcp"},
        }}))

        loop = PlanLoop(slice_dir)
        loop._assert_agents = lambda: None
        loop.git = lambda *args: ("" if args[0] == "status"
                                  else "/specs"
                                  if args == ("rev-parse", "--show-toplevel")
                                  else "sha123")

        def fake_session(prompt, cwd, timeout, agent=None, model=None,
                         effort=None, resume_session=None, extra_env=None,
                         flags=None, progress=None, on_session=None):
            calls.append((agent, model, effort, list(flags or ())))
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
        original_home = run_loop._user_home
        plan_loop.run_kc_session = fake_session
        run_loop._user_home = lambda: home
        run_loop._PROMOTED_MCP.clear()
        try:
            code = run_to_exit(loop)
        finally:
            plan_loop.run_kc_session = original
            run_loop._user_home = original_home
            run_loop._PROMOTED_MCP.clear()
        assert code == 0
        promoted = home / run_loop.PROMOTED_MCP_FILE
        assert json.loads(promoted.read_text()) == {"mcpServers": {
            "fieldnotes": {"type": "http", "url": "https://fn.invalid/mcp"}}}
        trim = ["--disable-slash-commands", "--strict-mcp-config",
                "--mcp-config", str(promoted)]
        assert calls == [("plan-writer", "opus", "xhigh", trim),
                         ("plan-reviewer", "opus", "xhigh", trim)]


def test_dispatches_carry_the_change_discipline_pointer():
    """Every planning dispatch names the project's change-discipline doc
    (.aiworkflowrc's design_philosophy) — the planners bind plans to the
    same rules execution is held to (Triage #738: the plan roles were the
    only dispatches never told the doc exists)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / ".aiworkflowrc").write_text(
            'design_philosophy = "docs/conventions/change-discipline.md"\n')
        loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
        loop.repo_root = root
        assert run_to_exit(loop) == 4
        # the rerun's fix pass carries it too — all three prompt templates
        loop2 = ScriptedLoop(slice_dir, [W_DONE])
        loop2.repo_root = root
        assert run_to_exit(loop2) == 0
        doc = str(root / "docs/conventions/change-discipline.md")
        assert len(loop.prompts + loop2.prompts) == 3
        for role, prompt in loop.prompts + loop2.prompts:
            assert f"change-discipline doc is {doc}" in prompt, role


def test_no_design_philosophy_means_no_pointer_line():
    """No .aiworkflowrc (or none naming design_philosophy) degrades to no
    line — the plan loop reads the config for nothing else, and preflight
    owns validating it, so it must never die on it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        root = Path(tmp) / "repo"
        root.mkdir()  # no .aiworkflowrc at all
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        loop.repo_root = root
        assert run_to_exit(loop) == 0
        for role, prompt in loop.prompts:
            assert "change-discipline" not in prompt, role


# -- the exit-0 seed: Outstanding actions the plan already owes ---------------
#
# AIWF-14: a ruled push hold, and the criteria that wait on it, reached the
# report only when a completion consult happened to notice. The loop enters
# them itself at exit 0 — once, however often it reruns.

close_out = sys.modules[plan_loop.ReportError.__module__]

HOLD_SECTION = """
## Push holds

- ../HelmCharts — Ruling Q1: the chart bump rides the operator's own release.
"""


def criterion(vid, description, owed_after=None):
    item = {"id": vid, "area": "deploy", "description": description,
            "verdict": None, "rationale": "", "evidence": []}
    if owed_after is not None:
        item["owed_after"] = owed_after
    return item


def plans(holds, items):
    """A writer effect: the plan completed with `holds` as its `## Push
    holds` section, and verification.json holding `items`."""
    def effect(loop):
        loop.plan_path.write_text(PLAN_HEADER + holds + PHASE_BLOCK)
        (loop.slice_dir / "verification.json").write_text(
            json.dumps({"items": items}, indent=2) + "\n")
    return effect


def outstanding(slice_dir):
    """The actions part of `close_out.py list`."""
    view = close_out.list_view(slice_dir)
    return view.split("## decision")[0]


def entries_in_full(slice_dir):
    """Every entry in full, as `close_out.py show` prints it — the rendered
    report carries the ask alone; the body and the Provenance are the
    store's."""
    ids = [eid for eid, _ in close_out.live_entries(slice_dir, "action")]
    return close_out.show_view(slice_dir, ids)


def commits(loop):
    return [c for c in loop.git_calls if c[:1] == ("commit",)]


SEED_COMMIT = ("commit", "-m", "slice 099: seed close-out outstanding actions")


def test_a_push_hold_is_seeded_once_naming_the_criteria_owed_after_it():
    items = [criterion("V01", "The app serves the new route."),
             criterion("V02", "The dev cluster runs the new chart.",
                       owed_after="../HelmCharts"),
             criterion("V13", "Rolling back the chart restores the old "
                              "route without a manual step.",
                       owed_after="../HelmCharts/")]
    writer = ("plan-writer", {"outcome": "done", "summary": "written"},
              plans(HOLD_SECTION, items))
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        report = slice_dir / "close-out.md"
        loop = ScriptedLoop(slice_dir, [writer, R_ISSUES])
        assert run_to_exit(loop) == 4
        assert "Push HelmCharts" not in close_out.list_view(slice_dir), "exit 0 only"
        assert commits(loop) == [("commit", "-m", "slice 099: close-out report")]

        fix = ScriptedLoop(slice_dir, [writer])
        assert run_to_exit(fix) == 0
        assert outstanding(slice_dir) == (
            "## action\n"
            "A1 — Push HelmCharts by hand when its hold lifts\n"
            "    Consequence: until you push it, nothing HelmCharts deploys "
            "carries the slice, and V02, V13 stay unproven.\n")
        close_out.render_report(slice_dir)   # the run's render, which shows it
        text = report.read_text()
        assert ("**Proposal:** Push it when the hold lifts, then say so: the "
                "session settles V02, V13 after the push.") in " ".join(text.split())
        full = entries_in_full(slice_dir)
        assert ("`plan.md`'s `## Push holds` section holds `../HelmCharts`: "
                "Ruling Q1: the chart bump rides the operator's own "
                "release.") in full
        assert "stay open until the push lands" in full
        assert "- V02 — The dev cluster runs the new chart." in full
        assert "- V13 — Rolling back the chart" in full
        assert "V01" not in full
        assert ("**Provenance:** read — `plan.md`'s `## Push holds` and "
                "`verification.json`'s `owed_after`, seeded by the plan "
                "loop") in full
        assert ("add", str(slice_dir / "close-out.json")) in fix.git_calls
        assert commits(fix) == [SEED_COMMIT]
        log = (slice_dir / "plan_log.txt").read_text()
        assert "close-out A1: Push HelmCharts by hand when its hold lifts" in log

        # A rerun of the finished loop enters nothing twice, commits nothing.
        again = ScriptedLoop(slice_dir, [])
        assert run_to_exit(again) == 0
        close_out.render_report(slice_dir)
        assert report.read_text() == text
        assert not commits(again)


def test_a_github_hold_is_named_as_its_clone_without_cloning_it():
    """The run loop's push check names a `github:` target's repo by its
    scratch clone's directory; the seed names it the same, from the path
    alone — the plan loop never clones."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [])

        def no_clone(*args, **kwargs):
            raise AssertionError("the plan loop cloned")

        saved = plan_loop.github_target.ensure_clone
        plan_loop.github_target.ensure_clone = no_clone
        try:
            assert loop._held_repo_name("github:acme/Widget") == "Widget"
            assert loop._held_repo_name("github:acme/Widget.git") == "Widget"
        finally:
            plan_loop.github_target.ensure_clone = saved


def test_an_owed_criterion_no_hold_covers_gets_its_own_settle_entry():
    """A criterion owed after anything but a held repo's push is its own
    action; a held component names the code repo, as the run loop would."""
    long_wait = ("the operator rotates the Vault root token and re-runs the "
                 "cluster bootstrap by hand against the production estate")
    items = [criterion("V05", "Pods resolve the new internal zone.",
                       owed_after="the operator's DNS cutover"),
             criterion("V07", "The bootstrap reads the new token.",
                       owed_after=long_wait)]
    holds = "\n## Push holds\n\n- app — Ruling Q2: ships with the next tag.\n"
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [("plan-writer", {"outcome": "done"},
                                         plans(holds, items)), R_GO])
        loop.repo_root = Path(tmp) / "CodeRepo"
        assert run_to_exit(loop) == 0
        view = outstanding(slice_dir)
        assert view.startswith(
            "## action\n"
            "A1 — Push CodeRepo by hand when its hold lifts\n"
            "    Consequence: until you push it, nothing CodeRepo deploys "
            "carries the slice.\n"
            "A2 — Settle V05 after the operator's DNS cutover\n"
            "    Consequence: V05 stays unproven until then; the test phase "
            "does not settle it.\n"
            "A3 — Settle V07 after the operator rotates the Vault root "), view
        a3 = view.split("A3 — ")[1].split("\n")[0]
        assert len(a3) <= plan_loop.SEED_HEADLINE_WIDTH and a3.endswith(" …")
        close_out.render_report(slice_dir)   # the run's render, which shows it
        text = (slice_dir / "close-out.md").read_text()
        assert "**Proposal:** Push it when the hold lifts.\n" in text
        full = entries_in_full(slice_dir)
        for vid in ("V05", "V07"):
            # the same on every owed-after action: the store's, not the page's
            proposal = (f"**Proposal:** When that has happened, say so: the session "
                        f"settles {vid} in verification.json.")
            assert proposal in full and proposal not in text
        # the page names the criterion by its area, with what it waits on in full
        assert "## Settle V05 (deploy) after the operator's DNS cutover\n" in text
        assert f"## Settle V07 (deploy) after {long_wait}\n" in text
        assert "V05 — Pods resolve the new internal zone." in full
        assert "marks V05 owed after: the operator's DNS cutover." in full
        assert f"marks V07 owed after: {long_wait}." in full
        assert ("**Provenance:** read — `plan.md`'s `## Push holds`, seeded "
                "by the plan loop") in full
        assert commits(loop)[-1] == SEED_COMMIT
        # The shortened headline is the one the rerun looks up.
        again = ScriptedLoop(slice_dir, [])
        again.repo_root = loop.repo_root
        assert run_to_exit(again) == 0
        close_out.render_report(slice_dir)
        assert (slice_dir / "close-out.md").read_text() == text


def test_no_hold_and_nothing_owed_leaves_the_report_alone():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        seen = []

        def writer_effect(loop):
            seen.append((slice_dir / "close-out.json").read_text())
            plans("", [criterion("V01", "The app serves the new route.")])(loop)

        loop = ScriptedLoop(slice_dir, [("plan-writer", {"outcome": "done"},
                                         writer_effect), R_GO])
        assert run_to_exit(loop) == 0
        assert (slice_dir / "close-out.json").read_text() == seen[0]
        assert not (slice_dir / "close-out.md").exists()
        assert commits(loop) == [("commit", "-m", "slice 099: close-out report")]


def test_a_struck_entry_with_the_seeded_headline_is_not_entered_again():
    """Striking is how the operator or the completion consult settled it —
    a replan must not bring it back."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(
            slice_dir, "Outstanding actions",
            "Push HelmCharts by hand when its hold lifts", "pushed",
            consequence="none", provenance="read")
        close_out.strike_entry(slice_dir, "A1", "pushed 2026-09-20",
                               by="operator")
        before = (slice_dir / "close-out.json").read_text()
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "done"},
             plans(HOLD_SECTION, [criterion("V02", "Runs the new chart.",
                                            owed_after="../HelmCharts")])),
            R_GO])
        assert run_to_exit(loop) == 0
        assert (slice_dir / "close-out.json").read_text() == before
        assert not commits(loop)
        log = (slice_dir / "plan_log.txt").read_text()
        assert "close-out A1 already holds: Push HelmCharts" in log


def test_a_report_that_refuses_the_seed_is_logged_not_a_failed_plan():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "close-out.json").write_text("{ not json\n")
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "done"}, plans(HOLD_SECTION, [])),
            R_GO])
        assert run_to_exit(loop) == 0
        assert not commits(loop)
        log = (slice_dir / "plan_log.txt").read_text()
        assert "close-out entry not written (" in log
        assert "is not valid JSON" in log


def test_the_seed_commits_on_the_base_branch_only():
    """The seed writes into the shared tree like every other commit of the
    loop's: a tree moved off the base bails before anything is appended."""
    def moves_the_tree(loop):
        loop.branch = "phase/191-P3"

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "done"}, plans(HOLD_SECTION, [])),
            R_GO + (moves_the_tree,)])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "is on phase/191-P3, not main" in bail["details"]
        assert "Push HelmCharts" not in close_out.list_view(slice_dir)
        # Back on base, the rerun (phase done) seeds it.
        rerun = ScriptedLoop(slice_dir, [])
        assert run_to_exit(rerun) == 0
        assert "A1 — Push HelmCharts by hand" in close_out.list_view(slice_dir)
        assert commits(rerun) == [SEED_COMMIT]


# -- the shared spec tree ----------------------------------------------------
#
# The loop runs IN the spec repo, one working tree shared with every parallel
# session — other plan loops, run loops, the operator's own. Everything this
# loop writes (plan.md, verification.json, close-out.md)
# lands on whatever branch that tree is on.

def test_the_loop_records_the_branch_it_started_on():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        loop.branch = "trunk"
        assert run_to_exit(loop) == 0
        assert load_state(slice_dir)["base"] == "trunk"


def test_a_phase_branch_is_never_recorded_as_the_base():
    """A run loop left it there when it bailed; planning onto it would
    commit this slice's plan into another slice's work."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [])
        loop.branch = "phase/191-P3"
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "phase/191-P3, a phase branch" in bail["details"]
        assert not loop.spawned
        assert load_state(slice_dir)["base"] is None


def test_a_tree_moved_off_the_base_bails_before_the_next_dispatch():
    def moves_the_tree(loop):
        write_phases(loop)
        loop.branch = "phase/191-P3"

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(
            slice_dir, [("plan-writer", {"outcome": "done",
                                         "summary": "written"},
                         moves_the_tree), R_GO])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "is on phase/191-P3, not main" in bail["details"]
        assert [s[0] for s in loop.spawned] == ["plan-writer"]


# -- the installed-plugin and verification-key guards -----------------------

OURS = run_loop.plugin_version()


class installed:
    """installed_plugins.json in `tmp`, naming `version` for this plugin
    (None: no entry for it) beside a kubecoder install holding `skills`,
    with the loop's guard pointed at it for the `with` block. `set` rewrites
    it — the marketplace updating mid-run."""

    def __init__(self, tmp, version, skills=()):
        self.path = Path(tmp) / "installed_plugins.json"
        self.install = Path(tmp) / "cache" / "aiworkflow" / "dev"
        self.kubecoder = Path(tmp) / "cache" / "kubecoder-config" / "0.8"
        for name in skills:
            (self.kubecoder / "skills" / name).mkdir(parents=True)
            (self.kubecoder / "skills" / name / "SKILL.md").write_text(name)
        self.set(version)

    def set(self, version):
        plugins = {"kubecoder@kubecoder-config": [
            {"scope": "user", "installPath": str(self.kubecoder),
             "version": "0.8"}]}
        if version is not None:
            plugins["dev@aiworkflow"] = [{
                "scope": "user", "version": version,
                "installPath": str(self.install / version)}]
        self.path.write_text(json.dumps({"version": 2, "plugins": plugins}))

    def __enter__(self):
        self.saved = run_loop.INSTALLED_PLUGINS
        run_loop.INSTALLED_PLUGINS = self.path
        return self

    def __exit__(self, *exc):
        run_loop.INSTALLED_PLUGINS = self.saved
        return False


def test_a_plugin_version_mismatch_bails_before_the_first_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with installed(tmp, "0.0.1") as inst:
            loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
            assert run_to_exit(loop) == 3
            assert not loop.spawned
            bail = json.loads((slice_dir / "plan_bailout.json").read_text())
            assert bail["reason"] == "plugin_version"
            assert f"runs plugin {OURS}" in bail["details"]
            assert "installed plugin is 0.0.1" in bail["details"]
            assert str(inst.install / "0.0.1" / "tools" / "plan_loop.py") \
                in bail["details"]
            assert "plan_state.json" in bail["details"]

            inst.set(OURS)
            loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
            assert run_to_exit(loop) == 0, "the relaunch picks the run up"


def test_a_plugin_dir_run_passes_the_version_guard_and_says_so_once():
    """From a checkout (`--plugin-dir`), agents of the installed version are
    the run's premise: the plan loop goes on, with one line in its log."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        saved = run_loop.PLUGINS_HOME
        run_loop.PLUGINS_HOME = Path(tmp) / "plugins-home"
        try:
            with installed(tmp, "0.0.1"):
                loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
                assert run_to_exit(loop) == 0
        finally:
            run_loop.PLUGINS_HOME = saved
        said = [line for line in
                (slice_dir / "plan_log.txt").read_text().splitlines()
                if "[plugin]" in line]
        assert len(said) == 1, said
        assert f"runs plugin {OURS} from a checkout" in said[0]
        assert "load the installed 0.0.1" in said[0]


def test_the_relaunch_after_a_plugin_version_bail_needs_no_hand_cleanup():
    """The bail leaves plan_bailout.json, plan_state.json, plan_log.txt and
    the let-go plan.lock untracked in the slice folder; the relaunch from
    the installed path starts on them as they are — the real cleanliness
    parse passes the loop's own files — and clears the stale bail record
    itself."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with installed(tmp, "0.0.1") as inst:
            assert run_to_exit(ScriptedLoop(slice_dir, [W_DONE, R_GO])) == 3
            left = sorted(p.name for p in slice_dir.iterdir()
                          if p.name in plan_loop.LOOP_OWNED_FILES)
            assert left == ["plan.lock", "plan_bailout.json",
                            "plan_log.txt", "plan_state.json"]

            inst.set(OURS)
            porcelain = "".join(f"?? specs/099/{name}\0" for name in left)
            loop = DirtyGitLoop(slice_dir, [W_DONE, R_GO],
                                porcelain=porcelain)
            assert run_to_exit(loop) == 0
            assert [s[0] for s in loop.spawned] == ["plan-writer",
                                                    "plan-reviewer"]
            assert not (slice_dir / "plan_bailout.json").exists()


def test_a_matching_or_unknown_installed_plugin_proceeds():
    for version in (OURS, None, "absent"):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir = make_slice(tmp)
            with installed(tmp, version) as inst:
                if version == "absent":
                    inst.path.unlink()
                loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
                assert run_to_exit(loop) == 0, version


def install_mid_writer(writes_verdict):
    """Run the real _spawn with a writer session that updates the installed
    plugin; return (sessions run, the bail)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        sessions = []
        loop = PlanLoop(slice_dir)
        loop._assert_agents = lambda: None
        loop.git = lambda *args: (
            "" if args[0] == "status"
            else "/specs" if args == ("rev-parse", "--show-toplevel")
            else "sha123")
        with installed(tmp, OURS) as inst:

            def fake_session(prompt, cwd, timeout, agent=None, model=None,
                             effort=None, resume_session=None, extra_env=None,
                             flags=None, progress=None, on_session=None):
                sessions.append((agent, resume_session))
                write_phases(loop)
                if writes_verdict:
                    (slice_dir / "plan_writer_result_r1.json").write_text(
                        '{"outcome": "done", "summary": "ok"}')
                inst.set("9.9.9")
                return 0, type("R", (), {"session_id": "sess-1",
                                         "result_text": "",
                                         "is_error": False})()

            original = plan_loop.run_kc_session
            plan_loop.run_kc_session = fake_session
            try:
                assert run_to_exit(loop) == 3
            finally:
                plan_loop.run_kc_session = original
        return sessions, json.loads(
            (slice_dir / "plan_bailout.json").read_text())


def test_an_install_mid_run_bails_before_the_next_dispatch_or_nudge():
    """The real _spawn: the writer's pass updates the installed plugin, so
    the reviewer's dispatch — or, when the writer left no verdict, the
    verdict nudge — never goes out."""
    for writes_verdict in (True, False):
        sessions, bail = install_mid_writer(writes_verdict)
        assert sessions == [("plan-writer", None)], writes_verdict
        assert bail["reason"] == "plugin_version"
        assert "installed plugin is 9.9.9" in bail["details"]


# -- the skills the slice names (AIWF-56) -------------------------------------

def test_a_skill_the_slice_names_reaches_the_planners():
    """The planners have no Skill tool either: a skill slice.md or plan.md
    names is handed over as its installed file — both writer passes and the
    review — a blank line closing the list before the close-out line."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "slice.md").write_text(
            "# test slice\n\nThe Jenkinsfile follows "
            "`kubecoder:jenkins-pipelines`; mind `origin:main`.\n")
        with installed(tmp, OURS, skills=("jenkins-pipelines",)) as inst:
            loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
            assert run_to_exit(loop) == 4
            loop2 = ScriptedLoop(slice_dir, [W_DONE])
            assert run_to_exit(loop2) == 0
        skill = inst.kubecoder / "skills" / "jenkins-pipelines" / "SKILL.md"
        line = ("\nSkills this slice names. This session has no Skill tool: "
                "each skill is the\nfile named here — read it before the "
                "work it governs.\n"
                f"- `kubecoder:jenkins-pipelines`: {skill}\n\n"
                "The slice's close-out report is ")
        prompts = loop.prompts + loop2.prompts
        assert [role for role, _ in prompts] == [
            "plan-writer", "plan-reviewer", "plan-writer"]
        for role, prompt in prompts:
            assert prompt.count(line) == 1, role
        log = (slice_dir / "plan_log.txt").read_text()
        for label in ("[plan-writer r1]", "[plan-reviewer r1]",
                      "[plan-writer r2]"):
            assert f"{label} skills named — kubecoder:jenkins-pipelines\n" \
                in log, label


def test_a_slice_naming_no_skill_dispatches_the_planners_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with installed(tmp, OURS, skills=("jenkins-pipelines",)):
            loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
            assert run_to_exit(loop) == 0
        for role, prompt in loop.prompts:
            assert "Skills this slice names" not in prompt, role
        assert "skills named" not in (slice_dir / "plan_log.txt").read_text()


def writes_items(*items):
    def effect(loop):
        write_phases(loop)
        (loop.slice_dir / "verification.json").write_text(
            json.dumps({"items": list(items)}))
    return effect


def test_an_unknown_verification_key_bails():
    """Before the next dispatch, and before the exit-0 seed reads the file
    when the last pass wrote it."""
    unknown = dict(criterion("V02", "it works"), surprise=1)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "done", "summary": "w"},
             writes_items(criterion("V01", "fine"), unknown)), R_GO])
        assert run_to_exit(loop) == 3
        assert [s[0] for s in loop.spawned] == ["plan-writer"]
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "V02 `surprise`" in bail["details"]
        assert "V01" not in bail["details"]

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [
            W_DONE, (*R_GO, writes_items(unknown))])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "V02 `surprise`" in bail["details"]
        assert [s[0] for s in loop.spawned] == ["plan-writer", "plan-reviewer"]


def test_the_full_verification_schema_proceeds():
    item = criterion("V01", "it works", owed_after="../HelmCharts")
    assert set(item) == run_loop.VERIFICATION_ITEM_KEYS
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [
            ("plan-writer", {"outcome": "done", "summary": "w"},
             writes_items(item)), R_GO])
        assert run_to_exit(loop) == 0


# -- the GO check's tool scan (AIWF-24) -----------------------------------------

def tool_plan(tmp, *rulings):
    """A GO'd plan whose one phase targets a repo (by absolute path) whose
    manifest calls `aac-tools`, a tool the stubbed pod does not run."""
    deploy = Path(tmp) / "Deploy"
    (deploy / ".kubecoder").mkdir(parents=True)
    (deploy / ".kubecoder" / "project.yaml").write_text(
        "projects:\n  - name: root\n    test: cexec aac-tools check\n")
    block = PHASE_BLOCK.replace("Target: app", f"Target: {deploy}")
    ruled = ("\n## Driver rulings\n\n" + "".join(f"- {r}\n" for r in rulings)
             if rulings else "")

    def write(loop):
        loop.plan_path.write_text(PLAN_HEADER + ruled + block)
        (loop.slice_dir / "verification.json").write_text('{"items": []}\n')

    return ("plan-writer", {"outcome": "done", "summary": "written"}, write)


def test_go_with_a_target_calling_a_missing_tool_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [tool_plan(tmp), R_GO])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "missing_tools"
        assert "- aac-tools — called by Deploy/.kubecoder/project.yaml" \
            in bail["details"]
        assert "rerun the plan loop once the environment runs them" \
            in bail["details"]


def test_go_proceeds_past_a_repo_the_rulings_waive_whole():
    with tempfile.TemporaryDirectory() as tmp:
        deploy = Path(tmp) / "Deploy"
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [tool_plan(
            tmp, f"gate {deploy} — none — no aac-tools here",
            f"accept {deploy} lint — no aac-tools here",
            f"accept {deploy} build — no aac-tools here"), R_GO])
        saved = run_loop.load_project_dirs
        run_loop.load_project_dirs = lambda cwd: {"root": Path(cwd)}
        try:
            assert run_to_exit(loop) == 0
        finally:
            run_loop.load_project_dirs = saved


# -- the GO check's service scan (AIWF-38) --------------------------------------

def service_plan(tmp, *rulings):
    """`tool_plan`'s GO'd plan, its target repo calling no tool but
    declaring `postgres` and `s3storage` in its environment config —
    services the stubbed pod does not run."""
    step = tool_plan(tmp, *rulings)
    kubecoder = Path(tmp) / "Deploy" / ".kubecoder"
    (kubecoder / "project.yaml").write_text("projects: []\n")
    (kubecoder / "config.yaml").write_text(
        "services:\n  - postgres\n  - use: s3storage\n    expose: [9000]\n")
    return step


def test_go_with_a_sibling_needing_a_missing_service_warns_and_proceeds():
    """Another repo's config declares services for its own workspace, and
    nothing says which its gates use: logged, and a red gate there is where
    the run loop asks (AIWF-75)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [service_plan(tmp), R_GO])
        assert run_to_exit(loop) == 0
        assert not (slice_dir / "plan_bailout.json").exists()
        assert ("warning: services not held — Deploy/.kubecoder/config.yaml "
                "declares postgres, s3storage, which this pod does not run; "
                "only the host's own are held, and a gate that goes red in "
                "Deploy bails missing_services") \
            in (slice_dir / "plan_log.txt").read_text()


def host_with_services(loop, tmp):
    """Point the loop at a host repo whose environment config declares
    `postgres`, a service the stubbed pod does not run."""
    root = Path(tmp) / "repo"
    (root / ".kubecoder").mkdir(parents=True)
    (root / ".kubecoder" / "config.yaml").write_text("services:\n  - postgres\n")
    loop.repo_root = root


def host_plan(*rulings):
    """A GO'd plan whose one phase targets the host's `app`, with
    `rulings` under `## Driver rulings`."""
    ruled = ("\n## Driver rulings\n\n" + "".join(f"- {r}\n" for r in rulings)
             if rulings else "")

    def write(loop):
        loop.plan_path.write_text(PLAN_HEADER + ruled + PHASE_BLOCK)
        (loop.slice_dir / "verification.json").write_text('{"items": []}\n')

    return ("plan-writer", {"outcome": "done", "summary": "written"}, write)


def test_go_with_a_host_declaring_a_missing_service_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [host_plan(), R_GO])
        host_with_services(loop, tmp)
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "missing_services"
        assert "- postgres — declared by repo/.kubecoder/config.yaml" \
            in bail["details"]
        assert "`kc env restart` applies it" in bail["details"]
        assert "rerun the plan loop once the environment runs them" \
            in bail["details"]


def test_go_proceeds_past_a_service_repo_the_rulings_waive_whole():
    # a waived sibling is not warned about: nothing runs its suites
    with tempfile.TemporaryDirectory() as tmp:
        deploy = Path(tmp) / "Deploy"
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [service_plan(
            tmp, f"gate {deploy} — none — no postgres here",
            f"accept {deploy} lint — no postgres here",
            f"accept {deploy} build — no postgres here"), R_GO])
        saved = run_loop.load_project_dirs
        run_loop.load_project_dirs = lambda cwd: {"root": Path(cwd)}
        try:
            assert run_to_exit(loop) == 0
        finally:
            run_loop.load_project_dirs = saved
        assert "services not held" \
            not in (slice_dir / "plan_log.txt").read_text()
    # a waived host is not held; one verb left unwaived still holds it
    waivers = ("gate app — none — no postgres here",
               "accept app lint — no postgres here",
               "accept app build — no postgres here")
    for rulings, code in ((waivers, 0), (waivers[:2], 3)):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir = make_slice(tmp)
            loop = ScriptedLoop(slice_dir, [host_plan(*rulings), R_GO])
            host_with_services(loop, tmp)
            saved = run_loop.load_project_dirs
            run_loop.load_project_dirs = lambda cwd: {"app": Path(cwd)}
            try:
                assert run_to_exit(loop) == code, rulings
            finally:
                run_loop.load_project_dirs = saved


# -- the other slices' push holds, the reviewer's alone ------------------------
#
# A scratch clone is one per repo, shared by every slice that targets it: the
# reviewer is shown what the other slices in flight keep unpushed there.

OTHER_HOLDS = (
    "Push holds of the other slices in flight (each plan's `## Push holds`) "
    "—\ncommits each keeps unpushed in that repo until the operator pushes "
    "it:\n")


def sibling(tmp, rel, holds=None):
    """A folder at `<tmp>/<rel>` whose plan.md holds `holds` ((target, why)
    pairs; an empty list for a plan with no `## Push holds` section) — None
    for a folder with no plan.md at all."""
    folder = Path(tmp) / rel
    folder.mkdir(parents=True)
    if holds is not None:
        section = "".join(f"- {target} — {why}\n" for target, why in holds)
        (folder / "plan.md").write_text(
            PLAN_HEADER + ("\n## Push holds\n\n" + section if holds else "")
            + PHASE_BLOCK)
    return folder


def holding_own_push(slice_dir):
    """The loop's own plan, phased, holding a push of its own."""
    (slice_dir / "plan.md").write_text(PLAN_HEADER + HOLD_SECTION + PHASE_BLOCK)


def test_the_review_lists_the_push_holds_of_the_other_slices_in_flight():
    """A pending slice and one being planned each hold a push: the review
    names both, labelled by their folder under slices/, target and why as
    written, after the close-out line; no writer pass carries them."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        sibling(tmp, "050_x", [("github:pvginkel/StepCaDeploy",
                                "Ruling Q1: the CA rides the next release.")])
        sibling(tmp, "backlog/054_y", [("../scratch/NewsfilterDeploy",
                                        "the operator pushes it by hand.")])
        loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES])
        assert run_to_exit(loop) == 4
        loop2 = ScriptedLoop(slice_dir, [W_DONE])
        assert run_to_exit(loop2) == 0
        prompts = loop.prompts + loop2.prompts
        assert [role for role, _ in prompts] == [
            "plan-writer", "plan-reviewer", "plan-writer"]
        block = (
            plan_loop.dispatch_line(loop.report_path) + "\n\n" + OTHER_HOLDS
            + "- 050_x: github:pvginkel/StepCaDeploy — Ruling Q1: the CA "
              "rides the next release.\n"
            + "- backlog/054_y: ../scratch/NewsfilterDeploy — the operator "
              "pushes it by hand.\n"
            + "\nWrite your review to ")
        assert prompts[1][1].count(block) == 1
        for role, prompt in (prompts[0], prompts[2]):
            assert "Push holds of the other slices" not in prompt, role
            assert "StepCaDeploy" not in prompt, role
        log = (slice_dir / "plan_log.txt").read_text()
        assert ("[plan-reviewer r1] other slices' push holds — 2 from 2 "
                "slice(s)\n") in log


def test_only_the_other_pending_and_backlog_slices_holds_are_listed():
    """The loop's own holds, a slice holding nothing, a slice folder with no
    plan, a folder that is no slice, and the completed and deferred slices
    contribute nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        holding_own_push(slice_dir)
        sibling(tmp, "050_x", [("app", "held for the release.")])
        sibling(tmp, "051_no_holds", [])
        sibling(tmp, "052_no_plan")
        sibling(tmp, "notes", [("../NotesRepo", "not a slice.")])
        sibling(tmp, "backlog/notes", [("../BacklogNotes", "not a slice.")])
        sibling(tmp, "completed/040_z", [("../DoneRepo", "shipped.")])
        sibling(tmp, "deferred/041_w", [("../LaterRepo", "parked.")])
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        [(role, reviewer)] = loop.prompts
        assert role == "plan-reviewer"
        assert (OTHER_HOLDS + "- 050_x: app — held for the release.\n\n"
                "Write your review to ") in reviewer
        for absent in ("HelmCharts", "051_no_holds", "052_no_plan",
                       "NotesRepo", "BacklogNotes", "DoneRepo", "LaterRepo"):
            assert absent not in reviewer, absent
        log = (slice_dir / "plan_log.txt").read_text()
        assert ("[plan-reviewer r1] other slices' push holds — 1 from 1 "
                "slice(s)\n") in log


def test_a_slice_planned_in_the_backlog_sees_the_pending_slices_holds():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(Path(tmp) / "backlog")
        holding_own_push(slice_dir)
        sibling(tmp, "050_x", [("app", "held for the release.")])
        sibling(tmp, "backlog/054_y", [("../Other", "held too.")])
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        [(_, reviewer)] = loop.prompts
        assert (OTHER_HOLDS + "- 050_x: app — held for the release.\n"
                "- backlog/054_y: ../Other — held too.\n\n"
                "Write your review to ") in reviewer
        assert "HelmCharts" not in reviewer


def test_no_other_slice_holding_a_push_leaves_the_review_as_it_was():
    """Nothing held elsewhere renders the reviewer's prompt as before the
    block existed — the close-out line, a blank line, the review's paths —
    and logs nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        holding_own_push(slice_dir)
        sibling(tmp, "051_no_holds", [])
        sibling(tmp, "completed/040_z", [("../DoneRepo", "shipped.")])
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        [(_, reviewer)] = loop.prompts
        assert "Push holds of the other slices" not in reviewer
        assert (plan_loop.dispatch_line(loop.report_path)
                + "\n\nWrite your review to ") in reviewer
        assert reviewer == plan_loop.REVIEWER_PROMPT.format(
            slice_name=loop.slice_name, slice_dir=loop.slice_dir,
            philosophy_line=loop._philosophy_line(), skill_line="",
            close_out_line=plan_loop.dispatch_line(loop.report_path),
            other_holds_line="",
            review_path=loop.slice_dir / "plan_review_r1.md",
            findings_path=loop.slice_dir / "plan_review_r1.json",
            verdict_path=loop.slice_dir / "plan_review_result_r1.json")
        assert "push holds —" not in (slice_dir / "plan_log.txt").read_text()


# -- Pilot's halt and `stop` -------------------------------------------------

@contextlib.contextmanager
def halt_file(tmp):
    """The halt file's path for this test, pointed at by the run loop's
    module, whose `halt_requested` the plan loop asks — absent until touched."""
    path = Path(tmp) / "quota-limit-halt-requested"
    saved = run_loop.HALT_FILE
    run_loop.HALT_FILE = path
    try:
        yield path
    finally:
        run_loop.HALT_FILE = saved


def test_a_halt_at_the_start_runs_nothing():
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir = make_slice(tmp)
        halt.touch()
        loop = ScriptedLoop(slice_dir, [])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert run_to_exit(loop) == 7
        assert not loop.spawned
        assert not (slice_dir / "plan_state.json").exists()
        assert f"Halted: {halt} is present" in err.getvalue()
        assert not run_loop.lock_held(slice_dir / "plan.lock")


def test_a_halt_stops_the_loop_between_passes_and_the_rerun_takes_the_next():
    """The pass in flight finishes; the halt is met before the next one draws
    its round, so the rerun dispatches it under the number it would have had."""
    def writes_then_halts(loop):
        write_phases(loop)
        halt.touch()

    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [(*W_DONE[:2], writes_then_halts)])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert run_to_exit(loop) == 7
        state = load_state(slice_dir)
        assert state["phase"] == "reviewing"
        assert state["review_rounds"] == 0
        assert "Halted before the plan-reviewer pass" in err.getvalue()
        assert "HALTED before the plan-reviewer pass" in \
            (slice_dir / "plan_log.txt").read_text()
        record = load_state(slice_dir)["exit"]
        assert (record["code"], record["halted"]) == (
            7, "before the plan-reviewer pass")
        assert (slice_dir / "close-out.json").exists(), (
            "the report's store predates the first pass")
        assert not run_loop.lock_held(slice_dir / "plan.lock")

        halt.unlink()
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert loop.spawned == [("plan-reviewer", 1, "go")]


# A plan loop in miniature: holds plan.lock with the real note's shape, and
# on SIGINT lets it go and exits 130, as PlanLoop.run does.
PLAN_DRIVER_CHILD = """\
import fcntl, os, signal, socket, sys, time
signal.signal(signal.SIGINT, signal.default_int_handler)
fd = os.open(os.path.join(sys.argv[1], "plan.lock"), os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
os.write(fd, f"host: {socket.gethostname()}\\npid: {os.getpid()}\\n".encode())
print("ready", flush=True)
try:
    while True:
        time.sleep(0.02)
except KeyboardInterrupt:
    os.ftruncate(fd, 0)
    sys.exit(130)
"""


def stop(slice_dir):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            plan_loop.cmd_stop(type("Args", (), {"slice_dir": str(slice_dir)})())
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    raise AssertionError("cmd_stop did not exit")


def test_stop_interrupts_the_plan_loop_and_waits_for_its_lock():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        code, out, _ = stop(slice_dir)
        assert code == 1 and "no driver is running" in out
        assert "plan.lock is free" in out

        child = subprocess.Popen(
            [sys.executable, "-c", PLAN_DRIVER_CHILD, str(slice_dir)],
            stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline() == "ready\n"
            saved = run_loop.STOP_POLL
            run_loop.STOP_POLL = 0.02
            try:
                code, out, _ = stop(slice_dir)
            finally:
                run_loop.STOP_POLL = saved
            assert child.wait(timeout=10) == 130
        finally:
            child.kill()
            child.wait()
        assert code == 0, out
        assert f"sent SIGINT to the driver (pid {child.pid})" in out
        assert out.splitlines()[-1] == "stopped"
        assert not run_loop.lock_held(slice_dir / "plan.lock")


# -- `run --detach` and `wait` ------------------------------------------------

def call(cmd, **args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cmd(type("Args", (), args)())
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    raise AssertionError(f"{cmd.__name__} did not exit")


def wait(slice_dir, for_seconds=0):
    return call(plan_loop.cmd_wait, slice_dir=str(slice_dir),
                for_seconds=for_seconds)


@contextlib.contextmanager
def patched(module, **attrs):
    saved = {name: getattr(module, name) for name in attrs}
    for name, value in attrs.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def plan_record(tmp, exit_=None):
    slice_dir = Path(tmp) / "099_test_slice"
    slice_dir.mkdir()
    state = {"slice": slice_dir.name, "phase": "adjudicating"}
    if exit_ is not None:
        state["exit"] = exit_
    (slice_dir / "plan_state.json").write_text(json.dumps(state))
    return slice_dir


def test_wait_answers_with_the_exit_and_what_it_leaves():
    """The plan loop's `wait` is the run loop's signal on plan.lock and
    plan_state.json: the exit and, by it, the document to register, the bail
    record, or where a halt stopped — nothing a session reads to decide."""
    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = wait(Path(tmp) / "nope")
        assert code == 2 and "not found" in err
        (Path(tmp) / "099_x").mkdir()
        code, _, err = wait(Path(tmp) / "099_x")
        assert code == 2 and "never started" in err
    cases = [
        ({"code": 4, "ts": "t", "reason": "review",
          "document": "/specs/slices/backlog/099_x/asks/2-plan-review.md"},
         ["ended: exit 4", "reason: review",
          "document: /specs/slices/backlog/099_x/asks/2-plan-review.md"]),
        ({"code": 7, "ts": "t", "halted": "before the plan-writer fix pass"},
         ["ended: exit 7", "halted: before the plan-writer fix pass"]),
        ({"code": 0, "ts": "t"}, ["ended: exit 0"]),
    ]
    for record, lines in cases:
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = wait(plan_record(tmp, record))
            assert (code, out.splitlines()) == (0, lines), record
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = plan_record(tmp, {"code": 3, "ts": "t", "reason": "blocked"})
        code, out, _ = wait(slice_dir)
        assert out.splitlines() == [
            "ended: exit 3", "reason: blocked",
            f"bailout: {os.path.abspath(slice_dir / 'plan_bailout.json')}"]


def test_wait_re_arms_while_the_loop_runs_and_relaunches_one_gone():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = plan_record(tmp)
        where = os.path.abspath(slice_dir)
        fd = os.open(slice_dir / "plan.lock", os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            code, out, _ = wait(slice_dir)
        finally:
            os.close(fd)
        assert code == run_loop.WAIT_RUNNING
        assert out.splitlines() == [
            "running", f"next: python3 {plan_loop.SCRIPT} wait {where}"]
        code, out, _ = wait(slice_dir)
        assert code == run_loop.WAIT_KILLED
        assert out.splitlines() == [
            "gone: the driver left no exit record",
            f"next: python3 {plan_loop.SCRIPT} run {where} --detach"]


def test_run_detach_names_the_plan_loops_own_stop_and_wait():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        with patched(run_loop, detach=lambda body, log: (4242, 0, "")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                plan_loop.cmd_run(type("Args", (), {
                    "slice_dir": str(slice_dir), "verbose": False,
                    "step": None, "detach": True})())
        lines = out.getvalue().splitlines()
        assert lines[1] == ("driver detached: pid 4242 — it outlives this "
                            "shell; `plan_loop.py stop` interrupts it")
        assert lines[2] == (f"next: python3 {plan_loop.SCRIPT} wait "
                            f"{os.path.abspath(slice_dir)}")


def test_a_detached_plan_loop_runs_through_the_real_handshake():
    """Detached, the loop's refusal comes back as the caller's exit, and a
    loop that starts is waited on to its exit record."""
    def detached(loop):
        def body(started):
            loop.on_start = started
            loop.run()
        return run_loop.detach(body, loop.log_path)

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        pid, code, text = detached(ScriptedLoop(slice_dir, [W_DONE, R_GO]))
        assert code == 0 and pid, text
        with patched(run_loop, WAIT_POLL=0.02):
            code, out, _ = wait(slice_dir, for_seconds=30)
        assert (code, out.splitlines()) == (0, ["ended: exit 0"])
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "plan.md").unlink()
        pid, code, text = detached(ScriptedLoop(slice_dir, []))
        assert (pid, code) == (None, 2) and "does not exist" in text


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
