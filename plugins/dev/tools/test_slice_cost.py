"""slice_cost.py — pricing a loop-run slice from its state files.

The fixtures build a slice dir (state.json / plan_state.json) plus fake
Claude Code transcripts in tmp_path; the state files' transcript paths point
straight at them, exactly as the loops record real ones.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "slice_cost", Path(__file__).resolve().parent / "slice_cost.py"
)
slice_cost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slice_cost)
CACHE_READ_MULT = slice_cost.CACHE_READ_MULT
CACHE_WRITE_MULT = slice_cost.CACHE_WRITE_MULT
PRICES = slice_cost.PRICES
build_report = slice_cost.build_report
collect = slice_cost.collect
cost_for = slice_cost.cost_for
main = slice_cost.main

OPUS = "claude-opus-5"
SONNET = "claude-sonnet-5"


def _message(mid, model=OPUS, ts="2026-07-31T10:00:00Z", **usage):
    base = {"input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    base.update(usage)
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "usage": base}}


def _tool_message(mid, calls, ts="2026-07-31T10:00:00Z", **usage):
    """An assistant message that made tool calls, plus the results that came
    back — what the turn profile reads."""
    msg = _message(mid, ts=ts, **usage)
    msg["message"]["content"] = [
        {"type": "tool_use", "id": f"{mid}-{i}", "name": name,
         "input": {"command": arg} if name == "Bash" else {"file_path": arg}}
        for i, (name, arg, *_res) in enumerate(calls)]
    results = [{"type": "user", "timestamp": ts,
                "message": {"content": [{"type": "tool_result",
                                         "tool_use_id": f"{mid}-{i}",
                                         "content": res[0] if res else "ok"}]}}
               for i, (_name, _arg, *res) in enumerate(calls)]
    return [msg, *results]


def _write_transcript(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _slice(tmp_path, state=None, plan_state=None):
    slice_dir = tmp_path / "114_deploy"
    slice_dir.mkdir()
    if state is not None:
        (slice_dir / "state.json").write_text(json.dumps(state))
    if plan_state is not None:
        (slice_dir / "plan_state.json").write_text(json.dumps(plan_state))
    return slice_dir


def _history_entry(session, transcript, role="code-writer", phase="1"):
    return {"ts": "2026-07-31T10:00:00Z", "phase": phase, "role": role,
            "round": 1, "outcome": "done", "summary": "",
            "session": session, "transcript": str(transcript),
            "duration_s": 60}


# -- pricing ----------------------------------------------------------------

def test_cost_applies_cache_multipliers():
    tok = {"input": 1_000_000, "output": 1_000_000,
           "cache_write": 1_000_000, "cache_read": 1_000_000}
    base = PRICES[OPUS]
    expected = (base["input"] + base["output"]
                + base["input"] * CACHE_WRITE_MULT
                + base["input"] * CACHE_READ_MULT)
    assert cost_for(OPUS, tok) == pytest.approx(expected)


def test_unknown_model_prices_zero():
    assert cost_for("claude-nonexistent", {"input": 1_000_000}) == 0.0


# -- transcript scanning ----------------------------------------------------

def test_duplicate_message_ids_counted_once(tmp_path):
    t = tmp_path / "proj" / "sess1.jsonl"
    _write_transcript(t, [
        _message("m1", input_tokens=100, output_tokens=10),
        _message("m1", input_tokens=100, output_tokens=10),   # stream dup
        _message("m2", input_tokens=50, output_tokens=5),
    ])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [_history_entry("sess1", t)],
    })
    convs, warnings = collect(slice_dir)
    assert warnings == []
    (c,) = convs
    assert c.turns == 2
    assert c.tokens_by_class()["input"] == 150
    assert c.tokens_by_class()["output"] == 15


def test_wall_clock_spans_message_timestamps(tmp_path):
    t = tmp_path / "proj" / "sess1.jsonl"
    _write_transcript(t, [
        _message("m1", ts="2026-07-31T10:00:00Z", output_tokens=1),
        _message("m2", ts="2026-07-31T10:30:00Z", output_tokens=1),
    ])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("sess1", t)]})
    convs, _ = collect(slice_dir)
    assert convs[0].duration_s() == 1800


# -- collection -------------------------------------------------------------

def test_resumed_session_scanned_once(tmp_path):
    """Nudges and session-limit redispatches append several history entries
    for one session id — it must not be double-priced."""
    t = tmp_path / "proj" / "sess1.jsonl"
    _write_transcript(t, [_message("m1", input_tokens=100)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [
            _history_entry("sess1", t),
            _history_entry("sess1", t, role="code-writer"),
        ],
    })
    convs, _ = collect(slice_dir)
    assert len(convs) == 1


def test_orchestrator_and_both_loops_collected(tmp_path):
    orch = tmp_path / "proj" / "orch.jsonl"
    writer = tmp_path / "proj" / "writer.jsonl"
    planner = tmp_path / "proj" / "planner.jsonl"
    for p in (orch, writer, planner):
        _write_transcript(p, [_message("m", input_tokens=10)])
    slice_dir = _slice(
        tmp_path,
        state={"orchestrator": {"session": "orch", "transcript": str(orch)},
               "history": [_history_entry("writer", writer)]},
        plan_state={"orchestrator": None,
                    "history": [{"role": "plan-writer", "round": 1,
                                 "outcome": "done", "summary": "",
                                 "session": "planner",
                                 "transcript": str(planner),
                                 "duration_s": 5}]},
    )
    convs, warnings = collect(slice_dir)
    assert warnings == []
    roles = {c.role for c in convs}
    assert roles == {"orchestrator:run", "code-writer", "plan-writer"}


def test_subagents_ride_their_parent(tmp_path):
    t = tmp_path / "proj" / "sess1.jsonl"
    _write_transcript(t, [_message("m1", input_tokens=10)])
    sub = tmp_path / "proj" / "sess1" / "subagents" / "agent-aaa.jsonl"
    _write_transcript(sub, [_message("s1", model=SONNET, output_tokens=7)])
    sub.with_suffix(".meta.json").write_text(
        json.dumps({"agentType": "test-fixer", "description": "fix suite"}))
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [_history_entry("sess1", t, role="test-agent",
                                   phase=None)],
    })
    convs, _ = collect(slice_dir)
    assert len(convs) == 2
    subagent = next(c for c in convs if c.kind == "subagent")
    assert subagent.role == "subagent:test-fixer"
    assert subagent.phase is None
    assert subagent.tok_by_model[SONNET]["output"] == 7


def test_missing_transcript_is_a_warning_not_a_crash(tmp_path):
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [_history_entry("gone", tmp_path / "nope.jsonl")],
    })
    convs, warnings = collect(slice_dir)
    assert convs == []
    assert len(warnings) == 1 and "transcript missing" in warnings[0]


def test_no_state_files_raises(tmp_path):
    slice_dir = _slice(tmp_path)
    with pytest.raises(FileNotFoundError):
        collect(slice_dir)


def test_null_session_entries_skipped(tmp_path):
    """A protocol-failure round records session: null — no transcript to
    scan."""
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [{"role": "code-writer", "phase": "1", "round": 1,
                     "outcome": "blocked", "summary": "", "session": None,
                     "transcript": None, "duration_s": 0}],
    })
    convs, warnings = collect(slice_dir)
    assert convs == [] and warnings == []


# -- report -----------------------------------------------------------------

def test_report_aggregates_by_role_and_phase(tmp_path):
    t1 = tmp_path / "proj" / "s1.jsonl"
    t2 = tmp_path / "proj" / "s2.jsonl"
    _write_transcript(t1, [_message("m1", output_tokens=1_000_000)])
    _write_transcript(t2, [_message("m2", output_tokens=1_000_000)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [
            _history_entry("s1", t1, role="code-writer", phase="1"),
            _history_entry("s2", t2, role="code-reviewer", phase="1"),
        ],
    })
    convs, warnings = collect(slice_dir)
    report = build_report(slice_dir, convs, warnings)
    out_price = PRICES[OPUS]["output"]
    assert report["totals"]["cost_usd"] == pytest.approx(2 * out_price)
    assert report["roles"]["code-writer"]["cost"] == pytest.approx(out_price)
    assert report["phases"]["P1"]["cost"] == pytest.approx(2 * out_price)
    assert report["phases"]["P1"]["n"] == 2


def test_phaseless_sessions_grouped_under_their_role(tmp_path):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=100)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [_history_entry("s1", t, role="doc-writer", phase=None)],
    })
    convs, warnings = collect(slice_dir)
    report = build_report(slice_dir, convs, warnings)
    assert "doc-writer" in report["phases"]


def test_unknown_model_tokens_warned(tmp_path):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [
        _message("m1", model="claude-future-9", input_tokens=123)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("s1", t)]})
    convs, warnings = collect(slice_dir)
    report = build_report(slice_dir, convs, warnings)
    assert report["totals"]["cost_usd"] == 0.0
    assert any("claude-future-9" in w and "123" in w
               for w in report["warnings"])


# -- CLI --------------------------------------------------------------------

def test_main_json_output(tmp_path, capsys):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=200_000)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("s1", t)]})
    assert main([str(slice_dir), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["slice"] == "114_deploy"
    assert report["totals"]["cost_usd"] == pytest.approx(
        0.2 * PRICES[OPUS]["output"])
    assert report["sessions"][0]["role"] == "code-writer"


def test_main_table_output_smoke(tmp_path, capsys):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=100)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("s1", t)]})
    assert main([str(slice_dir)]) == 0
    out = capsys.readouterr().out
    assert "cost report" in out and "code-writer" in out


def test_main_missing_dir_exits_2(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2


def test_main_no_state_exits_2(tmp_path, capsys):
    slice_dir = _slice(tmp_path)
    assert main([str(slice_dir)]) == 2


# -- derived ratios and the close-out write ---------------------------------

def test_derived_ratios_split_planner_research_rework(tmp_path):
    def t(name):
        return tmp_path / "proj" / f"{name}.jsonl"

    for name in ("w1", "w2", "consult", "planner"):
        _write_transcript(t(name),
                          [_message(f"m-{name}", output_tokens=1_000_000)])
    sub = tmp_path / "proj" / "planner" / "subagents" / "agent-r1.jsonl"
    _write_transcript(sub, [_message("s1", output_tokens=1_000_000)])
    sub.with_suffix(".meta.json").write_text(
        json.dumps({"agentType": "Explore"}))
    slice_dir = _slice(
        tmp_path,
        state={
            "orchestrator": None,
            "history": [
                _history_entry("w1", t("w1")),                    # round 1
                {**_history_entry("w2", t("w2")), "round": 2},    # rework
                _history_entry("consult", t("consult"),           # completion consult
                               role="consult", phase=None),
            ],
        },
        plan_state={
            "orchestrator": None,
            "history": [{"role": "plan-writer", "round": 1,
                         "outcome": "done", "summary": "",
                         "session": "planner", "transcript": str(t("planner")),
                         "duration_s": 5}],
        },
    )
    convs, warnings = collect(slice_dir)
    report = build_report(slice_dir, convs, warnings)
    d = report["derived"]
    out = PRICES[OPUS]["output"]     # every conversation costs exactly this
    total = 5 * out
    assert d["cost_usd"] == pytest.approx(total, abs=0.01)
    assert d["planner_cost_usd"] == pytest.approx(out, abs=0.01)
    assert d["planner_share"] == pytest.approx(out / total, abs=0.001)
    assert d["research_cost_usd"] == pytest.approx(out, abs=0.01)
    assert d["research_share"] == pytest.approx(out / total, abs=0.001)
    assert d["consult_cost_usd"] == pytest.approx(out, abs=0.01)
    assert d["consult_share"] == pytest.approx(out / total, abs=0.001)
    assert d["rework_cost_usd"] == pytest.approx(out, abs=0.01)
    assert d["rework_share"] == pytest.approx(out / total, abs=0.001)


def test_only_the_first_completion_consult_is_priced_apart(tmp_path):
    """The first phaseless consult is the completion step every run makes —
    its own bucket, with its sub-agents. A phase-bound consult (the
    fix-round judge), a second completion consult (the rising bar after
    appended work) and a second test round are spend past first delivery."""
    def t(name):
        return tmp_path / "proj" / f"{name}.jsonl"

    for name in ("w1", "cfix", "c1", "c2", "test1", "test2"):
        _write_transcript(t(name), [_message(f"m-{name}", output_tokens=1_000_000)])
    sub = tmp_path / "proj" / "c1" / "subagents" / "agent-x.jsonl"
    _write_transcript(sub, [_message("s1", output_tokens=1_000_000)])
    sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "Explore"}))
    slice_dir = _slice(tmp_path, state={"orchestrator": None, "history": [
        _history_entry("w1", t("w1")),
        {**_history_entry("cfix", t("cfix"), role="consult"), "round": 1},
        {**_history_entry("c1", t("c1"), role="consult", phase=None), "round": 2},
        {**_history_entry("test1", t("test1"), role="test-agent", phase=None), "round": 1},
        {**_history_entry("c2", t("c2"), role="consult", phase=None), "round": 3},
        {**_history_entry("test2", t("test2"), role="test-agent", phase=None), "round": 2},
    ]})
    convs, warnings = collect(slice_dir)
    d = build_report(slice_dir, convs, warnings)["derived"]
    out = PRICES[OPUS]["output"]
    assert d["consult_cost_usd"] == pytest.approx(2 * out, abs=0.01)    # c1 + its sub-agent
    assert d["rework_cost_usd"] == pytest.approx(3 * out, abs=0.01)     # cfix + c2 + test2


def test_a_round_resuming_a_question_or_blocked_round_is_not_rework(tmp_path):
    """A writer round 2 after the writer's own `question` (or `blocked`)
    round is the first delivery going on once the operator answered; the
    round 3 that follows a review `issues` on the same phase is rework."""
    def t(name):
        return tmp_path / "proj" / f"{name}.jsonl"

    for name in ("w1", "w2", "r1", "w3", "v1", "v2"):
        _write_transcript(t(name), [_message(f"m-{name}", output_tokens=1_000_000)])
    slice_dir = _slice(tmp_path, state={"orchestrator": None, "history": [
        {**_history_entry("w1", t("w1")), "outcome": "question"},
        {**_history_entry("w2", t("w2")), "round": 2},                   # continuation
        {"phase": "1", "role": "gate", "round": 2, "outcome": "green",
         "summary": "", "session": None, "transcript": None, "duration_s": 1},
        {**_history_entry("r1", t("r1"), role="code-reviewer"), "outcome": "issues"},
        {**_history_entry("w3", t("w3")), "round": 3},                   # rework
        {**_history_entry("v1", t("v1"), role="code-reviewer", phase="2"),
         "outcome": "blocked"},
        {**_history_entry("v2", t("v2"), role="code-reviewer", phase="2"),
         "round": 2},                                                     # continuation
    ]})
    convs, warnings = collect(slice_dir)
    d = build_report(slice_dir, convs, warnings)["derived"]
    assert d["rework_cost_usd"] == pytest.approx(PRICES[OPUS]["output"], abs=0.01)


def test_appended_phases_are_rework_from_their_first_round(tmp_path):
    """A phase the run appended (state.json `appended_phases`) is spend past
    first delivery whatever its round number — writer, reviewer, and their
    sub-agents; a planned phase's round 1 is not. A state without the field
    (pre-0.5.0) marks nothing."""
    def t(name):
        return tmp_path / "proj" / f"{name}.jsonl"

    for name in ("w1", "w4", "r4"):
        _write_transcript(t(name), [_message(f"m-{name}", output_tokens=1_000_000)])
    sub = tmp_path / "proj" / "w4" / "subagents" / "agent-x.jsonl"
    _write_transcript(sub, [_message("s1", output_tokens=1_000_000)])
    sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "Explore"}))
    history = [
        _history_entry("w1", t("w1"), phase="1"),                       # planned, r1
        _history_entry("w4", t("w4"), phase="4"),                       # appended, r1
        _history_entry("r4", t("r4"), role="code-reviewer", phase="4"),  # appended, r1
    ]
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "appended_phases": ["4"], "history": history})
    convs, warnings = collect(slice_dir)
    d = build_report(slice_dir, convs, warnings)["derived"]
    assert d["rework_share"] == pytest.approx(3 / 4, abs=0.001)   # w4 + its sub-agent + r4

    (slice_dir / "state.json").write_text(json.dumps({"orchestrator": None,
                                                      "history": history}))
    convs, warnings = collect(slice_dir)
    d = build_report(slice_dir, convs, warnings)["derived"]
    assert d["rework_share"] == 0.0


def test_run_subagents_ride_their_dispatchers_rework_bucket(tmp_path):
    t = tmp_path / "proj" / "w2.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=1_000_000)])
    sub = tmp_path / "proj" / "w2" / "subagents" / "agent-f1.jsonl"
    _write_transcript(sub, [_message("s1", output_tokens=1_000_000)])
    sub.with_suffix(".meta.json").write_text(
        json.dumps({"agentType": "test-fixer"}))
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [{**_history_entry("w2", t), "round": 2}],
    })
    convs, warnings = collect(slice_dir)
    report = build_report(slice_dir, convs, warnings)
    d = report["derived"]
    assert d["rework_share"] == pytest.approx(1.0, abs=0.001)
    assert d["research_share"] == 0.0     # run-loop sub-agents never are


# -- the session table names each session's round ---------------------------

def test_sessions_carry_their_round_and_the_label_names_it(tmp_path, capsys):
    t = tmp_path / "proj" / "w2.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=100)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [{**_history_entry("w2", t), "round": 2}]})
    assert main([str(slice_dir)]) == 0
    assert build_report(slice_dir, *collect(slice_dir))["sessions"][0][
        "round"] == 2
    assert "P1 code-writer r2" in capsys.readouterr().out


def test_write_state_appends_cost_block(tmp_path, capsys):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [_message("m1", output_tokens=200_000)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("s1", t)]})
    assert main([str(slice_dir), "--write-state", "--json"]) == 0
    state = json.loads((slice_dir / "state.json").read_text())
    assert state["history"], "existing state keys must survive the write"
    cost = state["cost"]
    assert cost["cost_usd"] == pytest.approx(
        0.2 * PRICES[OPUS]["output"], abs=0.01)
    assert cost["planner_share"] == 0.0 and cost["rework_share"] == 0.0
    assert cost["warnings"] == []
    assert "ts" in cost


# -- the turn profile -------------------------------------------------------

def test_turns_block_profiles_each_role(tmp_path):
    """Three reads then an edit: orientation is three turns, two of them a
    batched read would have folded away."""
    t = tmp_path / "proj" / "w1.jsonl"
    _write_transcript(t, [
        *_tool_message("m1", [("Bash", "cat plan.md")], input_tokens=1_000),
        *_tool_message("m2", [("Bash", "cat run_loop.py")],
                       cache_read_input_tokens=40_000),
        *_tool_message("m3", [("Bash", "cat plan.md")],
                       cache_read_input_tokens=40_000),
        *_tool_message("m4", [("Edit", "run_loop.py")],
                       cache_read_input_tokens=40_000, output_tokens=500),
    ])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("w1", t)]})
    report = build_report(slice_dir, *collect(slice_dir))
    tp = report["turns"]
    assert tp["sessions"] == 1 and tp["turns"] == 4
    role = tp["by_role"]["code-writer"]
    assert role["turns"] == 4 and role["tools_per_turn"] == 1.0
    assert role["orient_turns"] == 3          # turns before the first edit
    assert role["ctx_first"] == 1_000 and role["ctx_max"] == 40_000
    assert role["batchable_strict_turns"] == 1   # the re-read of plan.md
    assert tp["avoidable_turns"] == 1
    assert tp["avoidable_cost_usd"] == pytest.approx(
        tp["cost_per_turn_usd"], abs=0.01)


def test_turns_block_prices_a_turn_at_the_slice_rate(tmp_path, capsys):
    t = tmp_path / "proj" / "w1.jsonl"
    _write_transcript(t, [
        *_tool_message("m1", [("Bash", "close_out.py rep.md list",
                               "usage: close_out.py [-h] slice_dir")],
                       output_tokens=100_000),
        *_tool_message("m2", [("Bash", "close_out.py /s/1 list")],
                       output_tokens=100_000),
    ])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("w1", t)]})
    assert main([str(slice_dir)]) == 0
    report = build_report(slice_dir, *collect(slice_dir))
    tp = report["turns"]
    # 200k output tokens over two turns, at the Opus output price
    assert tp["cost_per_turn_usd"] == pytest.approx(
        0.1 * PRICES[OPUS]["output"], abs=0.01)
    assert tp["by_role"]["code-writer"]["retry_fumble_turns"] == 2
    out = capsys.readouterr().out
    assert "2 turns at $" in out and "avoidable 2" in out


def test_write_state_carries_the_turn_block(tmp_path, capsys):
    t = tmp_path / "proj" / "s1.jsonl"
    _write_transcript(t, [*_tool_message("m1", [("Edit", "run_loop.py")],
                                         output_tokens=1_000)])
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None, "history": [_history_entry("s1", t)]})
    assert main([str(slice_dir), "--write-state"]) == 0
    turns = json.loads((slice_dir / "state.json").read_text())["cost"]["turns"]
    assert turns["turns"] == 1 and turns["avoidable_turns"] == 0
    assert turns["by_role"]["code-writer"]["n"] == 1


def test_a_missing_transcript_leaves_the_turn_block_empty(tmp_path):
    """collect() already warns; the profile just has nothing to replay."""
    slice_dir = _slice(tmp_path, state={
        "orchestrator": None,
        "history": [_history_entry("gone", tmp_path / "proj" / "gone.jsonl")]})
    report = build_report(slice_dir, *collect(slice_dir))
    assert report["turns"]["turns"] == 0
    assert report["turns"]["by_role"] == {}
    assert report["warnings"]
