#!/usr/bin/env python3
"""Seed Pilot's step timings with the slices a repo ran before its steps were timed.

Pilot estimates the time a running work item still takes from the Step
Timings it keeps per repo: one per step a work item's session published done
with its kind and its duration (pilot_progress.py). A slice run before the
loops published either has its record only in its spec repo's committed
state files. This command reads them and hands Pilot one timing per finished
step, as a run on this release would have published it, through Pilot's
`seed_step_timings` tool (pilot_progress.seed_step_timings).

    seed_timings.py [<repo-root>] [--dry-run] [--json]

  <repo-root>  the project repo, whose `.aiworkflowrc` names its `spec_repo`
               (project_config); the working directory when not given.
  --dry-run    print the timings, one JSON object a line, and send nothing;
               needs no credentials.
  --json       the summary as one JSON object, not a line of words.

A work item placed in the repo runs it once (P-323): the timings attach to
that work item's repo, and its session's `PILOT_MCP_URL` and `PILOT_TOKEN` are
the credentials (`credentials`, as `send` takes them). Sending a key again
replaces its timing, so a second run changes nothing but what changed.

What it reads: `slices/completed/*/state.json` (the run, `run`) and
`plan_state.json` (the plan, `plan`) in the spec repo, each file on its own.
A file whose `progress` steps already carry a `kind` was published live and
is skipped; a file that does not read is named on stderr and skipped, and the
rest go on.

What a timing is, by the rulings it follows (t24, AIWF-196):

- One per step the live loops would have published, by the codes and rounds
  they give (pilot_progress `step_code`): a phase's `code` round per
  code-writer round and its `review` round per reviewer round, `sweep` per
  sweep run, `consult` per completion consult (counted as `_completion_consults`
  counts them, not by the row's consult number), `test` per test round, then
  `docs`, `wrap-up` and `fixes`; the plan's `write` and `review` per round. No
  `ground`: the plan preparer leaves no history row.
- The rows a round's step covers fold into it, as the active step covers them
  live: a phase's gate rows and its gate test-fixer into the code or review
  step it ran under (the merge's re-gate into the review), a consult with a
  phase into its review (debrief.py), a flake's test-fixer into the
  completion consult whose `flake` dispatched it (run-loop.md § The steps
  Pilot shows), the doc gate and the wrap-up's gates into `wrap-up` (into `docs` on a run from
  before the wrap-up), the fixes pass's rows into `fixes`.
- `kind` from the one map (D1, pilot_progress `kind_of`), the plan's review
  apart from the run's.
- `duration` the sum of the step's rows' `duration_s`, whole seconds (D4):
  the run's own measure, which leaves out a usage halt and a wait on the
  operator. A step whose rows hold no positive duration gives no timing.
- `ended_at` its last row's `ts`, ISO text with its offset; a `ts` with none
  is UTC.
- `listed_ahead` as this release lists it (AIWF-196, AIWF-199): true for a
  step on the run's seeded list, round 1 of a phase the run began with, the
  first sweep and the first consult, the test, doc and wrap-up steps, the
  fixes step (its launcher lists it pending, D2), and the plan's first write
  and review; false for an appended phase's steps (`appended_phases`; on a
  state with none, the phases whose first row follows the run's first
  phase-less one) and for any repeat round.
- `key` `<spec-repo-folder>/<slice-folder>/<run|plan>/<code>`, unique in the
  repo, at most KEY_MAX characters (a longer one cut and given a hash).

It sends at most SEED_MAX timings a call, once `discover` shows the Pilot
lists the tool, and prints what it read and what Pilot wrote. Exit 0 when all
was sent (or nothing was owed), 1 on a refusal or no answer, the reason
printed and the token never, 2 on a usage fault: no `.aiworkflowrc` or
`spec_repo`, no credentials, or a Pilot that does not list the tool. Stdlib
only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pilot_progress  # noqa: E402
import project_config  # noqa: E402
from pilot_progress import PLAN, RUN, kind_of, split_code, step_code  # noqa: E402

KEY_MAX = 200
STATE_FILES = (("state.json", RUN), ("plan_state.json", PLAN))
# The gate rows of the doc ladder and of the fixes pass, which run inside a
# step and are never one.
DOC_GATES = ("doc-gate", "wrap-up-gate")
FIXES_ROLES = ("fixes-gate", "fixes-doc-gate")


class Unreadable(Exception):
    pass


# -- reading -------------------------------------------------------------------

def read_state(path: Path) -> dict:
    """The state file at `path` as a JSON object with a history list;
    Unreadable with why where it is not one."""
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        raise Unreadable(f"unreadable ({e.strerror or e})") from None
    except (ValueError, UnicodeDecodeError) as e:
        raise Unreadable(f"not JSON ({e})") from None
    if not isinstance(data, dict):
        raise Unreadable(f"not a JSON object (a {type(data).__name__})")
    history = data.get("history", [])
    if not isinstance(history, list):
        raise Unreadable("its history is not a list")
    return data


def published_live(state: dict) -> bool:
    """Whether the state's steps carry a kind: a run on a release that
    published them, whose timings Pilot recorded as they went."""
    steps = state.get("progress")
    return isinstance(steps, list) and any(
        isinstance(s, dict) and "kind" in s for s in steps)


def moment(ts) -> datetime | None:
    """A row's `ts` with its offset, a naive one taken as UTC; None for one
    that is no ISO time."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return then if then.tzinfo is not None else then.replace(tzinfo=UTC)


