#!/usr/bin/env python3
"""A loop's steps, as Pilot shows them — the list and its two publishers.

Both loops keep a list of the steps their run takes, `progress` in their
state file (plan_state.json, state.json): `{"code", "label", "state"}` per
step, the state `pending`, `active` or `done` and nothing else, in the order
the steps were taken, the ones not reached yet after them. A step the driver
started also carries `started`, the time it went active, which `wait`'s
`running` line counts from (`active_summary`) and Pilot never sees
(`sanitize` sends the three fields alone). The drivers edit it through
the pure helpers here and never send it anywhere: they hold no Pilot
credential, and a driver that outlives the session that started it
would hold a stale one. The loops' `wait` (run_loop.wait_on_driver) is what
publishes it — that process is the Pilot session's own, so the token in its
environment is the live one — through `Publisher`. The other publisher is
plan_loop.py `progress`, the plan-slice session's publish of its grounding
steps before the plan loop exists: a process of the Pilot session too, so
its token is live as well, sending a list it is given, with no state file,
through `publish_steps`.

A step's code is `[P<phase>.]<kind>[-<round>]`: round 1 has no suffix, the
phase id is the plan's (`P3.code`, `P3a.review-2`, `sweep`, `write-2`). The
kinds are a fixed set, because a later estimate keys on them: the run loop's
`code`, `review`, `sweep`, `consult`, `test`, `docs` and `wrap-up`, the plan
loop's `ground` (the grounding ahead of its passes), `write` and `review`.

A publisher sends the whole list with one JSON-RPC `tools/call` of Pilot's
MCP tool `set_progress`, with no `initialize` first (the server keeps no
session) and no MCP client: `urllib.request`, bounded at about TIMEOUT
seconds, so a slow Pilot never pushes `wait` past its budget. It is
best-effort and silent — what it could not do goes to the slice's log once
per kind per `wait` or `publish_steps` call, nothing is printed, and nothing
it raises reaches the caller. Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

PENDING = "pending"
ACTIVE = "active"
DONE = "done"
STATES = (PENDING, ACTIVE, DONE)

RUN_KINDS = ("code", "review", "sweep", "consult", "test", "docs", "wrap-up")
PLAN_KINDS = ("ground", "write", "review")
KINDS = frozenset(RUN_KINDS + PLAN_KINDS)

# Pilot refuses the whole call over any one of these, so they are kept on
# this side (`sanitize`).
CODE_MAX = 64
LABEL_MAX = 120
STEPS_MAX = 100

TIMEOUT = 3          # seconds, the whole call: connect, send, answer
TOOL = "set_progress"
# The HTTP seam: `send` takes an opener of its own, and falls back to this
# one, looked up at the call so a suite can put a fake here.
OPENER = urllib.request.urlopen

_PHASE_RE = re.compile(r"^P([A-Za-z0-9]+)\.")
_CODE_RE = re.compile(r"^(?:P([A-Za-z0-9]+)\.)?(.+?)(?:-(\d+))?$")


# -- the list ------------------------------------------------------------------

def step_code(kind: str, round_: int = 1, phase: str | None = None) -> str:
    """The code of a step of `kind` — of phase `phase` (as the plan writes
    its id) when it has one, in round `round_`."""
    if kind not in KINDS:
        raise ValueError(f"unknown step kind {kind!r}")
    code = f"{kind}-{round_}" if round_ >= 2 else kind
    return f"P{phase}.{code}" if phase is not None else code


def phase_of(code: str) -> str | None:
    """The phase id a step's code names, or None for a step of no phase."""
    match = _PHASE_RE.match(code or "")
    return match.group(1) if match else None


def clip_label(label: str) -> str:
    return label if len(label) <= LABEL_MAX else label[:LABEL_MAX - 1] + "…"


def make_step(code: str, label: str, state: str = PENDING) -> dict:
    return {"code": code, "label": clip_label(label), "state": state}


def phase_steps(phase_id: str, title: str, done: bool = False) -> list[dict]:
    """A phase's two steps before any round of it ran: its code step,
    labelled with its title, and its review."""
    state = DONE if done else PENDING
    return [make_step(step_code("code", 1, phase_id), f"P{phase_id} · {title}",
                      state),
            make_step(step_code("review", 1, phase_id), f"P{phase_id} · review",
                      state)]


