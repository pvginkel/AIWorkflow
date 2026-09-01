#!/usr/bin/env python3
"""Preflight — the gate a pipeline command runs as step one.

Profiles (``--for triage|plan|run``) check exactly what that command needs. The
run profile is the full gate; the runner does NOT re-run preflight, so
``/dev:run-slice`` is where a broken project is caught.

Contract, expressed over `kc` primitives plus the repo's `.aiworkflowrc` (see
${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md and `project_config.py` for the
schema):

| Check                                          | triage | plan | run |
|------------------------------------------------|:------:|:----:|:---:|
| kc on PATH                                      |   x    |  x   |  x  |
| Control plane healthy (kc status)               |        |  x   |  x  |
| Manifest valid (kc project list >=1 component)  |        |  x   |  x  |
| `.aiworkflowrc` present and valid               |   x    |  x   |  x  |
| `spec_repo` set, directory exists               |   x    |  x   |  x  |
| `design_philosophy` set, file exists            |        |      |  x  |
| `test_phase.strategy` set + exists, when on     |        |      |  x  |
| `doc_phase.plan` set + exists, when on          |        |      |  x  |
| `devlock.lease` resolvable, when set            |        |      |  x  |
| Clean working tree                              |        |      |  x  |
| Synced with origin (ff / rebase; refuse dirty)  |        |  x   |  x  |
| Baseline `kc project build` (all components)    |        |      |  x  |

A phase the project switched off is not checked: its pointer is absent by
contract, and checking it would make an optional phase mandatory again.

The sync is the one step that *acts* rather than checks: pulling a clean base
onto its own origin destroys nothing, while a repo with uncommitted work is
refused, never pulled over (docs/preflight.md, "Notes on the sync").

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
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_config  # noqa: E402

# The project contract, for the pointer in every failure message. Resolved from
# this script's location (<plugin>/tools/preflight.py), not the cwd.
CONTRACT_DOC = Path(__file__).resolve().parents[1] / "docs" / "project-contract.md"

# Each pointer the config can carry: what it points at, whether that is a
# directory, and the TOML that sets it. The `when` field names the switch that
# makes it required — None meaning "always, for this profile".
POINTERS = {
    "spec_repo": ("the spec/slices repo (a directory)", True,
                  'spec_repo = "<path>"'),
    "design_philosophy": ("the project's design-philosophy / change-discipline "
                          "doc (a file)", False,
                          'design_philosophy = "<path>"'),
    "test_phase.strategy": ("the project's slice-testing-strategy doc (a file)",
                            False, '[test_phase]\n    strategy = "<path>"'),
    "doc_phase.plan": ("the project's slice-doc-plan doc (a file)", False,
                       '[doc_phase]\n    plan = "<path>"'),
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
        fail(2, "`kc` is not on PATH. This pipeline is kc-native and requires the "
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


def load_config(root: Path) -> project_config.ProjectConfig:
    """The config itself is a contract check: absent, unparseable or naming an
    unknown key all bail with the schema in the message."""
    try:
        return project_config.load(root)
    except project_config.ConfigError as e:
        fail(1, f"{e}\n\nSee {CONTRACT_DOC} for the full project contract.")


def check_pointer(cfg: project_config.ProjectConfig, key: str) -> None:
    """One `.aiworkflowrc` pointer: set, and its target on disk."""
    what, expect_dir, snippet = POINTERS[key]
    target = {
        "spec_repo": cfg.spec_repo,
        "design_philosophy": cfg.design_philosophy,
        "test_phase.strategy": cfg.test_strategy,
        "doc_phase.plan": cfg.doc_plan,
    }[key]
    if target is None:
        fail(1,
             f"Missing required `{key}` in {cfg.path}.\n"
             f"Add it, pointing at {what}:\n\n"
             f"    {snippet}\n\n"
             f"See {CONTRACT_DOC} for the full project contract.")
    ok = target.is_dir() if expect_dir else target.is_file()
    if not ok:
        kind = "directory" if expect_dir else "file"
        fail(1,
             f"`{key}` in {cfg.path} points to {target}, which is not an "
             f"existing {kind}.\nFix the path (see {CONTRACT_DOC}).")


def check_phase_pointers(cfg: project_config.ProjectConfig) -> None:
    """The two optional phases: checked only when the project runs them. A
    phase switched off has no procedure doc to point at, by contract."""
    if cfg.test_phase:
        check_pointer(cfg, "test_phase.strategy")
    if cfg.doc_phase:
        check_pointer(cfg, "doc_phase.plan")


def check_devlock(cfg: project_config.ProjectConfig) -> None:
    """A named lease must be somewhere the driver can create it. The lock file
    itself is created on demand (its content is irrelevant — the flock is on
    the inode), so only its directory has to exist; a typo'd path would
    otherwise take a lock nothing else contends for, coordinating nothing."""
    if cfg.devlock_lease is None:
        return
    if not cfg.devlock_lease.parent.is_dir():
        fail(1,
             f"`devlock.lease` in {cfg.path} resolves to "
             f"{cfg.devlock_lease}, whose directory does not exist. The lease "
             f"is relative to the spec repo and must sit where every "
             f"contending repo can see it (see {CONTRACT_DOC}).")


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


def sync_roots(root: Path,
               cfg: project_config.ProjectConfig | None) -> list[Path]:
    """Every checkout the sync covers: the target repo, then the environment's
    other repos, then the spec repo.

    In a KubeCoder pod the environment's repos are all checked out beside the
    target (`/work/<Repo>`), which is the layout `.aiworkflowrc` already encodes
    (`spec_repo = "../Specs"`) — so the siblings *are* the environment. A `.git`
    that is a file, not a directory, is a worktree and still a checkout.
    Deduped by resolved path, so a spec repo that is also a sibling is synced
    once.
    """
    roots = [root]
    seen = {root.resolve()}
    for d in sorted(root.parent.iterdir()):
        if not d.is_dir() or not (d / ".git").exists():
            continue
        if d.resolve() in seen:
            continue
        seen.add(d.resolve())
        roots.append(d)
    if cfg is not None and cfg.spec_repo is not None:
        if cfg.spec_repo.resolve() not in seen:
            roots.append(cfg.spec_repo)
    return roots


def check_synced(root: Path, cfg: project_config.ProjectConfig | None) -> None:
    """Bring every repo of the environment up to date with its origin.

    The *checked-out* branch is what gets synced, in the target repo and in
    every sibling: the run loop records whatever branch it finds the first time
    it touches a repo (`_base_branch`), so the checked-out branch is the base
    the slice will build on — no fixed `main` is assumed. A repo with a detached
    HEAD or a branch with no upstream has nothing to pull onto and is skipped.

    Behind and clean fast-forwards; behind with local commits rebases, and a
    rebase that conflicts is aborted (leaving the repo as it was) and handed to
    the operator. Ahead-only is left alone — unpushed commits are the
    operator's, and the run loop pushes at its test phase. A repo with
    uncommitted changes is refused rather than pulled over.
    """
    for repo in sync_roots(root, cfg):
        name, path = repo.name, str(repo)
        branch = _git(["-C", path, "symbolic-ref", "--quiet", "--short", "HEAD"])
        if branch.returncode != 0:
            continue  # detached HEAD — nothing to pull onto
        tracking = _git(["-C", path, "rev-parse", "--abbrev-ref",
                         "--symbolic-full-name", "@{u}"])
        if tracking.returncode != 0:
            continue  # no upstream — nothing to pull from
        upstream = tracking.stdout.strip()
        remote = upstream.split("/", 1)[0]

        fetched = _git(["-C", path, "fetch", "--quiet", remote])
        if fetched.returncode != 0:
            fail(2,
                 f"`git fetch {remote}` failed in `{name}` ({path}) "
                 f"(rc={fetched.returncode}). Preflight syncs every repo of the "
                 f"environment with its origin before a slice starts, and a "
                 f"remote it cannot reach is the environment's fault, not the "
                 f"project's — fix it (network, credentials) and retry.\n"
                 + (fetched.stderr or fetched.stdout).rstrip("\n"))

        counts = _git(["-C", path, "rev-list", "--left-right", "--count",
                       "HEAD...@{u}"])
        parts = counts.stdout.split()
        if counts.returncode != 0 or len(parts) != 2 or not all(
                p.isdigit() for p in parts):
            continue  # nothing countable — nothing to act on
        ahead, behind = int(parts[0]), int(parts[1])
        if behind == 0:
            continue  # up to date, or ahead only

        status = _git(["-C", path, "status", "--porcelain"])
        if status.stdout.strip():
            fail(1,
                 f"`{name}` ({path}) is {behind} behind {upstream} and has "
                 f"uncommitted changes — preflight will not pull over them. "
                 f"Commit or stash, or pull by hand, then retry.\n"
                 + status.stdout.rstrip("\n"))

        if ahead == 0:
            merged = _git(["-C", path, "merge", "--ff-only", "--quiet", "@{u}"])
            if merged.returncode != 0:
                fail(1,
                     f"`{name}` ({path}) is {behind} behind {upstream} but "
                     f"`git merge --ff-only` refused it "
                     f"(rc={merged.returncode}) — bring it up to date by hand, "
                     f"then retry.\n"
                     + (merged.stderr or merged.stdout).rstrip("\n"))
            continue

        rebased = _git(["-C", path, "rebase", "--quiet", "@{u}"])
        if rebased.returncode != 0:
            _git(["-C", path, "rebase", "--abort"])
            tail = (rebased.stdout + rebased.stderr).strip().splitlines()[-20:]
            fail(1,
                 f"`{name}` ({path}) has {ahead} local commits that do not "
                 f"rebase onto {upstream} ({behind} behind) — resolve by hand "
                 f"(rebase or merge), then retry. The rebase was aborted, so "
                 f"the repo stands where it did.\n" + "\n".join(tail))


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
    "triage": ["kc", "config", "spec_repo"],
    "plan": ["kc", "kc_status", "manifest", "config", "spec_repo", "synced"],
    "run": ["kc", "kc_status", "manifest", "config", "spec_repo",
            "design_philosophy", "phase_pointers", "devlock", "clean_tree",
            "synced", "baseline_build"],
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
    cfg = load_config(root) if "config" in checks else None
    if "spec_repo" in checks:
        check_pointer(cfg, "spec_repo")
    if "design_philosophy" in checks:
        check_pointer(cfg, "design_philosophy")
    if "phase_pointers" in checks:
        check_phase_pointers(cfg)
    if "devlock" in checks:
        check_devlock(cfg)
    if "clean_tree" in checks:
        check_clean_tree(root)
    if "synced" in checks:
        check_synced(root, cfg)
    if "baseline_build" in checks:
        check_baseline_build(root)
    # Silent on success.


if __name__ == "__main__":
    main()