def _seconds(value) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(float(value), 0.0)


def _round(row: dict) -> int:
    r = row.get("round")
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 1 else 1


def _phase(row: dict) -> str | None:
    p = row.get("phase")
    return None if p is None else str(p)


def _rows(state: dict) -> list[dict]:
    return [r for r in state.get("history") or [] if isinstance(r, dict)]


# -- the steps -----------------------------------------------------------------

class _Steps:
    """The steps a history comes to, in the order each was first met: per
    code its rows' seconds, its last time and whether it was listed ahead."""

    def __init__(self) -> None:
        self.steps: dict[str, dict] = {}

    def add(self, code: str, row: dict, ahead: bool) -> None:
        step = self.steps.setdefault(code, {"seconds": 0.0, "ended": None,
                                            "ahead": ahead})
        step["seconds"] += _seconds(row.get("duration_s"))
        then = moment(row.get("ts"))
        if then is not None:
            step["ended"] = then


def appended_phases(state: dict, rows: list[dict]) -> set[str]:
    """The phases the run gained after it began: `appended_phases`, or, on a
    state from before it was kept, the phases whose first row follows the
    run's first row of no phase (a sweep, a completion consult, the test
    phase), the point an appended phase can come from."""
    kept = state.get("appended_phases")
    if isinstance(kept, list):
        return {str(p) for p in kept}
    first_tail = next((i for i, r in enumerate(rows)
                       if _phase(r) is None
                       and r.get("role") in ("sweep", "consult", "test-agent")),
                      None)
    if first_tail is None:
        return set()
    seen = {_phase(r) for r in rows[:first_tail]}
    return {_phase(r) for r in rows[first_tail:]
            if _phase(r) is not None and _phase(r) not in seen}


