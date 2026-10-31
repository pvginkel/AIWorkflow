#!/usr/bin/env python3
"""Plan loop — the single structural write→review round behind /dev:plan-slice.

The plan-slice stage settles the slice's requirements and its plan-preparer
seeds plan.md's header sections; this script owns the mechanical half: a fresh plan-writer
pass completes the plan (phases with `Target:` lines, attachments only where
the executor genuinely cannot derive the design, verification.json's
outcome-level acceptance criteria), then a fresh plan-reviewer pass judges
it — structurally, in ONE round. The review is not optional: exit 0 is
refused without a reviewer verdict on file, and it is the only place
anything checks the plan against slice.md; nobody downstream reads slice.md
again.

There is no review loop. A `go` verdict completes the plan. Anything else —
blocking findings or questions only the operator can rule — exits 4 with a
document: the role's hand-back (plan_questions_rN.json, plan_review_rN.json)
rendered through asks.py into the slice's asks/, one ask per question or
finding, for the session to register with Pilot (docs/pilot.md). The
answers go into plan.md's rulings section; the rerun resumes the paused
pass, and after a review it always dispatches ONE writer fix pass, which
resolves every finding the rulings do not overrule. No review follows it.

  exit 0 — plan complete: a reviewer verdict is on file and the plan parses
           as run_loop.py's phase queue.
  exit 4 — operator input needed: the writer's questions, or the review's
           findings, as the document named on stdout and in plan_state.json's
           `exit`. Answer it, rerun — the loop continues where it paused.
  exit 3 — bailed (plan_bailout.json): an agent reported blocked, or a
           protocol failure.

The loop never resumes an agent session but to nudge it: every pass is a
fresh context reading its inputs from the slice folder (slice.md, plan.md,
the review). Rulings reach agents through plan.md only — dispatch prompts
carry pointers, not relayed content. State persists in
<slice>/plan_state.json across invocations, the last exit as its `exit`.

One loop plans a slice at a time: it holds <slice>/plan.lock for the run,
the lock's note naming its KubeCoder environment, host and pid with a
heartbeat (run_loop's SliceLock), and plan_state.json's `driver` recording
the same for `status`. A second plan loop — or one started while the
slice's run loop holds run.lock — is refused with exit 2, naming the holder.

The loop is the first to run on a slice, so it creates and commits the
slice's close-out report (<slice>/close-out.json, the store — the
close-out.md and close-out-record.md rendered from it are docs/close-out.md's)
before its first dispatch. At exit 0 it seeds that report's actions from the plan: one entry
per `## Push holds` repo, listing the criteria verification.json marks
`owed_after` that push, and one per criterion owed after anything else —
each entered once, however often the loop reruns. It renders nothing: the
report is the run's to render, and registering it the run's continuation.

All loop and session output goes to <slice>/plan_log.txt; stdout carries the
log-file line plus one terse timestamped line per pass start and the final
verdict; -v/--verbose echoes the full log there too.

`run --detach` takes the loop out of the launching shell, as the run loop's
does, and `wait` is what the stage's session waits on inside its turn: a
foreground call under the Bash tool's ten minutes that answers with a
signal, never a report (docs/pilot.md § A turn's end is the run's end).

Pilot's halt file (run_loop.HALT_FILE) is looked for before every pass:
present, the loop exits 7 with plan_state.json current, and the rerun once
it is gone takes the next pass; present at the start, nothing runs. `stop`
interrupts a running loop as Ctrl-C does.

Usage:
    plan_loop.py run <slice-dir> [--step ID] [--detach] [--verbose]
    plan_loop.py wait <slice-dir> [--for SECONDS]
    plan_loop.py stop <slice-dir>
    plan_loop.py status <slice-dir>

Exit codes: 0 plan complete · 4 operator input needed · 3 bailed
(plan_bailout.json written) · 7 halted · 2 usage/precondition error ·
130 interrupted · 1 unexpected error. `run --detach` exits 0 once the loop
started, else with its refusal's code. Of wait: 0 the loop ended (its code
in the output) · 5 still running at --for · 6 gone, no exit record · 2
nothing to wait on. Of stop: 0 stopped · 1 no loop running, or still
running after the wait · 2 the loop is on another host.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The loop is kc-native and shares the run loop's seams rather than carrying
# twins: run_kc_session is the one kc dispatch helper, parse_plan the one
# plan-shape authority, and the target repo's root comes from `git rev-parse
# --show-toplevel` in the process cwd — not from `__file__`, which locates the
# plugin these tools ship in, never the repo being planned.
import asks  # noqa: E402
import github_target  # noqa: E402
import project_config  # noqa: E402
import run_loop  # noqa: E402
from close_out import (  # noqa: E402
    ReportError,
    append_entry,
    dispatch_line,
    find_by_headline,
    init_report,
    report_path,
    store_path,
)
from run_loop import (  # noqa: E402
    AGENTS_DIR,
    EXIT_HALTED,
    PHILOSOPHY_LINE,
    SPAWN_ENV,
    WAIT_DEFAULT,
    Halted,
    SliceLock,
    _exit_status,
    _git_toplevel,
    _now_hms,
    _now_iso,
    _orchestrator_record,
    _protocol_failure_detail,
    _read_json,
    _transcript_path,
    assert_plugin_current,
    assert_verification_keys,
    driver_line,
    holder_note,
    lock_held,
    parse_plan,
    parse_push_holds,
    plugin_version,
    render_asks_document,
    resolve_skills,
    run_kc_session,
    skill_line,
    skills_named,
    spawn_flags,
    stop_driver,
    wait_on_driver,
)

SCRIPT = Path(__file__).resolve()

TIMEOUTS = {"plan-writer": 7200, "plan-reviewer": 3600}
NUDGE_TIMEOUT = 900

# Model/effort per role, passed explicitly on every dispatch (sub-agents
# inherit from the dispatching session).
MODELS: dict[str, tuple[str, str | None]] = {
    "plan-writer": ("opus", "xhigh"),
    "plan-reviewer": ("opus", "xhigh"),
}

VERDICTS = {
    "plan-writer": {"done", "questions", "blocked"},
    "plan-reviewer": {"go", "issues", "questions"},
}

# The passes Pilot's halt stops the loop before, by the state's `phase`.
HALT_PASSES = {
    "writing": "plan-writer pass",
    "fixing": "plan-writer fix pass",
    "reviewing": "plan-reviewer pass",
}

# Files the loop itself writes into the slice folder. They are working state,
# not slice artifacts, so they are excluded from every cleanliness check: the
# loop must not read its own output as an agent leaving work uncommitted.
LOOP_OWNED_FILES = frozenset({
    "plan_log.txt",       # loop + session output, appended across runs
    "plan_state.json",    # loop-owned state; survives so a rerun can resume
    "plan_bailout.json",  # bail record, rewritten each run
    "plan.lock",          # the loop's lock; its note names the live holder
})
# The report the loop renders from its store at every exit, and commits only
# where it commits the store: left modified by an exit that commits nothing,
# it is the loop's own output, not an agent's work left uncommitted, so the
# cleanliness checks pass it by as they pass the files above. The store
# itself is an agent's commit and stays checked.
RENDERED_FILES = frozenset({"close-out.md", "close-out-record.md"})

# The kind the exit-0 seed enters, by its old section name, and the widths it
# shortens to: a headline (a free-text `owed_after` can run long) and a
# criterion quoted in a hold's entry.
OUTSTANDING = "Outstanding actions"
SEED_HEADLINE_WIDTH = 90
SEED_CRITERION_WIDTH = 100

# A slice folder's name — its number, then its slug (`NNN_slug`).
SLICE_FOLDER_RE = re.compile(r"^\d{3,}_")

# The findings of a review that come to the operator, by the class the
# reviewer gives each in plan_review_rN.json; an advisory note stays in the
# prose review.
FINDING_CLASSES = ("blocking", "operator")


def _target_key(target: str) -> str:
    """A hold target or an `owed_after` as the seed compares them — the
    backticks and trailing slash a hand-written one may carry set aside."""
    return target.strip().strip("`").strip().rstrip("/")


class Bailout(Exception):
    def __init__(self, reason: str, details: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.details = details


# ---------------------------------------------------------------------------
# The hand-backs. A `questions` verdict's plan_questions_rN.json and an
# `issues` or `questions` review's plan_review_rN.json are what the loop puts
# to the operator: each entry one ask of the exit's document.
# ---------------------------------------------------------------------------

_HANDBACK = {
    "plan-writer": ("questions", {"headline", "body", "options", "recommend",
                                  "proposal"}),
    "plan-reviewer": ("findings", {"class", "headline", "body", "options",
                                   "recommend", "proposal"}),
}


def read_handback(role: str, path: Path) -> tuple[list[dict], list[str]]:
    """(asks, faults) of a role's hand-back file. An entry is one ask: a
    decision where it gives `options` (with an optional `recommend`) or a
    `proposal`, a question otherwise. Of a review, a `blocking` finding must
    say its disposition, as a proposal or options, an `operator` one may
    leave the choice open, and an `advisory` one is left in the prose
    review. Every ask is checked as asks.py will render it, so a hand-back
    without faults is a document that renders."""
    key, fields = _HANDBACK[role]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], [f"{path.name} is not there"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return [], [f"{path.name} is no JSON: {e}"]
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], [f'{path.name} is no {{"{key}": [...]}}']
    found: list[str] = []
    out: list[dict] = []
    scratch = asks.new_store("a hand-back")
    for n, item in enumerate(items, 1):
        who = f"{key} {n}"
        if not isinstance(item, dict):
            found.append(f"{who} is no object")
            continue
        unknown = sorted(set(item) - fields)
        if unknown:
            found.append(f"{who}: no field {', '.join(unknown)}")
            continue
        if role == "plan-reviewer":
            cls = item.get("class")
            if cls == "advisory":
                continue
            if cls not in FINDING_CLASSES:
                found.append(f"{who}: `class` is blocking, operator or "
                             f"advisory, not {cls!r}")
                continue
            if cls == "blocking" and not (item.get("proposal")
                                          or item.get("options")):
                found.append(f"{who}: a blocking finding says its "
                             "disposition, as a `proposal` or `options`")
                continue
        block = {k: item[k] for k in ("options", "recommend", "proposal")
                 if item.get(k) not in (None, "", [])}
        kind = "decision" if ("options" in block or "proposal" in block) \
            else "question"
        try:
            asks.append(scratch, kind, item.get("headline"), item.get("body"),
                        **block)
        except (asks.AskError, AttributeError, TypeError) as e:
            found.append(f"{who}: {e}")
            continue
        out.append({"kind": kind, "headline": item["headline"],
                    "body": item["body"], **block})
    if not out and not found:
        found.append(f"{path.name} holds no {key[:-1]} that needs a ruling")
    return out, found


# ---------------------------------------------------------------------------
# Dispatch prompts. Role contracts live in the agent definitions; prompts
# carry only instance data — pointers into the slice folder, never relayed
# rulings or findings.
# ---------------------------------------------------------------------------

WRITER_INITIAL_PROMPT = """\
You are completing the plan for slice {slice_name}.
Slice folder: {slice_dir}

