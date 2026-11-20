#!/usr/bin/env python3
"""A loop's steps, as Pilot shows them — the list and its two publishers.

Both loops keep a list of the steps their run takes, `progress` in their
state file (plan_state.json, state.json): `{"code", "label", "state",
"kind"}` per step, the state `pending`, `active` or `done` and nothing else,
in the order the steps were taken, the ones not reached yet after them. A
step that opens a round past the first also carries `why`, one short line
saying what the round before left unsettled. The drivers edit it through
the pure helpers here and never send it anywhere: they hold no Pilot
credential, and a driver that outlives the session that started it
would hold a stale one. The loops' `wait` (run_loop.wait_on_driver) is what
publishes it — that process is the Pilot session's own, so the token in its
environment is the live one — through `Publisher`. The other publisher is
plan_loop.py `progress`, the plan-slice session's publish of its grounding
steps before the plan loop exists: a process of the Pilot session too, so
its token is live as well, sending a list it is given, with no state file,
through `publish_steps`.

A step's code is `[P<phase>.]<name>[-<round>]`: round 1 has no suffix, the
phase id is the plan's (`P3.code`, `P3a.review-2`, `sweep`, `write-2`). The
names are a fixed set (RUN_KINDS, PLAN_KINDS), which `debrief.py` and
`labeller_records.py` read back out of the codes: the run loop's `code`,
`review`, `sweep`, `consult`, `test`, `docs`, `wrap-up`, `fixes` (the fixes
pass, after the close-out is answered) and `close-out` (the close-out's own
continuation), the plan loop's `ground` (the grounding ahead of its passes),
`write` and `review`. A step's `kind`, what Pilot's estimate keys on, is
not its name but what the one map KIND_MAP gives the name in its loop
(`kind_of`): the run's `code` is `code-writer`, the plan's `review`
`plan-review`, apart from the run's `review`. The live publishing and the
seed (`seed_timings.py`) both take it from there.

Fields a step carries for its clock and its mark, which Pilot never sees
(`sanitize` sends only the `duration` and the `marked` they come to):

- `started`, the ISO time its clock's open stretch began (on a done step,
  the time it last started), and `spent`, the seconds its clock banked
  before it, which `wait`'s `running` line counts together
  (`active_summary`). The clock runs from a start (`start`) to the
  step's finish, which stores `duration`, the whole seconds of both, on the
  done step; it stops without finishing at a `pause` (a usage halt's sleep,
  the close-out's step while `fixes` runs, `paused` naming why) and runs
  again at `resume`; `bank` (a driver's clean exit) banks the open stretch
  into `spent`, and `restart_clock` (a resume) keeps `spent` and banks a
  killed driver's open stretch up to its last sign of life. A step
  finished without its clock ever running has no `duration`.
- `gate_s`, the seconds the round's finished gate runs took, and
  `gate_started`, the start of the one running (`gate_started`,
  `gate_ended`): past GATE_MARK_MINUTES of the two the step is published
  `marked`, and `marked`, kept on the step once the threshold is passed, so
  it stays marked to its done publication.

A step also carries `conversations`, which Pilot does see: the Claude Code
session ids of the rounds that did its work, in the order they came
(`add_conversation`).

A publisher sends the whole list with one JSON-RPC `tools/call` of Pilot's
MCP tool `set_progress`, with no `initialize` first (the server keeps no
session) and no MCP client: `urllib.request`, bounded at about TIMEOUT
seconds, so a slow Pilot never pushes `wait` past its budget. Every step
goes with its `kind`, `marked` and `conversations`, and a done one with its
`duration`, to every Pilot: both of Pilot's stages take them. A step's `why`
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

The same client seeds a repo's past timings (`seed_step_timings`, which
`seed_timings.py` calls): up to SEED_MAX a call, bounded at about
SEED_TIMEOUT seconds, with the credentials `send` takes (`credentials`).

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

# The names a step's code is made of, which debrief.py and
# labeller_records.py read back: unchanged, whatever the kinds become.
RUN_KINDS = ("code", "review", "sweep", "consult", "test", "docs", "wrap-up",
             "fixes", "close-out")
PLAN_KINDS = ("ground", "write", "review")
KINDS = frozenset(RUN_KINDS + PLAN_KINDS)

RUN = "run"
PLAN = "plan"
# The one map from a loop's step name to the step's kind (D1): what Pilot's
# estimate keys on, for the live publishing and the seed alike. The plan's
# review and the run's stay apart.
KIND_MAP = {
    RUN: {"code": "code-writer", "review": "review", "sweep": "sweep",
          "consult": "consult", "test": "test", "docs": "docs",
          "wrap-up": "wrap-up", "fixes": "fixes", "close-out": "close-out"},
    PLAN: {"ground": "plan-grounding", "write": "plan-writer",
           "review": "plan-review"},
}

# Pilot refuses the whole call over any one of these, so they are kept on
# this side (`sanitize`).
CODE_MAX = 64
LABEL_MAX = 120
WHY_MAX = 120
STEPS_MAX = 100
KIND_MAX = 64
DURATION_MAX = 2**31 - 1
CONVERSATION_MAX = 64
CONVERSATIONS_MAX = 100

# A code round's step is marked once its gate time passes this (D3); a repo
# sets its own in `.aiworkflowrc`'s `[progress] gate_mark_minutes`.
GATE_MARK_MINUTES = 40

TIMEOUT = 3          # seconds, the whole call: connect, send, answer
DEBRIEF_TIMEOUT = 15  # the debrief's one call, which no `wait` budget bounds
SEED_TIMEOUT = 30    # a seed's call of up to SEED_MAX timings
TOOL = "set_progress"
DEBRIEF_TOOL = "register_debrief"
SEED_TOOL = "seed_step_timings"
SEED_MAX = 1000
# The HTTP seam: `send` takes an opener of its own, and falls back to this
# one, looked up at the call so a suite can put a fake here.
OPENER = urllib.request.urlopen

_PHASE_RE = re.compile(r"^P([A-Za-z0-9]+)\.")
_CODE_RE = re.compile(r"^(?:P([A-Za-z0-9]+)\.)?(.+?)(?:-(\d+))?$")


# -- the list ------------------------------------------------------------------

def step_code(kind: str, round_: int = 1, phase: str | None = None) -> str:
    """The code of a step named `kind` (one of KINDS) — of phase `phase`
    (as the plan writes its id) when it has one, in round `round_`."""
    if kind not in KINDS:
        raise ValueError(f"unknown step kind {kind!r}")
    code = f"{kind}-{round_}" if round_ >= 2 else kind
    return f"P{phase}.{code}" if phase is not None else code


def kind_of(code: str, loop: str = RUN) -> str | None:
    """The kind of the step `code` in `loop` (RUN or PLAN), from KIND_MAP:
    a whole code (`P2.code-3` → `code-writer`, `review` in the plan →
    `plan-review`) or a bare name. None for a code whose name the loop's map
    lacks; ValueError for a loop that is neither."""
    if loop not in KIND_MAP:
        raise ValueError(f"unknown loop {loop!r}")
    if not isinstance(code, str) or not code:
        return None
    return KIND_MAP[loop].get(split_code(code)[1])


def phase_of(code: str) -> str | None:
    """The phase id a step's code names, or None for a step of no phase."""
    match = _PHASE_RE.match(code or "")
    return match.group(1) if match else None


