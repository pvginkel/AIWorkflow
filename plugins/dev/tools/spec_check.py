#!/usr/bin/env python3
"""Check the shape of what changed in a spec repo since a base commit.

A spec repo seldom has a suite: AnsibleSpecs has no manifest, script or CI,
so every phase there wrote a throwaway check of its own and the driver's
gate had nothing to run (AIWF-68). The run loop gates a phase whose Target is the
spec repo with this tool, then with the repo's own `kc project test` where
its tree has a manifest — rules one spec repo alone holds belong there.

Only what the change since `--base` made is checked — committed, staged,
unstaged and untracked files git does not ignore — so old debt never reds a
phase, in a file it touched or one it did not:

- `git diff --check <base>`: whitespace errors and leftover conflict
  markers, in the lines the change added (an untracked file's are all
  added), as the repo's whitespace config and attributes define them;
- every changed `.md` file: every pipe table outside code fences that has
  a line the change added has a header row, a delimiter row under it, and
  the header's cell count in every row — a pipe that is escaped (`\\|`) or
  inside a backtick code span separates no cells; and its code fences are
  closed, where they were at the base;
- every changed `.json` file parses, where it did at the base.

A file the base does not have (`git show <base>:<path>` finds none) is new,
and every line of it is the change's; so is every line of an untracked
file.

It reads the tree and never writes to it, the index included.

Usage:
    spec_check.py --base <rev> [<repo>]

Output is one `path:line: what` line per problem, then a summary line.
Exit codes: 0 clean · 1 a problem found · 2 usage error (a `--base` that is
no commit, a directory that is no git repo).
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

# A code fence's opening line: three or more backticks or tildes, at any
# indent (a fence inside a list item is indented), then an info string,
# which in a backtick fence holds no backtick. Its closing line is the same
# character, at least as many, and nothing after it.
FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
# One cell of a table's delimiter row: dashes, a colon at either end for
# its alignment.
DELIMITER_CELL_RE = re.compile(r"^:?-+:?$")
# A problem line of `git diff --check`; the offending line that follows a
# whitespace error starts with `+`.
CHECK_LINE_RE = re.compile(r"^(.*):(\d+): (.*)$")
# A hunk header of `git diff -U0`: where its `+` lines start, and how many.
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


class UsageError(Exception):
    """A base or a repo the check cannot run against: exit 2."""


def _git(repo: Path, *args: str, codes: tuple[int, ...] = (0,)) -> str:
    """`git <args>` in `repo`, its stdout; UsageError with git's message on
    an exit code not in `codes`."""
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                                text=True, errors="surrogateescape")
    except OSError as e:   # no such directory, no git
        raise UsageError(f"`git {args[0]}` cannot run in {repo}: {e}") from None
    if result.returncode not in codes:
        raise UsageError(f"`git {' '.join(args)}` failed in {repo}: "
                         f"{(result.stderr or result.stdout).strip()}")
    return result.stdout


def _split_z(text: str) -> list[str]:
    return [name for name in text.split("\0") if name]


def changed_files(repo: Path, base: str) -> tuple[list[str], list[str]]:
    """(every path changed since `base`, the untracked ones among them),
    repo-relative and sorted: a deleted file is listed, and has nothing to
    check."""
    tracked = _split_z(_git(repo, "diff", "--name-only", "-z",
                            "--no-renames", base, "--"))
    untracked = _split_z(_git(repo, "ls-files", "-z", "--others",
                              "--exclude-standard"))
    return sorted(set(tracked) | set(untracked)), sorted(untracked)


def _check_lines(output: str) -> list[tuple[str, int, str]]:
    problems = []
    for line in output.splitlines():
        match = CHECK_LINE_RE.match(line)
        if match and not line.startswith("+"):
            problems.append((match[1], int(match[2]), match[3]))
    return problems


def whitespace_problems(repo: Path, base: str,
                        untracked: list[str]) -> list[tuple[str, int, str]]:
    """`git diff --check` over the change: the tracked files against
    `base`, each untracked file against nothing. Its exit code says only
    that it found something, so its lines are read instead."""
    output = _git(repo, "diff", "--check", "--no-color", base, "--",
                  codes=(0, 2))
    problems = _check_lines(output)
    for name in untracked:
        if (repo / name).is_file():
            output = _git(repo, "diff", "--no-index", "--check", "--no-color",
                          "--", "/dev/null", name, codes=(0, 1, 2, 3))
            problems += _check_lines(output)
    return problems


def table_cells(line: str) -> list[str] | None:
    """A table row's cells, or None for a line with no cell-separating pipe.
    A pipe separates cells unless it is escaped or inside a backtick code
    span — a run of backticks to the next run of exactly as many; one with
    no such run is literal. One leading and one trailing pipe are the row's
    edges."""
    text = line.strip()
    cuts: list[int] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == "`":
            run = len(text) - i - len(text[i:].lstrip("`"))
            close = re.compile(f"(?<!`){'`' * run}(?!`)").search(text, i + run)
            i = close.end() if close else i + run
            continue
        if char == "|":
            cuts.append(i)
        i += 1
    if not cuts:
        return None
    cells, start = [], 0
    for cut in cuts:
        cells.append(text[start:cut])
        start = cut + 1
    cells.append(text[start:])
    if cuts[0] == 0:
        cells.pop(0)
    if cuts[-1] == len(text) - 1 and len(cells) > 1:
        cells.pop()
    return [cell.strip() for cell in cells]


def _is_delimiter(line: str | None, cells: list[str] | None) -> bool:
    return bool(line is not None and cells
                and all(DELIMITER_CELL_RE.match(cell) for cell in cells))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _fences(lines: list[str]) -> tuple[list[str | None],
                                        tuple[str, int, int] | None]:
    """Each line as the table scan sees it — None inside a code fence — and
    the fence still open at the end as (char, length, line), else None."""
    outside: list[str | None] = []
    fence: tuple[str, int, int] | None = None
    for n, line in enumerate(lines, 1):
        if fence is None:
            match = FENCE_OPEN_RE.match(line)
            if match and not (match[1][0] == "`" and "`" in match[2]):
                fence = (match[1][0], len(match[1]), n)
                outside.append(None)
            else:
                outside.append(line)
            continue
        match = FENCE_CLOSE_RE.match(line)
        if match and match[1][0] == fence[0] and len(match[1]) >= fence[1]:
            fence = None
        outside.append(None)
    return outside, fence


def _tables(outside: list[str | None]
            ) -> Iterator[tuple[int, int, list[tuple[int, str]]]]:
    """Every pipe table in the lines outside code fences: (its first line,
    its last line, its problems as (line, what)). A table starts at a row
    that opens with a pipe, or at a row with a pipe right above a delimiter
    row that has one too (a bare `---` under a line is a heading's
    underline); it runs on over the following lines that hold a pipe. A
    broken one — no delimiter row, or no header row — spans its pipe-led
    lines and is one problem, not one per line."""
    rows = [None if line is None else table_cells(line) for line in outside]

    def leads(i: int) -> bool:
        return outside[i] is not None and outside[i].lstrip().startswith("|")

    i = 0
    while i < len(outside):
        line, cells = outside[i], rows[i]
        below = i + 1 < len(outside) and _is_delimiter(outside[i + 1],
                                                       rows[i + 1])
        if cells is None or not (leads(i) or (below
                                              and "|" in outside[i + 1])):
            i += 1
            continue
        first, found = i + 1, []
        if below and not (_is_delimiter(line, cells) and leads(i)):
            width = len(cells)
            if len(rows[i + 1]) != width:
                found.append((i + 2, f"the table's delimiter row has "
                                     f"{_plural(len(rows[i + 1]), 'cell')}, "
                                     f"its header {width}"))
            i += 2
            while i < len(outside) and rows[i] is not None:
                if len(rows[i]) != width:
                    found.append((i + 1, f"a table row with "
                                         f"{_plural(len(rows[i]), 'cell')}, "
                                         f"its header {width}"))
                i += 1
        else:
            found.append((first, "a table delimiter row with no header row "
                                 "above it" if _is_delimiter(line, cells)
                          else "a table header row with no delimiter row "
                               "under it"))
            i += 1
            while i < len(outside) and leads(i):
                i += 1
        yield first, i, found


def markdown_problems(text: str, base: str | None = None,
                      added: set[int] | None = None) -> list[tuple[int, str]]:
    """(line, what) for every unclosed code fence and malformed pipe table in
    a Markdown text that the change made. `base` is the file at the base,
    None for a file new since; `added` the lines the change added or
    changed, None for all of them. A table is the change's when one of its
    lines is added; an unclosed fence when the base closed every fence, or
    has no such file."""
    outside, fence = _fences(text.splitlines())
    problems: list[tuple[int, str]] = []
    if fence is not None and (base is None
                              or _fences(base.splitlines())[1] is None):
        problems.append((fence[2], f"the code fence opened here "
                                   f"({fence[0] * fence[1]}) is never closed"))
    for first, last, found in _tables(outside):
        if added is None or not added.isdisjoint(range(first, last + 1)):
            problems += found
    return problems


def _json_error(data: bytes) -> tuple[int, str] | None:
    try:
        json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        return 1, "not UTF-8 text, so no JSON"
    except json.JSONDecodeError as e:
        return e.lineno, f"invalid JSON: {e.msg}"
    return None


def json_problem(data: bytes, base: bytes | None = None
                 ) -> tuple[int, str] | None:
    """(line, what) when a JSON file's content does not parse and the change
    made it so: it parsed at the base (`base`), or is new (None)."""
    found = _json_error(data)
    if found is None or (base is not None and _json_error(base) is not None):
        return None
    return found


def added_lines(repo: Path, base: str, name: str) -> set[int]:
    """The lines of the file `name` as it is now that its diff from `base`
    adds or changes: every hunk's `+` lines."""
    output = _git(repo, "diff", "-U0", "--no-color", "--no-ext-diff",
                  "--no-textconv", "--no-renames", base, "--", name)
    added: set[int] = set()
    for match in HUNK_RE.finditer(output):
        start = int(match[1])
        added.update(range(start, start + int(match[2] or 1)))
    return added


