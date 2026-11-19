#!/usr/bin/env python3
"""A loop's steps, as Pilot shows them — the list and its two publishers.

Both loops keep a list of the steps their run takes, `progress` in their
state file (plan_state.json, state.json): `{"code", "label", "state"}` per
step, the state `pending`, `active` or `done` and nothing else, in the order
the steps were taken, the ones not reached yet after them. A step that opens
a round past the first also carries `why`, one short line saying what the
round before left unsettled. A step the driver started also carries
`started`, the time it went active, which `wait`'s `running` line counts
from (`active_summary`) and Pilot never sees (`sanitize` leaves it out). The
drivers edit it through
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
`code`, `review`, `sweep`, `consult`, `test`, `docs`, `wrap-up` and
`fixes` (the fixes pass, after the close-out is answered), the plan
loop's `ground` (the grounding ahead of its passes), `write` and `review`.

A publisher sends the whole list with one JSON-RPC `tools/call` of Pilot's
MCP tool `set_progress`, with no `initialize` first (the server keeps no
session) and no MCP client: `urllib.request`, bounded at about TIMEOUT
seconds, so a slow Pilot never pushes `wait` past its budget. A step's `why`
goes only to a Pilot that takes it: one that refuses a step's unknown field
refuses the whole list over it. What the Pilot takes is read from the Pilot
itself, its own `tools/list` (`discover`), never from a version or a
setting, and asked only where a step has a why to send. It is best-effort
and silent — what it could not do goes to the slice's log once per kind per
`wait` or `publish_steps` call, nothing is printed, and nothing it raises
reaches the caller.

The same client hands a work item's debrief to Pilot, once, at its stage's
end: one `tools/call` of DEBRIEF_TOOL, made only where that Pilot's own
`tools/list` names it (`hand_off_debrief`), and what came of it goes to the
slice's log in one line. The debrief's `subject` and `completes` go with it
only where that same list gives DEBRIEF_TOOL both fields, as a step's why
goes only where `set_progress` gives a step one; the loop's figures go
likewise only where it gives DEBRIEF_TOOL a `figures` field.

Run on its own, over a slice folder's state file, with the session's
`PILOT_TOKEN` and `PILOT_MCP_URL`:

    pilot_progress.py publish <slice-dir> [--plan]

sends the list once as `wait` sends it, and prints what came of it in one
line. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
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

RUN_KINDS = ("code", "review", "sweep", "consult", "test", "docs", "wrap-up",
             "fixes")
PLAN_KINDS = ("ground", "write", "review")
KINDS = frozenset(RUN_KINDS + PLAN_KINDS)

# Pilot refuses the whole call over any one of these, so they are kept on
# this side (`sanitize`).
CODE_MAX = 64
LABEL_MAX = 120
WHY_MAX = 120
STEPS_MAX = 100

TIMEOUT = 3          # seconds, the whole call: connect, send, answer
DEBRIEF_TIMEOUT = 15  # the debrief's one call, which no `wait` budget bounds
TOOL = "set_progress"
DEBRIEF_TOOL = "register_debrief"
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


def split_code(code: str) -> tuple[str | None, str, int]:
    """A step's code, not empty, as its phase id (None for a step of no
    phase), its kind and its round: `P3a.review-2` → ("3a", "review", 2),
    `sweep` → (None, "sweep", 1)."""
    phase, kind, round_ = _CODE_RE.match(code).groups()
    return phase, kind, int(round_) if round_ else 1


def active_step(steps) -> dict | None:
    """The list's active step, or None where none is."""
    return next((s for s in steps if isinstance(s, dict)
                 and s.get("state") == ACTIVE), None) \
        if isinstance(steps, list) else None


def clip_label(label: str) -> str:
    return label if len(label) <= LABEL_MAX else label[:LABEL_MAX - 1] + "…"


def clip_why(why) -> str | None:
    """A step's why as Pilot takes it: one line, each run of whitespace one
    space, cut at WHY_MAX with an ellipsis; None for a why that is no text
    or leaves nothing."""
    if not isinstance(why, str):
        return None
    line = " ".join(why.split())
    if not line:
        return None
    return line if len(line) <= WHY_MAX else line[:WHY_MAX - 1] + "…"