def split_code(code: str) -> tuple[str | None, str, int]:
    """A step's code, not empty, as its phase id (None for a step of no
    phase), its name and its round: `P3a.review-2` → ("3a", "review", 2),
    `sweep` → (None, "sweep", 1)."""
    phase, kind, round_ = _CODE_RE.match(code).groups()
    return phase, kind, int(round_) if round_ else 1


def active_step(steps) -> dict | None:
    """The list's active step — the one whose clock runs where a paused one
    stands beside it — or None where none is."""
    if not isinstance(steps, list):
        return None
    active = [s for s in steps if isinstance(s, dict)
              and s.get("state") == ACTIVE]
    return next((s for s in active if not s.get("paused")),
                active[0] if active else None)


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
              why: str | None = None, loop: str = RUN) -> dict:
    """A step of `loop` (RUN or PLAN), with its kind from KIND_MAP; the plan
    loop's callers pass PLAN, so that its review is the plan's."""
    step = {"code": code, "label": clip_label(label), "state": state}
    line = clip_why(why)
    if line is not None:
        step["why"] = line
    kind = kind_of(code, loop)
    if kind is not None:
        step["kind"] = kind
    return step


def phase_steps(phase_id: str, title: str, done: bool = False) -> list[dict]:
    """A phase's two steps before any round of it ran: its code step,
    labelled with its title, and its review."""
    state = DONE if done else PENDING
    return [make_step(step_code("code", 1, phase_id), f"P{phase_id} · {title}",
                      state),
            make_step(step_code("review", 1, phase_id), f"P{phase_id} · review",
                      state)]


