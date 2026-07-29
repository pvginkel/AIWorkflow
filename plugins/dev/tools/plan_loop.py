#!/usr/bin/env python3
"""Plan loop — drives a slice's planning through the bounded write/review loop.

The interactive /dev:plan-slice session settles the design with the operator,
then launches this script; the script owns everything mechanical after that.
It dispatches fresh plan-writer / plan-reviewer sessions until one of three
terminal states:

  exit 0 — the reviewer signed off (GO): hygiene findings fixed in one
           unreviewed pass, the plans' CT-/G- references linted against their
           definitions, ledger entries no plan cites pruned, verification.json
           seeded from the acceptance criteria, phase `done`.
  exit 4 — questions pending: an agent raised something only the operator can
           rule on. The session briefs the operator from the named file
           (plan-briefer), has the rulings recorded to qa_log.md and slice.md
           (plan-scribe), then reruns this script — the loop continues where
           it paused.
  exit 3 — bailed (plan_bailout.json): the review budget ran out, an agent
           reported blocked, or a protocol failure. Rerunning continues once
           the cause is resolved; `--grant N` extends the review budget (an
           operator decision relayed by the session, never the script's own).

The loop never resumes an agent session: every pass is a fresh context reading
its inputs from the slice folder (slice.md, qa_log.md, grounding.md, the
artifacts, the latest review). Rulings reach agents through those files only —
dispatch prompts carry pointers, not relayed content. Round counts persist in
<slice>/plan_state.json across invocations; the review budget spans the whole
planning cycle, not one invocation.

Before every writer/reviewer dispatch the loop re-anchors the slice's grounding
ledger (grounding_check.py --repair; format and tiers in
${CLAUDE_PLUGIN_ROOT}/docs/grounding-ledger.md) and the dispatch carries the
resulting freshness line: a trust line when the anchors hold, the drifted
entries when they do not. No agent step is involved — the checker is
deterministic and its repairs are committed by the loop.

All loop and session output goes to <slice>/plan_log.txt; stdout stays silent —
one line naming the log — unless -v/--verbose echoes it.

After exit 0 the session verifies fidelity and presents to the operator;
corrections at that point are logged as rulings and re-enter the loop with
`--reopen` (which buys the fix pass its confirming review round).

Usage:
    plan_loop.py run <slice-dir> [--grant N] [--reopen] [--verbose]
    plan_loop.py status <slice-dir>

Exit codes: 0 plan complete · 4 questions pending · 3 bailed
(plan_bailout.json written) · 2 usage/precondition error · 1 unexpected error.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from grounding_dispatch import commit_ledger, run_check  # noqa: E402

# The loop is kc-native and shares the task runner's seams rather than carrying
# twins: run_kc_session is the one kc dispatch helper (create-headless / send /
# status / end — see its docstring for the verb mapping), and the target repo's
# root comes from `git rev-parse --show-toplevel` in the process cwd — the
# plugin's tools no longer live inside the target repo, and /dev:plan-slice
# runs the loop from it.
from task_runner import (  # noqa: E402
    SPAWN_ENV,
    _git_toplevel,
    _now_iso,
    _orchestrator_record,
    _protocol_failure_detail,
    _read_json,
    _transcript_path,
    run_kc_session,
)

REVIEW_BUDGET = 4  # total review rounds per planning cycle; --grant extends
TIMEOUTS = {"plan-writer": 7200, "plan-reviewer": 3600}
NUDGE_TIMEOUT = 900

# Task folders (tasks/NN[a]_slug/) and the ids the plans inside them cite.
TASK_DIR_RE = re.compile(r"^\d{2}[a-z]?_")
CT_ID_RE = re.compile(r"\bCT-(\d+)\b")
G_ID_RE = re.compile(r"\bG-(\d+)\b")

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


def _stamp_label(stamp: dict[str, str] | None) -> str:
    """`Repo@sha` per stamped repo, shas cut to the length the checker's own
    summary uses. A non-legacy report always carries a stamp."""
    parts = [f"{name}@{sha[:12]}" for name, sha in (stamp or {}).items()]
    return ", ".join(parts) if parts else "no stamp"


def _drift_label(entry: dict) -> str:
    return (f"{entry.get('id')} {entry.get('status')} "
            f"({entry.get('file')}:{entry.get('cited_line')})")


def _id_sort_key(item: tuple[str, list[str]]) -> tuple[str, int]:
    prefix, _, num = item[0].partition("-")
    return prefix, int(num)


def _render_dangling(dangling: dict[str, list[str]]) -> str:
    return "; ".join(f"{id_} (cited by {', '.join(plans)})"
                     for id_, plans in dangling.items())


# ---------------------------------------------------------------------------
# Dispatch prompts. Role contracts live in the agent definitions; prompts
# carry only instance data — pointers into the slice folder, never relayed
# rulings or findings.
# ---------------------------------------------------------------------------

# The freshness line every writer/reviewer dispatch carries. It states what the
# checker established so the receiving pass does not re-derive it: distrust
# framing on a two-hour-old ledger measured 46% duplicate re-verification.
GROUNDING_LEGACY_LINE = (
    "grounding.md predates the ledger format — no mechanical freshness check "
    "ran."
)

GROUNDING_FRESH_LINE = (
    "Deterministic fact from the loop: grounding.md was verified at {stamp}; "
    "grounding_check.py re-anchored it against HEAD just now — {summary}."
    "{drift_clause} Trust the ledger to this line: scope any Explore "
    "dispatches to declared gaps{drift_ref}, never to re-confirming ledger "
    "entries."
)

GROUNDING_DRIFT_CLAUSE = (
    " These entries no longer anchor and are unverified: {entries}."
)

GROUNDING_DRIFT_REF = " and the drift listed above"

WRITER_INITIAL_PROMPT = """\
You are writing the task breakdown for slice {slice_name}.
Slice folder: {slice_dir}

