#!/usr/bin/env python3
"""Run loop — drives a slice's phased plan through the dev loop.

The Markdown plan is the queue; this driver is its bookkeeper (see
${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md — the canonical contract). The plan
(<slice>/plan.md) holds phases as `### P<id> — <title>` headings, each opening
with a `Target:` line naming a `kc project list` component or a sibling repo.
Document order is authoritative; ids are labels. Per unfinished phase, in
order: fetch the target repo (nothing else in a run refreshes a
remote-tracking ref, so an unfetched clone dates an agent's read of
`origin/<base>` to the day it was cloned) → branch → executor session (fresh
code-writer) → deterministic gate (red spawns a fresh executor fix round,
capped) → code-reviewer loop (round 1's fix is automatic; from round 2 a
consult funds each further round against a bar that rises per round; backstop
cap) → gate-checked ff-merge → the driver stamps `✅ DONE <date>` on the phase
heading. Only the driver stamps.

After the last phase the driver runs the loop-tail gate sweep — `kc project
lint` + `build` + `test`, per component, across every touched repo with a kc
manifest — and the commit-stamped report rides the loop-tail dispatches as
deterministic fact, under one principle: a branch whose gates are red is not
pushed, so a red tree is decided on at the consult (fixing phase or bail),
never discovered at push time. Then a completion consult (may append phases
— the loop picks them up), then the test phase ("read the
slice-testing-strategy doc and execute" — the driver holds the devlock;
under that hold pushing and rolling dev for verification is pre-authorized,
and a clean pass that left any repo the slice touched behind its origin is
nudged, capped, then bails), then the doc phase ("read the slice-doc-plan
doc and execute", diff-based, single writer, gated by the driver's own
lint+build+test sweep). Phases appended by the consult or the test phase
re-enter the loop through a generation bar: the first generation appends
only work the plan owes and no phase delivered, the second blocking work
only, a third pending generation bails to the operator.

The driver's part in the slice's close-out report (<slice>/close-out.md —
${CLAUDE_PLUGIN_ROOT}/docs/close-out.md): create it if the plan loop did
not, name it and close_out.py (the only way to write to it) in every
dispatch, enter refuted findings and funding-consult merges through that
tool, render it into reading order before the doc phase and at completion,
stamp the run header at completion.

The plan doc is writable by every agent in the loop — deliberately. The
driver's job is keeping the shared doc parseable: a parse error, a vanished
phase, or a missing/unknown Target is nudged back to the session that
produced it ("fix the plan doc"), never treated as fatal while a session can
fix it. Bails are errors (exit 3) and operator questions (exit 4) only.

Every spawned agent must end by writing the verdict JSON file named in its
dispatch prompt and leave the worktree committed; a session that misses
either gets one resume-nudge, after which a missing verdict counts as
`blocked` and an uncommitted tree bails. A session the account's
session-limit window killed is not an agent outcome at all: the driver waits
out the stated reset and redispatches the same round.

Execution state lives in <slice>/state.json (written atomically; the driver
is its only writer): known phase ids, per-phase rounds, the bail-out and
appended-phase records, per-session transcript paths. Session outputs land
in <slice>/phases/P<id>/ (review docs, gate logs, verdicts); executor inputs
come from plan.md, never from copies. A phase may target the specs repo
itself, which holds that whole record — so the `slices/` tree stays out of the
driver's git queries there (_bookkeeping_pathspec).

All driver and session output goes to <slice>/log.txt (tail -f to watch);
stdout carries the log-file line plus one terse timestamped line per major
transition (each job start, each phase merged, the close-out summary) so a
watching caller can follow progress cheaply; -v/--verbose echoes the full
log there too.

Usage:
    run_loop.py run <slice-dir> [--resume] [--verbose] [--dry-run]
    run_loop.py status <slice-dir>

Exit codes: 0 slice complete · 3 bailed on an error (bailout.json written) ·
4 bailed with an operator question (bailout.json written) ·
2 usage/precondition error · 1 unexpected error.
"""

import argparse
import fcntl
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_config  # noqa: E402
from close_out import (  # noqa: E402
    ReportError,
    append_entry,
    counts_line,
    dispatch_line,
    entry_counts,
    init_report,
    render_report,
    report_path,
    stamp_header,
)

# ---------------------------------------------------------------------------
# Configuration — the one place models and efforts are set. Every outer
# dispatch passes its model/effort explicitly (`kc session create-headless
# --model M --reasoning-effort E`); sub-agents inherit from the dispatching
# session, which is the intended mechanism. The always-Sonnet agents
# (test-agent, test-fixer, rebase-agent) additionally pin `model:` in their
# own definitions, so they stay Sonnet even when dispatched as sub-agents.
# ---------------------------------------------------------------------------

MODELS: dict[str, tuple[str, str | None]] = {
    "code-writer": ("opus", "xhigh"),
    "code-reviewer": ("opus", "xhigh"),
    "doc-writer": ("opus", "xhigh"),
    "consult": ("opus", "xhigh"),
    "test-agent": ("sonnet", None),
}

# The plugin name. Installed agents resolve as `dev:<role>`; the driver
# dispatches by the namespaced name so the lookup cannot land on a
# same-named agent the target repo happens to ship.
AGENT_NAMESPACE = "dev"

# Roles the driver dispatches with --agent, plus the sub-agents the procedure
# docs route to. `kc session create-headless --agent` does not validate the
# name — an unknown agent spawns a plain SDK session that answers anyway — so
# the driver asserts these definitions exist before any dispatch.
REQUIRED_AGENTS = ("code-writer", "code-reviewer", "doc-writer",
                   "test-agent", "test-fixer", "rebase-agent")

# Where those definitions live: this script is <plugin>/tools/run_loop.py, so
# the agents ship one level up. Resolved from __file__, not the target repo —
# the workflow is plugin-shipped and a run can target any repo.
AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"

TIMEOUTS = {
    "code-writer": 7200,
    "code-reviewer": 3600,
    "consult": 1800,
    "test-agent": 14400,   # includes a CI build wait and live checks
    "doc-writer": 7200,
}

GATE_TIMEOUT = 3600
NUDGE_TIMEOUT = 900

# The loop-tail sweep and the doc gate run all three verbs; the per-phase
# gate stays test-only (lint/build breakage there surfaces at loop tail,
# where fixing it costs one phase instead of a per-phase tax).
SWEEP_VERBS = ("lint", "build", "test")

GATE_FIX_CAP = 3       # executor fix rounds against a red gate, per phase
# Nudges at the test session over a repo it committed to but never pushed.
# The driver checks rather than pushes: a slice touching several repos may
# need an order only the agent running the verification knows.
PUSH_NUDGE_CAP = 2
# The review loop's runaway backstop, not its working budget. Round 1's fix
# is automatic; from round 2 on a funding consult judges every `issues`
# verdict against a bar that rises each round (_review_bar) BEFORE an
# executor round is spent.
REVIEW_ROUND_CAP = 5
# Append-phase generations (completion consult + test phase): the first
# absorbs in-scope touch-ups, the second appends blocking work only, a third
# pending generation bails to the operator.
GENERATION_CAP = 2

# The spawn environment of every dispatched session (plan_loop imports it).
# Ephemeral sessions must not pay the 1-hour cache-write premium; and the
# prefix they carry on every turn is trimmed of what no headless role uses —
# the operator's auto-memory (per-user, per-cwd, never read or written by a
# dispatched role) and Claude Code's bundled skills (code-review, dataviz,
# … — never invoked by one). Measured 2026-08-23 at ctx1 −3.3 k tokens per
# session (≈ 10 % of the 32 k prefix), identical across roles. The plugin's
# own agents and skills still register.
SPAWN_ENV = {
    "FORCE_PROMPT_CACHING_5M": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
}

# The claude flags `create-headless` passes through to the spawned claude
# (kc's own pass-through, under claude's flag names), finishing the prefix
# trim SPAWN_ENV starts — agent-dispatch.md § Spawning has the why and the
# numbers. `--disable-slash-commands` for every role (the plugin's agents
# are not skills and still register); `--strict-mcp-config` for every role
# but the test-agent, which keeps the operator's MCP servers because it
# drives CI through Jenkins. Sub-agents inherit the parent's trim.
SPAWN_FLAGS = ("--disable-slash-commands",)
MCP_ROLES = frozenset({"test-agent"})


def spawn_flags(role: str | None) -> list[str]:
    """The pass-through flags for one dispatch — or for the nudge of one,
    which resumes the same session and must carry the same prefix."""
    flags = list(SPAWN_FLAGS)
    if role not in MCP_ROLES:
        flags.append("--strict-mcp-config")
    return flags

# The devlock wait: poll the flock nonblocking so the wait is loggable and
# bounded (a session crash releases the lease via fd close, so a very long
# hold is a stuck holder, not a working one).
DEVLOCK_POLL = 15
DEVLOCK_MAX_WAIT = 4 * 3600

# The account's session-limit window: a session killed by it surfaces the
# API's notice ("You've hit your session limit · resets 10:10pm
# (Europe/Amsterdam)") as its whole output instead of doing any work. That is
# an account state, not an agent outcome — the driver waits it out and
# redispatches the same round.
SESSION_LIMIT_RE = re.compile(r"you[’']ve hit your session limit", re.IGNORECASE)
SESSION_LIMIT_RESET_RE = re.compile(
    r"resets\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)"
    r"(?:\s*\((?P<zone>[^)]+)\))?", re.IGNORECASE)
SESSION_LIMIT_GRACE = 300         # the stated reset is approximate: wait past it
SESSION_LIMIT_FALLBACK = 1800     # no parseable reset: retry in half an hour
SESSION_LIMIT_MAX_SLEEP = 12 * 3600   # no single wait may exceed this

VERDICTS = {
    "code-writer": {"done", "question", "blocked"},
    "code-reviewer": {"signoff", "issues", "critical"},
    "test-agent": {"clean", "findings", "blocked"},
    "doc-writer": {"done", "question", "blocked"},
}


class Bailout(Exception):
    """A terminal stop. `question=True` marks an operator question (exit 4);
    everything else is an error (exit 3)."""

    def __init__(self, reason: str, phase: str | None = None,
                 details: str = "", consult: str | None = None,
                 question: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.phase = phase
        self.details = details
        self.consult = consult
        self.question = question


# Every timestamp the loops write or print is the operator's local wall clock
# (the process's TZ, UTC if unset) — these are read by the human watching the
# run, never compared across hosts. The ISO stamps stay offset-aware, so they
# remain unambiguous for anything that parses them back.
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# The plugin manifest beside this tools/ directory — the installed clone has
# the same layout as the repo.
PLUGIN_MANIFEST = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


def plugin_version() -> str | None:
    """The version of the plugin this loop runs from, for the state file —
    so a slice's record says which plugin produced it and runs can be read
    before/after a change. None when the manifest is unreadable (a loop is
    never held up by its own bookkeeping)."""
    manifest = _read_json(PLUGIN_MANIFEST) or {}
    return manifest.get("version") or None


def _protocol_failure_detail(role: str, returncode: int, verdict: dict | None,
                             verdict_name: str, valid: bool,
                             nudged: bool) -> str:
    """Explain why a dispatch is treated as a protocol failure.

    The return code and the verdict's validity are independent axes: a session
    can be killed (rc != 0) *after* it committed and wrote a perfectly good
    verdict — e.g. a SIGTERM'd worker exits 143 — so the two are reported
    separately."""
    if verdict is None:
        vstate = "missing/unparseable"
    elif not valid:
        vstate = f"invalid outcome {verdict.get('outcome')!r}"
    else:
        vstate = f"valid outcome {verdict.get('outcome')!r}"
    return (
        f"{role} session ended rc={returncode}; verdict file "
        f"{verdict_name}: {vstate}"
        + (" (after one nudge)" if nudged else "")
    )


def session_limit_notice(result) -> str | None:
    """The API's session-limit notice in a session's final text, or None."""
    text = getattr(result, "result_text", "") or ""
    return text.strip() if SESSION_LIMIT_RE.search(text) else None


def parse_session_limit_reset(text: str,
                              now: datetime | None = None) -> datetime | None:
    """The moment the limit window reopens, from the notice's stated reset
    ("resets 10:10pm (Europe/Amsterdam)").

    A 12-hour clock with no date, so a reset that already passed today is
    tomorrow's. Returns None when the text states no parseable time, or names
    a zone this host does not know — the caller then falls back to a short
    fixed wait rather than guessing a wall-clock offset."""
    match = SESSION_LIMIT_RESET_RE.search(text)
    if not match:
        return None
    zone = match.group("zone")
    if zone:
        try:
            tz = ZoneInfo(zone.strip())
        except (KeyError, ValueError):
            return None
    else:
        tz = datetime.now().astimezone().tzinfo
    minute = int(match.group("minute") or 0)
    if minute > 59:
        return None
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower().startswith("p"):
        hour += 12
    now = now.astimezone(tz) if now else datetime.now(tz)
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return reset


def _transcript_path(cwd: Path | str, session_id: str | None) -> str | None:
    """The Claude Code transcript file for a session spawned with this cwd:
    ~/.claude/projects/<munged-cwd>/<session-id>.jsonl. The munge mirrors
    Claude Code's project-dir encoding: every non-alphanumeric path character
    becomes '-'. Recorded in state.json so a later session can research any
    agent's conversation without reverse-engineering this mapping."""
    if not session_id:
        return None
    munged = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(cwd).resolve()))
    return str(Path.home() / ".claude" / "projects" / munged
               / f"{session_id}.jsonl")


def _orchestrator_record() -> dict | None:
    """The interactive session that launched this run (Claude Code exports
    its id to Bash children), so cost attribution can count the orchestrator.
    None when run by hand."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    return {"session": sid, "transcript": _transcript_path(Path.cwd(), sid)}


def spec_root_for(slice_dir: Path) -> Path | None:
    """The spec repo root: the parent of the `slices/` tree the slice sits in
    (`slices/NNN_slug`, `slices/backlog/NNN_slug`, … all resolve the same)."""
    for parent in slice_dir.parents:
        if parent.name == "slices":
            return parent.parent
    return None


# ---------------------------------------------------------------------------
# Plan parsing — `### P<id> — <title>` headings, ids [A-Za-z0-9]+, document
# order authoritative. Every ### heading in the plan is a phase heading;
# done-records live under the heading without introducing new ###s.
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^###\s+(.*)$")
PHASE_RE = re.compile(r"^###\s+P([A-Za-z0-9]+)\s+—\s+(.+?)\s*$")
DONE_STAMP_RE = re.compile(r"✅\s*DONE\b")
TARGET_RE = re.compile(r"^\s*\**Target\**\s*:\**\s*`?([^`]+?)`?\s*$")
PUSH_HOLDS_RE = re.compile(r"^##\s+Push holds\s*$", re.IGNORECASE)
HOLD_RE = re.compile(r"^\s*[-*]\s+\**`?(\S+?)`?\**\s+—\s+(\S.*?)\s*$")


class Phase:
    def __init__(self, id_: str, title: str, line_no: int):
        self.id = id_
        self.title = title       # includes any ✅ DONE stamp text
        self.line_no = line_no   # 0-based index of the heading line
        self.body: list[str] = []
        self.done = bool(DONE_STAMP_RE.search(title))
        self.target: str | None = None

    def resolve_target(self) -> None:
        for line in self.body:
            match = TARGET_RE.match(line)
            if match:
                self.target = match.group(1).strip()
                return


def parse_plan(text: str) -> tuple[list[Phase], list[str]]:
    """(phases in document order, structure errors). Errors name what a
    fixing session needs: the offending heading or phase and what is wrong.
    A DONE phase is not required to still carry a Target — only work the
    driver may yet dispatch needs one."""
    phases: list[Phase] = []
    errors: list[str] = []
    current: Phase | None = None
    for line_no, line in enumerate(text.splitlines()):
        heading = HEADING_RE.match(line)
        if heading:
            match = PHASE_RE.match(line)
            if not match:
                errors.append(
                    f"line {line_no + 1}: `### {heading.group(1)}` is not a "
                    "phase heading (`### P<id> — <title>`, id [A-Za-z0-9]+)")
                current = None
                continue
            current = Phase(match.group(1), match.group(2), line_no)
            phases.append(current)
        elif current is not None:
            current.body.append(line)
    seen: set[str] = set()
    for phase in phases:
        if phase.id in seen:
            errors.append(f"phase id P{phase.id} appears more than once "
                          "(ids are labels, but they must be unique)")
        seen.add(phase.id)
        phase.resolve_target()
        if not phase.done and not phase.target:
            errors.append(f"phase P{phase.id} has no `Target:` line")
    return phases, errors


def parse_push_holds(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(held target → why, structure errors) from `## Push holds` — the one
    `##` section the driver reads. A repo listed there is one this slice must
    not push: the push check reports it held instead of nudging the test
    session and bailing. Prose and comments in the section are ignored; a
    bullet that is not a hold is a structure error, because a hold the driver
    silently missed is a repo it would push."""
    holds: list[tuple[str, str]] = []
    errors: list[str] = []
    in_section = in_comment = False
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines()):
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if line.startswith("#"):
            in_section = bool(PUSH_HOLDS_RE.match(line))
            continue
        if not in_section or not line.lstrip().startswith(("-", "*")):
            continue
        match = HOLD_RE.match(line)
        if not match:
            errors.append(
                f"line {line_no + 1}: `{line.strip()}` is not a push hold "
                "(`- <target> — <why>`, em dash, target written as a phase "
                "writes its `Target:`)")
            continue
        target, why = match.group(1).strip(), match.group(2).strip()
        if target in seen:
            errors.append(f"line {line_no + 1}: `{target}` is held twice")
            continue
        seen.add(target)
        holds.append((target, why))
    return holds, errors


# ---------------------------------------------------------------------------
# The phase digest — the writer's orientation, rendered into its dispatch
# from what the driver already holds: the plan as it stands (rulings land
# mid-run, so it is rebuilt per round), verification.json, the slice's
# intent paragraph, and git. The plan stays the writer's to edit; the digest
# is what it reads instead of the whole file.
# ---------------------------------------------------------------------------