def pending_first(steps: list[dict]) -> list[dict]:
    """A copy of the list with every step pending and none carrying a
    duration — a fresh run's first publication, made before any step of it
    is published begun, so that each step stands listed ahead on Pilot's
    side when it starts (AIWF-200)."""
    return [{k: v for k, v in s.items() if k != "duration"} | {"state": PENDING}
            for s in steps if isinstance(s, dict)]


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
    as `start` keeps it — is one named `kind` (of phase `phase`)."""
    last = next((s for s in reversed(steps) if s.get("state") != PENDING),
                None)
    match = _CODE_RE.match((last or {}).get("code") or "")
    return bool(match) and match.group(1) == phase and match.group(2) == kind


# -- the clock -----------------------------------------------------------------

def _moment(at) -> datetime | None:
    """`at` as a datetime with its offset: one given (a naive one taken as
    local), or an ISO text with its offset; None for anything else, a text
    with no offset included."""
    if isinstance(at, datetime):
        return at if at.tzinfo is not None else at.astimezone()
    if isinstance(at, str):
        try:
            then = datetime.fromisoformat(at)
        except ValueError:
            return None
        return then if then.tzinfo is not None else None
    return None


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(at) -> str:
    """`at` as the ISO text a step keeps: a text as given, a datetime
    written out, None as now."""
    if isinstance(at, str):
        return at
    return (_moment(at) if at is not None else _now()).isoformat()


def _between(start, end) -> float:
    """The seconds from `start` to `end`, 0 where either is not a time or
    the end comes first."""
    a, b = _moment(start), _moment(end)
    if a is None or b is None:
        return 0.0
    return max(0.0, (b - a).total_seconds())


def _spent(step: dict) -> float:
    spent = step.get("spent")
    return float(spent) if isinstance(spent, int | float) \
        and not isinstance(spent, bool) and spent == spent else 0.0


def _has_clock(step: dict) -> bool:
    """Whether the step's clock ever ran: a time it started, or seconds
    banked."""
    return step.get("started") is not None or "spent" in step


def _running(step: dict) -> bool:
    """Whether the step's clock has an open stretch: active, not paused,
    and a time it started. A done step keeps the time it last started, its
    clock stopped."""
    return step.get("state") == ACTIVE and not step.get("paused") \
        and step.get("started") is not None


def elapsed(step: dict, at=None) -> float:
    """The seconds the step's clock has run up to `at` (now where None):
    its banked seconds and its open stretch."""
    open_ = _between(step["started"], at if at is not None else _now()) \
        if _running(step) else 0.0
    return _spent(step) + open_


def _banked(step: dict, at) -> dict:
    """The step with its open stretch, up to `at`, added to `spent` and
    closed; a step with none as it is."""
    out = dict(step)
    if _running(out):
        out["spent"] = round(elapsed(out, at), 3)
        out.pop("started")
    return out


def _finished(step: dict, at) -> dict:
    """The step done at `at`: a step that was not done and whose clock ran
    stores its whole seconds as `duration`, an int, and keeps the time it
    last started; its running gate's stretch goes into `gate_s`. A step
    already done is left as it is, and a step whose clock never ran gets
    no duration."""
    if step.get("state") == DONE:
        return dict(step)
    out = _gate_closed(step, at)
    if _has_clock(out):
        out["spent"] = round(elapsed(out, at), 3)
        out["duration"] = int(_spent(out))
    else:
        out.pop("duration", None)
    out.pop("paused", None)
    out["state"] = DONE
    return out


def _resolve(steps: list[dict], code: str | None):
    """Whether a step is the one `code` names — the active ones whose clock
    runs, where `code` is None."""
    if code is not None:
        return lambda s: s.get("code") == code
    return lambda s: s.get("state") == ACTIVE and not s.get("paused")


def start(steps: list[dict], code: str, label: str,
          started: str | None = None, why: str | None = None,
          loop: str = RUN) -> list[dict]:
    """The list with step `code` active and every other active step done —
    both loops run one step at a time; a paused step (`pause`) alone stays
    as it is. A step not on the list goes in right before the first pending
    one, so the steps taken stay in the order they were taken, ahead of
    those not reached yet. Every step it touches carries its kind in
    `loop`.

    With `started`, an ISO time, the step's clock runs from it, and the
    steps it finishes stop at it (now, without one). A step started again —
    active already, or done and re-activated, a round reattached under its
    number — keeps the seconds it ran, its open stretch banked and its
    duration dropped until it is done again: the round counts whole. With
    `why`, the step takes that line, and without one it keeps the why it
    has."""
    at = started if started is not None else _now()
    out = [_finished(s, at) if s.get("state") == ACTIVE
           and s.get("code") != code and not s.get("paused") else dict(s)
           for s in steps]
    line = clip_why(why)
    kind = kind_of(code, loop)
    for i, s in enumerate(out):
        if s.get("code") != code:
            continue
        if started is not None:
            s = _banked(s, started)
            s["started"] = started
        s.pop("duration", None)
        s.pop("paused", None)
        s.update(label=clip_label(label), state=ACTIVE)
        if line is not None:
            s["why"] = line
        if kind is not None:
            s["kind"] = kind
        out[i] = s
        return out
    step = make_step(code, label, ACTIVE, why, loop)
    if started is not None:
        step["started"] = started
    out.insert(_first_pending(out), step)
    return out


def pause(steps: list[dict], at, code: str | None = None,
          reason: str = "paused") -> list[dict]:
    """The list with step `code`'s clock stopped at `at` — the active steps
    whose clock runs, where `code` is None — without finishing it: its open
    stretch banked, and `paused` naming `reason` until `resume`. A usage
    halt's sleep pauses the running step; the close-out pauses its own step
    while `fixes` runs. A step not active is left as it is."""
    match = _resolve(steps, code)
    return [dict(_banked(s, at), paused=reason)
            if match(s) and s.get("state") == ACTIVE and not s.get("paused")
            else dict(s) for s in steps]


def resume(steps: list[dict], at, code: str | None = None,
           reason: str | None = None) -> list[dict]:
    """The list with step `code`'s paused clock running again from `at` —
    every paused step, where `code` is None, of those paused for `reason`
    where it is given. A step not paused is left as it is."""
    def lifts(s: dict) -> bool:
        return bool(s.get("paused")) and (code is None or s.get("code") == code) \
            and (reason is None or s.get("paused") == reason)
    out = []
    for s in steps:
        s = dict(s)
        if lifts(s):
            s.pop("paused")
            if s.get("state") == ACTIVE:
                s["started"] = _iso(at)
        out.append(s)
    return out


def bank(steps: list[dict], at, code: str | None = None) -> list[dict]:
    """The list with step `code`'s open stretch — the active steps', where
    `code` is None — added to its banked seconds up to `at`, and closed: a
    driver's clean exit, so the time the run then stands stopped is not the
    step's. `restart_clock` opens it again."""
    match = _resolve(steps, code)
    return [_banked(s, at) if match(s) else dict(s) for s in steps]


