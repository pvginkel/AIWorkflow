#!/usr/bin/env python3
"""Plan loop — the single structural write→review round behind /dev:plan-slice.

The interactive /dev:plan-slice session settles requirements and rulings with the
operator and seeds plan.md's header sections; this script owns the mechanical
half: a fresh plan-writer pass completes the plan (phases with `Target:`
lines, attachments only where the executor genuinely cannot derive the
design, verification.json's outcome-level acceptance criteria), then a fresh
plan-reviewer pass judges it — structurally, in ONE round. The review is not
optional: exit 0 is refused without a reviewer verdict on file, and it is
the only place anything checks the plan against slice.md; nobody downstream
reads slice.md again.

There is no review loop. A `go` verdict completes the plan. Anything else —
blocking findings or operator questions — exits 4 with the review on file:
the interactive session adjudicates the findings with the operator, records
the rulings in plan.md's rulings section (edited in place, never
correction-chained), and either leaves the accepted fixes to the rerun,
which dispatches ONE writer fix pass, or applies them itself and declares
that by rerunning with --fixes-applied. The loop never infers which
happened — the fix pass is the default, so a forgotten flag costs one no-op
writer pass instead of shipping the plan unfixed. No confirming review
follows — the operator's read is the second look.

  exit 0 — plan complete: a reviewer verdict is on file and the plan parses
           as run_loop.py's phase queue.
  exit 4 — operator input needed: writer questions, or a review pending
           adjudication. Handle it, rerun — the loop continues where it
           paused.
  exit 3 — bailed (plan_bailout.json): an agent reported blocked, or a
           protocol failure.

The loop never resumes an agent session: every pass is a fresh context
reading its inputs from the slice folder (slice.md, plan.md, the review).
Rulings reach agents through plan.md only — dispatch prompts carry pointers,
not relayed content. State persists in <slice>/plan_state.json across
invocations.

The loop is the first to run on a slice, so it creates and commits the
slice's close-out report (<slice>/close-out.md — docs/close-out.md) before
its first dispatch.

All loop and session output goes to <slice>/plan_log.txt; stdout carries the
log-file line plus one terse timestamped line per pass start and the final
verdict, so a watching caller can follow progress cheaply; -v/--verbose
echoes the full log there too.

Usage:
    plan_loop.py run <slice-dir> [--fixes-applied] [--verbose]
    plan_loop.py status <slice-dir>

Exit codes: 0 plan complete · 4 operator input needed · 3 bailed
(plan_bailout.json written) · 2 usage/precondition error · 1 unexpected error.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The loop is kc-native and shares the run loop's seams rather than carrying
# twins: run_kc_session is the one kc dispatch helper, parse_plan the one
# plan-shape authority, and the target repo's root comes from `git rev-parse
# --show-toplevel` in the process cwd — not from `__file__`, which locates the
# plugin these tools ship in, never the repo being planned.
import project_config  # noqa: E402
from close_out import ReportError, dispatch_line, init_report, report_path  # noqa: E402
from run_loop import (  # noqa: E402
    AGENTS_DIR,
    PHILOSOPHY_LINE,
    SPAWN_ENV,
    _git_toplevel,
    _now_hms,
    _now_iso,
    _orchestrator_record,
    _protocol_failure_detail,
    _read_json,
    _transcript_path,
    parse_plan,
    plugin_version,
    run_kc_session,
    spawn_flags,
)

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

# Files the loop itself writes into the slice folder. They are working state,
# not slice artifacts, so they are excluded from every cleanliness check: the
# loop must not read its own output as an agent leaving work uncommitted.
LOOP_OWNED_FILES = frozenset({
    "plan_log.txt",       # loop + session output, appended across runs
    "plan_state.json",    # loop-owned state; survives so a rerun can resume
    "plan_bailout.json",  # bail record, rewritten each run
})


class Bailout(Exception):
    def __init__(self, reason: str, details: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.details = details


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
{philosophy_line}{close_out_line}
Commit to the spec repo (stage by name), then write your verdict
to {verdict_path}. Blocking questions go to {questions_path} with verdict
`questions`.
"""

WRITER_FIX_PROMPT = """\
The plan-reviewer's findings on slice {slice_name}'s plan have been
adjudicated with the operator. Slice folder: {slice_dir}

Read {review_path} and plan.md — the rulings recorded in plan.md supersede
the review where they speak. Apply every ruling the plan does not yet
reflect and resolve every blocking finding the rulings do not overrule —
the reviewer and the operator state problems; the fix design is yours. This
is the only fix pass: no review follows it, the operator's read does.
{philosophy_line}{close_out_line}
Commit (stage by name), then write your verdict to {verdict_path}. A
finding the rulings leave genuinely unresolved goes to {questions_path}
with verdict `questions`.
"""

WRITER_RESUME_NOTE = """\
An earlier pass paused on the questions in {questions_file}; plan.md's
rulings section now holds the answers. Continue that pass with them applied.
"""