Read slice.md and plan.md there. plan.md's requirements/rulings section is
the operator's settled input — preserve it verbatim. Complete the plan per
your contract: the task-shape declaration (before you investigate), the
phases (each opening with its `Target:` line), ordering constraints,
not-in-scope, attachments/ only where an executor genuinely cannot derive
the design, and verification.json's outcome-level acceptance criteria.
{philosophy_line}{skill_line}{close_out_line}
Commit to the spec repo (stage by name), then write your verdict
to {verdict_path}. Questions only the operator can rule go to
{questions_path}, shaped as your hand-back section says, with verdict
`questions`.
"""

WRITER_FIX_PROMPT = """\
The operator has ruled on the plan-reviewer's findings on slice
{slice_name}'s plan. Slice folder: {slice_dir}

Read {review_path} and plan.md — the rulings recorded in plan.md supersede
the review where they speak. Apply every ruling the plan does not yet
reflect and resolve every blocking finding the rulings do not overrule —
the reviewer and the operator state problems; the fix design is yours. This
is the only fix pass: no review follows it.
{philosophy_line}{skill_line}{close_out_line}
Commit (stage by name), then write your verdict to {verdict_path}. A
finding the rulings leave genuinely unresolved goes to {questions_path},
shaped as your hand-back section says, with verdict `questions`.
"""

WRITER_RESUME_NOTE = """\
An earlier pass paused on the questions in {questions_file}; plan.md's
rulings section now holds the answers. Continue that pass with them applied.
"""

REVIEWER_PROMPT = """\
Review the plan for slice {slice_name} — the full plan, in your one and
only round: no fix-verify loop follows; your findings go to the operator.
Slice folder: {slice_dir}
{philosophy_line}{skill_line}{close_out_line}{other_holds_line}

