#!/usr/bin/env python3
"""Code health grader — ranks files by composite quality score.

Runs structural analysis (AST checks + radon cyclomatic complexity + complexipy
cognitive complexity) across every Python source tree in the uv workspace,
combines the output into a per-file score, and prints a ranked list of worst
offenders.

File exclusion is driven by .gitignore and .codehealthignore files (both at
root level and nested). No hardcoded exclusion lists.

Usage:
    uv run python -m tools.code_health                 # all members
    uv run python -m tools.code_health --top 20        # show top 20 (default: 20)
    uv run python -m tools.code_health --all           # show every file with findings
    uv run python -m tools.code_health --json          # JSON output
    uv run python -m tools.code_health --fail-under 4  # exit 1 if any file rates below 4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .cognitive_analyzer import run_cognitive_analysis
from .formatting import print_report
from .gitignore import load_ignore_patterns
from .models import FileReport, score_to_rating
from .python_analyzer import analyze_python

# Python source trees to analyze, relative to the workspace root. Each uv
# workspace member keeps its code under <member>/src.
#
# This grader is PYTHON-ONLY: every analyzer below it (AST checks, radon, complexipy)
# parses Python. The Go worker is therefore out of scope and deliberately absent —
# it is not an omission to "fix" by listing worker/, which has no src/ tree at all
# (its packages live directly under worker/internal, worker/cmd). Grading the worker
# needs a Go analyzer, which this tool does not have.
SOURCE_DIRS = (
    "controller/src",
    "bot/src",
    "mcp-server/src",
    "packages/kubecoder-contracts/src",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Code health grader")
    parser.add_argument("--top", type=int, default=20, help="Show top N files (default: 20)")
    parser.add_argument("--all", action="store_true", help="Show all files with findings")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-gitignore", action="store_true",
                        help="Disable .gitignore/.codehealthignore filtering")
    parser.add_argument("--fail-under", type=int, default=0, metavar="RATING",
                        help="Exit 1 if any file rates below RATING (1-10); 0 = never fail.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent

    ignore_spec = None if args.no_gitignore else load_ignore_patterns(root)

    reports: list[FileReport] = []
    for rel in SOURCE_DIRS:
        src_dir = root / rel
        if not src_dir.exists():
            continue
        if not args.json:
            print(f"Analyzing {rel}...", flush=True)
        reports.extend(analyze_python(src_dir, root, ignore_spec))

    if not args.json:
        print("Running cognitive complexity analysis...", flush=True)
    run_cognitive_analysis(root, reports)

    top_n = None if args.all else args.top
    print_report(reports, top_n, args.json, root)

    if args.fail_under:
        worst = min((score_to_rating(r.score) for r in reports), default=10)
        if worst < args.fail_under:
            return 1
    return 0


if __name__ == "__main__":
    # Pipe through a pager when connected to a TTY (unless --json).
    if sys.stdout.isatty() and "--json" not in sys.argv:
        import io
        import shutil

        buf = io.StringIO()
        _real_stdout = sys.stdout
        sys.stdout = buf
        try:
            exit_code = main()
        finally:
            output = buf.getvalue()
            sys.stdout = _real_stdout

        term_lines = shutil.get_terminal_size().lines
        if output.count("\n") > term_lines:
            pager = subprocess.Popen(["less", "-R"], stdin=subprocess.PIPE, encoding="utf-8")
            try:
                pager.communicate(input=output)
            except (BrokenPipeError, KeyboardInterrupt):
                pass
        else:
            print(output, end="")
        sys.exit(exit_code)
    else:
        sys.exit(main())