def run_steps(state: dict) -> dict[str, dict]:
    """The run's steps from its history, each row folded into the step that
    was active as it ran (the module's docstring)."""
    rows = _rows(state)
    appended = appended_phases(state, rows)
    fixes = state.get("fixes")
    fixes_at = moment(fixes.get("started_at")) if isinstance(fixes, dict) \
        else None
    has_wrap_up = "wrap_up" in state or any(r.get("role") == "wrap-up"
                                            for r in rows)
    out = _Steps()
    current: dict[str, str] = {}      # phase -> the step it last started
    last_review: dict[str, str] = {}  # phase -> its last review step
    check: str | None = None          # the completion check's last step
    completions = 0
    wrapped = False

    def phase_ahead(phase: str, round_: int) -> bool:
        return round_ == 1 and phase not in appended

    for row in rows:
        role, phase, round_ = row.get("role"), _phase(row), _round(row)
        then = moment(row.get("ts"))
        in_fixes = fixes_at is not None and then is not None and then >= fixes_at
        if role in FIXES_ROLES or (in_fixes and (role == "wrap-up"
                                                 or role in DOC_GATES)) \
                or (role == "wrap-up" and row.get("kind") == "fixes"):
            out.add("fixes", row, True)
        elif phase is not None and role in ("code-writer", "code-reviewer"):
            name = "code" if role == "code-writer" else "review"
            code = step_code(name, round_, phase)
            current[phase] = code
            if name == "review":
                last_review[phase] = code
            out.add(code, row, phase_ahead(phase, round_))
        elif phase is not None and role in ("gate", "test-fixer"):
            code = current.get(phase) or step_code("code", 1, phase)
            out.add(code, row, phase_ahead(phase, split_code(code)[2]))
        elif phase is not None and role == "consult":
            code = current.get(phase)
            if code is None or split_code(code)[1] != "review":
                code = last_review.get(phase) or step_code("review", 1, phase)
            out.add(code, row, phase_ahead(phase, split_code(code)[2]))
        elif role == "sweep":
            check = step_code("sweep", round_)
            out.add(check, row, round_ == 1)
        elif role == "test-fixer":
            # A flake's fixer runs after the consult's answer, inside its
            # step; a sweep spawns no session of its own.
            code = check if check is not None \
                and split_code(check)[1] == "consult" else step_code(
                    "consult", max(completions, 1))
            out.add(code, row, split_code(code)[2] == 1)
        elif role == "consult":
            # A session-limit wait is no answer: the redispatch keeps the step.
            n = completions + 1
            if row.get("outcome") != "session_limit":
                completions = n
            check = step_code("consult", n)
            out.add(check, row, n == 1)
        elif role == "test-agent":
            out.add(step_code("test", round_), row, round_ == 1)
        elif role == "doc-writer":
            out.add("wrap-up" if wrapped else "docs", row, True)
        elif role == "wrap-up":
            wrapped = True
            out.add("wrap-up", row, True)
        elif role == "doc-gate":
            out.add("wrap-up" if has_wrap_up else "docs", row, True)
        elif role == "wrap-up-gate":
            out.add("wrap-up", row, True)
    return out.steps


def plan_steps(state: dict) -> dict[str, dict]:
    """The plan loop's steps from its history: a writer's round its `write`
    step, a reviewer's its `review`."""
    out = _Steps()
    for row in _rows(state):
        name = {"plan-writer": "write", "plan-reviewer": "review"}.get(
            row.get("role"))
        if name is not None:
            round_ = _round(row)
            out.add(step_code(name, round_), row, round_ == 1)
    return out.steps


def make_key(spec: str, slice_name: str, loop: str, code: str) -> str:
    """The timing's key, at most KEY_MAX characters: one longer is cut and
    ends in a hash of the whole, so it stays unique."""
    key = f"{spec}/{slice_name}/{loop}/{code}"
    if len(key) <= KEY_MAX:
        return key
    digest = hashlib.sha1(key.encode()).hexdigest()[:12]
    return f"{key[:KEY_MAX - len(digest) - 1]}~{digest}"


def timings_of(steps: dict[str, dict], loop: str, spec: str,
               slice_name: str) -> list[dict]:
    """The timings of a state file's steps: one per step with a positive
    duration, an end time and a kind."""
    out = []
    for code, step in steps.items():
        duration = min(int(step["seconds"]), pilot_progress.DURATION_MAX)
        kind = kind_of(code, loop)
        if duration <= 0 or step["ended"] is None or kind is None:
            continue
        out.append({"key": make_key(spec, slice_name, loop, code),
                    "kind": kind, "ended_at": step["ended"].isoformat(),
                    "duration": duration, "listed_ahead": step["ahead"]})
    return out


class Collected:
    def __init__(self) -> None:
        self.timings: list[dict] = []
        self.slices = 0
        self.files = 0
        self.live = 0
        self.unreadable = 0


def collect(spec_repo: Path, warn: Callable[[str], None]) -> Collected:
    """Every timing the spec repo's completed slices give, in slice order,
    the plan's before the run's."""
    got = Collected()
    spec = spec_repo.resolve().name
    completed = spec_repo / "slices" / "completed"
    folders = sorted(p for p in completed.iterdir() if p.is_dir()) \
        if completed.is_dir() else []
    for folder in folders:
        found = False
        for name, loop in sorted(STATE_FILES, key=lambda f: f[1] != PLAN):
            path = folder / name
            if not path.exists():
                continue
            found = True
            got.files += 1
            try:
                state = read_state(path)
            except Unreadable as e:
                got.unreadable += 1
                warn(f"seed_timings: {folder.name}/{name} skipped: {e}")
                continue
            if published_live(state):
                got.live += 1
                continue
            steps = run_steps(state) if loop == RUN else plan_steps(state)
            got.timings += timings_of(steps, loop, spec, folder.name)
        got.slices += found
    return got