# The done-record's opener — `**Done (P<id>).**` (`**Done (r1).**`, `**Done
# (<date>).**`: the parenthesis is free). Universal before it was written
# down (296 of 296 done phases across both spec repos, 2026-08-23); the digest
# reads a done phase's record from that line to the end of its section. A
# done phase without one contributes its whole section — bounded by the
# ~a-page contract, never skipped.
DONE_RECORD_RE = re.compile(r"^\s*\*\*Done\b")
# The plan's prose sections the digest carries verbatim, by `##` heading
# prefix (case-insensitive): the requirements/rulings (authoritative on
# intent) and what the slice leaves out.
DIGEST_SECTIONS = ("requirements", "not in scope")
# `git diff --stat` rows kept per repo before the digest elides the middle.
DIGEST_STAT_LINES = 40


def plan_sections(text: str) -> tuple[str, dict[str, list[str]]]:
    """(the plan's title line without its `# `, `##` section heading → its
    lines including the heading). A section runs to the next `##` heading
    or to the first phase heading (`###`) — the phases are not prose."""
    title = ""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif HEADING_RE.match(line):
            current = None
        elif current is not None:
            sections[current].append(line)
    return title, sections


def slice_intent(slice_text: str) -> str:
    """The first paragraph of slice.md after its title — the slice's intent
    in the triage session's words. Empty when the file has none."""
    lines = slice_text.splitlines()
    start = 0
    if lines and lines[0].startswith("# "):
        start = 1
    para: list[str] = []
    for line in lines[start:]:
        if line.strip():
            para.append(line)
        elif para:
            break
    return "\n".join(para)


def done_record(phase: Phase) -> list[str]:
    """A done phase's record: from its `**Done` opener to the end of the
    section, or the whole section when no opener is there."""
    body = phase.body
    for i, line in enumerate(body):
        if DONE_RECORD_RE.match(line):
            body = body[i:]
            break
    return _strip_blank(body)


def _strip_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _trim_stat(stat: str) -> str:
    lines = stat.splitlines()
    if len(lines) <= DIGEST_STAT_LINES:
        return stat
    kept = lines[:DIGEST_STAT_LINES - 1]
    return "\n".join(kept + [f" … {len(lines) - DIGEST_STAT_LINES} more files",
                             lines[-1]])


def build_phase_digest(plan_text: str, phase_id: str, intent: str,
                       criteria: list[dict], touched: list[tuple[str, str]],
                       ) -> str:
    """The digest for phase `phase_id`, rendered as Markdown for the
    dispatch. `intent` is the slice's intent paragraph (`slice_intent`),
    `criteria` verification.json's items, `touched` (repo, `git diff --stat`
    text) per repo earlier phases changed. Empty parts are left out; a phase
    the plan does not carry digests to the slice parts only (the driver has
    already parsed the plan, so that is a race with an edit, not a
    structure error)."""
    title, sections = plan_sections(plan_text)
    phases, _ = parse_plan(plan_text)
    out: list[str] = ["---", "", f"# Orientation digest — phase P{phase_id}", ""]
    if title:
        out += [f"**Slice.** {title}", ""]
    if intent:
        out += [intent, ""]
    for name, lines in sections.items():
        if name.lower().startswith(DIGEST_SECTIONS):
            out += _strip_blank(lines) + [""]

    idx = next((i for i, p in enumerate(phases) if p.id == phase_id), None)
    if idx is not None:
        phase = phases[idx]
        out += ["## Your phase", "", f"### P{phase.id} — {phase.title}", ""]
        out += _strip_blank(phase.body) + [""]
        earlier, later = phases[:idx], phases[idx + 1:]
        if earlier:
            out += ["## Settled by earlier phases (their done-records)", ""]
            for p in earlier:
                out += [f"### P{p.id} — {p.title}", ""]
                out += (done_record(p) if p.done
                        else [f"Target: {p.target}", "(not done yet)"]) + [""]
        if later:
            out += ["## Later phases (edit them in the plan if your work "
                    "changes them)", ""]
            out += [f"- P{p.id} — {p.title} (Target: {p.target})"
                    for p in later] + [""]
    if criteria:
        out += ["## Acceptance criteria (verification.json — the test phase "
                "checks them off, not you)", ""]
        for item in criteria:
            area = item.get("area")
            tag = f" ({area})" if area else ""
            out.append(f"- {item.get('id', '?')}{tag} — "
                       f"{item.get('description', '')}")
        out.append("")
    if touched:
        out += ["## Files earlier phases touched", ""]
        for repo, stat in touched:
            out += [f"{repo}:", "", "```", _trim_stat(stat), "```", ""]
    return "\n".join(out).rstrip() + "\n"


def stamp_phase(plan_path: Path, phase_id: str, date: str) -> bool:
    """Append `✅ DONE <date>` to the phase's heading line — the driver's
    mechanical stamp, applied after review passed and the merge landed.
    Returns False when the heading is not there (the caller re-parses and
    routes that as a vanished phase)."""
    lines = plan_path.read_text().splitlines(keepends=True)
    pattern = re.compile(r"^###\s+P" + re.escape(phase_id) + r"\s+—\s+")
    for i, line in enumerate(lines):
        if pattern.match(line) and not DONE_STAMP_RE.search(line):
            lines[i] = line.rstrip("\n") + f" ✅ DONE {date}\n"
            plan_path.write_text("".join(lines))
            return True
    return False


# ---------------------------------------------------------------------------
# kc integration — project discovery, session drive, repo root
# ---------------------------------------------------------------------------


def _git_toplevel() -> Path:
    """The target repo's root, from `git rev-parse --show-toplevel` in the
    process cwd — not from __file__, which locates the plugin the driver
    ships in, never the repo being run."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository (run the slice from the "
              "target repo).", file=sys.stderr)
        sys.exit(2)
    return Path(result.stdout.strip())


def load_project_dirs(cwd: Path) -> dict[str, Path]:
    """The valid component set + each component's *effective* cwd, from the
    target repo's `.kubecoder/project.yaml` via `kc project list
    --output=json`. The JSON is a bare array of {name, cwd, description} in
    manifest order; `cwd` is absolute and already resolved."""
    result = subprocess.run(
        ["kc", "project", "list", "--output=json"],
        cwd=str(cwd), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise Bailout(
            "protocol_failure",
            details="`kc project list --output=json` failed "
                    f"(rc={result.returncode}): "
                    f"{(result.stderr or result.stdout).strip()}",
        )
    try:
        entries = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        raise Bailout(
            "protocol_failure",
            details=f"`kc project list --output=json` emitted invalid JSON: {e}",
        ) from None
    return {e["name"]: Path(e["cwd"]) for e in entries}


class SessionResult:
    """The bits of a driven turn the driver consumes downstream: the claude
    sessionId (for --resume across rounds and the transcript locator) and the
    turn's final response text (read ONLY by session_limit_notice — outcomes
    always come from verdict files)."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.result_text: str = ""
        self.is_error: bool = False


def _kc_session_id(name: str, cwd: Path) -> str | None:
    """The claude sessionId from the headless status snapshot. `sessionId` is
    empty until the first turn has run, so this is read *after* send."""
    try:
        result = subprocess.run(
            ["kc", "session", "status", name, "--output=json"],
            cwd=str(cwd), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        snapshot = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return snapshot.get("sessionId") or None


def _kc_send(name: str, prompt: str, cwd: Path, timeout: int,
             progress) -> tuple[int, str]:
    """POST one turn to a headless session and consume its response to the
    terminal result (`kc session send` owns SSE reconnect). The condensed log
    (send's stderr under -v) streams to `progress`; the response text is
    returned so the caller can recognize the account's session-limit notice.

    Enforces `timeout`: on expiry it SIGINTs `kc session send`, which POSTs a
    worker interrupt so the turn is never stranded, then raises
    subprocess.TimeoutExpired (the caller's policy turns that into a bail)."""
    prompt_fd, prompt_path = tempfile.mkstemp(suffix=".prompt")
    resp_path = prompt_path + ".resp"
    try:
        with os.fdopen(prompt_fd, "w") as f:
            f.write(prompt)
        args = ["kc", "session", "send", name,
                "--prompt-file", prompt_path,
                "--response-file", resp_path, "-v"]
        proc = subprocess.Popen(
            args, cwd=str(cwd), text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                ready, _, _ = select.select(
                    [proc.stderr], [], [], min(remaining, 1.0))
                if ready:
                    line = proc.stderr.readline()
                    if not line:
                        break  # stderr EOF — the send is finishing
                    if progress:
                        progress(line.rstrip("\n"))
                elif proc.poll() is not None:
                    break
            proc.wait(timeout=30)
            try:
                response_text = Path(resp_path).read_text()
            except OSError:
                response_text = ""
            return proc.returncode, response_text
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)  # send POSTs an interrupt on SIGINT
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
    finally:
        for p in (prompt_path, resp_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def run_kc_session(
    prompt: str,
    cwd: str,
    timeout: int,
    agent: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    resume_session: str | None = None,
    extra_env: dict[str, str] | None = None,
    flags: Sequence[str] | None = None,
    progress=None,
    on_session=None,
) -> tuple[int, SessionResult]:
    """Drive one headless kc session to completion; return (returncode,
    result). Maps each seam onto a kc verb:
      create-headless [--resume ID] [--agent ROLE] [--model M]
                      [--reasoning-effort E] --cwd CWD [-e NAME=VALUE ...]
                      [FLAG ...]                 → the assigned session name
      send NAME --prompt-file P --response-file R -v   (synchronous; SSE)
      status NAME --output=json                  → the claude sessionId
      end NAME                                    (idempotent; always)

    `agent` is the bare role (e.g. "code-writer"); it is dispatched namespaced
    (`dev:code-writer`) and resolves to the plugin's own definition wherever
    `cwd` sits. A falsy `agent` spawns with no agent at all (consults).
    `flags` are claude flags kc passes through verbatim (`spawn_flags`).
    Raises subprocess.TimeoutExpired on timeout — the turn is interrupted
    and the session torn down before it propagates."""
    result = SessionResult()

    create_args = ["session", "create-headless", "--cwd", str(cwd)]
    if resume_session:
        create_args += ["--resume", resume_session]
    if agent:
        create_args += ["--agent", f"{AGENT_NAMESPACE}:{agent}"]
    if model:
        create_args += ["--model", model]
    if effort:
        create_args += ["--reasoning-effort", effort]
    for name, value in (extra_env or {}).items():
        create_args += ["-e", f"{name}={value}"]
    create_args += list(flags or ())

    created = subprocess.run(
        ["kc", *create_args], cwd=str(cwd), capture_output=True, text=True)
    if created.returncode != 0:
        result.result_text = (created.stderr or created.stdout).strip()
        result.is_error = True
        return created.returncode or 1, result
    session_name = (created.stdout.strip().splitlines() or [""])[-1].strip()
    if not session_name:
        result.result_text = "kc session create-headless printed no session name"
        result.is_error = True
        return 1, result

    try:
        returncode, response_text = _kc_send(
            session_name, prompt, Path(cwd), timeout, progress)
        result.result_text = response_text
        result.session_id = _kc_session_id(session_name, Path(cwd))
        if on_session and result.session_id:
            on_session(result.session_id)
        result.is_error = returncode != 0
        return returncode, result
    finally:
        # Best-effort teardown: never let cleanup hang the driver or mask the
        # exception that is propagating (e.g. a timeout).
        try:
            subprocess.run(
                ["kc", "session", "end", session_name],
                cwd=str(cwd), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# The devlock — the cooperative occupancy lease over the single dev instance,
# a flock on the inode `devlock.lease` names (the spec repo is the shared
# mount every contending code repo can see, and devlock.sh flocks the same
# file). The driver holds it from whichever of the test and doc phases runs
# first to the end of the run: under that hold pushing and rolling dev for
# verification is pre-authorized — the lock IS the coordination. Held
# in-process so a driver crash releases it via fd close.
# ---------------------------------------------------------------------------

class DevLock:
    def __init__(self, lease: Path | None):
        self.lock_path = lease
        # devlock.sh's own convention: a human-readable note beside the lock.
        self.holder_path = lease.parent / "dev-holder" if lease else None
        self._fd = None

    @property
    def configured(self) -> bool:
        """A project that names no lease has nothing to coordinate — one dev
        instance is a fact about a deployed project, not about every repo the
        pipeline drives. The lock degrades to a no-op."""
        return self.lock_path is not None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def holder_note(self) -> str:
        try:
            return self.holder_path.read_text().strip()
        except (OSError, AttributeError):
            return "(no holder note)"

    def acquire(self, purpose: str, log, sleep) -> None:
        if not self.configured or self._fd is not None:
            return
        self._fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o644)
        deadline = time.monotonic() + DEVLOCK_MAX_WAIT
        logged = False
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not logged:
                    log("devlock held — waiting; holder:\n"
                        + self.holder_note())
                    logged = True
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise Bailout(
                        "devlock_timeout",
                        details="the dev occupancy lease stayed held for "
                                f"{DEVLOCK_MAX_WAIT}s; holder:\n"
                                + self.holder_note(),
                    ) from None
                sleep(DEVLOCK_POLL)
        session = os.environ.get("DEVLOCK_SESSION",
                                 f"run_loop[{os.getpid()}]")
        self.holder_path.write_text(
            f"session: {session}\npurpose: {purpose}\n"
            f"acquired: {_now_iso()}\npid: {os.getpid()}\n")
        log(f"devlock ACQUIRED ({purpose})")

    def release(self, log) -> None:
        if self._fd is None:
            return
        try:
            self.holder_path.unlink(missing_ok=True)
        except OSError:
            pass
        os.close(self._fd)
        self._fd = None
        log("devlock released")


# ---------------------------------------------------------------------------
# The slice lock — one driver per slice folder. A slice's run record lives in
# the spec repo, which is the mount every environment shares; the code repo it
# branches is not. Two drivers on one folder therefore write one log.txt, one
# state.json and one phases/** while branching two different repositories, and
# the second finds no phase branch where the record says work is committed —
# so it rebuilds the branch from base and the first driver's commit is gone
# with no trace in the record. flock, so a driver that dies releases it by
# construction and a --resume walks straight in; taken non-blocking, because a
# second driver is a mistake to report, not a queue to join.
# ---------------------------------------------------------------------------

class SliceLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd = None

    def acquire(self) -> str | None:
        """None when the lock is ours, the holder's note when it is not."""
        if self._fd is not None:
            return None
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            note = ""
            try:
                note = os.read(fd, 4096).decode(errors="replace").strip()
            except OSError:
                pass
            os.close(fd)
            return note or "(no holder note)"
        os.ftruncate(fd, 0)
        os.write(fd, (f"host: {socket.gethostname()}\npid: {os.getpid()}\n"
                      f"started: {_now_iso()}\n").encode())
        self._fd = fd
        return None

    def release(self) -> None:
        if self._fd is None:
            return
        os.ftruncate(self._fd, 0)
        os.close(self._fd)
        self._fd = None


# ---------------------------------------------------------------------------
# Dispatch prompts. Role contracts live in the agent definitions; prompts
# carry only instance data. Consults run bare, so their prompt is the
# protocol.
# ---------------------------------------------------------------------------

EXECUTOR_PROMPT = """\
Execute phase P{phase_id} of slice {slice_name}: implement exactly that
phase. Its Target is {target}; work on branch {branch}, which is checked
out{where}. The repo is truth for current state, the plan for intent.

The plan is digested below — your phase whole and everything settled
around it, from the plan as it stands. The plan itself is {plan_path}: edit
it there (your done-record, later phases your work changes) and open it for
what the digest points at — an attachment, a later phase's text — rather
than re-reading it whole.

Run the phase's test gate yourself before handing back{gate_hint}.

When done:
- Append the phase's done-record in the plan, under the phase's own heading
  (never a new `###` heading), opening `**Done (P{phase_id}).**` — what
  landed, what settled beyond the plan's text, what changes for later
  phases; hard cap ~25 lines, settlements not narration. Edit later phases
  your work changes, in place.
- Commit everything: code on the branch; the plan edit in the specs repo,
  staged by name (shared working tree).
- Write your verdict to {verdict_path}.
{pointers}"""

# Carried by every dispatch that writes or reviews code. The project's
# change-discipline doc lives at a path only the config knows, and
# code-writer's "delete, don't tombstone" rule defers to it by name.
PHILOSOPHY_LINE = """
This project's change-discipline doc is {philosophy} — its rules bind this
work.
"""

# Carried by every dispatch: where the slice's close-out report is and that
# close_out.py is the only way to write to it (close_out.dispatch_line — one
# sentence, shared with the plan loop). The agent registers hold the rule
# (out-of-scope observations go there, append only), the tool mints the
# shape — the prompt carries the path and the tool, once.
CLOSE_OUT_LINE = """
{dispatch_line}
"""

# Carried by every executor dispatch whose target repo holds the slice
# folder — the specs repo as a `Target:`. The driver's run record is written
# into that tree while the session works; an agent that sweeps it into a
# commit takes the live log with it at the merge's `git checkout <base>`.
BOOKKEEPING_NOTE = """
The slice folder {slice_dir} sits inside this phase's target repo, and
everything the driver writes there — log.txt, state.json, phases/ — is the
live record of this run, changing while you work. Stage what you commit by
name, never `git add -A`, and commit none of those. The plan doc is yours to
edit as always.
"""

EXECUTOR_GATE_FIX_PROMPT = """\
The test gate for phase P{phase_id} of slice {slice_name} is red (branch
{branch}, fix round {round}). The plan: {plan_path}, digested below.

The gate command was `{gate_cmd}`; its output is in {gate_log}. The gate is
fail-fast and terse, so the log ends at the FIRST failing statement — there
may be more behind it. The phase's work so far is git diff
{merge_base}..HEAD{where}. Make the gate green without weakening what it
checks; test your own work before handing back. Commit your fixes, update the
phase's done-record if what landed changed, then write your verdict to
{verdict_path}.
{pointers}"""

EXECUTOR_REVIEW_FIX_PROMPT = """\
You are resolving review findings for phase P{phase_id} of slice
{slice_name}. The plan: {plan_path}, digested below.

