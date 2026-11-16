"""Tests for pilot_progress — a loop's steps, the helpers that edit the list,
the one `set_progress` call that sends it, the publisher `wait` uses, and the
one-off publish of a list given (`publish_steps`).

HTTP is faked at the opener seam: no test reaches a network. Stdlib only;
runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_pilot_progress.py` or via pytest.
"""

import importlib.util
import io
import json
import sys
import tempfile
import urllib.error
from datetime import datetime
from email.message import Message
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "pilot_progress", Path(__file__).resolve().parent / "pilot_progress.py"
)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)

URL = "http://pilot.invalid/mcp"
TOKEN = "tok-s3cret"
ENV = {"PILOT_TOKEN": TOKEN, "PILOT_MCP_URL": URL}


class FakeResponse:
    """What `urlopen` hands back: the Content-Type and a body read line by
    line or whole."""

    def __init__(self, body: str | bytes,
                 content_type="text/event-stream"):
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        self._body = io.BytesIO(body.encode() if isinstance(body, str)
                                else body)

    def readline(self):
        return self._body.readline()

    def read(self):
        return self._body.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """An opener answering each call with the next of `answers` — a
    response, or an exception to raise — and recording each request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []    # (request, timeout)

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        answer = self.answers.pop(0) if len(self.answers) > 1 \
            else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer()
        return answer

    def sent(self):
        """The step lists the `set_progress` calls carried."""
        return [json.loads(r.data)["params"]["arguments"]["steps"]
                for r, _ in self.requests
                if json.loads(r.data)["method"] == "tools/call"]

    def methods(self):
        return [json.loads(r.data)["method"] for r, _ in self.requests]


def result(steps):
    return {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text",
                                    "text": json.dumps({"steps": steps})}],
                       "structuredContent": {"steps": steps}}}


def sse(*events):
    """A `text/event-stream` body of `events`, each a list of lines."""
    return "".join("\n".join(lines) + "\n\n" for lines in events)


def ok_stream(steps):
    return FakeResponse(sse(["event: message",
                             f"data: {json.dumps(result(steps))}"]))


STEPS = [{"code": "P1.code", "label": "P1 · First", "state": "done"},
         {"code": "P1.review", "label": "P1 · review", "state": "active"}]
# The same run a round later: its repeat round's step with its why.
WHY = "The reviewer found the beat's spec passing with the beat removed"
WHY_STEPS = [STEPS[0], dict(STEPS[1], state="done"),
             {"code": "P1.code-2", "label": "P1 · code 2", "state": "active",
              "why": WHY}]


def pilot_tools(why=True, debrief=True, subject=True):
    """A Pilot's `tools/list`, as its MCP server lists the `pilot-work`
    tools: `set_progress`'s steps with a `why` where `why`, and
    `register_debrief` where `debrief`, its `subject` and `completes` where
    `subject` — a Pilot before the debrief's notice lists neither."""
    step = {"properties": {
        "code": {"maxLength": 64, "minLength": 1, "type": "string"},
        "label": {"maxLength": 120, "minLength": 1, "type": "string"},
        "state": {"anyOf": [{"enum": ["pending", "active", "done"]},
                            {"type": "null"}], "default": None}},
        "required": ["code", "label"], "title": "Step", "type": "object"}
    if why:
        step["properties"]["why"] = {
            "anyOf": [{"maxLength": 120, "minLength": 1, "type": "string"},
                      {"type": "null"}], "default": None}
    tools = [
        {"name": "register_document", "inputSchema": {"type": "object"}},
        {"name": "set_progress", "inputSchema": {
            "$defs": {"Step": step},
            "properties": {"steps": {"items": {"$ref": "#/$defs/Step"},
                                     "maxItems": 100, "type": "array"}},
            "required": ["steps"], "type": "object"}},
        {"name": "set_progress_step", "inputSchema": {"type": "object"}}]
    if debrief:
        fields = {
            "debrief": {"maxLength": 16000, "minLength": 1, "type": "string"},
            "entries": {"items": {"$ref": "#/$defs/DebriefEntry"},
                        "maxItems": 500, "minItems": 1, "type": "array"}}
        if subject:
            fields["subject"] = {
                "anyOf": [{"maxLength": 120, "minLength": 1, "type": "string"},
                          {"type": "null"}], "default": None}
            fields["completes"] = {"default": True, "type": "boolean"}
        tools.append({"name": "register_debrief", "inputSchema": {
            "$defs": {"DebriefEntry": {"type": "object"}},
            "properties": fields, "required": ["debrief", "entries"],
            "type": "object"}})
    return tools


def listed(tools=None, **takes):
    message = {"jsonrpc": "2.0", "id": 1,
               "result": {"tools": pilot_tools(**takes) if tools is None
                          else tools}}
    return FakeResponse(sse(["event: message", f"data: {json.dumps(message)}"]))


# -- the client ---------------------------------------------------------------

def test_the_request_is_one_tools_call_of_set_progress():
    opener = FakeOpener(ok_stream(STEPS))
    answer = pp.send(STEPS, URL, TOKEN, opener)
    assert answer == pp.Answer(pp.OK, {"steps": STEPS}, "")
    [(request, timeout)] = opener.requests
    assert request.full_url == URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Accept") == "application/json, text/event-stream"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "set_progress", "arguments": {"steps": STEPS}}}
    assert timeout == pp.TIMEOUT == 3


def test_the_event_stream_is_read_for_the_response_to_id_1():
    """An `event:` line, CRLF line ends, a response split over several
    `data:` lines and a notification ahead of it: the event that answers
    id 1 is the one taken."""
    notification = {"jsonrpc": "2.0", "method": "notifications/message",
                    "params": {"level": "info", "data": "working"}}
    lines = json.dumps(result(STEPS), indent=1).splitlines()
    body = ("event: message\r\n"
            f"data: {json.dumps(notification)}\r\n\r\n"
            "event: message\r\n"
            + "".join(f"data: {line}\r\n" for line in lines)
            + "\r\n"
            + "data: never read\r\n\r\n")
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(FakeResponse(body)))
    assert (answer.kind, answer.steps) == (pp.OK, {"steps": STEPS})
    # `data:` with no space after it, and a stream that ends with no blank
    # line after its last event
    body = f"data:{json.dumps(result(STEPS))}"
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(FakeResponse(body)))
    assert answer.kind == pp.OK