{grounding_line}

Read slice.md, qa_log.md, and grounding.md there, then produce the breakdown
and slice-level artifacts per your contract. Commit to the spec repo (stage
by name), then write your verdict to {verdict_path}. Blocking questions go to
{questions_path} with verdict `questions`.
"""

WRITER_FIX_PROMPT = """\
The plan-reviewer did not sign off on slice {slice_name}'s breakdown.
Slice folder: {slice_dir}

{grounding_line}

Read {review_path} and qa_log.md — rulings logged after the review supersede
it. Resolve every outstanding material and needs-ruling finding and apply
every ruling the artifacts do not yet reflect — the reviewer and the operator
state problems; the fix design is yours. Commit (stage by name), then write
your verdict to {verdict_path}. A finding qa_log.md leaves unresolved goes to
{questions_path} with verdict `questions`.
"""

WRITER_RESUME_NOTE = """\
An earlier pass paused on the questions in {questions_file}; qa_log.md now
holds the rulings. Continue that pass with them applied.
"""

WRITER_HYGIENE_PROMPT = """\
The plan-reviewer signed off on slice {slice_name} with hygiene findings only.
Slice folder: {slice_dir}

Read {review_path} and fix its hygiene findings in one pass — and sweep the
artifacts for further instances of the same defect classes. No design or
scope changes. Line-scoped edits only — no new research: a finding that cannot
be fixed without opening an investigation is left unfixed and named in your
verdict summary; material work goes back through review, never through this
pass. Commit (stage by name), then write your verdict to {verdict_path}.
"""

WRITER_LINT_PROMPT = """\
The loop's deterministic cross-reference lint found dangling ids in the task
plans for slice {slice_name}: {dangling}
Slice folder: {slice_dir}

Fix the references or add the missing definitions — line-scoped edits only, no
design or scope changes. Commit (stage by name), then write your verdict to
{verdict_path}.
"""

REVIEWER_PROMPT = """\
Review the planning output for slice {slice_name} (round {round}).
Slice folder: {slice_dir}

{grounding_line}

{scope}

