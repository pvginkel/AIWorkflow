#!/usr/bin/env python3
"""Preflight for the `dev` plugin — the gate a pipeline command runs as step one.

Profiles (``--for triage|plan|run``) check exactly what that command needs. The
run profile is the full gate; the runner does NOT re-run preflight, so
``/dev:run-slice`` is where a broken project is caught.

Contract, expressed over `kc` primitives + three machine-checkable `CLAUDE.md`
lines (see docs/project-contract.md):

    Spec repo: <path>
    Slice testing strategy: <path-to-doc>
    Design philosophy: <path-to-doc>

| Check                                         | triage | plan | run |
|-----------------------------------------------|:------:|:----:|:---:|
| kc on PATH                                     |   x    |  x   |  x  |
| Control plane healthy (kc status)              |        |  x   |  x  |
| Manifest valid (kc project list ≥1 component)  |        |  x   |  x  |
| `Spec repo:` in CLAUDE.md, path exists         |   x    |  x   |  x  |
| `Slice testing strategy:` set, target exists   |        |      |  x  |
| `Design philosophy:` set, target exists        |        |      |  x  |
| Clean working tree                             |        |      |  x  |
| Baseline `kc project build` (all components)   |        |      |  x  |

**Silent on success** (exit 0). On failure, prints ONE actionable message —
what is missing, the exact line/fix, and a pointer to the project contract — so
a new repo self-onboards from the error text. Exit codes:

    0  pass
    1  contract violation (the project must fix something)
    2  environment broken (kc missing / control plane down / not in a git repo)

The command runs the profile and relays this message verbatim on non-zero.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The project contract, for the pointer in every failure message. Resolved from
# this script's install location (<plugin>/tools/preflight.py), not a repo path.
CONTRACT_DOC = Path(__file__).resolve().parent.parent / "docs" / "project-contract.md"

# The three machine-checkable CLAUDE.md entries (label → what its value points at).
ENTRIES = {
    "Spec repo": "the spec/slices repo (a directory)",
    "Slice testing strategy": "the project's slice-testing-strategy doc (a file)",
    "Design philosophy": "the project's design-philosophy / change-discipline doc (a file)",
}


def fail(code: int, message: str):
    """Print one actionable message and exit with the contract/env code."""
    sys.stderr.write(message.rstrip("\n") + "\n")
    raise SystemExit(code)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def repo_root() -> Path:
    result = _git(["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        fail(2, "Not inside a git repository — run the pipeline command from the "
                "target code repo.")
    return Path(result.stdout.strip())


def check_kc() -> None:
    if shutil.which("kc") is None:
        fail(2, "`kc` is not on PATH. The dev plugin is kc-native and requires the "
                "KubeCoder CLI — run inside a KubeCoder pod, where `kc` is always "
                "available.")


def check_kc_status() -> None:
    """The control plane must be up before a command that dispatches sessions.

    `kc status` probes the worker daemon (one loopback /healthz) and the
    controller (the authenticated env self-read), and exits non-zero when
    either fails. Both probes are bounded by the CLI itself (5s + 10s), so no
    timeout is needed here. Its report goes to stdout; a precondition failure
    (a broken or outdated pod) goes to stderr — relay whichever spoke.
    """
    result = subprocess.run(["kc", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        report = (result.stdout + result.stderr).strip()
        fail(2,
             "`kc status` reports a broken control plane. Every agent this "
             "pipeline dispatches runs through `kc session`, so the first "
             "dispatch would fail — fix the environment before retrying (the "
             "report says which half is down).\n" + report)


def _claude_md(root: Path) -> str:
    path = root / "CLAUDE.md"
    return path.read_text() if path.is_file() else ""


def _entry(text: str, label: str) -> str | None:
    """Read a `Label: value` line, tolerating markdown decoration (list markers,
    bold, backticks). Returns the stripped value, or None if the line is absent."""
    # Tolerate markdown decoration around the label and value: leading list
    # markers / blockquote, `**bold**` or backticks wrapping the label, the
    # colon, and the value (`- **Spec repo:** ` + backticked path all match).
    pattern = re.compile(
        r"(?m)^[\s>*`-]*" + re.escape(label) + r"[\s*`]*:[\s*`]*(.+?)[\s*`]*$"
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _resolve(root: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (root / p)


def check_entry(root: Path, label: str, *, expect_dir: bool) -> None:
    text = _claude_md(root)
    value = _entry(text, label)
    if value is None:
        fail(1,
             f"Missing required CLAUDE.md entry: `{label}:`.\n"
             f"Add a line to {root / 'CLAUDE.md'} pointing at {ENTRIES[label]}:\n\n"
             f"    {label}: <path>\n\n"
             f"See {CONTRACT_DOC} for the full project contract.")
    target = _resolve(root, value)
    ok = target.is_dir() if expect_dir else target.is_file()
    if not ok:
        kind = "directory" if expect_dir else "file"
        fail(1,
             f"CLAUDE.md `{label}: {value}` points to {target}, which is not an "
             f"existing {kind}.\nFix the path in {root / 'CLAUDE.md'} "
             f"(see {CONTRACT_DOC}).")


def check_manifest(root: Path) -> None:
    result = subprocess.run(
        ["kc", "project", "list", "--output=json"],
        cwd=str(root), capture_output=True, text=True)
    if result.returncode != 0:
        fail(1,
             "No valid `.kubecoder/project.yaml` manifest: `kc project list "
             f"--output=json` failed (rc={result.returncode}).\n"
             f"{(result.stderr or result.stdout).strip()}\n\n"
             f"Author a manifest so `kc project list` returns the components "
             f"(see {CONTRACT_DOC}).")
    try:
        components = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        fail(1, "`kc project list --output=json` did not emit valid JSON — "
                f"check the manifest (see {CONTRACT_DOC}).")
    if not components:
        fail(1, "`.kubecoder/project.yaml` declares no components. Add at least "
                f"one (see {CONTRACT_DOC}).")


def check_clean_tree(root: Path) -> None:
    result = _git(["-C", str(root), "status", "--porcelain"])
    if result.stdout.strip():
        fail(1,
             "The working tree has uncommitted changes; commit or stash before "
             "running a slice (a dirty tree is never the runner's to clean up).\n"
             + result.stdout.rstrip("\n"))


def check_baseline_build(root: Path) -> None:
    result = subprocess.run(
        ["kc", "project", "build"], cwd=str(root), capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-40:]
        fail(1,
             "Baseline `kc project build` failed — the suite must be green before a "
             "slice runs (a baseline-broken build screams on task 1 otherwise). Fix "
             "the baseline, or narrow the manifest's build list, then retry.\n"
             + "\n".join(tail))


# Triage deliberately has no `kc_status`: it dispatches nothing and touches no
# kc surface — it is intake, doable without the repo. Gating it on live
# controller reachability would fail work that needs none of it.
PROFILES = {
    "triage": ["kc", "spec_repo"],
    "plan": ["kc", "kc_status", "manifest", "spec_repo"],
    "run": ["kc", "kc_status", "manifest", "spec_repo", "testing_strategy",
            "design_philosophy", "clean_tree", "baseline_build"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--for", dest="profile", required=True,
                        choices=sorted(PROFILES), help="which command's profile to run")
    args = parser.parse_args()
    checks = PROFILES[args.profile]

    # kc first (env gate), before anything that shells out to it; the control
    # plane next — both are environment, and neither needs the repo.
    if "kc" in checks:
        check_kc()
    if "kc_status" in checks:
        check_kc_status()
    root = repo_root()
    if "manifest" in checks:
        check_manifest(root)
    if "spec_repo" in checks:
        check_entry(root, "Spec repo", expect_dir=True)
    if "testing_strategy" in checks:
        check_entry(root, "Slice testing strategy", expect_dir=False)
    if "design_philosophy" in checks:
        check_entry(root, "Design philosophy", expect_dir=False)
    if "clean_tree" in checks:
        check_clean_tree(root)
    if "baseline_build" in checks:
        check_baseline_build(root)
    # Silent on success.


if __name__ == "__main__":
    main()
