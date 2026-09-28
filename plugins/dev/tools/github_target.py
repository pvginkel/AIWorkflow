#!/usr/bin/env python3
"""GitHub repo targets — `Target: github:<owner>/<repo>`.

A plan phase may land in a GitHub repo the environment does not check out.
The workflow clones it into the scratch root (`/work/scratch/<repo>`,
KubeCoder's convention for repos an environment does not declare) and from
then on it is a repo path like any sibling: branched, merged and pushed where
it sits, gated from its own root. `ensure_clone` is the one entry point — the
run loop's target resolution and so its dry run call it — and every later
step sees a plain path; the plan loop needs only the pure `clone_path`, and
preflight's sync walks `scratch_clones()`.

What `ensure_clone` does, per target, at most once per process:

| The clone path holds                         | first touch       | owned  |
|----------------------------------------------|-------------------|--------|
| nothing                                      | `git clone`       | refuse |
| not a checkout, or another repo's origin     | refuse            | refuse |
| a clean clone, behind origin                 | fetch + ff        | as is  |
| dirty, detached, a `phase/` branch, no       | refuse            | as is  |
| upstream, or commits origin lacks            |                   |        |

*Owned* is a clone the calling run already records as one of its repos: its
merged, not yet pushed phases sit on the base branch, and a sync or an
"ahead" refusal would fight the run itself.

A target naming a repo the environment already checks out directly under the
work root is refused first — the sibling `../<Dir>` form addresses it, and a
second clone would split the slice's commits across two trees. There is no
`kc` verb listing the environment's repos (and the manifest is never parsed),
so the check reads each checkout's `origin` URL.

Every clone the workflow cloned or adopted carries `aiworkflow.scratchClone`
in its git config; that mark, not the directory, is what preflight syncs.

Every refusal is a ValueError whose message is operator-facing: the path, what
is wrong, and the fix. Stdlib only.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# KubeCoder's scratch root: repos an environment does not declare are cloned
# here. Its parent is the work root the declared repos sit in.
SCRATCH_ROOT = Path("/work/scratch")
PREFIX = "github:"
CLONE_URL = "https://github.com/{owner}/{repo}"
MARK_KEY = "aiworkflow.scratchClone"
# Network steps are bounded: a hung clone or fetch becomes a refusal.
GIT_TIMEOUT = 600

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_GITHUB_URL_RES = (
    re.compile(r"^https?://(?:[^@/]+@)?github\.com/([^/]+)/([^/]+)$", re.I),
    re.compile(r"^(?:[^@/]+@)?github\.com:([^/]+)/([^/]+)$", re.I),
    re.compile(r"^ssh://(?:[^@/]+@)?github\.com(?::\d+)?/([^/]+)/([^/]+)$",
               re.I),
)
FORM = "`github:<owner>/<repo>` (e.g. `github:pvginkel/RegistryDeploy`)"

# target → the clone's path, for every target this process has ensured.
_ensured: dict[str, Path] = {}


def reset_cache() -> None:
    """Forget what this process ensured (tests)."""
    _ensured.clear()


def is_github(target: str | None) -> bool:
    return bool(target) and target.startswith(PREFIX)


def parse(target: str) -> tuple[str, str]:
    """(owner, repo) of a `github:` target; a trailing `.git` is dropped.
    Raises ValueError naming the form on anything else."""
    body = target[len(PREFIX):].strip() if is_github(target) else ""
    parts = body.split("/")
    if len(parts) == 2 and parts[1].endswith(".git"):
        parts[1] = parts[1][:-len(".git")]
    if len(parts) != 2 or not all(_NAME_RE.match(p) for p in parts) \
            or parts[1] in (".", ".."):
        raise ValueError(f"Target `{target}` is not a GitHub repo target — "
                         f"write it {FORM}")
    return parts[0], parts[1]


def clone_path(target: str) -> Path:
    """Where the target's clone lives — pure, nothing is touched."""
    return SCRATCH_ROOT / parse(target)[1]


def _url_key(url: str) -> str:
    """A remote URL as the match compares it: any GitHub form (https, scp,
    ssh; `.git` or not) as `github.com/<owner>/<repo>` in lower case, anything
    else as written minus a trailing `/` and `.git`."""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-len(".git")]
    for pattern in _GITHUB_URL_RES:
        match = pattern.match(url)
        if match:
            return f"github.com/{match.group(1)}/{match.group(2)}".lower()
    return url


def origin_matches(url: str, owner: str, repo: str) -> bool:
    """Is `url` this GitHub repo — in any of its URL forms, or as the clone
    URL template writes it?"""
    want = {_url_key(f"https://github.com/{owner}/{repo}"),
            _url_key(CLONE_URL.format(owner=owner, repo=repo))}
    return bool(url.strip()) and _url_key(url) in want


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """git, never prompting: a credentials prompt in a headless session would
    hang the run, so a repo that needs one fails instead. A timeout is a
    failure of its own (rc 124, git's stderr replaced by the note)."""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            ["git", *args], 124, "", f"timed out after {timeout}s")


def _origin(path: Path) -> str:
    result = _git("-C", str(path), "remote", "get-url", "origin")
    return result.stdout.strip() if result.returncode == 0 else ""


def declared_checkout(owner: str, repo: str) -> Path | None:
    """The environment's own checkout of this repo, if it has one: a git
    checkout directly under the work root (the scratch root excluded) whose
    `origin` is it. The invoking repo is one of them."""
    work = SCRATCH_ROOT.parent
    scratch = SCRATCH_ROOT.resolve()
    try:
        beside = sorted(work.iterdir())
    except OSError:
        return None
    for d in beside:
        if not d.is_dir() or d.resolve() == scratch \
                or not (d / ".git").exists():
            continue
        if origin_matches(_origin(d), owner, repo):
            return d
    return None


