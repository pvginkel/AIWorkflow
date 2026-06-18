#!/usr/bin/env python3
"""Pre-flight checks before running a slice.

Bundles the full repo build, test collection, and test-harness
readiness checks into one script. Silent on success; on failure, dumps
the buffered output of every check (including the OK lines for earlier
checks) plus the captured output from the failing step. The /run-slice
pre-flight (Step 0) invokes this before any dev agent starts, so
environment drift is caught up front rather than surfacing mid-slice.

## Customize for your project

The flow — build, then test collection, then test-harness readiness — is
the load-bearing part. The project-specific pieces all live in `main()`:

- The build step delegates to `build-all.py` (customize its `STEPS`).
- The test-collection and harness-readiness checks (`run_init_d` calls)
  assume a Poetry/pytest backend with a one-shot `prepare` command that
  warms the test harness. Replace them with whatever confirms your test
  harness can collect and run tests.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "scripts"

STATUS_COL = 60


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


def run_init_d(
    buf: io.StringIO,
    component: str,
    action: str,
    cmd: list[str],
    cwd: Path,
    timeout: float | None = None,
) -> int:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        write_status(buf, component, action, ok=False)
        buf.write(f"timed out after {timeout}s\n")
        append(buf, e.stdout)
        append(buf, e.stderr)
        return 124
    write_status(buf, component, action, ok=result.returncode == 0)
    if result.returncode != 0:
        append(buf, result.stdout)
        append(buf, result.stderr)
    return result.returncode


def run_passthrough(buf: io.StringIO, cmd: list[str], cwd: Path) -> int:
    """Run a command and capture its output verbatim into buf.

    Used for build-all.py, which emits its own init.d-style status lines.
    """
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    append(buf, result.stdout)
    append(buf, result.stderr)
    return result.returncode


def main() -> int:
    buf = io.StringIO()

    rc = run_passthrough(
        buf, ["python3", str(SCRIPT_DIR / "build-all.py")], REPO_ROOT
    )
    if rc != 0:
        sys.stdout.write(buf.getvalue())
        return rc

    # --- Customize: test-harness readiness checks for your toolchain. ---
    rc = run_init_d(
        buf,
        "backend",
        "pytest --co",
        ["poetry", "run", "pytest", "--co", "-q"],
        REPO_ROOT / "backend",
    )
    if rc != 0:
        sys.stdout.write(buf.getvalue())
        return rc

    rc = run_init_d(
        buf,
        "backend",
        "cli prepare",
        ["poetry", "run", "cli", "prepare"],
        REPO_ROOT / "backend",
        timeout=10,
    )
    if rc != 0:
        sys.stdout.write(buf.getvalue())
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
