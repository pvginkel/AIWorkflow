#!/usr/bin/env python3
"""Commit your own change to a spec-repo file and leave another writer's
uncommitted edit in that same file where it is, uncommitted.

The spec repo is one working tree shared by every session in every
environment: the loops, the agents they dispatch, the operator's sessions and
the operator by hand. Staging by name (`git add -- <paths>`) keeps other files
out of a commit, but not another writer's uncommitted edit inside a file you
commit — the lane boxes the operator ticks in `slices/DAG.md`, a running
slice's `plan.md` between two of its driver's commits — and `git add -p`,
which could split them, is interactive. This tool makes that split.

  1. Before your first edit of such a file, snapshot it. Each line starts with
     the token to commit it by, and says whether the file holds an edit that
     is not yours:

         spec_commit.py snap slices/DAG.md
         slices/DAG.md@1a2b3c4d5e6f  — holds an uncommitted edit that is not …

  2. Edit the file in place, with your usual tools.
  3. Commit by the token, and any file that is wholly yours by its plain path:

         spec_commit.py commit -m "<subject>" slices/DAG.md@1a2b3c4d5e6f new.md

For each token the commit takes your change — the snapshot to the file as it
is now — and applies it onto HEAD's version of the file (a 3-way merge); a
plain path goes in whole, as `git add` takes it. The commit is built in a
temporary index, so what other sessions staged in the real one stays staged
and out of it; the working tree is never written, so the other writer's edit
stays there, uncommitted. The pre-commit hook (the spec-tree guard) runs as
`git commit` would run it, the spec tree's lease is held shared throughout,
and HEAD moves by compare-and-swap: a commit that lands meanwhile is merged
against, never reverted.

Limits: an edit someone makes between your snapshot and your commit counts as
yours, and one you made before `snap` counts as not yours — snapshot first. A
change of yours on the other writer's lines, or on the line next to them, is
refused, and refusal is all-or-nothing: nothing in the call is committed.

Usage:
    spec_commit.py snap <path>...
    spec_commit.py commit -m <message> [-m <message>...] <path>@<sha>|<path>...

Exit codes: 0 committed, or nothing to commit · 1 unexpected error ·
2 usage/precondition error, nothing written · 3 a change overlaps an edit
that is not yours, nothing committed · 4 the tree is held by a running phase,
or the pre-commit hook refused, nothing committed.
"""

import argparse
import difflib
import fcntl
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

LEASE_NAME = "dev-spec-tree.lock"
HOLDER_NAME = "dev-spec-tree.holder"
PHASE_BRANCH_ENV = "DEV_PHASE_BRANCH"
SNAPSHOT_RE = re.compile(r"^(.*)@([0-9a-f]{7,40})$")
FILE_MODES = ("100644", "100755")
# HEAD can move under a commit (another session commits); each attempt
# rebuilds against the new HEAD.
ATTEMPTS = 5
# The real index is synced after the commit; another git command may hold
# its lock for a moment.
INDEX_LOCK_TRIES = 5
INDEX_LOCK_PAUSE = 0.2


class Precondition(Exception):
    """A usage or precondition failure — exit 2, nothing written."""


class GitError(Exception):
    """A git command failed where it should not have — exit 1."""


class Held(Exception):
    """The spec tree's lease is held exclusively by a running phase — exit 4.
    Carries the holder's note."""


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def run_git(root: Path, *args: str, input: bytes | None = None,
            env: dict[str, str] | None = None,
            literal: bool = True) -> subprocess.CompletedProcess:
    """git in `root`, output captured as bytes. Pathspecs are literal: a spec
    file named `[x].md` is that file, not a glob. The hook run passes
    literal=False, because the option reaches a hook as an env var."""
    command = ["git", *(["--literal-pathspecs"] if literal else []), *args]
    return subprocess.run(command, cwd=root, input=input, env=env,
                          capture_output=True,
                          stdin=subprocess.DEVNULL if input is None else None)


def stderr_of(result: subprocess.CompletedProcess) -> str:
    return (os.fsdecode(result.stderr).strip()
            or os.fsdecode(result.stdout).strip()
            or f"exit {result.returncode}")


