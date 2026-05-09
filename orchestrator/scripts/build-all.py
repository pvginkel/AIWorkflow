#!/usr/bin/env python3
"""Build all components of the {{ project_name }} monorepo.

Customize the STEPS list for your project. Each entry is:
    (component_label, action_description, command_argv, working_directory)

Add or remove rows so this script installs/builds every subproject your
slices depend on. The /run-slice pre-flight invokes this script to catch
dependency drift and broken builds before any dev agent starts.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _initd_log import run_step

REPO_ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, str, list[str], Path]] = [
    ("root", "poetry install", ["poetry", "install", "--no-interaction"], REPO_ROOT),
    (
        "root",
        "pnpm install",
        ["pnpm", "install", "--frozen-lockfile", "--config.confirmModulesPurge=false"],
        REPO_ROOT,
    ),
    # Add per-subproject install/build steps below. Examples:
    # ("backend", "poetry install", ["poetry", "install", "--no-interaction"], REPO_ROOT / "backend"),
    # ("frontend", "pnpm build-fast", ["pnpm", "build-fast"], REPO_ROOT / "frontend"),
    # ("portal", "pnpm build-fast", ["pnpm", "build-fast"], REPO_ROOT / "portal"),
]


def main() -> int:
    for component, action, cmd, cwd in STEPS:
        if run_step(component, action, cmd, cwd) != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