def make_step(code: str, label: str, state: str = PENDING,
              why: str | None = None) -> dict:
    step = {"code": code, "label": clip_label(label), "state": state}
    line = clip_why(why)
    if line is not None:
        step["why"] = line
    return step


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


def taken(steps: list[dict], code: str) -> bool:
    """Whether step `code` was started already: on the list and no longer
    pending — a round dispatched again under its number, not a new one."""
    return any(s.get("code") == code and s.get("state") != PENDING
               for s in steps)


def follows(steps: list[dict], kind: str, phase: str | None = None) -> bool:
    """Whether the step started last — the last on the list not pending,
    as `start` keeps it — is one of `kind` (of phase `phase`)."""
    last = next((s for s in reversed(steps) if s.get("state") != PENDING),
                None)
    match = _CODE_RE.match((last or {}).get("code") or "")
    return bool(match) and match.group(1) == phase and match.group(2) == kind


def start(steps: list[dict], code: str, label: str,
          started: str | None = None, why: str | None = None) -> list[dict]:
    """The list with step `code` active and every other active step done —
    both loops run one step at a time. A step not on the list goes in right
    before the first pending one, so the steps taken stay in the order they
    were taken, ahead of those not reached yet. With `started`, an ISO time,
    the step carries it as the time it went active; with `why`, that line,
    and without one it keeps the why it has."""
    out = [dict(s) for s in steps]
    for s in out:
        if s.get("state") == ACTIVE and s.get("code") != code:
            s["state"] = DONE
    stamp = {"started": started} if started is not None else {}
    line = clip_why(why)
    if line is not None:
        stamp["why"] = line
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


def sanitize(steps, why: bool = False) -> list[dict]:
    """The list as Pilot takes it: a step whose code is empty or longer
    than CODE_MAX dropped, a repeated code kept at its first, an empty label
    replaced by the code, a label cut at LABEL_MAX, a state outside STATES
    left out, and of more than STEPS_MAX steps the last ones — the list is
    in the order the steps were taken, so the oldest done steps go first.
    With `why`, a step keeps its why as `clip_why` leaves it; without, no
    step carries one."""
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
        line = clip_why(s.get("why")) if why else None
        if line is not None:
            step["why"] = line
        out.append(step)
    return out[-STEPS_MAX:]


def has_why(steps: list[dict]) -> bool:
    return any(isinstance(s, dict) and clip_why(s.get("why")) is not None
               for s in steps)


# -- the client ----------------------------------------------------------------

OK = "ok"
REFUSED = "refused"
NO_ANSWER = "no_answer"


class Takes(NamedTuple):
    """What a Pilot takes beyond a step's code, label and state, as its own
    `tools/list` shows it: a step's `why` where `set_progress`'s steps have
    that field, the debrief where it lists DEBRIEF_TOOL, the debrief's
    `subject` and `completes` where DEBRIEF_TOOL has both fields, and its
    `figures` where DEBRIEF_TOOL has that field."""
    why: bool = False
    debrief: bool = False
    subject: bool = False
    figures: bool = False


NOTHING = Takes()


class Answer(NamedTuple):
    """What a call came to: `ok` — with, of a `set_progress`, the list as
    Pilot now holds it, of a `tools/list` (`discover`), what it takes, of a
    DEBRIEF_TOOL, the number of entries it stored — `refused` with Pilot's
    reason, or `no_answer` with why none came."""
    kind: str
    steps: list | None = None
    reason: str = ""
    takes: Takes | None = None
    entries: int | None = None


class _NoAnswer(Exception):
    pass


