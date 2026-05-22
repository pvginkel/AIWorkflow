#!/usr/bin/env python3
"""Regenerate the OpenAPI cache for one or more frontend subprojects.

Picks a free port, starts the backend, waits for the OpenAPI spec
endpoint to be reachable, runs `pnpm generate:api` in the requested
subproject(s), and stops the backend cleanly on exit.

We poll `/api/docs/openapi.json` directly rather than `/health/readyz`:
the readiness probe can sit at HTTP 503 indefinitely when a non-critical
dependency is degraded in the local dev environment, even though the
OpenAPI endpoint itself is perfectly usable. What we actually care
about is whether the downstream `generate:api` fetch will succeed, so
that's what we poll.

## Customize for your project

The defaults below assume:
- A `backend/` subproject with `poetry run cli prepare` (one-shot setup)
  and `poetry run dev` (long-running server) commands.
- The OpenAPI spec lives at `/api/docs/openapi.json`.
- One or more sibling subprojects (`frontend/`, `portal/`) with a
  `pnpm generate:api` script in their `package.json`.

If your stack differs, edit the constants and the `run_prepare` /
`start_backend` helpers. The flow (prepare → start backend → wait →
generate → stop) is the load-bearing part — keep it.

Usage:
    scripts/regenerate-openapi.py --frontend
    scripts/regenerate-openapi.py --portal
    scripts/regenerate-openapi.py --frontend --portal
    scripts/regenerate-openapi.py --frontend --portal --commit --slice 182
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
LOG_DIR = ROOT / "logs"

OPENAPI_PATH = "/api/docs/openapi.json"
READY_TIMEOUT_S = 120

# OpenAPI cache directory per regeneration target. `--commit` stages and
# commits exactly the directories for the targets that were regenerated.
# Customize the keys/paths for your subprojects.
CACHE_DIRS = {
    "frontend": "frontend/openapi-cache",
    "portal": "portal/openapi-cache",
}


def pick_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_for_ready(port: int, dev_proc: subprocess.Popen[bytes], timeout_s: int) -> None:
    """Poll the OpenAPI spec endpoint until it returns 200 or the deadline expires.

    Fails fast if the backend process has exited.
    """
    url = f"http://localhost:{port}{OPENAPI_PATH}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rc = dev_proc.poll()
        if rc is not None:
            raise RuntimeError(
                f"Backend exited before becoming ready (exit code {rc}). "
                f"See {LOG_DIR / 'regenerate-openapi-backend.log'}"
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(
        f"Backend did not become ready on port {port} within {timeout_s}s "
        f"(polled {url}). See {LOG_DIR / 'regenerate-openapi-backend.log'}"
    )


def stop_backend(dev_proc: subprocess.Popen[bytes]) -> None:
    if dev_proc.poll() is not None:
        return
    try:
        os.killpg(dev_proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        dev_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(dev_proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        dev_proc.wait(timeout=5)


def run_prepare() -> int:
    result = subprocess.run(
        ["poetry", "run", "cli", "prepare"],
        cwd=BACKEND_DIR,
    )
    return result.returncode


def start_backend(port: int, log_path: Path) -> subprocess.Popen[bytes]:
    env = {**os.environ, "PORT": str(port)}
    log_file = open(log_path, "wb")
    try:
        return subprocess.Popen(
            ["poetry", "run", "dev"],
            cwd=BACKEND_DIR,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception:
        log_file.close()
        raise


def regenerate(project: str, port: int) -> int:
    project_dir = ROOT / project
    env = {**os.environ, "PORT": str(port)}
    print(f"[{project}] pnpm generate:api", flush=True)
    result = subprocess.run(
        ["pnpm", "generate:api"],
        cwd=project_dir,
        env=env,
    )
    return result.returncode


def commit_caches(targets: list[str], slice_id: str | None) -> int:
    """Stage and commit exactly the OpenAPI caches that were regenerated.

    Scoped to the cache directories for `targets` only — never stages
    anything else. If the regenerated spec is byte-identical to the
    committed cache (no spec change this slice), nothing is staged and
    the commit is skipped.
    """
    paths = [CACHE_DIRS[t] for t in targets]
    if subprocess.run(["git", "add", "--", *paths], cwd=ROOT).returncode != 0:
        print("git add failed", file=sys.stderr)
        return 1
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *paths], cwd=ROOT
    )
    if staged.returncode == 0:
        print("OpenAPI cache unchanged — nothing to commit", flush=True)
        return 0
    suffix = f" (slice {slice_id})" if slice_id else ""
    message = f"Regenerate OpenAPI spec: {', '.join(targets)}{suffix}"
    commit = subprocess.run(["git", "commit", "-m", message, "--", *paths], cwd=ROOT)
    if commit.returncode != 0:
        print("git commit failed", file=sys.stderr)
        return 1
    print(f"Committed: {message}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", action="store_true", help="Regenerate frontend OpenAPI client")
    parser.add_argument("--portal", action="store_true", help="Regenerate portal OpenAPI client")
    parser.add_argument(
        "--timeout",
        type=int,
        default=READY_TIMEOUT_S,
        help="Seconds to wait for backend readiness (default: %(default)s)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="After regenerating, stage and commit exactly the regenerated caches",
    )
    parser.add_argument(
        "--slice",
        dest="slice_id",
        metavar="NUMBER",
        help="Slice identifier for the --commit commit message",
    )
    args = parser.parse_args()

    targets: list[str] = []
    if args.frontend:
        targets.append("frontend")
    if args.portal:
        targets.append("portal")
    if not targets:
        parser.error("Specify at least one of --frontend or --portal")

    LOG_DIR.mkdir(exist_ok=True)
    backend_log = LOG_DIR / "regenerate-openapi-backend.log"

    rc = run_prepare()
    if rc != 0:
        print("cli prepare failed", file=sys.stderr)
        return rc

    port = pick_free_port()
    print(f"Starting backend on port {port} (log: {backend_log})", flush=True)
    dev_proc = start_backend(port, backend_log)

    try:
        wait_for_ready(port, dev_proc, args.timeout)
        print(f"Backend ready on port {port}", flush=True)
        for target in targets:
            rc = regenerate(target, port)
            if rc != 0:
                print(f"generate:api failed for {target}", file=sys.stderr)
                return rc
    finally:
        stop_backend(dev_proc)

    if args.commit:
        return commit_caches(targets, args.slice_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