def test_a_json_answer_is_the_response_itself():
    response = FakeResponse(json.dumps(result(STEPS)),
                            content_type="application/json; charset=utf-8")
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(response))
    assert (answer.kind, answer.steps) == (pp.OK, {"steps": STEPS})


def test_is_error_is_a_refusal_with_its_text():
    refusal = {"jsonrpc": "2.0", "id": 1, "result": {
        "isError": True,
        "content": [{"type": "text", "text": "steps[1].code: too long"},
                    {"type": "image", "data": "x"},
                    {"type": "text", "text": "and one more"}]}}
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(
        FakeResponse(sse([f"data: {json.dumps(refusal)}"]))))
    assert answer == pp.Answer(pp.REFUSED, None,
                               "steps[1].code: too long and one more")


def test_a_json_rpc_error_is_a_refusal():
    error = {"jsonrpc": "2.0", "id": 1,
             "error": {"code": -32602, "message": "Unknown tool: set_progress"}}
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(
        FakeResponse(sse([f"data: {json.dumps(error)}"]))))
    assert answer == pp.Answer(pp.REFUSED, None, "Unknown tool: set_progress")


def http_error(code, msg):
    return urllib.error.HTTPError(URL, code, msg, Message(), io.BytesIO(b""))


def test_no_answer_is_every_failure_to_get_one():
    cases = [
        (http_error(406, "Not Acceptable"), "HTTP 406 Not Acceptable"),
        (http_error(400, "Invalid Content-Type header"),
         "HTTP 400 Invalid Content-Type header"),
        (http_error(401, "Unauthorized"), "HTTP 401 Unauthorized"),
        (http_error(503, "Service Unavailable"), "HTTP 503"),
        (urllib.error.URLError(ConnectionRefusedError(111, "refused")),
         "URLError"),
        (TimeoutError("timed out"), "TimeoutError: timed out"),
        (ConnectionResetError(104, "Connection reset by peer"),
         "Connection reset"),
    ]
    for error, why in cases:
        answer = pp.send(STEPS, URL, TOKEN, FakeOpener(error))
        assert answer.kind == pp.NO_ANSWER, error
        assert why in answer.reason, (error, answer.reason)
    # an answer that holds no response to id 1
    for body in ("", sse(['data: {"jsonrpc": "2.0", "method": "ping"}']),
                 sse(["data: not json"]),
                 sse(['data: {"jsonrpc": "2.0", "id": 2, "result": {}}'])):
        answer = pp.send(STEPS, URL, TOKEN, FakeOpener(FakeResponse(body)))
        assert answer.kind == pp.NO_ANSWER, body
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(
        FakeResponse("<html>", content_type="application/json")))
    assert answer.kind == pp.NO_ANSWER
    # past the deadline nothing more is read
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(ok_stream(STEPS)),
                     timeout=0)
    assert answer.kind == pp.NO_ANSWER


def test_no_reason_holds_the_token():
    for error in (urllib.error.URLError(f"bad header Bearer {TOKEN}"),
                  RuntimeError(TOKEN)):
        answer = pp.send(STEPS, URL, TOKEN, FakeOpener(error))
        assert answer.kind == pp.NO_ANSWER and TOKEN not in answer.reason
    refusal = {"jsonrpc": "2.0", "id": 1,
               "error": {"message": f"token {TOKEN} expired"}}
    answer = pp.send(STEPS, URL, TOKEN, FakeOpener(
        FakeResponse(sse([f"data: {json.dumps(refusal)}"]))))
    assert answer.kind == pp.REFUSED and TOKEN not in answer.reason


def test_the_list_is_held_to_pilots_limits_before_it_is_sent():
    steps = [
        {"code": "", "label": "no code", "state": "done"},
        {"code": "x" * 65, "label": "code too long", "state": "done"},
        {"code": "x" * 64, "label": "code at the limit", "state": "done"},
        {"code": "P1.code", "label": "", "state": "done"},
        {"code": "P1.code", "label": "repeated", "state": "active"},
        {"code": "P1.review", "label": "y" * 121, "state": "active"},
        {"code": "test", "label": "Test phase", "state": "failed"},
        {"code": "docs", "label": "z" * 120},
        "not a step",
        {"label": "no code at all"},
    ]
    assert pp.sanitize(steps) == [
        {"code": "x" * 64, "label": "code at the limit", "state": "done"},
        {"code": "P1.code", "label": "P1.code", "state": "done"},
        {"code": "P1.review", "label": "y" * 119 + "…", "state": "active"},
        {"code": "test", "label": "Test phase"},
        {"code": "docs", "label": "z" * 120},
    ]
    many = [{"code": f"s{i}", "label": f"step {i}", "state": "done"}
            for i in range(101)]
    kept = pp.sanitize(many)
    assert len(kept) == 100 and kept[0]["code"] == "s1" \
        and kept[-1]["code"] == "s100"
    assert pp.sanitize(None) == [] and pp.sanitize({"steps": []}) == []
    opener = FakeOpener(ok_stream([]))
    pp.send(steps, URL, TOKEN, opener)
    assert opener.sent() == [pp.sanitize(steps)]


def test_a_why_is_sent_only_when_asked_and_held_to_pilots_limits():
    steps = [
        {"code": "a", "label": "A", "state": "done", "why": " one\n line "},
        {"code": "b", "label": "B", "state": "done", "why": "  "},
        {"code": "c", "label": "C", "state": "active", "why": "x" * 130},
        {"code": "d", "label": "D", "why": 5},
        {"code": "e", "label": "E", "state": "pending"},
    ]
    bare = [{"code": "a", "label": "A", "state": "done"},
            {"code": "b", "label": "B", "state": "done"},
            {"code": "c", "label": "C", "state": "active"},
            {"code": "d", "label": "D"},
            {"code": "e", "label": "E", "state": "pending"}]
    assert pp.sanitize(steps) == bare
    with_whys = pp.sanitize(steps, why=True)
    assert [s.get("why") for s in with_whys] == [
        "one line", None, "x" * 119 + "…", None, None]
    assert [{k: v for k, v in s.items() if k != "why"} for s in with_whys] \
        == bare
    assert pp.has_why(steps) and not pp.has_why(bare)
    assert not pp.has_why([steps[1], steps[3], "not a step"])
    opener = FakeOpener(lambda: ok_stream([]))
    pp.send(steps, URL, TOKEN, opener)
    pp.send(steps, URL, TOKEN, opener, why=True)
    assert opener.sent() == [bare, with_whys]