def _first_pending(steps: list[dict]) -> int:
    return next((i for i, s in enumerate(steps) if s.get("state") == PENDING),
                len(steps))


def start(steps: list[dict], code: str, label: str,
          started: str | None = None) -> list[dict]:
    """The list with step `code` active and every other active step done —
    both loops run one step at a time. A step not on the list goes in right
    before the first pending one, so the steps taken stay in the order they
    were taken, ahead of those not reached yet. With `started`, an ISO time,
    the step carries it as the time it went active."""
    out = [dict(s) for s in steps]
    for s in out:
        if s.get("state") == ACTIVE and s.get("code") != code:
            s["state"] = DONE
    stamp = {"started": started} if started is not None else {}
    for s in out:
        if s.get("code") == code:
            s.update(label=clip_label(label), state=ACTIVE, **stamp)
            return out
    out.insert(_first_pending(out), {**make_step(code, label, ACTIVE), **stamp})
    return out


def restart_clock(steps: list[dict], started: str) -> list[dict]:
    """The list with its active step started at `started` — a resumed run's:
    the time the run stood stopped is no time spent in the step."""
    return [dict(s, started=started) if s.get("state") == ACTIVE else dict(s)
            for s in steps]


def finish_active(steps: list[dict]) -> list[dict]:
    """The list with every active step done."""
    return [dict(s, state=DONE) if s.get("state") == ACTIVE else dict(s)
            for s in steps]


def finish_step(steps: list[dict], code: str) -> list[dict]:
    """The list with step `code` done — a step the run reached and that had
    nothing to do."""
    return [dict(s, state=DONE) if s.get("code") == code else dict(s)
            for s in steps]


def finish_phase(steps: list[dict], phase_id: str) -> list[dict]:
    """The list with every step of phase `phase_id` done — the phase merged,
    whatever of it was still pending or active."""
    return [dict(s, state=DONE) if phase_of(s.get("code", "")) == phase_id
            else dict(s) for s in steps]


def has_phase(steps: list[dict], phase_id: str) -> bool:
    return any(phase_of(s.get("code", "")) == phase_id for s in steps)


def insert_phase(steps: list[dict], phase_id: str, title: str,
                 order: list[str], done: bool = False) -> list[dict]:
    """The list with a phase's two steps added — a phase the plan gained
    after the list was made. They go before the first pending step that
    closes the run (a step of no phase) or belongs to a phase later in the
    plan's document order `order`, so an appended phase sits where the run
    will take it; with none, at the end."""
    rank = {pid: i for i, pid in enumerate(order)}
    mine = rank.get(phase_id, len(order))

    def ahead(s: dict) -> bool:
        if s.get("state") != PENDING:
            return False
        other = phase_of(s.get("code", ""))
        return other is None or rank.get(other, -1) > mine

    at = next((i for i, s in enumerate(steps) if ahead(s)), len(steps))
    out = [dict(s) for s in steps]
    out[at:at] = phase_steps(phase_id, title, done)
    return out


def active_summary(steps, now: datetime | None = None) -> str | None:
    """Where a loop stands, for `wait`'s `running` line: its active step's
    phase, kind and round as its code names them — `P4 code`, `P4 review
    r2`, `sweep r2`, `wrap-up`, `write r2` — and the whole minutes since it
    started, `, 12m` (`, <1m`, `, 1h05m`). None with no active step; no time
    for a step that carries none, as one an older loop started, or one that
    does not read as an ISO time with its offset. Never raises."""
    try:
        step = next((s for s in steps if isinstance(s, dict)
                     and s.get("state") == ACTIVE), None) \
            if isinstance(steps, list) else None
        code = step.get("code") if step else None
        if not isinstance(code, str) or not code:
            return None
        match = _CODE_RE.match(code)
        if match:
            phase, kind, round_ = match.groups()
            code = ((f"P{phase} " if phase else "") + kind
                    + (f" r{round_}" if round_ else ""))
        elapsed = _elapsed(step.get("started"), now)
        return f"{code}, {elapsed}" if elapsed else code
    except Exception:
        return None