def _post(method: str, params: dict, url: str, token: str,
          opener: Callable | None, timeout: float):
    """The JSON-RPC message answering one `method` call, None where the
    answer held none, read within about `timeout` seconds; `_NoAnswer` with
    the reason where no answer came."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
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
                return _json(response.read())
            return _event_stream_response(response, deadline)
    except urllib.error.HTTPError as e:
        raise _NoAnswer(_scrub(f"HTTP {e.code} {e.reason}", token)) from None
    except Exception as e:
        reason = getattr(e, "reason", None) or e
        raise _NoAnswer(_scrub(f"{type(e).__name__}: {reason}",
                               token)) from None


def send(steps: list[dict], url: str, token: str,
         opener: Callable | None = None, timeout: float = TIMEOUT,
         why: bool = False) -> Answer:
    """One `tools/call` of `set_progress` with the whole list, held to
    Pilot's limits (`sanitize`), each step's why with it only with `why`,
    and answered within about `timeout` seconds. Never raises; no reason
    holds the token."""
    try:
        message = _post("tools/call", {
            "name": TOOL, "arguments": {"steps": sanitize(steps, why)}},
            url, token, opener, timeout)
    except _NoAnswer as e:
        return Answer(NO_ANSWER, reason=str(e))
    return _answer(message, token)


def send_debrief(words: str, entries: list[dict], url: str, token: str,
                 opener: Callable | None = None,
                 timeout: float = DEBRIEF_TIMEOUT,
                 subject: str | None = None, completes: bool = True,
                 figures: str | None = None) -> Answer:
    """One `tools/call` of DEBRIEF_TOOL with the stage session's `words` and
    the run's `entries`, as given, with a `subject`, it and `completes`, and
    with `figures`, them: `ok` with the number Pilot stored, else `refused`
    or `no_answer` with the reason. Never raises; no reason holds the
    token."""
    arguments = {"debrief": words, "entries": entries}
    if subject is not None:
        arguments.update(subject=subject, completes=completes)
    if figures is not None:
        arguments["figures"] = figures
    try:
        message = _post("tools/call", {
            "name": DEBRIEF_TOOL, "arguments": arguments},
            url, token, opener, timeout)
    except _NoAnswer as e:
        return Answer(NO_ANSWER, reason=str(e))
    answer = _answer(message, token)
    if answer.kind != OK:
        return answer
    stored = answer.steps.get("entries") if isinstance(answer.steps, dict) \
        else None
    return Answer(OK, entries=stored if isinstance(stored, int) else None)


def discover(url: str, token: str, opener: Callable | None = None,
             timeout: float = TIMEOUT) -> Answer:
    """One `tools/list` of the Pilot at `url`, answered within about
    `timeout` seconds: `ok` with what it takes (`Takes`), else `refused` or
    `no_answer` with the reason. Never raises; no reason holds the token."""
    try:
        message = _post("tools/list", {}, url, token, opener, timeout)
    except _NoAnswer as e:
        return Answer(NO_ANSWER, reason=str(e))
    if not isinstance(message, dict):
        return Answer(NO_ANSWER, reason="the answer held no JSON-RPC response")
    error = message.get("error")
    if error is not None:
        reason = error.get("message") if isinstance(error, dict) else None
        return Answer(REFUSED, reason=_scrub(str(reason or error), token))
    result = message.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return Answer(NO_ANSWER, reason="the answer listed no tools")
    named = {t.get("name"): t for t in tools if isinstance(t, dict)}
    return Answer(OK, takes=Takes(
        why=_steps_take_why(named.get(TOOL)), debrief=DEBRIEF_TOOL in named,
        subject=_debrief_takes_subject(named.get(DEBRIEF_TOOL)),
        figures=_debrief_takes_figures(named.get(DEBRIEF_TOOL))))


def _steps_take_why(tool) -> bool:
    """Whether `set_progress`'s input schema gives a step a `why`: a field
    of its `steps`' items, inline or through a `$ref` into its `$defs`."""
    try:
        schema = tool["inputSchema"]
        items = schema["properties"]["steps"]["items"]
        ref = items.get("$ref")
        if isinstance(ref, str):
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                return False
            items = schema["$defs"][ref[len(prefix):]]
        return "why" in items["properties"]
    except (KeyError, TypeError, AttributeError):
        return False


def _debrief_takes_subject(tool) -> bool:
    """Whether DEBRIEF_TOOL's input schema has both `subject` and
    `completes` among its fields."""
    try:
        fields = tool["inputSchema"]["properties"]
        return "subject" in fields and "completes" in fields
    except (KeyError, TypeError):
        return False


def _debrief_takes_figures(tool) -> bool:
    """Whether DEBRIEF_TOOL's input schema has `figures` among its
    fields."""
    try:
        fields = tool["inputSchema"]["properties"]
        return isinstance(fields, dict) and "figures" in fields
    except (KeyError, TypeError):
        return False


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
UNLISTED = "unlisted"
NOT_PUBLISHED = "Pilot progress not published"
NOT_LISTED = ("Pilot's tools not listed, so it was sent only what every Pilot "
              "takes")