# -- what a Pilot takes -------------------------------------------------------

def test_discover_reads_what_a_pilot_takes_from_its_own_tools_list():
    opener = FakeOpener(listed())
    answer = pp.discover(URL, TOKEN, opener)
    assert answer == pp.Answer(pp.OK, takes=pp.Takes(why=True, debrief=True,
                                                     subject=True))
    [(request, timeout)] = opener.requests
    assert json.loads(request.data) == {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert request.full_url == URL and request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert request.get_header("Accept") == "application/json, text/event-stream"
    assert timeout == pp.TIMEOUT
    # a Pilot that takes none of them, and each read apart
    for takes, want in (
            ({"why": False, "debrief": False}, pp.NOTHING),
            ({"why": False}, pp.Takes(debrief=True, subject=True)),
            ({"debrief": False}, pp.Takes(why=True)),
            ({"subject": False}, pp.Takes(why=True, debrief=True))):
        assert pp.discover(URL, TOKEN, FakeOpener(listed(**takes))).takes \
            == want, takes
    assert pp.NOTHING == pp.Takes(why=False, debrief=False, subject=False)
    # a schema with the step inline, and a JSON answer
    inline = [{"name": "set_progress", "inputSchema": {"properties": {
        "steps": {"items": {"properties": {"code": {}, "why": {}}}}}}}]
    assert pp.discover(URL, TOKEN, FakeOpener(listed(inline))).takes == \
        pp.Takes(why=True)
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "result": {"tools": pilot_tools()}})
    assert pp.discover(URL, TOKEN, FakeOpener(FakeResponse(
        body, content_type="application/json"))).takes == \
        pp.Takes(why=True, debrief=True, subject=True)


def test_the_debrief_takes_a_subject_only_where_both_its_fields_are_listed():
    def takes(schema):
        tools = [{"name": "register_debrief", "inputSchema": schema}]
        return pp.discover(URL, TOKEN, FakeOpener(listed(tools))).takes
    both = {"debrief": {}, "entries": {}, "subject": {}, "completes": {}}
    assert takes({"properties": both}) == pp.Takes(debrief=True, subject=True)
    for schema in (
            {"properties": {"debrief": {}, "entries": {}, "subject": {}}},
            {"properties": {"debrief": {}, "entries": {}, "completes": {}}},
            {"properties": {"debrief": {}, "entries": {}}},
            {"$defs": {"Arguments": {"properties": both}}},
            {"properties": []}, {}, "not a schema", None):
        assert takes(schema) == pp.Takes(debrief=True), schema
    assert pp.discover(URL, TOKEN, FakeOpener(listed(
        [{"name": "register_debrief"}]))).takes == pp.Takes(debrief=True)


def test_a_schema_that_does_not_give_a_step_a_why_takes_none():
    step = {"properties": {"code": {}, "why": {}}}
    for schema in (
            {},
            {"properties": {"steps": {"items": {"$ref": "#/definitions/Step"}}},
             "definitions": {"Step": step}},
            {"properties": {"steps": {"items": {"$ref": "#/$defs/Missing"}}},
             "$defs": {"Step": step}},
            {"properties": []},
            "not a schema"):
        tools = [{"name": "set_progress", "inputSchema": schema}]
        assert pp.discover(URL, TOKEN, FakeOpener(listed(tools))).takes == \
            pp.NOTHING, schema
    for tools in ([{"name": "set_progress"}], ["set_progress"], []):
        assert pp.discover(URL, TOKEN, FakeOpener(listed(tools))).takes == \
            pp.NOTHING, tools


def test_discover_says_why_where_no_list_came():
    refusal = {"jsonrpc": "2.0", "id": 1,
               "error": {"code": -32601, "message": f"no list for {TOKEN}"}}
    assert pp.discover(URL, TOKEN, FakeOpener(FakeResponse(sse([
        f"data: {json.dumps(refusal)}"])))) == pp.Answer(
        pp.REFUSED, reason="no list for <token>")
    no_tools = {"jsonrpc": "2.0", "id": 1, "result": {}}
    for answer, reason in (
            (urllib.error.URLError("down"), "URLError: down"),
            (http_error(502, "Bad Gateway"), "HTTP 502 Bad Gateway"),
            (RuntimeError(TOKEN), "RuntimeError: <token>"),
            (FakeResponse(sse(["data: not json"])),
             "the answer held no JSON-RPC response"),
            (FakeResponse(sse([f"data: {json.dumps(no_tools)}"])),
             "the answer listed no tools")):
        assert pp.discover(URL, TOKEN, FakeOpener(answer)) == pp.Answer(
            pp.NO_ANSWER, reason=reason), answer


# -- the list -----------------------------------------------------------------

def test_a_code_names_its_phase_kind_and_round():
    code = pp.step_code
    assert [code("code", 1, "3"), code("code", 2, "3"), code("review", 1, "3a"),
            code("review", 2, "3a"), code("sweep"), code("sweep", 2),
            code("consult"), code("test"), code("test", 2), code("docs"),
            code("wrap-up"), code("ground"), code("write"), code("write", 2),
            code("review")] == [
        "P3.code", "P3.code-2", "P3a.review", "P3a.review-2", "sweep",
        "sweep-2", "consult", "test", "test-2", "docs", "wrap-up", "ground",
        "write", "write-2", "review"]
    assert pp.PLAN_KINDS == ("ground", "write", "review")
    try:
        code("merge")
    except ValueError:
        pass
    else:
        raise AssertionError("a kind outside the set was given a code")
    assert pp.phase_of("P3a.review-2") == "3a"
    assert pp.phase_of("review-2") is None
    assert [pp.split_code(c) for c in (
        "P3a.review-2", "P3.code", "sweep", "consult-12", "wrap-up",
        "write-2")] == [
        ("3a", "review", 2), ("3", "code", 1), (None, "sweep", 1),
        (None, "consult", 12), (None, "wrap-up", 1), (None, "write", 2)]
    assert pp.clip_label("a" * 121) == "a" * 119 + "…"
    assert pp.clip_label("a" * 120) == "a" * 120


