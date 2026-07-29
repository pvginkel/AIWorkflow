"""Tests for plan_loop.PlanLoop — the bounded plan write/review loop.

Sessions and git are faked: each test scripts the sequence of (role, verdict)
pairs it expects the loop to request and asserts on transitions, exits, the
persisted plan_state.json, and verification seeding. No kc session is created,
no claude process is spawned.

Run: `python3 plugins/dev/tools/test_plan_loop.py` or via pytest.
"""

import contextlib
import importlib.util
import json
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "plan_loop", Path(__file__).resolve().parent / "plan_loop.py"
)
plan_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan_loop)
PlanLoop = plan_loop.PlanLoop
VERDICTS = plan_loop.VERDICTS
REVIEW_BUDGET = plan_loop.REVIEW_BUDGET


class ScriptedLoop(PlanLoop):
    """PlanLoop with _spawn replaced by a script of steps.

    A step is `(role, verdict)` or `(role, verdict, effect)`, where `effect` is
    called with the loop and stands in for what the session would have written
    to the slice folder.
    """

    def __init__(self, slice_dir, script):
        super().__init__(Path(slice_dir))
        self.script = list(script)
        self.spawned = []   # (role, round, outcome)
        self.prompts = []   # (role, prompt)
        self.git_calls = []  # every git invocation, as its argv tuple

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
        self.prompts.append((role, prompt))
        self.spawned.append((role, round_, verdict["outcome"]))
        self._record(role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1)
        if len(step) > 2:
            step[2](self)
        return verdict


def make_slice(tmp, tasks=()):
    slice_dir = Path(tmp) / "099_test_slice"
    slice_dir.mkdir(parents=True)
    (slice_dir / "slice.md").write_text("# test slice\n")
    (slice_dir / "acceptance_criteria.json").write_text(json.dumps({
        "criteria": [
            {"id": "CT-01", "area": "app", "description": "first"},
            {"id": "CT-02", "area": "web", "description": "second"},
        ]}))
    for name in tasks:
        tdir = slice_dir / "tasks" / name
        tdir.mkdir(parents=True)
        (tdir / "task.json").write_text("{}")
    return slice_dir


def write_plan(slice_dir, task, text):
    """A task folder with a plan.md — what the cross-reference lint reads."""
    tdir = slice_dir / "tasks" / task
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "task.json").write_text("{}")
    (tdir / "plan.md").write_text(text)


def run_to_exit(loop, grant=0, reopen=False):
    try:
        loop.run(grant=grant, reopen=reopen)
    except SystemExit as e:
        return e.code
    raise AssertionError("run() must exit")


def load_state(slice_dir):
    return json.loads((slice_dir / "plan_state.json").read_text())


W_DONE = ("plan-writer", {"outcome": "done", "summary": "written"})
W_Q = ("plan-writer", {"outcome": "questions", "summary": "need a ruling"})
R_GO = ("plan-reviewer", {"outcome": "go", "material": 0, "needs_ruling": 0,
                          "hygiene": 0, "summary": "clean"})
R_GO_HYG = ("plan-reviewer", {"outcome": "go", "material": 0,
                              "needs_ruling": 0, "hygiene": 2,
                              "summary": "prose only"})
R_ISSUES = ("plan-reviewer", {"outcome": "issues", "material": 2,
                              "needs_ruling": 0, "hygiene": 1,
                              "summary": "two material"})
R_Q = ("plan-reviewer", {"outcome": "questions", "material": 1,
                         "needs_ruling": 1, "hygiene": 0,
                         "summary": "undecided semantics"})

W_LINT_NOOP = ("plan-writer", {"outcome": "done", "summary": "nothing fixed"})


# -- grounding_check.py stand-ins -------------------------------------------
#
# The loop reaches the checker through grounding_dispatch.run_check; these
# build reports in the checker's published JSON shape (legacy · stamp ·
# entries[].status/repaired · summary · pruned) so the tests pin the
# integration, not the checker's internals.

_UNSET = object()

LEGACY_REPORT = {
    "legacy": True, "stamp": None, "entries": [], "commits_since": {},
    "plan_citations": {"total": 0, "invalid": [],
                       "files_touched_since_stamp": 0},
    "pruned": [], "tier": 0,
    "summary": "grounding: legacy ledger — no mechanical check",
}


