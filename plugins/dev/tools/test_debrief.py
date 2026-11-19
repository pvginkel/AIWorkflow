"""Tests for debrief — a loop's debrief file: each dispatch's entry, its
section and round read off the step it ran under, the why on the entry that
opens a round, and the file appended in order.

Stdlib only; runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_debrief.py` or via pytest.
"""

import importlib.util
import io
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_spec = importlib.util.spec_from_file_location(
    "debrief", Path(__file__).resolve().parent / "debrief.py"
)
debrief = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(debrief)


def step(code, label, state="done", why=None):
    s = {"code": code, "label": label, "state": state}
    if why is not None:
        s["why"] = why
    return s


RUN = [
    step("P3.code", "P3 · The sessions"),
    step("P3.review", "P3 · review"),
    step("P3.code-2", "P3 · code 2", why="The gate went red: app test"),
    step("P3.review-2", "P3 · review 2", state="active"),
    step("sweep", "Gate sweep", state="pending"),
]


def placed(entry):
    return (entry["section"], entry["round"], entry.get("why"),
            entry["step"])


def test_an_entry_is_placed_by_the_step_it_ran_under():
    # a phase's entries are its first step's label, every round of it
    for code, want in (("P3.code", ("P3 · The sessions", 1, None, "P3.code")),
                       ("P3.review-2",
                        ("P3 · The sessions", 2, None, "P3.review-2"))):
        assert placed(debrief.make_entry([], RUN, code, "Code writer",
                                         60)) == want
    # a step of no phase is its kind's section, its round off its code
    for code, section in (("sweep-2", "Completion check"),
                          ("consult-3", "Completion check"),
                          ("test", "Test phase"), ("docs", "Doc phase"),
                          ("wrap-up", "Wrap-up"), ("write-2", "The plan"),
                          ("review", "The plan")):
        entry = debrief.make_entry([], [], code, "Someone", 1)
        assert entry["section"] == section, code
        assert entry["round"] == int(code.rpartition("-")[2]
                                     if code[-1].isdigit() else 1), code
    # a phase not on the list is named by its id
    assert debrief.make_entry([], [], "P9.code", "Code writer",
                              1)["section"] == "P9"


def test_the_why_goes_on_the_first_entry_of_the_step_that_carries_it():
    first = debrief.make_entry([], RUN, "P3.code-2", "Code writer", 540,
                               words="Fair catch.")
    assert first == {"section": "P3 · The sessions", "round": 2,
                     "role": "Code writer", "duration": 540,
                     "words": "Fair catch.",
                     "why": "The gate went red: app test",
                     "step": "P3.code-2"}
    # the round dispatched again under its step gives no why a second time
    again = debrief.make_entry([first], RUN, "P3.code-2", "Code writer", 30)
    assert "why" not in again
    # a step inside the round carries none
    assert "why" not in debrief.make_entry([first], RUN, "P3.review-2",
                                           "Code reviewer", 30)


def test_an_entry_carries_words_or_a_result_or_neither():
    words = debrief.make_entry([], [], "test", "Test agent", 5, words="Ok.")
    assert words["words"] == "Ok." and "passed" not in words
    for passed in (True, False):
        swept = debrief.make_entry([], [], "sweep", "Gate sweep", 5,
                                   passed=passed)
        assert swept["passed"] is passed and "words" not in swept
    none = debrief.make_entry([], [], "sweep", "Gate sweep", 5)
    assert "words" not in none and "passed" not in none
    assert none["duration"] == 5 and isinstance(none["duration"], int)


def test_a_verdicts_debrief_is_its_words_as_given():
    assert debrief.words_of({"debrief": "  Went well.\n\nMostly.\n"}) \
        == "Went well.\n\nMostly."
    for verdict in (None, [], "text", {}, {"debrief": "  \n"},
                    {"debrief": ["a"]}, {"debrief": 3}):
        assert debrief.words_of(verdict) is None, verdict


