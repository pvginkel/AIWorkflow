#!/usr/bin/env python3
"""Close a slice out in the spec repo — the mechanical half of /dev:run-slice
step 3, which an agent otherwise does by hand (hunting the README entry,
moving it, and remembering not to `git add -A` a shared working tree).

Given `<spec-repo>/slices/NNN_slug` it:

  1. finds the slice's entry in the spec README's `## Pending` section — the
     `- **NNN** — …` bullet, plain or link-wrapped (`- **[NNN](path)** — …`),
     plus its wrapped continuation lines,
  2. adds it to `## Completed`, in that section's own shape: appended to a
     bullet list with links to the slice's old path rewritten, or folded into
     a synthesized row when the section is a Markdown table,
  3. `git mv`s the slice folder into `slices/completed/`,
  4. stages README.md **by name** — never `git add -A`: the spec repo is one
     working tree shared by several parallel sessions.

The spec repo is not configured here: it is the repo the slice folder sits in,
so the path the caller passes (resolved from the target repo's `.aiworkflowrc`
`spec_repo`) is the only input.

It does not commit: the calling session commits the README and the moved
folder together with the run's state.json, log.txt and close-out.md — staged
by name at their new path (`git mv` stages the rename with HEAD's content, so
the driver's late edits to those files are still unstaged).

Every precondition is checked before anything is mutated — a missing README
entry, a missing folder, a folder whose id is not a whole number, or a slice
already under `slices/completed/` exits 2 having changed nothing.

Usage:
    close_slice.py <slice_dir>

Exit codes: 0 closed out · 2 usage/precondition error · 1 unexpected error.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# The number must be terminated — by the closing `**` or by the `](` of a
# link-wrapped id — or `- **063b** — …` would answer to a query for 063.
BULLET_RE = re.compile(r"^-\s+\*\*\[?(?P<num>\d+)(?:\*\*|\]\()")
CONTINUATION_RE = re.compile(r"^\s+\S")
HEADING_RE = re.compile(r"^#{1,6}\s")
# Same rule for the folder: digits, then `_` or the end of the name.
SLICE_NUM_RE = re.compile(r"^(\d+)(?:_|$)")
LEADING_DIGITS_RE = re.compile(r"^\d+")
# A table's first cell reads `[013 slug](…)` or `[pam-credentials](…)`; digits
# count only where they run out, so 013 is not the head of 0134.
CELL_NUM_RE = re.compile(r"^\[?(?P<num>\d+)(?!\d)")

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
    """The folder's id, and only when its digits run out at `_` or at the end
    of the name. A bare `^(\\d+)` prefix once read `182b_…` as slice 182 and
    moved the wrong README entry in production, so a letter suffix is now a
    hard error rather than a near miss."""
    match = SLICE_NUM_RE.match(slice_dir.name)
    if match:
        return match.group(1)
    if LEADING_DIGITS_RE.match(slice_dir.name):
        raise Precondition(
            f"{slice_dir.name}: letter-suffixed slice ids are not supported — "
            "slice ids are whole numbers, and every slice, follow-ups "
            "included, takes a fresh one from allocate-next-slice.sh")
    raise Precondition(f"{slice_dir.name} does not start with a slice "
                       "number")


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


def is_table_section(lines: list[str], start: int, end: int) -> bool:
    """Whether a section is written as a Markdown table rather than a bullet
    list — some spec repos keep `## Completed` as one. The first non-blank line
    decides; a bullet moved verbatim into a table would corrupt it."""
    for index in range(start, end):
        if lines[index].strip():
            return lines[index].strip().startswith("|")
    return False


def table_cells(line: str) -> list[str]:
    """A `| a | b |` row's cells, outer pipes dropped. A naive split, which is
    enough for what we read from it: the header's width and a row's first
    cell, neither of which carries an escaped pipe."""
    parts = line.strip().split("|")
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [part.strip() for part in parts]


def table_rows(lines: list[str], start: int, end: int) -> list[int]:
    """Line numbers of the table's rows in [start, end) — header and separator
    included, since both are just rows to append after."""
    return [index for index in range(start, end)
            if lines[index].strip().startswith("|")]


def table_lists(lines: list[str], start: int, end: int, number: str) -> bool:
    """The table's answer to find_entry: is this slice already a row? Only the
    first cell carries the id; cells with no leading digits (`[pam-…](…)`)
    are simply not numbered and can never collide."""
    for index in table_rows(lines, start, end):
        cells = table_cells(lines[index])
        if not cells:
            continue
        match = CELL_NUM_RE.match(cells[0])
        if match and int(match.group("num")) == int(number):
            return True
    return False


def rewrite_links(entry: list[str], dirname: str) -> list[str]:
    """The entry moves as it reads, but its links must not: a reference to the
    slice's old home (`slices/backlog/<dir>/`, or `slices/<dir>/` once planned)
    now points at `slices/completed/<dir>/`. The two passes cannot collide:
    neither pattern matches the other's output."""
    moved = f"slices/completed/{dirname}/"
    return [line.replace(f"slices/backlog/{dirname}/", moved)
                .replace(f"slices/{dirname}/", moved)
            for line in entry]