REVIEWER_PROMPT = """\
Review the plan for slice {slice_name} — the full plan, in your one and
only round: no fix-verify loop follows; your findings go to the operator.
Slice folder: {slice_dir}
{philosophy_line}{close_out_line}

Write your review to {review_path} and your verdict to {verdict_path}.
"""

VERDICT_NUDGE_PROMPT = """\
Your session ended without writing a valid verdict file. Do not start new
work: if any of your work is uncommitted, commit it, then write your verdict
now to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}; outcome
must be one of {outcomes}).
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
                 fixes_applied: bool = False):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.slice_num = self.slice_name.split("_")[0]
        self.plan_path = self.slice_dir / "plan.md"
        self.report_path = report_path(self.slice_dir)
        self.state_path = self.slice_dir / "plan_state.json"
        self.log_path = self.slice_dir / "plan_log.txt"
        self.verbose = verbose
        # The interactive session's declaration that it applied the
        # adjudicated fixes itself — the only thing that suppresses the fix
        # pass. Nothing is inferred from the plan's content.
        self.fixes_applied = fixes_applied
        self.state: dict = {}
        self._log_file = None
        # Sessions spawn in the target repo, not the spec repo: the loop is
        # launched from it, and the agents read the code there.
        self.repo_root = _git_toplevel()
        self._philosophy: str | None = None

    # -- state ---------------------------------------------------------------

    def _save_state(self) -> None:
        self.state["updated_at"] = _now_iso()
        tmp = self.state_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.state_path)

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
            if PurePosixPath(path).name not in LOOP_OWNED_FILES:
                dirty.append(path)
        return dirty

    # -- session spawning ----------------------------------------------------

    def _nudge(self, prompt: str, session_id: str, label: str,
               role: str) -> None:
        self.log(f"{label} nudging the session (resume)")
        try:
            run_kc_session(
                prompt=prompt, cwd=str(self.repo_root), timeout=NUDGE_TIMEOUT,
                resume_session=session_id, extra_env=SPAWN_ENV,
                flags=spawn_flags(role),
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

    def _spawn(self, role: str, prompt: str, verdict_path: Path,
               round_: int) -> dict:
        """Run one fresh session; return its validated verdict. A session
        failure, invalid verdict (after one nudge), or dirty slice folder
        (after one nudge) is a bail-out — the loop has no fallback driver."""
        label = f"[{role} r{round_}]"
        self.log(f"{label} session starting")
        verdict_path.unlink(missing_ok=True)
        model, effort = MODELS[role]

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(self.repo_root, sid)}")

        t0 = time.monotonic()
        try:
            returncode, result = run_kc_session(
                prompt=prompt, cwd=str(self.repo_root), timeout=TIMEOUTS[role],
                agent=role, model=model, effort=effort, extra_env=SPAWN_ENV,
                flags=spawn_flags(role),
                progress=lambda line: self._emit(f"    {label} {line}"),
                on_session=_note_session,
            )
        except subprocess.TimeoutExpired:
            raise Bailout("timeout",
                          details=f"{role} exceeded {TIMEOUTS[role]}s") from None
        duration_s = int(time.monotonic() - t0)
        session_id = result.session_id

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
                self.slice_dir / f"plan_questions_r{w}.md")

    def _writer_pass(self, initial: bool) -> None:
        w, verdict_path, questions_path = self._writer_paths()
        if initial:
            prompt = WRITER_INITIAL_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                philosophy_line=self._philosophy_line(),
                close_out_line=dispatch_line(self.report_path),
                verdict_path=verdict_path, questions_path=questions_path)
        else:
            review_path = (self.slice_dir /
                           f"plan_review_r{self.state['pending_review']}.md")
            prompt = WRITER_FIX_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                philosophy_line=self._philosophy_line(),
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
            self.state.update(pending_questions=str(questions_path),
                              phase="questions")
            self._save_state()
            self._exit_questions(questions_path)
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
        verdict_path = self.slice_dir / f"plan_review_result_r{r}.json"
        prompt = REVIEWER_PROMPT.format(
            slice_name=self.slice_name, slice_dir=self.slice_dir,
            philosophy_line=self._philosophy_line(),
            close_out_line=dispatch_line(self.report_path),
            review_path=review_path, verdict_path=verdict_path)

        self.announce(f"plan-reviewer r{r}")
        verdict = self._spawn("plan-reviewer", prompt, verdict_path, r)
        if verdict["outcome"] == "go":
            self.state.update(pending_review=r, phase="done")
            self._save_state()
            return
        # issues / questions: both are the operator's — the interactive
        # session adjudicates the review; there is no fix-verify loop.
        self.state.update(pending_review=r, phase="adjudicating")
        self._save_state()
        self._exit_adjudication(review_path)

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

    # -- terminal exits ------------------------------------------------------

    def _exit_questions(self, questions_file: Path) -> None:
        self.log(f"QUESTIONS PENDING — {questions_file}")
        print(f"QUESTIONS PENDING — ask the operator from {questions_file}, "
              "record the ruling in plan.md's rulings section, then rerun.",
              file=sys.stderr)
        sys.exit(4)

    def _exit_adjudication(self, review_path: Path) -> None:
        self.log(f"REVIEW PENDING ADJUDICATION — {review_path}")
        print(f"REVIEW PENDING ADJUDICATION — read {review_path}, "
              "adjudicate the findings with the operator, and record the "
              "rulings in plan.md's rulings section (edit superseded "
              "rulings in place — no correction-chains). Commit, then rerun: "
              "the rerun dispatches one writer fix pass, which applies the "
              "accepted fixes to the phases and verification.json. Only if "
              "you applied those fixes yourself, rerun with --fixes-applied "
              "to skip that pass.",
              file=sys.stderr)
        sys.exit(4)

    def _bail(self, bail: Bailout) -> None:
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
                "writer_rounds": 0,
                "review_rounds": 0,
                "pending_review": None,
                "pending_questions": None,
                "history": [],
            }
        self._save_state()

    def _ensure_report(self) -> None:
        """The slice's close-out report exists before the first dispatch —
        created from the template and committed by the loop (by name; the
        spec repo is a shared tree). A rerun finds it and leaves it be. Runs
        under the bail handler: a git or template failure is a bail
        (plan_bailout.json), never a traceback."""
        try:
            created = init_report(self.slice_dir)
        except ReportError as e:
            raise Bailout("protocol_failure", details=str(e)) from None
        if created:
            self.git("add", str(self.report_path))
            self.git("commit", "-m",
                     f"slice {self.slice_num}: close-out report")
            self.log(f"created {self.report_path.name} from the template")

    def run(self) -> None:
        if not (self.slice_dir / "slice.md").exists():
            print(f"Error: {self.slice_dir} has no slice.md", file=sys.stderr)
            sys.exit(2)
        if not self.plan_path.exists():
            print(f"Error: {self.plan_path} does not exist — the interactive "
                  "session seeds it (requirements/rulings) before the loop "
                  "runs.", file=sys.stderr)
            sys.exit(2)
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

        if self.fixes_applied and self.state["phase"] != "adjudicating":
            print("Error: --fixes-applied declares that the adjudicated "
                  f"fixes are in the plan, but phase is "
                  f"{self.state['phase']!r}, not 'adjudicating' — no review "
                  "is pending adjudication. Rerun without it.",
                  file=sys.stderr)
            sys.exit(2)

        # A questions exit resumes into the pass that raised (or must absorb)
        # the questions, now answered in plan.md's rulings section. An
        # adjudication exit resumes into the fix pass unless the session
        # declares it applied the fixes itself. That declaration is the only
        # thing that suppresses the pass: which edits the session made during
        # adjudication cannot be read off the plan — recording the rulings is
        # required either way, and ordering/not-in-scope maintenance follows
        # from a reversed ruling — so inferring it silently shipped unfixed
        # plans. Defaulting to the pass makes a forgotten flag a wasted
        # writer round rather than a hole.
        if self.state["phase"] == "questions":
            self.state["phase"] = ("fixing" if self.state["pending_review"]
                                   else "writing")
            self._save_state()
        elif self.state["phase"] == "adjudicating":
            if self.fixes_applied:
                self.log("--fixes-applied: the session applied the "
                         "adjudicated fixes itself — no fix pass")
                self.state["phase"] = "done"
            else:
                self.log("dispatching the writer fix pass for the "
                         "adjudicated review")
                self.state["phase"] = "fixing"
            self._save_state()

        try:
            self._ensure_report()
            while True:
                phase = self.state["phase"]
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
            self._verify_review_on_file()
            self._verify_plan_parses()
        except Bailout as bail:
            self._bail(bail)
        except KeyboardInterrupt:
            self.log("interrupted — plan_state.json is current; rerun to "
                     "continue")
            print("Interrupted — rerun to continue.", file=sys.stderr)
            sys.exit(130)

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
                    fixes_applied=args.fixes_applied)
    print(f"plan loop log: {loop.log_path}", flush=True)
    loop.run()


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "plan_state.json")
    if not state:
        print("no plan_state.json — the plan loop has not run on this slice")
        return
    print(f"slice {state['slice']}  phase={state['phase']}  "
          f"reviews={state['review_rounds']}  "
          f"writer_passes={state['writer_rounds']}")
    if state.get("pending_questions"):
        print(f"  questions pending: {state['pending_questions']}")
    elif state.get("pending_review") and state["phase"] != "done":
        print(f"  review round {state['pending_review']} on file "
              f"({state['phase']})")
    for h in state["history"][-8:]:
        print(f"  {h['ts']}  {h['role']} r{h['round']} → {h['outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or continue) the plan loop")
    run_p.add_argument("slice_dir", help="path to slices/backlog/NNN_slug/")
    run_p.add_argument("--fixes-applied", action="store_true",
                       help="on a rerun after an adjudication exit: the "
                            "accepted fixes are already in the plan's phases "
                            "and verification.json — skip the writer fix "
                            "pass. Without it the fix pass runs.")
    run_p.add_argument("-v", "--verbose", action="store_true",
                       help="echo the log to stdout as well as plan_log.txt")
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser("status", help="print a slice's plan-loop state")
    status_p.add_argument("slice_dir")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