# -- sending -------------------------------------------------------------------

def batches(timings: list[dict], size: int = pilot_progress.SEED_MAX):
    return [timings[i:i + size] for i in range(0, len(timings), size)]


def _kinds(timings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in timings:
        counts[t["kind"]] = counts.get(t["kind"], 0) + 1
    return dict(sorted(counts.items()))


def _summary(got: Collected, sent: int | None, written: int | None) -> dict:
    return {"slices": got.slices, "state_files": got.files,
            "skipped_live": got.live, "unreadable": got.unreadable,
            "timings": len(got.timings), "kinds": _kinds(got.timings),
            "sent": sent, "written": written}


def _line(summary: dict) -> str:
    kinds = ", ".join(f"{k} {n}" for k, n in summary["kinds"].items())
    line = (f"slices read {summary['slices']} ({summary['state_files']} state "
            f"files), skipped {summary['skipped_live']} published live and "
            f"{summary['unreadable']} unreadable; timings "
            f"{summary['timings']}" + (f" ({kinds})" if kinds else ""))
    if summary["sent"] is None:
        return line + "; dry run, nothing sent"
    written = summary["written"]
    return (line + f"; sent {summary['sent']}, Pilot wrote "
            + ("an unknown number" if written is None else str(written)))


def _report(summary: dict, as_json: bool, out) -> None:
    print(json.dumps(summary) if as_json else _line(summary), file=out)


def main(argv: list[str] | None = None, environ=None,
         opener: Callable | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed Pilot's step timings with the repo's slices run "
                    "before their steps were timed.")
    parser.add_argument("repo_root", nargs="?", type=Path, default=Path.cwd(),
                        help="the project repo (default: the working directory)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the timings as JSON lines; send nothing")
    parser.add_argument("--json", action="store_true",
                        help="the summary as one JSON object")
    args = parser.parse_args(argv)

    def fail(line: str, code: int) -> int:
        print(f"seed_timings: {line}", file=sys.stderr)
        return code

    try:
        cfg = project_config.load(args.repo_root)
    except project_config.ConfigError as e:
        return fail(str(e), 2)
    if cfg.spec_repo is None:
        return fail(f"{args.repo_root}'s .aiworkflowrc names no spec_repo", 2)
    if not cfg.spec_repo.is_dir():
        return fail(f"the spec repo {cfg.spec_repo} is not there", 2)

    got = collect(cfg.spec_repo, lambda line: print(line, file=sys.stderr))
    if args.dry_run:
        for timing in got.timings:
            print(json.dumps(timing))
        _report(_summary(got, None, None), args.json, sys.stderr)
        return 0
    if not got.timings:
        _report(_summary(got, 0, 0), args.json, sys.stdout)
        return 0

    url, token = pilot_progress.credentials(environ)
    if not url or not token:
        return fail("no Pilot to send to: PILOT_MCP_URL and PILOT_TOKEN are "
                    "not both set (a Pilot work item's session has them; "
                    "--dry-run needs neither)", 2)
    listed = pilot_progress.discover(url, token, opener,
                                     timeout=pilot_progress.SEED_TIMEOUT)
    if listed.kind != pilot_progress.OK:
        return fail(f"Pilot's tools could not be listed ({listed.kind}): "
                    f"{listed.reason}", 1)
    if not listed.takes.seed:
        return fail(f"this Pilot does not list {pilot_progress.SEED_TOOL}; "
                    "nothing sent", 2)

    sent, written = 0, 0
    for batch in batches(got.timings):
        answer = pilot_progress.seed_step_timings(batch, url, token, opener)
        if answer.kind != pilot_progress.OK:
            _report(_summary(got, sent, written), args.json, sys.stdout)
            word = "refused" if answer.kind == pilot_progress.REFUSED \
                else "gave no answer to"
            return fail(f"Pilot {word} timings {sent + 1}-{sent + len(batch)} "
                        f"of {len(got.timings)}: {answer.reason}", 1)
        sent += len(batch)
        written = None if written is None or answer.timings is None \
            else written + answer.timings
    _report(_summary(got, sent, written), args.json, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
