"""turn_profile.py — replaying a transcript into per-turn facts.

Two kinds of fixture. The replay tests write a stream-json transcript into a
temp dir, exactly as Claude Code does (each assistant message logged several
times, tool results arriving in the next user message). The classification
tests build turn dicts directly — `_t(i, *calls)` — because what a class
depends on is the tool calls and their results, not how they were logged.

No agent is spawned, nothing is priced: `analyse` takes the pricing function,
and these tests hand it one that charges a flat rate per token.
"""

import importlib.util
import json
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "turn_profile", Path(__file__).resolve().parent / "turn_profile.py"
)
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)

OPUS = "claude-opus-5"


def flat_cost(_model, tok):
    """A pricing function with one rate, so a cost is a token count / 1e6."""
    return sum(tok.values()) / 1_000_000


# -- transcript fixtures ----------------------------------------------------

def _assistant(mid, blocks=(), ts="2026-08-23T10:00:00Z", model=OPUS, **usage):
    u = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 0}
    u.update(usage)
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "content": list(blocks),
                        "usage": u}}


def _use(name, tid, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(tid, text="", is_error=False):
    return {"type": "user", "timestamp": "2026-08-23T10:00:01Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                     "content": text, "is_error": is_error}]}}


def _text_user(text):
    return {"type": "user", "timestamp": "2026-08-23T10:00:01Z",
            "message": {"content": [{"type": "text", "text": text}]}}


def _replay(records):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "session.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return tp.replay(path)


# -- turn fixtures for the classifier ---------------------------------------

def _call(name, key="", cmd="", res="", is_error=False):
    return {"name": name, "key": key or cmd[:160], "id": None, "cmd": cmd,
            "result_chars": len(res), "is_error": is_error, "res_head": res[:600]}


def _t(i, *calls, res_paths=()):
    return {"i": i, "tools": list(calls), "res_paths": set(res_paths)}


def _classes(*turns, first_edit=None):
    return [r["cls"] for r in tp.classify_turns(list(turns), first_edit)]


# -- replay -----------------------------------------------------------------

def test_repeated_message_ids_are_one_turn_with_all_its_calls():
    """The stream logs an assistant message once per block; usage is counted
    once and the tool calls accumulate onto the same turn."""
    rep = _replay([
        _assistant("m1", [_use("Bash", "t1", command="cat a.py")],
                   input_tokens=10, cache_read_input_tokens=1_000),
        _assistant("m1", [_use("Bash", "t2", command="cat b.py")],
                   input_tokens=10, cache_read_input_tokens=1_000),
        _result("t1", "line\n"),
        _result("t2", "other\n"),
    ])
    (turn,) = rep["turns"]
    assert [c["cmd"] for c in turn["tools"]] == ["cat a.py", "cat b.py"]
    assert turn["ctx"] == 1_010          # input + cache_read + cache_write
    assert turn["result_chars"] == len("line\n") + len("other\n")


def test_results_attach_to_their_call_and_reveal_their_paths():
    rep = _replay([
        _assistant("m1", [_use("Grep", "t1", pattern="def run", path="tools")],
                   input_tokens=5),
        _result("t1", "tools/run_loop.py:120:def run()\n"),
    ])
    (turn,) = rep["turns"]
    assert turn["tools"][0]["is_error"] is False
    assert "tools/run_loop.py" in {str(p) for p in turn["res_paths"]}


def test_an_error_result_is_flagged_on_the_call():
    rep = _replay([
        _assistant("m1", [_use("Bash", "t1", command="close_out.py report.md list")]),
        _result("t1", "usage: close_out.py [-h] ...", is_error=True),
    ])
    assert rep["turns"][0]["tools"][0]["is_error"] is True


def test_injected_text_is_not_an_operator_prompt():
    rep = _replay([
        _assistant("m1", [], output_tokens=5),
        _text_user("<system-reminder>plan.md changed</system-reminder>"),
        _text_user("carry on"),
    ])
    assert rep["user_prompts"] == 1
    assert rep["injected_chars"] > 0


def test_a_message_without_usage_is_not_a_turn():
    rep = _replay([{"type": "assistant", "timestamp": "2026-08-23T10:00:00Z",
                    "message": {"id": "m1", "model": OPUS, "content": []}}])
    assert rep["turns"] == []


# -- what one Bash command did ----------------------------------------------

def test_a_command_splits_into_steps_but_not_inside_quotes_or_heredocs():
    assert tp.bash_segments("cat a.py; cat b.py && grep x c.py") == [
        "cat a.py", "cat b.py", "grep x c.py"]
    assert tp.bash_segments("close_out.py append --headline 'a; b'") == [
        "close_out.py append --headline 'a; b'"]
    assert len(tp.bash_segments(
        "python3 - <<'PY'\nimport os; os.remove('x')\nPY")) == 1


def test_reads_chained_in_one_command_are_counted_separately():
    """`tools/turn` cannot see this batching; `reads/turn` is the honest one."""
    turn = _t(1, _call("Bash", cmd="sed -n 1,40p plan.md && sed -n 1,20p slice.md"))
    _ops, _targets, reads = tp.turn_ops(turn)
    assert reads == 2
    assert tp.turn_ops(_t(1, _call("Read", key="plan.md")))[2] == 1


def test_an_edit_made_through_the_shell_is_an_edit():
    for cmd in ("sed -i 's/a/b/' run_loop.py",
                "echo hi > notes.md",
                "python3 - <<'PY'\nPath('x.py').write_text('a')\nPY"):
        assert "edit" in tp.bash_ops(cmd), cmd
    assert "edit" not in tp.bash_ops("kc project test 2>&1 | tail -5")


def test_a_gate_is_read_from_the_text_not_the_program():
    assert tp.bash_ops("cexec python sh -c 'uv run --with pytest pytest'") == ["gate"]
    assert tp.tool_class("Bash", "kc project test") == "gate"
    assert tp.tool_class("Bash", "git diff --stat") == "git-inspect"
    assert tp.tool_class("Read", "") == "Read"


# -- the turn classes -------------------------------------------------------

def test_work_beats_the_reads_that_led_to_it():
    """First match wins: a turn that read and then edited is an edit."""
    assert _classes(_t(1, _call("Bash", cmd="cat run_loop.py"),
                       _call("Edit", key="run_loop.py"))) == ["edit"]
    assert _classes(_t(1, _call("Bash", cmd="cat x.py && kc project test"))) == ["gate"]
    assert _classes(_t(1, _call("Bash", cmd="git add -A && git commit -m x"))) == ["commit"]


def test_writing_the_plan_or_a_verdict_is_a_record_not_an_edit():
    assert _classes(_t(1, _call("Edit", key="/s/170/plan.md"))) == ["record"]
    assert _classes(_t(1, _call("Write", key="/s/170/phases/P1/result.json"))) == ["record"]
    # a turn that writes both is the edit it also was
    assert _classes(_t(1, _call("Edit", key="/s/170/plan.md"),
                       _call("Edit", key="run_loop.py"))) == ["edit"]


def test_orientation_ends_at_the_first_edit():
    turns = [_t(1, _call("Bash", cmd="cat plan.md")),
             _t(2, _call("Edit", key="run_loop.py")),
             _t(3, _call("Bash", cmd="cat run_loop.py"))]
    assert _classes(*turns, first_edit=2) == ["orient-read", "edit", "work-read"]
    # no edit at all: everything the session read was orientation
    assert _classes(turns[0], turns[2]) == ["orient-read", "orient-read"]


def test_a_failed_call_is_a_fumble_and_repeating_it_is_a_retry():
    """The loop's commands end in `2>&1`, so failure is read from the text."""
    bad = _call("Bash", cmd="close_out.py /s/170/close-out.md list",
                res="usage: close_out.py [-h] slice_dir ...")
    help_ = _call("Bash", cmd="close_out.py --help", res="close_out.py [-h]")
    ok = _call("Bash", cmd="close_out.py /s/170 list", res="B1 ...")
    assert _classes(_t(1, help_)) == ["fumble"]
    # re-running the same tool within two turns of its failure is the retry —
    # reading its help after failing counts there too, not as a second fumble
    assert _classes(_t(1, bad), _t(2, help_), _t(3, ok)) == ["fumble", "retry", "retry"]
    assert tp.classify_turns([_t(1, bad)], None)[0]["fumble_key"] == "close_out.py"


def test_the_quiet_classes():
    assert _classes(_t(1)) == ["think"]
    assert _classes(_t(1, _call("Bash", cmd="sleep 30"))) == ["wait"]
    assert _classes(_t(1, _call("Bash", cmd="git diff --stat"))) == ["git-inspect"]
    assert _classes(_t(1, _call("Agent", key="Explore: find callers"))) == ["dispatch"]
    assert _classes(_t(1, _call("Bash", cmd="curl -s localhost:8080/health"))) == ["other"]


# -- batching ---------------------------------------------------------------

def test_a_run_of_read_turns_folds_into_its_first_turn():
    out = tp.classify_turns(
        [_t(1, _call("Bash", cmd="cat a.py")),
         _t(2, _call("Bash", cmd="cat b.py")),
         _t(3, _call("Bash", cmd="cat c.py")),
         _t(4, _call("Edit", key="a.py"))], 4)
    assert [r.get("batchable", False) for r in out] == [False, True, True, False]


def test_strict_batching_keeps_only_the_reads_that_did_not_need_the_last_one():
    """Turn 2 reads a file turn 1's result named — it could not have been
    batched with it. Turn 3 re-reads what was already in context."""
    out = tp.classify_turns(
        [_t(1, _call("Bash", cmd="cat a.py"), res_paths=["b.py"]),
         _t(2, _call("Bash", cmd="cat b.py")),
         _t(3, _call("Bash", cmd="cat a.py")),
         _t(4, _call("Edit", key="a.py"))], 4)
    assert [r.get("batchable", False) for r in out] == [False, True, True, False]
    assert [r.get("batchable_strict", False) for r in out] == [False, False, True, False]


def test_a_search_is_never_strictly_batchable():
    """A grep's target is a pattern, not a path already in context."""
    out = tp.classify_turns(
        [_t(1, _call("Read", key="a.py")),
         _t(2, _call("Grep", key="run in .")),
         _t(3, _call("Edit", key="a.py"))], 3)
    assert out[1]["batchable"] is True and out[1]["batchable_strict"] is False


# -- analyse ----------------------------------------------------------------

def _session_records():
    """Nine turns: three orientation reads, an edit, a gate, a fumble, its
    retry, a commit and a think."""
    ctx = {"cache_read_input_tokens": 30_000}
    return [
        _assistant("m1", [_use("Bash", "t1", command="cat plan.md")],
                   input_tokens=1_000, output_tokens=100),
        _result("t1", "# plan"),
        _assistant("m2", [_use("Bash", "t2", command="cat run_loop.py")],
                   output_tokens=100, **ctx),
        _result("t2", "code"),
        _assistant("m3", [_use("Bash", "t3", command="cat plan.md")],
                   output_tokens=100, **ctx),
        _result("t3", "# plan"),
        _assistant("m4", [_use("Edit", "t4", file_path="run_loop.py")],
                   output_tokens=100, **ctx),
        _result("t4", "ok"),
        _assistant("m5", [_use("Bash", "t5", command="kc project test")],
                   output_tokens=100, **ctx),
        _result("t5", "OK"),
        _assistant("m6", [_use("Bash", "t6", command="close_out.py rep.md list")],
                   output_tokens=100, **ctx),
        _result("t6", "usage: close_out.py [-h] slice_dir"),
        _assistant("m7", [_use("Bash", "t7", command="close_out.py /s/170 list")],
                   output_tokens=100, **ctx),
        _result("t7", "B1"),
        _assistant("m8", [_use("Bash", "t8", command="git commit -am x")],
                   output_tokens=100, **ctx),
        _result("t8", "1 file changed"),
        _assistant("m9", [], output_tokens=100, **ctx),
    ]


def test_analyse_reports_what_the_session_did():
    m = tp.analyse(_replay(_session_records()), flat_cost)["metrics"]
    assert m["turns"] == 9
    assert m["turn_class_turns"] == {
        "orient-read": 3, "edit": 1, "gate": 1, "fumble": 1, "retry": 1,
        "commit": 1, "think": 1}
    assert m["first_edit_turn"] == 4 and m["orient_turns_edit"] == 3
    # 8 calls over 9 turns; 5 read ops — the three `cat`s and both
    # `close_out.py list`, which reads the report
    assert m["tools_per_turn"] == 0.89 and m["reads_per_turn"] == 0.56
    assert m["avoidable_turns"] == 3          # fumble + retry + one strict batch
    assert m["retry_turns"] == 1 and m["fumble_turns"] == 1
    assert m["batchable_turns"] == 2 and m["batchable_strict_turns"] == 1


def test_analyse_prices_every_turn_with_the_function_it_is_given():
    a = tp.analyse(_replay(_session_records()), flat_cost)
    m = a["metrics"]
    tokens = sum(m["tok"][k] for k in ("input", "cache_read", "cache_write", "output"))
    assert m["cost"] == round(tokens / 1_000_000, 4)
    assert abs(sum(a["turn_cost"]) - m["cost"]) < 1e-9
    assert abs(sum(m["turn_class_cost"].values()) - m["cost"]) < 1e-3
    assert m["ctx_first"] == 1_000 and m["ctx_max"] == 30_000


def test_a_prompt_that_did_not_come_back_from_cache_is_a_break():
    """Turn 2 was read from cache; turn 3's prompt was written again."""
    rep = _replay([
        _assistant("m1", cache_creation_input_tokens=30_000),
        _assistant("m2", cache_read_input_tokens=30_000,
                   cache_creation_input_tokens=500),
        _assistant("m3", ts="2026-08-23T10:20:00Z",
                   cache_creation_input_tokens=30_500),
    ])
    a = tp.analyse(rep, flat_cost)
    (brk,) = a["breaks"]
    assert brk["turn"] == 3 and brk["shortfall"] == 30_500
    assert brk["gap_s"] == 1_200                     # over the 5-minute TTL
    assert a["metrics"]["breaks"] == 1
    assert a["metrics"]["breaks_after_gap"] == 1
    assert a["metrics"]["gaps_over_ttl"] == 1
    assert brk["extra_cost"] == 0.0                  # flat_cost charges no tier


def test_an_empty_transcript_analyses_to_nothing():
    assert tp.analyse({"turns": [], "user_prompts": 0, "injected_chars": 0},
                      flat_cost) == {}


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