def restart_clock(steps: list[dict], started: str,
                  last_seen=None) -> list[dict]:
    """The list with its active step's clock running from `started` — a
    resumed run's: the time the run stood stopped is no time spent in the
    step, the time it ran before is. An open stretch a killed driver left
    is banked up to `last_seen`, the old driver's last sign of life, where
    given, and dropped where not; one a clean exit banked is kept as it is.
    A paused step stays paused: its `resume` restarts it."""
    out = []
    for s in steps:
        s = dict(s)
        if s.get("state") == ACTIVE and not s.get("paused"):
            if s.get("started") is not None and last_seen is not None:
                s = _banked(s, last_seen)
            elif "spent" in s or s.get("started") is not None:
                s["spent"] = round(_spent(s), 3)
            s["started"] = started
        out.append(s)
    return out


def finish_active(steps: list[dict], at=None) -> list[dict]:
    """The list with every active step done at `at` (now where None), a
    paused one included."""
    at = at if at is not None else _now()
    return [_finished(s, at) if s.get("state") == ACTIVE else dict(s)
            for s in steps]


def finish_step(steps: list[dict], code: str, at=None) -> list[dict]:
    """The list with step `code` done at `at` (now where None) — a step
    the run reached and that had nothing to do, which gets no duration
    unless its clock ran."""
    at = at if at is not None else _now()
    return [_finished(s, at) if s.get("code") == code else dict(s)
            for s in steps]