def test_the_step_is_the_active_one_or_the_roles_own_where_none_is():
    assert debrief.step_of(RUN, "code-reviewer", 2, "3") == "P3.review-2"
    for role, round_, phase, code in (
            ("code-writer", 2, "4", "P4.code-2"),
            ("code-reviewer", 1, "4", "P4.review"),
            ("consult", 3, "4", "P4.review-3"),
            ("consult", 2, None, "consult-2"),
            ("test-fixer", 1, None, "consult"),
            ("sweep", 2, None, "sweep-2"),
            ("test-agent", 1, None, "test"),
            ("doc-writer", 1, None, "docs"),
            ("wrap-up", 1, None, "wrap-up"),
            ("plan-writer", 2, None, "write-2"),
            ("plan-reviewer", 1, None, "review")):
        assert debrief.step_of([], role, round_, phase) == code, role
        assert debrief.step_of(None, role, round_, phase) == code, role


def test_a_role_is_named_as_the_full_debrief_shows_it():
    assert debrief.role_name("code-writer") == "Code writer"
    assert debrief.role_name("consult", "3") == "Review consult"
    assert debrief.role_name("consult") == "Completion consult"
    assert debrief.role_name("sweep") == "Gate sweep"
    assert debrief.role_name("plan-reviewer") == "Plan reviewer"


def test_record_appends_each_dispatch_in_order_and_keeps_the_rest():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / debrief.RUN_FILE
        assert debrief.read(path) == []
        debrief.record(path, RUN, "code-reviewer", 2, 30, "3",
                       verdict={"outcome": "signoff", "debrief": "Clean."})
        data = json.loads(path.read_text())
        data["debrief"] = "The stage session's own."
        path.write_text(json.dumps(data))
        steps = [dict(s, state="done") for s in RUN[:4]] + [
            step("sweep", "Gate sweep", state="active")]
        debrief.record(path, steps, "sweep", 1, 9, passed=False)
        debrief.record(path, steps, "consult", 1, 40, verdict=None)
        data = json.loads(path.read_text())
        assert data["debrief"] == "The stage session's own."
        assert [(e["role"], e.get("words"), e.get("passed"))
                for e in data["entries"]] == [
            ("Code reviewer", "Clean.", None),
            ("Gate sweep", None, False),
            ("Completion consult", None, None)]
        assert debrief.read(path) == data["entries"]
        assert not (Path(tmp) / (debrief.RUN_FILE + ".tmp")).exists()



def test_a_salvaged_verdict_gives_the_last_entry_its_words_and_nothing_else():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / debrief.RUN_FILE
        debrief.record(path, RUN, "code-reviewer", 1, 30, "3",
                       verdict={"outcome": "signoff", "debrief": "Clean."})
        debrief.record(path, RUN, "code-writer", 2, 60, "3", verdict=None)
        data = json.loads(path.read_text())
        data["debrief"] = "The stage session's own."
        path.write_text(json.dumps(data))
        debrief.revise_words(path, {"outcome": "done"})
        assert json.loads(path.read_text()) == data
        debrief.revise_words(path, {"outcome": "done",
                                    "debrief": "Late, but there.\n"})
        revised = json.loads(path.read_text())
        assert revised["debrief"] == "The stage session's own."
        assert [e.get("words") for e in revised["entries"]] == [
            "Clean.", "Late, but there."]
        assert revised["entries"][1] == dict(data["entries"][1],
                                             words="Late, but there.")


# -- the plan preparer ----------------------------------------------------------

T0 = datetime(2026, 11, 14, 9, 0, tzinfo=timezone(timedelta(hours=1)))


def test_the_preparers_start_words_and_end_make_its_entry_first_in_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / debrief.PLAN_FILE
        debrief.ground_start(path, T0 - timedelta(hours=1))
        debrief.ground_start(path, T0)          # a dispatch again: its own
        debrief.ground_words(path, "Well grounded.\n\n")
        assert debrief.read(path) == []          # it waits under `ground`
        entry = debrief.ground_end(path, T0 + timedelta(minutes=17, seconds=5))
        assert entry == {"section": "The grounding", "round": 1,
                         "role": "Plan preparer", "duration": 1025,
                         "words": "Well grounded.", "step": "ground"}
        data = json.loads(path.read_text())
        assert data == {"entries": [entry]}
        # the loop's passes come after it, in a later work item
        debrief.record(path, [step("write", "Plan · write", "active")],
                       "plan-writer", 1, 60, verdict={"debrief": "Fine."})
        assert [e["role"] for e in debrief.read(path)] == [
            "Plan preparer", "Plan writer"]


