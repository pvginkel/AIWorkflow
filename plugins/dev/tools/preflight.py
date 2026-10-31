#!/usr/bin/env python3
"""Preflight — the gate a pipeline command runs as step one.

Profiles (``--for triage|plan|run``) check exactly what that command needs. The
run profile is the full gate; the runner does NOT re-run preflight, so
``/dev:run-slice`` is where a broken project is caught.

Contract, expressed over `kc` primitives plus the repo's `.aiworkflowrc` (see
${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md and `project_config.py` for the
schema):

| Check                                                | triage | plan | run |
|------------------------------------------------------|:------:|:----:|:---:|
| kc on PATH                                           |   x    |  x   |  x  |
| Control plane healthy (kc status)                    |        |  x   |  x  |
| Manifest valid (kc project list >=1 component)       |        |  x   |  x  |
| `.aiworkflowrc` present and valid                    |   x    |  x   |  x  |
| `spec_repo` set, directory exists                    |   x    |  x   |  x  |
| Retired spec-tree guard removed (spec repo)          |   x    |  x   |  x  |
| `design_philosophy` set, file exists                 |        |      |  x  |
| `test_phase.strategy` set + exists, when on          |        |      |  x  |
| `doc_phase.plan` set + exists, when on               |        |      |  x  |
| `devlock.lease` resolvable, when set                 |        |      |  x  |
| Declared Target repos cloned (`--slice` only)        |        |  x   |  x  |
| Clean working tree                                   |        |      |  x  |
| Synced with origin (ff / rebase; refuse dirty)       |        |  x*  |  x  |
| Every `needs:` slice completed (`--slice` only)      |        |  x   |     |
| Baseline `kc project setup`, then `kc project build` |        |      |  x  |

A phase the project switched off is not checked: its pointer is absent by
contract, and checking it would make an optional phase mandatory again.

* Planning blocks only on the repos it may touch: the target repo, the spec
repo, and every repo a Target of the `--slice` plan names. Any other repo's
refusal is a `warning:` line and the sync goes on; a repo that vanished
mid-sync, or whose GitHub origin is gone, is skipped. Run refuses them all.

A pending phase of the `--slice` plan whose repo-path Target
`.kubecoder/config.yaml` declares and the pod has not cloned yet is an
environment fault (exit 2), named as such (`check_targets_cloned`); without
`--slice` there is no plan to read, and the check passes.

A slice `slice.md` says must follow others — its front matter's `needs:` line,
which triage writes — is not ready to plan until each of them has completed
(`check_ready_to_plan`, exit 1). It runs after the sync, so a slice that
completed elsewhere reads as completed here.

Three steps *act* rather than check. The sync pulls a clean base onto its own
origin, which destroys nothing, while a repo with uncommitted work is refused,
never pulled over (docs/preflight.md, "Notes on the sync"). The guard removal
deletes the pre-commit hook an older plugin installed in the spec repo's git
dir — only a hook carrying the guard's marker; anyone else's is left alone.
Under run, the baseline's `kc project setup` installs what the repo's lockfiles
ask for before the build, so an install behind its lockfile does not read as a
red baseline; a red or timed-out setup is a `warning:` line when the build is
green (docs/preflight.md, "Notes on the run baseline").

**Silent on success** (exit 0) — but for the notes: a line when it removed that
hook, a `warning:` line under plan for each repo the sync passed over (*,
above), and one under run when the baseline's setup was red or timed out and
its build green. A failure stops at the first check that fails and is data
(Failure): the check, the fact it found, the fix that makes it pass, and what a
command it ran said. On stderr they read as one message, the fact before the
fix, from which a new repo self-onboards; with `--json`, stdout carries one
object instead, pass or fail, for a stage to render into an `action` document
(docs/preflight.md, "Output"). Exit codes:

    0  pass
    1  contract violation (the project must fix something)
    2  environment broken (kc missing / control plane down / not in a git repo)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_target  # noqa: E402
import project_config  # noqa: E402
import run_loop  # noqa: E402

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


class Failure(SystemExit):
    """A check that did not pass, as data. `check` names it as the profiles
    do (`PROFILES`; a pointer by its key, `git_repo` and `slice` for the repo
    and `--slice` themselves); `fact` is what it found; `fix` what makes it
    pass, with the exact line or command where there is one; `output` what a
    command it ran said, verbatim. Exits with `code`: 1 the project's to fix,
    2 the environment's."""

    def __init__(self, code: int, check: str, fact: str, fix: str,
                 output: str = ""):
        super().__init__(code)
        self.check = check
        self.fact = fact.strip()
        self.fix = fix.strip()
        self.output = output.rstrip("\n")

    def text(self) -> str:
        """The failure as one message: the fact, the fix, the output."""
        return "\n".join(part for part in (self.fact, self.fix, self.output)
                         if part)

    def data(self) -> dict:
        return {"code": self.code, "check": self.check, "fact": self.fact,
                "fix": self.fix, "output": self.output}


# Under --json, main collects the notes here and prints them in its one
# object; None prints each note as its line when it is made, and a failure's
# message on stderr when it is raised.
NOTES: list[dict] | None = None