def codes(steps):
    return [(s["code"], s["state"]) for s in steps]


def seeded():
    return (pp.phase_steps("1", "First") + pp.phase_steps("2", "Second")
            + [pp.make_step("test", "Test phase"),
               pp.make_step("wrap-up", "Wrap-up")])


def test_start_makes_one_step_active_in_the_order_taken():
    base = seeded()
    assert base[0] == {"code": "P1.code", "label": "P1 · First",
                       "state": "pending"}
    steps = pp.start(base, "P1.code", "P1 · First")
    steps = pp.start(steps, "P1.code-2", "P1 · code 2")
    assert codes(steps)[:3] == [("P1.code", "done"), ("P1.code-2", "active"),
                                ("P1.review", "pending")]
    steps = pp.start(steps, "P1.review", "P1 · review")
    steps = pp.start(steps, "P1.code-3", "P1 · code 3")
    assert codes(steps) == [
        ("P1.code", "done"), ("P1.code-2", "done"), ("P1.review", "done"),
        ("P1.code-3", "active"), ("P2.code", "pending"),
        ("P2.review", "pending"), ("test", "pending"), ("wrap-up", "pending")]
    # a step on the list keeps its place, its label the one given
    again = pp.start(steps, "P2.code", "P2 · Second, renamed")
    assert codes(again)[3:5] == [("P1.code-3", "done"), ("P2.code", "active")]
    assert again[4]["label"] == "P2 · Second, renamed"
    # nothing pending: at the end
    done = pp.finish_phase(pp.finish_phase(steps, "1"), "2")
    done = pp.finish_step(pp.finish_step(done, "test"), "wrap-up")
    assert pp.start(done, "sweep", "Gate sweep")[-1] == {
        "code": "sweep", "label": "Gate sweep", "state": "active"}
    # the edits leave the list they were given as it was
    assert base == seeded()


T0, T1 = "2026-11-04T09:00:00+01:00", "2026-11-04T09:30:00+01:00"


def test_a_started_step_carries_its_time_and_a_resume_restarts_it():
    steps = pp.start(seeded(), "P1.code", "P1 · First", T0)
    assert steps[0] == {"code": "P1.code", "label": "P1 · First",
                        "state": "active", "started": T0}
    # a new step, and a step started again, take the time given
    steps = pp.start(steps, "P1.code-2", "P1 · code 2", T1)
    assert steps[1]["started"] == T1 and steps[0]["started"] == T0
    assert pp.start(steps, "P1.code-2", "P1 · code 2", T0)[1]["started"] == T0
    # no time given, none recorded and none dropped
    assert "started" not in pp.start(seeded(), "P1.code", "P1 · First")[0]
    assert pp.start(steps, "P1.code-2", "P1 · code 2")[1]["started"] == T1
    # the resume: the active step alone, an older one with none included
    restarted = pp.restart_clock(steps, "later")
    assert [s.get("started") for s in restarted[:3]] == [T0, "later", None]
    assert pp.restart_clock(seeded(), "later") == seeded()
    # Pilot never sees it
    assert pp.sanitize(steps)[1] == {"code": "P1.code-2",
                                     "label": "P1 · code 2", "state": "active"}


def test_a_why_is_one_line_held_to_pilots_limit():
    assert pp.clip_why("  The gate\n went   red\t") == "The gate went red"
    assert pp.clip_why("w" * 120) == "w" * 120
    assert pp.clip_why("w" * 121) == "w" * 119 + "…"
    assert pp.WHY_MAX == 120
    for nothing in ("", " \n\t", None, 7, ["a"]):
        assert pp.clip_why(nothing) is None, nothing


def test_a_step_carries_its_why_and_a_restart_without_one_keeps_it():
    assert pp.make_step("P1.code-2", "P1 · code 2", why=" The gate\nwent red ") \
        == {"code": "P1.code-2", "label": "P1 · code 2", "state": "pending",
            "why": "The gate went red"}
    assert pp.make_step("P1.code", "P1 · First", why=" ") == \
        pp.make_step("P1.code", "P1 · First")
    steps = pp.start(seeded(), "P1.code", "P1 · First")
    steps = pp.start(steps, "P1.code-2", "P1 · code 2", T0, why=WHY)
    assert steps[1] == {"code": "P1.code-2", "label": "P1 · code 2",
                        "state": "active", "started": T0, "why": WHY}
    # started again: without a why it keeps its own, with one it takes it
    assert pp.start(steps, "P1.code-2", "P1 · code 2", T1)[1]["why"] == WHY
    assert pp.start(steps, "P1.code-2", "P1 · code 2",
                    why="Another")[1]["why"] == "Another"
    # past the limit, cut as Pilot would refuse it whole
    assert pp.start(seeded(), "sweep-2", "Gate sweep 2", why="x" * 200)[0][
        "why"] == "x" * 119 + "…"
    # what finishes a step leaves its why
    for edit in (pp.finish_active, lambda s: pp.finish_phase(s, "1")):
        assert edit(steps)[1]["why"] == WHY


def test_a_step_is_taken_once_started_and_follows_the_step_started_last():
    steps = pp.start(seeded(), "P1.code", "P1 · First")
    assert pp.taken(steps, "P1.code")
    # seeded but not reached, and not on the list at all
    assert not pp.taken(steps, "P1.review")
    assert not pp.taken(steps, "P1.code-2")
    assert pp.follows(steps, "code", "1")
    assert not pp.follows(steps, "code", "2")
    assert not pp.follows(steps, "review", "1")
    assert not pp.follows(steps, "code")
    # done, it is still the step started last
    assert pp.follows(pp.finish_active(steps), "code", "1")
    steps = pp.start(pp.finish_phase(steps, "1"), "sweep-2", "Gate sweep 2")
    assert pp.follows(steps, "sweep") and not pp.follows(steps, "sweep", "1")
    assert not pp.follows(seeded(), "code", "1") and not pp.follows([], "code")