Write your review to {review_path}, the findings that need a ruling to
{findings_path}, shaped as your output section says, and your verdict to
{verdict_path}.
"""

# The reviewer's alone: the push holds the other slices in flight declare
# (PlanLoop._other_holds_line), one row per hold.
OTHER_HOLDS_LINE = """\
Push holds of the other slices in flight (each plan's `## Push holds`) —
commits each keeps unpushed in that repo until the operator pushes it:
{rows}"""

VERDICT_NUDGE_PROMPT = """\
Your session ended without writing a valid verdict file. Do not start new
work: if any of your work is uncommitted, commit it, then write your verdict
now to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}; outcome
must be one of {outcomes}).
"""

# A `questions` or `issues` hand-back that cannot go to the operator as it
# stands: its faults, for the one nudge before the bail.
HANDBACK_NUDGE_PROMPT = """\
Your hand-back {path} cannot go to the operator as it stands:
{faults}
Do not start new work: rewrite that file as your contract's hand-back
section shapes it, commit it (stage by name), and end.
"""

COMMIT_NUDGE_PROMPT = """\
Your session ended leaving uncommitted changes in the slice folder. Commit
them now (stage by name — the spec repo is a shared working tree). Do not
start new work.
"""


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------

class PlanLoop:
    def __init__(self, slice_dir: Path, verbose: bool = False,
                 step: str | None = None):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.slice_num = self.slice_name.split("_")[0]
        self.plan_path = self.slice_dir / "plan.md"
        self.report_path = report_path(self.slice_dir)
        self.state_path = self.slice_dir / "plan_state.json"
        self.log_path = self.slice_dir / "plan_log.txt"
        self.verbose = verbose
        # Whether the log has said once that the version guard let a
        # --plugin-dir run's checkout pass (assert_plugin_current).
        self._checkout_logged = False
        # The plan task the planning serves, from the brief (`--step`):
        # every document the loop renders carries it; kept in
        # plan_state.json for the reruns that do not give it.
        self.step = (step or "").strip() or None
        # `run --detach`'s handshake: called once the loop is past its
        # refusals, so a refusal reaches the caller as an attached run's does.
        self.on_start = None
        # Whether this run read or wrote plan_state.json — what makes its
        # exit worth recording there (`_record_exit`).
        self._owns_state = False
        # What the exit record says beyond the code: the document an exit 4
        # rendered, a bail's reason, where a halt stopped.
        self._exit_facts: dict = {}
        # The last dispatched session, for a hand-back's nudge.
        self._session: str | None = None
        self.state: dict = {}
        self._log_file = None
        # Sessions spawn in the target repo, not the spec repo: the loop is
        # launched from it, and the agents read the code there.
        self.repo_root = _git_toplevel()
        self._philosophy: str | None = None
        # One plan loop per slice (`_take_plan_lock`), held for the run.
        self._plan_lock = SliceLock(self.slice_dir / "plan.lock")

    # -- state ---------------------------------------------------------------

    def _save_state(self) -> None:
        self.state["updated_at"] = _now_iso()
        tmp = self.state_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.state_path)

    def _record_exit(self, code: int) -> None:
        """The loop's exit, on disk as plan_state.json's `exit` — written
        last, whatever the exit: a detached loop's code reaches nobody else,
        and `wait` reads it. Nothing for a run refused before it owned the
        state, and nothing here may mask the exit."""
        if not self._owns_state:
            return
        self.state["exit"] = {"code": code, "ts": _now_iso(),
                              **self._exit_facts}
        try:
            self._save_state()
        except OSError as e:
            print(f"warning: the exit record was not written: {e}",
                  file=sys.stderr)

    def _record(self, role: str, round_: int, outcome: str, summary: str,
                session: str | None, duration_s: int) -> None:
        self.state["history"].append({
            "ts": _now_iso(), "role": role, "round": round_,
            "outcome": outcome, "summary": summary, "session": session,
            "transcript": _transcript_path(self.repo_root, session),
            "duration_s": duration_s,
        })
        self._save_state()

    def _emit(self, line: str) -> None:
        if self._log_file is None:
            self._log_file = open(self.log_path, "a", buffering=1)
        self._log_file.write(line + "\n")
        if self.verbose:
            print(line, flush=True)

    def log(self, msg: str) -> None:
        self._emit(f"[{_now_hms()}] {msg}")

    def announce(self, msg: str) -> None:
        """One terse timestamped stdout line per major transition — the
        caller's window into the loop. Job starts and landings only."""
        print(f"[{_now_hms()}] {msg}", flush=True)

    # -- git (spec repo, scoped to the slice folder) -------------------------

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.slice_dir), *args],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise Bailout(
                "protocol_failure",
                details=f"git {' '.join(args)} failed:\n{result.stderr.strip()}",
            )
        return result.stdout.strip()

    def _slice_dirty(self) -> bool:
        return bool(self._slice_dirty_paths())

    def _slice_dirty_paths(self) -> list[str]:
        """Changed paths under the slice dir, excluding the loop's own files.

        Uses -z so paths carrying spaces or quotes parse exactly; a rename or
        copy entry is followed by its origin path, which is consumed and
        ignored (the destination alone decides dirtiness).
        """
        raw = self.git("status", "--porcelain", "-z", "--", str(self.slice_dir))
        entries = [e for e in raw.split("\0") if e]
        dirty: list[str] = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            # "XY path": two status columns then a space, then the path.
            status, path = entry[:2], entry[3:]
            if status[0] in ("R", "C"):
                i += 1  # skip the origin path of a rename/copy
            if PurePosixPath(path).name not in LOOP_OWNED_FILES | RENDERED_FILES:
                dirty.append(path)
        return dirty

    def _spec_root(self) -> str:
        """The spec repo's root — asked only by the bails that name it."""
        return self.git("rev-parse", "--show-toplevel")

    def _current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD")

    def _base_branch(self) -> str:
        """The branch the spec repo was on when this loop first ran, recorded
        in plan_state.json. A `phase/` branch is never it: that one is a run
        loop's, left checked out where that run bailed, and planning onto it
        would commit this slice's plan into another slice's work."""
        if not self.state.get("base"):
            cur = self._current_branch()
            if cur.startswith("phase/"):
                raise Bailout(
                    "blocked",
                    details=f"the spec repo {self._spec_root()} is on {cur}, "
                            "a phase branch — a run loop's, left there when "
                            "it bailed; check out its base branch there and "
                            "rerun")
            self.state["base"] = cur
            self._save_state()
        return self.state["base"]

    def _assert_on_base(self) -> None:
        """The spec repo must still be on that branch before every dispatch
        and before the loop's own commit. The tree is shared with every
        parallel session — another plan loop, a run loop, the operator's own
        — so whichever branch it sits on is where this slice's plan,
        verification.json and close-out entries land. No loop moves it (a
        run loop's phase on it works in a worktree of its own), so a tree off
        its base is a hand checkout, or a run loop of a plugin before 0.9.93,
        which still branched it in place."""
        base = self._base_branch()
        cur = self._current_branch()
        if cur != base:
            raise Bailout(
                "blocked",
                details=f"the spec repo {self._spec_root()} is on {cur}, not "
                        f"{base} — a hand checkout, or a run loop of a plugin "
                        "before 0.9.93, left it there; check out "
                        f"{base} there and rerun")

    def _assert_current(self, plugin: bool = True) -> None:
        """The run loop's guards, in this loop's bail vocabulary: the
        installed plugin — the one the agent about to run loads — is this
        loop's, and verification.json holds no key this loop would ignore.
        Before the run, before every dispatch, and (keys only) before the
        exit-0 seed reads the file."""
        try:
            if plugin:
                said = assert_plugin_current(
                    Path(__file__).name,
                    " (a plan loop rerun resumes from plan_state.json on its "
                    "own)")
                if said and not self._checkout_logged:
                    self._checkout_logged = True
                    self.log(f"[plugin] {said}")
            assert_verification_keys(self.slice_dir)
        except run_loop.Bailout as e:
            raise Bailout(e.reason, details=e.details) from None

    # -- session spawning ----------------------------------------------------

    def _nudge(self, prompt: str, session_id: str, label: str,
               role: str) -> None:
        self.log(f"{label} nudging the session (resume)")
        try:
            self._assert_current()
            run_kc_session(
                prompt=prompt, cwd=str(self.repo_root),
                timeout=NUDGE_TIMEOUT, resume_session=session_id,
                extra_env=SPAWN_ENV, flags=spawn_flags(role, self.log),
                progress=lambda line: self._emit(f"    {label} {line}"),
            )
        except subprocess.TimeoutExpired:
            self.log(f"{label} nudge timed out")

    def _philosophy_line(self) -> str:
        """The project's change-discipline pointer, carried by every
        dispatch the way the run loop's dispatches carry it (PHILOSOPHY_LINE)
        — the planners bind phases and criteria to the same rules execution
        is held to. The loop reads the config for nothing else, and
        preflight owns validating it, so a missing or broken config degrades
        to no line rather than a dead planning loop."""
        if self._philosophy is None:
            try:
                doc = project_config.load(self.repo_root).design_philosophy
            except project_config.ConfigError:
                doc = None
            self._philosophy = (
                PHILOSOPHY_LINE.format(philosophy=doc) if doc else "")
        return self._philosophy

    def _skill_line(self, label: str) -> str:
        """The skills slice.md and plan.md name, resolved to their installed
        files (SKILL_LINE, the run loop's) — the planners see no skill
        listing either. Read at each dispatch: the writer may name one the
        reviewer then needs. This loop's close-out line carries no newline of
        its own, so a blank line closes the list before it."""
        text = ""
        for name in ("slice.md", "plan.md"):
            try:
                text += (self.slice_dir / name).read_text() + "\n"
            except OSError:
                pass
        skills = resolve_skills(text)
        if not skills:
            return ""
        self.log(f"{label} {skills_named(skills)}")
        return skill_line(skills, "this slice") + "\n"

    def _other_holds_line(self, label: str) -> str:
        """The push holds of every other slice in flight — pending
        (`slices/NNN_slug`) or being planned (`slices/backlog/NNN_slug`) —
        for the review. A scratch clone is one per repo, shared by every
        slice that targets it; another slice's held commits sit in it
        unpushed, so a plan that targets or holds that clone without an
        ordering constraint builds on them. The reviewer is the one check
        that sees this plan and the others together. A plan's malformed
        holds are its own loops' to report; this lists what parses. The
        close-out line carries no newline of its own, so a blank line opens
        the block."""
        slices = self.slice_dir.parent
        if slices.name == "backlog":
            slices = slices.parent
        folders: list[Path] = []
        for parent in (slices, slices / "backlog"):
            try:
                folders += [d for d in parent.iterdir()
                            if SLICE_FOLDER_RE.match(d.name) and d.is_dir()
                            and d != self.slice_dir]
            except OSError:
                pass
        rows: list[str] = []
        holders = 0
        for folder in sorted(folders,
                             key=lambda d: d.relative_to(slices).as_posix()):
            try:
                holds, _ = parse_push_holds((folder / "plan.md").read_text())
            except (OSError, UnicodeDecodeError):
                continue
            name = folder.relative_to(slices).as_posix()
            rows += [f"- {name}: {target} — {why}" for target, why in holds]
            holders += bool(holds)
        if not rows:
            return ""
        self.log(f"{label} other slices' push holds — {len(rows)} from "
                 f"{holders} slice(s)")
        return "\n\n" + OTHER_HOLDS_LINE.format(rows="\n".join(rows))

    def _spawn(self, role: str, prompt: str, verdict_path: Path,
               round_: int) -> dict:
        """Run one fresh session; return its validated verdict. A session
        failure, invalid verdict (after one nudge), or dirty slice folder
        (after one nudge) is a bail-out — the loop has no fallback driver.
        The spec tree is asserted on its base first: an agent dispatched onto
        someone else's branch commits the plan there."""
        label = f"[{role} r{round_}]"
        model, effort = MODELS[role]

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(self.repo_root, sid)}")

        t0 = time.monotonic()
        try:
            self._assert_on_base()
            self._assert_current()
            self.log(f"{label} session starting")
            verdict_path.unlink(missing_ok=True)
            returncode, result = run_kc_session(
                prompt=prompt, cwd=str(self.repo_root),
                timeout=TIMEOUTS[role], agent=role, model=model,
                effort=effort, extra_env=SPAWN_ENV,
                flags=spawn_flags(role, self.log),
                progress=lambda line: self._emit(f"    {label} {line}"),
                on_session=_note_session,
            )
        except subprocess.TimeoutExpired:
            raise Bailout("timeout",
                          details=f"{role} exceeded {TIMEOUTS[role]}s") from None
        duration_s = int(time.monotonic() - t0)
        session_id = result.session_id
        self._session = session_id

        def _valid(v: dict | None) -> bool:
            return v is not None and v.get("outcome") in VERDICTS[role]

        nudged = False
        verdict = _read_json(verdict_path)
        if not _valid(verdict) and session_id:
            self._nudge(
                VERDICT_NUDGE_PROMPT.format(
                    verdict_path=verdict_path,
                    outcomes=sorted(VERDICTS[role])),
                session_id, label, role)
            nudged = True
            verdict = _read_json(verdict_path)
            if _valid(verdict):
                returncode = 0
        if returncode != 0 or not _valid(verdict):
            raise Bailout(
                "protocol_failure",
                details=_protocol_failure_detail(
                    role, returncode, verdict, verdict_path.name,
                    _valid(verdict), nudged),
            )

        if self._slice_dirty():
            if session_id:
                self._nudge(COMMIT_NUDGE_PROMPT, session_id, label, role)
            dirty = self._slice_dirty_paths()
            if dirty:
                raise Bailout(
                    "protocol_failure",
                    details=f"{role} left the slice folder uncommitted"
                            + (" after a commit nudge" if session_id else "")
                            + ": " + ", ".join(dirty),
                )

        outcome = verdict["outcome"]
        self.log(f"{label} → {outcome}: {verdict.get('summary', '')[:160]}")
        self._record(role, round_, outcome, verdict.get("summary", ""),
                     session_id, duration_s)
        return verdict

    # -- passes --------------------------------------------------------------

    def _writer_paths(self) -> tuple[int, Path, Path]:
        self.state["writer_rounds"] += 1
        w = self.state["writer_rounds"]
        self._save_state()
        return (w, self.slice_dir / f"plan_writer_result_r{w}.json",
                self.slice_dir / f"plan_questions_r{w}.json")

    def _writer_pass(self, initial: bool) -> None:
        w, verdict_path, questions_path = self._writer_paths()
        if initial:
            prompt = WRITER_INITIAL_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                philosophy_line=self._philosophy_line(),
                skill_line=self._skill_line(f"[plan-writer r{w}]"),
                close_out_line=dispatch_line(self.report_path),
                verdict_path=verdict_path, questions_path=questions_path)
        else:
            review_path = (self.slice_dir /
                           f"plan_review_r{self.state['pending_review']}.md")
            prompt = WRITER_FIX_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                philosophy_line=self._philosophy_line(),
                skill_line=self._skill_line(f"[plan-writer r{w}]"),
                close_out_line=dispatch_line(self.report_path),
                review_path=review_path, verdict_path=verdict_path,
                questions_path=questions_path)
        if self.state.get("pending_questions"):
            prompt += "\n" + WRITER_RESUME_NOTE.format(
                questions_file=self.state["pending_questions"])

        self.announce(f"plan-writer r{w}"
                      + ("" if initial else " (fix pass)"))
        verdict = self._spawn("plan-writer", prompt, verdict_path, w)
        if verdict["outcome"] == "questions":
            entries = self._handback("plan-writer", questions_path, w)
            self.state.update(pending_questions=str(questions_path),
                              phase="questions")
            self._save_state()
            self._exit_questions(entries, w, initial)
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", details=verdict.get("summary", ""))
        # The initial pass goes to its one review; the fix pass completes
        # the plan — no confirming review, the operator's read follows.
        self.state.update(pending_questions=None,
                          phase="reviewing" if initial else "done")
        self._save_state()

    def _review_round(self) -> None:
        self.state["review_rounds"] += 1
        r = self.state["review_rounds"]
        self._save_state()
        review_path = self.slice_dir / f"plan_review_r{r}.md"
        findings_path = self.slice_dir / f"plan_review_r{r}.json"
        verdict_path = self.slice_dir / f"plan_review_result_r{r}.json"
        prompt = REVIEWER_PROMPT.format(
            slice_name=self.slice_name, slice_dir=self.slice_dir,
            philosophy_line=self._philosophy_line(),
            skill_line=self._skill_line(f"[plan-reviewer r{r}]"),
            close_out_line=dispatch_line(self.report_path),
            other_holds_line=self._other_holds_line(f"[plan-reviewer r{r}]"),
            review_path=review_path, findings_path=findings_path,
            verdict_path=verdict_path)

        self.announce(f"plan-reviewer r{r}")
        verdict = self._spawn("plan-reviewer", prompt, verdict_path, r)
        if verdict["outcome"] == "go":
            self.state.update(pending_review=r, phase="done")
            self._save_state()
            return
        # issues / questions: both are the operator's, as one document of
        # the findings that need a ruling; there is no fix-verify loop.
        entries = self._handback("plan-reviewer", findings_path, r)
        self.state.update(pending_review=r, phase="adjudicating")
        self._save_state()
        self._exit_adjudication(entries, r)

    # -- the hand-backs: what goes to the operator ---------------------------

    def _handback(self, role: str, path: Path, round_: int) -> list[dict]:
        """The asks a `questions` or `issues` verdict's hand-back file puts,
        each checked as asks.py will render it. A file with faults gets one
        nudge to the session that wrote it, then a bail: an ask the operator
        cannot be shown is a stop nobody can answer."""
        label = f"[{role} r{round_}]"
        entries, faults = read_handback(role, path)
        nudged = False
        if faults and self._session:
            self.log(f"{label} hand-back {path.name}: {len(faults)} fault(s)")
            self._nudge(HANDBACK_NUDGE_PROMPT.format(
                path=path, faults="\n".join(f"- {f}" for f in faults)),
                self._session, label, role)
            nudged = True
            dirty = self._slice_dirty_paths()
            if dirty:
                raise Bailout(
                    "protocol_failure",
                    details=f"{role} left the slice folder uncommitted after "
                            "its hand-back nudge: " + ", ".join(dirty))
            entries, faults = read_handback(role, path)
        if faults:
            raise Bailout(
                "protocol_failure",
                details=f"{role}'s hand-back {path.name} cannot go to the "
                        "operator" + (" after a nudge" if nudged else "")
                        + ":\n" + "\n".join(f"- {f}" for f in faults))
        return entries

    # -- the exit-0 gate -----------------------------------------------------

    def _verify_review_on_file(self) -> None:
        """Exit 0 is refused without a reviewer verdict on file: the review
        is the only check of the plan against slice.md. The exit-0 path
        re-reads the verdict from disk rather than trusting its own state."""
        r = self.state.get("pending_review") or self.state["review_rounds"]
        verdict = _read_json(
            self.slice_dir / f"plan_review_result_r{r}.json")
        if not verdict or verdict.get("outcome") not in \
                VERDICTS["plan-reviewer"]:
            raise Bailout(
                "protocol_failure",
                details=f"phase is done but plan_review_result_r{r}.json "
                        "does not hold a reviewer verdict — exit 0 is "
                        "refused without the review on file")

    def _verify_plan_parses(self) -> None:
        """The GO'd plan must be the queue run_loop.py can drive."""
        try:
            text = self.plan_path.read_text()
        except OSError as e:
            raise Bailout("plan_doc",
                          details=f"plan.md unreadable at GO: {e}") from None
        phases, errors = parse_plan(text)
        if errors:
            raise Bailout(
                "plan_doc",
                details="the GO'd plan does not parse as a phase queue:\n"
                        + "\n".join(f"- {e}" for e in errors))
        if not phases:
            raise Bailout("plan_doc",
                          details="the GO'd plan contains no "
                                  "`### P<id> — <title>` phases")
        self._verify_environment(phases, text)

    def _verify_environment(self, phases: list, text: str) -> None:
        """The GO'd plan's Target repos must not call a tool container this
        pod does not run, nor the host declare a service it does not run
        (another Target repo's are logged) (`run_loop.tools_check` and
        `run_loop.services_check`, the run
        loop's own startup checks) — asked now, while the slice is with the
        operator, rather than when the run loop starts it. A Target maps to
        its repo as `_held_repo_name` maps it, without kc; a GitHub target
        not cloned yet is skipped (the run loop checks its clone)."""
        roots = [root for phase in phases
                 if not phase.done and phase.target
                 and (root := self._target_root(phase.target)) is not None]
        rulings, _ = run_loop.parse_rulings(text)
        resolved = []
        for ruling in rulings:
            root = self._target_root(ruling.target)
            if root is not None:
                kind = ("sibling" if run_loop.is_repo_path(ruling.target)
                        else "project")
                resolved.append((ruling, run_loop.ResolvedTarget(
                    ruling.target, kind, root, None, root)))
        relaunch = "rerun the plan loop once the environment runs them"
        details = run_loop.tools_check(roots, resolved, self.repo_root,
                                       self.log, relaunch=relaunch)
        if details:
            raise Bailout("missing_tools", details=details)
        details = run_loop.services_check(roots, resolved, self.repo_root,
                                          self.log, relaunch=relaunch)
        if details:
            raise Bailout("missing_services", details=details)

    def _target_root(self, target: str) -> Path | None:
        """The repo a Target lands in, as `_held_repo_name` reads it — None
        for a GitHub target whose clone is not on disk."""
        if github_target.is_github(target):
            try:
                path = github_target.clone_path(target)
            except ValueError:
                return None
            return path if path.is_dir() else None
        if target.startswith("/"):
            return Path(target)
        if target.startswith("../"):
            return (self.repo_root / target).resolve()
        return self.repo_root

    # -- terminal exits ------------------------------------------------------

    def _exit_questions(self, entries: list[dict], round_: int,
                        initial: bool) -> None:
        pass_ = "pass" if initial else "fix pass"
        self._exit_with_document(
            "plan-questions", "the plan-writer's questions", entries,
            [f"The plan-writer's {pass_} r{round_} on slice "
             f"{self.slice_num}'s plan stopped on what only you can rule. "
             "Your answers go into plan.md's rulings section in your words, "
             "and the plan loop resumes the pass with them."],
            "questions", f"QUESTIONS PENDING (plan-writer r{round_})")

    def _exit_adjudication(self, entries: list[dict], round_: int) -> None:
        self._exit_with_document(
            "plan-review", "the plan review's findings", entries,
            [f"The plan-reviewer read slice {self.slice_num}'s plan once and "
             "found what the plan cannot go on without your ruling. Your "
             "answers go into plan.md's rulings section in your words. Then "
             "one writer fix pass resolves every finding you did not "
             "overrule, and no review follows it. The full review, with its "
             f"evidence and any advisory notes, is plan_review_r{round_}.md."],
            "review", f"REVIEW PENDING RULINGS (plan-reviewer r{round_})")

    def _exit_with_document(self, slug: str, what: str, entries: list[dict],
                            context: list[str], reason: str,
                            headline: str) -> None:
        """Exit 4 with the asks as a document in the slice's asks/, for the
        session to register with Pilot (docs/pilot.md § The documents): its
        path on stdout and in the exit record. Nothing is committed — the
        session commits what it registers. A document that cannot be written
        is logged, and the exit stands without it."""
        document = None
        try:
            document = str(render_asks_document(
                self.slice_dir, slug, f"Slice {self.slice_num}: {what}",
                self.state.get("step"),
                f"Slice {self.slice_num}'s plan waits on {len(entries)} "
                "rulings before the plan loop can go on",
                context, entries))
        except (asks.AskError, OSError) as e:
            self.log(f"{headline}: the document was not written: {e}")
        self._exit_facts = {"reason": reason, "document": document}
        self.log(f"{headline} — {document or 'no document'}")
        if document:
            print(f"document: {document}", flush=True)
        print(f"{headline} — register the document; its answers go into "
              "plan.md's rulings section, then rerun.", file=sys.stderr)
        sys.exit(4)

    def _bail(self, bail: Bailout) -> None:
        self._exit_facts = {"reason": bail.reason}
        payload = {"reason": bail.reason, "details": bail.details,
                   "ts": _now_iso()}
        with open(self.slice_dir / "plan_bailout.json", "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        self.log(f"BAIL-OUT ({bail.reason}): {bail.details[:300]}")
        print(f"BAIL-OUT ({bail.reason}) — see "
              f"{self.slice_dir / 'plan_bailout.json'}", file=sys.stderr)
        sys.exit(3)

    # -- top level -----------------------------------------------------------

    def _assert_agents(self) -> None:
        """kc's --agent does not validate names; assert the two roles resolve
        before dispatching anything."""
        missing = [role for role in ("plan-writer", "plan-reviewer")
                   if not (AGENTS_DIR / f"{role}.md").is_file()]
        if missing:
            print("Error: agent definition(s) not found: "
                  + ", ".join(missing)
                  + f" (searched {AGENTS_DIR}) — reinstall the dev plugin",
                  file=sys.stderr)
            sys.exit(2)

    def _has_phases(self) -> bool:
        """A plan that already parses with phases (a reset re-plan) enters at
        review; a seeded header-only plan enters at writing."""
        try:
            phases, errors = parse_plan(self.plan_path.read_text())
        except OSError:
            return False
        return bool(phases) and not errors

    def _init_state(self) -> None:
        self.state = _read_json(self.state_path) or {}
        if not self.state:
            self.state = {
                "slice": self.slice_name,
                "created_at": _now_iso(),
                "plugin_version": plugin_version(),
                "orchestrator": _orchestrator_record(),
                "phase": "reviewing" if self._has_phases() else "writing",
                "base": None,
                "writer_rounds": 0,
                "review_rounds": 0,
                "pending_review": None,
                "pending_questions": None,
                "history": [],
            }
        # This run's driver, over whichever run recorded itself last; the
        # last run's exit cleared, so a `wait` under this run never reads it
        # as this one's end; the plan task kept for the reruns without one.
        self.state["driver"] = dict(self._plan_lock.driver)
        self.state.pop("exit", None)
        if self.step:
            self.state["step"] = self.step
        self._owns_state = True
        self._save_state()

    def _ensure_report(self) -> None:
        """The slice's close-out report exists before the first dispatch —
        its store created and committed by the loop (by name; the spec repo
        is a shared tree). A rerun finds the store and leaves it be. Runs
        under the bail handler: a git or store failure is a bail
        (plan_bailout.json), never a traceback. This is where the loop
        records its base branch — before the store is written, so a report
        created onto the wrong branch and bailed on cannot be found (and
        skipped) by the rerun."""
        self._assert_on_base()
        store = store_path(self.slice_dir)
        try:
            created = init_report(self.slice_dir)
        except ReportError as e:
            raise Bailout("protocol_failure", details=str(e)) from None
        if created:
            self.git("add", str(store))
            self.git("commit", "-m",
                     f"slice {self.slice_num}: close-out report")
            self.log(f"created {store.name}")

    # -- the exit-0 seed: the actions the plan already owes ---------------------

    def _held_repo_name(self, target: str) -> str:
        """The held repo's directory name as the run loop's push check names
        it (`root.name` of `_resolve_target(target).git_root`): a sibling
        path's own, resolved against the code repo; a GitHub target's clone's
        (the path alone — nothing is cloned here); a component's, the code
        repo's. The seeded headline is then the one that check would write,
        so it finds this entry instead of adding its own."""
        if github_target.is_github(target):
            try:
                return github_target.clone_path(target).name
            except ValueError:
                return target
        if target.startswith("/"):
            return Path(target).name
        if target.startswith("../"):
            return (self.repo_root / target).resolve().name
        return self.repo_root.name

    def _criteria(self) -> list[dict]:
        """verification.json's items, as far as they read — the seed is a
        convenience at exit 0, not a second check of the file."""
        try:
            items = json.loads(
                (self.slice_dir / "verification.json").read_text()
            ).get("items", [])
        except (OSError, ValueError, AttributeError):
            return []
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _owed_entries(self) -> list[tuple[str, str, str, str, str]]:
        """(headline, body, consequence, provenance, proposal) per
        Outstanding action the plan owes the operator, as it stands at exit 0: one per `## Push
        holds` repo, naming the criteria verification.json marks `owed_after`
        that target; one per criterion whose `owed_after` names anything
        else — an operator action the run cannot take either."""
        try:
            holds, errors = parse_push_holds(self.plan_path.read_text())
        except OSError:
            holds, errors = [], []
        for error in errors:
            self.log(f"push holds: {error} — not seeded")
        owed: list[tuple[str, str, str]] = []   # (id, description, after)
        for item in self._criteria():
            after = item.get("owed_after")
            if isinstance(after, str) and after.strip():
                owed.append((str(item.get("id") or "?"),
                             " ".join(str(item.get("description") or "").split()),
                             " ".join(after.split())))

        def row(vid: str, desc: str) -> str:
            short = textwrap.shorten(desc, SEED_CRITERION_WIDTH,
                                     placeholder=" …")
            return f"- {vid} — {short}" if desc else f"- {vid}"

        entries: list[tuple[str, str, str, str, str]] = []
        for target, why in holds:
            name = self._held_repo_name(target)
            after = [o for o in owed if _target_key(o[2]) == _target_key(target)]
            body = f"`plan.md`'s `## Push holds` section holds `{target}`: {why}"
            consequence = (f"until you push it, nothing {name} deploys "
                           "carries the slice")
            provenance = "read — `plan.md`'s `## Push holds`"
            proposal = "Push it when the hold lifts."
            if after:
                ids = ", ".join(vid for vid, _, _ in after)
                body += (
                    "\n\nCriteria owed after that push — the run cannot "
                    "prove them, so they stay open until the push lands and "
                    "are settled after it:\n\n"
                    + "\n".join(row(vid, desc) for vid, desc, _ in after))
                consequence += (f", and {ids} "
                                + ("stays" if len(after) == 1 else "stay")
                                + " unproven")
                provenance += " and `verification.json`'s `owed_after`"
                proposal = ("Push it when the hold lifts, then say so: the "
                            f"session settles {ids} after the push.")
            entries.append((f"Push {name} by hand when its hold lifts", body,
                            consequence + ".",
                            provenance + ", seeded by the plan loop", proposal))

        held = {_target_key(target) for target, _ in holds}
        for vid, desc, after in owed:
            if _target_key(after) in held:
                continue
            entries.append((
                textwrap.shorten(f"Settle {vid} after {after}",
                                 SEED_HEADLINE_WIDTH, placeholder=" …"),
                (f"{vid} — {desc}\n\n" if desc else "")
                + f"`verification.json` marks {vid} owed after: {after}. "
                "The run cannot take that action; settle the criterion once "
                "it has happened.",
                f"{vid} stays unproven until then; the test phase does not "
                "settle it.",
                "read — `verification.json`'s `owed_after`, seeded by the "
                "plan loop",
                f"When that has happened, say so: the session settles {vid} "
                "in verification.json."))
        return entries

    def _seed_outstanding(self) -> None:
        """At exit 0, enter the actions the plan already owes into the
        close-out report, so the operator's runbook does not hang on
        a later role noticing them. A headline the section already carries,
        live or struck, is left be: the loop reruns after questions and
        adjudication, and a slice may be replanned. Appended entries are
        committed under the same branch check as `_ensure_report`;
        a report that refuses an entry is logged, never a failed plan."""
        entries = self._owed_entries()
        if not entries:
            return
        self._assert_on_base()
        seeded = 0
        for headline, body, consequence, provenance, proposal in entries:
            try:
                eid = find_by_headline(self.slice_dir, OUTSTANDING,
                                       headline)
                if eid is not None:
                    self.log(f"close-out {eid} already holds: {headline}")
                    continue
                eid = append_entry(self.slice_dir, OUTSTANDING, headline,
                                   body, consequence=consequence,
                                   provenance=provenance,
                                   proposal=proposal)
            except ReportError as e:
                self.log(f"close-out entry not written ({e}): {headline}")
                continue
            seeded += 1
            self.log(f"close-out {eid}: {headline}")
        if seeded:
            self.git("add", str(store_path(self.slice_dir)))
            self.git("commit", "-m",
                     f"slice {self.slice_num}: seed close-out "
                     "outstanding actions")

    def _take_plan_lock(self) -> None:
        """One plan loop on a slice, and none beside a live run of it —
        refused (exit 2) before the loop reads or writes anything, so a
        second loop is told about the first rather than about the first's
        uncommitted plan.md. The run loop's lock is only probed, never
        taken or created: the run is not this loop's to hold off."""
        holder = self._plan_lock.acquire()
        if holder is not None:
            print(f"Error: {self._plan_lock.lock_path} is held — another plan "
                  "loop is running this slice:\n"
                  + "\n".join(f"  {line}" for line in holder.splitlines())
                  + "\nTwo plan loops edit one plan.md and interleave one "
                    "plan_log.txt. `ps` sees only this pod's processes, so the "
                    "holder may be alive in another environment: wait for it, "
                    "or stop it in the environment its note names.",
                  file=sys.stderr)
            sys.exit(2)
        run_lock = self.slice_dir / "run.lock"
        if lock_held(run_lock):
            self._plan_lock.release()
            note = holder_note(run_lock) or "(no holder note)"
            print(f"Error: {run_lock} is held — a run loop is running this "
                  "slice:\n"
                  + "\n".join(f"  {line}" for line in note.splitlines())
                  + "\nRe-planning under a live run rewrites the queue it is "
                    "executing. Wait for the run to end, or stop it in the "
                    "environment its note names.",
                  file=sys.stderr)
            sys.exit(2)

    def run(self) -> None:
        if not (self.slice_dir / "slice.md").exists():
            print(f"Error: {self.slice_dir} has no slice.md", file=sys.stderr)
            sys.exit(2)
        if not self.plan_path.exists():
            print(f"Error: {self.plan_path} does not exist — the plan-slice "
                  "stage seeds it (requirements/rulings) before the loop "
                  "runs.", file=sys.stderr)
            sys.exit(2)
        self._take_plan_lock()
        # Let go at every exit — sys.exit's included, which passes through —
        # and the exit recorded before the lock goes, so a `wait` that sees
        # the lock free finds it.
        try:
            self._run()
        except BaseException as e:
            self._record_exit(_exit_status(e))
            raise
        finally:
            self._plan_lock.release()

    def _run(self) -> None:
        # Before anything is read or written: a halt at the start runs
        # nothing, and the start after it is the same command again.
        if run_loop.halt_requested():
            print(f"Halted: {run_loop.HALT_FILE} is present — Pilot's halt "
                  "holds, and the plan loop does not start. Rerun once the "
                  "file is gone.", file=sys.stderr)
            sys.exit(EXIT_HALTED)
        self._assert_agents()
        dirty = self._slice_dirty_paths()
        if dirty:
            print(f"Error: uncommitted changes under {self.slice_dir}; "
                  "commit (stage by name) before running the loop:",
                  file=sys.stderr)
            for path in dirty:
                print(f"  {path}", file=sys.stderr)
            sys.exit(2)
        self._init_state()
        (self.slice_dir / "plan_bailout.json").unlink(missing_ok=True)
        # The start point: every refusal is behind it, and plan_state.json
        # is on disk for the `wait` that follows a detached start at once.
        if self.on_start is not None:
            self.on_start()

        # A questions exit resumes into the pass that raised (or must absorb)
        # the questions, now answered in plan.md's rulings section. A review
        # exit resumes into the one fix pass, always: nothing of the plan
        # says whether the rulings' fixes are in it — recording the rulings
        # is required either way, and ordering/not-in-scope maintenance
        # follows from a reversed ruling — so inferring it silently shipped
        # unfixed plans, and nobody reads the plan after the loop to catch it.
        if self.state["phase"] == "questions":
            self.state["phase"] = ("fixing" if self.state["pending_review"]
                                   else "writing")
            self._save_state()
        elif self.state["phase"] == "adjudicating":
            self.log("dispatching the writer fix pass for the ruled review")
            self.state["phase"] = "fixing"
            self._save_state()

        try:
            self._assert_current()
            self._ensure_report()
            while True:
                phase = self.state["phase"]
                # Pilot's halt, between passes — the safe point: the
                # pass in flight finishes, and the rerun takes the next
                # one from `phase`, its round not yet drawn.
                if phase in HALT_PASSES and run_loop.halt_requested():
                    raise Halted(f"before the {HALT_PASSES[phase]}")
                if phase == "writing":
                    self._writer_pass(initial=True)
                elif phase == "fixing":
                    self._writer_pass(initial=False)
                elif phase == "reviewing":
                    self._review_round()
                elif phase == "done":
                    break
                else:
                    raise Bailout("protocol_failure",
                                  details=f"unknown phase {phase!r}")
            self._assert_current(plugin=False)
            self._verify_review_on_file()
            self._verify_plan_parses()
            self._seed_outstanding()
        except Bailout as bail:
            self._bail(bail)
        except KeyboardInterrupt:
            self.log("interrupted — plan_state.json is current; rerun to "
                     "continue")
            print("Interrupted — rerun to continue.", file=sys.stderr)
            sys.exit(130)
        except Halted as halt:
            self._exit_facts = {"halted": halt.where}
            self.log(f"HALTED {halt.where}: {run_loop.HALT_FILE} is "
                     "present — plan_state.json is current; rerun once "
                     "it is gone")
            print(f"Halted {halt.where}: {run_loop.HALT_FILE} is present "
                  "— rerun once it is gone.", file=sys.stderr)
            sys.exit(EXIT_HALTED)

        self.log(f"plan complete: {self.state['writer_rounds']} writer "
                 f"pass(es), review on file")
        self.announce(f"plan complete: {self.state['writer_rounds']} writer "
                      f"pass(es), review on file")
        sys.exit(0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
        sys.exit(2)
    loop = PlanLoop(slice_dir, verbose=args.verbose,
                    step=getattr(args, "step", None))
    print(f"plan loop log: {loop.log_path}", flush=True)
    if getattr(args, "detach", False):
        run_loop.run_detached(loop, slice_dir, script=SCRIPT)
        return
    loop.run()


def _ended_lines(record: dict, slice_dir: Path) -> list[str]:
    """What an ended loop leaves for the session: the exit, and by it where
    a halt stopped, the document an exit 4 put, or a bail's reason and
    record."""
    code = record.get("code")
    lines = [f"ended: exit {code}"]
    if code == EXIT_HALTED:
        lines.append(f"halted: {record.get('halted') or 'at a safe point'}")
    elif code == 4:
        lines.append(f"reason: {record.get('reason')}")
        if record.get("document"):
            lines.append(f"document: {record['document']}")
    elif code == 3:
        lines.append(f"reason: {record.get('reason')}")
        lines.append("bailout: "
                     f"{os.path.abspath(slice_dir / 'plan_bailout.json')}")
    return lines


def cmd_wait(args) -> None:
    """Block until the loop ends or `--for` seconds pass, then say which:
    `running` with the wait to re-arm, `ended: exit <n>` with what the exit
    leaves, or `gone` with the relaunch — run_loop's `wait`, on plan.lock
    and plan_state.json."""
    wait_on_driver(Path(args.slice_dir), "plan_state.json", "plan.lock",
                   args.for_seconds, SCRIPT, "--detach", _ended_lines)


def cmd_stop(args) -> None:
    """SIGINT the slice's plan loop — its KeyboardInterrupt path: the
    report rendered, plan_state.json current, exit 130; the rerun takes the
    interrupted pass again — and wait for it to let plan.lock go."""
    sys.exit(stop_driver(Path(args.slice_dir) / "plan.lock", None))


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "plan_state.json")
    if not state:
        print("no plan_state.json — the plan loop has not run on this slice")
        return
    print(f"slice {state['slice']}  phase={state['phase']}  "
          f"reviews={state['review_rounds']}  "
          f"writer_passes={state['writer_rounds']}")
    print(f"  {driver_line(state.get('driver'), slice_dir / 'plan.lock')}")
    if state.get("pending_questions"):
        print(f"  questions pending: {state['pending_questions']}")
    elif state.get("pending_review") and state["phase"] != "done":
        print(f"  review round {state['pending_review']} on file "
              f"({state['phase']})")
    exit_ = state.get("exit") or {}
    if exit_.get("document"):
        print(f"  document: {exit_['document']}")
    for h in state["history"][-8:]:
        print(f"  {h['ts']}  {h['role']} r{h['round']} → {h['outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or continue) the plan loop")
    run_p.add_argument("slice_dir", help="path to slices/backlog/NNN_slug/")
    run_p.add_argument("--step", metavar="ID",
                       help="the plan task the planning serves, from Pilot's "
                            "brief: every document the loop renders carries "
                            "it as `step`; kept for the reruns that do not "
                            "give it")
    run_p.add_argument("--detach", action="store_true",
                       help="run the loop in its own session, outliving this "
                            "shell; exits once it started and prints the "
                            "`wait` command to follow it with")
    run_p.add_argument("-v", "--verbose", action="store_true",
                       help="echo the log to stdout as well as plan_log.txt")
    run_p.set_defaults(func=cmd_run)

    wait_p = sub.add_parser(
        "wait", help="wait on a slice's plan loop, in the foreground; exit 0 "
                     "when it ended, 5 still running at --for, 6 gone (no "
                     "exit record)")
    wait_p.add_argument("slice_dir")
    wait_p.add_argument("--for", dest="for_seconds", type=float,
                        default=WAIT_DEFAULT, metavar="SECONDS",
                        help=f"give up waiting after this long (default "
                             f"{WAIT_DEFAULT}, inside the Bash tool's ten "
                             "minutes)")
    wait_p.set_defaults(func=cmd_wait)

    stop_p = sub.add_parser("stop", help="interrupt the slice's plan loop "
                                         "(SIGINT, as Ctrl-C) and wait for it")
    stop_p.add_argument("slice_dir")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="print a slice's plan-loop state")
    status_p.add_argument("slice_dir")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