def test_a_preparer_that_gave_no_words_has_an_entry_without_them():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / debrief.PLAN_FILE
        debrief.ground_start(path, T0)
        entry = debrief.ground_end(path, T0 + timedelta(seconds=30))
        assert "words" not in entry and entry["duration"] == 30
        try:
            debrief.ground_end(path, T0)
        except ValueError as e:
            assert "no start of the plan preparer noted" in str(e)
        else:
            raise AssertionError("an end with no start noted")
        assert len(debrief.read(path)) == 1


# -- the stage session's debrief -----------------------------------------------

STAGE_ASK = ("The loop has ended. Below are the debriefs of every agent it "
             "dispatched, in order, and the loop's own figures: phases, "
             "rounds, consults, durations, cost. Read them against the run as "
             "you watched it, then give, in your own words, how you feel the "
             "loop went. What to dwell on is yours, and so is saying that "
             "nothing is worth saying.")


def row(role, phase=None, round_=1, outcome="done", duration_s=60):
    return {"role": role, "phase": phase, "round": round_, "outcome": outcome,
            "duration_s": duration_s}


RUN_STATE = {
    "created_at": "2026-11-14T09:00:00+01:00",
    "updated_at": "2026-11-14T13:30:00+01:00",
    "known_phases": ["1", "1a"], "appended_phases": ["1a"],
    "phases": {"1": {"executor_rounds": 2, "review_rounds": 2},
               "1a": {"executor_rounds": 1, "review_rounds": 1}},
    "progress": [step("P1.code", "P1 · First"), step("P1a.code", "P1a · Fix")],
    "consult_seq": 2, "test_rounds": 1, "sweep_runs": 2,
    "history": [
        row("code-writer", "1", duration_s=1200), row("gate", "1", duration_s=0),
        row("code-reviewer", "1", outcome="issues", duration_s=300),
        row("consult", "1", duration_s=120),
        row("code-writer", "1", 2, duration_s=600),
        row("code-reviewer", "1", 2, outcome="signoff", duration_s=240),
        row("sweep", outcome="red", duration_s=600),
        row("consult", duration_s=180), row("test-fixer", duration_s=900),
        row("sweep", outcome="green", duration_s=600),
        row("code-writer", "1a", duration_s=300),
        row("code-reviewer", "1a", outcome="signoff", duration_s=60),
        row("test-agent", duration_s=1500), row("doc-writer", duration_s=2400),
        row("doc-gate", outcome="green", duration_s=630),
        row("wrap-up", duration_s=900)],
    "bailouts": [{"reason": "question"}],
    "cost": {"cost_usd": 104.29, "planner_cost_usd": 10.63, "warnings": []},
}


def test_the_stage_session_is_asked_in_the_operators_words():
    assert debrief.STAGE_PROMPT == STAGE_ASK


def test_the_runs_figures_are_its_phases_rounds_consults_durations_and_cost():
    assert debrief.run_figures(RUN_STATE) == [
        "Phases: 2, 1 appended during the run: P1a",
        "P1 · First: 2 code rounds, 2 review rounds, 41m",
        "P1a · Fix: 1 code round, 1 review round, 6m",
        "Consults: 2, 1 at a review and 1 at the completion check",
        "Completion check: 2 gate sweeps (red, green), 1 test-fixer round, 38m",
        "Test phase: 1 round, 25m",
        "Doc phase: 40m, its gate 10m",
        "Wrap-up: 15m, its gates 0s",
        "The run: 2h55m in its agents and gates, 4h30m from its start to its "
        "end",
        "Stops: 1 stop for the operator or a fix, 0 halts at Pilot's halt file",
        "Cost: $104.29 for the slice, the planning's $10.63 of it"]
    unpriced = debrief.run_figures({k: v for k, v in RUN_STATE.items()
                                    if k != "cost"})
    assert unpriced[-1] == ("Cost: not priced, as slice_cost.py --write-state "
                            "has not run")