def ledger_entry(id_, status="OK", repaired=False,
                 file="app/api.py", line=12):
    return {"id": id_, "claim": "a claim", "file": file, "cited_line": line,
            "cited_end": line, "anchor": "anchor", "status": status,
            "new_line": None, "repaired": repaired}


def make_report(entries=(), stamp=None, pruned=(), summary="grounding: fine"):
    return {
        "legacy": False, "stamp": stamp or {"MyApp": "1a2b3c4d5e6f7890"},
        "entries": list(entries), "commits_since": {"MyApp": 2},
        "plan_citations": {"total": 3, "invalid": [],
                           "files_touched_since_stamp": 1},
        "pruned": list(pruned), "tier": 0, "summary": summary,
    }


@contextlib.contextmanager
def checker(read=_UNSET, repair=_UNSET, prune=_UNSET):
    """Replace the loop's grounding_dispatch.run_check with a scripted
    responder, keyed by what the loop asks for: `repair` at every
    writer/reviewer dispatch, `prune` at GO, a plain read for the lint's ledger
    read. Unset kinds answer with a legacy report; an explicit None is a
    checker that produced nothing. Yields the recorded call kinds, in order."""
    calls = []
    by_kind = {"prune": prune, "repair": repair, "read": read}

    def responder(slice_dir, *, task=None, repair=False, prune=False):
        kind = "prune" if prune else "repair" if repair else "read"
        calls.append(kind)
        report = by_kind[kind]
        return LEGACY_REPORT if report is _UNSET else report

    original = plan_loop.run_check
    plan_loop.run_check = responder
    try:
        yield calls
    finally:
        plan_loop.run_check = original


@contextlib.contextmanager
def ledger_commits():
    """Record the messages the loop commits grounding.md under. The commit
    itself belongs to grounding_dispatch (stage AND commit by name, tested
    there); what the loop owns is when it fires and what it says."""
    messages = []
    original = plan_loop.commit_ledger

    def recorder(slice_dir, message):
        messages.append(message)
        return True

    plan_loop.commit_ledger = recorder
    try:
        yield messages
    finally:
        plan_loop.commit_ledger = original


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
        items = json.loads(
            (slice_dir / "verification.json").read_text())["items"]
        assert [i["id"] for i in items] == ["V01", "V02"]
        assert items[0]["description"] == "CT-01: first"
        assert all(i["source"] == "ac" for i in items)


def test_review_issues_then_go():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_ISSUES, W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        assert not loop.script
        assert load_state(slice_dir)["review_rounds"] == 2
        fix_prompt = loop.prompts[2][1]
        assert "plan_review_r1.md" in fix_prompt


def test_budget_exhausted_then_grant():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        # Spend exactly the default budget: every review comes back issues, so
        # the round after the last one bails. Derived from REVIEW_BUDGET rather
        # than pinned, so raising the default does not re-break this test.
        loop = ScriptedLoop(
            slice_dir, [W_DONE] + [R_ISSUES, W_DONE] * REVIEW_BUDGET)
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "review_budget"
        state = load_state(slice_dir)
        assert state["review_rounds"] == REVIEW_BUDGET
        # The fixed breakdown awaits its confirming round; the operator grants.
        loop2 = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop2, grant=1) == 0
        assert not (slice_dir / "plan_bailout.json").exists()
        state = load_state(slice_dir)
        assert state["review_budget"] == REVIEW_BUDGET + 1
        assert state["review_rounds"] == REVIEW_BUDGET + 1


def test_reviewer_questions_pause_and_resume():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_Q])
        assert run_to_exit(loop) == 4
        state = load_state(slice_dir)
        assert state["phase"] == "questions" and state["pending_review"] == 1
        # Rulings logged to qa_log.md; the rerun fixes first, then re-reviews.
        loop2 = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop2) == 0
        assert loop2.spawned[0][0] == "plan-writer"
        assert "plan_review_r1.md" in loop2.prompts[0][1]


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
        assert load_state(slice_dir)["pending_questions"] is None


def test_hygiene_pass_runs_unreviewed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO_HYG, W_DONE])
        assert run_to_exit(loop) == 0
        assert not loop.script
        reviews = [s for s in loop.spawned if s[0] == "plan-reviewer"]
        assert len(reviews) == 1, "hygiene findings must not buy a re-review"
        hygiene_prompt = loop.prompts[2][1]
        assert "hygiene" in hygiene_prompt and "plan_review_r1.md" in hygiene_prompt
        # The pass is line-scoped: research inside it is a material round in
        # disguise, and it carries no grounding freshness line to invite one.
        assert "no new research" in hygiene_prompt
        assert "Deterministic fact from the loop" not in hygiene_prompt
        assert plan_loop.GROUNDING_LEGACY_LINE not in hygiene_prompt