The code-reviewer found issues with the phase's branch (the work under review
is git diff {merge_base}..HEAD on {branch}{where}). Read {review_path} and
resolve every finding tagged blocking — the reviewer describes problems; the
fix design is yours.
Resolve each blocking finding failure-first. If its anchor is executable — a
failing test, a repro trace, analyzer output — witness the failure before
changing code: write the failing test or run the claimed repro. Witnessed,
fix it; the witnessing test rides your commit as the regression test. If you
cannot make it fail, the finding is refuted: change no code for it and report
it in your verdict's `refuted` list — its id plus one line of evidence, what
you ran or wrote and why it cannot fail. The loop records the refutation; do
not argue it in prose. Findings anchored by inspection — a requirement
contradiction, a coverage gap — have no failure to witness: check the cited
requirement and resolve them directly.
Findings tagged advisory are NOT yours to fix: they stay in the review file
and the close-out report, and the residue rider mops up the mechanical ones.
An advisory fixed here widens the next round's re-review to everything the
fix touched and breeds its own findings — comment fixes especially. Leave
them. The phase's section in the plan carries its intent; earlier rounds'
reviews sit next to this one — check them before re-deciding anything.
For a finding about prose the default fix is deleting or narrowing the claim,
not rewording it — a fix that grows the section is suspect. Run the gate
yourself before handing back{gate_hint}. Commit your fixes, update the
phase's done-record if what landed changed, then write your verdict to
{verdict_path}.
{pointers}"""

# Appended by the driver to a round's review file when the fix round refuted
# findings, so the next round's reviewer reads the refutation where it reads
# the findings — one record, never relitigated.
REFUTATION_TAG = """

## Refuted findings (fix round after review round {round})

The fix round witnessed each of these findings' claimed failures and could
not make them fail. They are refuted — settled by that evidence and
recorded in the close-out report with the refutation attached; they fund no
further work:

{entries}
"""

OPERATOR_RULING_TAG = """

## Operator ruling (post-round-{round} question)

The fix round's executor bailed with a question:

> {question}

The operator has ruled. The ruling is in the plan doc's requirements/rulings
section — living text, authoritative. Read it there and implement it as part
of resolving this review.
"""

REVIEWER_PROMPT = """\
Review the complete branch diff for phase P{phase_id} of slice {slice_name}
(review round {round}): git diff {merge_base}..HEAD on branch
{branch}{where}.

The requirements are the phase's section in {plan_path} — its outcome and
constraints; read the whole plan for context, and treat its
requirements/rulings section as authoritative on intent — plus the slice's
acceptance criteria in {verification_path} and this repo's conventions.
Judge outcomes, not approach. The slice spans multiple phases — only this
phase's scope is under review; end-to-end testing and prose docs have their
own later phases, so their absence here is not a finding.

{gate_line}
{philosophy_line}{close_out_line}
Write your review to {review_path} and your verdict to {verdict_path}.
"""

REVIEWER_DELTA_PROMPT = """\
Re-review phase P{phase_id} of slice {slice_name} (review round {round}) on
branch {branch}{where}. Round {prev_round} reviewed the full branch diff and
found issues: {prev_review}. The executor's response since then is git diff
{fix_range} — that range is this round's subject; the rest of the branch
(git diff {merge_base}..HEAD) was reviewed last round and is context, not
re-review scope.