def test_the_plans_figures_are_its_rounds_durations_and_the_folders_cost():
    state = {"created_at": "2026-11-14T09:00:00+01:00",
             "updated_at": "2026-11-14T09:25:00+01:00",
             "writer_rounds": 2, "review_rounds": 1,
             "history": [row("plan-writer", duration_s=700),
                         row("plan-reviewer", outcome="issues",
                             duration_s=600),
                         row("plan-writer", round_=2, duration_s=140)]}
    entries = [{"step": "ground", "duration": 1020}]
    assert debrief.plan_figures(state, entries, (21.333, ["a warning"])) == [
        "Plan preparer: 17m", "Plan writer: 2 passes, 14m",
        "Plan reviewer: 1 round, 10m",
        "The loop: 25m from its start to its end",
        "Cost: $21.33 for the folder, with 1 pricing warning"]
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "plan_state.json").write_text(json.dumps(state))
        assert debrief.plan_cost(Path(tmp)) == (0, [])
        assert debrief.plan_cost(Path(tmp) / "nothing") is None


def entries_file(tmp, name=debrief.RUN_FILE, **extra):
    path = Path(tmp) / name
    path.write_text(json.dumps({"entries": [
        {"section": "P1 · First", "round": 1, "role": "Code writer",
         "duration": 1200, "words": "Smooth.\n\nOne snag.", "step": "P1.code"},
        {"section": "P1 · First", "round": 2, "role": "Code writer",
         "duration": 600, "why": "The reviewer found a gap",
         "step": "P1.code-2"},
        {"section": "Completion check", "round": 1, "role": "Gate sweep",
         "duration": 600, "passed": False, "step": "sweep"},
        {"section": "Completion check", "round": 2, "role": "Gate sweep",
         "duration": 30, "step": "sweep-2"}], **extra}))
    return path


def test_the_input_is_the_ask_every_debrief_in_order_and_the_figures():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "state.json").write_text(json.dumps(RUN_STATE))
        entries_file(tmp)
        text = debrief.render_input(Path(tmp), "run")
        head, _, figures = text.partition("\nThe loop's figures:\n")
        assert head.split("\n") == [
            STAGE_ASK, "", "The debriefs, in order:", "",
            "1. P1 · First · round 1 · Code writer · 20m",
            "   Smooth.", "", "   One snag.",
            "2. P1 · First · round 2 · Code writer · 10m · no debrief",
            "   Why: The reviewer found a gap",
            "3. Completion check · round 1 · Gate sweep · 10m · failed",
            "4. Completion check · round 2 · Gate sweep · 30s · nothing ran",
            ""]
        assert figures.splitlines() == [
            f"- {line}" for line in debrief.run_figures(RUN_STATE)]


def test_the_file_goes_to_pilot_held_to_its_limits_and_without_its_steps():
    long = "x" * 5000
    data = {"debrief": "  " + "y" * 17000 + "\n", "entries": [
        {"section": "s" * 130, "round": 2, "role": "r" * 70,
         "duration": 540, "words": long, "why": "w " * 100, "step": "P1.code-2"},
        {"section": "Completion check", "round": 1, "role": "Gate sweep",
         "duration": 600, "passed": True, "step": "sweep"},
        {"section": "Completion check", "round": 2, "role": "Gate sweep",
         "duration": 30, "step": "sweep-2"},
        *({"section": "Wrap-up", "round": 1, "role": "Wrap-up",
           "duration": i, "step": "wrap-up"} for i in range(600))]}
    words, entries, figures = debrief.for_pilot(data)
    assert figures is None
    assert len(words) == 16_000 and words.endswith("…") and words[0] == "y"
    assert len(entries) == 500 and entries[-1]["duration"] == 496
    first = entries[0]
    assert set(first) == {"section", "round", "role", "duration", "words",
                          "why"}
    assert (len(first["section"]), len(first["role"]), len(first["words"]),
            len(first["why"])) == (120, 64, 4000, 120)
    assert entries[1] == {"section": "Completion check", "round": 1,
                          "role": "Gate sweep", "duration": 600,
                          "passed": True}
    assert "passed" not in entries[2] and "words" not in entries[2]
    assert all(type(e["round"]) is int and type(e["duration"]) is int
               for e in entries)
    assert debrief.for_pilot({"entries": []}) == (None, [], None)
    assert debrief.for_pilot({"debrief": " \n"})[0] is None