def test_the_active_summary_names_the_phase_the_step_and_its_minutes():
    now = datetime.fromisoformat("2026-11-04T10:12:30+01:00")

    def summary(code, started=T0, state="active"):
        step = {"code": code, "label": "x", "state": state}
        if started is not None:
            step["started"] = started
        return pp.active_summary([{"code": "P1.code", "label": "x",
                                   "state": "done"}, step], now)

    assert [summary("P4.code"), summary("P4.review-2"), summary("P3a.code-3"),
            summary("sweep-2"), summary("consult"), summary("test"),
            summary("docs"), summary("wrap-up"), summary("write-2"),
            summary("review")] == [
        "P4 code, 1h12m", "P4 review r2, 1h12m", "P3a code r3, 1h12m",
        "sweep r2, 1h12m", "consult, 1h12m", "test, 1h12m", "docs, 1h12m",
        "wrap-up, 1h12m", "write r2, 1h12m", "review, 1h12m"]
    assert [summary("P4.code", started) for started in (
        "2026-11-04T10:00:00+01:00", "2026-11-04T09:12:00Z",
        "2026-11-04T10:12:00+01:00", "2026-11-04T10:20:00+01:00",
        "2026-11-03T09:00:00+01:00")] == [
        "P4 code, 12m", "P4 code, <1m", "P4 code, <1m", "P4 code, <1m",
        "P4 code, 25h12m"]
    # an older loop's step, or a time that does not read: no elapsed
    for started in (None, "", "yesterday", "2026-11-04T09:00:00", 1730710000):
        assert summary("P4.code", started) == "P4 code", started
    # no active step, or no list: nothing to say
    assert summary("P4.code", state="done") is None
    for steps in (None, [], {"steps": []}, ["P4.code"], [{"state": "active"}]):
        assert pp.active_summary(steps, now) is None, steps
    # the clock's own default is the local time, offset and all
    assert pp.active_summary(
        [{"code": "test", "label": "x", "state": "active",
          "started": datetime.now().astimezone().isoformat()}]) == "test, <1m"


def test_the_active_step_is_the_one_started_last_or_none():
    steps = pp.start(seeded(), "P1.code", "P1 · First")
    assert pp.active_step(steps)["code"] == "P1.code"
    assert pp.active_step(pp.start(steps, "P1.review", "P1 · review"))[
        "code"] == "P1.review"
    for none in (seeded(), pp.finish_active(steps), [], None, "x",
                 [None, "x"]):
        assert pp.active_step(none) is None, none


def test_finishing_marks_the_active_step_or_a_whole_phase_done():
    steps = pp.start(seeded(), "P1.code", "P1 · First")
    assert codes(pp.finish_active(steps))[0] == ("P1.code", "done")
    assert codes(pp.finish_phase(steps, "1"))[:3] == [
        ("P1.code", "done"), ("P1.review", "done"), ("P2.code", "pending")]
    assert codes(pp.finish_step(steps, "wrap-up"))[-1] == ("wrap-up", "done")


def test_a_phase_goes_in_before_the_first_later_or_closing_pending_step():
    order = ["1", "1a", "2", "3"]
    steps = pp.start(seeded(), "P1.code", "P1 · First")
    # P3 appended at the end of the plan: before the closing steps
    out = pp.insert_phase(steps, "3", "Third", order)
    assert [c for c, _ in codes(out)] == [
        "P1.code", "P1.review", "P2.code", "P2.review", "P3.code",
        "P3.review", "test", "wrap-up"]
    # P1a, between P1 and P2 in the plan: before P2's pending steps
    out = pp.insert_phase(steps, "1a", "Between", order)
    assert [c for c, _ in codes(out)][:4] == [
        "P1.code", "P1.review", "P1a.code", "P1a.review"]
    assert out[2] == {"code": "P1a.code", "label": "P1a · Between",
                      "state": "pending"}
    # a phase stamped done goes in done; with nothing pending, at the end
    finished = [dict(s, state="done") for s in steps]
    out = pp.insert_phase(finished, "3", "Third", order, done=True)
    assert codes(out)[-2:] == [("P3.code", "done"), ("P3.review", "done")]
    assert pp.has_phase(out, "3") and not pp.has_phase(steps, "3")


# -- the publisher ------------------------------------------------------------

def state_file(tmp, progress=STEPS, **extra):
    path = Path(tmp) / "state.json"
    state = dict(extra)
    if progress is not None:
        state["progress"] = progress
    path.write_text(json.dumps(state))
    return path


def publisher(path, opener, env=ENV):
    lines = []
    return pp.Publisher(path, lines.append, environ=env, opener=opener), lines


def test_the_publisher_sends_a_changed_list_and_a_forced_one():
    with tempfile.TemporaryDirectory() as tmp:
        path = state_file(tmp)
        opener = FakeOpener(lambda: ok_stream(STEPS))
        pub, lines = publisher(path, opener)
        assert pub.publish(force=True).kind == pp.OK
        assert pub.publish() is None          # unchanged: nothing sent
        assert pub.publish(force=True).kind == pp.OK
        changed = STEPS + [{"code": "test", "label": "Test phase",
                            "state": "pending"}]
        state_file(tmp, changed)
        assert pub.publish().kind == pp.OK
        assert opener.sent() == [STEPS, STEPS, changed]
        assert lines == []


def test_each_failure_kind_is_logged_once_per_publisher():
    with tempfile.TemporaryDirectory() as tmp:
        path = state_file(tmp)
        refusal = {"jsonrpc": "2.0", "id": 1, "result": {
            "isError": True, "content": [{"type": "text", "text": "no\nway"}]}}
        opener = FakeOpener(
            urllib.error.URLError("refused"), urllib.error.URLError("again"),
            FakeResponse(sse([f"data: {json.dumps(refusal)}"])),
            FakeResponse(sse([f"data: {json.dumps(refusal)}"])),
            ok_stream(STEPS))
        pub, lines = publisher(path, opener)
        for _ in range(5):
            pub.publish(force=True)
        assert len(opener.requests) == 5
        assert lines == [
            f"Pilot progress not published: no answer from {URL}: "
            "URLError: refused",
            "Pilot progress not published: Pilot refused it: no way"]
        # a failed send is not retried on an unchanged list
        pub2, lines2 = publisher(path, FakeOpener(urllib.error.URLError("x")))
        pub2.publish(force=True)
        assert pub2.publish() is None
        assert len(pub2.opener.requests) == 1 and len(lines2) == 1


