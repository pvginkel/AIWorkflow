"""Tests for pilot_progress — a loop's steps, the helpers that edit the list,
the one `set_progress` call that sends it, and the publisher `wait` uses.

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
        """The step lists the calls carried."""
        return [json.loads(r.data)["params"]["arguments"]["steps"]
                for r, _ in self.requests]


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


# -- the list -----------------------------------------------------------------

def test_a_code_names_its_phase_kind_and_round():
    code = pp.step_code
    assert [code("code", 1, "3"), code("code", 2, "3"), code("review", 1, "3a"),
            code("review", 2, "3a"), code("sweep"), code("sweep", 2),
            code("consult"), code("test"), code("test", 2), code("docs"),
            code("wrap-up"), code("write"), code("write", 2),
            code("review")] == [
        "P3.code", "P3.code-2", "P3a.review", "P3a.review-2", "sweep",
        "sweep-2", "consult", "test", "test-2", "docs", "wrap-up", "write",
        "write-2", "review"]
    try:
        code("merge")
    except ValueError:
        pass
    else:
        raise AssertionError("a kind outside the set was given a code")
    assert pp.phase_of("P3a.review-2") == "3a"
    assert pp.phase_of("review-2") is None
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