def test_the_figures_go_to_pilot_cut_to_its_limit_and_none_where_blank():
    figures = "- " + "f" * 9000
    _, _, held = debrief.for_pilot({"figures": "\n" + figures + "\n  "})
    assert len(held) == debrief.FIGURES_MAX == 8_000
    assert held.endswith("…") and held.startswith("- fff")
    assert debrief.for_pilot({"figures": " - Phases: 2\n"})[2] == \
        "- Phases: 2"
    for data in ({}, {"figures": ""}, {"figures": " \n\t"},
                 {"figures": None}, {"figures": ["- Phases: 2"]},
                 {"figures": 42}):
        assert debrief.for_pilot(data)[2] is None, data


def test_the_figures_text_is_what_the_input_prints_under_its_heading():
    plan_state = {"writer_rounds": 1, "review_rounds": 1, "history": []}
    saved = debrief.plan_cost
    debrief.plan_cost = lambda slice_dir: (12.5, [])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps(RUN_STATE))
            (Path(tmp) / "plan_state.json").write_text(json.dumps(plan_state))
            entries_file(tmp)
            for stage, lines in (
                    ("run", debrief.run_figures(RUN_STATE)),
                    ("plan", debrief.plan_figures(plan_state, [],
                                                  (12.5, [])))):
                text = debrief.figures_text(Path(tmp), stage)
                assert text == "\n".join(f"- {f}" for f in lines), stage
                printed = debrief.render_input(Path(tmp), stage)
                assert printed.partition("\nThe loop's figures:\n")[2] == \
                    text + "\n", stage
                assert debrief.render_input(Path(tmp), stage, text) == \
                    printed, stage
    finally:
        debrief.plan_cost = saved


class _Response:
    def __init__(self, message):
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self._body = json.dumps(message).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class JsonOpener:
    """Pilot answering each call with the next of `messages`, as JSON."""

    def __init__(self, *messages):
        self.messages = list(messages)
        self.bodies = []

    def __call__(self, request, timeout=None):
        self.bodies.append(json.loads(request.data))
        return _Response(self.messages.pop(0))


LISTED = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
    {"name": "set_progress", "inputSchema": {}},
    {"name": "register_debrief", "inputSchema": {}}]}}


def run_cli(argv, stdin="", opener=None, env=None):
    pp = debrief.pilot_progress
    saved = (sys.stdin, sys.stdout, sys.stderr, pp.os.environ, pp.OPENER)
    sys.stdin, sys.stdout, sys.stderr = (io.StringIO(stdin), io.StringIO(),
                                         io.StringIO())
    pp.os.environ = dict(env if env is not None else {
        "PILOT_TOKEN": "tok", "PILOT_MCP_URL": "http://pilot.invalid/mcp"})
    pp.OPENER = opener
    try:
        try:
            code = debrief.main(argv)
        except SystemExit as e:
            code = e.code
        return code, sys.stdout.getvalue(), sys.stderr.getvalue()
    finally:
        sys.stdin, sys.stdout, sys.stderr, pp.os.environ, pp.OPENER = saved


def test_input_keeps_the_figures_it_prints_in_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "state.json").write_text(json.dumps(RUN_STATE))
        # no debrief file yet: input makes one holding the figures alone
        code, out, _ = run_cli(["input", tmp, "--stage", "run"])
        want = debrief.figures_text(Path(tmp), "run")
        assert code == 0
        assert out == debrief.render_input(Path(tmp), "run")
        assert out.endswith("The loop's figures:\n" + want + "\n")
        path = Path(tmp) / debrief.RUN_FILE
        assert json.loads(path.read_text()) == {"figures": want}
        # a file with entries and a debrief keeps both; a re-run replaces
        path = entries_file(tmp, debrief="Given.", figures="- stale")
        kept = json.loads(path.read_text())
        code, out, _ = run_cli(["input", tmp, "--stage", "run"])
        assert code == 0 and out.endswith(want + "\n")
        assert json.loads(path.read_text()) == {**kept, "figures": want}