def base_blob(repo: Path, base: str, name: str) -> bytes | None:
    """The file `name` as it was at `base` — None where it was not there:
    the file is new."""
    result = subprocess.run(["git", "show", f"{base}:{name}"], cwd=repo,
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def check(repo: Path, base: str) -> tuple[list[tuple[str, int, str]],
                                         list[str], str]:
    """(every problem as (path, line, what), sorted; the files changed; the
    base's sha) for the repo holding `repo`, since `base`. UsageError for a
    base or a repo it cannot check against."""
    try:
        top = Path(_git(Path(repo), "rev-parse", "--show-toplevel").strip())
    except UsageError:
        raise UsageError(f"{repo} is not in a git repository") from None
    sha = _git(top, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}",
               codes=(0, 1)).strip()
    if not sha:
        raise UsageError(f"--base {base} is not a commit in {top}")
    changed, untracked = changed_files(top, sha)
    problems = whitespace_problems(top, sha, untracked)
    for name in changed:
        path = top / name
        suffix = path.suffix.lower()
        if not path.is_file() or suffix not in (".md", ".json"):
            continue
        base_data = base_blob(top, sha, name)
        if suffix == ".json":
            if (found := json_problem(path.read_bytes(), base_data)):
                problems.append((name, *found))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        base_text = (None if base_data is None
                     else base_data.decode("utf-8", errors="replace"))
        added = (None if base_data is None or name in untracked
                 else added_lines(top, sha, name))
        problems += [(name, n, what)
                     for n, what in markdown_problems(text, base_text, added)]
    return sorted(problems), changed, sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True,
                        help="the commit the change is taken against")
    parser.add_argument("repo", nargs="?", default=".",
                        help="the repo to check (default: the current "
                             "directory)")
    args = parser.parse_args(argv)
    try:
        problems, changed, sha = check(Path(args.repo), args.base)
    except UsageError as e:
        print(f"spec_check: {e}", file=sys.stderr)
        return 2
    since = f"{_plural(len(changed), 'file')} changed since {sha[:12]}"
    for name, n, what in problems:
        print(f"{name}:{n}: {what}")
    if not problems:
        print(f"spec_check: clean — {since}")
        return 0
    files = len({name for name, _, _ in problems})
    print(f"spec_check: {_plural(len(problems), 'problem')} in "
          f"{_plural(files, 'file')}, of {since}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
