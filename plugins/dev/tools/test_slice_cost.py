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