def test_a_state_with_no_list_sends_and_logs_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        opener = FakeOpener(ok_stream(STEPS))
        for path in (state_file(tmp, progress=None, run_phase="phases"),
                     state_file(tmp, progress={"not": "a list"}),
                     Path(tmp) / "missing.json"):
            for env in (ENV, {}):
                pub, lines = publisher(path, opener, env)
                assert pub.publish(force=True) is None
                assert lines == []
        path.write_text("{half")
        assert publisher(path, opener)[0].publish(force=True) is None
        path.write_text("[1, 2]")
        assert publisher(path, opener)[0].publish(force=True) is None
        assert opener.requests == []


def test_a_list_with_no_why_is_sent_with_no_question_of_what_pilot_takes():
    with tempfile.TemporaryDirectory() as tmp:
        opener = FakeOpener(lambda: ok_stream(STEPS))
        pub, lines = publisher(state_file(tmp), opener)
        assert pub.publish(force=True).kind == pp.OK
        assert opener.methods() == ["tools/call"] and lines == []


def test_a_why_goes_only_to_a_pilot_that_takes_it_asked_once_per_publisher():
    later = WHY_STEPS + [{"code": "P1.review-2", "label": "P1 · review 2",
                          "state": "active"}]
    for takes in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            path = state_file(tmp, WHY_STEPS)
            opener = FakeOpener(listed(why=takes),
                                lambda: ok_stream(WHY_STEPS))
            pub, lines = publisher(path, opener)
            assert pub.publish(force=True).kind == pp.OK
            state_file(tmp, later)
            assert pub.publish().kind == pp.OK
            assert opener.methods() == ["tools/list", "tools/call",
                                        "tools/call"]
            assert opener.sent() == [pp.sanitize(WHY_STEPS, why=takes),
                                     pp.sanitize(later, why=takes)]
            assert ("why" in opener.sent()[0][2]) is takes
            assert lines == []
            # the next `wait`'s publisher asks again
            pub2, _ = publisher(path, opener)
            pub2.publish(force=True)
            assert opener.methods()[3:] == ["tools/list", "tools/call"]


def test_a_pilot_that_lists_no_tools_gets_the_steps_without_their_whys():
    later = WHY_STEPS + [{"code": "test", "label": "Test phase",
                          "state": "pending"}]
    with tempfile.TemporaryDirectory() as tmp:
        # no answer: logged once, and asked again at the next send
        path = state_file(tmp, WHY_STEPS)
        opener = FakeOpener(urllib.error.URLError("down"), ok_stream(STEPS),
                            listed(), lambda: ok_stream(STEPS))
        pub, lines = publisher(path, opener)
        assert pub.publish(force=True).kind == pp.OK
        state_file(tmp, later)
        assert pub.publish().kind == pp.OK
        assert opener.methods() == ["tools/list", "tools/call",
                                    "tools/list", "tools/call"]
        assert opener.sent() == [pp.sanitize(WHY_STEPS),
                                 pp.sanitize(later, why=True)]
        assert lines == [f"{pp.NOT_LISTED}: no answer from {URL}: "
                         "URLError: down"]
        assert lines[0].startswith("Pilot's tools not listed, so it was sent "
                                   "only what every Pilot takes: ")
        # a refusal is an answer: kept for the publisher, logged once
        path = state_file(tmp, WHY_STEPS)
        refusal = {"jsonrpc": "2.0", "id": 1,
                   "error": {"message": "Method not found"}}
        opener = FakeOpener(FakeResponse(sse([f"data: {json.dumps(refusal)}"])),
                            lambda: ok_stream(STEPS))
        pub, lines = publisher(path, opener)
        pub.publish(force=True)
        pub.publish(force=True)
        assert opener.methods() == ["tools/list", "tools/call", "tools/call"]
        assert opener.sent() == [pp.sanitize(WHY_STEPS)] * 2
        assert lines == [f"{pp.NOT_LISTED}: Pilot refused it: Method not found"]


def test_what_a_pilot_takes_is_asked_once_and_never_without_credentials():
    with tempfile.TemporaryDirectory() as tmp:
        opener = FakeOpener(listed(debrief=False))
        pub, lines = publisher(state_file(tmp), opener)
        assert pub.takes() == pp.Takes(why=True)
        assert pub.takes() == pp.Takes(why=True)
        assert opener.methods() == ["tools/list"] and lines == []
        pub, lines = publisher(state_file(tmp, WHY_STEPS), opener, env={})
        assert pub.takes() == pp.NOTHING
        assert pub.publish(force=True) is None
        assert len(opener.requests) == 1
        assert lines == ["Pilot progress not published: no PILOT_TOKEN/"
                         "PILOT_MCP_URL in this session's environment"]


def test_no_credentials_is_logged_once_and_nothing_is_sent():
    with tempfile.TemporaryDirectory() as tmp:
        path = state_file(tmp)
        opener = FakeOpener(ok_stream(STEPS))
        for env in ({}, {"PILOT_TOKEN": TOKEN}, {"PILOT_MCP_URL": URL},
                    {"PILOT_TOKEN": "", "PILOT_MCP_URL": URL}):
            pub, lines = publisher(path, opener, env)
            pub.publish(force=True)
            pub.publish(force=True)
            assert lines == ["Pilot progress not published: no "
                             "PILOT_TOKEN/PILOT_MCP_URL in this session's "
                             "environment"], env
        assert opener.requests == []


def test_the_environment_is_read_from_the_process_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        saved = pp.os.environ
        pp.os.environ = dict(ENV)
        try:
            pub = pp.Publisher(state_file(tmp), lambda line: None)
        finally:
            pp.os.environ = saved
        assert (pub.token, pub.url) == (TOKEN, URL)
        saved_opener = pp.OPENER
        opener = FakeOpener(ok_stream(STEPS))
        pp.OPENER = opener
        try:
            assert pub.publish(force=True).kind == pp.OK
        finally:
            pp.OPENER = saved_opener
        assert len(opener.requests) == 1


def test_nothing_the_publisher_meets_escapes_it():
    def broken_log(line):
        raise OSError("log gone")

    class Weird(Exception):
        pass

    with tempfile.TemporaryDirectory() as tmp:
        path = state_file(tmp)
        pub = pp.Publisher(path, broken_log, environ=ENV,
                           opener=FakeOpener(Weird("boom")))
        answer = pub.publish(force=True)
        assert answer.kind == pp.NO_ANSWER and "Weird: boom" in answer.reason
        pub = pp.Publisher(path, broken_log, environ={})
        assert pub.publish(force=True) is None

        class Exploding:
            def __enter__(self):
                raise RuntimeError("no body")

            def __exit__(self, *exc):
                return False

        pub, lines = publisher(path, FakeOpener(Exploding))
        assert pub.publish(force=True).kind == pp.NO_ANSWER
        assert lines and "RuntimeError: no body" in lines[0]
        # a reason is one line, whatever the answer held
        pub, lines = publisher(path, FakeOpener(
            urllib.error.URLError("two\nlines")))
        pub.publish(force=True)
        assert "\n" not in lines[0]


