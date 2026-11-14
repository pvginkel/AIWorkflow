"""Tests for debrief — a loop's debrief file: each dispatch's entry, its
section and round read off the step it ran under, the why on the entry that
opens a round, and the file appended in order.

Stdlib only; runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_debrief.py` or via pytest.
"""

import importlib.util
import json
import sys
import tempfile
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
