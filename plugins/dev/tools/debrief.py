#!/usr/bin/env python3
"""A loop's debrief file: every dispatch's own account of how it went.

Every role a loop dispatches is asked, at its hand-back, for a debrief — "a
few lines, in your own words, on how you feel this went for you" — and gives
it as its verdict's `debrief`. The loop keeps each one in a file of its own
beside its state file, RUN_FILE beside the run's `state.json` and PLAN_FILE
beside the plan's `plan_state.json`, as an entry of its own, in the order
it dispatched them: never a field of the history row, never one text with
prefixes. The file is `{"entries": [...]}`; the loops append to it and never
rewrite an entry.

An entry is

  {"section": "P3 · The sessions", "round": 2, "role": "Code writer",
   "duration": 540, "words": "…", "why": "…", "step": "P3.code-2"}

`section` and `round` say where it stands in the full debrief Pilot shows,
which groups consecutive entries of one section and counts their rounds:
both are read off `step`, the code of the step in Progress the dispatch ran
under (`pilot_progress`), so the sections and their rounds read as Progress
has them — a phase, named as its first step is labelled, holds its code and
review rounds and a consult at its review; the completion check its sweeps,
its consults and a sweep's test-fixer; the test phase, the doc phase, the
wrap-up and the plan each one of their own. `role` is the role's name as
the full debrief shows it, `duration` the dispatch's whole seconds.
`words` is the role's debrief as it gave it, and an entry without it is a
dispatch that handed back no debrief, or no verdict: a timeout, a verdict
missing or invalid. A gate sweep, the driver's own, has an entry with
`passed`, its result, in place of words, and with neither where nothing in
it ran. `why` is on the first entry of a step that carries one — the step
that opens a round past the first. `step` is the plugin's own: what Pilot
is handed of an entry leaves it out.

Stdlib only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pilot_progress

RUN_FILE = "debrief.json"
PLAN_FILE = "plan_debrief.json"

CHECK_SECTION = "Completion check"
PLAN_SECTION = "The plan"
# The section of a step of no phase, by its kind; a phase's is its first
# step's label.
SECTIONS = {
    "sweep": CHECK_SECTION, "consult": CHECK_SECTION,
    "test": "Test phase", "docs": "Doc phase", "wrap-up": "Wrap-up",
    "write": PLAN_SECTION, "review": PLAN_SECTION,
}

ROLE_NAMES = {
    "code-writer": "Code writer", "code-reviewer": "Code reviewer",
    "test-fixer": "Test fixer", "test-agent": "Test agent",
    "doc-writer": "Doc writer", "wrap-up": "Wrap-up", "sweep": "Gate sweep",
    "plan-writer": "Plan writer", "plan-reviewer": "Plan reviewer",
}

# The kind of the step a role runs under, where the list has no active
# step to read it off.
ROLE_KINDS = {
    "code-writer": "code", "code-reviewer": "review", "test-fixer": "consult",
    "test-agent": "test", "doc-writer": "docs", "wrap-up": "wrap-up",
    "sweep": "sweep", "plan-writer": "write", "plan-reviewer": "review",
}


def role_name(role: str, phase: str | None = None) -> str:
    """The name the full debrief shows for a dispatch of `role`: a consult
    at a phase's review is the review's, one of no phase the completion
    check's."""
    if role == "consult":
        return "Review consult" if phase is not None else "Completion consult"
    return ROLE_NAMES.get(role, role)


def step_of(steps, role: str, round_: int, phase: str | None = None) -> str:
    """The code of the step a dispatch of `role` ran under: the list's
    active step — every dispatch runs inside one — or, on a list with none,
    the step of the role's kind and the dispatch's round."""
    step = pilot_progress.active_step(steps)
    if step is not None and isinstance(step.get("code"), str) and step["code"]:
        return step["code"]
    kind = ("review" if role == "consult" and phase is not None
            else ROLE_KINDS.get(role, "consult"))
    return pilot_progress.step_code(kind, round_, phase)


def words_of(verdict) -> str | None:
    """A verdict's debrief, its ending whitespace left off; None for a
    verdict that is none, or whose `debrief` is no text or blank."""
    if not isinstance(verdict, dict):
        return None
    words = verdict.get("debrief")
    if not isinstance(words, str) or not words.strip():
        return None
    return words.strip()


def read(path: Path) -> list[dict]:
    """The file's entries, in order; none where there is no file."""
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return []
    return list(json.loads(text).get("entries") or [])


def make_entry(entries: list[dict], steps, code: str, role: str,
               duration: int, words: str | None = None,
               passed: bool | None = None) -> dict:
    """The entry of a dispatch that ran under step `code` of the list
    `steps`, after the file's `entries`: its section and round off the
    step, and the step's why where no entry before it ran under that step."""
    phase, kind, round_ = pilot_progress.split_code(code)
    listed = {s.get("code"): s for s in steps if isinstance(s, dict)} \
        if isinstance(steps, list) else {}
    if phase is not None:
        first = listed.get(pilot_progress.step_code("code", 1, phase)) or {}
        section = first.get("label") or f"P{phase}"
    else:
        section = SECTIONS.get(kind) or (listed.get(code) or {}).get("label") \
            or code
    entry = {"section": section, "round": round_, "role": role,
             "duration": int(duration)}
    if words is not None:
        entry["words"] = words
    elif passed is not None:
        entry["passed"] = passed
    why = pilot_progress.clip_why((listed.get(code) or {}).get("why"))
    if why is not None and not any(e.get("step") == code for e in entries):
        entry["why"] = why
    entry["step"] = code
    return entry


def append(path: Path, entry: dict) -> None:
    """`entry` after the file's entries, written atomically; the rest of
    the file kept as it is."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        data = {}
    data["entries"] = [*(data.get("entries") or []), entry]
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def record(path: Path, steps, role: str, round_: int, duration: int,
           phase: str | None = None, verdict=None,
           passed: bool | None = None) -> dict:
    """A dispatch's entry appended to the file at `path`: of `role` (in
    `phase`, round `round_`), which took `duration` seconds and handed back
    `verdict` — None where it handed back none — or, for a gate sweep, came
    to `passed`. Returns the entry."""
    code = step_of(steps, role, round_, phase)
    entry = make_entry(read(path), steps, code, role_name(role, phase),
                       duration, words=words_of(verdict), passed=passed)
    append(path, entry)
    return entry
