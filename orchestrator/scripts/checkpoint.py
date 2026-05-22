#!/usr/bin/env python3
"""Dev-session verification checkpoint.

Run after the code-writer and after each fix round — the verification
checkpoint in the major/minor change workflows. Bundles a subproject's
check/build/test commands with diff-derived structural assertions, so the
coordinator reads a compact report instead of eyeballing the raw git diff
(which would then sit in its context for the rest of a long dev session).

Per project, the commands are whatever `PROJECT_COMMANDS` lists; the
reference config below assumes:

  backend    poetry run check, poetry run pytest
  frontend   pnpm run build              (build subsumes check)
  portal     pnpm run build, pnpm test   (Vitest)

Structural assertions, derived from `git status` over the subproject:

  - backend: app/models/ changed without a new alembic/versions/ file
  - backend: app/models/ changed without an app/data/test_data/ update
  - app/ (backend) or src/ (frontend/portal) changed without a matching
    tests/ change

Command failures are hard — checkpoint exits non-zero and dumps the
output. Structural assertions are printed as warnings; the coordinator
judges and acts on them. Slow e2e suites and the requirements.json /
test_plan.json spot-checks stay with the coordinator.

## Customize for your project

- `PROJECT_COMMANDS` — the check/build/test commands per subproject.
- `structural_warnings` — the diff-derived assertions. The path prefixes
  (app/models/, alembic/versions/, app/data/test_data/, src/, tests/)
  assume a particular layout; adjust them, or the whole function, to
  match your subprojects.

Usage:
    scripts/checkpoint.py --project backend
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_COL = 60

# Per-project check/build/test commands run at the checkpoint. Customize
# the keys and command lists for your subprojects.
PROJECT_COMMANDS: dict[str, list[tuple[str, list[str]]]] = {
    "backend": [
        ("check", ["poetry", "run", "check"]),
        ("pytest", ["poetry", "run", "pytest"]),
    ],
    "frontend": [
        ("build", ["pnpm", "run", "build"]),
    ],
    "portal": [
        ("build", ["pnpm", "run", "build"]),
        ("vitest", ["pnpm", "test"]),
    ],
}


def write_status(buf: io.StringIO, component: str, action: str, ok: bool) -> None:
    label = f"[{component}] {action}"
    padding = max(1, STATUS_COL - len(label))
    buf.write(label + " " * padding)
    buf.write("[  OK  ]\n" if ok else "[FAILED]\n")


def append(buf: io.StringIO, text: str | None) -> None:
    if not text:
        return
    buf.write(text)
    if not text.endswith("\n"):
        buf.write("\n")


def changed_paths(project: str) -> list[tuple[str, str]]:
    """(status, repo-relative path) for every working-tree change in the project."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", project],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"error: git status failed\n{result.stderr}")
    out: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:  # rename — take the new path
            path = path.split(" -> ", 1)[1]
        out.append((status, path.strip('"')))
    return out


def _is_test_path(path: str) -> bool:
    return (
        "/tests/" in path
        or "/__tests__/" in path
        or ".test." in path
        or ".spec." in path
        or path.startswith(("backend/tests/",))
    )


def structural_warnings(project: str, changes: list[tuple[str, str]]) -> list[str]:
    """Diff-derived assertions. Warnings only — the coordinator acts on them."""
    warnings: list[str] = []
    paths = [p for _, p in changes]

    if project == "backend":
        models_changed = any(p.startswith("backend/app/models/") for p in paths)
        migration_added = any(
            p.startswith("backend/alembic/versions/")
            and ("?" in status or "A" in status)
            for status, p in changes
        )
        test_data_changed = any(p.startswith("backend/app/data/test_data/") for p in paths)
        tests_changed = any(p.startswith("backend/tests/") for p in paths)
        source_changed = any(
            p.startswith("backend/app/") and not p.startswith("backend/app/data/test_data/")
            for p in paths
        )
        if models_changed and not migration_added:
            warnings.append(
                "app/models/ changed but no new file appears under "
                "alembic/versions/ — a schema change needs a migration"
            )
        if models_changed and not test_data_changed:
            warnings.append(
                "app/models/ changed but app/data/test_data/ was not updated "
                "— test data must stay in sync with the schema"
            )
        if source_changed and not tests_changed:
            warnings.append(
                "app/ changed but nothing under tests/ was added or updated "
                "— a behaviour change needs test coverage"
            )
    else:  # frontend / portal
        src_prefix = f"{project}/src/"
        source_changed = any(
            p.startswith(src_prefix) and not _is_test_path(p) for p in paths
        )
        tests_changed = any(
            (p.startswith(f"{project}/tests/") or _is_test_path(p)) for p in paths
        )
        if source_changed and not tests_changed:
            warnings.append(
                "src/ changed but no test (tests/ spec or *.test.*) was added "
                "or updated — a UI change needs test coverage"
            )
    return warnings


def run_commands(project: str) -> int:
    """Run the project's check/build/test commands. Silent on success;
    dumps the buffered output on the first failure."""
    buf = io.StringIO()
    project_dir = REPO_ROOT / project
    for action, cmd in PROJECT_COMMANDS[project]:
        result = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
        write_status(buf, project, action, ok=result.returncode == 0)
        if result.returncode != 0:
            append(buf, result.stdout)
            append(buf, result.stderr)
            sys.stdout.write(buf.getvalue())
            return result.returncode or 1
    sys.stdout.write(buf.getvalue())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project", required=True, choices=sorted(PROJECT_COMMANDS),
        help="Subproject to checkpoint",
    )
    args = parser.parse_args()
    project = args.project

    changes = changed_paths(project)
    print(f"checkpoint — {project}: {len(changes)} working-tree change(s)")
    for status, path in changes[:40]:
        print(f"  {status} {path}")
    if len(changes) > 40:
        print(f"  ... and {len(changes) - 40} more")
    print()

    warnings = structural_warnings(project, changes)

    rc = run_commands(project)

    if warnings:
        print()
        print(f"STRUCTURAL WARNINGS — {len(warnings)} (resolve or justify each):")
        for w in warnings:
            print(f"  - {w}")

    if rc != 0:
        print(f"\ncheckpoint FAILED — a command did not pass. Fix it before proceeding.")
        return rc
    if warnings:
        print("\ncheckpoint: commands passed; address the structural warnings above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
