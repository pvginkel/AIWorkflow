"""Tests for labeller_vocab — the labeller's declared lists, the nestings and
`declarations` (docs/labeller.md § The vocabularies).

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_labeller_vocab.py` or via pytest.
"""

import importlib.util
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


vocab = _load("labeller_vocab")
turn_profile = _load("turn_profile")
project_config = _load("project_config")

LIST_NAMES = ("work_unit_kind", "unit_outcome", "rework_kind", "unit_measure",
              "segment_kind", "wait_cause", "call_class", "avoidable_kind",
              "batchable_condition", "command_class", "build_result", "file_class",
              "tool_effect_kind", "rule", "ask_category", "event_kind",
              "context_part_kind")


def codes(name):
    return [v["code"] for v in vocab.lists()[name]]


def test_every_list_the_page_declares_is_answered_and_no_other():
    assert tuple(vocab.lists()) == LIST_NAMES


def test_every_value_has_a_code_name_description_and_a_position_unique_in_its_list():
    for name, values in vocab.lists().items():
        assert values, name
        assert [v["position"] for v in values] == list(range(1, len(values) + 1)), name
        assert len({v["code"] for v in values}) == len(values), name
        for v in values:
            assert {"code", "name", "description", "position"} <= set(v), (name, v)
            assert v["code"] and v["name"], (name, v)
            assert v["description"].endswith("."), (name, v)


def test_the_work_unit_kinds_hold_the_gate_and_the_nestings_pair_only_declared_kinds():
    assert codes("work_unit_kind") == ["slice", "stage", "phase", "dispatch", "sweep", "gate"]
    pairs = [(n["inner"], n["outer"]) for n in vocab.nesting()]
    assert pairs == [("stage", "slice"), ("phase", "stage"), ("dispatch", "phase"),
                     ("dispatch", "stage"), ("sweep", "stage"), ("gate", "phase"),
                     ("gate", "stage")]
    kinds = set(codes("work_unit_kind"))
    assert all(inner in kinds and outer in kinds for inner, outer in pairs)


def test_call_class_is_turn_profiles_classes_in_its_order():
    assert tuple(codes("call_class")) == turn_profile.TURN_CLASSES
    assert set(vocab._CALL_CLASS) == set(turn_profile.TURN_CLASSES)


def test_batchable_condition_is_batchable_whys_whole_in_its_order():
    rows = [(v["code"], v["name"], v["description"])
            for v in vocab.lists()["batchable_condition"]]
    assert rows == [tuple(r) for r in turn_profile.BATCHABLE_WHYS]


def test_file_class_is_the_classes_a_project_rule_may_give_with_whether_counted():
    values = vocab.lists()["file_class"]
    assert tuple(v["code"] for v in values) == project_config.FILE_CLASSES
    assert {v["code"]: v["counted"] for v in values} == {
        "code": True, "test": True, "docs": True, "spec": True,
        "generated": False, "record": False}


def test_the_extra_facts_sit_beside_their_values():
    assert {v["code"]: v["unit"] for v in vocab.lists()["unit_measure"]}[
        "review_findings"] == "findings"
    assert all(v["home"] == "/etc/claude-code/CLAUDE.md" for v in vocab.lists()["rule"])
    (gate_red,) = vocab.lists()["event_kind"]
    assert gate_red["code"] == "gate_red" and "is_error" in gate_red
    assert gate_red["is_error"] is False  # D9: a red gate is not an error
    assert all(v["name"] == v["code"] for v in vocab.lists()["build_result"])


def test_the_lists_are_in_the_pages_order():
    assert codes("wait_cause") == ["command", "sub_agent", "background_task", "person",
                                   "hold", "driver", "startup"]
    assert codes("command_class") == ["test_suite", "gate", "ci_wait", "chunked_wait",
                                      "sleep_poll", "git"]
    assert codes("ask_category") == ["requirements", "plan_question", "plan_review",
                                     "run_question", "close_out", "pilots_own"]
    assert codes("segment_kind") == ["start", "work", "gate", "records", "wait"]
    assert codes("avoidable_kind") == ["retry", "fumble", "batchable"]


def test_the_digest_is_22_url_safe_characters_over_the_canonical_json():
    d = vocab.digest({"b": 1, "a": [1, "é"]})
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", d)
    assert d == vocab.digest({"a": [1, "é"], "b": 1})
    assert d != vocab.digest({"a": [1, "e"], "b": 1})


def test_declarations_change_with_the_groups_and_the_version_and_only_with_them():
    groups = [{"key": "FooSpecs/001_one", "spec_repo": "FooSpecs", "name": "One",
               "summary": "s", "slices": ["001_one"]}]
    a = vocab.declarations(vocab.vocabularies(1, "0.1.0", groups))
    assert a == vocab.declarations(vocab.vocabularies(1, "0.1.0", [dict(g) for g in groups]))
    assert a != vocab.declarations(vocab.vocabularies(1, "0.1.1", groups))
    assert a != vocab.declarations(vocab.vocabularies(1, "0.1.0", []))


def test_the_vocabularies_answer_has_the_pages_shape():
    answer = vocab.vocabularies(1, "0.1.0", [])
    assert set(answer) == {"contract", "version", "lists", "nesting", "groups"}


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