def fail(code: int, check: str, fact: str, fix: str, output: str = ""):
    """Stop at a check that failed (Failure): its message on stderr at once,
    or, under --json, the object main prints."""
    failure = Failure(code, check, fact, fix, output)
    if NOTES is None:
        sys.stderr.write(failure.text() + "\n")
    raise failure


def note(check: str, text: str, warning: bool = True) -> None:
    """A note on a pass: its line on stdout, `warning:` first where it is
    one, or, under --json, an entry of the object's `notes`."""
    if NOTES is None:
        print(f"warning: {text}" if warning else text)
    else:
        NOTES.append({"check": check, "note": text})


class Refusal(Exception):
    """A repo the sync will not sync: the exit code, fact, fix and output to
    `fail` with — or, in a repo planning does not block on, `summary`, the
    refusal on one line (the fact's first unless the refusal gives its own),
    for the note made instead."""

    def __init__(self, code: int, fact: str, fix: str, output: str = "",
                 summary: str | None = None):
        super().__init__(fact)
        self.code = code
        self.fact = fact
        self.fix = fix
        self.output = output
        self.summary = summary or fact.splitlines()[0]


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


# git's ref-update race: two sessions in one pod fetching the same clone at the
# same moment (parallel /dev:plan-slice sessions share the /work siblings), and
# the loser's ref transaction finds the ref already moved. Nothing is wrong with
# the network or the credentials, and a moment later the fetch goes through —
# so it is retried, with these waits (seconds) between the attempts.
FETCH_RACE_MARKER = "incorrect old value provided"
FETCH_RACE_BACKOFF = (1, 2)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _lost_race(result: subprocess.CompletedProcess) -> bool:
    return FETCH_RACE_MARKER in (result.stderr or "") + (result.stdout or "")


def _fetch(path: str, remote: str) -> tuple[subprocess.CompletedProcess, int]:
    """`git fetch` with the ref-update race retried; any other failure is
    returned at once. Returns the last result and the attempts it took."""
    attempts = 0
    for wait in (*FETCH_RACE_BACKOFF, None):
        attempts += 1
        fetched = _git(["-C", path, "fetch", "--quiet", remote])
        if fetched.returncode == 0 or wait is None or not _lost_race(fetched):
            break
        _sleep(wait)
    return fetched, attempts


