"""Tests for labeller — the command: its verbs, the request and answer shapes,
the contract check, the refusals and error lines, the JSON Lines stream, the
batch loop and the stamp (docs/labeller.md).

The run records (`labeller_records`) and the transcript engine
(`labeller_engine`) are stubbed in `sys.modules`, so these tests feed their
own conversations and never read a transcript. Every data folder is a temp
dir; nothing reads the real home.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_labeller.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("labeller", _HERE / "labeller.py")
labeller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(labeller)

VERSION = labeller.plugin_version()


# ---------------------------------------------------------------------------
# The stubs


class StubRecords:
    """The run records as Part 2's interface gives them: `load`, `tie`,
    `stamp_inputs`, `groups`. `units` maps a session id to the record inputs
    of its tie; `fail` names session ids whose tie raises."""

    loaded: list = []
    units: dict = {}
    fail: set = set()
    group_list: list = []

    @classmethod
    def load(cls, data_dir, blob=None):
        cls.loaded.append((Path(data_dir), blob))
        return cls(), f"blob<{blob}>"

    def tie(self, conversation, transcript):
        if conversation["session_id"] in self.fail:
            raise KeyError("no such state file")
        return {"session": conversation["session_id"],
                "agent": transcript.get("agent_id"),
                "named": list(transcript.get("named") or [])}

    def stamp_inputs(self, tie, context):
        return {"units": self.units.get(tie["session"]), "named": tie["named"],
                "pilot": tie["session"] in context["pilot"]}

    def groups(self):
        return self.group_list


class LabelError(Exception):
    def __init__(self, code, message):
        super().__init__(code, message)
        self.code, self.message = code, message


class StubEngine:
    """`label_one` answers a labels line, or does what the transcript's
    `path` says: `raise-<code>` raises LabelError, `oserror` an OSError,
    `boom` a plain exception, `named` re-stamps with a slice it read."""

    calls: list = []

    @staticmethod
    def label_one(item, tie, records):
        StubEngine.calls.append((item, tie))
        path = item["path"]
        if path.startswith("raise-"):
            raise LabelError(path[len("raise-"):], "the detail")
        if path == "oserror":
            raise FileNotFoundError(2, "No such file or directory")
        if path == "boom":
            return {}["missing"]
        stamp = item["stamp"]
        if path == "named":
            stamp, tie = item["restamp"](["FooSpecs/044"])
        return {"answer": "labels", "stamp": stamp, "boundary": None, "checkpoint": None,
                "labels": {"transcript": [], "launches": [], "calls": []},
                "units": [], "test_suites": [], "ci_builds": []}


@contextlib.contextmanager
def stubs(units=None, fail=(), groups=()):
    records = types.ModuleType("labeller_records")
    records.Records = StubRecords
    engine = types.ModuleType("labeller_engine")
    engine.label_one = StubEngine.label_one
    engine.LabelError = LabelError
    StubRecords.loaded, StubRecords.units = [], dict(units or {})
    StubRecords.fail, StubRecords.group_list = set(fail), list(groups)
    StubEngine.calls = []
    saved = {k: sys.modules.get(k) for k in ("labeller_records", "labeller_engine")}
    sys.modules["labeller_records"], sys.modules["labeller_engine"] = records, engine
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


@contextlib.contextmanager
def home():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "projects").mkdir()
        (base / "plugins").mkdir()
        (base / "data").mkdir()
        yield base, {"projects": str(base / "projects"), "plugins": str(base / "plugins"),
                     "data": str(base / "data")}


def request(home_, **extra):
    return {"contract": 1, "home": home_, **extra}


def run(verb, req=None, raw=None):
    """(exit code, stdout lines as JSON) of `main` on a request."""
    out = io.StringIO()
    text = raw if raw is not None else json.dumps(req if req is not None else {})
    code = labeller.main([verb] if verb else [], io.StringIO(text), out)
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def conversation(sid, *transcripts, sessions=(), documents=()):
    return {"session_id": sid, "sessions": list(sessions), "documents": list(documents),
            "transcripts": list(transcripts)}


def whole(path, agent_id=None, **extra):
    return {"agent_id": agent_id, "path": path, "mode": "whole",
            "launches": [] if agent_id else [{"n": 1, "started_at": "2026-11-15T18:00:00Z"}],
            "calls": [{"id": "msg_1", "position": 1}], **extra}


# ---------------------------------------------------------------------------
# info, the refusals, the contract


def test_info_answers_the_contract_the_version_and_the_verbs_whatever_it_is_handed():
    for raw in ("", "{}", '{"contract": 7}'):
        code, (line,) = run("info", raw=raw)
        assert code == 0
        assert line == {"contract": 1, "version": VERSION,
                        "verbs": ["info", "vocabularies", "stamps", "label", "classes",
                                  "check"]}


def test_the_version_is_the_plugins():
    manifest = json.loads((_HERE.parent / ".claude-plugin" / "plugin.json").read_text())
    assert VERSION == manifest["version"]


def test_a_request_not_spoken_is_refused_with_exit_2_and_what_is_spoken():
    with home() as (_, h):
        for contract in (2, None, "1", True):
            code, (line,) = run("classes", {"contract": contract, "home": h, "files": []})
            assert code == 2, contract
            assert line["error"]["code"] == "contract"
            assert line["error"]["speaks"] == [1]


def test_bad_json_an_unknown_verb_and_a_missing_home_are_refused():
    assert run("classes", raw="{nope")[1][0]["error"]["code"] == "json"
    assert run("classes", raw="[1]")[1][0]["error"]["code"] == "request"
    code, (line,) = run("relabel", {})
    assert code == 2 and line["error"]["code"] == "verb"
    assert run(None, {})[1][0]["error"]["code"] == "verb"
    code, (line,) = run("classes", {"contract": 1, "files": []})
    assert code == 2 and line["error"]["code"] == "home"
    code, (line,) = run("classes", {"contract": 1, "home": {"projects": "/p"}, "files": []})
    assert code == 2 and "home.plugins" in line["error"]["detail"]
    for line in (run("relabel", {})[1][0], run("classes", raw="{nope")[1][0]):
        assert set(line["error"]) == {"code", "detail"}


def test_check_takes_flags_and_exits_2_on_arguments_it_cannot_use():
    out = io.StringIO()
    assert labeller.main(["check", "--projects", "/nonexistent/projects"], io.StringIO(""),
                         out) == 2
    assert "is not a folder" in out.getvalue()
    assert labeller.main(["check", "--sample", "many"], io.StringIO(""), io.StringIO()) == 2


def test_the_command_runs_as_a_script_and_exits_as_the_page_says():
    script = str(_HERE / "labeller.py")
    done = subprocess.run([sys.executable, "-B", script, "info"], input="",
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["contract"] == 1
    done = subprocess.run([sys.executable, "-B", script, "relabel"], input="{}",
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert json.loads(done.stdout)["error"]["code"] == "verb"


CRASHING = """
import runpy, sys, types
records = types.ModuleType("labeller_records")
class Records:
    @classmethod
    def load(cls, data_dir, blob=None):
        raise RuntimeError("broken")
