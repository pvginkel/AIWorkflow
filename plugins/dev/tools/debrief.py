#!/usr/bin/env python3
"""A loop's debrief file: every dispatch's own account of how it went.

Every role a loop dispatches is asked, at its hand-back, for a debrief — "a
few lines, in your own words, on how you feel this went for you" — and gives
it as its verdict's `debrief`. The loop keeps each one in a file of its own
beside its state file, RUN_FILE beside the run's `state.json` and PLAN_FILE
beside the plan's `plan_state.json`, as an entry of its own, in the order
it dispatched them: never a field of the history row, never one text with
prefixes. The file is `{"entries": [...]}`; the loops append to it, and
rewrite an entry only where the run's commit nudge salvages its round's
verdict (`revise_words`).

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

The plan preparer, which the plan-slice session dispatches before the plan
loop exists, has its entry in PLAN_FILE too, under the step `ground`: the
session notes its start before the dispatch and its end after it, and the
preparer gives its words in between (`ground`). They wait in the file under
`ground` until the end makes them an entry, which stands first, before the
loop's first pass, across the work items between.

When the loop completes, the stage session is handed every entry in order
and the loop's figures under STAGE_PROMPT (`input`), and gives its own
debrief, which the file keeps as `debrief` beside `entries` (`give`). Then
the whole goes to Pilot, held to its limits (`for_pilot`), once, where that
Pilot takes it (pilot_progress.hand_off_debrief); the slice's log says what
came of it. It goes with the slice as its subject (`subject_of`), the same
at both stages, the planning's not completing it and the run's completing
it (COMPLETES), so that Pilot carries one slice's debriefs in one notice.
Run on its own, over a slice folder:

    debrief.py input <slice-dir> --stage run|plan
    debrief.py give <slice-dir> --stage run|plan       (the words on stdin)
    debrief.py hand-off <slice-dir> --stage run|plan
    debrief.py ground <slice-dir> --start|--words|--end  (--words on stdin)

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pilot_progress

RUN_FILE = "debrief.json"
PLAN_FILE = "plan_debrief.json"

# The state file, the debrief file and the log of each stage, by its name.
STAGES = {
    "run": ("state.json", RUN_FILE, "log.txt"),
    "plan": ("plan_state.json", PLAN_FILE, "plan_log.txt"),
}

# Whether a stage's debrief completes its slice's account: the run's does,
# and the planning's is carried with it.
COMPLETES = {"run": True, "plan": False}

# A slice folder's number: digits, then `_` or the end of the name.
SLICE_NUM_RE = re.compile(r"^(\d+)(?:_|$)")

GROUND = "ground"
PREPARER = "plan-preparer"

CHECK_SECTION = "Completion check"
PLAN_SECTION = "The plan"
# The section of a step of no phase, by its kind; a phase's is its first
# step's label.
SECTIONS = {
    "sweep": CHECK_SECTION, "consult": CHECK_SECTION,
    "test": "Test phase", "docs": "Doc phase", "wrap-up": "Wrap-up",
    "write": PLAN_SECTION, "review": PLAN_SECTION, GROUND: "The grounding",
}

ROLE_NAMES = {
    "code-writer": "Code writer", "code-reviewer": "Code reviewer",
    "test-fixer": "Test fixer", "test-agent": "Test agent",
    "doc-writer": "Doc writer", "wrap-up": "Wrap-up", "sweep": "Gate sweep",
    "plan-writer": "Plan writer", "plan-reviewer": "Plan reviewer",
    PREPARER: "Plan preparer",
}

# The kind of the step a role runs under, where the list has no active
# step to read it off.
ROLE_KINDS = {
    "code-writer": "code", "code-reviewer": "review", "test-fixer": "consult",
    "test-agent": "test", "doc-writer": "docs", "wrap-up": "wrap-up",
    "sweep": "sweep", "plan-writer": "write", "plan-reviewer": "review",
    PREPARER: GROUND,
}

# The operator's words to the stage session at the loop's end, as ruled.
STAGE_PROMPT = (
    "The loop has ended. Below are the debriefs of every agent it dispatched, "
    "in order, and the loop's own figures: phases, rounds, consults, "
    "durations, cost. Read them against the run as you watched it, then give, "
    "in your own words, how you feel the loop went. What to dwell on is "
    "yours, and so is saying that nothing is worth saying."
)

# Pilot refuses the whole call over any one of these (its register_debrief),
# so they are kept on this side (`for_pilot`); a why's is
# pilot_progress.WHY_MAX.
DEBRIEF_MAX = 16_000
ENTRIES_MAX = 500
SECTION_MAX = 120
ROLE_MAX = 64
WORDS_MAX = 4_000
SUBJECT_MAX = 120


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


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def append(path: Path, entry: dict) -> None:
    """`entry` after the file's entries, written atomically; the rest of
    the file kept as it is."""
    path = Path(path)
    data = _load(path)
    data["entries"] = [*(data.get("entries") or []), entry]
    _save(path, data)


def revise_words(path: Path, verdict) -> None:
    """The file's last entry given the words of `verdict`, a verdict the
    round wrote on its commit nudge, after its entry was appended; a
    verdict with none leaves the entry as it is."""
    path = Path(path)
    words = words_of(verdict)
    data = _load(path)
    if words is None or not data.get("entries"):
        return
    data["entries"][-1]["words"] = words
    _save(path, data)


def _save(path: Path, data: dict) -> None:
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


# -- the plan preparer ---------------------------------------------------------

def _now() -> datetime:
    return datetime.now().astimezone()


def ground_start(path: Path, now: datetime | None = None) -> None:
    """The preparer's dispatch noted as started: its time under `ground`,
    whatever an earlier dispatch left there replaced."""
    path = Path(path)
    data = _load(path)
    data[GROUND] = {"started": (now or _now()).isoformat()}
    _save(path, data)


def ground_words(path: Path, words: str) -> None:
    """The preparer's debrief, kept under `ground` until its end is noted."""
    path = Path(path)
    data = _load(path)
    data[GROUND] = {**(data.get(GROUND) or {}), "words": words.strip()}
    _save(path, data)