# -- a list given, with no state file ----------------------------------------

GROUNDING = [{"code": "ground", "label": "Plan · ground", "state": "active"},
             {"code": "write", "label": "Plan · write", "state": "pending"},
             {"code": "review", "label": "Plan · review", "state": "pending"}]


def test_publish_steps_sends_the_list_given_as_pilot_takes_it():
    lines = []
    opener = FakeOpener(lambda: ok_stream(GROUNDING))
    answer = pp.publish_steps(GROUNDING, lines.append, environ=ENV,
                              opener=opener)
    assert (answer.kind, answer.steps) == (pp.OK, {"steps": GROUNDING})
    assert opener.sent() == [GROUNDING] and lines == []
    [(request, _)] = opener.requests
    assert request.full_url == URL
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    # held to Pilot's limits: a start time and an over-long label are not sent
    given = [dict(GROUNDING[0], started=T0, label="g" * 121), *GROUNDING[1:]]
    pp.publish_steps(given, lines.append, environ=ENV, opener=opener)
    assert opener.sent()[1] == pp.sanitize(given) != given
    assert "started" not in opener.sent()[1][0]
    # the list it was given is left as it was
    assert given[0]["started"] == T0
    # a why, to a Pilot that takes it
    opener = FakeOpener(listed(), lambda: ok_stream(WHY_STEPS))
    pp.publish_steps(WHY_STEPS, lines.append, environ=ENV, opener=opener)
    assert opener.methods() == ["tools/list", "tools/call"]
    assert opener.sent() == [pp.sanitize(WHY_STEPS, why=True)]
    assert opener.sent()[0][2]["why"] == WHY and lines == []


def test_publish_steps_logs_why_it_could_not_publish_and_never_raises():
    refusal = {"jsonrpc": "2.0", "id": 1,
               "error": {"message": f"token {TOKEN}\nexpired"}}
    cases = [
        (ENV, FakeOpener(urllib.error.URLError("refused")), pp.NO_ANSWER,
         f"Pilot progress not published: no answer from {URL}: "
         "URLError: refused"),
        (ENV, FakeOpener(FakeResponse(sse([f"data: {json.dumps(refusal)}"]))),
         pp.REFUSED,
         "Pilot progress not published: Pilot refused it: token <token> "
         "expired"),
        (ENV, FakeOpener(urllib.error.URLError("x" * 400)), pp.NO_ANSWER,
         None),
    ]
    for env, opener, kind, line in cases:
        lines = []
        answer = pp.publish_steps(GROUNDING, lines.append, environ=env,
                                  opener=opener)
        assert answer.kind == kind and len(opener.requests) == 1
        [logged] = lines
        assert TOKEN not in logged and "\n" not in logged
        if line is not None:
            assert logged == line
        else:
            assert len(logged) == len(pp.NOT_PUBLISHED) + 2 + pp.REASON_MAX
    opener = FakeOpener(ok_stream(GROUNDING))
    for env in ({}, {"PILOT_TOKEN": TOKEN}, {"PILOT_MCP_URL": URL}):
        lines = []
        assert pp.publish_steps(GROUNDING, lines.append, environ=env,
                                opener=opener) is None
        assert lines == ["Pilot progress not published: no "
                         "PILOT_TOKEN/PILOT_MCP_URL in this session's "
                         "environment"], env
    assert opener.requests == []

    def broken_log(line):
        raise OSError("log gone")

    class Weird(Exception):
        pass

    answer = pp.publish_steps(GROUNDING, broken_log, environ=ENV,
                              opener=FakeOpener(Weird("boom")))
    assert answer.kind == pp.NO_ANSWER and "Weird: boom" in answer.reason
    assert pp.publish_steps(GROUNDING, broken_log, environ={}) is None
    # even a list that is not one, or an environment that cannot be read
    assert pp.publish_steps(GROUNDING, broken_log, environ=object()) is None
    assert pp.publish_steps(None, broken_log, environ={}) is None


def test_publish_steps_reads_the_process_environment_by_default():
    saved, saved_opener = pp.os.environ, pp.OPENER
    opener = FakeOpener(ok_stream(GROUNDING))
    pp.os.environ, pp.OPENER = dict(ENV), opener
    try:
        answer = pp.publish_steps(GROUNDING, lambda line: None)
    finally:
        pp.os.environ, pp.OPENER = saved, saved_opener
    assert answer.kind == pp.OK and opener.sent() == [GROUNDING]



# -- the debrief's hand-off ---------------------------------------------------

ENTRIES = [{"section": "P1 · First", "round": 1, "role": "Code writer",
            "duration": 540, "words": "It went."},
           {"section": "Completion check", "round": 1, "role": "Gate sweep",
            "duration": 600, "passed": True}]


def stored(n):
    message = {"jsonrpc": "2.0", "id": 1, "result": {
        "content": [{"type": "text", "text": json.dumps({"entries": n})}],
        "structuredContent": {"entries": n}}}
    return FakeResponse(sse(["event: message",
                             f"data: {json.dumps(message)}"]))


def refused(text):
    message = {"jsonrpc": "2.0", "id": 1, "result": {
        "isError": True, "content": [{"type": "text", "text": text}]}}
    return FakeResponse(sse([f"data: {json.dumps(message)}"]))


def hand_off(opener, env=ENV, words="It went well.", **about):
    lines = []
    answer = pp.hand_off_debrief(words, ENTRIES, lines.append, environ=env,
                                 opener=opener, **about)
    return answer, lines


def test_the_debrief_is_one_call_of_register_debrief_to_a_pilot_that_lists_it():
    opener = FakeOpener(listed(), stored(2))
    answer, lines = hand_off(opener)
    assert (answer.kind, answer.entries) == (pp.OK, 2)
    assert opener.methods() == ["tools/list", "tools/call"]
    body = json.loads(opener.requests[1][0].data)
    assert body["params"] == {"name": "register_debrief", "arguments": {
        "debrief": "It went well.", "entries": ENTRIES}}
    assert opener.requests[1][1] == pp.DEBRIEF_TIMEOUT
    assert lines == ["Debrief handed to Pilot: 2 entries stored"]