records.Records = Records
sys.modules["labeller_records"] = records
sys.argv = [sys.argv[1], "vocabularies"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def test_a_crash_is_exit_1_with_a_traceback_and_nothing_on_stdout():
    with home() as (base, h):
        runner = base / "crash.py"
        runner.write_text(CRASHING)
        done = subprocess.run([sys.executable, "-B", str(runner), str(_HERE / "labeller.py")],
                              input=json.dumps(request(h)), capture_output=True,
                              text=True, timeout=60)
        assert done.returncode == 1
        assert "Traceback" in done.stderr and "broken" in done.stderr
        assert done.stdout == ""


# ---------------------------------------------------------------------------
# The data folder


def test_home_data_overrides_the_installed_plugins_data_folder():
    assert labeller.data_dir({"plugins": "/p", "data": "/d"}) == Path("/d")


def test_the_data_folder_is_the_installed_keys_read_off_the_cache_layout():
    tools = Path("/mnt/home/.claude/plugins/cache/aiworkflow/dev/0.10.81/tools")
    assert labeller.data_dir({"plugins": "/mnt/home/.claude/plugins"}, tools) == Path(
        "/mnt/home/.claude/plugins/data/dev-aiworkflow")


def test_else_the_sole_installed_key_of_the_plugins_name():
    with tempfile.TemporaryDirectory() as tmp:
        plugins = Path(tmp)
        tools = Path("/work/AIWorkflow/plugins/dev/tools")
        (plugins / "installed_plugins.json").write_text(json.dumps(
            {"plugins": {"dev@some.market": [{}], "other@x": [{}]}}))
        assert labeller.data_dir({"plugins": tmp}, tools) == plugins / "data" / "dev-some-market"
        (plugins / "installed_plugins.json").write_text(json.dumps(
            {"plugins": {"dev@a": [{}], "dev@b": [{}]}}))
        with contextlib.suppress(labeller.Refusal):
            labeller.data_dir({"plugins": tmp}, tools)
            raise AssertionError("two keys must not tell a folder")
        (plugins / "installed_plugins.json").unlink()
        try:
            labeller.data_dir({"plugins": tmp}, tools)
        except labeller.Refusal as r:
            assert r.code == "home"
        else:
            raise AssertionError("no key must be refused")


# ---------------------------------------------------------------------------
# vocabularies and classes


def test_vocabularies_answers_the_lists_the_nestings_and_the_records_groups():
    group = {"key": "FooSpecs/001_one", "spec_repo": "FooSpecs", "name": "One",
             "summary": "s", "slices": ["001_one"]}
    with home() as (base, h), stubs(groups=[group]):
        code, (line,) = run("vocabularies", request(h, index="old"))
        assert code == 0
        assert line["contract"] == 1 and line["version"] == VERSION
        assert line["groups"] == [group]
        assert "work_unit_kind" in line["lists"]
        assert {"inner": "gate", "outer": "phase"} in line["nesting"]
        assert StubRecords.loaded == [(base / "data", "old")]


def test_classes_answers_each_files_class_in_request_order_with_file_rules():
    with home() as (base, h):
        (base / "data" / "runs" / "FooSpecs").mkdir(parents=True)
        files = [["Foo", "a.md"], ["FooSpecs", "slices/001_x/state.json"], ["Foo", "b.py"]]
        code, (line,) = run("classes", request(h, files=files))
        assert code == 0
        assert line["classes"] == ["docs", "record", "code"]
        assert set(line) == {"contract", "version", "file_rules", "classes"}
        assert re.fullmatch(r"[A-Za-z0-9_-]{22}", line["file_rules"])


def test_classes_refuses_files_that_are_not_pairs():
    with home() as (_, h):
        for files in (None, [["Foo"]], [["Foo", 3]], "x"):
            code, (line,) = run("classes", request(h, files=files))
            assert code == 2 and line["error"]["code"] == "request", files


# ---------------------------------------------------------------------------
# The stamp


def test_a_stamp_is_the_format_a_digest_and_the_named_slices():
    s = labeller.format_stamp({"a": 1})
    assert re.fullmatch(r"1:[A-Za-z0-9_-]{22}", s)
    assert labeller.format_stamp({"a": 1}, ["X/1", "Y/2", "X/1"]) == s + ":X/1,Y/2"
    assert labeller.parse_stamp(s + ":X/1,Y/2") == ["X/1", "Y/2"]
    for text in (s, None, "", "2:abc:X/1", "garbage"):
        assert labeller.parse_stamp(text) == []


def stamps_request(h, *convs, pilot=(), index=None):
    return request(h, pilot={"conversations": list(pilot)}, index=index,
                   conversations=list(convs))


def held(agent_id=None, stamp=None, agent_type=None):
    t = {"agent_id": agent_id, "held": stamp}
    if agent_type:
        t["agent_type"] = agent_type
    return t


def test_stamps_answers_every_transcript_in_request_order_with_the_declarations():
    with home() as (base, h), stubs(units={"s1": ["u1"]}):
        req = stamps_request(h, conversation("s1", held("a1", agent_type="Explore"), held()),
                             conversation("s2", held()), index="prev")
        code, (line,) = run("stamps", req)
        assert code == 0
        assert set(line) == {"contract", "version", "declarations", "file_rules", "index",
                             "stamps"}
        assert [(s["session_id"], s["agent_id"]) for s in line["stamps"]] == [
            ("s1", "a1"), ("s1", None), ("s2", None)]
        assert all(re.fullmatch(r"1:[A-Za-z0-9_-]{22}", s["stamp"]) for s in line["stamps"])
        assert len({s["stamp"] for s in line["stamps"]}) == 3
        assert line["index"] == "blob<prev>"
        assert StubRecords.loaded == [(base / "data", "prev")]


def test_declarations_is_the_digest_of_the_vocabularies_answer():
    with home() as (_, h), stubs(groups=[{"key": "k"}]):
        _, (line,) = run("stamps", stamps_request(h))
        _, (vocab,) = run("vocabularies", request(h))
        sys.path.insert(0, str(_HERE))
        import labeller_vocab
        assert line["declarations"] == labeller_vocab.digest(vocab)
        StubRecords.group_list = []
        _, (again,) = run("stamps", stamps_request(h))
        assert again["declarations"] != line["declarations"]


def stamp_of(h, conv, pilot=()):
    _, (line,) = run("stamps", stamps_request(h, conv, pilot=pilot))
    return [s["stamp"] for s in line["stamps"]]


def test_a_stamp_changes_with_the_records_inputs_and_the_context_and_only_with_them():
    sessions = [{"id": "p1", "kind": "work", "created_at": "2026-11-15T18:00:00Z",
                 "brief": "/dev:run-slice 001_one", "repo": "Foo", "clarification": False}]
    docs = [{"id": "d1", "session": "p1", "source_path": "/work/FooSpecs/x.md"}]
    with home() as (_, h), stubs(units={"s1": ["u1"]}):
        base = stamp_of(h, conversation("s1", held(), sessions=sessions, documents=docs))
        assert stamp_of(h, conversation("s1", held(), sessions=sessions, documents=docs)) == base
        StubRecords.units["s1"] = ["u1", "u2"]
        assert stamp_of(h, conversation("s1", held(), sessions=sessions,
                                        documents=docs)) != base
        StubRecords.units["s1"] = ["u1"]
        other = [dict(sessions[0], brief="/dev:plan-slice 001_one")]
        assert stamp_of(h, conversation("s1", held(), sessions=other, documents=docs)) != base
        moved = [dict(docs[0], source_path="/work/FooSpecs/y.md")]
        assert stamp_of(h, conversation("s1", held(), sessions=sessions,
                                        documents=moved)) != base
        assert stamp_of(h, conversation("s1", held(), sessions=sessions, documents=docs),
                        pilot=["s1"]) != base
        # A Session's `created_at` places a Launch on it, so it is an input.
        later = [dict(sessions[0], created_at="2026-11-16T00:00:00Z")]
        assert stamp_of(h, conversation("s1", held(), sessions=later, documents=docs)) != base
        # A Session's Holds and Turns give a later Launch its wait cause (D6).
        turned = [dict(sessions[0], turns=[{"started_at": "2026-11-15T18:00:01Z",
                                            "cause": "brief"}])]
        with_turns = stamp_of(h, conversation("s1", held(), sessions=turned, documents=docs))
        assert with_turns != base
        caused = [dict(turned[0], turns=[dict(turned[0]["turns"][0], cause="person")])]
        assert stamp_of(h, conversation("s1", held(), sessions=caused,
                                        documents=docs)) != with_turns
        holding = [dict(turned[0], holds=[{"kind": "slot", "started_at": "2026-11-15T18:00:00Z",
                                           "ended_at": "2026-11-15T18:00:01Z"}])]
        assert stamp_of(h, conversation("s1", held(), sessions=holding,
                                        documents=docs)) != with_turns
        # Facts Pilot hands that no rule reads change nothing.
        renamed = [dict(sessions[0], id="p9")]
        assert stamp_of(h, conversation("s1", held(), sessions=renamed,
                                        documents=docs)) == base


def test_a_subagents_stamp_takes_its_agent_type():
    with home() as (_, h), stubs():
        a = stamp_of(h, conversation("s1", held("a1", agent_type="Explore")))
        b = stamp_of(h, conversation("s1", held("a1", agent_type="general-purpose")))
        assert a != b


def test_stamps_carries_the_held_stamps_named_slices_into_the_tie_and_the_text():
    with home() as (_, h), stubs():
        plain = stamp_of(h, conversation("s1", held()))[0]
        named = stamp_of(h, conversation("s1", held(stamp=plain + ":FooSpecs/044")))[0]
        assert named.endswith(":FooSpecs/044")
        assert named.split(":")[1] != plain.split(":")[1]  # the tie saw the name
        # The held stamp's digest is never read: the stamp is computed again.
        assert stamp_of(h, conversation("s1", held(stamp="1:stale")))[0] == plain


def test_a_transcript_whose_stamp_cannot_be_computed_gets_a_null_stamp_alone():
    with home() as (_, h), stubs(fail={"bad"}):
        _, (line,) = run("stamps", stamps_request(h, conversation("bad", held()),
                                                  conversation("good", held())))
        assert [s["stamp"] is None for s in line["stamps"]] == [True, False]


def test_an_index_past_the_cap_is_not_handed_back():
    assert labeller._index_out("x" * labeller.INDEX_CAP) == "x" * labeller.INDEX_CAP
    assert labeller._index_out("x" * (labeller.INDEX_CAP + 1)) is None
    assert labeller._index_out(None) is None


def test_stamps_refuses_conversations_that_are_not_a_list_of_objects():
    with home() as (_, h), stubs():
        for convs in (None, [{"transcripts": []}], [{"session_id": "s", "transcripts": 3}]):
            code, (line,) = run("stamps", request(h, conversations=convs))
            assert code == 2 and line["error"]["code"] == "request", convs


# ---------------------------------------------------------------------------
# The label batch


def label(h, *convs, index=None, pilot=()):
    return run("label", request(h, pilot={"conversations": list(pilot)}, index=index,
                                conversations=list(convs)))


def test_label_streams_a_header_a_line_per_transcript_main_first_and_done():
    with home() as (base, h), stubs():
        code, lines = label(h,
                            conversation("s1", whole("x/a1.jsonl", "a1"), whole("x/s1.jsonl"),
                                         whole("x/a2.jsonl", "a2")),
                            conversation("s2", whole("x/s2.jsonl")), index="i0")
        assert code == 0
        assert lines[0] == {"contract": 1, "version": VERSION}
        assert [(ln["session_id"], ln["agent_id"]) for ln in lines[1:-1]] == [
            ("s1", None), ("s1", "a1"), ("s1", "a2"), ("s2", None)]
        assert all(ln["answer"] == "labels" for ln in lines[1:-1])
        assert lines[-1] == {"done": True, "count": 4, "index": "blob<i0>"}
        item, tie = StubEngine.calls[0]
        assert item["file"] == str(base / "projects" / "x" / "s1.jsonl")
        assert item["session_id"] == "s1" and item["conversation"]["session_id"] == "s1"
        assert tie["session"] == "s1"
        assert re.fullmatch(r"1:[A-Za-z0-9_-]{22}", item["stamp"])


def test_label_and_stamps_give_one_transcript_the_same_stamp():
    with home() as (_, h), stubs(units={"s1": ["u"]}):
        conv = conversation("s1", whole("x/s1.jsonl"))
        _, lines = label(h, conv, pilot=["s1"])
        _, (st,) = run("stamps", stamps_request(h, conversation("s1", held()), pilot=["s1"]))
        assert lines[1]["stamp"] == st["stamps"][0]["stamp"]


def test_the_engine_restamps_with_the_slices_the_file_names_as_stamps_will():
    with home() as (_, h), stubs():
        _, lines = label(h, conversation("s1", whole("named")))
        stamp = lines[1]["stamp"]
        assert stamp.endswith(":FooSpecs/044")
        _, (st,) = run("stamps", stamps_request(h, conversation("s1", held(stamp=stamp))))
        assert st["stamps"][0]["stamp"] == stamp


def test_one_bad_transcript_fails_only_itself():
    with home() as (_, h), stubs():
        code, lines = label(h, conversation("s1", whole("raise-calls_mismatch"),
                                            whole("oserror", "a1"), whole("boom", "a2"),
                                            whole("../outside.jsonl", "a3"),
                                            whole("x/fine.jsonl", "a4")))
        assert code == 0
        by_agent = {ln["agent_id"]: ln for ln in lines[1:-1]}
        assert by_agent[None] == {"session_id": "s1", "agent_id": None, "answer": "error",
                                  "error": {"code": "calls_mismatch", "detail": "the detail"}}
        assert by_agent["a1"]["error"]["code"] == "unreadable"
        assert by_agent["a2"]["error"]["code"] == "internal"
        assert "KeyError" in by_agent["a2"]["error"]["detail"]
        assert "test_labeller.py" in by_agent["a2"]["error"]["detail"]  # the last frame
        assert by_agent["a3"]["error"]["code"] == "unreadable"
        assert by_agent["a4"]["answer"] == "labels"
        assert lines[-1]["count"] == 5


def test_a_tie_that_raises_is_an_internal_error_of_its_transcript():
    with home() as (_, h), stubs(fail={"bad"}):
        _, lines = label(h, conversation("bad", whole("x/a.jsonl")),
                         conversation("ok", whole("x/b.jsonl")))
        assert [ln["answer"] for ln in lines[1:-1]] == ["error", "labels"]
        assert lines[1]["error"]["code"] == "internal"


def test_each_line_is_written_and_flushed_as_its_transcript_is_done():
    seen = []

    class Out(io.StringIO):
        def flush(self):
            seen.append(self.getvalue().count("\n"))

    with home() as (_, h), stubs():
        out = Out()
        req = request(h, conversations=[conversation("s1", whole("x/a"), whole("x/b", "a1"))])
        labeller.main(["label"], io.StringIO(json.dumps(req)), out)
        assert seen == [1, 2, 3, 4]


def test_the_lines_before_a_crash_stand_and_no_done_line_follows():
    with home() as (_, h), stubs():
        out = io.StringIO()
        boom = StubEngine.label_one

        def label_one(item, tie, records):
            if item["agent_id"] == "a1":
                raise SystemExit("cut")  # not an Exception: the batch stops here
            return boom(item, tie, records)

        sys.modules["labeller_engine"].label_one = label_one
        req = request(h, conversations=[conversation("s1", whole("x/a"), whole("x/b", "a1"))])
        with contextlib.suppress(SystemExit):
            labeller.main(["label"], io.StringIO(json.dumps(req)), out)
        lines = [json.loads(x) for x in out.getvalue().splitlines()]
        assert [ln.get("answer") for ln in lines] == [None, "labels"]
        assert not any(ln.get("done") for ln in lines)


def test_a_malformed_label_request_is_refused_before_any_line():
    with home() as (_, h), stubs():
        for t in ({"agent_id": None, "mode": "whole", "calls": []},
                  {"agent_id": None, "path": "x", "mode": "partial", "calls": []},
                  {"agent_id": None, "path": "x", "mode": "whole"},
                  {"agent_id": None, "path": "x", "mode": "appended", "calls": []}):
            code, lines = label(h, conversation("s1", t))
            assert code == 2 and len(lines) == 1, t
            assert lines[0]["error"]["code"] == "request"
        assert StubEngine.calls == []


def test_an_appended_transcript_reaches_the_engine_as_handed():
    with home() as (_, h), stubs():
        t = {"agent_id": None, "path": "x/a.jsonl", "mode": "appended",
             "from": {"call": "msg_9", "byte": 4096}, "checkpoint": "1:v:abc",
             "launches": [{"n": 2, "started_at": "t"}], "calls": [{"id": "msg_9"}]}
        code, lines = label(h, conversation("s1", t))
        assert code == 0 and lines[1]["answer"] == "labels"
        item, _ = StubEngine.calls[0]
        assert item["from"] == t["from"] and item["checkpoint"] == "1:v:abc"
        assert item["mode"] == "appended"


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