def test_existing_breakdown_enters_at_review():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, tasks=("01_first",))
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert loop.spawned[0][0] == "plan-reviewer"


def test_seed_preserves_qa_corrections():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "verification.json").write_text(json.dumps({"items": [
            {"id": "V01", "source": "ac", "area": "app",
             "description": "CT-01: stale", "verdict": None,
             "rationale": "", "evidence": []},
            {"id": "V02", "source": "qa_correction", "area": "web",
             "description": "direction change", "verdict": None,
             "rationale": "", "evidence": []},
        ]}))
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        items = json.loads(
            (slice_dir / "verification.json").read_text())["items"]
        assert [i["source"] for i in items] == ["ac", "ac", "qa_correction"]
        assert items[0]["description"] == "CT-01: first"
        assert items[2]["id"] == "V03"
        assert items[2]["description"] == "direction change"


def test_reopen_after_done():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        # New rulings logged after the GO re-enter via a fix pass and get a
        # confirming review round on top of the spent budget.
        loop2 = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop2, reopen=True) == 0
        assert loop2.spawned[0][0] == "plan-writer"
        assert "plan_review_r1.md" in loop2.prompts[0][1]
        state = load_state(slice_dir)
        assert state["review_budget"] == REVIEW_BUDGET + 1
        assert state["review_rounds"] == 2
        assert state["phase"] == "done"


def test_reopen_requires_done():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_Q])
        assert run_to_exit(loop) == 4
        loop2 = ScriptedLoop(slice_dir, [])
        assert run_to_exit(loop2, reopen=True) == 2


def test_writer_blocked_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(
            slice_dir,
            [("plan-writer", {"outcome": "blocked", "summary": "no specs"})])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "blocked" and "no specs" in bail["details"]


def test_missing_slice_md_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "099_empty"
        slice_dir.mkdir()
        loop = ScriptedLoop(slice_dir, [])
        assert run_to_exit(loop) == 2


def test_dirty_slice_folder_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [])
        real_git = loop.git

        def dirty_git(*args):
            if args[0] == "status":
                return " M qa_log.md"
            return real_git(*args)

        loop.git = dirty_git
        assert run_to_exit(loop) == 2
        assert not (slice_dir / "plan_state.json").exists()


def _loop_with_status(slice_dir, porcelain_z):
    """A loop whose `git status` returns a scripted -z porcelain payload."""
    loop = ScriptedLoop(slice_dir, [])
    real_git = loop.git

    def scripted_git(*args):
        if args[0] == "status":
            return porcelain_z
        return real_git(*args)

    loop.git = scripted_git
    return loop


def test_loop_owned_files_are_not_dirty():
    # The loop writes plan_log.txt/plan_state.json into the slice dir it then
    # checks; reading its own output as agent work made the loop unable to
    # pass its own preflight on any rerun.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = _loop_with_status(
            slice_dir,
            "?? slices/099_test_slice/plan_log.txt\0"
            "?? slices/099_test_slice/plan_state.json\0"
            "?? slices/099_test_slice/plan_bailout.json\0",
        )
        assert loop._slice_dirty_paths() == []
        assert loop._slice_dirty() is False


def test_real_work_is_still_dirty_alongside_loop_files():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = _loop_with_status(
            slice_dir,
            "?? slices/099_test_slice/plan_log.txt\0"
            " M slices/099_test_slice/tasks/01_x/plan.md\0"
            "?? slices/099_test_slice/plan_state.json\0",
        )
        assert loop._slice_dirty_paths() == [
            "slices/099_test_slice/tasks/01_x/plan.md"
        ]
        assert loop._slice_dirty() is True


def test_dirty_paths_parse_spaces_and_renames():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        # -z keeps a spaced path in one entry; a rename emits its origin as a
        # following entry, which must be consumed rather than counted.
        loop = _loop_with_status(
            slice_dir,
            "R  slices/099_test_slice/new name.md\0"
            "slices/099_test_slice/old name.md\0"
            "?? slices/099_test_slice/plan_log.txt\0",
        )
        assert loop._slice_dirty_paths() == [
            "slices/099_test_slice/new name.md"
        ]