def ensure_clone(target: str, *, owned: bool = False) -> Path:
    """The target's clone, cloned or synced as the module docstring's table
    says. `owned` is the caller's run already recording the clone as one of
    its repos: it is checked, never synced."""
    if target in _ensured:
        return _ensured[target]
    owner, repo = parse(target)
    declared = declared_checkout(owner, repo)
    if declared is not None:
        raise ValueError(
            f"Target `{target}` names {owner}/{repo}, which this environment "
            f"already checks out at {declared} — use the sibling "
            f"`../{declared.name}` form instead (or a component name, when "
            "that is the repo the slice runs from)")
    path = clone_path(target)
    if not path.exists():
        if owned:
            raise ValueError(
                f"{path} is gone — the scratch clone this run made for "
                f"`Target: {target}` and merged its phases into. Whatever "
                "of those phases was not pushed went with it. Restore the "
                "clone (or re-clone it and re-run the lost phases) before "
                "resuming.")
        _clone(target, owner, repo, path)
    else:
        if not path.is_dir() or not (path / ".git").exists():
            raise ValueError(
                f"{path} exists but is not a git checkout — `Target: "
                f"{target}` clones there. Move it away or delete it, then "
                "retry.")
        origin = _origin(path)
        if not origin_matches(origin, owner, repo):
            raise ValueError(
                f"{path} is a checkout of "
                f"{origin or 'a repo with no origin remote'}, not "
                f"{owner}/{repo} — `Target: {target}` clones to that path. "
                "Move it away or delete it, then retry.")
        if not owned:
            _sync(target, path)
    _git("-C", str(path), "config", MARK_KEY, f"{owner}/{repo}")
    _ensured[target] = path
    return path


def _clone(target: str, owner: str, repo: str, path: Path) -> None:
    url = CLONE_URL.format(owner=owner, repo=repo)
    try:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"cannot create the scratch root {SCRATCH_ROOT} for "
                         f"`Target: {target}`: {e}") from None
    result = _git("clone", "--quiet", url, str(path), timeout=GIT_TIMEOUT)
    if result.returncode != 0:
        raise ValueError(
            f"`git clone {url} {path}` failed for `Target: {target}` "
            f"(rc={result.returncode}). Check that the repo exists and is "
            "reachable from this pod (network, credentials), then retry.\n"
            + (result.stderr or result.stdout).rstrip("\n"))


def _sync(target: str, path: Path) -> None:
    """Bring an existing clone up to its origin — fast-forward only. Anything
    the driver would have to decide about (local work, a run's branch,
    commits origin lacks) is refused, never touched."""
    p = str(path)
    what = f"The scratch clone {path} (`Target: {target}`)"
    head = _git("-C", p, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head.returncode != 0:
        raise ValueError(f"{what} is on a detached HEAD — check out its "
                         "default branch, then retry.")
    branch = head.stdout.strip()
    if branch.startswith("phase/"):
        raise ValueError(
            f"{what} is on `{branch}`, a run loop's phase branch — a live "
            "run's, or one a bail left. If its run is live, wait for the "
            "phase to merge; otherwise, once any work on the branch is "
            f"committed, check the base branch back out (`git -C {p} "
            "checkout <base>`), then retry.")
    status = _git("-C", p, "status", "--porcelain")
    if status.stdout.strip():
        raise ValueError(
            f"{what} has uncommitted changes — the driver will not sync over "
            "them. Commit and push them, or delete the clone, then retry.\n"
            + status.stdout.rstrip("\n"))
    tracking = _git("-C", p, "rev-parse", "--abbrev-ref",
                    "--symbolic-full-name", "@{u}")
    if tracking.returncode != 0:
        raise ValueError(
            f"{what} is on `{branch}`, a branch with no upstream — check out "
            "a branch that tracks origin, then retry.")
    upstream = tracking.stdout.strip()
    remote = upstream.split("/", 1)[0]
    fetched = _git("-C", p, "fetch", "--quiet", remote, timeout=GIT_TIMEOUT)
    if fetched.returncode != 0:
        raise ValueError(
            f"`git fetch {remote}` failed in {what} "
            f"(rc={fetched.returncode}). Check that the remote is reachable "
            "from this pod (network, credentials), then retry.\n"
            + (fetched.stderr or fetched.stdout).rstrip("\n"))
    counts = _git("-C", p, "rev-list", "--left-right", "--count",
                  "HEAD...@{u}").stdout.split()
    if len(counts) != 2 or not all(c.isdigit() for c in counts):
        raise ValueError(f"{what}: cannot count `{branch}` against "
                         f"{upstream} — check the clone by hand, then retry.")
    ahead, behind = int(counts[0]), int(counts[1])
    if ahead:
        raise ValueError(
            f"{what} has {ahead} commit(s) on `{branch}` that {upstream} does "
            "not have — the driver adopts a clone only when origin holds all "
            "of it. Push them, or delete the clone, then retry.")
    if behind:
        merged = _git("-C", p, "merge", "--ff-only", "--quiet", "@{u}")
        if merged.returncode != 0:
            raise ValueError(
                f"{what}: fast-forwarding `{branch}` to {upstream} failed — "
                "sync it by hand, then retry.\n"
                + (merged.stderr or merged.stdout).rstrip("\n"))


def scratch_clones() -> list[Path]:
    """The clones under the scratch root the workflow cloned or adopted (the
    ones carrying the mark), sorted. A clone someone made by hand is not the
    workflow's to sync."""
    try:
        beside = sorted(SCRATCH_ROOT.iterdir())
    except OSError:
        return []
    return [d for d in beside
            if d.is_dir() and (d / ".git").exists()
            and _git("-C", str(d), "config", "--get",
                     MARK_KEY).stdout.strip()]