def ground_end(path: Path, now: datetime | None = None) -> dict:
    """The preparer's entry appended to the file: its time from the start
    noted to `now`, and its words where it gave them; `ground` taken off.
    ValueError where no start was noted. Returns the entry."""
    path = Path(path)
    data = _load(path)
    pending = data.pop(GROUND, None) or {}
    if not isinstance(pending.get("started"), str):
        raise ValueError(f"no start of the plan preparer noted in {path}")
    seconds = ((now or _now())
               - datetime.fromisoformat(pending["started"])).total_seconds()
    entries = list(data.get("entries") or [])
    entry = make_entry(entries, [], GROUND, ROLE_NAMES[PREPARER],
                       max(int(seconds), 0), words=pending.get("words") or None)
    data["entries"] = [*entries, entry]
    _save(path, data)
    return entry


# -- the stage session's debrief -----------------------------------------------

def give(path: Path, words: str) -> None:
    """The stage session's own debrief, kept as the file's `debrief`."""
    path = Path(path)
    data = _load(path)
    data["debrief"] = words.strip()
    _save(path, data)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def for_pilot(data: dict) -> tuple[str | None, list[dict]]:
    """The file's `debrief` and entries as Pilot's register_debrief takes
    them: each text past its limit cut with an ellipsis, a why as a step's
    is, `step` left out, and past ENTRIES_MAX the entries in order up to it
    — the file keeps them all. The debrief is None where the file has none."""
    words = data.get("debrief")
    words = _clip(words.strip(), DEBRIEF_MAX) \
        if isinstance(words, str) and words.strip() else None
    entries = []
    for e in (data.get("entries") or [])[:ENTRIES_MAX]:
        entry = {"section": _clip(e["section"], SECTION_MAX),
                 "round": int(e["round"]),
                 "role": _clip(e["role"], ROLE_MAX),
                 "duration": int(e["duration"])}
        if e.get("words"):
            entry["words"] = _clip(e["words"], WORDS_MAX)
        elif isinstance(e.get("passed"), bool):
            entry["passed"] = e["passed"]
        why = pilot_progress.clip_why(e.get("why"))
        if why is not None:
            entry["why"] = why
        entries.append(entry)
    return words, entries