def entry_description(entry: list[str]) -> str:
    """The prose half of a Pending bullet — everything past the ` — ` that
    follows the id — folded onto one line for a table cell, pipes escaped so
    the cell survives. A bullet with no separator contributes all its text."""
    head = entry[0]
    match = BULLET_RE.match(head)
    cut = head.find(" — ", match.end() if match else 0)
    text = head[cut + 3:] if cut >= 0 else head.lstrip("- ")
    parts = [text] + entry[1:]
    return " ".join(part.strip() for part in parts
                    if part.strip()).replace("|", r"\|")


def slice_link(slice_dir: Path, number: str) -> str:
    """The row's first cell: `[NNN slug-with-hyphens](slices/completed/…)`,
    pointing at the slice's plan if it has one, else its brief, else the folder
    — read before the `git mv`, while the folder is still where it was."""
    slug = slice_dir.name[len(number):].lstrip("_").replace("_", "-")
    target = f"slices/completed/{slice_dir.name}"
    for candidate in ("plan.md", "slice.md"):
        if (slice_dir / candidate).is_file():
            target = f"{target}/{candidate}"
            break
    return f"[{f'{number} {slug}'.strip()}]({target})"


def table_row(header: str, first_cell: str, description: str) -> str:
    """A synthesized row, as wide as the header. Only the two cells we can
    derive are filled; the middle ones get an em dash for the closing session
    to refine by hand."""
    columns = max(len(table_cells(header)), 2)
    cells = [first_cell] + ["—"] * (columns - 2) + [description]
    return "| " + " | ".join(cells) + " |"


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
    # Pending is a bullet list everywhere; only Completed varies in shape.
    as_table = is_table_section(lines, completed_start, completed_end)
    listed = (table_lists(lines, completed_start, completed_end, number)
              if as_table
              else bool(find_entry(lines, completed_start, completed_end,
                                   number)))
    if listed:
        raise Precondition(f"slice {number} is already listed under "
                           f"`{COMPLETED_HEADING}` in the spec README")
    span = find_entry(lines, pending_start, pending_end, number)
    if not span:
        raise Precondition(f"no `- **{number}** — …` entry under "
                           f"`{PENDING_HEADING}` in the spec README")
    # Read off the folder before the mv relocates it.
    first_cell = slice_link(slice_dir, number)

    # All preconditions hold; from here on we mutate.
    git(spec_root, "mv", str(slice_dir.relative_to(spec_root)),
        str(destination.relative_to(spec_root)))

    entry = lines[span[0]:span[1]]
    remaining = lines[:span[0]] + lines[span[1]:]
    shift = span[1] - span[0]
    start = completed_start - shift if completed_start > span[0] else completed_start
    end = completed_end - shift if completed_end > span[0] else completed_end
    if as_table:
        rows = table_rows(remaining, start, end)
        block = [table_row(remaining[rows[0]], first_cell,
                           entry_description(entry))]
        insert_at = rows[-1] + 1
    else:
        block = rewrite_links(entry, slice_dir.name)
        insert_at = last_entry_end(remaining, start, end)
    updated = remaining[:insert_at] + block + remaining[insert_at:]
    readme_path.write_text(
        "\n".join(updated) + ("\n" if text.endswith("\n") else ""))
    git(spec_root, "add", "README.md")

    if as_table:
        moved = (f"README.md: slice {number} entry moved Pending → Completed "
                 "as a synthesized table row — the middle cells are `—`, "
                 "refine them by hand if the table wants them")
    else:
        moved = (f"README.md: slice {number} entry moved Pending → Completed "
                 f"({shift} line{'' if shift == 1 else 's'})")
    return [
        f"git mv slices/{slice_dir.name} → slices/completed/{slice_dir.name}",
        moved,
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
