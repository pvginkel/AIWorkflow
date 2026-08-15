#!/usr/bin/env python3
"""Close a slice out in the spec repo — the mechanical half of /dev:run-slice
step 3, which an agent otherwise does by hand (hunting the README entry,
moving it, and remembering not to `git add -A` a shared working tree).

Given `<spec-repo>/slices/NNN_slug` it:

  1. finds the slice's entry in the spec README's `## Pending` section
     (the `- **NNN** — …` bullet and its wrapped continuation lines),
  2. moves that entry verbatim to the end of the `## Completed` list,
  3. `git mv`s the slice folder into `slices/completed/`,
  4. stages README.md **by name** — never `git add -A`: the spec repo is one
     working tree shared by several parallel sessions.

The spec repo is not configured here: it is the repo the slice folder sits in,
so the path the caller passes (resolved from the target repo's `Spec repo:`
CLAUDE.md line) is the only input.

It does not commit: the calling session commits the README and the moved
folder together with the run's state.json, log.txt and close-out.md — staged
by name at their new path (`git mv` stages the rename with HEAD's content, so
the driver's late edits to those files are still unstaged).

Every precondition is checked before anything is mutated — a missing README
entry, a missing folder, or a slice already under `slices/completed/` exits 2
having changed nothing.

Usage:
    close_slice.py <slice_dir>

Exit codes: 0 closed out · 2 usage/precondition error · 1 unexpected error.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

BULLET_RE = re.compile(r"^-\s+\*\*(?P<num>\d+)\*\*")
CONTINUATION_RE = re.compile(r"^\s+\S")
HEADING_RE = re.compile(r"^#{1,6}\s")
SLICE_NUM_RE = re.compile(r"^(\d+)")

PENDING_HEADING = "## Pending"
COMPLETED_HEADING = "## Completed"


class Precondition(Exception):
    """A precondition failure — exit 2, nothing mutated."""


def spec_root_for(slice_dir: Path) -> Path:
    """The spec repo root: the parent of the `slices/` tree the slice sits in
    (`slices/NNN_slug`, `slices/backlog/NNN_slug`, … all resolve the same)."""
    for parent in slice_dir.parents:
        if parent.name == "slices":
            return parent.parent
    raise Precondition(f"{slice_dir} is not inside a slices/ tree")


def slice_number(slice_dir: Path) -> str:
    match = SLICE_NUM_RE.match(slice_dir.name)
    if not match:
        raise Precondition(f"{slice_dir.name} does not start with a slice "
                           "number")
    return match.group(1)


def section_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    """(first line after the heading, first line of the next section)."""
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        end = len(lines)
        for offset in range(index + 1, len(lines)):
            if HEADING_RE.match(lines[offset]):
                end = offset
                break
        return index + 1, end
    raise Precondition(f"the spec README has no `{heading}` section")


def find_entry(lines: list[str], start: int, end: int,
               number: str) -> tuple[int, int] | None:
    """The half-open line range of the `- **NNN** — …` bullet in [start, end),
    including its wrapped continuation lines. None when it is not there."""
    for index in range(start, end):
        match = BULLET_RE.match(lines[index])
        if not match or int(match.group("num")) != int(number):
            continue
        stop = index + 1
        while stop < end and CONTINUATION_RE.match(lines[stop]):
            stop += 1
        return index, stop
    return None


def last_entry_end(lines: list[str], start: int, end: int) -> int:
    """Where a new entry appends: after the section's last bullet block, or —
    for a section that has no entries yet — after its intro prose."""
    last = None
    for index in range(start, end):
        if BULLET_RE.match(lines[index]) or CONTINUATION_RE.match(lines[index]):
            last = index + 1
    if last is not None:
        return last
    last = start
    for index in range(start, end):
        if lines[index].strip():
            last = index + 1
    return last


def git(spec_root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(spec_root), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise Precondition(f"git {' '.join(args)} failed: "
                           f"{result.stderr.strip() or result.stdout.strip()}")


def close_slice(slice_dir: Path) -> list[str]:
    """Run the close-out. Returns the action lines to print."""
    slice_dir = slice_dir.resolve()
    spec_root = spec_root_for(slice_dir)
    number = slice_number(slice_dir)

    if slice_dir.parent.name == "completed":
        raise Precondition(f"slice {number} is already under "
                           "slices/completed/")
    if not slice_dir.is_dir():
        raise Precondition(f"slice folder not found: {slice_dir}")
    destination = spec_root / "slices" / "completed" / slice_dir.name
    if destination.exists():
        raise Precondition(f"{destination} already exists")

    readme_path = spec_root / "README.md"
    if not readme_path.is_file():
        raise Precondition(f"spec README not found: {readme_path}")
    text = readme_path.read_text()
    lines = text.splitlines()

    pending_start, pending_end = section_bounds(lines, PENDING_HEADING)
    completed_start, completed_end = section_bounds(lines, COMPLETED_HEADING)
    if find_entry(lines, completed_start, completed_end, number):
        raise Precondition(f"slice {number} is already listed under "
                           f"`{COMPLETED_HEADING}` in the spec README")
    span = find_entry(lines, pending_start, pending_end, number)
    if not span:
        raise Precondition(f"no `- **{number}** — …` entry under "
                           f"`{PENDING_HEADING}` in the spec README")

    # All preconditions hold; from here on we mutate.
    git(spec_root, "mv", str(slice_dir.relative_to(spec_root)),
        str(destination.relative_to(spec_root)))

    entry = lines[span[0]:span[1]]
    remaining = lines[:span[0]] + lines[span[1]:]
    shift = span[1] - span[0]
    insert_at = last_entry_end(
        remaining,
        completed_start - shift if completed_start > span[0] else completed_start,
        completed_end - shift if completed_end > span[0] else completed_end)
    updated = remaining[:insert_at] + entry + remaining[insert_at:]
    readme_path.write_text(
        "\n".join(updated) + ("\n" if text.endswith("\n") else ""))
    git(spec_root, "add", "README.md")

    return [
        f"git mv slices/{slice_dir.name} → slices/completed/{slice_dir.name}",
        f"README.md: slice {number} entry moved Pending → Completed "
        f"({shift} line{'' if shift == 1 else 's'})",
        "staged README.md (not committed — commit it with state.json/log.txt/"
        "close-out.md, added by name at their new path)",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slice_dir",
                        help="path to <spec-repo>/slices/NNN_slug")
    args = parser.parse_args(argv)

    try:
        actions = close_slice(Path(args.slice_dir))
    except Precondition as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # anything unexpected is exit 1 by contract
        print(f"close_slice failed: {exc}", file=sys.stderr)
        return 1
    for action in actions:
        print(action)
    return 0


if __name__ == "__main__":
    sys.exit(main())