def slice_title(slice_dir: Path) -> str | None:
    """slice.md's `# ` title, its frontmatter skipped; None where the folder
    has no slice.md to read, as `run_loop.slice_card_and_title` reads it, or
    it has no title."""
    try:
        lines = (Path(slice_dir) / "slice.md").read_text(
            encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    start = 0
    if lines and lines[0] == "---":
        close = next((i for i in range(1, len(lines)) if lines[i] == "---"),
                     None)
        if close is not None:
            start = close + 1
    for line in lines[start:]:
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return None


def subject_of(slice_dir: Path) -> str | None:
    """What the slice's debriefs are an account of, as Pilot titles their
    notice: `Slice <number> · <title>`, the folder's number and slice.md's
    title, cut to SUBJECT_MAX with an ellipsis. The folder keeps its name
    and slice.md from the planning to the run, so both stages give the
    same. None where the folder's name opens on no number or slice.md has
    no title."""
    match = SLICE_NUM_RE.match(Path(os.path.abspath(slice_dir)).name)
    title = slice_title(slice_dir)
    if match is None or title is None:
        return None
    return _clip(" ".join(f"Slice {match.group(1)} · {title}".split()),
                 SUBJECT_MAX)


def hand_off(path: Path, log_line, subject: str | None = None,
             completes: bool = True) -> pilot_progress.Answer | None:
    """The file handed to Pilot whole, as `for_pilot` holds it, where the
    Pilot of this process's environment takes it, with `subject` and
    `completes` where it takes them; what came of it is one line through
    `log_line`. ValueError where the file holds no debrief of the stage
    session's."""
    words, entries = for_pilot(_load(Path(path)))
    if words is None:
        raise ValueError(f"no debrief of the stage session's in {path}")
    return pilot_progress.hand_off_debrief(words, entries, log_line,
                                           subject=subject,
                                           completes=completes)


# -- what the stage session reads ----------------------------------------------

def span(seconds) -> str:
    """Whole seconds as `45s`, `12m` or `1h05m`."""
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"


def _n(count, noun: str, nouns: str | None = None) -> str:
    count = int(count or 0)
    return f"{count} {noun if count == 1 else nouns or noun + 's'}"


def _took(rows) -> str:
    return span(sum(int(h.get("duration_s") or 0) for h in rows))


def _between(state: dict) -> str | None:
    try:
        seconds = (datetime.fromisoformat(state["updated_at"])
                   - datetime.fromisoformat(state["created_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None
    return span(seconds)


def run_figures(state: dict) -> list[str]:
    """The run's figures off its state.json: its phases, each with its
    rounds and its time, its consults, the completion check, the test and
    doc phases and the wrap-up with theirs, the run's time, its stops, and
    its cost where slice_cost.py --write-state has put it there."""
    history = [h for h in state.get("history") or [] if isinstance(h, dict)]
    labels = {s.get("code"): s.get("label") for s in state.get("progress") or []
              if isinstance(s, dict)}
    phases = state.get("phases") or {}
    known = [str(p) for p in state.get("known_phases") or phases]
    appended = [str(p) for p in state.get("appended_phases") or []]

    def rows(*roles, phase=None):
        return [h for h in history if h.get("role") in roles
                and h.get("phase") == phase]

    lines = [f"Phases: {len(known)}" + (
        f", {len(appended)} appended during the run: "
        + ", ".join(f"P{p}" for p in appended) if appended else "")]
    for pid in known:
        record = phases.get(pid) or {}
        own = [h for h in history if h.get("phase") == pid]
        lines.append(
            f"{labels.get(f'P{pid}.code') or f'P{pid}'}: "
            f"{_n(record.get('executor_rounds'), 'code round')}, "
            f"{_n(record.get('review_rounds'), 'review round')}, "
            f"{_took(own)}")
    consults = [h for h in history if h.get("role") == "consult"]
    at_review = sum(1 for h in consults if h.get("phase") is not None)
    lines.append(f"Consults: {len(consults)}, {at_review} at a review and "
                 f"{len(consults) - at_review} at the completion check")
    sweeps = rows("sweep")
    check = rows("sweep", "consult", "test-fixer")
    lines.append(
        f"Completion check: {_n(len(sweeps), 'gate sweep')}"
        + (" (" + ", ".join(str(h.get("outcome")) for h in sweeps) + ")"
           if sweeps else "")
        + f", {_n(len(rows('test-fixer')), 'test-fixer round')}, "
        f"{_took(check)}")
    lines.append(f"Test phase: {_n(state.get('test_rounds'), 'round')}, "
                 f"{_took(rows('test-agent'))}")
    lines.append(f"Doc phase: {_took(rows('doc-writer'))}, its gate "
                 f"{_took(rows('doc-gate'))}")
    lines.append(f"Wrap-up: {_took(rows('wrap-up'))}, its gates "
                 f"{_took(rows('wrap-up-gate'))}")
    between = _between(state)
    lines.append(f"The run: {_took(history)} in its agents and gates"
                 + (f", {between} from its start to its end" if between
                    else ""))
    stops = state.get("bailouts") or []
    halts = state.get("halts") or []
    if stops or halts:
        lines.append(f"Stops: {_n(len(stops), 'stop')} for the operator or a "
                     f"fix, {_n(len(halts), 'halt')} at Pilot's halt file")
    cost = state.get("cost") or {}
    if isinstance(cost.get("cost_usd"), (int, float)):
        lines.append(f"Cost: ${cost['cost_usd']:,.2f} for the slice, the "
                     f"planning's ${cost.get('planner_cost_usd') or 0:,.2f} "
                     "of it" + _warned(cost.get("warnings")))
    else:
        lines.append("Cost: not priced, as slice_cost.py --write-state has "
                     "not run")
    return lines


def _warned(warnings) -> str:
    return f", with {_n(len(warnings), 'pricing warning')}" if warnings else ""


def plan_cost(slice_dir: Path) -> tuple[float, list[str]] | None:
    """What slice_cost.py prices the plan loop's sessions of the folder at,
    their sub-agents and the stage session's included, with its warnings;
    None where the folder has no state file it reads."""
    import slice_cost

    try:
        convs, warnings = slice_cost.collect(Path(slice_dir))
    except FileNotFoundError:
        return None
    return sum(c.cost() for c in convs if c.loop == "plan"), warnings


def plan_figures(state: dict, entries: list[dict],
                 cost: tuple[float, list[str]] | None) -> list[str]:
    """The plan's figures off its plan_state.json and its debrief file: the
    preparer's time, the writer's passes and the review's rounds with
    theirs, the loop's time and the cost slice_cost.py gives the folder."""
    history = [h for h in state.get("history") or [] if isinstance(h, dict)]
    grounding = [e for e in entries if e.get("step") == GROUND]
    lines = []
    if grounding:
        lines.append("Plan preparer: " + span(
            sum(int(e.get("duration") or 0) for e in grounding)))
    lines.append(
        f"Plan writer: {_n(state.get('writer_rounds'), 'pass', 'passes')}, "
        f"{_took([h for h in history if h.get('role') == 'plan-writer'])}")
    lines.append(
        f"Plan reviewer: {_n(state.get('review_rounds'), 'round')}, "
        f"{_took([h for h in history if h.get('role') == 'plan-reviewer'])}")
    between = _between(state)
    if between:
        lines.append(f"The loop: {between} from its start to its end")
    lines.append(f"Cost: ${cost[0]:,.2f} for the folder" + _warned(cost[1])
                 if cost is not None else "Cost: not priced")
    return lines


def _entry_lines(i: int, entry: dict) -> list[str]:
    head = [entry.get("section"), f"round {entry.get('round')}",
            entry.get("role"), span(entry.get("duration"))]
    kind = pilot_progress.split_code(entry["step"])[1] \
        if entry.get("step") else None
    if isinstance(entry.get("passed"), bool):
        head.append("passed" if entry["passed"] else "failed")
    elif not entry.get("words"):
        head.append("nothing ran" if kind == "sweep" else "no debrief")
    lines = [f"{i}. " + " · ".join(str(h) for h in head)]
    if entry.get("why"):
        lines.append(f"   Why: {entry['why']}")
    lines += [f"   {line}".rstrip() for line in
              (entry.get("words") or "").splitlines()]
    return lines


def render_input(slice_dir: Path, stage: str) -> str:
    """What the stage session reads at the loop's end: STAGE_PROMPT, then
    every entry of the stage's debrief file in order, then the loop's
    figures."""
    slice_dir = Path(slice_dir)
    state_name, file_name, _ = STAGES[stage]
    state = json.loads((slice_dir / state_name).read_text())
    entries = read(slice_dir / file_name)
    figures = (run_figures(state) if stage == "run"
               else plan_figures(state, entries, plan_cost(slice_dir)))
    lines = [STAGE_PROMPT, "", "The debriefs, in order:", ""]
    for i, entry in enumerate(entries, 1):
        lines += _entry_lines(i, entry)
    if not entries:
        lines.append("None.")
    lines += ["", "The loop's figures:", *(f"- {f}" for f in figures)]
    return "\n".join(lines) + "\n"


# -- the command line ----------------------------------------------------------

def _words_in() -> str:
    words = sys.stdin.read()
    if not words.strip():
        print("Error: no words on stdin", file=sys.stderr)
        sys.exit(2)
    return words


def _paths(slice_dir: str, stage: str) -> tuple[Path, Path, Path]:
    slice_dir = Path(slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
        sys.exit(2)
    state_name, file_name, log_name = STAGES[stage]
    return slice_dir / state_name, slice_dir / file_name, slice_dir / log_name


def _hand_off(slice_dir: str, stage: str) -> int:
    _, path, log_path = _paths(slice_dir, stage)
    said: list[str] = []

    def log_line(text: str) -> None:
        said.append(text)
        pilot_progress.append_log_line(log_path, text, "debrief")

    try:
        hand_off(path, log_line, subject_of(Path(slice_dir)),
                 COMPLETES[stage])
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    if said:
        print(said[-1])
    return 0


def cmd_input(args) -> int:
    state_path, _, _ = _paths(args.slice_dir, args.stage)
    if not state_path.is_file():
        print(f"Error: no {state_path.name} in {args.slice_dir}",
              file=sys.stderr)
        return 2
    sys.stdout.write(render_input(Path(args.slice_dir), args.stage))
    return 0


def cmd_give(args) -> int:
    _, path, _ = _paths(args.slice_dir, args.stage)
    give(path, _words_in())
    return _hand_off(args.slice_dir, args.stage)


def cmd_hand_off(args) -> int:
    return _hand_off(args.slice_dir, args.stage)


def cmd_ground(args) -> int:
    _, path, _ = _paths(args.slice_dir, "plan")
    if args.start:
        ground_start(path)
    elif args.words:
        ground_words(path, _words_in())
    else:
        try:
            ground_end(path)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def stage_parser(name: str, help_: str):
        p = sub.add_parser(name, help=help_)
        p.add_argument("slice_dir")
        p.add_argument("--stage", required=True, choices=sorted(STAGES),
                       help="the run's debrief.json or the plan's "
                            "plan_debrief.json")
        return p

    stage_parser("input", "print what the stage session reads at the loop's "
                          "end: the ask, every debrief in order, the loop's "
                          "figures").set_defaults(func=cmd_input)
    stage_parser("give", "keep the stage session's debrief, given on stdin, "
                         "in the file, and hand the whole to Pilot"
                 ).set_defaults(func=cmd_give)
    stage_parser("hand-off", "hand the file's debrief to Pilot, once, where "
                             "the Pilot of this environment takes it"
                 ).set_defaults(func=cmd_hand_off)

    ground_p = sub.add_parser("ground", help="the plan preparer's entry in "
                                             "plan_debrief.json")
    ground_p.add_argument("slice_dir")
    when = ground_p.add_mutually_exclusive_group(required=True)
    when.add_argument("--start", action="store_true",
                      help="note the dispatch's start, before it")
    when.add_argument("--words", action="store_true",
                      help="the preparer's debrief, on stdin")
    when.add_argument("--end", action="store_true",
                      help="note the dispatch's end, after it, and append "
                           "its entry")
    ground_p.set_defaults(func=cmd_ground)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