def test_give_keeps_the_stage_sessions_words_and_hands_the_whole_to_pilot():
    with tempfile.TemporaryDirectory() as tmp:
        path = entries_file(tmp)
        kept = json.loads(path.read_text())["entries"]
        opener = JsonOpener(LISTED, {"jsonrpc": "2.0", "id": 1, "result": {
            "content": [], "structuredContent": {"entries": 4}}})
        code, out, _ = run_cli(["give", tmp, "--stage", "run"],
                               "It went well, if slowly.\n", opener)
        assert (code, out) == (0, "Debrief handed to Pilot: 4 entries stored\n")
        data = json.loads(path.read_text())
        assert data == {"entries": kept, "debrief": "It went well, if slowly."}
        call = opener.bodies[1]["params"]
        assert call["name"] == "register_debrief"
        assert call["arguments"] == {
            "debrief": "It went well, if slowly.",
            "entries": debrief.for_pilot(data)[1]}
        assert [e["round"] for e in call["arguments"]["entries"]] == [1, 2, 1, 2]
        log = (Path(tmp) / "log.txt").read_text()
        assert log.endswith("] [debrief] Debrief handed to Pilot: 4 entries "
                            "stored\n")


def test_a_pilot_that_does_not_take_it_leaves_the_debrief_in_the_folder():
    with tempfile.TemporaryDirectory() as tmp:
        entries_file(tmp, debrief.PLAN_FILE)
        opener = JsonOpener({"jsonrpc": "2.0", "id": 1, "result": {"tools": [
            {"name": "set_progress", "inputSchema": {}}]}})
        code, out, _ = run_cli(["give", tmp, "--stage", "plan"], "Fine.",
                               opener)
        line = ("Debrief not handed to Pilot, kept in the slice's folder: this "
                "Pilot lists no register_debrief")
        assert (code, out) == (0, line + "\n")
        assert [b["method"] for b in opener.bodies] == ["tools/list"]
        assert json.loads((Path(tmp) / debrief.PLAN_FILE).read_text())[
            "debrief"] == "Fine."
        assert (Path(tmp) / "plan_log.txt").read_text().endswith(line + "\n")
        # outside Pilot: no credentials, nothing sent, the log says so
        code, out, _ = run_cli(["hand-off", tmp, "--stage", "plan"],
                               opener=JsonOpener(), env={})
        assert code == 0 and "no PILOT_TOKEN/PILOT_MCP_URL" in out


SLICE_MD = """---
issue: P-58
# the card triage filed it under
---

# The search page

The intent.

# Not the title
"""


def test_the_subject_is_the_slices_number_and_title_at_both_stages():
    with tempfile.TemporaryDirectory() as tmp:
        backlog = Path(tmp) / "slices" / "backlog" / "058_the_search_page"
        backlog.mkdir(parents=True)
        (backlog / "slice.md").write_text(SLICE_MD)
        want = "Slice 058 · The search page"
        assert debrief.subject_of(backlog) == want
        # the planning's folder, the run's and the closed one's alike
        for there in (Path(tmp) / "slices" / "058_the_search_page",
                      Path(tmp) / "slices" / "completed" / "058_the_search_page"):
            there.parent.mkdir(parents=True, exist_ok=True)
            backlog = backlog.rename(there)
            assert debrief.subject_of(there) == want
            assert debrief.subject_of(str(there) + "/") == want
        # no frontmatter, a title with spaces in it, a folder named by its
        # number alone
        (backlog / "slice.md").write_text("\n#  The   search\tpage \n")
        assert debrief.subject_of(backlog) == want
        bare = Path(tmp) / "7"
        bare.mkdir()
        (bare / "slice.md").write_text("# A\n")
        assert debrief.subject_of(bare) == "Slice 7 · A"
        # held to Pilot's limit
        (backlog / "slice.md").write_text("# " + "t" * 200 + "\n")
        subject = debrief.subject_of(backlog)
        assert len(subject) == debrief.SUBJECT_MAX == 120
        assert subject.startswith("Slice 058 · ttt") and subject.endswith("…")
        # none without a number or a title
        for name, text in (("182b_letter", "# A\n"), ("search_page", "# A\n"),
                           ("059_untitled", "---\n# A\n---\nNo title.\n"),
                           ("060_blank", "# \n"), ("061_no_file", None)):
            folder = Path(tmp) / name
            folder.mkdir()
            if text is not None:
                (folder / "slice.md").write_text(text)
            assert debrief.subject_of(folder) is None, name
        # none where slice.md cannot be read or decoded, as with no slice.md
        undecodable = Path(tmp) / "062_undecodable"
        undecodable.mkdir()
        (undecodable / "slice.md").write_bytes(b"# Caf\xe9 page\n")
        unreadable = Path(tmp) / "063_unreadable"
        (unreadable / "slice.md").mkdir(parents=True)
        for folder in (undecodable, unreadable):
            assert debrief.subject_of(folder) is None, folder.name