def test_loop_owned_files_pass_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        loop = _loop_with_status(
            slice_dir, "?? slices/099_test_slice/plan_log.txt\0")
        loop.script = [("plan-writer", {"outcome": "done"}),
                       ("plan-reviewer", {"outcome": "go"})]
        assert run_to_exit(loop) == 0
        assert loop.state["phase"] == "done"


def test_protocol_failure_detail_reports_rc_and_verdict_separately():
    # Shared with the task runner (imported from task_runner.py); pinned here
    # because the loop's bail details are built from it.
    detail = plan_loop._protocol_failure_detail
    # A valid verdict written before a SIGTERM (rc=143) must read as a killed
    # process, not a verdict-protocol violation.
    msg = detail("plan-writer", 143, {"outcome": "done"}, "verdict.json",
                 valid=True, nudged=False)
    assert "rc=143" in msg
    assert "valid outcome 'done'" in msg
    assert "invalid outcome" not in msg

    bad = detail("plan-writer", 0, {"outcome": "banana"}, "verdict.json",
                 valid=False, nudged=True)
    assert "invalid outcome 'banana'" in bad
    assert "after one nudge" in bad

    missing = detail("plan-writer", 1, None, "verdict.json", valid=False,
                     nudged=False)
    assert "missing/unparseable" in missing
    assert "invalid outcome" not in missing


# -- grounding freshness line ------------------------------------------------

def test_legacy_ledger_line_reaches_writer_and_reviewer():
    with tempfile.TemporaryDirectory() as tmp, checker() as calls:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        assert [role for role, _ in loop.prompts] == ["plan-writer",
                                                      "plan-reviewer"]
        for _, prompt in loop.prompts:
            assert plan_loop.GROUNDING_LEGACY_LINE in prompt
        # One repairing check per dispatch, both before the session.
        assert calls.count("repair") == 2


def test_clean_ledger_line_states_the_stamp_without_drift():
    report = make_report(
        entries=[ledger_entry("G-001"), ledger_entry("G-002")],
        summary="grounding: 2 entries: 2 OK")
    with tempfile.TemporaryDirectory() as tmp, checker(repair=report):
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        for _, prompt in loop.prompts:
            assert "grounding.md was verified at MyApp@1a2b3c4d5e6f;" in prompt
            assert "grounding: 2 entries: 2 OK" in prompt
            assert "scope any Explore dispatches to declared gaps, never" in prompt
            assert "no longer anchor" not in prompt
            assert plan_loop.GROUNDING_LEGACY_LINE not in prompt


def test_drifted_entries_are_named_in_the_dispatch_line():
    report = make_report(entries=[
        ledger_entry("G-001"),
        ledger_entry("G-004", status="MISSING",
                     file="app/api.py", line=88),
        ledger_entry("G-009", status="GONE", file="web/gone.ts", line=3),
    ])
    with tempfile.TemporaryDirectory() as tmp, checker(repair=report):
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        prompt = loop.prompts[0][1]
        assert ("These entries no longer anchor and are unverified: "
                "G-004 MISSING (app/api.py:88), "
                "G-009 GONE (web/gone.ts:3)." in prompt)
        assert "declared gaps and the drift listed above, never" in prompt
        assert "G-001" not in prompt


def test_repair_commits_grounding_md():
    report = make_report(entries=[
        ledger_entry("G-001", status="MOVED", repaired=True),
        ledger_entry("G-002"),
    ])
    with tempfile.TemporaryDirectory() as tmp, checker(repair=report), \
            ledger_commits() as messages:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        # one per dispatch, since the stub keeps reporting the repair
        assert messages == [
            "grounding: repair drifted citations (plan loop)"] * 2


def test_unrepaired_check_commits_nothing():
    report = make_report(entries=[ledger_entry("G-001"),
                                  ledger_entry("G-002", status="MISSING")])
    with tempfile.TemporaryDirectory() as tmp, checker(repair=report), \
            ledger_commits() as messages:
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        assert messages == []


def test_checker_failure_falls_back_to_the_legacy_line():
    # A checker that produces no report (crash, timeout, exit 2) must not end
    # the planning cycle.
    with tempfile.TemporaryDirectory() as tmp, checker(read=None, repair=None,
                                                       prune=None):
        slice_dir = make_slice(tmp)
        loop = ScriptedLoop(slice_dir, [W_DONE, R_GO])
        assert run_to_exit(loop) == 0
        assert plan_loop.GROUNDING_LEGACY_LINE in loop.prompts[0][1]
        assert load_state(slice_dir)["phase"] == "done"