def git(root: Path, *args: str, input: bytes | None = None,
        env: dict[str, str] | None = None) -> bytes:
    result = run_git(root, *args, input=input, env=env)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr_of(result)}")
    return result.stdout


def git_text(root: Path, *args: str, input: bytes | None = None,
             env: dict[str, str] | None = None) -> str:
    return os.fsdecode(git(root, *args, input=input, env=env)).strip()


@dataclass(frozen=True)
class Entry:
    """One tree or index entry. `kind` is the tree's object type; an index
    entry is always a blob."""

    mode: str
    sha: str
    kind: str = "blob"

    @property
    def is_file(self) -> bool:
        return self.kind == "blob" and self.mode in FILE_MODES


def tree_entry(root: Path, commit: str, rel: str) -> Entry | None:
    """`rel`'s entry in `commit`, or None. The path is matched exactly — the
    listing also answers for a pathspec's prefix."""
    for record in git(root, "ls-tree", "-z", commit, "--", rel).split(b"\0"):
        meta, _, path = record.partition(b"\t")
        if record and os.fsdecode(path) == rel:
            mode, kind, sha = meta.decode().split()
            return Entry(mode, sha, kind)
    return None


# A conflicted path in the real index, which never equals a tree's entry.
UNMERGED = Entry("unmerged", "unmerged")


def index_entry(root: Path, rel: str) -> Entry | None:
    """`rel`'s entry in the real index: None when it has none, UNMERGED when
    it has conflict stages."""
    found = []
    for record in git(root, "ls-files", "-s", "-z", "--", rel).split(b"\0"):
        meta, _, path = record.partition(b"\t")
        if record and os.fsdecode(path) == rel:
            found.append(meta.decode().split())
    if not found:
        return None
    if len(found) == 1 and found[0][2] == "0":
        return Entry(found[0][0], found[0][1])
    return UNMERGED


def current_branch(root: Path) -> str | None:
    result = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return os.fsdecode(result.stdout).strip() if result.returncode == 0 else None


def head_or_none(root: Path) -> str | None:
    result = run_git(root, "rev-parse", "--verify", "--quiet", "HEAD")
    return os.fsdecode(result.stdout).strip() if result.returncode == 0 else None


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Target:
    """A path as the caller gave it, and where it lies in its work tree."""

    raw: str
    absolute: str
    path: Path
    root: Path
    rel: str