def repo_root() -> Path:
    result = _git(["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        fail(2, "git_repo", "Not inside a git repository.",
             "Run the pipeline command from the target code repo.")
    return Path(result.stdout.strip())


def check_kc() -> None:
    if shutil.which("kc") is None:
        fail(2, "kc", "`kc` is not on PATH, and this pipeline is kc-native: it "
                      "requires the KubeCoder CLI.",
             "Run inside a KubeCoder pod, where `kc` is always available.")


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
        fail(2, "kc_status",
             "`kc status` reports a broken control plane. Every agent this "
             "pipeline dispatches runs through `kc session`, so the first "
             "dispatch would fail.",
             "Mend the half of the control plane the report names as down.",
             report)


def load_config(root: Path) -> project_config.ProjectConfig:
    """The config itself is a contract check: absent, unparseable or naming an
    unknown key all bail with the schema in the message."""
    try:
        return project_config.load(root)
    except project_config.ConfigError as e:
        fail(1, "config", str(e),
             f"Write `.aiworkflowrc` at the repo root as said, or correct it; "
             f"the full project contract is {CONTRACT_DOC}.")


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
        fail(1, key, f"Missing required `{key}` in {cfg.path}.",
             f"Add it, pointing at {what}:\n\n"
             f"    {snippet}\n\n"
             f"The full project contract is {CONTRACT_DOC}.")
    ok = target.is_dir() if expect_dir else target.is_file()
    if not ok:
        kind = "directory" if expect_dir else "file"
        fail(1, key,
             f"`{key}` in {cfg.path} points to {target}, which is not an "
             f"existing {kind}.",
             f"Correct the path (the project contract: {CONTRACT_DOC}).")


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
        fail(1, "devlock",
             f"`devlock.lease` in {cfg.path} resolves to "
             f"{cfg.devlock_lease}, whose directory does not exist.",
             f"Point it at a directory that exists: the lease is relative to "
             f"the spec repo and must sit where every contending repo can see "
             f"it (the project contract: {CONTRACT_DOC}).")


# ---------------------------------------------------------------------------
# The retired spec-tree guard. Plugins 0.9.86–0.9.92 installed a pre-commit
# hook in the spec repo's git dir that refused a commit on a `phase/*` branch
# the committing session's environment did not name — a phase then branched
# the shared spec tree in place. From 0.9.93 such a phase works in a linked
# worktree of its own, whose commits are on its phase branch and run the
# shared git dir's hooks, so the guard would refuse every one of them. Every
# profile removes it; an environment still on an older plugin puts it back at
# its own preflight until it is updated, and the next preflight here removes
# it again.
# ---------------------------------------------------------------------------

GUARD_MARKER = "# aiworkflow spec-tree guard"


def remove_spec_tree_guard(cfg: project_config.ProjectConfig | None) -> None:
    """Delete the spec repo's pre-commit hook where git looks for it
    (`core.hooksPath` honoured) when it is the retired guard — its text
    carries GUARD_MARKER — and say so in one line. A hook without the marker
    is someone else's and is left alone; no hook, no spec repo, or a spec
    repo that is no git repo is nothing to do. A guard that cannot be
    deleted is an environment failure (exit 2): every commit a spec-repo
    phase makes in its worktree would meet it."""
    if cfg is None or cfg.spec_repo is None:
        return
    where = _git(["-C", str(cfg.spec_repo), "rev-parse", "--git-path",
                  "hooks/pre-commit"])
    if where.returncode != 0 or not where.stdout.strip():
        return
    target = Path(where.stdout.strip())
    if not target.is_absolute():
        target = cfg.spec_repo / target
    try:
        text = target.read_text(errors="replace")
    except OSError:
        return
    if GUARD_MARKER not in text:
        return
    try:
        target.unlink()
    except OSError as e:
        fail(2, "spec_tree_guard",
             f"Could not remove the retired spec-tree guard {target} ({e}): "
             f"a phase on the spec repo works in a worktree of its own, and "
             f"the guard refuses its commits there.",
             f"Delete {target}.")
    note("spec_tree_guard",
         f"removed the retired spec-tree guard {target} — a phase on the "
         f"spec repo works in a worktree of its own, and the guard would "
         f"refuse its commits there", warning=False)


def check_manifest(root: Path) -> None:
    result = subprocess.run(
        ["kc", "project", "list", "--output=json"],
        cwd=str(root), capture_output=True, text=True)
    if result.returncode != 0:
        fail(1, "manifest",
             "No valid `.kubecoder/project.yaml` manifest: `kc project list "
             f"--output=json` failed (rc={result.returncode}).",
             f"Author a manifest so `kc project list` returns the components "
             f"(the project contract: {CONTRACT_DOC}).",
             (result.stderr or result.stdout).strip())
    try:
        components = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        fail(1, "manifest",
             "`kc project list --output=json` did not emit valid JSON.",
             f"Correct the manifest, `.kubecoder/project.yaml` (the project "
             f"contract: {CONTRACT_DOC}).")
    if not components:
        fail(1, "manifest", "`.kubecoder/project.yaml` declares no components.",
             f"Add at least one (the project contract: {CONTRACT_DOC}).")


def current_branch(repo: Path) -> str | None:
    """The checked-out branch, None on a detached HEAD."""
    branch = _git(["-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"])
    return branch.stdout.strip() if branch.returncode == 0 else None


# ---------------------------------------------------------------------------
# A repo on a run loop's phase branch. The loop checks `phase/<slice>-P<id>`
# (the doc phase: `phase/<slice>-docs`) out in the phase's target repo — the
# shared spec tree included — and checks the base back out once the phase
# merges, or at a bail. Met here, the branch is usually a live run's, often
# another environment's: pushing it, tracking it or checking something else
# out changes that run's branch under it. So such a repo is refused before any
# other check looks at it, naming the run when its run.lock is held.
# ---------------------------------------------------------------------------

PHASE_BRANCH = re.compile(r"phase/(\d+)-")


def find_slice_dir(spec_repo: Path, num: str) -> Path | None:
    """Slice `num`'s folder: `slices/` while it runs, else backlog or
    completed. None when the spec repo has none."""
    for parent in ("slices", "slices/backlog", "slices/completed"):
        folder = spec_repo / parent
        if not folder.is_dir():
            continue
        for d in sorted(folder.iterdir()):
            if d.is_dir() and d.name.split("_")[0] == num:
                return d
    return None


def run_lock_holder(lock: Path) -> str | None:
    """The holder's note when a live driver holds `lock`, else None.

    A probe that must not disturb the holder: opened read-only and never
    created, so the note is neither truncated nor rewritten; a shared lock
    tried non-blocking, released at once (the window where a starting driver
    would find it busy is that one call)."""
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:
        return None  # no run.lock — no run has held it
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            note = os.read(fd, 4096).decode(errors="replace").strip()
            return note or "(no holder note)"
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def _indented(note: str) -> str:
    return "\n".join(f"  {line}" for line in note.splitlines())


def refuse_phase_branch(repo: Path, branch: str | None,
                        cfg: project_config.ProjectConfig | None) -> None:
    """Refuse (a Refusal, exit 1) a repo on a `phase/` branch — telling a
    live run's branch from one a bail left, and never advising a push or an
    upstream."""
    if branch is None or not branch.startswith("phase/"):
        return
    name, path = repo.name, str(repo)
    match = PHASE_BRANCH.match(branch)
    num = match.group(1) if match else None
    spec = cfg.spec_repo if cfg is not None else None
    slice_dir = find_slice_dir(spec, num) if spec and num else None
    head = f"`{name}` ({path}) is on `{branch}`"

    if slice_dir is None:
        whose = f" for slice {num}" if num else ""
        where = f" under {spec / 'slices'}" if spec and num else ""
        raise Refusal(
            1,
            f"{head}, a run loop's phase branch{whose} — not a branch to "
            f"push or track. Preflight found no slice folder{where} to tell "
            f"whether that run is live.",
            f"If it is, wait for its phase to merge (the run checks the base "
            f"branch back out itself); if it is not, once any work on the "
            f"branch is committed, check `{name}`'s base branch back out.")

    lock = slice_dir / "run.lock"
    holder = run_lock_holder(lock)
    if holder is None:
        raise Refusal(
            1,
            f"{head}, a phase branch left by slice {num}'s run "
            f"({slice_dir}), which is not running — nothing holds its "
            f"run.lock. A bail leaves the branch checked out; the slice's "
            f"log.txt says why.",
            f"Once any work on the branch is committed, check `{name}`'s base "
            f"branch back out. Never push a phase branch or give it an "
            f"upstream: it is the run's own.")

    live = (f"{head}, the phase branch of slice {num}'s run ({slice_dir}), "
            f"and that run is live")
    raise Refusal(
        1,
        f"{live} — {lock} is held by:\n{_indented(holder)}\n"
        f"The run checked this branch out for its phase and checks the base "
        f"branch back out itself once the phase merges.",
        f"Wait for that. Do not set an upstream, push, or check anything out "
        f"in `{name}` meanwhile — each would change a live run's branch "
        f"under it.",
        summary=f"{live} ({lock} is held).")


def check_clean_tree(root: Path,
                     cfg: project_config.ProjectConfig | None = None) -> None:
    # A dirty tree on a phase branch is most likely a live run's writer at
    # work — "commit or stash" is the one advice that must not reach it.
    try:
        refuse_phase_branch(root, current_branch(root), cfg)
    except Refusal as refusal:
        fail(refusal.code, "clean_tree", refusal.fact, refusal.fix,
             refusal.output)
    result = _git(["-C", str(root), "status", "--porcelain"])
    if result.stdout.strip():
        fail(1, "clean_tree",
             f"The working tree of {root} has uncommitted changes, and a "
             f"dirty tree is never the run's to clean up.",
             "Commit or stash them before the slice runs.",
             result.stdout.rstrip("\n"))


def sync_roots(root: Path,
               cfg: project_config.ProjectConfig | None) -> list[Path]:
    """Every checkout the sync covers: the target repo, then the environment's
    other repos, then the spec repo, then the workflow's scratch clones.

    In a KubeCoder pod the environment's repos are all checked out beside the
    target (`/work/<Repo>`), which is the layout `.aiworkflowrc` already encodes
    (`spec_repo = "../Specs"`) — so the siblings *are* the environment. A `.git`
    that is a file, not a directory, is a worktree and still a checkout. The
    scratch clones are the ones a `github:` Target had the workflow clone or
    adopt (`github_target.scratch_clones`); they get the siblings' treatment.
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
            seen.add(cfg.spec_repo.resolve())
            roots.append(cfg.spec_repo)
    for d in github_target.scratch_clones():
        if d.resolve() not in seen:
            seen.add(d.resolve())
            roots.append(d)
    return roots


def find_slice(cfg: project_config.ProjectConfig, given: str) -> Path:
    """`--slice`'s folder: a directory path as given, else the folder of
    that name in the spec repo, else slice `given` by number — zero-padded
    to the folders' three digits when the number as given finds none."""
    if Path(given).is_dir():
        return Path(given)
    for parent in ("slices", "slices/backlog", "slices/completed"):
        named = cfg.spec_repo / parent / given
        if "/" not in given and named.is_dir():
            return named
    nums = [given]
    if given.isdigit() and given.zfill(3) != given:
        nums.append(given.zfill(3))
    for num in nums:
        found = find_slice_dir(cfg.spec_repo, num)
        if found is not None:
            return found
    fail(1, "slice",
         f"`--slice {given}` names no slice folder: `{given}` is not a "
         f"directory, and the spec repo {cfg.spec_repo} has no slice "
         f"{' or '.join(nums)} under slices/, slices/backlog/ or "
         f"slices/completed/.",
         "Give the slice's number, its folder's name or its folder's path.")


def plan_targets(root: Path, slice_dir: Path) -> set[Path]:
    """The repos the slice's plan.md targets, resolved: a sibling path
    against the target repo, a `github:` Target as its scratch clone, a
    component as the target repo itself (a component that lives in a sibling
    is not looked up). Done phases count. The plan's structure errors, and a
    malformed `github:` Target, are the plan loop's to name, not preflight's;
    no plan.md yet is no Targets."""
    plan = slice_dir / "plan.md"
    if not plan.is_file():
        return set()
    phases, _errors = run_loop.parse_plan(plan.read_text())
    repos = set()
    for phase in phases:
        target = phase.target
        if not target:
            continue
        if target.startswith(("../", "/")):
            repos.add((root / target).resolve())
        elif github_target.is_github(target):
            try:
                repos.add(github_target.clone_path(target).resolve())
            except ValueError:
                continue
        else:
            repos.add(root.resolve())
    return repos


def strict_repos(root: Path, cfg: project_config.ProjectConfig | None,
                 slice_arg: str | None) -> set[Path]:
    """The repos planning blocks on, by resolved path: the target repo, the
    spec repo, and — given `--slice` — every repo its plan targets."""
    strict = {root.resolve()}
    if cfg is not None and cfg.spec_repo is not None:
        strict.add(cfg.spec_repo.resolve())
    if slice_arg is not None:
        strict |= plan_targets(root, find_slice(cfg, slice_arg))
    return strict


def check_targets_cloned(root: Path, cfg: project_config.ProjectConfig | None,
                         slice_arg: str | None) -> None:
    """Fail (exit 2) when a pending phase of the `--slice` plan targets a
    repo `.kubecoder/config.yaml` declares and the pod has not cloned
    (`run_loop.not_cloned_message`). Such a repo was added while the
    environment ran and is cloned at the next pod start; until then the run
    loop would take the Target for a wrong path, nudge a session to fix a
    plan that is fine, and ask the operator. The environment is broken, not
    the project — hence 2.

    Only repo paths are looked at, resolved as the run loop resolves them,
    and only pending phases, which are all the run loop resolves. A
    `github:` Target's scratch clone is the loop's to make, and an unknown
    component the plan loop's to name. A missing Target config.yaml does
    not declare, or kc not answering, passes: the loop names it as before.
    No `--slice`, or no plan.md yet, is nothing to check."""
    if slice_arg is None:
        return
    plan = find_slice(cfg, slice_arg) / "plan.md"
    if not plan.is_file():
        return
    phases, _errors = run_loop.parse_plan(plan.read_text())
    problems = []
    for phase in phases:
        target = phase.target
        if phase.done or not target or not target.startswith(("../", "/")):
            continue
        path = ((root / target).resolve() if not target.startswith("/")
                else Path(target))
        message = run_loop.not_cloned_message(target, path)
        if message:
            problems.append(f"- phase P{phase.id}: {message}")
    if problems:
        fail(2, "targets_cloned",
             f"The slice's plan ({plan}) targets a repo this environment "
             f"declares but has not cloned — the plan is fine, and the "
             f"environment is a checkout short:\n" + "\n".join(problems),
             "Restart the environment (`kc env restart`), or clone each repo "
             "where its line says and run `kc project setup` in it.")


def slice_needs(slice_md: Path) -> list[str]:
    """The slices `slice.md` must follow: its front matter's `needs:` line,
    the numbers as written (`needs: 028, 031`; brackets allowed). No front
    matter, no `needs:` line or an empty one is none. A front matter is the
    block between a first line `---` and the next; a `needs:` line anywhere
    else is the slice's prose, not its order."""
    lines = slice_md.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "needs":
            value = value.strip().strip("[]")
            return [token for token in re.split(r"[\s,]+", value) if token]
    return []


def check_ready_to_plan(cfg: project_config.ProjectConfig | None,
                        slice_arg: str | None) -> None:
    """Fail (exit 1) when the `--slice` slice must follow a slice that has
    not completed: each number its `slice.md` names under `needs:` must be
    a folder under `slices/completed/`. A slice planned before the one it
    builds on is planned against code that slice is about to change. The
    order is the project's — triage writes it, and the operator moves it —
    so the fix names both ways: plan once the slice has completed, or take
    it off the line. No `--slice`, or no `slice.md`, is nothing to check."""
    if slice_arg is None:
        return
    folder = find_slice(cfg, slice_arg)
    slice_md = folder / "slice.md"
    if not slice_md.is_file():
        return
    needs = slice_needs(slice_md)
    bad = [token for token in needs if not token.isdigit()]
    if bad:
        fail(1, "ready_to_plan",
             f"The `needs:` line in {slice_md} names "
             f"{', '.join(f'`{token}`' for token in bad)}, which is not a "
             f"slice number.",
             "Write the slices it must follow by number, `needs: 028, 031`, "
             "or remove the line if it must follow none.")
    waiting = []
    for token in needs:
        num = token.zfill(3)
        found = find_slice_dir(cfg.spec_repo, num)
        if found is not None and found.parent.name == "completed":
            continue
        where = (f"at {found.relative_to(cfg.spec_repo)}, not completed"
                 if found is not None else
                 "under none of slices/, slices/backlog/ or "
                 "slices/completed/")
        waiting.append(f"- {num}, {where}")
    if waiting:
        fail(1, "ready_to_plan",
             f"Slice {folder.name} must follow slices that have not "
             f"completed (the `needs:` line in its slice.md):\n"
             + "\n".join(waiting),
             "Plan it once each of them has completed. If the order no "
             "longer holds, take that slice off the `needs:` line in "
             f"{slice_md}.")


# A dirty tree may be another process's pull caught mid-checkout — a sibling
# is half-applied for a moment, and "commit or stash" would capture that. So a
# repo found behind and dirty is looked at once more after this wait (seconds).
DIRTY_RECHECK_WAIT = 2

# The run loop's lock, untracked wherever it sits: a live run holds it, and a
# clean exit empties its note and leaves the file until close_slice.py deletes
# it at close-out. No pull writes it, so the dirty test passes it over — or a
# spec repo with a run on, or a lock a close-out predating the deletion left,
# would never be pulled again.
RUN_LOCK = "run.lock"

# What GitHub answers a fetch from a repo that was deleted or moved:
# `remote: Repository not found.`, then `fatal: repository '<url>' not found`.
ORIGIN_GONE_MARKER = "repository not found"


def _ahead_behind(path: str) -> tuple[int, int] | None:
    """(ahead, behind) against the upstream; None when nothing is countable."""
    counts = _git(["-C", path, "rev-list", "--left-right", "--count",
                   "HEAD...@{u}"])
    parts = counts.stdout.split()
    if counts.returncode != 0 or len(parts) != 2 or not all(
            p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def _uncommitted(path: str) -> str:
    """`git status --porcelain`, less its untracked run.lock lines (RUN_LOCK).
    A path git quotes keeps its closing quote, stripped before the name."""
    status = _git(["-C", path, "status", "--porcelain"]).stdout
    return "".join(
        line for line in status.splitlines(keepends=True)
        if not (line.startswith("?? ")
                and line[3:].rstrip('\n"').rsplit("/", 1)[-1] == RUN_LOCK))


def _index_lock(repo: Path) -> Path | None:
    """Where git's index lock for `repo` would be (relative answers are to
    the repo); None when git does not say."""
    where = _git(["-C", str(repo), "rev-parse", "--git-path", "index.lock"])
    if where.returncode != 0 or not where.stdout.strip():
        return None
    lock = Path(where.stdout.strip())
    return lock if lock.is_absolute() else repo / lock


def _origin_gone(repo: Path) -> str:
    """The note for a repo whose GitHub origin no longer exists."""
    name, path = repo.name, str(repo)
    line = (f"`{name}` ({path}) was not synced — its origin reports "
            f"\"Repository not found\", so the repo was deleted or moved on "
            f"GitHub; planning goes on without it.")
    if _git(["-C", path, "config", "--get",
             github_target.MARK_KEY]).stdout.strip():
        line += (f" It is a workflow scratch clone: `git -C {path} config "
                 f"--unset {github_target.MARK_KEY}` unmarks it.")
    return line


def _passed_over(repo: Path, refusal: Refusal) -> str:
    """The note for a refusal in a repo planning does not block on."""
    return (f"{refusal.summary} Not synced, as the slice's plan "
            f"targets no part of `{repo.name}`: planning goes on, and "
            f"`/dev:run-slice`'s preflight refuses it until it is resolved.")


def _sync_repo(repo: Path, cfg: project_config.ProjectConfig | None,
               planning: bool) -> str | None:
    """One repo's sync (check_synced). Raises a Refusal where the repo is not
    synced; returns the note a repo skipped under plan gets, if any."""
    name, path = repo.name, str(repo)
    branch_name = current_branch(repo)
    if branch_name is None:
        return None  # detached HEAD — nothing to pull onto
    refuse_phase_branch(repo, branch_name, cfg)
    tracking = _git(["-C", path, "rev-parse", "--abbrev-ref",
                     "--symbolic-full-name", "@{u}"])
    if tracking.returncode != 0:
        raise Refusal(
            1,
            f"`{name}` ({path}) is on `{branch_name}`, a branch with no "
            f"upstream — preflight syncs every repo of the environment "
            f"with its origin before a slice starts, and a repo it skipped "
            f"would report green having synced nothing.",
            f"Set the tracking ref (`git -C {path} branch "
            f"--set-upstream-to=origin/{branch_name}`) or push the branch "
            f"with `-u`.")
    upstream = tracking.stdout.strip()
    remote = upstream.split("/", 1)[0]

    fetched, attempts = _fetch(path, remote)
    if fetched.returncode != 0:
        if planning and not (repo / ".git").exists():
            return None  # the checkout (or the whole dir) vanished mid-sync
        if planning and ORIGIN_GONE_MARKER in (
                (fetched.stderr or "") + (fetched.stdout or "")).lower():
            return _origin_gone(repo)
        if _lost_race(fetched):
            why = (f" Another session in this pod was updating the same "
                   f"clone's refs at the same moment — git's ref-update "
                   f"race, not a network or credentials problem; preflight "
                   f"tried {attempts} times.")
            fix = "Run preflight again: a rerun normally clears the race."
        else:
            why = ""
            fix = ("Make the remote reachable from this pod (network, "
                   "credentials).")
        output = fetched.stderr or fetched.stdout
        raise Refusal(
            2,
            f"`git fetch {remote}` failed in `{name}` ({path}) "
            f"(rc={fetched.returncode}). Preflight syncs every repo of the "
            f"environment with its origin before a slice starts.{why}",
            fix, output.rstrip("\n"))

    counts = _ahead_behind(path)
    if counts is None or counts[1] == 0:
        return None  # nothing countable, up to date, or ahead only
    ahead, behind = counts

    status = _uncommitted(path)
    if status.strip():
        # Another process's pull may be mid-checkout: look once more after a
        # wait, and a held index lock at either look is that process.
        lock = _index_lock(repo)
        locked = lock is not None and lock.exists()
        _sleep(DIRTY_RECHECK_WAIT)
        counts = _ahead_behind(path)
        if counts is None or counts[1] == 0:
            return None  # whatever was pulling brought it up to date
        ahead, behind = counts
        status = _uncommitted(path)
        locked = locked or (lock is not None and lock.exists())
        if status.strip() and locked:
            raise Refusal(
                1,
                f"`{name}` ({path}) is {behind} behind {upstream} and has "
                f"uncommitted changes while another git process works in it "
                f"— its index lock {lock} was held as preflight looked.",
                "Committing or stashing now would capture that process's "
                "half-applied work, so don't: wait for it to finish.",
                status.rstrip("\n"))
        if status.strip():
            raise Refusal(
                1,
                f"`{name}` ({path}) is {behind} behind {upstream} and has "
                f"uncommitted changes — preflight will not pull over them.",
                "Commit or stash them, or pull by hand.",
                status.rstrip("\n"))

    if ahead == 0:
        merged = _git(["-C", path, "merge", "--ff-only", "--quiet", "@{u}"])
        if merged.returncode != 0:
            raise Refusal(
                1,
                f"`{name}` ({path}) is {behind} behind {upstream} but "
                f"`git merge --ff-only` refused it (rc={merged.returncode}).",
                "Bring it up to date by hand.",
                (merged.stderr or merged.stdout).rstrip("\n"))
        return None

    rebased = _git(["-C", path, "rebase", "--quiet", "@{u}"])
    if rebased.returncode != 0:
        _git(["-C", path, "rebase", "--abort"])
        tail = (rebased.stdout + rebased.stderr).strip().splitlines()[-20:]
        raise Refusal(
            1,
            f"`{name}` ({path}) has {ahead} local commits that do not "
            f"rebase onto {upstream} ({behind} behind). The rebase was "
            f"aborted, so the repo stands where it did.",
            "Resolve it by hand, by a rebase or a merge.",
            "\n".join(tail))
    return None


def check_synced(root: Path, cfg: project_config.ProjectConfig | None,
                 strict: set[Path] | None = None) -> None:
    """Bring every repo of the environment up to date with its origin.

    The *checked-out* branch is what gets synced, in the target repo and in
    every sibling: the run loop records whatever branch it finds the first time
    it touches a repo (`_base_branch`), so the checked-out branch is the base
    the slice will build on — no fixed `main` is assumed. A repo with a detached
    HEAD has nothing to pull onto and is skipped; a repo on a run loop's phase
    branch is refused first (`refuse_phase_branch`), upstream or not; any other
    branch with no upstream is refused, naming the repo and the branch —
    skipped, it would report green having synced nothing.

    Behind and clean fast-forwards; behind with local commits rebases, and a
    rebase that conflicts is aborted (leaving the repo as it was) and handed to
    the operator. Ahead-only is left alone — unpushed commits are the
    operator's, and the run loop pushes at its test phase. A repo with
    uncommitted changes is refused rather than pulled over — after a second
    look DIRTY_RECHECK_WAIT later, since another process's pull is dirty for a
    moment; one whose index lock was held is told to wait, never to commit or
    stash. An untracked run.lock is not uncommitted work (RUN_LOCK).

    `strict` is the plan profile's set of repos that may block (strict_repos,
    resolved paths); None, the run profile, makes every repo strict. Under
    plan any other repo's refusal is one note and the sync goes on, and
    every repo, strict or not, is skipped when it vanished mid-sync
    (silently) or its GitHub origin is gone (with a note).
    """
    for repo in sync_roots(root, cfg):
        try:
            warning = _sync_repo(repo, cfg, planning=strict is not None)
        except Refusal as refusal:
            if strict is None or repo.resolve() in strict:
                fail(refusal.code, "synced", refusal.fact, refusal.fix,
                     refusal.output)
            warning = _passed_over(repo, refusal)
        if warning:
            note("synced", warning)


# kc's exit code for "nothing ran" (KC-81; run_loop.KC_NOTHING_RAN): a project
# whose manifest has no build statement has no baseline to break — it passes.
KC_NOTHING_RAN = 3

# How much of each command's output a red baseline's message carries.
SETUP_TAIL = 20
BUILD_TAIL = 40


def _captured(stream: str | bytes | None) -> str:
    """A captured stream as text: a TimeoutExpired's partial output may be
    bytes, or None when nothing was read before the kill."""
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream or ""


def check_baseline_build(root: Path) -> None:
    """`kc project setup`, then the baseline `kc project build`. Setup runs
    first so a dependency added since the last setup does not read as a red
    baseline — PilotApp's type-check met TS2307 "Cannot find module 'pg'"
    after a template sync added `pg` to its lockfile, and setup made it
    green. As in the run loop's `_setup_targets`, setup does not decide, the
    build does: a red or timed-out setup is one `warning:` line under a green
    build, and a red build's message carries setup's outcome and last lines,
    a failed setup named as the first thing to fix. SETUP_TIMEOUT bounds a
    hung setup; exit 3 (nothing ran) passes for both verbs."""
    try:
        setup = subprocess.run(
            ["kc", "project", "setup"], cwd=str(root), capture_output=True,
            text=True, timeout=run_loop.SETUP_TIMEOUT)
    except subprocess.TimeoutExpired as expired:
        setup_output = _captured(expired.stdout) + _captured(expired.stderr)
        outcome = "timed_out"
        setup_said = setup_failed = f"timed out after {run_loop.SETUP_TIMEOUT}s"
    else:
        setup_output = setup.stdout + setup.stderr
        outcome = run_loop.kc_outcome(setup.returncode)
        setup_said = (f"{run_loop.GATE_OUTCOME_LABELS[outcome]} "
                      f"(exit {setup.returncode})")
        setup_failed = (f"failed (exit {setup.returncode})"
                        if outcome == "red" else None)
    setup_lines = setup_output.strip().splitlines()

    result = subprocess.run(
        ["kc", "project", "build"], cwd=str(root), capture_output=True, text=True)
    if result.returncode in (0, KC_NOTHING_RAN):
        if setup_failed:
            built = ("was green" if result.returncode == 0
                     else f"had nothing to build (exit {KC_NOTHING_RAN})")
            last = next((line.strip() for line in reversed(setup_lines)
                         if line.strip()), "")
            note("baseline_build",
                 f"`kc project setup` {setup_failed}, but the baseline "
                 f"`kc project build` {built}, so the run goes on — the phase "
                 f"gates meet what setup could not install"
                 + (f" (setup's last line: {last})" if last else ""))
        return

    fix = "Fix the baseline, or narrow the manifest's build list."
    if setup_failed:
        about_setup = f"`kc project setup`, run before it, {setup_failed}."
        fix = ("Fix setup's own failure first — the build may be red only "
               "for what setup could not install. Then " + fix[0].lower()
               + fix[1:])
    elif outcome == "green":
        about_setup = ("`kc project setup` ran green before it, so the red is "
                       "not install state.")
    else:
        about_setup = ("The repo defines no `kc project setup`, so none ran "
                       "before it.")
    tail = (result.stdout + result.stderr).strip().splitlines()[-BUILD_TAIL:]
    fail(1, "baseline_build",
         "Baseline `kc project build` failed — the suite must be green before "
         "a slice runs (a baseline-broken build screams on task 1 otherwise). "
         + about_setup,
         fix,
         "\n\n".join([
             "\n".join([f"`kc project setup` → {setup_said}:",
                        *setup_lines[-SETUP_TAIL:]]),
             "\n".join([f"`kc project build` → RED (exit {result.returncode}):",
                        *tail])]))


# Triage deliberately has no `kc_status`: it dispatches nothing and touches no
# kc surface — it is intake, doable without the repo. Gating it on live
# controller reachability would fail work that needs none of it.
PROFILES = {
    "triage": ["kc", "config", "spec_repo", "spec_tree_guard"],
    "plan": ["kc", "kc_status", "manifest", "config", "spec_repo",
             "spec_tree_guard", "targets_cloned", "synced", "ready_to_plan"],
    "run": ["kc", "kc_status", "manifest", "config", "spec_repo",
            "spec_tree_guard", "design_philosophy", "phase_pointers",
            "devlock", "targets_cloned", "clean_tree", "synced",
            "baseline_build"],
}


def main() -> None:
    global NOTES
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--for", dest="profile", required=True,
                        choices=sorted(PROFILES), help="which command's profile to run")
    parser.add_argument("--slice", metavar="N|NAME|PATH",
                        help="plan and run: the slice (its number, its "
                             "folder's name or its folder's path) "
                             "whose plan's Targets must not name a repo the "
                             "environment declares and has not cloned; under "
                             "plan, its Targets may also block the sync")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON object on stdout, pass or fail: "
                             "the notes, and a failure's check, fact, fix "
                             "and output")
    args = parser.parse_args()
    if args.slice is not None and args.profile not in ("plan", "run"):
        parser.error("--slice applies to --for plan and --for run only")
    if not args.json:
        run_profile(args)
        return
    NOTES = []
    try:
        try:
            cfg = run_profile(args)
        except Failure as failure:
            report = {"result": "fail", "profile": args.profile,
                      **failure.data(), "notes": NOTES}
            print(json.dumps(report, indent=2))
            raise
        report = {"result": "pass", "profile": args.profile, "notes": NOTES}
        if args.profile == "run" and cfg is not None:
            # What the run's pushes are, for the stage that asks before a
            # push that deploys while Pilot's auto pilot is off.
            report["push"] = {"enabled": cfg.push, "deploys": cfg.push_deploys,
                              "deploys_stated": cfg.push_deploys_stated}
        print(json.dumps(report, indent=2))
    finally:
        NOTES = None


def run_profile(args) -> project_config.ProjectConfig | None:
    """The profile's checks in order; a Failure at the first that fails.
    Returns the project's config, where the profile loads it."""
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
    if "spec_tree_guard" in checks:
        remove_spec_tree_guard(cfg)
    if "design_philosophy" in checks:
        check_pointer(cfg, "design_philosophy")
    if "phase_pointers" in checks:
        check_phase_pointers(cfg)
    if "devlock" in checks:
        check_devlock(cfg)
    if "targets_cloned" in checks:
        check_targets_cloned(root, cfg, args.slice)
    if "clean_tree" in checks:
        check_clean_tree(root, cfg)
    if "synced" in checks:
        strict = (strict_repos(root, cfg, args.slice)
                  if args.profile == "plan" else None)
        check_synced(root, cfg, strict)
    if "ready_to_plan" in checks:
        check_ready_to_plan(cfg, args.slice)
    if "baseline_build" in checks:
        check_baseline_build(root)
    # Silent on success, but for the notes.
    return cfg


if __name__ == "__main__":
    main()