SUBJECT = "Slice 058 · The search page"


def test_the_subject_and_completes_go_to_a_pilot_that_lists_them():
    for completes in (False, True):
        opener = FakeOpener(listed(), stored(2))
        answer, lines = hand_off(opener, subject=SUBJECT, completes=completes)
        assert (answer.kind, answer.entries) == (pp.OK, 2)
        assert json.loads(opener.requests[1][0].data)["params"] == {
            "name": "register_debrief", "arguments": {
                "debrief": "It went well.", "entries": ENTRIES,
                "subject": SUBJECT, "completes": completes}}
        assert lines == ["Debrief handed to Pilot: 2 entries stored"]


def test_a_pilot_that_does_not_list_them_stores_the_debrief_as_before():
    for opener, about in (
            (FakeOpener(listed(subject=False), stored(2)),
             {"subject": SUBJECT, "completes": False}),
            (FakeOpener(listed(), stored(2)), {"completes": False}),
            (FakeOpener(listed(), stored(2)), {})):
        answer, lines = hand_off(opener, **about)
        assert (answer.kind, answer.entries) == (pp.OK, 2), about
        assert json.loads(opener.requests[1][0].data)["params"] == {
            "name": "register_debrief", "arguments": {
                "debrief": "It went well.", "entries": ENTRIES}}, about
        assert lines == ["Debrief handed to Pilot: 2 entries stored"]
    # no subject, no `completes`: Pilot refuses it false without one
    opener = FakeOpener(stored(2))
    assert pp.send_debrief("w", ENTRIES, URL, TOKEN, opener,
                           completes=False).kind == pp.OK
    assert json.loads(opener.requests[0][0].data)["params"]["arguments"] == {
        "debrief": "w", "entries": ENTRIES}


def test_a_pilot_that_lists_no_register_debrief_is_sent_none():
    opener = FakeOpener(listed(why=False, debrief=False))
    answer, lines = hand_off(opener)
    assert answer.kind == pp.OK and opener.methods() == ["tools/list"]
    assert lines == ["Debrief not handed to Pilot, kept in the slice's folder: "
                     "this Pilot lists no register_debrief"]


def test_the_hand_off_says_in_one_line_why_it_handed_nothing():
    second = ("Cannot register the debrief of work item 7 because it has its "
              "debrief already")
    for opener, env, want in (
            (FakeOpener(listed()), {}, "no PILOT_TOKEN/PILOT_MCP_URL in this "
                                       "session's environment"),
            (FakeOpener(urllib.error.URLError("down")), ENV,
             f"its tools not listed, no answer from {URL}: URLError: down"),
            (FakeOpener(FakeResponse(json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -32600, "message": "no"}}),
                "application/json")), ENV,
             "its tools not listed, Pilot refused it: no"),
            (FakeOpener(listed(), urllib.error.URLError("gone")), ENV,
             f"no answer from {URL}: URLError: gone"),
            (FakeOpener(listed(), refused(second)), ENV,
             f"Pilot refused it: {second}")):
        answer, lines = hand_off(opener, env)
        assert lines == ["Debrief not handed to Pilot, kept in the slice's "
                         f"folder: {want}"], lines
        if not env:
            assert answer is None and opener.requests == []
        else:
            assert answer.kind in (pp.NO_ANSWER, pp.REFUSED)


def test_the_hand_off_never_raises_and_holds_no_token():
    def boom(*a, **k):
        raise RuntimeError("bad")
    answer, lines = hand_off(boom)
    assert answer.kind == pp.NO_ANSWER and len(lines) == 1
    _, lines = hand_off(FakeOpener(listed(), refused(f"bad token {TOKEN}")))
    assert TOKEN not in lines[0] and "<token>" in lines[0]
    assert pp.hand_off_debrief("w", ENTRIES, lambda line: 1 / 0,
                               environ=ENV, opener=FakeOpener(listed(),
                                                              stored(2))) \
        .kind == pp.OK


# -- run on its own -----------------------------------------------------------

def run_publish(argv, opener, env=ENV):
    saved, saved_opener, saved_out = pp.os.environ, pp.OPENER, sys.stdout
    pp.os.environ, pp.OPENER, sys.stdout = dict(env), opener, io.StringIO()
    try:
        code = pp.main(argv)
        return code, sys.stdout.getvalue()
    finally:
        pp.os.environ, pp.OPENER, sys.stdout = saved, saved_opener, saved_out


def test_publish_sends_a_folders_steps_once_with_their_whys_and_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "state.json").write_text(json.dumps(
            {"progress": WHY_STEPS}))
        (Path(tmp) / "plan_state.json").write_text(json.dumps(
            {"progress": STEPS}))
        opener = FakeOpener(listed(), ok_stream(WHY_STEPS))
        assert run_publish(["publish", tmp], opener) == (
            0, "ok: Pilot holds 3 steps\n")
        assert opener.sent() == [WHY_STEPS]
        opener = FakeOpener(ok_stream(STEPS))
        assert run_publish(["publish", tmp, "--plan"], opener) == (
            0, "ok: Pilot holds 2 steps\n")
        assert opener.sent() == [STEPS]
        # a miss is printed and goes to the folder's log as `wait`'s does
        assert run_publish(["publish", tmp, "--plan"], FakeOpener(
            urllib.error.URLError("down"))) == (
            0, "no_answer: URLError: down\n")
        log = (Path(tmp) / "plan_log.txt").read_text()
        assert "] [publish] Pilot progress not published: no answer" in log
        assert run_publish(["publish", tmp], FakeOpener(listed()), env={}) \
            == (0, "not sent: no PILOT_TOKEN/PILOT_MCP_URL in this "
                   "environment\n")
        (Path(tmp) / "state.json").write_text("{}")
        assert run_publish(["publish", tmp], FakeOpener(listed())) == (
            0, "not sent: state.json holds no steps\n")
    with tempfile.TemporaryDirectory() as tmp:
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            assert run_publish(["publish", tmp], FakeOpener(listed()))[0] == 2
        finally:
            sys.stderr = saved

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
