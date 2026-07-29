#!/usr/bin/env python3
"""Shared grounding-checker dispatch for the workflow's scripts.

The plan loop and the task runner both re-anchor a slice's grounding ledger
around their dispatches (the format, statuses and tiers are normative in
${CLAUDE_PLUGIN_ROOT}/docs/grounding-ledger.md). What they share is the
mechanics — shelling out to grounding_check.py, and committing what
`--repair`/`--prune` rewrote — not the wording: each script renders its own
freshness line for its own agents, and those texts stay with the script that
dispatches them.

Neither function here raises. A checker that cannot run must never end a
planning cycle or a slice run, and a ledger commit git refuses costs a
re-repair at the next dispatch, not the run.

This is a library, not a CLI: `grounding_check.py <slice_dir> --json` is the
CLI, and it stays the single definition of the report shape and the exit
codes.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GROUNDING_CHECK = SCRIPT_DIR / "grounding_check.py"

CHECK_TIMEOUT = 300
COMMIT_TIMEOUT = 60
GIT_TIMEOUT = 30

LEDGER = "grounding.md"


def repo_root() -> Path:
    """The cwd to run the checker in: the target repo's root, from `git
    rev-parse --show-toplevel` in this process's cwd.

    The checker resolves citations against the repo it runs in, and the plugin's
    scripts no longer live inside that repo — both callers run from it, so its
    toplevel is the answer. A git that cannot answer falls back to the cwd
    itself: the checker then fails its own precondition and run_check reports no
    report, which is this module's contract for a check that cannot run.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return Path.cwd()
    if result.returncode != 0:
        return Path.cwd()
    return Path(result.stdout.strip())


def run_check(slice_dir: Path, *, task: str | None = None,
              repair: bool = False, prune: bool = False) -> dict | None:
    """grounding_check.py's JSON report for a slice, or None when there is none.

    Exit 0 (tier 0/1, or a legacy ledger) and exit 3 (tier 2 — entries that no
    longer anchor) both carry a full report: drift is a normal outcome that
    rides the dispatch, not a failure. None means no report at all — a
    usage/precondition error (exit 2), an unexpected failure (exit 1), a
    timeout, a checker that cannot be run, or output that will not parse — and
    every caller answers it the same way: behave as if no mechanical check ran.

    `task` scopes to the entries that task's plan.md cites, `repair` rewrites
    MOVED line numbers in place, `prune` drops the entries no plan cites.
    Neither rewrite is committed here; the caller owns the message.
    """
    cmd = [sys.executable, str(GROUNDING_CHECK),
           str(Path(slice_dir).resolve()), "--json"]
    if task:
        cmd += ["--task", task]
    if repair:
        cmd.append("--repair")
    if prune:
        cmd.append("--prune")
    try:
        result = subprocess.run(cmd, cwd=repo_root(), capture_output=True,
                                text=True, timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 3):
        return None
    try:
        report = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return report if isinstance(report, dict) else None


def commit_ledger(slice_dir: Path, message: str) -> bool:
    """Commit grounding.md as the checker left it, in the specs repo holding it.

    Staged AND committed by name: that working tree is shared with parallel
    sessions, so a bare `git commit -m` would sweep up whatever another session
    had staged. The explicit pathspec is what keeps this commit to the one file
    the checker rewrote. Returns False (never raises) when git refuses —
    nothing to commit, no repo, a lock, a failed hook.
    """
    slice_dir = Path(slice_dir).resolve()
    for args in (["add", "--", LEDGER],
                 ["commit", "-m", message, "--", LEDGER]):
        try:
            result = subprocess.run(["git", "-C", str(slice_dir), *args],
                                    capture_output=True, text=True,
                                    timeout=COMMIT_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
    return True