def _elapsed(started, now: datetime | None) -> str | None:
    try:
        then = datetime.fromisoformat(started)
        seconds = ((now or datetime.now().astimezone()) - then).total_seconds()
    except (TypeError, ValueError):
        return None
    minutes = int(seconds // 60)
    if minutes < 1:
        return "<1m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def sanitize(steps) -> list[dict]:
    """The list as Pilot takes it: a step whose code is empty or longer
    than CODE_MAX dropped, a repeated code kept at its first, an empty label
    replaced by the code, a label cut at LABEL_MAX, a state outside STATES
    left out, and of more than STEPS_MAX steps the last ones — the list is
    in the order the steps were taken, so the oldest done steps go first."""
    out: list[dict] = []
    seen: set[str] = set()
    for s in steps if isinstance(steps, list) else []:
        if not isinstance(s, dict):
            continue
        code = s.get("code")
        if not isinstance(code, str) or not code or len(code) > CODE_MAX \
                or code in seen:
            continue
        seen.add(code)
        label = s.get("label")
        if not isinstance(label, str) or not label.strip():
            label = code
        step = {"code": code, "label": clip_label(label)}
        if s.get("state") in STATES:
            step["state"] = s["state"]
        out.append(step)
    return out[-STEPS_MAX:]


# -- the client ----------------------------------------------------------------

OK = "ok"
REFUSED = "refused"
NO_ANSWER = "no_answer"


class Answer(NamedTuple):
    """What a `set_progress` call came to: `ok` with the list as Pilot now
    holds it, `refused` with Pilot's reason, or `no_answer` with why none
    came."""
    kind: str
    steps: list | None = None
    reason: str = ""


def send(steps: list[dict], url: str, token: str,
         opener: Callable | None = None, timeout: float = TIMEOUT) -> Answer:
    """One `tools/call` of `set_progress` with the whole list, held to
    Pilot's limits (`sanitize`) and answered within about `timeout`
    seconds. Never raises; no reason holds the token."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": TOOL, "arguments": {"steps": sanitize(steps)}},
    }).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    })
    deadline = time.monotonic() + timeout
    try:
        with (opener or OPENER)(request, timeout=timeout) as response:
            kind = (response.headers.get("Content-Type") or "").split(";")[0]
            if kind.strip().lower() == "application/json":
                message = _json(response.read())
            else:
                message = _event_stream_response(response, deadline)
    except urllib.error.HTTPError as e:
        return Answer(NO_ANSWER, reason=_scrub(f"HTTP {e.code} {e.reason}",
                                               token))
    except Exception as e:
        reason = getattr(e, "reason", None) or e
        return Answer(NO_ANSWER, reason=_scrub(
            f"{type(e).__name__}: {reason}", token))
    return _answer(message, token)


def _json(raw: bytes | str):
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _event_stream_response(response, deadline: float) -> dict | None:
    """The JSON-RPC response to id 1 out of a `text/event-stream` body, read
    line by line until it is parsed, the stream ends or `deadline` passes.
    An event is its `data:` lines joined with newlines, up to a blank line;
    any other field (`event:`, `id:`) and a comment are skipped, and a CRLF
    is a line end as a LF is."""
    data: list[str] = []
    while time.monotonic() < deadline:
        raw = response.readline()
        if not raw:
            break
        line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes)
                else raw).rstrip("\r\n")
        if line:
            name, _, value = line.partition(":")
            if name == "data":
                data.append(value[1:] if value.startswith(" ") else value)
            continue
        message = _response_to_1(data)
        if message is not None:
            return message
        data = []
    return _response_to_1(data)


def _response_to_1(data: list[str]) -> dict | None:
    if not data:
        return None
    message = _json("\n".join(data))
    if isinstance(message, dict) and message.get("id") == 1 \
            and ("result" in message or "error" in message):
        return message
    return None


def _answer(message, token: str) -> Answer:
    if not isinstance(message, dict):
        return Answer(NO_ANSWER, reason="the answer held no JSON-RPC response")
    error = message.get("error")
    if error is not None:
        reason = error.get("message") if isinstance(error, dict) else None
        return Answer(REFUSED, reason=_scrub(str(reason or error), token))
    result = message.get("result")
    if not isinstance(result, dict):
        return Answer(NO_ANSWER, reason="the answer held no JSON-RPC response")
    if result.get("isError"):
        content = result.get("content")
        texts = [str(c.get("text")) for c in content
                 if isinstance(c, dict) and c.get("type") == "text"
                 and c.get("text")] if isinstance(content, list) else []
        return Answer(REFUSED, reason=_scrub(" ".join(texts) or "no reason given",
                                             token))
    return Answer(OK, steps=result.get("structuredContent"))


def _scrub(reason: str, token: str) -> str:
    return reason.replace(token, "<token>") if token else reason


# -- the publishers ------------------------------------------------------------

UNCONFIGURED = "unconfigured"
NOT_PUBLISHED = "Pilot progress not published"
REASON_MAX = 300


class _Sender:
    """A send of a list with its logging: the credentials from the
    sending process's own environment (`PILOT_TOKEN`, `PILOT_MCP_URL`), and
    each kind of failure — no credentials, no answer, a refusal — put in the
    slice's log through `log_line` once per sender."""

    def __init__(self, log_line: Callable[[str], None], environ=None,
                 opener: Callable | None = None):
        env = os.environ if environ is None else environ
        self.log_line = log_line
        self.token = env.get("PILOT_TOKEN") or ""
        self.url = env.get("PILOT_MCP_URL") or ""
        self.opener = opener
        self._logged: set[str] = set()

    def _send(self, steps: list[dict]) -> Answer | None:
        """The answer to the send, or None with no credentials to send it."""
        if not self.token or not self.url:
            self._note(UNCONFIGURED, "no PILOT_TOKEN/PILOT_MCP_URL in this "
                                     "session's environment")
            return None
        answer = send(steps, self.url, self.token, self.opener)
        if answer.kind == NO_ANSWER:
            self._note(NO_ANSWER, f"no answer from {self.url}: {answer.reason}")
        elif answer.kind == REFUSED:
            self._note(REFUSED, f"Pilot refused it: {answer.reason}")
        return answer

    def _note(self, kind: str, why: str) -> None:
        if kind in self._logged:
            return
        self._logged.add(kind)
        why = " ".join(_scrub(why, self.token).split())
        if len(why) > REASON_MAX:
            why = why[:REASON_MAX - 1] + "…"
        try:
            self.log_line(f"{NOT_PUBLISHED}: {why}")
        except Exception:
            pass


class Publisher(_Sender):
    """One `wait`'s publishing of the state file's list: built from the
    waiting process's own environment (`PILOT_TOKEN`, `PILOT_MCP_URL`) and
    told where the state file is and how to put a line in the slice's log.

    `publish` sends the list when it differs from the last one it tried to
    send, or always when forced — a failed send is not retried on an
    unchanged list; the next change, or `wait`'s forced last publish, tries
    again. A state file with no list (a driver started on an older plugin)
    sends and logs nothing. Each kind of failure — no credentials, no
    answer, a refusal — is logged once per publisher, so once per `wait`."""

    def __init__(self, state_path: Path, log_line: Callable[[str], None],
                 environ=None, opener: Callable | None = None):
        super().__init__(log_line, environ, opener)
        self.state_path = Path(state_path)
        self._last: list[dict] | None = None

    def publish(self, force: bool = False) -> Answer | None:
        """The answer to the send this made, or None when it sent nothing."""
        try:
            return self._publish(force)
        except Exception:
            return None

    def _publish(self, force: bool) -> Answer | None:
        steps = self._read()
        if steps is None:
            return None
        if not force and steps == self._last:
            return None
        self._last = steps
        return self._send(steps)

    def _read(self) -> list[dict] | None:
        """The state file's list as Pilot takes it, or None with no list."""
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return None
        progress = state.get("progress") if isinstance(state, dict) else None
        if not isinstance(progress, list):
            return None
        return sanitize(progress)


def publish_steps(steps: list[dict], log_line: Callable[[str], None],
                  environ=None, opener: Callable | None = None) -> Answer | None:
    """One send of `steps`, a list given rather than a state file's — the
    plan-slice session's grounding steps, before the plan loop exists
    (plan_loop.py `progress`) — with the publisher's ways: the credentials
    from this process's environment, the list held to Pilot's limits, each
    kind of failure logged once through `log_line`. The answer, or None when
    nothing was sent; never raises."""
    try:
        return _Sender(log_line, environ, opener)._send(sanitize(steps))
    except Exception:
        return None