def finish_phase(steps: list[dict], phase_id: str, at=None) -> list[dict]:
    """The list with every step of phase `phase_id` done at `at` (now where
    None) — the phase merged, whatever of it was still pending or active; a
    pending one gets no duration."""
    at = at if at is not None else _now()
    return [_finished(s, at) if phase_of(s.get("code", "")) == phase_id
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


def edit_step(steps: list[dict], code: str | None,
              edit: Callable[[dict], dict]) -> list[dict]:
    """The list with `edit` applied to step `code` — to the active step
    (`active_step`), where `code` is None; unchanged where no step is it."""
    target = active_step(steps) if code is None else next(
        (s for s in steps if isinstance(s, dict) and s.get("code") == code),
        None)
    return [edit(dict(s)) if s is target and target is not None else dict(s)
            for s in steps]


# -- a step's conversations ----------------------------------------------------

def clip_conversations(ids) -> list[str]:
    """Session ids as Pilot takes a step's: each a text, not blank, of at
    most CONVERSATION_MAX characters (a longer one dropped, not cut), each
    once, the first CONVERSATIONS_MAX of them, in the order given."""
    out: list[str] = []
    for i in ids if isinstance(ids, list) else []:
        if len(out) >= CONVERSATIONS_MAX:
            break
        if isinstance(i, str) and i.strip() and len(i) <= CONVERSATION_MAX \
                and i not in out:
            out.append(i)
    return out


def add_conversation(steps: list[dict], code: str | None,
                     session_id) -> list[dict]:
    """The list with `session_id` among step `code`'s conversations — the
    active step's, where `code` is None — after those it names already: an
    id it names, a blank one, one over CONVERSATION_MAX characters, or one
    past the first CONVERSATIONS_MAX, leaves it as it was (D5)."""
    def add(step: dict) -> dict:
        step["conversations"] = clip_conversations(
            clip_conversations(step.get("conversations")) + [session_id])
        return step
    return edit_step(steps, code, add)


# -- the gate mark -------------------------------------------------------------

def _minutes(minutes) -> int:
    return minutes if isinstance(minutes, int) and not isinstance(
        minutes, bool) and minutes > 0 else GATE_MARK_MINUTES


def gate_seconds(step: dict, at=None) -> float:
    """The seconds of the round's gate runs up to `at` (now where None):
    the finished ones' total and the running one's elapsed time — none on a
    done step, whose finish ended it (`finish_active` and its kin)."""
    gate = step.get("gate_s")
    total = float(gate) if isinstance(gate, int | float) \
        and not isinstance(gate, bool) else 0.0
    if step.get("gate_started") is not None and step.get("state") != DONE:
        total += _between(step["gate_started"],
                          at if at is not None else _now())
    return total


def gate_marked(step: dict, at=None,
                minutes: int = GATE_MARK_MINUTES) -> bool:
    """Whether the step is marked at `at`: marked already, or its gate
    seconds past `minutes` (D3)."""
    return step.get("marked") is True \
        or gate_seconds(step, at) > _minutes(minutes) * 60


def gate_started(step: dict, at) -> dict:
    """The step with a gate run started at `at` — one the driver runs for
    its round: the phase gate, the re-gate after a fix, the run on the
    merge base."""
    out = dict(step)
    out["gate_started"] = _iso(at)
    return out


def _gate_closed(step: dict, at) -> dict:
    out = dict(step)
    if out.get("gate_started") is not None:
        out["gate_s"] = round(gate_seconds(out, at), 3)
    out.pop("gate_started", None)
    return out


def gate_ended(step: dict, at, minutes: int = GATE_MARK_MINUTES) -> dict:
    """The step with its running gate ended at `at`, its seconds added to
    the round's, and `marked` kept on it once they pass `minutes`."""
    out = _gate_closed(step, at)
    if gate_marked(out, at, minutes):
        out["marked"] = True
    return out


def mark(step: dict, at=None, minutes: int = GATE_MARK_MINUTES) -> dict:
    """The step with `marked` kept on it where its gate seconds at `at`
    passed `minutes` — the mark persisted, so it stays to the done
    publication."""
    out = dict(step)
    if gate_marked(out, at, minutes):
        out["marked"] = True
    return out


# -- what `wait` says and what Pilot takes ---------------------------------------

def active_summary(steps, now: datetime | None = None) -> str | None:
    """Where a loop stands, for `wait`'s `running` line: its active step's
    phase, name and round as its code names them — `P4 code`, `P4 review
    r2`, `sweep r2`, `wrap-up`, `write r2` — and the whole minutes its
    clock has run, its banked seconds included, `, 12m` (`, <1m`,
    `, 1h05m`). None with no active step; no time for a step whose clock
    never ran, as one an older loop started, or whose start does not read
    as an ISO time. Never raises."""
    try:
        step = active_step(steps)
        code = step.get("code") if step else None
        if not isinstance(code, str) or not code:
            return None
        match = _CODE_RE.match(code)
        if match:
            phase, kind, round_ = match.groups()
            code = ((f"P{phase} " if phase else "") + kind
                    + (f" r{round_}" if round_ else ""))
        took = _took(step, now)
        return f"{code}, {took}" if took else code
    except Exception:
        return None


def _took(step: dict, now: datetime | None) -> str | None:
    started = step.get("started")
    if started is not None and _moment(started) is None:
        return None
    if not _has_clock(step):
        return None
    seconds = elapsed(step, now or _now())
    minutes = int(seconds // 60)
    if minutes < 1:
        return "<1m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def _kind(step: dict, loop: str) -> str | None:
    kind = step.get("kind")
    if isinstance(kind, str) and kind.strip() and len(kind) <= KIND_MAX:
        return kind
    try:
        return kind_of(step.get("code"), loop)
    except ValueError:
        return None


def _duration(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) \
            or value != value or value in (float("inf"), float("-inf")):
        return None
    return min(max(int(value), 0), DURATION_MAX)


def sanitize(steps, why: bool = False, *, at=None,
             gate_mark_minutes: int = GATE_MARK_MINUTES,
             loop: str = RUN) -> list[dict]:
    """The list as Pilot takes it, every step with all of Pilot's fields and
    none other, since a call clears a field it leaves out: a step whose code
    is empty or longer than CODE_MAX dropped, a repeated code kept at its
    first, an empty label replaced by the code, a label cut at LABEL_MAX, a
    state outside STATES left out, and of more than STEPS_MAX steps the last
    ones — the list is in the order the steps were taken, so the oldest done
    steps go first. With `why`, a step keeps its why as `clip_why` leaves
    it; without, no step carries one.

    Each step carries its `kind` (the one it holds, else KIND_MAP's for its
    code in `loop`; none where neither gives one), `marked`, always a bool,
    computed at `at` (now where None) against `gate_mark_minutes`
    (`gate_marked`), and `conversations`, always a list, clipped as
    `clip_conversations` clips them. A step sent `done` that carries a
    duration sends it, an int clipped to 0..DURATION_MAX; no other step
    sends one."""
    when = at if at is not None else _now()
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
        kind = _kind(s, loop)
        if kind is not None:
            step["kind"] = kind
        duration = _duration(s.get("duration")) \
            if step.get("state") == DONE else None
        if duration is not None:
            step["duration"] = duration
        step["marked"] = gate_marked(s, when, gate_mark_minutes)
        step["conversations"] = clip_conversations(s.get("conversations"))
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
    `figures` where DEBRIEF_TOOL has that field, and the seed where it lists
    SEED_TOOL."""
    why: bool = False
    debrief: bool = False
    subject: bool = False
    figures: bool = False
    seed: bool = False


NOTHING = Takes()


class Answer(NamedTuple):
    """What a call came to: `ok` — with, of a `set_progress`, the list as
    Pilot now holds it, of a `tools/list` (`discover`), what it takes, of a
    DEBRIEF_TOOL, the number of entries it stored, of a SEED_TOOL, the
    number of timings it wrote — `refused` with Pilot's reason, or
    `no_answer` with why none came."""
    kind: str
    steps: list | None = None
    reason: str = ""
    takes: Takes | None = None
    entries: int | None = None
    timings: int | None = None


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


def credentials(environ=None) -> tuple[str, str]:
    """The session's Pilot, as `(url, token)`, from `PILOT_MCP_URL` and
    `PILOT_TOKEN` in `environ` (this process's environment where None);
    an empty text for either that is not set."""
    env = os.environ if environ is None else environ
    return env.get("PILOT_MCP_URL") or "", env.get("PILOT_TOKEN") or ""


def send(steps: list[dict], url: str, token: str,
         opener: Callable | None = None, timeout: float = TIMEOUT,
         why: bool = False, *, gate_mark_minutes: int = GATE_MARK_MINUTES,
         loop: str = RUN) -> Answer:
    """One `tools/call` of `set_progress` with the whole list, held to
    Pilot's limits (`sanitize`, which computes each step's mark now against
    `gate_mark_minutes` and gives a step with no kind its `loop`'s), each
    step's why with it only with `why`, and answered within about `timeout`
    seconds. Never raises; no reason holds the token."""
    try:
        message = _post("tools/call", {
            "name": TOOL, "arguments": {"steps": sanitize(
                steps, why, gate_mark_minutes=gate_mark_minutes, loop=loop)}},
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


def seed_step_timings(timings: list[dict], url: str, token: str,
                      opener: Callable | None = None,
                      timeout: float = SEED_TIMEOUT) -> Answer:
    """One `tools/call` of SEED_TOOL with `timings`, as given — each a
    `key`, a `kind`, an `ended_at` as ISO text with its offset, a
    `duration` as an int and, where known, `listed_ahead` — answered within
    about `timeout` seconds: `ok` with the number Pilot wrote (`timings`),
    else `refused` with Pilot's reason (a work item with no repo, a key
    repeated, a tool it does not list) or `no_answer` with why none came.
    The credentials are `send`'s (`credentials`). ValueError for no
    timings or more than SEED_MAX, which the caller splits into calls;
    otherwise never raises, and no reason holds the token."""
    if not isinstance(timings, list) or not 1 <= len(timings) <= SEED_MAX:
        raise ValueError(f"a seed call takes 1 to {SEED_MAX} timings")
    try:
        message = _post("tools/call", {
            "name": SEED_TOOL, "arguments": {"timings": timings}},
            url, token, opener, timeout)
    except _NoAnswer as e:
        return Answer(NO_ANSWER, reason=str(e))
    answer = _answer(message, token)
    if answer.kind != OK:
        return answer
    content = answer.steps
    if not isinstance(content, dict):
        texts = [c.get("text") for c in (message["result"].get("content")
                                          or [])
                 if isinstance(c, dict) and c.get("type") == "text"]
        content = _json(texts[0]) if texts and isinstance(texts[0], str) \
            else None
    written = content.get("timings") if isinstance(content, dict) else None
    return Answer(OK, timings=written if isinstance(written, int)
                  and not isinstance(written, bool) else None)


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
        figures=_debrief_takes_figures(named.get(DEBRIEF_TOOL)),
        seed=SEED_TOOL in named))


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
        self.log_line = log_line
        self.url, self.token = credentials(environ)
        self.opener = opener
        self.loop = RUN
        self.gate_mark_minutes = GATE_MARK_MINUTES
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
        answer = send(steps, self.url, self.token, self.opener, why=why,
                      gate_mark_minutes=self.gate_mark_minutes, loop=self.loop)
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
    and so is the miss of what the Pilot takes, asked once per publisher.

    Each step's mark is computed at the publish against `gate_mark_minutes`
    (the repo's `[progress] gate_mark_minutes`), so a gate still running
    marks its step as soon as it passes them; a step with no kind takes its
    `loop`'s, the plan's where the state file is plan_state.json unless
    `loop` says otherwise."""

    def __init__(self, state_path: Path, log_line: Callable[[str], None],
                 environ=None, opener: Callable | None = None,
                 gate_mark_minutes: int = GATE_MARK_MINUTES,
                 loop: str | None = None):
        super().__init__(log_line, environ, opener)
        self.state_path = Path(state_path)
        self.gate_mark_minutes = gate_mark_minutes
        self.loop = loop if loop is not None else (
            PLAN if self.state_path.name == "plan_state.json" else RUN)
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
        return sanitize(progress, why=True,
                        gate_mark_minutes=self.gate_mark_minutes,
                        loop=self.loop)


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
                  environ=None, opener: Callable | None = None,
                  loop: str = RUN,
                  gate_mark_minutes: int = GATE_MARK_MINUTES) -> Answer | None:
    """One send of `steps`, a list given rather than a state file's — the
    plan-slice session's grounding steps, before the plan loop exists
    (plan_loop.py `progress`), or the close-out's continuation's — with the
    publisher's ways: the credentials from this process's environment, the
    list held to Pilot's limits, a step with no kind given its `loop`'s,
    the whys where Pilot takes them, each kind of failure logged once
    through `log_line`. The answer, or None when nothing was sent; never
    raises."""
    try:
        sender = _Sender(log_line, environ, opener)
        sender.loop, sender.gate_mark_minutes = loop, gate_mark_minutes
        return sender._send(sanitize(steps, why=True, loop=loop,
                                     gate_mark_minutes=gate_mark_minutes))
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