Verify that every round-{prev_round} finding tagged blocking is actually
resolved — re-open the code, do not take the executor's word — and review
the fix commits themselves for new problems, including interactions with the
branch code they touch. Advisory findings left unfixed are the protocol
working, not a gap — they are in the review file and the close-out report;
do not re-report them. A finding the fix round refuted — witnessed as
unable to fail, per the refutation record appended to the prior review — is
settled by that evidence: do not re-raise it unless a fix commit
invalidates the refutation. Ground the prior round already proved stays proved: re-derive a
premise (live system state, another repo's behavior) only where a fix commit
touches it. The requirements are unchanged: the phase's section in
{plan_path} and the acceptance criteria in {verification_path}.

{gate_line}
{philosophy_line}{close_out_line}
Write your review to {review_path} and your verdict to {verdict_path}.
"""

# Stated in every reviewer dispatch so the review does not spend turns
# re-running the suite the driver already ran. The green claim is only made
# when it is backed by this commit (see _gate_line) — a reviewer told "green"
# about a different commit would be worse than one told nothing.
GATE_GREEN_LINE = """\
The deterministic test gate ran GREEN on this exact commit ({green_at}):
`{gate_cmd}` — with full output in {gate_log}. Tests and lints pass; that is
an established input to your review, not something to re-derive.
Do not re-run the suite or the linter to confirm it. Targeted runs remain
yours to make where they buy a finding: a single test you suspect is vacuous,
a case the diff leaves uncovered, a mutation that proves a test actually
catches the behavior it claims. The green says the tests pass, never that
they are adequate.\
"""

GATE_UNVERIFIED_LINE = """\
No deterministic test gate is recorded green against this commit — treat the
branch's test and lint state as unverified, and say so in your review if it
bears on a finding.\
"""

# The review-funding bar: stated by the driver (which knows the round number
# and what the fix range touched), judged by the consult (which reads the
# findings). Discrete steps — each admits roughly an order of magnitude fewer
# findings: round cost is flat while the marginal value of review rounds
# decays hard.
REVIEW_BAR_BLOCKING = """\
Fund a fix round only for findings the review shows to be blocking — merging
them would harm the product (data corruption, a broken flow, a wire-contract
claim a consumer would implement against). Advisory, Minor-only, or
prose-only findings go to the close-out report, not a fix round here.\
"""
REVIEW_BAR_BLOCKER = """\
Only Blocker-grade harm funds another round — data corruption, a broken core
flow, a wire-contract falsity a consumer would implement against. Ordinary
Majors, and anything prose, merge and go to the close-out report.\
"""
REVIEW_BAR_CRITICAL = """\
Only a `critical` verdict — the phase's premise or the slice itself in
question — funds another round. Everything else merges (recorded in the
close-out report) or bails.\
"""

REVIEW_PROSE_FACT = """\
Deterministic fact from the driver: the fix commits this round reviewed
({fix_range}) touched no production code — only tests and docs — so the bar
below is already one step above this round's default.

"""

REVIEW_FUNDING_SITUATION = """\
Review round {round} for phase P{phase_id} reported `{outcome}`: the findings
are in {review_path}, each tagged blocking or advisory. The executor has not
yet acted on them. Decide whether they fund another executor fix round, or
the phase merges now — findings never vanish: on merge, every unresolved
finding stays in the review file and the driver records the merge in the
close-out report for the operator.

{prose_fact}This is review round {round} of at most {cap} for this phase; the
funding bar rises every round, and at this round it is:

{bar}

Judge the findings against that bar on the review's own evidence. A red gate
cannot merge regardless of your choice.\
"""

REVIEW_BUDGET_SITUATION = """\
Review round {round} for phase P{phase_id} reported `{outcome}`
({review_path}) and this phase's review budget ({cap} rounds) is exhausted —
no further fix round can be funded. Decide whether the phase merges with its
unresolved findings recorded in the close-out report for the operator, or the
slice stops.\
"""


def _review_bar(round_: int, prose_only: bool) -> str:
    """The funding bar for a consulted review round. A prose-only fix range
    (no production code touched) applies the next round's bar a step early."""
    effective = round_ + (1 if prose_only else 0)
    if effective <= 2:
        return REVIEW_BAR_BLOCKING
    if effective == 3:
        return REVIEW_BAR_BLOCKER
    return REVIEW_BAR_CRITICAL


# The generation bar on appended work (completion consult + test phase).
GENERATION_BARS = {
    1: """\
This is the loop's first follow-up generation: append a phase only for work
the plan owes and no phase delivered — a requirement or ruling nothing
carried out, an acceptance criterion with no implementing work to point at.
Price it: a phase costs an executor round, a review round and the consult
this generation forces; a close-out entry costs the operator one word.
Everything else — out of scope, advisory, in scope but not owed — goes in
the close-out report, never a phase.\
""",
    2: """\
This is the loop's second follow-up generation: append BLOCKING work only —
work without which the slice's acceptance criteria are not met or the product
is harmed. Everything else goes in the close-out report. A generation after
this one bails to the operator, so append nothing you would not stop the
slice over.\
""",
}

# The rider holds at every generation: run-created mechanical residue is
# fixed on the spot — a fix is not a report.
GENERATION_RIDER = """\
Exception, at every generation: mechanical residue — comment or formatting
fixes with no behaviour change, in files this slice's diff already touched —
is neither reported nor appended. Fix it in this session: make the edit, keep
gofmt honest where the change is Go, and commit to the checked-out branch.
The driver's lint+build+test sweep re-runs on any commit it has not seen, so
the fix is gated before the loop closes — but never before a push your own
procedure doc orders, so keep the tree green as you commit.\
"""

COMPLETION_CONSULT_SITUATION = """\
Every phase of the plan is stamped done. Judge honestly, against both the
plan and the repo: does the plan describe outstanding work? Signals worth
checking: an acceptance criterion in {verification_path} whose implementing
work you cannot point at; a done-record that admits a leftover; a
requirement or ruling in the plan not delivered by any phase; a later phase
edited to depend on something nothing produced.

{sweep_block}

{generation_bar}

If outstanding work clears that bar, append new phases to {plan_path}
(`### P<id> — <title>` with a `Target:` line; a suffix like P3a inserts
between P3 and P4 — document order is authoritative) and answer `appended`.
Record everything that does not clear the bar as entries in the close-out
report — and you are the one pass that reconciles that report, through
close_out.py (its path is in this prompt) and never by editing the file:
strike what you absorbed into an appended phase (`strike <id> --reason
"absorbed by P<x> (<commit>)" --by "consult <n>"`), duplicates you are sure
of (`--reason "duplicate of B3"`), and what a phase resolved (`--reason
"resolved by P<x> (<commit>): <what was re-run>"`); record any other
observation about an entry with `note`. If nothing is outstanding, answer
`complete`.\
"""

# The loop-tail sweep's report, as it rides the completion-consult and
# test-phase dispatches. Same contract as _gate_line's green claim: stated
# only about the exact commits it ran on (the driver re-sweeps whenever a
# swept HEAD moves, so the report a dispatch carries always describes the
# tree that dispatch sees).
SWEEP_BLOCK = """\
Deterministic fact from the driver — the loop-tail gate sweep: `kc project
lint` + `build` + `test`, run per component so every red is visible, on
exactly these commits:

{rows}

{stance}\
"""

SWEEP_STANCE_CONSULT_GREEN = """\
Every row is GREEN: the merged tree lints, builds and tests clean — an
established input to your judgment, not something to re-derive or re-run.\
"""

SWEEP_STANCE_CONSULT_RED = """\
One principle, no special cases: a branch whose gates are red is not
pushed — and the test phase, which runs next, is where this slice is
pushed. A RED row above is therefore outstanding work on this consult's
table: append a phase that fixes it, or answer `bail` with the question.
Either is acceptable; what `complete` asserts is that the tree is pushable
exactly as it stands.\
"""

SWEEP_STANCE_TEST_GREEN = """\
Every row is GREEN: those suites pass, as an established input — do not
re-run them to confirm it. Targeted runs remain yours where they buy a
finding, and the re-validation your procedure doc orders after a rebase
still applies: a rebase produces a tree nothing has run against. One
principle, no special cases: a branch whose gates are red is not pushed —
a red you find after the rebase routes as a finding, without pushing.\
"""

SWEEP_STANCE_TEST_RED = """\
One principle, no special cases: a branch whose gates are red is not
pushed. A RED row above means this tree does not leave the machine as it
stands: route the red as a finding (append the fixing phase — a red gate
is blocking by definition), and push nothing until every gate is green.
The same holds for any red you find after the rebase.\
"""

SWEEP_STANCE_NONE = """\
No swept repo carries a kc manifest, so nothing ran — treat the tree's
lint/build/test state as unverified.\
"""

TEST_PHASE_PROMPT = """\
The phases of slice {slice_name} are all merged on {base_branch}. Run the
slice's test phase: read {test_plan_doc} and execute it for this slice — the
procedure, the gate semantics, and how findings route all live in that doc,
not in this prompt.

Deterministic facts from the driver:
- The driver holds the devlock. Under that hold, pushing and rolling dev for
  this slice's verification is pre-authorized — do not ask for permission.
  prd stays operator-gated; nothing here touches it.
- The slice folder is {slice_dir}; the plan is {plan_path}. Check off
  {verification_path} as you verify (verdict + evidence per item).
- {close_out_line}
{hold_block}
{sweep_block}

Findings route through a generation bar, stated for this pass:

{generation_bar}

A finding that clears the bar becomes a new phase appended to the plan
(`### P<id> — <title>` + `Target:` line); report `findings` so the loop
re-enters. A finding that does not clear it goes in the close-out report. A
clean pass reports `clean`. Commit what you write (specs files staged
by name), then write your verdict to {verdict_path}.
"""

DOC_PHASE_PROMPT = """\
The phases of slice {slice_name} are merged and the test phase is complete.
Run the slice's doc phase: read {doc_plan_doc} and execute it for this slice
— the procedure lives in that doc, not in this prompt.

Deterministic facts from the driver:
- The slice's shipped work is {diff_ranges} — write docs from that diff with
  the whole shipped behavior in view.
- The slice folder is {slice_dir}; the plan is {plan_path}.
- {close_out_line}
- Work on branch {branch}, which is checked out. Never push — any repo, any
  branch. After your hand-back the driver runs the full gate sweep —
  `kc project lint` + `build` + `test` (a red comes back to this session) —
  rebase-merges the branch onto {base_branch} and pushes; the dev roll that
  push triggers is left to land on its own.

Run the doc gates the doc names yourself as you work, commit, then write
your verdict to {verdict_path}.
"""

DOC_GATE_NUDGE_PROMPT = """\
The driver's full gate sweep is red after your doc-phase commits (nudge
{round} of {cap}): `kc project lint` + `build` + `test`, output in
{gate_log}. The sweep is fail-fast, so the log ends at the FIRST failing
statement — there may be more behind it. Fix what broke on branch {branch}
without weakening any gate — mechanical suite breakage may go to the
`dev:test-fixer` sub-agent — commit, and do not push. Do not start other work.
"""

HOLD_BLOCK = """\
- The plan holds these repos — pushing them is NOT part of this phase, and
  the driver's push check reports them held rather than asking you for them:
{rows}
  Everything else this slice committed is yours to push, per your procedure
  doc.
"""

PUSH_NUDGE_PROMPT = """\
The test phase is not done: work this slice committed is not on origin
(nudge {round} of {cap}) —

{repos}

A reviewed-but-unpushed commit never reaches the deploy it was meant for
(one run's dev roll crash-looped exactly that way, its sibling's half of the
change still local). Push what is owed, in whatever order these repos need,
per your procedure doc's push step — wait for the CI build it names, and redo
any live check the push invalidates. Do not start other work.
"""

CONSULT_PROMPT = """\
You are the workflow consult for slice {slice_name}. The run loop hit a
decision point it does not decide itself.

Situation: {situation}
{phase_line}Slice folder: {slice_dir} (state.json holds the run history)
{close_out_line} Out-of-scope findings and sub-bar leftovers go there as
entries; `list` before you write, add if in doubt.

Investigate as needed — read the material below, the plan, git log/diff.
{material}

Choose exactly one action:
{actions}

Write {verdict_path} as JSON:
  {{"outcome": "<action>", "summary": "<your reasoning, 1-5 sentences>"}}
Optionally write a longer write-up next to it as {consult_md_name}.
"""

PLAN_DOC_NUDGE_PROMPT = """\
Your session's edit left the plan doc unparseable for the driver. Fix the
plan doc now — {plan_path} — and commit the fix (specs repo, staged by
name). Do not start other work. The problems:

{problems}

The rules: phases are `### P<id> — <title>` headings (id [A-Za-z0-9]+,
unique; every other heading level is fine, but `###` is reserved for
phases); every unfinished phase opens with a `Target:` line naming a
`kc project list` component or a sibling repo path; done-records go under
the phase's own heading without new `###`s; only the driver writes
`✅ DONE` stamps.
"""

VERDICT_NUDGE_PROMPT = """\
Your session ended without writing a valid verdict file. Do not start new
work: if any of your work is uncommitted, commit it, then write your verdict
now to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}{outcomes}).
"""

COMMIT_NUDGE_PROMPT = """\
Your session ended leaving uncommitted changes in the working tree. Commit
the work that belongs to this phase now (stage deliberately; drop anything
that should not be kept). Do not start new work.
"""

REATTACH_PROMPT = """\
Your session was interrupted mid-run (the driver process died — host
restart, quota stop, or similar). The working tree is exactly as you left
it. Reassess where you were (git status, git log, the plan), finish your
work, commit it, then write your verdict to {verdict_path}.
"""


# ---------------------------------------------------------------------------
# Target resolution — the `Target:` line names where a phase lands, from
# which the driver roots its git operations and picks the gate.
# ---------------------------------------------------------------------------

class ResolvedTarget:
    def __init__(self, name: str, kind: str, git_root: Path,
                 gate_argv: list[str] | None, gate_cwd: Path):
        self.name = name
        self.kind = kind            # "project" | "sibling"
        self.git_root = git_root    # where branches/merges happen
        self.gate_argv = gate_argv  # None → no deterministic gate
        self.gate_cwd = gate_cwd


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class RunLoop:
    def __init__(self, slice_dir: Path, resume: bool, verbose: bool = False):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.slice_num = self.slice_name.split("_")[0]
        self.plan_path = self.slice_dir / "plan.md"
        self.verification_path = self.slice_dir / "verification.json"
        self.report_path = report_path(self.slice_dir)
        self.state_path = self.slice_dir / "state.json"
        self.log_path = self.slice_dir / "log.txt"
        self.resume = resume
        self.verbose = verbose
        self.state: dict = {}
        self._log_file = None
        self._reattach: dict | None = None
        self.repo_root = _git_toplevel()
        self._cfg: project_config.ProjectConfig | None = None
        self._devlock: DevLock | None = None
        self._slice_lock = SliceLock(self.slice_dir / "run.lock")
        # name → effective cwd, from `kc project list --output=json`; loaded
        # in run() (both fresh and resume need it before any dispatch).
        self.project_dirs: dict[str, Path] = {}

    @property
    def cfg(self) -> project_config.ProjectConfig:
        """The project's own contract — which phases it runs, which procedure
        docs they execute, whether it has a dev instance to lease. Read from
        the repo rather than __init__'s argument list, so it resolves against
        whatever `repo_root` ends up being; `run()` forces it before any work.
        Preflight has already validated it for a run, so a config broken
        between then and now is an environment fault (exit 2), not a bail the
        loop could resume from."""
        if self._cfg is None:
            try:
                self._cfg = project_config.load(self.repo_root)
            except project_config.ConfigError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)
        return self._cfg

    @property
    def devlock(self) -> DevLock:
        if self._devlock is None:
            self._devlock = DevLock(self.cfg.devlock_lease)
        return self._devlock

    # -- state ---------------------------------------------------------------

    def _save_state(self) -> None:
        self.state["updated_at"] = _now_iso()
        tmp = self.state_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.state_path)

    def _phase_state(self, phase_id: str) -> dict:
        defaults = {
            "status": "pending", "stage": None, "branch": None,
            "target": None, "executor_rounds": 0, "gate_fix_rounds": 0,
            "review_rounds": 0, "gate_runs": 0,
            "gate_green_commit": None, "gate_green_log": None,
            "reviewed_head": None,
        }
        ps = self.state["phases"].setdefault(phase_id, dict(defaults))
        for key, value in defaults.items():
            ps.setdefault(key, value)
        return ps

    def _record(self, phase: str | None, role: str, round_: int,
                outcome: str, summary: str, session: str | None,
                duration_s: int, transcript: str | None = None,
                extra: dict | None = None) -> None:
        self.state["history"].append({
            "ts": _now_iso(), "phase": phase, "role": role, "round": round_,
            "outcome": outcome, "summary": summary, "session": session,
            "transcript": transcript, "duration_s": duration_s,
            **(extra or {}),
        })
        self._save_state()

    def _emit(self, line: str) -> None:
        """All driver/session output lands in <slice>/log.txt; stdout echoes
        it only under --verbose (the log must never flood a caller's
        context)."""
        if self._log_file is None:
            self._log_file = open(self.log_path, "a", buffering=1)
        self._log_file.write(line + "\n")
        if self.verbose:
            print(line, flush=True)

    def log(self, msg: str) -> None:
        self._emit(f"[{_now_hms()}] {msg}")

    def announce(self, msg: str) -> None:
        """One terse timestamped stdout line per major transition — the
        caller's window into a run that otherwise reports only into
        log.txt. Every line lands in the watching session's context: job
        starts and landings only, never detail."""
        print(f"[{_now_hms()}] {msg}", flush=True)

    # -- git -----------------------------------------------------------------

    def git(self, *args: str, root: Path | None = None,
            check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root or self.repo_root,
            capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise Bailout(
                "protocol_failure", details=(
                    f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
                ),
            )
        return result.stdout.strip()

    def git_ok(self, *args: str, root: Path | None = None) -> bool:
        """A git query whose whole answer is its exit status — `merge-base
        --is-ancestor`, which prints nothing and says no by exiting 1 (and
        for an object this repo does not have at all, 128)."""
        return subprocess.run(
            ["git", *args], cwd=root or self.repo_root,
            capture_output=True, text=True,
        ).returncode == 0

    def specs_git(self, *args: str) -> str:
        """Git in the specs repo (the slice folder's repo) — used only for
        the driver's own plan.md edits (stamps), staged by name: the specs
        repo is one working tree shared by several parallel sessions."""
        return self.git("-C", str(self.slice_dir), *args)

    def _current_branch(self, root: Path) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD", root=root)

    def _bookkeeping_pathspec(self, root: Path) -> list[str]:
        """The pathspec holding the workflow's own bookkeeping outside a git
        query — empty unless the target repo IS the specs repo.

        A phase targeting the specs repo puts the driver's live run record
        (log.txt, state.json, phases/**) inside the very tree the driver
        branches, dirty-checks and resets — and every parallel session's
        record alongside it. None of that is a phase's deliverable: a
        slice's product is code, docs, or the wire contracts, never the
        workflow's own scratch. So the whole `slices/` tree stays out of
        these queries, which is exactly what the driver has always done
        when the target was a code repo and this tree lived elsewhere.
        Uncommitted work under `slices/` is therefore unchecked here too —
        also as before: an agent's plan.md edit rides the next stamp
        commit."""
        spec_root = spec_root_for(self.slice_dir)
        if spec_root is None:
            return []
        try:
            rel = (spec_root / "slices").relative_to(Path(root).resolve())
        except ValueError:
            return []
        return [".", f":(exclude){rel}"]

    def _worktree_dirty(self, root: Path) -> bool:
        pathspec = self._bookkeeping_pathspec(root)
        args = ("status", "--porcelain", *(["--", *pathspec] if pathspec
                                           else []))
        return bool(self.git(*args, root=root))

    def _reset_tracked(self, root: Path) -> None:
        """Drop a dead round's uncommitted work before redispatching. Scoped
        away from the bookkeeping tree when that sits inside the target:
        `reset --hard` would take an agent's uncommitted plan.md edit with
        it (the live log and state are untracked, so neither form touches
        those)."""
        pathspec = self._bookkeeping_pathspec(root)
        if not pathspec:
            self.git("reset", "--hard", "HEAD", root=root)
            return
        self.git("restore", "--source=HEAD", "--staged", "--worktree", "--",
                 *pathspec, root=root)

    def _assert_record_untracked(self, phase_id: str, root: Path, base: str,
                                 branch: str) -> None:
        """The driver's run record must stay untracked while the run is in
        flight. Committed onto the phase branch, the merge's `git checkout
        <base>` unlinks the file the open log handle is still writing to and
        the rest of the run's log goes nowhere. Caught here, before the
        checkout, with the branch still intact."""
        if not self._bookkeeping_pathspec(root):
            return
        rel = self.slice_dir.relative_to(Path(root).resolve())
        paths = [str(rel / name) for name in ("log.txt", "state.json",
                                              "phases")]
        swept = self.git("log", "--name-only", "--pretty=format:",
                         f"{base}..{branch}", "--", *paths, root=root)
        if swept:
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details="the driver's own run record was committed onto "
                        f"{branch} (a `git add -A` in {root}): "
                        + ", ".join(sorted(set(swept.split())))
                        + ". Rewrite the branch without those paths, then "
                          "resume.",
            )

    def _fetch_origin(self, root: Path) -> None:
        """Refresh a repo's remote-tracking refs — run before an agent is
        pointed at that repo, and before the driver reads `origin/<base>`
        itself.

        Nothing else in a run fetches: the driver branches off the LOCAL base
        branch and ff-merges back into it, so a repo cloned days ago keeps
        whatever `origin/<base>` came with the clone, and an agent reading
        that ref reads the day of the clone. One run's executor called a
        sibling-repo commit that had been on `origin/main` for a day "absent
        from origin" and raised a Blocker over it. Refs only — no local branch
        moves, so a base sitting behind its origin stays the operator's
        call."""
        self.git("fetch", "origin", root=root)

    def _touched_roots(self) -> list[tuple[Path, str]]:
        """Every repo this slice has touched, with the base branch it was
        recorded at. `state["bases"]` is the run's own record of what the
        slice touched — better input than a re-parse of the plan's `Target:`
        lines. The spec repo is left out: its commits are the slice's own
        record, they land at close-out, and nothing deploys from them."""
        spec_root = spec_root_for(self.slice_dir)
        spec_root = spec_root.resolve() if spec_root else None
        return [(Path(key), base)
                for key, base in sorted(self.state["bases"].items())
                if spec_root is None or Path(key).resolve() != spec_root]

    def _push_holds(self, text: str) -> tuple[dict[str, str], list[str]]:
        """(repo root → why the plan holds its push, structure errors).
        Roots are keyed as `state["bases"]` keys them, so the push check and
        the doc phase can look a repo up directly."""
        holds, errors = parse_push_holds(text)
        resolved: dict[str, str] = {}
        for target, why in holds:
            try:
                root = self._resolve_target(target).git_root
            except ValueError as e:
                errors.append(f"push hold `{target}`: {e}")
                continue
            resolved[str(root)] = why
        return resolved, errors

    def _held_roots(self) -> dict[str, str]:
        """The holds as the plan stands right now — re-read per call, so a
        hold the operator adds while the run sits at a bail takes effect on
        resume. Unresolvable entries drop out here and come back as plan
        structure errors from `_load_plan`."""
        try:
            text = self.plan_path.read_text()
        except OSError:
            return {}
        return self._push_holds(text)[0]

    def _hold_block(self) -> str:
        """The held repos as the test phase's dispatch carries them. The
        plan says it too, but the procedure doc that dispatch executes says
        `push`, and a deterministic fact outranks a section the agent has to
        find."""
        try:
            holds, _ = parse_push_holds(self.plan_path.read_text())
        except OSError:
            return ""
        if not holds:
            return ""
        return HOLD_BLOCK.format(
            rows="\n".join(f"  - {t} — {why}" for t, why in holds))

    def _base_branch(self, root: Path) -> str:
        """The base branch of a target repo, recorded the first time the loop
        touches that repo (the invoking repo is recorded at init)."""
        key = str(root)
        if key not in self.state["bases"]:
            self.state["bases"][key] = self._current_branch(root)
            self._save_state()
        return self.state["bases"][key]

    def _slice_base(self, root: Path) -> str:
        """The sha a repo stood at before this slice's first phase touched it
        — the doc phase's diff base."""
        key = str(root)
        if key not in self.state["slice_base"]:
            self.state["slice_base"][key] = self.git(
                "rev-parse", "HEAD", root=root)
            self._save_state()
        return self.state["slice_base"][key]

    # -- plan ----------------------------------------------------------------

    def _load_plan(self) -> list[Phase]:
        """Parse the plan; on structure errors, nudge the session that
        produced them, then re-parse. A plan still broken after the nudge —
        or broken with no session to nudge (the operator's own edit) — is an
        operator question, not a crash."""
        for attempt in (1, 2):
            try:
                text = self.plan_path.read_text()
            except OSError as e:
                raise Bailout("plan_unreadable", details=str(e)) from None
            phases, errors = parse_plan(text)
            errors.extend(self._vanished_phases(phases))
            errors.extend(self._target_errors(phases))
            errors.extend(self._push_holds(text)[1])
            if not errors:
                self._track_phases(phases)
                return phases
            session, role = self._last_session()
            if attempt == 1 and session:
                self.log("plan doc unparseable — nudging the session that "
                         f"last edited it ({session}): " + "; ".join(errors))
                self._nudge(
                    PLAN_DOC_NUDGE_PROMPT.format(
                        plan_path=self.plan_path,
                        problems="\n".join(f"- {e}" for e in errors)),
                    self.repo_root, session, "[plan-doc]", role)
                continue
            raise Bailout(
                "plan_doc", question=True,
                details="the plan doc needs a fix only you can make:\n"
                        + "\n".join(f"- {e}" for e in errors))
        raise AssertionError("unreachable")

    def _vanished_phases(self, phases: list[Phase]) -> list[str]:
        present = {p.id for p in phases}
        return [f"phase P{pid} vanished from the plan (it is tracked in "
                "state.json; restore it or its heading)"
                for pid in self.state.get("known_phases", [])
                if pid not in present]

    def _target_errors(self, phases: list[Phase]) -> list[str]:
        errors = []
        for phase in phases:
            if phase.done or not phase.target:
                continue
            try:
                self._resolve_target(phase.target)
            except ValueError as e:
                errors.append(f"phase P{phase.id}: {e}")
        return errors

    def _track_phases(self, phases: list[Phase]) -> None:
        known = [p.id for p in phases]
        if known != self.state.get("known_phases"):
            fresh = [pid for pid in known
                     if pid not in self.state.get("known_phases", [])]
            if fresh and self.state.get("known_phases"):
                # Phases the plan gained after the run started — appended
                # by a consult, the test phase, or the operator; the
                # close-out header reads planned vs appended off this.
                self.log(f"new phase(s) in the plan: {', '.join(fresh)}")
                self.state.setdefault("appended_phases", []).extend(fresh)
            self.state["known_phases"] = known
            self._save_state()

    def _last_session(self) -> tuple[str | None, str | None]:
        """The last recorded session and its role — the one that last
        edited the plan, for the plan-doc nudge."""
        for entry in reversed(self.state.get("history", [])):
            if entry.get("session"):
                return entry["session"], entry.get("role")
        return None, None

    def _resolve_target(self, target: str) -> ResolvedTarget:
        """A `kc project list` component, or a sibling repo path. Raises
        ValueError with a fix-it message for anything else."""
        if target in self.project_dirs:
            return ResolvedTarget(
                target, "project", self.repo_root,
                ["kc", "project", "test", "--project", target],
                self.repo_root)
        if target.startswith(("../", "/")):
            path = (self.repo_root / target).resolve() \
                if not target.startswith("/") else Path(target)
            if not path.is_dir():
                raise ValueError(f"Target `{target}` is not an existing "
                                 "directory")
            if not (path / ".git").exists():
                raise ValueError(f"Target `{target}` is not a git repo")
            # A sibling with its own manifest gates through kc from its own
            # root; one without has no deterministic gate — the reviewer is
            # told the state is unverified.
            gate = (["kc", "project", "test"]
                    if (path / ".kubecoder" / "project.yaml").is_file()
                    else None)
            return ResolvedTarget(target, "sibling", path, gate, path)
        raise ValueError(
            f"Target `{target}` is neither a `kc project list` component "
            f"({', '.join(sorted(self.project_dirs)) or 'none found'}) nor "
            "a sibling repo path (`../Repo`)")

    def _stamp_done(self, phase_id: str) -> None:
        """The driver's mechanical `✅ DONE` stamp, committed in the specs
        repo by name. Agents never stamp. Called after the phase merged, so
        the stamp lands on the base branch either way — including when the
        specs repo IS the target and the merge just checked base out."""
        if not stamp_phase(self.plan_path, phase_id, _today()):
            raise Bailout(
                "plan_doc", question=True,
                details=f"phase P{phase_id} merged but its heading is gone "
                        "from the plan — restore it so the stamp can land")
        self.specs_git("add", str(self.plan_path))
        self.specs_git("commit", "-m",
                       f"slice {self.slice_num}: stamp P{phase_id} done")
        self.log(f"[P{phase_id}] stamped ✅ DONE")

    # -- session spawning ----------------------------------------------------

    def _nudge(self, prompt: str, cwd: Path, session_id: str,
               label: str, role: str | None) -> None:
        """One resume-shot at a session that missed part of its protocol.
        Failures fall through to the caller's re-check; a nudge never
        raises. `role` is the resumed session's, so the resume carries the
        same spawn flags (a differing prefix would miss the cache)."""
        self.log(f"{label} nudging the session (resume)")
        try:
            run_kc_session(
                prompt=prompt, cwd=str(cwd), timeout=NUDGE_TIMEOUT,
                resume_session=session_id, extra_env=SPAWN_ENV,
                flags=spawn_flags(role),
                progress=lambda line: self._emit(f"    {label} {line}"),
            )
        except subprocess.TimeoutExpired:
            self.log(f"{label} nudge timed out")

    def _ensure_committed(self, phase_id: str | None, role: str,
                          session_id: str | None, root: Path) -> None:
        """An agent must leave the worktree clean. Dirty → one resume-nudge
        asking it to commit; still dirty → bail (the driver never commits an
        agent's leftovers itself)."""
        if not self._worktree_dirty(root):
            return
        label = f"[P{phase_id}] [{role}]" if phase_id else f"[{role}]"
        if session_id:
            self._nudge(COMMIT_NUDGE_PROMPT, root, session_id, label, role)
            if not self._worktree_dirty(root):
                self.log(f"{label} committed its leftovers on the nudge")
                return
        raise Bailout(
            "protocol_failure", phase=phase_id,
            details=f"{role} left uncommitted changes in {root}"
                    + (" after a commit nudge" if session_id
                       else "; no session to nudge"),
        )

    def _spawn(self, role: str, prompt: str, cwd: Path, verdict_path: Path,
               phase_id: str | None, round_: int,
               agent: str | None = None,
               display: str | None = None) -> tuple[dict, str | None]:
        """Run one session; return (verdict, session_id). Every spawn is a
        fresh session — the only resumed sessions are crash reattaches and
        protocol nudges. Model and effort come from the MODELS config,
        passed explicitly on every dispatch."""
        shown = display or role
        label = f"[P{phase_id}] [{shown}]" if phase_id else f"[{shown}]"
        prompt, resume_session = self._resolve_reattach(
            role, phase_id, prompt, verdict_path, label)
        model, effort = MODELS[role]

        def _valid(v: dict | None) -> bool:
            return v is not None and (
                role not in VERDICTS or v.get("outcome") in VERDICTS[role])

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(cwd, sid)}")
            in_flight = self.state.get("in_flight")
            if in_flight and not in_flight.get("session"):
                in_flight["session"] = sid
                self._save_state()

        while True:
            self.log(f"{label} session starting"
                     + (" (resume)" if resume_session else ""))
            self.announce((f"P{phase_id} " if phase_id else "") + shown
                          + (f" r{round_}" if round_ else "")
                          + (" (resume)" if resume_session else ""))
            verdict_path.unlink(missing_ok=True)

            self.state["in_flight"] = {
                "phase": phase_id, "role": role, "round": round_,
                "verdict_path": str(verdict_path), "session": resume_session,
                "started_at": _now_iso(),
            }
            self._save_state()

            t0 = time.monotonic()
            try:
                returncode, result = run_kc_session(
                    prompt=prompt,
                    cwd=str(cwd),
                    timeout=TIMEOUTS[role],
                    agent=agent,
                    model=model,
                    effort=effort,
                    resume_session=resume_session,
                    extra_env=SPAWN_ENV,
                    flags=spawn_flags(role),
                    progress=lambda line: self._emit(f"    {label} {line}"),
                    on_session=_note_session,
                )
            except subprocess.TimeoutExpired:
                # A timed-out session is stuck, not crashed — never reattach.
                self.state["in_flight"] = None
                self._save_state()
                # The verdict file is unlinked at every dispatch, so one
                # present now was written by this round — the agent finished
                # its work and the turn wedged after. Salvage it; the round
                # is only lost when the verdict is missing or unparseable.
                verdict = _read_json(verdict_path)
                if not _valid(verdict):
                    raise Bailout(
                        "timeout", phase=phase_id,
                        details=f"{role} exceeded {TIMEOUTS[role]}s",
                    ) from None
                self.log(f"{label} timed out after {TIMEOUTS[role]}s, but had "
                         f"already written {verdict_path.name} — salvaged")
                duration_s = TIMEOUTS[role]
                session_id = resume_session
                returncode = 0
                break
            duration_s = int(time.monotonic() - t0)

            session_id = result.session_id
            verdict = _read_json(verdict_path)
            notice = None if _valid(verdict) else session_limit_notice(result)
            if notice is None:
                break
            # The account's window, not this agent's failure: record it, wait
            # it out, and dispatch the same round again.
            self.state["in_flight"] = None
            self._record(phase_id, role, round_, "session_limit",
                         notice.replace("\n", " ")[:200], session_id,
                         duration_s,
                         transcript=_transcript_path(cwd, session_id))
            self._wait_out_session_limit(notice, label)

        nudged = False
        if not _valid(verdict) and session_id:
            outcomes = (f"; outcome must be one of {sorted(VERDICTS[role])}"
                        if role in VERDICTS else "")
            self._nudge(
                VERDICT_NUDGE_PROMPT.format(verdict_path=verdict_path,
                                            outcomes=outcomes),
                cwd, session_id, label, role)
            nudged = True
            verdict = _read_json(verdict_path)
            if _valid(verdict):
                returncode = 0  # the nudge completed the protocol
        if returncode != 0 or not _valid(verdict):
            detail = _protocol_failure_detail(
                role, returncode, verdict, verdict_path.name,
                _valid(verdict), nudged)
            verdict = {"outcome": "blocked", "summary": detail,
                       "_protocol_failure": True}
        outcome = verdict.get("outcome", "blocked")
        self.state["in_flight"] = None
        self.log(f"{label} → {outcome}: {verdict.get('summary', '')[:160]}")
        # Per-finding telemetry rides the history row: the reviewer's
        # `findings` (severity/impact/category/anchor per finding) and a fix
        # round's `refuted` list persist as the agent reported them.
        telemetry = {k: verdict[k] for k in ("findings", "refuted")
                     if isinstance(verdict.get(k), list) and verdict[k]}
        self._record(phase_id, role, round_, outcome,
                     verdict.get("summary", ""), session_id, duration_s,
                     transcript=_transcript_path(cwd, session_id),
                     extra=telemetry)
        if verdict.get("cards"):
            # A pre-0.5.0 register still on an installed clone: not a
            # protocol failure — the findings belong in close-out.md.
            self.log(f"{label} verdict carried a `cards` list — ignored; "
                     f"out-of-scope findings go in {self.report_path.name}")
        return verdict, session_id

    def _resolve_reattach(self, role: str, phase_id: str | None, prompt: str,
                          verdict_path: Path,
                          label: str) -> tuple[str, str | None]:
        """If this spawn matches the session a crashed run left in flight,
        resume that session with a recovery prompt instead of dispatching
        fresh. Consults never reattach (cheap, and their action vocabulary
        may have changed)."""
        r = self._reattach
        if not (r and r.get("session") and role in VERDICTS
                and r.get("role") == role and r.get("phase") == phase_id):
            return prompt, None
        self._reattach = None
        self.log(f"{label} reattaching to the interrupted session "
                 f"{r['session']}")
        return REATTACH_PROMPT.format(verdict_path=verdict_path), r["session"]

    def _wait_out_session_limit(self, notice: str, label: str) -> None:
        reset = parse_session_limit_reset(notice)
        if reset is None:
            seconds = float(SESSION_LIMIT_FALLBACK)
            when = "no parseable reset time"
        else:
            seconds = (reset - datetime.now(reset.tzinfo)).total_seconds() \
                + SESSION_LIMIT_GRACE
            when = f"resets {reset.astimezone().isoformat(timespec='minutes')}"
        seconds = max(0.0, min(seconds, float(SESSION_LIMIT_MAX_SLEEP)))
        self.log(f"{label} account session limit — {when}; sleeping "
                 f"{int(seconds)}s, then redispatching the same round "
                 "(no round spent, no nudge, no consult)")
        self._sleep(seconds)

    def _sleep(self, seconds: float) -> None:
        """The driver's only wall-clock wait, isolated so tests can take it
        out."""
        time.sleep(seconds)

    def _consult(self, site: str, situation: str, actions: dict[str, str],
                 material: list[Path], phase_id: str | None) -> dict:
        """Spawn a fresh bare consult session; return its verdict
        (validated). `site` names the decision point in log lines."""
        n = self.state["consult_seq"] = self.state.get("consult_seq", 0) + 1
        self._save_state()
        base = (self.slice_dir / "phases" / f"P{phase_id}"
                if phase_id else self.slice_dir)
        base.mkdir(parents=True, exist_ok=True)
        verdict_path = base / f"consult_{n}.json"
        phase_line = f"Phase: P{phase_id}\n" if phase_id else ""
        prompt = CONSULT_PROMPT.format(
            slice_name=self.slice_name,
            situation=situation,
            phase_line=phase_line,
            slice_dir=self.slice_dir,
            close_out_line=dispatch_line(self.report_path),
            material="\n".join(f"- {p}" for p in material) or "- (state.json only)",
            actions="\n".join(f"- `{a}` — {why}" for a, why in actions.items()),
            verdict_path=verdict_path,
            consult_md_name=f"consult_{n}.md",
        )
        verdict, _ = self._spawn(
            "consult", prompt, self.repo_root, verdict_path, phase_id, n,
            display=f"consult: {site}",
        )
        if verdict.get("outcome") not in actions:
            raise Bailout(
                "protocol_failure", phase=phase_id, consult=str(verdict_path),
                details=f"consult chose {verdict.get('outcome')!r}, "
                        f"offered {sorted(actions)}",
            )
        if verdict["outcome"] == "bail":
            raise Bailout(
                "consult_bail", phase=phase_id, consult=str(verdict_path),
                details=verdict.get("summary", ""),
            )
        return verdict

    # -- the deterministic test gate -----------------------------------------

    def _run_gate(self, phase_id: str, ps: dict, outputs: Path,
                  target: ResolvedTarget) -> tuple[bool, Path | None]:
        """Run the target's test gate as a subprocess. Green/red is the exit
        code; full output goes to gate_r<N>.log in the phase's outputs dir.
        A target with no deterministic gate (a sibling repo without a
        manifest) is green by definition — but records no green commit, so
        the reviewer is told the state is unverified."""
        if target.gate_argv is None:
            self.log(f"[P{phase_id}] no deterministic gate for "
                     f"{target.name} — proceeding (reviewer told unverified)")
            return True, None
        ps["gate_runs"] += 1
        n = ps["gate_runs"]
        self._save_state()
        log_path = outputs / f"gate_r{n}.log"
        argv = target.gate_argv
        self.log(f"[P{phase_id}] gate #{n} running ({' '.join(argv)})")
        t0 = time.monotonic()
        try:
            with open(log_path, "w") as log_file:
                result = subprocess.run(
                    argv, cwd=target.gate_cwd,
                    stdout=log_file, stderr=subprocess.STDOUT,
                    timeout=GATE_TIMEOUT,
                )
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout", phase=phase_id,
                details=f"gate `{' '.join(argv)}` exceeded {GATE_TIMEOUT}s "
                        f"(output in {log_path})",
            ) from None
        duration_s = int(time.monotonic() - t0)
        # rc 2 is kc's usage error — an unknown --project. The name came
        # from kc's own project list, so that is a driver bug, not a red
        # suite.
        if result.returncode == 2:
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details=f"`{' '.join(argv)}` rejected its arguments "
                        f"(output in {log_path})",
            )
        green = result.returncode == 0
        tail = ""
        try:
            lines = [ln for ln in log_path.read_text().splitlines()
                     if ln.strip()]
            tail = lines[-1] if lines else ""
        except OSError:
            pass
        if green:
            ps["gate_green_commit"] = self.git("rev-parse", "HEAD",
                                               root=target.git_root)
            ps["gate_green_log"] = str(log_path)
        self._record(phase_id, "gate", n, "green" if green else "red",
                     tail, None, duration_s)
        self.log(f"[P{phase_id}] gate #{n} → "
                 f"{'green' if green else 'RED'} ({duration_s}s) {tail[:120]}")
        return green, log_path

    def _gate_line(self, ps: dict, head: str, target: ResolvedTarget) -> str:
        """The gate paragraph in a reviewer dispatch. The green claim is made
        ONLY when the recorded green commit is the commit under review."""
        green_at = ps.get("gate_green_commit")
        gate_log = ps.get("gate_green_log")
        if not (green_at and gate_log and green_at == head):
            return GATE_UNVERIFIED_LINE
        return GATE_GREEN_LINE.format(
            green_at=green_at[:12],
            gate_cmd=" ".join(target.gate_argv or []), gate_log=gate_log)

    # -- the phase loop ------------------------------------------------------

    def _run_phases(self) -> None:
        """Work the plan front to back until no unfinished phase remains.
        The plan is re-parsed every iteration — phases appended mid-run are
        picked up in document order."""
        self.state["run_phase"] = "phases"
        self._save_state()
        while True:
            phases = self._load_plan()
            pending = next((p for p in phases if not p.done), None)
            if pending is None:
                return
            self._run_phase(pending)

    def _executor_where(self, target: ResolvedTarget) -> str:
        """The clause locating a sibling target's working tree: the session
        itself spawns in the invoking repo, so the prompt must carry the
        pointer."""
        if target.kind == "project":
            return ""
        return f" in the sibling repo {target.git_root}"

    def _bookkeeping_note(self, target: ResolvedTarget) -> str:
        """The paragraph fencing the driver's run record off from an
        executor working in the tree that holds it — empty otherwise. Every
        executor round is a fresh session, so every executor prompt carries
        it."""
        if not self._bookkeeping_pathspec(target.git_root):
            return ""
        return BOOKKEEPING_NOTE.format(slice_dir=self.slice_dir)

    def _pointers(self, target: ResolvedTarget) -> str:
        """What every executor dispatch carries at its tail: the close-out
        report's path and tool, the project's change-discipline doc, plus the
        bookkeeping fence where it applies."""
        return (self._philosophy_line() + self._close_out_line()
                + self._bookkeeping_note(target))

    def _close_out_line(self) -> str:
        return CLOSE_OUT_LINE.format(
            dispatch_line=dispatch_line(self.report_path))

    def _phase_digest(self, phase_id: str, root: Path, merge_base: str) -> str:
        """The writer's orientation for this round (build_phase_digest): the
        plan and verification.json as they stand, slice.md's intent
        paragraph, and what earlier phases changed in every repo the slice
        has touched — the target repo up to the phase branch's merge base
        (what this branch was cut from), every other repo up to its base
        branch. A repo the slice has not changed contributes nothing."""
        try:
            plan_text = self.plan_path.read_text()
        except OSError:
            plan_text = ""
        try:
            intent = slice_intent((self.slice_dir / "slice.md").read_text())
        except OSError:
            intent = ""
        try:
            criteria = json.loads(
                self.verification_path.read_text()).get("items", [])
        except (OSError, ValueError, AttributeError):
            criteria = []
        touched: list[tuple[str, str]] = []
        for repo, sha in self.state["slice_base"].items():
            head = merge_base if repo == str(root) \
                else self.state["bases"].get(repo)
            if not head:
                continue
            stat = self.git("diff", "--stat=100", f"{sha}..{head}",
                            root=Path(repo), check=False)
            if stat:
                touched.append((repo, stat))
        return build_phase_digest(plan_text, phase_id, intent, criteria,
                                  touched)

    def _philosophy_line(self) -> str:
        """The run profile requires the doc, so the empty case is only a loop
        driven past a preflight that never checked for it."""
        if not self.cfg.design_philosophy:
            return ""
        return PHILOSOPHY_LINE.format(philosophy=self.cfg.design_philosophy)

    def _gate_hint(self, target: ResolvedTarget) -> str:
        if target.kind == "project":
            return f" (`kc project test --project {target.name}`)"
        if target.gate_argv:
            return (f" (`kc project test` from {target.git_root})")
        return (f" ({target.git_root} has no kc manifest — gate per that "
                "repo's own conventions)")

    @staticmethod
    def _recorded_commits(ps: dict) -> list[str]:
        """Every commit the driver itself vouched for on this phase's branch:
        the head the last review read and the gate's last green. A target with
        no deterministic gate records only the former, a phase with no review
        yet only the latter, and a fix round that has re-gated but not yet
        been re-reviewed carries both."""
        out: list[str] = []
        for sha in (ps.get("reviewed_head"), ps.get("gate_green_commit")):
            if sha and sha not in out:
                out.append(sha)
        return out

    def _work_is_in(self, ref: str, sha: str, root: Path) -> bool:
        return self.git_ok("merge-base", "--is-ancestor", sha, ref, root=root)

    def _lost_work(self, phase_id: str, sha: str, branch: str,
                   root: Path) -> Bailout:
        return Bailout(
            "lost_work", phase=phase_id,
            details=f"commit {sha[:12]} is on P{phase_id}'s record as work "
                    f"the driver saw on the branch, and {branch} in {root} "
                    "does not carry it. Something rebuilt the branch or "
                    "replaced the checkout under the run; the loop will not "
                    "carry on over the top of a commit it cannot account "
                    "for. "
                    "Check that no second driver is on this slice (each "
                    "holds run.lock), then either restore the branch or "
                    "clear the phase's record in state.json (status, stage, "
                    "gate_green_commit, reviewed_head) to run it again from "
                    "the executor.")

    def _assert_record_still_on(self, phase_id: str, ps: dict, root: Path,
                                branch: str) -> None:
        """Every round hands back onto the branch its predecessors built. A
        session that rebuilt that branch — or a second driver that did —
        leaves the record pointing at a commit the tip no longer carries, and
        the next round would gate and review a tree missing the earlier
        rounds' work."""
        for sha in self._recorded_commits(ps):
            if not self._work_is_in(branch, sha, root):
                raise self._lost_work(phase_id, sha, branch, root)

    def _reconcile_branch(self, phase_id: str, ps: dict, root: Path,
                          base: str, branch: str, existing: str) -> bool:
        """Reality-check the phase's record against the repository before the
        branch below is reset or recreated. Returns True when the phase turns
        out to be finished already and the caller has nothing left to run.

        Two ways a branch and its record can disagree, and one of them has a
        benign explanation:

        - The record vouches for a commit the branch does not carry (or there
          is no branch left). If the base branch carries it the merge landed
          and the run died before the record caught up — a resume finishes
          the bookkeeping. If nothing carries it, the work is gone: bail
          rather than silently rebuild the branch from base and spend a
          round redoing it.
        - The phase is `pending` — the loop knows of no work — but a branch
          of its name exists with commits the base has not got. `git branch
          -D` below would drop them without a word.
        """
        recorded = self._recorded_commits(ps)
        if ps["status"] == "pending":
            ahead = self.git("rev-list", "--count", f"{base}..{branch}",
                             root=root) if existing else "0"
            if ahead not in ("", "0"):
                raise Bailout(
                    "lost_work", phase=phase_id,
                    details=f"{branch} exists in {root} with {ahead} "
                            f"commit(s) {base} has not got, and P{phase_id} "
                            "is `pending` — the run has no record of that "
                            "work, so deleting the branch for a fresh one "
                            "would drop it unseen. Inspect it, then delete "
                            "the branch yourself or resume the run that "
                            "made it.")
            return False
        if not recorded:
            # Rounds spent before the first gate or review leave no commit on
            # the record — nothing to check them against, and a writer that
            # bailed may well have committed nothing at all.
            return False
        if existing and all(self._work_is_in(branch, sha, root)
                            for sha in recorded):
            return False
        for sha in recorded:
            if not self._work_is_in(base, sha, root):
                raise self._lost_work(phase_id, sha, branch, root)
        # The merge landed and the record did not: finish the bookkeeping.
        if ps["status"] != "merged":
            ps.update(status="merged", stage=None)
            self._save_state()
        self.log(f"[P{phase_id}] already merged into {base} "
                 f"({recorded[0][:12]}) — stamping")
        self._stamp_done(phase_id)
        return True

    def _run_phase(self, phase: Phase) -> None:
        phase_id = phase.id
        ps = self._phase_state(phase_id)
        target = self._resolve_target(phase.target)
        root = target.git_root
        outputs = self.slice_dir / "phases" / f"P{phase_id}"
        outputs.mkdir(parents=True, exist_ok=True)
        branch = f"phase/{self.slice_num}-P{phase_id}"
        base = self._base_branch(root)
        self._slice_base(root)
        where = self._executor_where(target)
        gate_hint = self._gate_hint(target)

        self.log(f"[P{phase_id}] start (target={target.name}, "
                 f"branch={branch}, root={root})")
        self._fetch_origin(root)

        # Branch setup (fresh or resume) — over a branch reconciled against
        # what the record says is committed on it.
        existing = self.git("branch", "--list", branch, root=root)
        if self._reconcile_branch(phase_id, ps, root, base, branch, existing):
            return
        if ps["status"] == "pending" or not existing:
            if existing:
                self.git("checkout", base, root=root)
                self.git("branch", "-D", branch, root=root)
            self.git("checkout", "-b", branch, base, root=root)
            ps.update(status="in_progress", stage="executor", branch=branch,
                      target=phase.target)
        else:
            self.git("checkout", branch, root=root)
            if self._reattach and self._reattach.get("session") \
                    and self._reattach.get("phase") == phase_id:
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']} "
                         "(worktree preserved for reattach)")
            else:
                self._reset_tracked(root)
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']}")
        self._save_state()

        merge_base = self.git("merge-base", base, branch, root=root)

        def executor_verdict_path(r: int) -> Path:
            return outputs / f"executor_result_r{r}.json"

        def spawn_executor(build_prompt) -> dict:
            """build_prompt(verdict_path) → prompt, to which the phase digest
            is appended. Every round is a fresh session — fix rounds read
            their inputs from the digest, the plan and the durable outputs
            dir, never from the prior round's context."""
            ps["executor_rounds"] += 1
            r = ps["executor_rounds"]
            self._save_state()
            prompt = (build_prompt(executor_verdict_path(r)) + "\n"
                      + self._phase_digest(phase_id, root, merge_base))
            verdict, session = self._spawn(
                "code-writer", prompt,
                self.repo_root, executor_verdict_path(r),
                phase_id, r, agent="code-writer",
            )
            self._ensure_committed(phase_id, "code-writer", session, root)
            self._assert_record_still_on(phase_id, ps, root, branch)
            self._save_state()
            self._handle_executor_terminals(verdict, phase_id)
            return verdict

        # ---- executor stage ----
        if ps["stage"] == "executor":
            spawn_executor(lambda vp: EXECUTOR_PROMPT.format(
                phase_id=phase_id, plan_path=self.plan_path,
                slice_name=self.slice_name, target=phase.target,
                branch=branch, where=where, gate_hint=gate_hint,
                verdict_path=vp,
                pointers=self._pointers(target)))
            self._after_session_plan_check()
            ps["stage"] = "gate"
            self._save_state()

        # ---- gate + executor-fix loop ----
        if ps["stage"] == "gate":
            self._gate_until_green(phase, ps, outputs, target, branch,
                                   merge_base, where, spawn_executor)
            ps["stage"] = "review"
            self._save_state()

        # ---- operator-answered writer question → writer-direct resume ----
        # A writer that bailed with a question mid-review resumes into a
        # writer round, not a review of the unchanged branch: job 3 wrote
        # the ruling into the plan's requirements/rulings, and the driver
        # tags the round's review report so the fix round carries both.
        if ps["stage"] == "review" and ps.get("operator_question"):
            question = ps.pop("operator_question")
            r = ps["review_rounds"]
            review_path = outputs / f"code_review_r{r}.md"
            self._save_state()
            if r and review_path.exists():
                review_path.write_text(
                    review_path.read_text()
                    + OPERATOR_RULING_TAG.format(round=r, question=question))
                self.log(f"[P{phase_id}] operator ruling tagged onto "
                         f"{review_path.name}; dispatching the writer")
                fix_verdict = spawn_executor(
                    lambda vp, _r=r: EXECUTOR_REVIEW_FIX_PROMPT.format(
                        phase_id=phase_id, slice_name=self.slice_name,
                        plan_path=self.plan_path, branch=branch,
                        merge_base=merge_base, where=where,
                        review_path=outputs / f"code_review_r{_r}.md",
                        gate_hint=gate_hint, verdict_path=vp,
                        pointers=self._pointers(target)))
                self._after_session_plan_check()
                self._handle_refutations(outputs, phase_id, r, fix_verdict)
                self._gate_until_green(phase, ps, outputs, target, branch,
                                       merge_base, where, spawn_executor)

        # ---- review loop ----
        if ps["stage"] == "review":
            self._review_loop(phase, ps, outputs, target, branch, merge_base,
                              where, gate_hint, spawn_executor)
            ps["stage"] = "merging"
            self._save_state()

        # ---- merge + stamp ----
        if ps["stage"] == "merging":
            if self._worktree_dirty(root):
                raise Bailout(
                    "protocol_failure", phase=phase_id,
                    details="worktree dirty at merge — an agent left changes "
                            "outside its commit boundary",
                )
            head = self.git("rev-parse", "HEAD", root=root)
            if target.gate_argv is not None \
                    and ps["gate_green_commit"] != head:
                green, gate_log = self._run_gate(phase_id, ps, outputs, target)
                if not green:
                    raise Bailout(
                        "gate_red", phase=phase_id,
                        details=f"cannot merge a red test gate ({gate_log})",
                    )
            self._assert_record_untracked(phase_id, root, base, branch)
            self.git("checkout", base, root=root)
            self.git("merge", "--ff-only", branch, root=root)
            self.git("branch", "-D", branch, root=root)
            ps.update(status="merged", stage=None)
            self._save_state()
            self.log(f"[P{phase_id}] merged into {base}")
            self.announce(f"P{phase_id} merged")
            self._stamp_done(phase_id)

    def _handle_executor_terminals(self, verdict: dict,
                                   phase_id: str) -> None:
        """`question` is the operator's (exit 4); `blocked` is an error the
        orchestrator diagnoses (exit 3). Anything else proceeds."""
        if verdict["outcome"] == "question":
            # A review-stage writer question marks the phase so the resume
            # goes straight back to a writer round with the ruling —
            # executor- and gate-stage resumes re-dispatch a writer anyway.
            ps = self.state["phases"].get(phase_id)
            if ps is not None and ps.get("stage") == "review":
                ps["operator_question"] = verdict.get("summary", "")
                self._save_state()
            raise Bailout("operator_question", phase=phase_id, question=True,
                          details=verdict.get("summary", ""))
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", phase=phase_id,
                          details=verdict.get("summary", ""))

    def _after_session_plan_check(self) -> None:
        """Re-parse the plan right after a session that may have edited it,
        so a malformed edit is nudged back to its author while that session
        is still resumable."""
        self._load_plan()

    def _gate_until_green(self, phase: Phase, ps: dict, outputs: Path,
                          target: ResolvedTarget, branch: str,
                          merge_base: str, where: str,
                          spawn_executor) -> None:
        """A red gate spawns a fresh executor fix round (the fix rounds are
        the executor's — there is no separate fixer in the phase loop),
        capped; still red at the cap bails."""
        while True:
            green, gate_log = self._run_gate(phase.id, ps, outputs, target)
            if green:
                return
            if ps["gate_fix_rounds"] >= GATE_FIX_CAP:
                raise Bailout(
                    "gate_red", phase=phase.id,
                    details=f"gate still red after {GATE_FIX_CAP} executor "
                            f"fix rounds (latest output: {gate_log})",
                )
            ps["gate_fix_rounds"] += 1
            r = ps["gate_fix_rounds"]
            self._save_state()
            spawn_executor(lambda vp, _r=r, _log=gate_log:
                           EXECUTOR_GATE_FIX_PROMPT.format(
                               phase_id=phase.id, slice_name=self.slice_name,
                               branch=branch, round=_r,
                               plan_path=self.plan_path,
                               gate_cmd=" ".join(target.gate_argv or []),
                               gate_log=_log, merge_base=merge_base,
                               where=where, verdict_path=vp,
                               pointers=self._pointers(target)))
            self._after_session_plan_check()

    def _review_loop(self, phase: Phase, ps: dict, outputs: Path,
                     target: ResolvedTarget, branch: str, merge_base: str,
                     where: str, gate_hint: str, spawn_executor) -> None:
        phase_id = phase.id
        root = target.git_root
        while True:
            # The round number is proposed here and only BANKED once the
            # round actually produced a review. A round that died — blocked,
            # protocol failure, a session-limit window — funds nothing and
            # reviewed nothing.
            r = ps["review_rounds"] + 1
            if self._reattach and self._reattach.get("role") == "code-reviewer" \
                    and self._reattach.get("phase") == phase_id:
                r = self._reattach.get("round") or r
            head = self.git("rev-parse", "HEAD", root=root)
            prev_head = ps.get("reviewed_head")
            gate_line = self._gate_line(ps, head, target)
            delta = bool(r > 1 and prev_head and prev_head != head)
            review_path = outputs / f"code_review_r{r}.md"
            verdict_path = outputs / f"review_result_r{r}.json"
            if delta:
                prompt = REVIEWER_DELTA_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    round=r, prev_round=r - 1, branch=branch, where=where,
                    merge_base=merge_base, fix_range=f"{prev_head}..HEAD",
                    prev_review=outputs / f"code_review_r{r - 1}.md",
                    plan_path=self.plan_path,
                    verification_path=self.verification_path,
                    review_path=review_path, verdict_path=verdict_path,
                    gate_line=gate_line,
                    philosophy_line=self._philosophy_line(),
                    close_out_line=self._close_out_line(),
                )
            else:
                prompt = REVIEWER_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    round=r, merge_base=merge_base, branch=branch,
                    where=where, plan_path=self.plan_path,
                    verification_path=self.verification_path,
                    review_path=review_path, verdict_path=verdict_path,
                    gate_line=gate_line,
                    philosophy_line=self._philosophy_line(),
                    close_out_line=self._close_out_line(),
                )
            verdict, _ = self._spawn(
                "code-reviewer", prompt, self.repo_root, verdict_path,
                phase_id, r, agent="code-reviewer",
            )
            if verdict["outcome"] == "blocked" \
                    or verdict.get("_protocol_failure"):
                raise Bailout("blocked", phase=phase_id,
                              details=verdict.get("summary", ""))
            # A real verdict: this round is spent, and its HEAD is what the
            # next round's fix range is measured against.
            ps["review_rounds"] = r
            ps["reviewed_head"] = head
            self._save_state()
            if verdict["outcome"] == "signoff":
                return
            # issues / critical → the funding decision. Round 1's fix is
            # automatic; from round 2 on — and for any `critical` — a fresh
            # consult judges the findings against the rising bar BEFORE an
            # executor round is spent.
            if r >= 2 or verdict["outcome"] == "critical":
                fix_range = f"{prev_head}..{head}" if delta else None
                choice = self._review_funding_consult(
                    outputs, phase_id, r, verdict, fix_range, root)
                if choice == "merge":
                    return
            fix_verdict = spawn_executor(
                lambda vp, _r=r: EXECUTOR_REVIEW_FIX_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    plan_path=self.plan_path, branch=branch,
                    merge_base=merge_base, where=where,
                    review_path=outputs / f"code_review_r{_r}.md",
                    gate_hint=gate_hint, verdict_path=vp,
                    pointers=self._pointers(target)))
            self._after_session_plan_check()
            refuted = self._handle_refutations(outputs, phase_id, r,
                                               fix_verdict)
            self._gate_until_green(phase, ps, outputs, target, branch,
                                   merge_base, where, spawn_executor)
            if self._refutation_settles_review(verdict, refuted, ps, root):
                self.log(f"[P{phase_id}] every blocking finding of round {r} "
                         "was refuted with no code change — review settled")
                return

    def _handle_refutations(self, outputs: Path, phase_id: str, r: int,
                            fix_verdict: dict) -> set[str]:
        """The refuted-verdict path: a blocking finding the fix round could
        not make fail is recorded onto the round's review file, where the
        next round's reviewer reads it, and entered in the close-out report
        with its refutation evidence for the operator. Returns the refuted
        finding ids."""
        entries = fix_verdict.get("refuted")
        if not isinstance(entries, list) or not entries:
            return set()
        review_path = outputs / f"code_review_r{r}.md"
        ids: set[str] = set()
        lines = []
        for e in entries:
            fid = str(e.get("id", "?")) if isinstance(e, dict) else str(e)
            evidence = str(e.get("evidence", "")) if isinstance(e, dict) \
                else ""
            ids.add(fid)
            lines.append(f"- {fid}: {evidence}" if evidence else f"- {fid}")
            claim = self._finding_summary(phase_id, r, fid)
            self._report(
                "Notable events",
                f"Fix round after review r{r} of P{phase_id} refuted {fid}",
                ("The fix round witnessed the claimed failure of the "
                 f"reviewer's finding {fid}"
                 + (f' — "{claim}" —' if claim else "")
                 + " and could not make it fail: no code changed for it, "
                 "and the finding funds no further work. The writer's "
                 "evidence: " + (evidence or "(none given)")
                 + f"\n\nThe full finding and the refutation record are in "
                 f"{review_path}."),
                consequence="none the loop acts on — the finding funds no "
                            "further work and no code changed for it; "
                            "recorded so the reviewer's claim is not "
                            "re-filed as open.",
                provenance=f"witnessed — code-writer P{phase_id}, fix round "
                           f"after review r{r}; the review verdict's "
                           "findings list in state.json")
        if review_path.exists():
            review_path.write_text(
                review_path.read_text()
                + REFUTATION_TAG.format(round=r, entries="\n".join(lines)))
        self.log(f"[P{phase_id}] fix round refuted "
                 f"{len(ids)} finding(s): {', '.join(sorted(ids))}")
        return ids

    def _finding_summary(self, phase_id: str, r: int,
                         fid: str) -> str | None:
        """The one-line summary the round-r reviewer reported for finding
        `fid`, from the history row that persisted its `findings` list."""
        for row in reversed(self.state.get("history", [])):
            if (row.get("phase") == phase_id and row.get("round") == r
                    and row.get("role") == "code-reviewer"):
                for f in row.get("findings") or []:
                    if isinstance(f, dict) and str(f.get("id")) == fid:
                        return str(f.get("summary") or "") or None
                return None
        return None

    def _report(self, section: str, headline: str, body: str,
                consequence: str, provenance: str | None = None) -> None:
        """The driver's own close-out entries — deterministic events the
        operator should see without reading the log, each with the stock
        consequence line its event carries. A report an agent removed is
        logged, never a bail: the run's outcome does not hang on its
        narrative."""
        try:
            eid = append_entry(self.slice_dir, section, headline, body,
                               consequence=consequence, provenance=provenance)
        except ReportError as e:
            self.log(f"close-out entry not written ({e}): {headline}")
            return
        self.log(f"close-out {eid}: {headline}")

    def _refutation_settles_review(self, review_verdict: dict,
                                   refuted: set[str], ps: dict,
                                   root: Path) -> bool:
        """True when the fix round changed no code and refuted every
        blocking finding of the round it answered: re-reviewing the
        identical diff would be relitigation by construction. Requires the
        review verdict's machine-readable findings — without them the loop
        cannot know the blocking set and falls back to another round."""
        if not refuted:
            return False
        if self.git("rev-parse", "HEAD", root=root) != ps.get("reviewed_head"):
            return False
        findings = review_verdict.get("findings")
        if not isinstance(findings, list) or not findings:
            return False
        blocking = {str(f.get("id")) for f in findings
                    if isinstance(f, dict) and f.get("impact") == "blocking"}
        if not blocking or "None" in blocking:
            return False
        return blocking <= refuted

    def _production_paths(self, fix_range: str, root: Path) -> list[str]:
        """Paths in the range that are production code — not tests, not
        docs. Conservative by design — a docstring-only code edit still
        counts as production."""
        files = self.git("diff", "--name-only", fix_range,
                         root=root).splitlines()

        def _nonprod(path: str) -> bool:
            parts = path.split("/")
            return (path.endswith(".md") or path.endswith("_test.go")
                    or "tests" in parts or "docs" in parts
                    or "manual" in parts)

        return [f for f in files if f and not _nonprod(f)]

    def _review_funding_consult(self, outputs: Path, phase_id: str, r: int,
                                verdict: dict, fix_range: str | None,
                                root: Path) -> str:
        """Judge whether review round r's findings fund another executor
        round or the phase merges with them recorded in the close-out
        report. Returns 'fix_round' or 'merge' ('bail' raises inside
        _consult)."""
        review_path = outputs / f"code_review_r{r}.md"
        merge_note = ("merge now; the unresolved findings stay in the review "
                      "file and the merge is recorded in the close-out "
                      "report for the operator")
        if r >= REVIEW_ROUND_CAP:
            site = "review-budget"
            situation = REVIEW_BUDGET_SITUATION.format(
                round=r, phase_id=phase_id, outcome=verdict["outcome"],
                review_path=review_path, cap=REVIEW_ROUND_CAP)
            actions = {"merge": merge_note,
                       "bail": "stop the slice for the orchestrator"}
        else:
            site = "review-funding"
            prose_only = bool(fix_range) and \
                not self._production_paths(fix_range, root)
            situation = REVIEW_FUNDING_SITUATION.format(
                round=r, phase_id=phase_id, outcome=verdict["outcome"],
                review_path=review_path, cap=REVIEW_ROUND_CAP,
                prose_fact=(REVIEW_PROSE_FACT.format(fix_range=fix_range)
                            if prose_only else ""),
                bar=_review_bar(r, prose_only))
            actions = {
                "fix_round": "the findings clear the bar: spend an executor "
                             "fix round; the next review round verifies it",
                "merge": f"the findings do not clear the bar: {merge_note}",
                "bail": "stop the slice for the orchestrator",
            }
        choice = self._consult(site, situation, actions, [review_path],
                               phase_id)
        if choice["outcome"] == "merge":
            findings = [f for f in verdict.get("findings") or []
                        if isinstance(f, dict)]
            listing = "\n".join(
                f"- {f.get('id', '?')} [{f.get('severity', '?')}/"
                f"{f.get('impact', '?')}]: {f.get('summary', '')}"
                for f in findings)
            self._report(
                "Notable events",
                f"P{phase_id} merged with unresolved review findings "
                f"after r{r}",
                (f"Review round {r} reported `{verdict.get('outcome')}` and "
                 f"the {site} consult chose to merge rather than fund another "
                 f"fix round. Its reasoning: {choice.get('summary', '')}"
                 + (f"\n\nThe unresolved findings, as the reviewer tagged "
                    f"them:\n{listing}" if listing else "")
                 + f"\n\nThe full review is {review_path}."),
                consequence="the findings listed above are in the merged "
                            "tree as the reviewer left them; nothing later "
                            "in the run acts on them.",
                provenance=f"witnessed — consult {self.state.get('consult_seq')} "
                           f"({site}, P{phase_id} r{r})")
        return choice["outcome"]

    # -- the loop-tail gate sweep ---------------------------------------------
    # Slice 152 reached the completion consult with the manual known-red
    # ("owed to the doc phase"); the consult answered `complete`, the test
    # phase pushed to confirm, and CI failed a build the tree could never
    # pass. The sweep makes the tree's whole gate state a driver-run fact
    # BEFORE the loop-tail dispatches, so the fix-or-bail decision is made
    # at the consult — where it costs nothing — never at push time.

    def _sweep_targets(self) -> list[Path]:
        """The repos the loop-tail sweep covers: every repo in the run's
        `bases` record (spec repo excluded — nothing deploys from it) that
        carries a kc manifest. A repo without one has no deterministic
        gates to run."""
        return [root for root, _ in self._touched_roots()
                if (root / ".kubecoder" / "project.yaml").is_file()]

    def _ensure_gate_sweep(self) -> dict:
        """The current sweep record, running the sweep if the recorded one
        no longer describes the tree. Commit-stamped like the per-phase
        gate's green: the record is reused only while every swept repo's
        HEAD is exactly the swept commit — any movement (a consult
        committing mechanical residue, an appended phase merging) re-runs
        the whole sweep, so the report a dispatch consumes always describes
        the tree that dispatch sees. Interrupted mid-sweep there is simply
        no record yet; the next call re-runs it."""
        targets = self._sweep_targets()
        heads = {str(root): self.git("rev-parse", "HEAD", root=root)
                 for root in targets}
        sweep = self.state.get("gate_sweep")
        if sweep and sweep.get("commits") == heads:
            return sweep
        return self._run_gate_sweep(targets, heads)

    def _run_gate_sweep(self, targets: list[Path], heads: dict) -> dict:
        n = self.state["sweep_runs"] = self.state.get("sweep_runs", 0) + 1
        self._save_state()
        out_dir = self.slice_dir / "sweeps" / f"r{n}"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.announce(f"gate sweep r{n} (lint+build+test, "
                      f"{len(targets)} repo(s))")
        t0 = time.monotonic()
        results = []
        for root in targets:
            components = (self.project_dirs if root == self.repo_root
                          else load_project_dirs(root))
            for component in components:
                for verb in SWEEP_VERBS:
                    results.append(
                        self._run_sweep_cmd(root, component, verb, out_dir))
        duration_s = int(time.monotonic() - t0)
        green = all(r["green"] for r in results)
        self.state["gate_sweep"] = {
            "run": n, "commits": heads, "green": green,
            "ran_at": _now_iso(), "results": results,
        }
        reds = [f"{Path(r['repo']).name}/{r['component']} {r['verb']}"
                for r in results if not r["green"]]
        self._record(None, "sweep", n, "green" if green else "red",
                     "; ".join(reds) or f"{len(results)} command(s)",
                     None, duration_s)
        self.announce(f"gate sweep r{n} → "
                      + ("green" if green else "RED (" + ", ".join(reds) + ")")
                      + f" ({duration_s}s)")
        return self.state["gate_sweep"]

    def _run_sweep_cmd(self, root: Path, component: str, verb: str,
                       out_dir: Path) -> dict:
        """One sweep command, per component so a red in one suite never
        hides a red in the next (the kc verbs are fail-fast across their
        selection)."""
        argv = ["kc", "project", verb, "--project", component]
        log_path = out_dir / f"{root.name}_{component}_{verb}.log"
        t0 = time.monotonic()
        try:
            with open(log_path, "w") as log_file:
                result = subprocess.run(
                    argv, cwd=root, stdout=log_file,
                    stderr=subprocess.STDOUT, timeout=GATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout",
                details=f"sweep `{' '.join(argv)}` in {root} exceeded "
                        f"{GATE_TIMEOUT}s (output in {log_path})",
            ) from None
        # rc 2 is kc's usage error — the component name came from kc's own
        # project list, so that is a driver bug, not a red suite.
        if result.returncode == 2:
            raise Bailout(
                "protocol_failure",
                details=f"sweep `{' '.join(argv)}` in {root} rejected its "
                        f"arguments (output in {log_path})")
        green = result.returncode == 0
        duration_s = int(time.monotonic() - t0)
        self.log(f"[sweep] {root.name}/{component} {verb} → "
                 f"{'green' if green else 'RED'} ({duration_s}s)")
        return {"repo": str(root), "component": component, "verb": verb,
                "green": green, "log": str(log_path),
                "duration_s": duration_s}

    def _sweep_block(self, sweep: dict, green_stance: str,
                     red_stance: str) -> str:
        """The report as a dispatch carries it — every row with its log
        path, then the stance the caller's dispatch takes on it."""
        if not sweep["results"]:
            rows, stance = "- (nothing ran)", SWEEP_STANCE_NONE
        else:
            lines = []
            for repo, sha in sweep["commits"].items():
                lines.append(f"- {Path(repo).name} @ {sha[:12]}:")
                lines.extend(
                    f"  - {r['component']} {r['verb']} → "
                    f"{'GREEN' if r['green'] else 'RED'} — {r['log']}"
                    for r in sweep["results"] if r["repo"] == repo)
            rows = "\n".join(lines)
            stance = green_stance if sweep["green"] else red_stance
        return SWEEP_BLOCK.format(rows=rows, stance=stance)

    # -- follow-up generations ----------------------------------------------

    def _generation_bar(self) -> str:
        """The bar for the NEXT append generation; exhausting it is the
        caller's bail."""
        bar = GENERATION_BARS[min(self.state["generation"] + 1,
                                  GENERATION_CAP)]
        return f"{bar}\n\n{GENERATION_RIDER}"

    def _spend_generation(self, source: str) -> None:
        """A consult/test pass appended phases: spend a generation, or bail
        to the operator when a third one is pending."""
        self.state["generation"] += 1
        self._save_state()
        if self.state["generation"] > GENERATION_CAP:
            raise Bailout(
                "generation_exhausted", question=True,
                details=f"{source} appended more work after "
                        f"{GENERATION_CAP} follow-up generations — decide "
                        "what of it still runs in this slice (edit the plan, "
                        "then resume) and what goes in the close-out report.")
        self.log(f"follow-up generation {self.state['generation']} "
                 f"({source} appended phases)")

    def _has_unfinished_phase(self) -> bool:
        phases = self._load_plan()
        return any(not p.done for p in phases)

    def _completion_consult(self) -> bool:
        """After all phases are done: one fresh consult — 'does the plan
        describe outstanding work?'. True → phases were appended, loop
        again."""
        self.state["run_phase"] = "consult"
        self._save_state()
        sweep = self._ensure_gate_sweep()
        choice = self._consult(
            "completion",
            COMPLETION_CONSULT_SITUATION.format(
                verification_path=self.verification_path,
                plan_path=self.plan_path,
                sweep_block=self._sweep_block(sweep,
                                              SWEEP_STANCE_CONSULT_GREEN,
                                              SWEEP_STANCE_CONSULT_RED),
                generation_bar=self._generation_bar()),
            {
                "complete": "the plan describes no outstanding work",
                "appended": "you appended phases for outstanding work that "
                            "clears the bar; the loop re-enters",
                "bail": "something is wrong enough to stop the slice",
            },
            [self.plan_path, self.verification_path], None,
        )
        if choice["outcome"] == "complete":
            return False
        self._after_session_plan_check()
        if not self._has_unfinished_phase():
            self.log("consult answered `appended` but no unfinished phase "
                     "exists — treating as complete")
            return False
        self._spend_generation("the completion consult")
        return True

    def _test_phase(self) -> bool:
        """The test phase, inside the loop: 'read the slice-testing-strategy
        doc and execute'. True → blocking findings were appended as phases,
        loop again."""
        self.state["run_phase"] = "test"
        self.state["test_rounds"] = self.state.get("test_rounds", 0) + 1
        self._save_state()
        r = self.state["test_rounds"]
        test_plan_doc = self.cfg.test_strategy
        if not test_plan_doc:
            raise Bailout(
                "protocol_failure",
                details=f"{self.cfg.path} runs the test phase but names no "
                        "`test_phase.strategy` — it has no procedure doc to "
                        "execute")
        base = self._base_branch(self.repo_root)
        # The test session works across every repo the slice touched — it
        # pushes them and verifies what the push deployed — so all of them
        # are refreshed, not just the one it spawns in.
        for root, _ in self._touched_roots():
            self._fetch_origin(root)
        verdict_path = self.slice_dir / f"test_phase_result_r{r}.json"
        verdict, session = self._spawn(
            "test-agent",
            TEST_PHASE_PROMPT.format(
                slice_name=self.slice_name, base_branch=base,
                test_plan_doc=test_plan_doc, slice_dir=self.slice_dir,
                plan_path=self.plan_path,
                verification_path=self.verification_path,
                close_out_line=dispatch_line(self.report_path),
                hold_block=self._hold_block(),
                sweep_block=self._sweep_block(self.state["gate_sweep"],
                                              SWEEP_STANCE_TEST_GREEN,
                                              SWEEP_STANCE_TEST_RED),
                generation_bar=self._generation_bar(),
                verdict_path=verdict_path),
            self.repo_root, verdict_path, None, r, agent="test-agent",
            display="test-phase",
        )
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", details=verdict.get("summary", ""))
        if verdict["outcome"] == "clean":
            # the same re-parse the findings path gets: the push check reads
            # the plan's holds, so a malformed edit is nudged back while the
            # session that made it is still resumable
            self._after_session_plan_check()
            self._assert_pushed(session)
            return False
        # findings → blocking phases were appended
        self._after_session_plan_check()
        if not self._has_unfinished_phase():
            self.log("test phase reported `findings` but appended no phase "
                     "— its findings are in the close-out report; treating "
                     "as clean")
            self._assert_pushed(session)
            return False
        self._spend_generation("the test phase")
        return True

    def _push_check(self) -> tuple[list[str], list[tuple[Path, str]]]:
        """What the push check sees: one description per repo this slice
        touched whose base branch holds commits `origin` does not, and —
        separately, never in that list — the repos the plan holds that are
        ahead of their origin in exactly the same way, with its reason. A held repo's work
        is meant to stay local, so it is reported, never nudged.

        Re-fetched here rather than trusted from the test phase's dispatch:
        that session has been pushing since. A stale ref would report pushed
        work as missing."""
        held_why = self._held_roots()
        unpushed: list[str] = []
        held: list[tuple[Path, str]] = []
        for root, base in self._touched_roots():
            self._fetch_origin(root)
            if not self.git("rev-parse", "--verify", "--quiet",
                            f"origin/{base}", root=root, check=False):
                note = f"{root}: no origin/{base} at all"
            else:
                count = self.git("rev-list", "--count",
                                 f"origin/{base}..{base}", root=root)
                if count in ("", "0"):
                    continue
                note = (f"{root}: {count} commit(s) on {base} that "
                        f"origin/{base} does not have")
            why = held_why.get(str(root))
            if why is None:
                unpushed.append(note)
            else:
                held.append((root, why))
        return unpushed, held

    def _report_hold(self, root: Path, why: str) -> None:
        """A held repo, entered in the close-out report once per run: the
        slice's commits stay local, so the push is a keystroke only the
        operator can make."""
        key = str(root)
        reported = self.state.setdefault("holds_reported", [])
        if key in reported:
            return
        reported.append(key)
        self._save_state()
        self.log(f"[push-check] {root.name} is held by the plan ({why}) — "
                 "reported, not nudged")
        self._report(
            "Outstanding actions",
            f"Push {root.name} by hand when its hold lifts",
            f"`plan.md`'s `## Push holds` section holds `{root}`: {why}\n\n"
            f"The slice's commits sit on `{self._base_branch(root)}` in that "
            "repo and nowhere else; every repo the plan does not hold was "
            "pushed as usual.",
            consequence="none in this run — the driver took the hold as the "
                        "ruling it is; nothing this repo deploys carries the "
                        "slice until you push it.",
            provenance="witnessed — the driver's push check, against "
                       "`plan.md`'s `## Push holds` section")

    def _assert_pushed(self, session: str | None) -> None:
        """Before the doc phase: every repo the slice touched is on its
        origin. Nothing in the driver pushes a code phase — `_run_phase`
        ff-merges locally, primary repo and siblings alike — so the push is
        the test phase's, per its procedure doc; this is the check that it
        happened. An unpushed repo nudges that session, capped, then bails
        (the same shape as the doc gate): the driver never pushes another
        repo's work itself, because a multi-repo slice may need an order only
        the agent running the verification knows. A repo the plan holds is
        neither nudged nor bailed on — `_report_hold` puts it in the
        close-out report and the run carries on.

        A hold is per-slice and exceptional; `push.enabled = false` is the
        project saying its runs never reach origin at all. That one is its
        standing mode, not an outstanding keystroke, so it returns here
        without reporting anything."""
        if not self.cfg.push:
            return
        nudges = 0
        while True:
            unpushed, held = self._push_check()
            if not unpushed:
                # reported only once the rest is pushed, so the entry's
                # "every repo the plan does not hold was pushed" holds
                for root, why in held:
                    self._report_hold(root, why)
                return
            self.log("[test-phase] unpushed work: " + "; ".join(unpushed))
            if nudges >= PUSH_NUDGE_CAP or not session:
                raise Bailout(
                    "unpushed",
                    details="the test phase left this slice's work unpushed"
                            + (f" after {nudges} nudge(s)" if nudges
                               else "; no session to nudge")
                            + " — " + "; ".join(unpushed)
                            + ". Push it (or resolve why it cannot be "
                              "pushed), then resume.")
            nudges += 1
            self._nudge(
                PUSH_NUDGE_PROMPT.format(
                    repos="\n".join(f"- {u}" for u in unpushed),
                    round=nudges, cap=PUSH_NUDGE_CAP),
                self.repo_root, session, "[test-phase]", "test-agent")

    def _doc_phase(self) -> None:
        """The doc phase, after test-complete: one writer, diff-based over
        the whole slice, on its own branch — the writer never pushes. The
        driver gates the result with the full lint+build+test sweep (red
        is nudged back to the writer's session), then rebase-merges the
        branch onto the base branch and pushes. The dev roll that push
        triggers is deliberately not tracked: the sweep already proved the
        tree, and the roll lands on its own.

        A project that runs no doc phase skips all of it — the slice's code
        is already merged and settled by the time this is reached."""
        if not self.cfg.doc_phase:
            self.log(f"doc phase disabled in {self.cfg.path.name} — skipped")
            return
        self._acquire_devlock()
        self.state["run_phase"] = "docs"
        ds = self.state.setdefault(
            "doc_phase", {"stage": "writer", "gate_runs": 0, "nudges": 0,
                          "session": None})
        self._save_state()
        doc_plan_doc = self.cfg.doc_plan
        if not doc_plan_doc:
            raise Bailout(
                "protocol_failure",
                details=f"{self.cfg.path} runs the doc phase but names no "
                        "`doc_phase.plan` — it has no procedure doc to "
                        "execute")
        base = self._base_branch(self.repo_root)
        root = self.repo_root
        branch = f"phase/{self.slice_num}-docs"

        # Branch setup (fresh or resume; a resume past the writer stage
        # keeps the branch and the work on it). A landing-stage resume with
        # no branch means the merge landed before the crash — only the push
        # is owed.
        existing = self.git("branch", "--list", branch, root=root)
        if ds["stage"] == "writer" and not (
                self._reattach and self._reattach.get("role") == "doc-writer"):
            if existing:
                self.git("checkout", base, root=root)
                self.git("branch", "-D", branch, root=root)
            self.git("checkout", "-b", branch, base, root=root)
        elif existing:
            self.git("checkout", branch, root=root)
        elif ds["stage"] != "landing":
            ds.update(stage="writer", session=None)
            self.git("checkout", "-b", branch, base, root=root)
        self._save_state()

        if ds["stage"] == "writer":
            ranges = []
            for repo, sha in self.state["slice_base"].items():
                ranges.append(f"`git diff {sha[:12]}..HEAD` in {repo}")
            verdict_path = self.slice_dir / "doc_phase_result.json"
            # The writer ranks the Focus lines over the report as the
            # operator will read it: rendered — live entries first, Bugs
            # by severity, struck folded last.
            self._render_report()
            verdict, session = self._spawn(
                "doc-writer",
                DOC_PHASE_PROMPT.format(
                    slice_name=self.slice_name, doc_plan_doc=doc_plan_doc,
                    diff_ranges="; ".join(ranges) or "(no recorded range)",
                    slice_dir=self.slice_dir, plan_path=self.plan_path,
                    close_out_line=dispatch_line(self.report_path),
                    branch=branch, base_branch=base,
                    verdict_path=verdict_path),
                self.repo_root, verdict_path, None, 1, agent="doc-writer",
                display="doc-phase",
            )
            self._ensure_committed(None, "doc-writer", session, root)
            self._handle_executor_terminals(verdict, None)
            ds.update(stage="gate", session=session)
            self._save_state()

        if ds["stage"] == "gate":
            self._doc_gate_until_green(ds, branch)
            ds["stage"] = "landing"
            self._save_state()

        if ds["stage"] == "landing":
            self._land_doc_branch(branch, base)
            ds["stage"] = "done"
            self._save_state()

    def _doc_gate_until_green(self, ds: dict, branch: str) -> None:
        """The driver's own full-sweep gate on the doc branch. Red is
        nudged back to the writer's session (a fix in place, committed,
        never pushed), capped; still red at the cap bails."""
        while True:
            green, log_path = self._run_doc_gate(ds)
            if green:
                return
            session = ds.get("session")
            if ds["nudges"] >= GATE_FIX_CAP or not session:
                raise Bailout(
                    "gate_red",
                    details="the gate sweep (kc project lint+build+test) "
                            "still red after the doc phase"
                            + (f" and {ds['nudges']} nudge(s)"
                               if ds["nudges"] else "")
                            + f" (latest output: {log_path})")
            ds["nudges"] += 1
            self._save_state()
            self._nudge(
                DOC_GATE_NUDGE_PROMPT.format(
                    round=ds["nudges"], cap=GATE_FIX_CAP, gate_log=log_path,
                    branch=branch),
                self.repo_root, session, "[doc-phase]", "doc-writer")
            self._ensure_committed(None, "doc-writer", session,
                                   self.repo_root)

    def _run_doc_gate(self, ds: dict) -> tuple[bool, Path]:
        """The full cross-component sweep — `kc project lint` + `build` +
        `test`, fail-fast across the verbs — run by the driver as the doc
        phase's deterministic gate. Fail-fast rather than per-component:
        this gate exists to go green or hand ONE red log to the fixer, not
        to produce a report. Output goes to doc_gate_r<N>.log in the slice
        folder."""
        ds["gate_runs"] += 1
        n = ds["gate_runs"]
        self._save_state()
        log_path = self.slice_dir / f"doc_gate_r{n}.log"
        self.log(f"[doc-phase] gate #{n} running "
                 f"(kc project {' + '.join(SWEEP_VERBS)})")
        t0 = time.monotonic()
        green = True
        with open(log_path, "w") as log_file:
            for verb in SWEEP_VERBS:
                argv = ["kc", "project", verb]
                log_file.write(f"$ {' '.join(argv)}\n")
                log_file.flush()
                try:
                    rc = self._doc_gate_exec(argv, log_file)
                except subprocess.TimeoutExpired:
                    raise Bailout(
                        "timeout",
                        details=f"doc-phase gate `{' '.join(argv)}` exceeded "
                                f"{GATE_TIMEOUT}s (output in {log_path})",
                    ) from None
                if rc != 0:
                    green = False
                    break
        duration_s = int(time.monotonic() - t0)
        tail = ""
        try:
            lines = [ln for ln in log_path.read_text().splitlines()
                     if ln.strip()]
            tail = lines[-1] if lines else ""
        except OSError:
            pass
        self._record(None, "doc-gate", n, "green" if green else "red",
                     tail, None, duration_s)
        self.log(f"[doc-phase] gate #{n} → "
                 f"{'green' if green else 'RED'} ({duration_s}s) {tail[:120]}")
        return green, log_path

    def _doc_gate_exec(self, argv: list[str], log_file) -> int:
        """One doc-gate command — the subprocess seam, isolated for
        tests."""
        return subprocess.run(
            argv, cwd=self.repo_root, stdout=log_file,
            stderr=subprocess.STDOUT, timeout=GATE_TIMEOUT).returncode

    def _land_doc_branch(self, branch: str, base: str) -> None:
        """Rebase-merge the gated doc branch and push — no build tracking;
        the sweep proved the tree, and the resulting dev roll lands on its
        own. A plan holding this repo lands the merge locally and stops
        there: the same ruling the push check honours, at the one place the
        driver pushes anything."""
        root = self.repo_root
        held = self._held_roots().get(str(root))
        if self._worktree_dirty(root):
            raise Bailout(
                "protocol_failure",
                details="worktree dirty at doc landing — an agent left "
                        "changes outside its commit boundary")
        # Two ways this repo's push is off — the plan holds it for this slice,
        # or the project never pushes — and origin plays no part in either. A
        # repo whose push is off is ahead of its origin by everything the slice
        # landed and stays that way, so the branch rebases onto its own local
        # base and the check below has nothing left to protect.
        pushing = self.cfg.push and not held
        onto = f"origin/{base}" if pushing else base
        if self.git("branch", "--list", branch, root=root):
            if pushing:
                self.git("fetch", "origin", root=root)
                # Before any branch mutation: local `base` must not outrun
                # origin. The rebase below targets `origin/{base}`, so a commit
                # that only local `base` carries (an out-of-band fix landed
                # while the run sat at a bail) leaves the two divergent and the
                # `--ff-only` merge dies with a raw "Diverging branches can't be
                # fast-forwarded". Origin moving ahead is the harmless direction
                # — the rebase picks those commits up and local `base` is still
                # an ancestor.
                ahead = self.git("rev-list", "--count",
                                 f"origin/{base}..{base}", root=root)
                if ahead not in ("", "0"):
                    raise Bailout(
                        "blocked",
                        details=f"local {base} has {ahead} commit(s) that "
                                f"origin/{base} lacks, so the doc branch "
                                f"cannot fast-forward onto it — push {base} "
                                "(or resolve why it diverged), then resume")
            self.git("checkout", branch, root=root)
            try:
                self.git("rebase", onto, root=root)
            except Bailout:
                self.git("rebase", "--abort", root=root, check=False)
                raise Bailout(
                    "blocked",
                    details=f"the doc branch {branch} does not rebase "
                            f"cleanly onto {onto} — resolve by hand, "
                            "then resume",
                ) from None
            self.git("checkout", base, root=root)
            self.git("merge", "--ff-only", branch, root=root)
            self.git("branch", "-D", branch, root=root)
        if not pushing:
            if held:
                self._report_hold(root, held)
                self.log(f"[doc-phase] merged into {base} — {root.name} is "
                         "held by the plan, so nothing was pushed")
            else:
                self.log(f"[doc-phase] merged into {base}; the project does "
                         "not push — nothing sent to origin")
            return
        self.git("push", "origin", base, root=root)
        self.log(f"[doc-phase] merged into {base} and pushed — the dev roll "
                 "is not tracked")

    # -- top level -----------------------------------------------------------

    def _assert_agents(self) -> None:
        """`kc session create-headless --agent` does not validate names — a
        typo'd role spawns a plain SDK session that answers anyway. Assert
        every required definition resolves before dispatching anything."""
        missing = [role for role in REQUIRED_AGENTS
                   if not (AGENTS_DIR / f"{role}.md").is_file()]
        if missing:
            print("Error: agent definition(s) not found: "
                  + ", ".join(missing)
                  + f" (searched {AGENTS_DIR}) — reinstall the dev plugin",
                  file=sys.stderr)
            sys.exit(2)

    def preflight(self) -> None:
        if not self.plan_path.is_file():
            print(f"Error: {self.plan_path} does not exist — run /dev:plan-slice "
                  "first.", file=sys.stderr)
            sys.exit(2)
        if not self.verification_path.is_file():
            print(f"Error: {self.verification_path} does not exist — the "
                  "plan loop seeds it at GO.", file=sys.stderr)
            sys.exit(2)
        phases, errors = parse_plan(self.plan_path.read_text())
        if errors:
            print("Error: the plan doc does not parse:\n"
                  + "\n".join(f"  - {e}" for e in errors), file=sys.stderr)
            sys.exit(2)
        if not phases:
            print(f"Error: {self.plan_path} has no `### P<id> — <title>` "
                  "phases.", file=sys.stderr)
            sys.exit(2)
        if self._worktree_dirty(self.repo_root):
            print("Error: the working tree has uncommitted changes; commit "
                  "or stash before running a slice.", file=sys.stderr)
            sys.exit(2)

    def run(self) -> None:
        """The slice's run record takes one driver at a time; everything the
        run does happens inside that hold."""
        holder = self._slice_lock.acquire()
        if holder is not None:
            print(f"Error: {self._slice_lock.lock_path} is held — another "
                  "driver is running this slice:\n"
                  + "\n".join(f"  {line}" for line in holder.splitlines())
                  + "\nThe run record is shared and the code repo is not, so "
                    "a second driver rebuilds phase branches the first one is "
                    "still working on. Stop that run, or wait for it.",
                  file=sys.stderr)
            sys.exit(2)
        try:
            self._run()
        finally:
            self._slice_lock.release()

    def _run(self) -> None:
        if self.state_path.exists():
            if not self.resume:
                print(f"Error: {self.state_path} exists. Pass --resume to "
                      "continue, or delete state.json to restart.",
                      file=sys.stderr)
                sys.exit(2)
            self.state = _read_json(self.state_path) or {}
            self._reattach = self.state.get("in_flight") or None
            self.state["in_flight"] = None
        if not self.state:
            self.state = {
                "slice": self.slice_name,
                "created_at": _now_iso(),
                "plugin_version": plugin_version(),
                "orchestrator": _orchestrator_record(),
                "run_phase": "phases",
                "bases": {},
                "slice_base": {},
                "known_phases": [],
                "phases": {},
                "generation": 0,
                "test_rounds": 0,
                "sweep_runs": 0,
                "gate_sweep": None,
                "consult_seq": 0,
                "in_flight": None,
                "bailouts": [],
                "appended_phases": [],
                "history": [],
            }
        (self.slice_dir / "bailout.json").unlink(missing_ok=True)

        # A resume re-enters the stage the bail left off in rather than
        # replaying the consult→test ladder from the top.
        resume_at = self.state.get("run_phase") if self.resume else None

        try:
            # Forced here, inside the try: everything downstream reads it, and
            # a bail handler must never be the first thing to touch it.
            self.log(f"project config: {self.cfg.path}")
            self.project_dirs = load_project_dirs(self.repo_root)
            self._assert_agents()
            if not self.resume:
                self.preflight()
                self._base_branch(self.repo_root)
                self._slice_base(self.repo_root)
            self._ensure_report()

            if resume_at != "docs":
                while True:
                    self._run_phases()
                    if resume_at != "test" and self._completion_consult():
                        resume_at = None
                        continue
                    resume_at = None
                    if self._test_phase_under_lock():
                        continue
                    break
                self._settle_push()
            self._doc_phase()
            self.devlock.release(self.log)
        except Bailout as bail:
            self.devlock.release(self.log)
            self._bail(bail)
        except KeyboardInterrupt:
            self.devlock.release(self.log)
            self.log("interrupted — state.json is current; resume with "
                     "--resume")
            print("Interrupted — resume with --resume (the in-flight session "
                  "will be reattached).", file=sys.stderr)
            sys.exit(130)

        self.state["run_phase"] = "done"
        self._save_state()
        self._stamp_report()
        self._summary()
        sys.exit(0)

    def _ensure_report(self) -> None:
        """close-out.md exists from here on: created from the template and
        committed by the driver when the plan loop left none (a slice
        planned before the report existed) — idempotent, so a resume picks
        one up mid-run rather than running without."""
        try:
            created = init_report(self.slice_dir)
        except ReportError as e:
            raise Bailout("protocol_failure", details=str(e)) from None
        if created:
            self.specs_git("add", str(self.report_path))
            self.specs_git("commit", "-m",
                           f"slice {self.slice_num}: close-out report")
            self.log(f"created {self.report_path.name} from the template")

    def _render_report(self) -> None:
        """The report in reading order — before the doc phase and at
        completion. Idempotent, and never a failure: a report an agent
        broke is logged, the run goes on."""
        try:
            self.log("close-out rendered: " + render_report(self.slice_dir))
        except ReportError as e:
            self.log(f"close-out not rendered: {e}")

    def _stamp_report(self) -> None:
        """Render, then the run header from the completed state;
        /dev:run-slice re-stamps once the cost block has landed. Never a
        failure — the run is done whatever the report's state."""
        self._render_report()
        try:
            self.log(stamp_header(self.slice_dir))
        except ReportError as e:
            self.log(f"close-out header not stamped: {e}")

    def _test_phase_under_lock(self) -> bool:
        """The test phase under the devlock, when the project runs one. The
        lock is NOT released between a findings-loop re-entry and the next
        test round — the slice keeps its occupancy while it converges."""
        if not self.cfg.test_phase:
            return False
        # Re-checked here, before the lock, so a consult's commits (the
        # mechanical-residue rider) never let the test phase read a report
        # about a tree that no longer exists — and the sweep's minute is
        # spent outside the hold.
        self._ensure_gate_sweep()
        self._acquire_devlock()
        return self._test_phase()

    def _acquire_devlock(self) -> None:
        """Taken before whichever of the test and doc phases runs first and
        held to the end of the run — both may roll dev. Idempotent: the
        second caller finds it already held."""
        if self.devlock.held:
            return
        names = [name for name, on in (("test", self.cfg.test_phase),
                                       ("doc", self.cfg.doc_phase)) if on]
        phases = "+".join(names) + (" phases" if len(names) > 1 else " phase")
        self.announce(f"acquiring devlock ({phases})")
        self.devlock.acquire(f"slice {self.slice_num} {phases}",
                             self.log, self._sleep)

    def _settle_push(self) -> None:
        """The driver's push, for a project that runs no test phase.

        Nothing in the driver pushes a code phase — `_run_phase` ff-merges
        into the base locally, primary repo and siblings alike — so with a
        test phase the push is that phase's, per its procedure doc, and
        `_assert_pushed` is the check that it happened. A project with no
        test phase has no other pusher: without this its siblings never reach
        origin, and if it runs no doc phase either the slice ends with every
        commit still in the pod. The plan's `## Push holds` bind the driver
        exactly as they bind the test phase — a held repo is reported, not
        pushed."""
        if self.cfg.test_phase:
            return
        if not self.cfg.push:
            self.log("the project does not push — the slice's commits stay "
                     "local")
            return
        held_why = self._held_roots()
        for root, base in self._touched_roots():
            why = held_why.get(str(root))
            if why is not None:
                self._report_hold(root, why)
                continue
            self.git("push", "origin", base, root=root)
            self.log(f"pushed {base} in {root}")

    def _bail(self, bail: Bailout) -> None:
        self.state["run_phase"] = "bailed"
        # bailout.json is unlinked on resume; the count lives here so the
        # close-out header can say how often the run stopped.
        self.state.setdefault("bailouts", []).append(
            {"reason": bail.reason, "phase": bail.phase,
             "question": bail.question, "ts": _now_iso()})
        self._save_state()
        payload = {
            "reason": bail.reason,
            "phase": bail.phase,
            "details": bail.details,
            "consult": bail.consult,
            "question": bail.question,
            "ts": _now_iso(),
        }
        with open(self.slice_dir / "bailout.json", "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        kind = "OPERATOR QUESTION" if bail.question else "BAIL-OUT"
        self.log(f"{kind} ({bail.reason}): {bail.details[:300]}")
        self.log(f"wrote {self.slice_dir / 'bailout.json'}; "
                 "resume with --resume after resolving")
        print(f"{kind} ({bail.reason}) — see "
              f"{self.slice_dir / 'bailout.json'}", file=sys.stderr)
        sys.exit(4 if bail.question else 3)

    def _summary(self) -> None:
        phases = self.state["phases"]
        try:
            report = "close-out report: " + counts_line(
                entry_counts(self.slice_dir))
        except ReportError:
            report = "close-out report missing"
        lines = [f"slice {self.slice_name} complete: "
                 f"{len(phases)} phase(s) merged, "
                 f"{self.state.get('test_rounds', 0)} test round(s), "
                 + report]
        for pid, ps in phases.items():
            lines.append(
                f"  P{pid}: executor×{ps['executor_rounds']} "
                f"gate×{ps.get('gate_runs', 0)} "
                f"review×{ps['review_rounds']}")
        for line in lines:
            self.log(line)
        self.announce(lines[0])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}",
              file=sys.stderr)
        sys.exit(2)
    loop = RunLoop(slice_dir, resume=args.resume, verbose=args.verbose)
    if args.dry_run:
        cmd_dry_run(loop)
        return
    print(f"run loop log: {loop.log_path}", flush=True)
    loop.run()