SUBJECT_LISTED = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
    {"name": "set_progress", "inputSchema": {}},
    {"name": "register_debrief", "inputSchema": {"properties": {
        "debrief": {}, "entries": {}, "subject": {}, "completes": {}}}}]}}
STORED = {"jsonrpc": "2.0", "id": 1, "result": {
    "content": [], "structuredContent": {"entries": 4}}}


def test_each_stage_gives_the_slice_as_its_subject_the_run_completing_it():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "058_the_search_page"
        folder.mkdir()
        (folder / "slice.md").write_text(SLICE_MD)
        for name in (debrief.PLAN_FILE, debrief.RUN_FILE):
            entries_file(folder, name, debrief="Given.")
        for argv, completes in (
                (["give", str(folder), "--stage", "plan"], False),
                (["give", str(folder), "--stage", "run"], True),
                (["hand-off", str(folder), "--stage", "plan"], False),
                (["hand-off", str(folder), "--stage", "run"], True)):
            opener = JsonOpener(SUBJECT_LISTED, STORED)
            code, out, _ = run_cli(argv, "It went.", opener)
            assert (code, out) == (
                0, "Debrief handed to Pilot: 4 entries stored\n"), argv
            arguments = opener.bodies[1]["params"]["arguments"]
            assert (arguments["subject"], arguments["completes"]) == (
                "Slice 058 · The search page", completes), argv
            assert set(arguments) == {"debrief", "entries", "subject",
                                      "completes"}
        # a Pilot that lists neither field gets the debrief as before
        opener = JsonOpener(LISTED, STORED)
        assert run_cli(["give", str(folder), "--stage", "plan"], "It went.",
                       opener)[0] == 0
        assert set(opener.bodies[1]["params"]["arguments"]) == {
            "debrief", "entries"}
        # a folder that names no subject sends neither, the planning's too,
        # and so does one whose slice.md cannot be decoded
        (folder / "slice.md").unlink()
        opener = JsonOpener(SUBJECT_LISTED, STORED)
        assert run_cli(["give", str(folder), "--stage", "plan"], "It went.",
                       opener)[0] == 0
        assert set(opener.bodies[1]["params"]["arguments"]) == {
            "debrief", "entries"}
        (folder / "slice.md").write_bytes(b"# Caf\xe9 page\n")
        opener = JsonOpener(SUBJECT_LISTED, STORED)
        assert run_cli(["hand-off", str(folder), "--stage", "run"],
                       opener=opener) == (
            0, "Debrief handed to Pilot: 4 entries stored\n", "")
        assert set(opener.bodies[1]["params"]["arguments"]) == {
            "debrief", "entries"}


FIGURES_LISTED = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [
    {"name": "set_progress", "inputSchema": {}},
    {"name": "register_debrief", "inputSchema": {"properties": {
        "debrief": {}, "entries": {}, "subject": {}, "completes": {},
        "figures": {}}}}]}}