def locate(raw: str) -> Target:
    """Resolve `raw` against the cwd and find its work tree from its nearest
    existing directory, so a path that does not exist yet (or no longer
    does) still has a repo. Symlinked directories are resolved on both sides
    before the relative path is taken; the last component is kept as named,
    so a symlink is seen as one."""
    absolute = Path(os.path.abspath(raw))
    anchor = absolute
    if absolute.is_symlink() or not absolute.is_dir():
        anchor = absolute.parent
    while not anchor.is_dir():
        anchor = anchor.parent
    result = run_git(anchor, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise Precondition(f"{raw}: not in a git work tree ({stderr_of(result)})")
    root = Path(os.fsdecode(result.stdout).strip()).resolve()
    path = anchor.resolve() / absolute.relative_to(anchor)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        raise Precondition(f"{raw}: outside the work tree at {root}") from None
    return Target(raw, str(absolute), path, root, rel)


def one_root(targets: list[Target]) -> Path:
    roots = sorted({str(target.root) for target in targets})
    if len(roots) > 1:
        raise Precondition("the paths lie in more than one git work tree ("
                           + ", ".join(roots) + ") — one repo per call")
    return targets[0].root


def lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


# ---------------------------------------------------------------------------
# snap
# ---------------------------------------------------------------------------

NOTE_CLEAN = "no uncommitted edit in it"
NOTE_DIRTY = ("holds an uncommitted edit that is not yours; your commit "
              "leaves it out")
NOTE_NEW = ("does not exist yet: a file you create is yours, commit it as a "
            "plain path")
NOTE_UNTRACKED = ("not in HEAD: a file you created is yours, commit it as a "
                  "plain path; one someone else created is theirs, leave it out")


def snap(raws: list[str]) -> list[str]:
    """Every path is checked before any is snapshotted; then each tracked
    file's content is stored as a blob. Returns the lines to print."""
    targets = [locate(raw) for raw in raws]
    root = one_root(targets)
    head = head_or_none(root)

    plan: list[tuple[Target, Entry | None, bool]] = []
    for target in targets:
        info = lstat_or_none(target.path)
        entry = tree_entry(root, head, target.rel) if head else None
        if entry is not None and not entry.is_file:
            raise Precondition(f"{target.raw}: not a regular file in HEAD — "
                               "snap takes the files you are about to edit")
        if info is None and entry is not None:
            raise Precondition(f"{target.raw}: in HEAD but missing from the "
                               "working tree — snap takes the files you are "
                               "about to edit")
        if info is not None and not stat.S_ISREG(info.st_mode):
            kind = ("a directory" if stat.S_ISDIR(info.st_mode)
                    else "a symlink" if stat.S_ISLNK(info.st_mode)
                    else "not a regular file")
            raise Precondition(f"{target.raw}: {kind} — snap takes the files "
                               "you are about to edit")
        plan.append((target, entry, info is not None))

    lines = []
    for target, entry, exists in plan:
        if entry is None:
            lines.append(f"{target.raw}  — {NOTE_UNTRACKED if exists else NOTE_NEW}")
            continue
        blob = git_text(root, "hash-object", "-w", "--", target.rel)
        note = NOTE_CLEAN if blob == entry.sha else NOTE_DIRTY
        lines.append(f"{target.raw}@{blob[:12]}  — {note}")
    return lines


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    """A commit argument: a snapshotted file (`snapshot` is its blob's full
    sha, `abbrev` as given) or a plain path (both None)."""

    target: Target
    snapshot: str | None = None
    abbrev: str | None = None

    @property
    def absolute_token(self) -> str:
        """The argument again, with an absolute path — the background rerun
        may start in another directory."""
        if self.abbrev is None:
            return self.target.absolute
        return f"{self.target.absolute}@{self.abbrev}"


@dataclass(frozen=True)
class Merged:
    """A snapshot item, worked out: what goes into the commit (`blob` None is
    a deletion) and what the working file holds."""

    item: Item
    mode: str
    blob: str | None
    work: str | None
    unchanged: bool


@dataclass(frozen=True)
class Refusal:
    item: Item
    reason: str
    head: bytes = b""
    snapshot: bytes = b""
    work: bytes = b""
    detail: str = ""


def parse_items(raws: list[str]) -> list[Item]:
    items = []
    for raw in raws:
        match = SNAPSHOT_RE.match(raw)
        if match and match.group(1):
            items.append(Item(locate(match.group(1)), abbrev=match.group(2)))
        else:
            items.append(Item(locate(raw)))
    root = one_root([item.target for item in items])
    for item in items:
        if item.target.rel == ".":
            raise Precondition(f"{item.target.raw}: the whole work tree — name "
                               "the files you wrote")
    resolved, seen = [], set()
    for item in items:
        if item.abbrev is None:
            resolved.append(item)
            continue
        result = run_git(root, "rev-parse", "--verify", "--quiet",
                         f"{item.abbrev}^{{blob}}")
        if result.returncode != 0:
            raise Precondition(f"{item.target.raw}@{item.abbrev}: no such "
                               "snapshot in this repo — snap the file first")
        if item.target.rel in seen:
            raise Precondition(f"{item.target.raw}: given with two snapshots")
        seen.add(item.target.rel)
        resolved.append(Item(item.target, os.fsdecode(result.stdout).strip(),
                             item.abbrev))
    return resolved


def merge_snapshot(root: Path, base: str, item: Item,
                   scratch: Path) -> Merged | Refusal:
    """Apply the change from the snapshot to the working file onto `base`'s
    version: git merge-file with HEAD as current, the snapshot as base and
    the working file as other."""
    rel = item.target.rel
    head = tree_entry(root, base, rel)
    if head is None or not head.is_file:
        return Refusal(item, "gone")
    info = lstat_or_none(item.target.path)
    if info is None:
        if head.sha == item.snapshot:
            return Merged(item, head.mode, None, None, unchanged=False)
        return Refusal(item, "deleted",
                       head=git(root, "cat-file", "blob", head.sha),
                       snapshot=git(root, "cat-file", "blob", item.snapshot))
    if not stat.S_ISREG(info.st_mode):
        return Refusal(item, "not-a-file")
    work = git_text(root, "hash-object", "-w", "--", rel)
    if work == item.snapshot:
        return Merged(item, head.mode, head.sha, work, unchanged=True)
    if head.sha == item.snapshot:
        return Merged(item, head.mode, work, work, unchanged=False)

    contents = [git(root, "cat-file", "blob", sha)
                for sha in (head.sha, item.snapshot, work)]
    files = []
    for name, content in zip(("HEAD", "snapshot", "yours"), contents,
                             strict=True):
        file = scratch / f"merge-{name}"
        file.write_bytes(content)
        files.append(str(file))
    result = run_git(root, "merge-file", "-p", "-L", "HEAD", "-L", "snapshot",
                     "-L", "yours", *files)
    if result.returncode == 0:
        blob = git_text(root, "hash-object", "-w", "--stdin",
                        input=result.stdout)
        return Merged(item, head.mode, blob, work, unchanged=False)
    reason = "overlap" if 1 <= result.returncode <= 127 else "unmergeable"
    return Refusal(item, reason, *contents, detail=stderr_of(result))


def unified(before: bytes, after: bytes, before_name: str,
            after_name: str) -> str:
    lines = difflib.unified_diff(
        before.decode(errors="replace").splitlines(),
        after.decode(errors="replace").splitlines(),
        before_name, after_name, n=1, lineterm="")
    return "\n".join(lines) or "(no difference)"


def refusal_text(refusal: Refusal) -> str:
    raw = refusal.item.target.raw
    if refusal.reason == "gone":
        return (f"{raw}: no longer a file in HEAD — a commit since your "
                "snapshot removed it. Take your change back out of the file, "
                "leaving it as you found it, and defer it, saying why.")
    if refusal.reason == "not-a-file":
        return (f"{raw}: no longer a regular file in the working tree. Put "
                "it back as you found it and defer your change, saying why.")
    if refusal.reason == "deleted":
        return "\n".join([
            f"{raw}: you deleted it, and it holds an uncommitted edit that is "
            "not yours:",
            unified(refusal.head, refusal.snapshot, f"HEAD:{raw}",
                    f"{raw} at your snapshot"),
            f"Put it back as you found it (`git cat-file blob "
            f"{refusal.item.abbrev} > {raw}` restores your snapshot) and "
            "defer the deletion, saying why."])
    diffs = [
        "The uncommitted edit that is not yours (HEAD → your snapshot):",
        unified(refusal.head, refusal.snapshot, f"HEAD:{raw}",
                f"{raw} at your snapshot"),
        "Your change (your snapshot → now):",
        unified(refusal.snapshot, refusal.work, f"{raw} at your snapshot",
                f"{raw} now"),
    ]
    if refusal.reason == "unmergeable":
        return "\n".join([
            f"{raw}: git merge-file cannot merge it: {refusal.detail}",
            *diffs,
            "Take your change back out of the file, leaving it as you found "
            "it, and defer it, saying why."])
    return "\n".join([
        f"{raw}: your change touches the lines of an uncommitted edit that is "
        "not yours, or the lines next to them.",
        *diffs,
        "Take your change back out of the file, leaving it as you found it, "
        "and defer it, saying why."])


def background_line(lease: Path, messages: list[str], items: list[Item]) -> str:
    """This same commit, run under the lease: flock waits for the phase."""
    argv = ["python3", str(Path(__file__).resolve()), "commit"]
    for message in messages:
        argv += ["-m", message]
    argv += [item.absolute_token for item in items]
    return f"flock -s {shlex.quote(str(lease))} {shlex.join(argv)}"


def holder_note(lease: Path) -> str:
    try:
        note = (lease.parent / HOLDER_NAME).read_text().strip()
    except OSError:
        note = ""
    return note or "(no holder note)"


def hold_lease(lease: Path, branch: str | None) -> int | None:
    """The shared hold on the spec tree's lease, kept until the tool exits
    (the caller closes the fd), so a phase cannot check its branch out
    between the hook and the ref update. None when the session is the
    running phase's own, whose driver holds the lease exclusively for it."""
    phase = os.environ.get(PHASE_BRANCH_ENV)
    if phase and branch is not None and phase == branch:
        return None
    fd = os.open(lease, os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Held(holder_note(lease)) from None
    except BaseException:
        os.close(fd)
        raise
    return fd


def move_head(root: Path, new: str, old: str, reason: str) -> str | None:
    """Move HEAD from `old` to `new` — compare-and-swap, so it fails when
    another session committed since `old` was read. None once moved; git's
    complaint otherwise. A seam: the suite wraps it to land a commit
    between an attempt's read of HEAD and its ref update."""
    result = run_git(root, "update-ref", "-m", reason, "HEAD", new, old)
    return None if result.returncode == 0 else stderr_of(result)


def sync_index(root: Path, base: str, commit: str) -> list[str]:
    """Bring the real index along to the new commit, path by path, where it
    still held `base`'s entry; a path someone staged something else at is
    left as it is. Returns warnings — the commit stands either way."""
    names = git(root, "diff-tree", "-r", "-z", "--name-only", base, commit)
    cacheinfo, removals, touched = [], [], []
    for name in filter(None, names.split(b"\0")):
        rel = os.fsdecode(name)
        before, after = tree_entry(root, base, rel), tree_entry(root, commit, rel)
        if index_entry(root, rel) != before:
            continue
        touched.append(rel)
        if after is None:
            removals.append(rel)
        else:
            cacheinfo += ["--cacheinfo", f"{after.mode},{after.sha},{rel}"]
    if not touched:
        return []
    args = ["update-index", "--add", *cacheinfo]
    if removals:
        args += ["--force-remove", "--", *removals]
    for attempt in range(INDEX_LOCK_TRIES):
        result = run_git(root, *args)
        if result.returncode == 0:
            return []
        if "index.lock" not in stderr_of(result):
            break
        if attempt + 1 < INDEX_LOCK_TRIES:
            time.sleep(INDEX_LOCK_PAUSE)
    paths = " ".join(shlex.quote(rel) for rel in touched)
    return [f"warning: the commit stands, but the index still holds the old "
            f"{paths} ({stderr_of(result)}); `git reset -q -- {paths}` puts "
            "it right"]


def commit(messages: list[str], raws: list[str]) -> int:
    items = parse_items(raws)
    root = items[0].target.root
    lease = Path(git_text(root, "rev-parse", "--absolute-git-dir")) / LEASE_NAME
    branch = current_branch(root)
    try:
        fd = hold_lease(lease, branch)
    except Held as held:
        note = "\n".join(f"    {line}" for line in str(held).splitlines())
        print("spec_commit: nothing committed — the spec tree is held by a "
              f"running phase:\n{note}\n"
              "Run this same command again in the background, under the spec "
              "tree's lease. It waits until the phase gives the tree back, "
              "which can take hours:\n\n    "
              + background_line(lease, messages, items), file=sys.stderr)
        return 4
    try:
        return commit_held(root, lease, branch, messages, items)
    finally:
        if fd is not None:
            os.close(fd)


def commit_held(root: Path, lease: Path, branch: str | None,
                messages: list[str], items: list[Item]) -> int:
    subject = (messages[0].splitlines() or [""])[0]
    plain = [item.target.rel for item in items if item.snapshot is None]
    snapshots = [item for item in items if item.snapshot is not None]
    message_args = [arg for message in messages for arg in ("-m", message)]
    failure = ""
    for _ in range(ATTEMPTS):
        base = head_or_none(root)
        if base is None:
            raise Precondition("HEAD has no commit yet — nothing to commit onto")
        with tempfile.TemporaryDirectory(prefix="spec_commit.") as scratch:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
            git(root, "read-tree", base, env=env)
            if plain:
                added = run_git(root, "add", "--", *plain, env=env)
                if added.returncode != 0:
                    raise Precondition(f"git add: {stderr_of(added)}")
            results = [merge_snapshot(root, base, item, Path(scratch))
                       for item in snapshots]
            refusals = [r for r in results if isinstance(r, Refusal)]
            if refusals:
                print("\n\n".join(refusal_text(r) for r in refusals),
                      file=sys.stderr)
                print("\nNothing committed: refusal is all-or-nothing, so "
                      "nothing else in this call went in either. Once the "
                      "files above are as you found them, commit the rest "
                      "again without them.", file=sys.stderr)
                return 3
            merged = [r for r in results if isinstance(r, Merged)]
            stage = ["update-index", "--add"]
            removals = []
            for result in merged:
                if result.blob is None:
                    removals.append(result.item.target.rel)
                else:
                    stage += ["--cacheinfo", f"{result.mode},{result.blob},"
                                             f"{result.item.target.rel}"]
            if removals:
                stage += ["--force-remove", "--", *removals]
            if merged:
                git(root, *stage, env=env)
            warnings = [
                f"warning: no change of yours in {r.item.target.raw} since "
                "its snapshot — an edit made before `snap` is in the "
                "snapshot and counts as not yours"
                for r in merged if r.unchanged]
            tree = git_text(root, "write-tree", env=env)
            if tree == git_text(root, "rev-parse", f"{base}^{{tree}}"):
                for warning in warnings:
                    print(warning, file=sys.stderr)
                print("nothing committed: the tree is unchanged")
                return 0
            hook = run_git(root, "hook", "run", "--ignore-missing",
                           "pre-commit", env=env, literal=False)
            if hook.returncode != 0:
                output = (os.fsdecode(hook.stdout) + os.fsdecode(hook.stderr))
                print(output.rstrip("\n"), file=sys.stderr)
                print("\nspec_commit: nothing committed — the pre-commit hook "
                      "refused it. Where the hook says to commit again under "
                      "the spec tree's lease, it is this same command that "
                      "runs that way, in the background:\n\n    "
                      + background_line(lease, messages, items),
                      file=sys.stderr)
                return 4
            new = git_text(root, "commit-tree", tree, "-p", base, *message_args)
        failure = move_head(root, new, base, f"commit: {subject}")
        if failure is None:
            break
    else:
        raise GitError(f"nothing committed: HEAD kept moving through {ATTEMPTS} "
                       f"attempts; last: {failure}")

    for warning in warnings:
        print(warning, file=sys.stderr)
    try:
        for warning in sync_index(root, base, new):
            print(warning, file=sys.stderr)
    except Exception as exc:  # the commit stands; the index is a nicety
        print(f"warning: the commit stands, but syncing the index failed "
              f"({exc}); `git reset -q -- <paths>` puts it right",
              file=sys.stderr)
    print(f"committed {new[:12]} on {branch or 'detached HEAD'}: {subject}")
    for result in merged:
        if result.work is not None and result.work != result.blob:
            print(f"{result.item.target.raw}: the uncommitted edit that is not "
                  "yours is still in the working tree, uncommitted")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap_parser = sub.add_parser(
        "snap", help="store the files you are about to edit as they are now "
                     "and print the token to commit each by")
    snap_parser.add_argument("paths", nargs="+", metavar="path")
    commit_parser = sub.add_parser(
        "commit", help="commit your change to each snapshotted file, and "
                       "plain paths whole")
    commit_parser.add_argument("-m", dest="messages", action="append",
                               required=True, metavar="message",
                               help="a paragraph of the commit message; "
                                    "repeatable")
    commit_parser.add_argument("items", nargs="+", metavar="path@sha|path")
    args = parser.parse_args(argv)

    try:
        if args.command == "snap":
            for line in snap(args.paths):
                print(line)
            return 0
        return commit(args.messages, args.items)
    except Precondition as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # anything unexpected is exit 1 by contract
        print(f"spec_commit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
