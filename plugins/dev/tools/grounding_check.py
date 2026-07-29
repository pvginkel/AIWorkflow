#!/usr/bin/env python3
"""Grounding drift checker — re-greps a slice ledger's anchors against the tree.

The deterministic half of the grounding contract (the normative format,
statuses, and tiers live in ${CLAUDE_PLUGIN_ROOT}/docs/grounding-ledger.md).
Given a slice folder it parses `<slice>/grounding.md`, re-greps every entry's
anchor at its cited line, and reports per entry:

  OK        anchor found at (or inside) the cited line range
  MOVED     anchor found exactly once elsewhere in the file (new_line reported)
  MISSING   anchor nowhere in the file — or ambiguous (several candidate lines,
            none of them the cited one), which cannot be repaired safely
  GONE      the cited file no longer exists
  UNCHECKED a sweep entry, or an entry the checker cannot mechanically verify

plus `commits_since` per stamped repo and, for the task's plan.md files, a pass
over their own `file:line` citations (do they exist, is the line in range, how
many cited files moved since the stamp).

`--repair` rewrites MOVED line numbers in place — mechanical, no model, and the
`verified:` stamp is never touched. `--prune` deletes every entry no
`tasks/*/plan.md` cites (plan finalization). Neither commits: the caller owns
that. A ledger without a stamp or without `- G-NNN` entries is `legacy` and is
skipped — dispatches then carry an "unverified" line instead of a trust line.

Usage:
    grounding_check.py <slice_dir> [--task NN] [--repair] [--prune] [--json]

Exit codes: 0 tier 0/1 (or legacy) · 3 tier 2 (MISSING/GONE present) ·
2 usage/precondition error · 1 unexpected error.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Citations are relative to the target repo's root; `../SharedLib/…` reaches a
# sibling checkout, so every repo the ledger can name is that root or its
# sibling. The plugin's checker lives under ~/.claude rather than inside the
# repo it checks, so the root cannot come from `__file__` — it is the git repo
# the checker was invoked in (repo_root(), below), the same seam the runner uses.

GIT_TIMEOUT = 30

STATUS_ORDER = ("OK", "MOVED", "MISSING", "GONE", "UNCHECKED")
DRIFT_STATUSES = ("MOVED", "MISSING", "GONE")  # the ones worth a report line

# `verified: KubeCoder@1a2b3c4d, HelmCharts@9f8e — 2026-07-24`. The date is
# parsed off by ignoring anything that is not a Repo@sha token, so an em dash
# and a plain hyphen separator both work and a missing date never breaks it.
STAMP_RE = re.compile(r"^verified:\s*(?P<body>.+?)\s*$")
REPO_SHA_RE = re.compile(r"\b([A-Za-z][\w.+-]*)@([0-9a-fA-F]{6,40})\b")

# `- G-001: claim — `file:line[-line]` — "anchor"`, or the sweep form
# `- G-014 (sweep): free text` (no citation, no anchor).
ENTRY_RE = re.compile(r"^-\s+(?P<id>G-(?P<num>\d+))(?P<sweep>\s*\(sweep\))?\s*:"
                      r"\s*(?P<rest>.*)$")
BODY_RE = re.compile(r"^(?P<claim>.*?)\s+[—–-]\s+`(?P<citation>[^`]+)`"
                     r"\s+[—–-]\s+\"(?P<anchor>.*)\"\s*$")
CITATION_RE = re.compile(r"^(?P<file>.+?):(?P<start>\d+)(?:-(?P<end>\d+))?$")

# A plan's own inline citation: a backticked `path:line[-line]` whose path
# carries a file extension (so `env-id:1` style prose is not mistaken for one).
PLAN_CITE_RE = re.compile(r"`(?P<path>[^`\s:]+\.[A-Za-z0-9_]+)"
                          r":(?P<start>\d+)(?:-(?P<end>\d+))?`")

GID_RE = re.compile(r"\bG-(\d+)\b")

TASK_DIR_RE = re.compile(r"^\d{2}[a-z]?_")


class Precondition(Exception):
    """A usage/precondition error — exit 2, nothing mutated."""


@dataclass
class Entry:
    """One ledger line. `line_index` and `citation` are what --repair and
    --prune rewrite; everything else is what the report carries."""

    id: str
    num: int
    claim: str
    sweep: bool
    line_index: int
    citation: str | None = None
    file: str | None = None
    cited_start: int | None = None
    cited_end: int | None = None
    anchor: str | None = None
    status: str = "UNCHECKED"
    new_line: int | None = None
    repaired: bool = False

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "claim": self.claim,
            "file": self.file,
            "cited_line": self.cited_start,
            "cited_end": self.cited_end,
            "anchor": self.anchor,
            "status": self.status,
            "new_line": self.new_line,
            "repaired": self.repaired,
        }


# ---------------------------------------------------------------------------
# Repos + git
# ---------------------------------------------------------------------------

_REPO_ROOT: Path | None = None


def repo_root() -> Path:
    """The target repo's root, from `git rev-parse --show-toplevel` in the
    process cwd — resolved once per run. Both callers (the plan loop and the
    task runner) invoke the checker from the repo the citations are relative
    to. No git repo is a precondition error, not a crash: exit 2 is what the
    dispatch reads as "no mechanical check ran"."""
    global _REPO_ROOT
    if _REPO_ROOT is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=GIT_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise Precondition(f"cannot resolve the repo root: {exc}") from None
        if result.returncode != 0:
            raise Precondition(
                "not inside a git repository — the checker resolves citations "
                "against the repo it is run from")
        _REPO_ROOT = Path(result.stdout.strip())
    return _REPO_ROOT


def repo_path(name: str) -> Path:
    """The checkout for a repo named in the stamp or reached by a `../Name/`
    citation. This repo is the root itself; everything else is a sibling."""
    root = repo_root()
    if name == root.name:
        return root
    return root.parent / name


def repo_for_citation(rel: str) -> tuple[str, str]:
    """(repo name, path within that repo) for a citation path."""
    parts = PurePosixPath(rel).parts
    if len(parts) > 2 and parts[0] == "..":
        return parts[1], str(PurePosixPath(*parts[2:]))
    return repo_root().name, rel


def _git(repo: Path, *args: str) -> str | None:
    """git output, or None for any failure — an unresolvable sha, a missing
    checkout, or no git at all must never crash the checker."""
    if not repo.is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def commits_since(stamp: dict[str, str]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for name, sha in stamp.items():
        count = _git(repo_path(name), "rev-list", "--count", f"{sha}..HEAD")
        out[name] = int(count) if count and count.isdigit() else None
    return out


# ---------------------------------------------------------------------------
# Ledger parsing
# ---------------------------------------------------------------------------

def parse_stamp(lines: list[str]) -> dict[str, str] | None:
    for line in lines:
        match = STAMP_RE.match(line.strip())
        if not match:
            continue
        pairs = REPO_SHA_RE.findall(match.group("body"))
        if pairs:
            return dict(pairs)
    return None


def parse_entries(lines: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    for index, line in enumerate(lines):
        match = ENTRY_RE.match(line.strip())
        if not match:
            continue
        entry = Entry(
            id=match.group("id"), num=int(match.group("num")),
            claim=match.group("rest").strip(),
            sweep=bool(match.group("sweep")), line_index=index,
        )
        if not entry.sweep:
            _parse_body(entry, match.group("rest"))
        entries.append(entry)
    return entries


def _parse_body(entry: Entry, rest: str) -> None:
    """Split `claim — `file:line` — "anchor"` onto the entry. A body that does
    not carry a line-numbered citation (a malformed entry, or the per-task
    ledger's `path + symbol` form) stays UNCHECKED — the checker reports only
    what it can mechanically verify, and never escalates on its own confusion."""
    body = BODY_RE.match(rest.strip())
    if not body:
        return
    citation = CITATION_RE.match(body.group("citation").strip())
    if not citation:
        return
    entry.claim = body.group("claim").strip()
    entry.citation = body.group("citation").strip()
    entry.file = citation.group("file")
    entry.cited_start = int(citation.group("start"))
    entry.cited_end = (int(citation.group("end")) if citation.group("end")
                       else entry.cited_start)
    entry.anchor = body.group("anchor")


# ---------------------------------------------------------------------------
# Anchor checking
# ---------------------------------------------------------------------------

class FileCache:
    def __init__(self) -> None:
        self._lines: dict[str, list[str] | None] = {}

    def lines(self, rel: str) -> list[str] | None:
        if rel not in self._lines:
            path = (repo_root() / rel)
            try:
                text = path.read_text(errors="replace")
            except OSError:
                self._lines[rel] = None
            else:
                self._lines[rel] = text.splitlines()
        return self._lines[rel]


def check_entry(entry: Entry, cache: FileCache) -> None:
    if entry.sweep or entry.file is None or entry.anchor is None:
        entry.status = "UNCHECKED"
        return
    lines = cache.lines(entry.file)
    if lines is None:
        entry.status = "GONE"
        return
    hits = [n for n, line in enumerate(lines, 1) if entry.anchor in line]
    if not hits:
        entry.status = "MISSING"
        return
    if any(entry.cited_start <= hit <= entry.cited_end for hit in hits):
        entry.status = "OK"
        return
    if len(hits) == 1:
        entry.status = "MOVED"
        entry.new_line = hits[0]
        return
    # Several candidates and none is the cited line: the anchor no longer
    # identifies one place, so there is nothing safe to repair.
    entry.status = "MISSING"


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def plan_files(slice_dir: Path, task: str | None) -> list[Path]:
    tasks_dir = slice_dir / "tasks"
    if not tasks_dir.is_dir():
        return []
    dirs = sorted(d for d in tasks_dir.iterdir()
                  if d.is_dir() and TASK_DIR_RE.match(d.name))
    if task is not None:
        token = task.split("_")[0]
        dirs = [d for d in dirs
                if d.name == task or d.name.split("_")[0] == token]
    return [d / "plan.md" for d in dirs if (d / "plan.md").is_file()]


def referenced_ids(paths: list[Path]) -> set[int]:
    ids: set[int] = set()
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        ids.update(int(n) for n in GID_RE.findall(text))
    return ids


def check_plan_citations(paths: list[Path], slice_dir: Path,
                         stamp: dict[str, str],
                         cache: FileCache) -> dict:
    """Every backticked `path:line[-line]` in the plans: does the file exist,
    is the line inside it, and how many cited files moved since the stamp."""
    total = 0
    invalid: list[str] = []
    cited: set[str] = set()
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        try:
            label = str(path.relative_to(slice_dir))
        except ValueError:
            label = str(path)
        for match in PLAN_CITE_RE.finditer(text):
            total += 1
            rel = match.group("path")
            start = int(match.group("start"))
            end = int(match.group("end") or start)
            citation = match.group(0).strip("`")
            lines = cache.lines(rel)
            if lines is None:
                invalid.append(f"{label}: {citation} (file not found)")
                continue
            cited.add(rel)
            if end > len(lines):
                invalid.append(
                    f"{label}: {citation} (line beyond EOF, "
                    f"{len(lines)} lines)")
    touched = sum(1 for rel in sorted(cited) if _touched_since(rel, stamp))
    return {"total": total, "invalid": invalid,
            "files_touched_since_stamp": touched}


def _touched_since(rel: str, stamp: dict[str, str]) -> bool:
    name, inner = repo_for_citation(rel)
    sha = stamp.get(name)
    if not sha:
        return False
    out = _git(repo_path(name), "log", "--oneline", f"{sha}..HEAD", "--", inner)
    return bool(out)


# ---------------------------------------------------------------------------
# Rewrites (--repair / --prune)
# ---------------------------------------------------------------------------

def repair_entries(lines: list[str], entries: list[Entry]) -> list[Entry]:
    """Rewrite each MOVED entry's line number(s) in place. A range keeps its
    span length, anchored at the new start. The stamp is never touched."""
    repaired = []
    for entry in entries:
        if entry.status != "MOVED" or entry.new_line is None:
            continue
        span = entry.cited_end - entry.cited_start
        new_start = entry.new_line
        new_citation = f"{entry.file}:{new_start}"
        if span:
            new_citation += f"-{new_start + span}"
        lines[entry.line_index] = lines[entry.line_index].replace(
            f"`{entry.citation}`", f"`{new_citation}`", 1)
        entry.repaired = True
        repaired.append(entry)
    return repaired


def prune_entries(lines: list[str], entries: list[Entry],
                  keep: set[int]) -> tuple[list[str], list[Entry], list[Entry]]:
    """Drop every entry whose id no plan cites. Returns the surviving lines,
    the surviving entries, and the dropped ones."""
    dropped = [e for e in entries if e.num not in keep]
    if not dropped:
        return lines, entries, []
    drop_lines = {e.line_index for e in dropped}
    kept_entries = [e for e in entries if e.num in keep]
    new_lines = []
    shift = {}
    for index, line in enumerate(lines):
        if index in drop_lines:
            continue
        shift[index] = len(new_lines)
        new_lines.append(line)
    for entry in kept_entries:
        entry.line_index = shift[entry.line_index]
    return new_lines, kept_entries, dropped


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _legacy_report(summary: str) -> dict:
    return {
        "legacy": True, "stamp": None, "entries": [], "commits_since": {},
        "plan_citations": {"total": 0, "invalid": [],
                           "files_touched_since_stamp": 0},
        "pruned": [], "tier": 0, "summary": summary,
    }


def check(slice_dir: Path, task: str | None = None, repair: bool = False,
          prune: bool = False) -> dict:
    if not slice_dir.is_dir():
        raise Precondition(f"slice directory not found: {slice_dir}")
    if prune and task:
        raise Precondition("--prune scans every task's plan.md; it cannot be "
                           "combined with --task")

    ledger_path = slice_dir / "grounding.md"
    if not ledger_path.is_file():
        return _legacy_report("grounding: no ledger — no mechanical check")
    text = ledger_path.read_text(errors="replace")
    lines = text.splitlines()
    stamp = parse_stamp(lines)
    entries = parse_entries(lines)
    if not stamp or not entries:
        return _legacy_report("grounding: legacy ledger — no mechanical check")

    all_plans = plan_files(slice_dir, None)
    scoped_plans = plan_files(slice_dir, task) if task else all_plans
    if task and not scoped_plans:
        raise Precondition(f"no {slice_dir}/tasks/{task}*/plan.md to scope to")
    if prune and not all_plans:
        raise Precondition(
            f"{slice_dir}/tasks has no plan.md — refusing to prune every entry")

    pruned: list[Entry] = []
    if prune:
        lines, entries, pruned = prune_entries(
            lines, entries, referenced_ids(all_plans))
    if task:
        wanted = referenced_ids(scoped_plans)
        checked = [e for e in entries if e.num in wanted]
    else:
        checked = list(entries)

    cache = FileCache()
    for entry in checked:
        check_entry(entry, cache)

    repaired = repair_entries(lines, checked) if repair else []
    if repaired or pruned:
        ledger_path.write_text(
            "\n".join(lines) + ("\n" if text.endswith("\n") else ""))

    counts = Counter(e.status for e in checked)
    tier = 2 if (counts["MISSING"] or counts["GONE"]) else (
        1 if counts["MOVED"] else 0)
    report = {
        "legacy": False,
        "stamp": stamp,
        "entries": [e.as_json() for e in checked],
        "commits_since": commits_since(stamp),
        "plan_citations": check_plan_citations(
            scoped_plans, slice_dir, stamp, cache),
        "pruned": [e.id for e in pruned],
        "tier": tier,
    }
    report["summary"] = render_summary(report, task, bool(repaired))
    return report


def render_summary(report: dict, task: str | None, repaired: bool) -> str:
    stamp = report["stamp"] or {}
    since = report["commits_since"]
    parts = []
    for name, sha in stamp.items():
        count = since.get(name)
        note = (f"{count} commit{'' if count == 1 else 's'} since"
                if count is not None else "commits since unknown")
        parts.append(f"{name}@{sha[:12]} ({note})")
    stamp_part = "verified at " + ", ".join(parts) if parts else "no stamp"

    counts = Counter(e["status"] for e in report["entries"])
    bits = []
    for status in STATUS_ORDER:
        if not counts.get(status):
            continue
        label = f"{counts[status]} {status}"
        if status == "MOVED" and repaired:
            label += " (repaired)"
        bits.append(label)
    total = len(report["entries"])
    scope = f" cited by task {task}" if task else ""
    entries_part = f"{total} entr{'y' if total == 1 else 'ies'}{scope}"
    if bits:
        entries_part += ": " + ", ".join(bits)

    plans = report["plan_citations"]
    touched = plans["files_touched_since_stamp"]
    plans_part = (f"plans: {plans['total']} citations "
                  f"({len(plans['invalid'])} invalid), {touched} cited "
                  f"file{'' if touched == 1 else 's'} touched since stamp")
    return f"grounding: {stamp_part}; {entries_part}; {plans_part}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_human(report: dict) -> None:
    print(report["summary"])
    if report["legacy"]:
        return
    for entry in report["entries"]:
        # Sweep/unverifiable entries carry no drift signal; the summary counts
        # them and the report lines stay actionable.
        if entry["status"] not in DRIFT_STATUSES:
            continue
        cited = f"{entry['file']}:{entry['cited_line']}"
        if entry["cited_end"] and entry["cited_end"] != entry["cited_line"]:
            cited += f"-{entry['cited_end']}"
        line = f"  {entry['id']} {entry['status']}  {cited}"
        if entry["new_line"]:
            line += f" → {entry['new_line']}"
        if entry["repaired"]:
            line += " (repaired)"
        print(f"{line}  \"{entry['anchor']}\"")
    for invalid in report["plan_citations"]["invalid"]:
        print(f"  plan citation invalid — {invalid}")
    if report["pruned"]:
        print(f"  pruned (uncited by any plan): {', '.join(report['pruned'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slice_dir", help="path to slices/NNN_slug/")
    parser.add_argument("--task", metavar="NN",
                        help="scope to the entries this task's plan.md cites "
                             "(a letter suffix like 04a is fine)")
    parser.add_argument("--repair", action="store_true",
                        help="rewrite MOVED line numbers in place (no commit)")
    parser.add_argument("--prune", action="store_true",
                        help="delete every entry no tasks/*/plan.md cites")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable report on stdout")
    args = parser.parse_args(argv)

    try:
        report = check(Path(args.slice_dir), task=args.task,
                       repair=args.repair, prune=args.prune)
    except Precondition as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # anything unexpected is exit 1 by contract
        print(f"grounding_check failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 3 if report["tier"] >= 2 else 0


if __name__ == "__main__":
    sys.exit(main())