def test_the_kept_figures_go_to_a_pilot_that_lists_them_and_no_other():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "058_the_search_page"
        folder.mkdir()
        (folder / "slice.md").write_text(SLICE_MD)
        (folder / "state.json").write_text(json.dumps(RUN_STATE))
        entries_file(folder)
        assert run_cli(["input", str(folder), "--stage", "run"])[0] == 0
        kept = json.loads((folder / debrief.RUN_FILE).read_text())["figures"]
        opener = JsonOpener(FIGURES_LISTED, STORED)
        assert run_cli(["give", str(folder), "--stage", "run"], "It went.",
                       opener)[:2] == (
            0, "Debrief handed to Pilot: 4 entries stored\n")
        arguments = opener.bodies[1]["params"]["arguments"]
        assert arguments["figures"] == kept
        assert set(arguments) == {"debrief", "entries", "subject",
                                  "completes", "figures"}
        # today's Pilot, subject and completes but no figures: as before
        for listed in (SUBJECT_LISTED, LISTED):
            opener = JsonOpener(listed, STORED)
            assert run_cli(["hand-off", str(folder), "--stage", "run"],
                           opener=opener)[0] == 0
            assert "figures" not in opener.bodies[1]["params"]["arguments"]
        # a file with no figures kept sends none, to a Pilot that lists them
        entries_file(folder, debrief="Given.")
        opener = JsonOpener(FIGURES_LISTED, STORED)
        assert run_cli(["hand-off", str(folder), "--stage", "run"],
                       opener=opener)[0] == 0
        assert set(opener.bodies[1]["params"]["arguments"]) == {
            "debrief", "entries", "subject", "completes"}


def test_the_commands_refuse_what_they_cannot_do():
    with tempfile.TemporaryDirectory() as tmp:
        entries_file(tmp)
        for argv, stdin, says in (
                (["give", tmp, "--stage", "run"], " \n", "no words on stdin"),
                (["hand-off", tmp, "--stage", "run"], "",
                 "no debrief of the stage session's"),
                (["input", tmp, "--stage", "run"], "", "no state.json"),
                (["ground", tmp, "--end"], "", "no start of the plan preparer"),
                (["ground", tmp, "--words"], "", "no words on stdin"),
                (["input", str(Path(tmp) / "gone"), "--stage", "plan"], "",
                 "slice directory not found")):
            code, out, err = run_cli(argv, stdin, JsonOpener())
            assert code == 2 and says in err, (argv, err)
        assert "debrief" not in json.loads(
            (Path(tmp) / debrief.RUN_FILE).read_text())


def test_the_preparers_commands_make_its_entry():
    with tempfile.TemporaryDirectory() as tmp:
        for argv, stdin in ((["ground", tmp, "--start"], ""),
                            (["ground", tmp, "--words"], "Solid slice.\n"),
                            (["ground", tmp, "--end"], "")):
            assert run_cli(argv, stdin)[:2] == (0, "")
        (entry,) = debrief.read(Path(tmp) / debrief.PLAN_FILE)
        assert (entry["section"], entry["role"], entry["words"]) == (
            "The grounding", "Plan preparer", "Solid slice.")


# -- the stages' use of it -----------------------------------------------------

PLUGIN = Path(__file__).resolve().parents[1]
ROLE_ASK = ("Before you hand back, add a debrief: a few lines, in your own "
            "words, on how you feel this went for you.")


def flat(text):
    return " ".join(text.split())


def section(text, heading):
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def in_order(text, *parts):
    at = 0
    for part in parts:
        at = text.find(part, at)
        if at < 0:
            return False
        at += len(part)
    return True


def test_the_run_gives_its_debrief_at_the_close_out_once_its_cost_is_in():
    text = flat(section((PLUGIN / "skills" / "run-slice" / "SKILL.md")
                        .read_text(), "## The close-out"))
    assert in_order(text, "`slice_cost.py <slice> --write-state`",
                    "`debrief.py input <slice> --stage run`",
                    "`debrief.py give <slice> --stage run`",
                    "`close_slice.py <slice>`", "`debrief.json`")


def test_the_plan_gives_its_debrief_at_the_promotion_and_times_its_preparer():
    skill = (PLUGIN / "skills" / "plan-slice" / "SKILL.md").read_text()
    assert in_order(flat(section(skill, "## The promotion")),
                    "`debrief.py input <slice> --stage plan`",
                    "`debrief.py give <slice> --stage plan`",
                    "`git mv", "`plan_debrief.json`")
    assert in_order(flat(section(skill, "## The start")),
                    "`debrief.py ground <slice> --start`",
                    "dispatch `dev:plan-preparer`",
                    "`debrief.py ground <slice> --end`", "`plan_debrief.json`")
    preparer = (PLUGIN / "agents" / "plan-preparer.md").read_text()
    assert flat(preparer).count(ROLE_ASK) == 1
    assert in_order(flat(section(preparer, "## Hand-back")), ROLE_ASK,
                    "`debrief.py ground <slice> --words`", "`nothing to ask`")


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