def cmd_dry_run(loop: RunLoop) -> None:
    """Parse the plan and resolve every target — no sessions, no branches.
    Exit 0 when the plan is drivable, 2 with the problems otherwise."""
    if not loop.plan_path.is_file():
        print(f"Error: {loop.plan_path} does not exist.", file=sys.stderr)
        sys.exit(2)
    phases, errors = parse_plan(loop.plan_path.read_text())
    try:
        loop.project_dirs = load_project_dirs(loop.repo_root)
    except Bailout as e:
        print(f"warning: {e.details} — component targets unvalidated",
              file=sys.stderr)
    print(f"slice {loop.slice_name}: {len(phases)} phase(s)")
    for phase in phases:
        line = f"  P{phase.id}  {'DONE ' if phase.done else ''}{phase.title}"
        if phase.done:
            print(line)
            continue
        try:
            target = loop._resolve_target(phase.target or "")
            gate = " ".join(target.gate_argv) if target.gate_argv \
                else "(no deterministic gate)"
            print(f"{line}\n        target={target.name} [{target.kind}]  "
                  f"root={target.git_root}  gate: {gate}")
        except ValueError as e:
            errors.append(f"phase P{phase.id}: {e}")
            print(f"{line}\n        target=INVALID")
    holds, hold_errors = parse_push_holds(loop.plan_path.read_text())
    errors.extend(hold_errors)
    for target, why in holds:
        try:
            root = loop._resolve_target(target).git_root
            print(f"  hold  {target}  root={root}  not pushed: {why}")
        except ValueError as e:
            errors.append(f"push hold `{target}`: {e}")
            print(f"  hold  {target}  INVALID")
    if errors:
        print("\nplan problems:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "state.json")
    if not state:
        print("no state.json — the run loop has not started this slice")
        return
    print(f"slice {state['slice']}  run_phase={state['run_phase']}  "
          f"generation={state.get('generation', 0)}  "
          f"bail-outs={len(state.get('bailouts', []))}")
    for pid in state.get("known_phases", []):
        ps = state.get("phases", {}).get(pid)
        if not ps:
            print(f"  P{pid}: pending")
            continue
        print(f"  P{pid}: {ps['status']}"
              + (f" (stage {ps['stage']})" if ps.get("stage") else "")
              + f"  executor×{ps['executor_rounds']} "
                f"gate×{ps.get('gate_runs', 0)} "
                f"review×{ps['review_rounds']}")
    for h in state.get("history", [])[-8:]:
        print(f"  {h['ts']}  {('P' + h['phase']) if h.get('phase') else '-'}"
              f"  {h['role']} r{h['round']} → {h['outcome']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or resume) a slice")
    run_p.add_argument("slice_dir", help="path to slices/NNN_slug/")
    run_p.add_argument("--resume", action="store_true",
                       help="continue from state.json")
    run_p.add_argument("-v", "--verbose", action="store_true",
                       help="echo the log to stdout as well as log.txt")
    run_p.add_argument("--dry-run", action="store_true",
                       help="parse the plan, resolve targets, and exit")
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser("status", help="print a slice's run state")
    status_p.add_argument("slice_dir")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