Write your review to {review_path} and your verdict to {verdict_path}.
"""

REVIEWER_SCOPE_FULL = """\
This is the first review round: review the full breakdown."""

REVIEWER_SCOPE_DELTA = """\
Prior rounds are plan_review_r*.md in the slice folder. The changes since the
last review: `git -C {specs_root} diff {sha}..HEAD -- {slice_dir}`. Scope this
round to those changes and the prior findings' resolutions; do not re-derive
what a prior round verified and the diff does not touch."""

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
    def __init__(self, slice_dir: Path, verbose: bool = False):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.state_path = self.slice_dir / "plan_state.json"
        self.log_path = self.slice_dir / "plan_log.txt"
        self.verbose = verbose
        self.state: dict = {}
        self._log_file = None
        # Sessions spawn in the target repo, not the spec repo: the loop is
        # launched from it, and the agents read the code there.
        self.repo_root = _git_toplevel()

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
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._emit(f"[{ts}] {msg}")

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

    def _specs_root(self) -> str:
        return self.git("rev-parse", "--show-toplevel")

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

    # -- grounding ledger ----------------------------------------------------

    def _commit_grounding(self, message: str) -> None:
        """Commit the checker's own rewrite of grounding.md — by name, since
        the spec repo is a shared working tree (grounding_dispatch owns the
        mechanics). A failed commit is logged and survived: the rewrite is on
        disk either way, and it is the next dispatch's cleanliness check that
        turns a stuck tree into a bail."""
        if commit_ledger(self.slice_dir, message):
            self.log(f"committed grounding.md ({message})")
        else:
            self.log(f"grounding commit failed ({message}) — the rewrite is "
                     "on disk, uncommitted")

    def _grounding_line(self) -> str:
        """The freshness line a writer/reviewer dispatch carries: what the
        ledger was verified against, what re-anchoring it found just now, and
        which entries no longer hold. MOVED line numbers are repaired and
        committed here — the receiving pass must not find the slice folder
        dirty, and it must not spend tokens re-confirming what holds."""
        report = run_check(self.slice_dir, repair=True)
        if report is None:
            self.log("grounding check produced no report — dispatch carries "
                     "the legacy line")
            return GROUNDING_LEGACY_LINE
        if report.get("legacy"):
            self.log("grounding: legacy ledger — dispatch carries the legacy "
                     "line")
            return GROUNDING_LEGACY_LINE
        entries = report.get("entries") or []
        if any(e.get("repaired") for e in entries):
            self._commit_grounding(
                "grounding: repair drifted citations (plan loop)")
        drifted = [e for e in entries if e.get("status") in ("MISSING", "GONE")]
        clause = ref = ""
        if drifted:
            clause = GROUNDING_DRIFT_CLAUSE.format(
                entries=", ".join(_drift_label(e) for e in drifted))
            ref = GROUNDING_DRIFT_REF
        self.log(report.get("summary", ""))
        return GROUNDING_FRESH_LINE.format(
            stamp=_stamp_label(report.get("stamp")),
            summary=report.get("summary", ""),
            drift_clause=clause, drift_ref=ref)

    def _prune_grounding(self) -> None:
        """At GO, drop the ledger entries no plan cites. A legacy ledger
        prunes nothing — the checker says so and the loop moves on."""
        report = run_check(self.slice_dir, prune=True)
        if report is None:
            self.log("grounding prune produced no report — nothing pruned")
            return
        pruned = report.get("pruned") or []
        if not pruned:
            return
        self.log(f"grounding: pruned {len(pruned)} uncited "
                 f"entr{'y' if len(pruned) == 1 else 'ies'} "
                 f"({', '.join(pruned)})")
        self._commit_grounding("grounding: prune entries no plan cites")

    # -- cross-reference lint ------------------------------------------------

    def _plan_files(self) -> list[Path]:
        tasks_dir = self.slice_dir / "tasks"
        if not tasks_dir.is_dir():
            return []
        return [d / "plan.md" for d in sorted(tasks_dir.iterdir())
                if d.is_dir() and TASK_DIR_RE.match(d.name)
                and (d / "plan.md").is_file()]

    def _criteria_ids(self) -> set[int]:
        ac = _read_json(self.slice_dir / "acceptance_criteria.json") or {}
        return {int(n) for c in ac.get("criteria", [])
                for n in CT_ID_RE.findall(str(c.get("id", "")))}

    def _ledger_ids(self) -> set[int] | None:
        """The ids grounding.md defines, or None when nothing mechanical can
        read it (a legacy ledger, or a checker that produced no report) — the
        G-side of the lint is skipped then rather than calling every reference
        dangling."""
        report = run_check(self.slice_dir)
        if report is None or report.get("legacy"):
            return None
        return {int(n) for e in report.get("entries") or []
                for n in G_ID_RE.findall(str(e.get("id", "")))}

    def _dangling_ids(self) -> dict[str, list[str]]:
        """Every CT-/G- id the task plans cite that nothing defines, mapped to
        the plans citing it. CT ids resolve against acceptance_criteria.json,
        G ids against grounding.md; both compare by number, so CT-7 and CT-07
        are the same criterion."""
        definitions = ((CT_ID_RE, self._criteria_ids()),
                       (G_ID_RE, self._ledger_ids()))
        dangling: dict[str, list[str]] = {}
        for path in self._plan_files():
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            label = str(path.relative_to(self.slice_dir))
            for regex, defined in definitions:
                if defined is None:
                    continue
                for match in regex.finditer(text):
                    if int(match.group(1)) in defined:
                        continue
                    plans = dangling.setdefault(match.group(0), [])
                    if label not in plans:
                        plans.append(label)
        return dict(sorted(dangling.items(), key=_id_sort_key))

    def _cross_reference_lint(self) -> None:
        """At GO: the plans' CT-/G- references against their definitions.

        A dangling id buys one line-scoped writer fix pass — no review budget,
        no re-review, the hygiene pass's mechanics — and must be gone after
        it. A breakdown citing a criterion nothing defines is a protocol
        failure, not something for the orchestrator's post-exit fidelity check
        to find (slice 110's CT-34, cited by two plans and defined nowhere,
        cost a --reopen cycle).
        """
        dangling = self._dangling_ids()
        if not dangling:
            self.log("cross-reference lint: clean")
            return
        self.log(f"cross-reference lint: {_render_dangling(dangling)} — "
                 "one fix pass")
        w, verdict_path, _ = self._writer_paths()
        verdict = self._spawn(
            "plan-writer",
            WRITER_LINT_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                dangling=_render_dangling(dangling),
                verdict_path=verdict_path),
            verdict_path, w)
        if verdict["outcome"] != "done":
            raise Bailout("blocked",
                          details="cross-reference lint pass did not report "
                                  "done: " + verdict.get("summary", ""))
        still = self._dangling_ids()
        if still:
            raise Bailout(
                "protocol_failure",
                details="dangling plan references survive the lint fix pass: "
                        + _render_dangling(still))
        self.log("cross-reference lint: clean after the fix pass")

    # -- session spawning ----------------------------------------------------

    def _nudge(self, prompt: str, session_id: str, label: str) -> None:
        self.log(f"{label} nudging the session (resume)")
        try:
            run_kc_session(
                prompt=prompt, cwd=str(self.repo_root), timeout=NUDGE_TIMEOUT,
                resume_session=session_id, extra_env=SPAWN_ENV,
                progress=lambda line: self._emit(f"    {label} {line}"),
            )
        except subprocess.TimeoutExpired:
            self.log(f"{label} nudge timed out")

    def _spawn(self, role: str, prompt: str, verdict_path: Path,
               round_: int) -> dict:
        """Run one fresh session; return its validated verdict. A session
        failure, invalid verdict (after one nudge), or dirty slice folder
        (after one nudge) is a bail-out — the loop has no fallback driver."""
        label = f"[{role} r{round_}]"
        self.log(f"{label} session starting")
        verdict_path.unlink(missing_ok=True)

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(self.repo_root, sid)}")

        t0 = time.monotonic()
        try:
            returncode, result = run_kc_session(
                prompt=prompt, cwd=str(self.repo_root), timeout=TIMEOUTS[role],
                agent=role, extra_env=SPAWN_ENV,
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
                session_id, label)
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
                self._nudge(COMMIT_NUDGE_PROMPT, session_id, label)
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
        grounding_line = self._grounding_line()
        if initial:
            prompt = WRITER_INITIAL_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                grounding_line=grounding_line,
                verdict_path=verdict_path, questions_path=questions_path)
        else:
            review_path = (self.slice_dir /
                           f"plan_review_r{self.state['pending_review']}.md")
            prompt = WRITER_FIX_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                grounding_line=grounding_line,
                review_path=review_path, verdict_path=verdict_path,
                questions_path=questions_path)
        if self.state.get("pending_questions"):
            prompt += "\n" + WRITER_RESUME_NOTE.format(
                questions_file=self.state["pending_questions"])

        verdict = self._spawn("plan-writer", prompt, verdict_path, w)
        if verdict["outcome"] == "questions":
            self.state.update(pending_questions=str(questions_path),
                              phase="questions")
            self._save_state()
            self._exit_questions(questions_path)
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", details=verdict.get("summary", ""))
        self.state.update(pending_questions=None, pending_review=None,
                          phase="reviewing")
        self._save_state()

    def _review_round(self) -> None:
        if self.state["review_rounds"] >= self.state["review_budget"]:
            raise Bailout(
                "review_budget",
                details=f"{self.state['review_budget']} review round(s) spent "
                        "without a GO. Bring the contested points to the "
                        "operator; rerun with --grant N on their say-so.",
            )
        self.state["review_rounds"] += 1
        r = self.state["review_rounds"]
        self._save_state()
        review_path = self.slice_dir / f"plan_review_r{r}.md"
        verdict_path = self.slice_dir / f"plan_review_result_r{r}.json"
        prev_sha = self.state.get("last_reviewed_sha")
        scope = (REVIEWER_SCOPE_DELTA.format(
                     specs_root=self._specs_root(), sha=prev_sha,
                     slice_dir=self.slice_dir)
                 if prev_sha else REVIEWER_SCOPE_FULL)
        prompt = REVIEWER_PROMPT.format(
            slice_name=self.slice_name, slice_dir=self.slice_dir,
            grounding_line=self._grounding_line(),
            round=r, scope=scope, review_path=review_path,
            verdict_path=verdict_path)

        verdict = self._spawn("plan-reviewer", prompt, verdict_path, r)
        self.state["last_reviewed_sha"] = self.git("rev-parse", "HEAD")
        if verdict["outcome"] == "questions":
            self.state.update(pending_review=r, phase="questions")
            self._save_state()
            self._exit_questions(review_path)
        if verdict["outcome"] == "issues":
            self.state.update(pending_review=r, phase="fixing")
            self._save_state()
            return
        # go
        self.state.update(pending_review=r if verdict.get("hygiene") else None,
                          phase="hygiene" if verdict.get("hygiene") else "done")
        self._save_state()

    def _hygiene_pass(self) -> None:
        """One unreviewed fix pass for the GO round's hygiene findings."""
        w, verdict_path, questions_path = self._writer_paths()
        review_path = (self.slice_dir /
                       f"plan_review_r{self.state['pending_review']}.md")
        verdict = self._spawn(
            "plan-writer",
            WRITER_HYGIENE_PROMPT.format(
                slice_name=self.slice_name, slice_dir=self.slice_dir,
                review_path=review_path, verdict_path=verdict_path),
            verdict_path, w)
        if verdict["outcome"] != "done":
            raise Bailout("blocked",
                          details="hygiene pass did not report done: "
                                  + verdict.get("summary", ""))
        self.state.update(pending_review=None, phase="done")
        self._save_state()

    def _seed_verification(self) -> None:
        """Deterministic transform: one verification item per acceptance
        criterion, in order. Coordinator-authored qa_correction entries are
        preserved and renumbered after the criteria block."""
        ac = _read_json(self.slice_dir / "acceptance_criteria.json") or {}
        kept = [i for i in (_read_json(self.slice_dir / "verification.json")
                            or {}).get("items", [])
                if i.get("source") != "ac"]
        items = [{"id": f"V{n:02d}", "source": "ac",
                  "area": c.get("area", ""),
                  "description": f"{c.get('id', '')}: {c.get('description', '')}",
                  "verdict": None, "rationale": "", "evidence": []}
                 for n, c in enumerate(ac.get("criteria", []), 1)]
        for n, item in enumerate(kept, len(items) + 1):
            item["id"] = f"V{n:02d}"
            items.append(item)
        path = self.slice_dir / "verification.json"
        with open(path, "w") as f:
            json.dump({"items": items}, f, indent=2)
            f.write("\n")
        if self._slice_dirty():
            self.git("add", str(path))
            self.git("commit", "-m",
                     f"slice {self.slice_name.split('_')[0]}: "
                     "seed verification log")
        self.log(f"verification.json seeded ({len(items)} item(s))")

    # -- terminal exits ------------------------------------------------------

    def _exit_questions(self, questions_file: Path) -> None:
        self.log(f"QUESTIONS PENDING — {questions_file}")
        print(f"QUESTIONS PENDING — brief the operator from {questions_file} "
              "(plan-briefer), record the rulings (plan-scribe), then rerun.",
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

    def _init_state(self, grant: int) -> None:
        self.state = _read_json(self.state_path) or {}
        if not self.state:
            tasks_dir = self.slice_dir / "tasks"
            has_tasks = tasks_dir.is_dir() and any(
                d.is_dir() and TASK_DIR_RE.match(d.name)
                for d in tasks_dir.iterdir())
            self.state = {
                "slice": self.slice_name,
                "created_at": _now_iso(),
                "orchestrator": _orchestrator_record(),
                # An existing breakdown (a reset re-plan) enters at review.
                "phase": "reviewing" if has_tasks else "writing",
                "writer_rounds": 0,
                "review_rounds": 0,
                "review_budget": REVIEW_BUDGET,
                "pending_review": None,
                "pending_questions": None,
                "last_reviewed_sha": None,
                "history": [],
            }
        if grant:
            self.state["review_budget"] += grant
            self.log(f"review budget extended by {grant} "
                     f"(now {self.state['review_budget']})")
        self._save_state()

    def run(self, grant: int = 0, reopen: bool = False) -> None:
        if not (self.slice_dir / "slice.md").exists():
            print(f"Error: {self.slice_dir} has no slice.md", file=sys.stderr)
            sys.exit(2)
        dirty = self._slice_dirty_paths()
        if dirty:
            print(f"Error: uncommitted changes under {self.slice_dir}; "
                  "commit (stage by name) before running the loop:",
                  file=sys.stderr)
            for path in dirty:
                print(f"  {path}", file=sys.stderr)
            sys.exit(2)
        self._init_state(grant)
        (self.slice_dir / "plan_bailout.json").unlink(missing_ok=True)

        if reopen:
            if self.state["phase"] != "done":
                print("Error: --reopen re-enters a completed loop; this one "
                      f"is at phase {self.state['phase']!r} — just rerun.",
                      file=sys.stderr)
                sys.exit(2)
            # New rulings were logged after the GO; a reopen buys the fix
            # pass its confirming review round.
            self.state.update(phase="fixing",
                              pending_review=self.state["review_rounds"],
                              review_budget=self.state["review_budget"] + 1)
            self._save_state()
            self.log("reopened after new rulings (budget "
                     f"{self.state['review_budget']})")

        # A questions exit resumes into the pass that raised (or must absorb)
        # the questions, now answered in qa_log.md.
        if self.state["phase"] == "questions":
            self.state["phase"] = ("fixing" if self.state["pending_review"]
                                   else "writing")
            self._save_state()

        try:
            while True:
                phase = self.state["phase"]
                if phase == "writing":
                    self._writer_pass(initial=True)
                elif phase == "fixing":
                    self._writer_pass(initial=False)
                elif phase == "reviewing":
                    self._review_round()
                elif phase == "hygiene":
                    self._hygiene_pass()
                elif phase == "done":
                    break
                else:
                    raise Bailout("protocol_failure",
                                  details=f"unknown phase {phase!r}")
            # GO reached: the plans are final, so the deterministic passes over
            # them run before the loop hands anything to the orchestrator.
            self._cross_reference_lint()
            self._prune_grounding()
        except Bailout as bail:
            self._bail(bail)
        except KeyboardInterrupt:
            self.log("interrupted — plan_state.json is current; rerun to "
                     "continue")
            print("Interrupted — rerun to continue.", file=sys.stderr)
            sys.exit(130)

        self._seed_verification()
        rounds = self.state["review_rounds"]
        self.log(f"plan complete: review GO after {rounds} round(s), "
                 f"{self.state['writer_rounds']} writer pass(es)")
        sys.exit(0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
        sys.exit(2)
    loop = PlanLoop(slice_dir, verbose=args.verbose)
    print(f"plan loop log: {loop.log_path}", flush=True)
    loop.run(grant=args.grant, reopen=args.reopen)


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "plan_state.json")
    if not state:
        print("no plan_state.json — the plan loop has not run on this slice")
        return
    print(f"slice {state['slice']}  phase={state['phase']}  "
          f"reviews={state['review_rounds']}/{state['review_budget']}  "
          f"writer_passes={state['writer_rounds']}")
    if state.get("pending_questions"):
        print(f"  questions pending: {state['pending_questions']}")
    elif state.get("pending_review") and state["phase"] != "done":
        print(f"  pending review round: {state['pending_review']}")
    for h in state["history"][-8:]:
        print(f"  {h['ts']}  {h['role']} r{h['round']} → {h['outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or continue) the plan loop")
    run_p.add_argument("slice_dir", help="path to slices/backlog/NNN_slug/")
    run_p.add_argument("--grant", type=int, default=0, metavar="N",
                       help="extend the review budget by N rounds "
                            "(operator decision)")
    run_p.add_argument("--reopen", action="store_true",
                       help="re-enter a completed loop after new rulings "
                            "were logged to qa_log.md (adds one review round "
                            "to the budget)")
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