# -- cross-reference lint + prune at GO --------------------------------------

def test_lint_accepts_defined_ids():
    ledger = make_report(entries=[ledger_entry("G-001")])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger):
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01 [G-001].\n")
        write_plan(slice_dir, "02_second", "Covers CT-02 [G-001].\n")
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert not loop.script
        assert [s[0] for s in loop.spawned] == ["plan-reviewer"]


def test_lint_catches_a_dangling_ct_and_fixes_it_in_one_pass():
    # Slice 110: CT-34 was cited by two plans and defined nowhere; the lint
    # catches it before the loop exits instead of costing a --reopen cycle.
    ledger = make_report(entries=[ledger_entry("G-001")])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger):
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01 and CT-34 [G-001].\n")
        write_plan(slice_dir, "02_second", "Also CT-34.\n")

        def fix(_loop):
            write_plan(slice_dir, "01_first", "Covers CT-01 [G-001].\n")
            write_plan(slice_dir, "02_second", "Also CT-02.\n")

        loop = ScriptedLoop(slice_dir, [R_GO, W_LINT_NOOP + (fix,)])
        assert run_to_exit(loop) == 0
        assert not loop.script
        lint_prompt = loop.prompts[-1][1]
        assert ("CT-34 (cited by tasks/01_first/plan.md, "
                "tasks/02_second/plan.md)" in lint_prompt)
        assert "CT-01" not in lint_prompt
        state = load_state(slice_dir)
        # The lint pass is a writer pass that buys no review round.
        assert state["review_rounds"] == 1 and state["writer_rounds"] == 1
        assert [s[0] for s in loop.spawned] == ["plan-reviewer", "plan-writer"]
        assert (slice_dir / "verification.json").exists()


def test_lint_catches_a_dangling_g():
    ledger = make_report(entries=[ledger_entry("G-001"),
                                  ledger_entry("G-002")])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger):
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01 [G-002] [G-007].\n")

        def fix(_loop):
            write_plan(slice_dir, "01_first", "Covers CT-01 [G-002].\n")

        loop = ScriptedLoop(slice_dir, [R_GO, W_LINT_NOOP + (fix,)])
        assert run_to_exit(loop) == 0
        lint_prompt = loop.prompts[-1][1]
        assert "G-007 (cited by tasks/01_first/plan.md)" in lint_prompt
        assert "G-002" not in lint_prompt


def test_lint_skips_the_g_check_on_a_legacy_ledger():
    with tempfile.TemporaryDirectory() as tmp, checker():
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01 [G-777].\n")
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert [s[0] for s in loop.spawned] == ["plan-reviewer"]


def test_dangling_ids_surviving_the_fix_pass_bail():
    ledger = make_report(entries=[ledger_entry("G-001")])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger):
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-34 [G-001].\n")
        loop = ScriptedLoop(slice_dir, [R_GO, W_LINT_NOOP])
        assert run_to_exit(loop) == 3
        bail = json.loads((slice_dir / "plan_bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "CT-34 (cited by tasks/01_first/plan.md)" in bail["details"]
        # A bail before seeding: the breakdown is not handed on as complete.
        assert not (slice_dir / "verification.json").exists()


def test_prune_runs_after_the_lint_and_commits_what_it_dropped():
    ledger = make_report(entries=[ledger_entry("G-001")])
    pruned = make_report(entries=[ledger_entry("G-001")],
                         pruned=["G-005", "G-006"])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger,
                                                       prune=pruned) as calls, \
            ledger_commits() as messages:
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01, CT-02 [G-001].\n")
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert calls[-1] == "prune", "the prune is the last check at GO"
        assert "grounding: prune entries no plan cites" in messages


def test_prune_that_dropped_nothing_commits_nothing():
    ledger = make_report(entries=[ledger_entry("G-001")])
    with tempfile.TemporaryDirectory() as tmp, checker(read=ledger,
                                                       repair=ledger,
                                                       prune=ledger) as calls, \
            ledger_commits() as messages:
        slice_dir = make_slice(tmp)
        write_plan(slice_dir, "01_first", "Covers CT-01, CT-02 [G-001].\n")
        loop = ScriptedLoop(slice_dir, [R_GO])
        assert run_to_exit(loop) == 0
        assert "prune" in calls
        assert messages == []


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