NOT_TAKEN = "not_taken"
NOT_HANDED = "Debrief not handed to Pilot, kept in the slice's folder"
HANDED = "Debrief handed to Pilot"
REASON_MAX = 300


class _Sender:
    """A send of a list with its logging: the credentials from the
    sending process's own environment (`PILOT_TOKEN`, `PILOT_MCP_URL`), and
    each kind of failure — no credentials, no answer, a refusal, a
    `tools/list` that did not answer — put in the slice's log through
    `log_line` once per sender."""

    def __init__(self, log_line: Callable[[str], None], environ=None,
                 opener: Callable | None = None):
        env = os.environ if environ is None else environ
        self.log_line = log_line
        self.token = env.get("PILOT_TOKEN") or ""
        self.url = env.get("PILOT_MCP_URL") or ""
        self.opener = opener
        self._logged: set[str] = set()
        self._takes: Takes | None = None

    def takes(self) -> Takes:
        """What this sender's Pilot takes (`discover`), asked once per
        sender once it answered, a refusal included; NOTHING with no
        credentials, and NOTHING where it gave no answer, asked again at the
        next call."""
        if self._takes is not None:
            return self._takes
        if not self.token or not self.url:
            return NOTHING
        answer = discover(self.url, self.token, self.opener)
        if answer.kind == OK:
            self._takes = answer.takes
            return self._takes
        self._note(UNLISTED, f"no answer from {self.url}: {answer.reason}"
                   if answer.kind == NO_ANSWER
                   else f"Pilot refused it: {answer.reason}", NOT_LISTED)
        if answer.kind == REFUSED:
            self._takes = NOTHING
        return NOTHING

    def _send(self, steps: list[dict]) -> Answer | None:
        """The answer to the send, or None with no credentials to send it.
        The steps' whys go with them where this Pilot takes them, which is
        asked only where a step has one."""
        if not self.token or not self.url:
            self._note(UNCONFIGURED, "no PILOT_TOKEN/PILOT_MCP_URL in this "
                                     "session's environment")
            return None
        why = has_why(steps) and self.takes().why
        answer = send(steps, self.url, self.token, self.opener, why=why)
        if answer.kind == NO_ANSWER:
            self._note(NO_ANSWER, f"no answer from {self.url}: {answer.reason}")
        elif answer.kind == REFUSED:
            self._note(REFUSED, f"Pilot refused it: {answer.reason}")
        return answer

    def _note(self, kind: str, why: str, lead: str = NOT_PUBLISHED) -> None:
        if kind in self._logged:
            return
        self._logged.add(kind)
        why = " ".join(_scrub(why, self.token).split())
        if len(why) > REASON_MAX:
            why = why[:REASON_MAX - 1] + "…"
        try:
            self.log_line(f"{lead}: {why}")
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
    answer, a refusal — is logged once per publisher, so once per `wait`,
    and so is the miss of what the Pilot takes, asked once per publisher."""

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
        """The state file's list as a Pilot that takes the whys takes it, or
        None with no list."""
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return None
        progress = state.get("progress") if isinstance(state, dict) else None
        if not isinstance(progress, list):
            return None
        return sanitize(progress, why=True)


def hand_off_debrief(words: str, entries: list[dict],
                     log_line: Callable[[str], None], environ=None,
                     opener: Callable | None = None,
                     subject: str | None = None,
                     completes: bool = True,
                     figures: str | None = None) -> Answer | None:
    """The work item's debrief handed to Pilot, once: `words`, the stage
    session's own, and `entries`, held to Pilot's limits by the caller
    (debrief.for_pilot), sent with the credentials from this process's
    environment, and only where that Pilot's own `tools/list` names
    DEBRIEF_TOOL — one that does not would refuse the call as a tool it does
    not know. A `subject`, what the debrief is an account of, goes with
    `completes` only where that list gives DEBRIEF_TOOL both fields; to any
    other Pilot the debrief goes without them. The loop's `figures`, held to
    Pilot's limit by the caller, go likewise only where that list gives
    DEBRIEF_TOOL a `figures` field. What came of it, stored or
    why not, is one line through `log_line`. The answer of the last call
    made, or None with no credentials; never raises."""
    sender = _Sender(log_line, environ, opener)
    try:
        if not sender.token or not sender.url:
            sender._note(UNCONFIGURED, "no PILOT_TOKEN/PILOT_MCP_URL in this "
                                       "session's environment", NOT_HANDED)
            return None
        listed = discover(sender.url, sender.token, sender.opener)
        if listed.kind == NO_ANSWER:
            sender._note(UNLISTED, f"its tools not listed, no answer from "
                                   f"{sender.url}: {listed.reason}", NOT_HANDED)
            return listed
        if listed.kind == REFUSED:
            sender._note(UNLISTED, "its tools not listed, Pilot refused it: "
                                   f"{listed.reason}", NOT_HANDED)
            return listed
        if not listed.takes.debrief:
            sender._note(NOT_TAKEN, f"this Pilot lists no {DEBRIEF_TOOL}",
                         NOT_HANDED)
            return listed
        answer = send_debrief(
            words, entries, sender.url, sender.token, sender.opener,
            subject=subject if listed.takes.subject else None,
            completes=completes,
            figures=figures if listed.takes.figures else None)
        if answer.kind == NO_ANSWER:
            sender._note(NO_ANSWER, f"no answer from {sender.url}: "
                                    f"{answer.reason}", NOT_HANDED)
        elif answer.kind == REFUSED:
            sender._note(REFUSED, f"Pilot refused it: {answer.reason}",
                         NOT_HANDED)
        else:
            sender._note(OK, f"{answer.entries} entries stored"
                         if answer.entries is not None else "stored", HANDED)
        return answer
    except Exception:
        return None


def publish_steps(steps: list[dict], log_line: Callable[[str], None],
                  environ=None, opener: Callable | None = None) -> Answer | None:
    """One send of `steps`, a list given rather than a state file's — the
    plan-slice session's grounding steps, before the plan loop exists
    (plan_loop.py `progress`) — with the publisher's ways: the credentials
    from this process's environment, the list held to Pilot's limits, the
    whys where Pilot takes them, each kind of failure logged once through
    `log_line`. The answer, or None when nothing was sent; never raises."""
    try:
        return _Sender(log_line, environ, opener)._send(
            sanitize(steps, why=True))
    except Exception:
        return None


# -- run on its own ------------------------------------------------------------

def append_log_line(log_path: Path, text: str, tag: str) -> None:
    """One `[<tag>]` line in the slice's log, in the loops' line format, as
    one write on an O_APPEND descriptor, so a driver appending to the same
    file never splits it. A log that cannot be written loses the line."""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {text}\n".encode()
    try:
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def answer_line(answer: Answer) -> str:
    """What a send came to, in one line."""
    if answer.kind == OK:
        steps = answer.steps.get("steps") if isinstance(answer.steps, dict) \
            else None
        return f"ok: Pilot holds {len(steps)} steps" if isinstance(steps, list) \
            else "ok"
    return f"{answer.kind}: {answer.reason}"


def cmd_publish(args) -> int:
    """One forced publish of a slice folder's `progress`, as `wait` makes
    it, outside any loop: its misses in the folder's log, what came of it
    printed."""
    slice_dir = Path(args.slice_dir)
    state_name, log_name = (("plan_state.json", "plan_log.txt") if args.plan
                            else ("state.json", "log.txt"))
    if not (slice_dir / state_name).is_file():
        print(f"Error: no {state_name} in {slice_dir}", file=sys.stderr)
        return 2
    publisher = Publisher(slice_dir / state_name, lambda text: append_log_line(
        slice_dir / log_name, text, "publish"))
    answer = publisher.publish(force=True)
    if answer is not None:
        print(answer_line(answer))
    elif not publisher.token or not publisher.url:
        print("not sent: no PILOT_TOKEN/PILOT_MCP_URL in this environment")
    else:
        print(f"not sent: {state_name} holds no steps")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    publish_p = sub.add_parser(
        "publish", help="send a slice folder's steps to Pilot once, as a "
                        "loop's `wait` sends them, with the credentials in "
                        "this environment")
    publish_p.add_argument("slice_dir")
    publish_p.add_argument("--plan", action="store_true",
                           help="the plan loop's plan_state.json, not the "
                                "run's state.json")
    publish_p.set_defaults(func=cmd_publish)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
