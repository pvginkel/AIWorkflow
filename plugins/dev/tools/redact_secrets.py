#!/usr/bin/env python3
"""Stub out `kind: Secret` data in a unified diff before an agent reads it.

Slice 050 of another project removed five k8s Secrets — encrypted CA keys and
the passwords that decrypt them — and the run loop handed its agents the full
diff: every removed `data:` line landed in the doc-writer's and the
code-reviewer's transcripts. This tool sits between `git diff` and whoever
reads it. Every diff line inside a Secret's `data:` or `stringData:` block —
removed, added and context lines alike — comes out as one
`[Secret <name>: N data lines]` stub per run of such lines.

A hunk does not show enough to tell: a changed value deep in a long `data:`
block has no `kind: Secret` within its three lines of context. So each
touched manifest is read whole at both ends of the range, the Secret data
found there by line number, and the hunks mapped onto it — after checking
that every context and removed line is the old file's and every context and
added line the new file's, so a diff of some other range (or a `-w` diff)
cannot be mapped onto the wrong lines.

It is line-based, with no YAML library: plain multi-document manifests, Helm
and Jinja templates, Ansible tasks nesting a Secret under `definition:` (as a
mapping or a block scalar) and `kind: List` items all come down to one
indentation rule (`secret_data_lines`). Only files whose name carries a
manifest suffix (EXAMINED_SUFFIXES) are read; everything else passes through
untouched — prose and code mention `kind: Secret` freely.

Fail-closed throughout: whatever the tool cannot bound — a Secret in JSON or
flow style, a `data:` with a value on its own line, a diff that does not match
its blobs, a hunk header it cannot read, a combined diff — is a RedactionError
and no output at all, never the raw diff. Its message names the file, the side
and the line, and never a line of the file or the diff: it lands in
bailout.json and logs.

The driver imports it (`redact`) for the diffs it hands agents; agents run the
CLI for any diff they take themselves.

Usage:
    git -C <root> diff <A>..<B> [-- <pathspec>...] \\
        | redact_secrets.py --root <root> <A>..<B>

Exit codes: 0 the redacted diff on stdout · 2 usage error · 3 the diff could
not be redacted (nothing on stdout, the reason on stderr).
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import PurePosixPath

# A file is examined when one of its name's suffixes is a manifest's — so
# `secret.yaml.j2` and `secret.yaml.tpl` count, and `.py`/`.md` never do.
EXAMINED_SUFFIXES = frozenset(
    {".yaml", ".yml", ".json", ".tpl", ".j2", ".jinja", ".jinja2"})

# A YAML document marker, at column 0.
SEPARATOR_RE = re.compile(r"^(?:---|\.\.\.)(?:\s.*)?$")
# The one shape of a Secret the redactor places: a block-style `kind:` key,
# plain or as a list item's first key. `SecretStore`, `ExternalSecret` and
# `SealedSecret` do not match.
KIND_RE = re.compile(r"""^(\s*)(-\s+)?kind:\s*["']?Secret["']?\s*(#.*)?$""")
# Anything that loosely reads as one. A line this matches that KIND_RE did not
# place — JSON, flow style, a quoted key, a comment — is a Secret the
# redactor cannot bound.
LOOSE_KIND_RE = re.compile(r"""(?i)\bkind["']?\s*:\s*["']?Secret\b""")
LIST_ITEM_RE = re.compile(r"^(\s*)(-(?:\s+|$))")


def _key_re(names: str) -> re.Pattern:
    """A block mapping key among `names`, plain or quoted, optionally a list
    item's first key: (indent, `- ` marker, quote, key, value)."""
    return re.compile(rf"""^(\s*)(-\s+)?(["']?)({names})\3\s*:(?:\s(.*))?$""")


DATA_KEY_RE = _key_re("data|stringData")
METADATA_KEY_RE = _key_re("metadata")
NAME_KEY_RE = _key_re("name")
# What may follow a `data:` key on its own line: nothing, `{}`, a comment.
EMPTY_VALUE_RE = re.compile(r"^(?:\{\}\s*)?(?:#.*)?$")
TEMPLATE_STARTS = ("{{", "{%", "{#")

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13,
             '"': 34, "\\": 92}


class RedactionError(Exception):
    """A diff the redactor could not redact. The message names the file, the
    side and the line number and what was wrong — never a content line."""


def is_examined(path: str | None) -> bool:
    """Whether a file at `path` is read for Secret data at all."""
    if not path:
        return False
    return any(s.lower() in EXAMINED_SUFFIXES
               for s in PurePosixPath(path).suffixes)


def _split(text: str) -> list[str]:
    """`text`'s lines as git numbers them: split on `\\n` only (a `\\r`
    stays on its line, as it does in the diff), the last newline ending the
    last line rather than opening another."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _skippable(line: str) -> bool:
    """A line that neither belongs to a mapping's keys nor ends one: blank,
    a comment, or a template line (`{{- if … }}`, `{% for … %}`) — which a
    Helm or Jinja file may put at any column, column 0 included."""
    content = line.strip()
    return (not content or content.startswith("#")
            or content.startswith(TEMPLATE_STARTS))


def _key_col(match: re.Match) -> int:
    return len(match.group(1)) + len(match.group(2) or "")


def _mapping_extent(lines: list[str], k: int, col: int,
                    item: bool) -> tuple[int, int]:
    """[lo, hi) of the mapping whose `kind:` key sits on line index `k` at
    column `col`: its sibling keys and everything nested under them. A
    mapping is bounded by a less-indented line, a new list item at a lesser
    indent, or a document marker; its first key may sit after a `- ` marker
    — and when the kind line itself does (`item`), nothing above it is its
    mapping's."""
    lo = k
    j = k - 1
    while not item and j >= 0:
        line = lines[j]
        if SEPARATOR_RE.match(line):
            break
        if _skippable(line):
            j -= 1
            continue
        marker = LIST_ITEM_RE.match(line)
        if marker:
            dash = len(marker.group(1))
            if dash + len(marker.group(2)) == col:
                lo = j          # the first key of this list item's mapping
                break
            if dash < col:
                break
        elif _indent(line) < col:
            break
        lo = j
        j -= 1
    hi = k + 1
    j = k + 1
    while j < len(lines):
        line = lines[j]
        if SEPARATOR_RE.match(line):
            break
        if not _skippable(line) and _indent(line) < col:
            break
        j += 1
        hi = j
    return lo, hi


def _block_end(lines: list[str], j: int, col: int) -> int:
    """The index past the block under the key on line index `j` at column
    `col`: every following line that is skippable or indented deeper, up to
    the first other line at or left of `col`, or a document marker."""
    t = j + 1
    while t < len(lines):
        line = lines[t]
        if SEPARATOR_RE.match(line):
            break
        if not _skippable(line) and _indent(line) <= col:
            break
        t += 1
    return t


def _scalar(value: str) -> str:
    """A plain or quoted YAML scalar as written, its quotes and trailing
    comment dropped; a templated one (`{{ … }}`) exactly as written."""
    value = value.strip()
    if value.startswith("{{"):
        return value
    value = re.sub(r"\s+#.*$", "", value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def _metadata_name(lines: list[str], j: int, col: int) -> str | None:
    """`name:` among the direct children of the `metadata:` key on line
    index `j` at column `col`."""
    child = None
    for t in range(j + 1, _block_end(lines, j, col)):
        line = lines[t]
        if _skippable(line):
            continue
        if child is None:
            child = _indent(line)
        if _indent(line) != child:
            continue
        match = NAME_KEY_RE.match(line)
        if match and _key_col(match) == child:
            return _scalar(match.group(5) or "") or None
    return None


def secret_data_lines(text: str, where: str = "the file") -> dict[int, str]:
    """Every line of `text` inside a `kind: Secret`'s `data:` or
    `stringData:` block: 1-based line number → the Secret's name
    (`metadata.name`, `<unnamed>` when it has none).

    A Secret is a KIND_RE line; its mapping, the sibling keys at the kind
    key's column around it (`_mapping_extent`); its data, the block under a
    `data:`/`stringData:` sibling (`_block_end`) — the key line itself is
    structure, not data. A ConfigMap's `data:` is no Secret's sibling and is
    left alone. RedactionError, naming `where` and the line, for a `data:`
    whose value sits on its own line, and for a line that loosely reads as a
    Secret's kind but is not one this placed."""
    lines = _split(text)
    placed: set[int] = set()
    data: dict[int, str] = {}
    for k, line in enumerate(lines):
        kind = KIND_RE.match(line)
        if not kind:
            continue
        placed.add(k)
        col = _key_col(kind)
        lo, hi = _mapping_extent(lines, k, col, item=bool(kind.group(2)))
        name = None
        blocks: list[range] = []
        for j in range(lo, hi):
            meta = METADATA_KEY_RE.match(lines[j])
            if meta and _key_col(meta) == col and name is None:
                name = _metadata_name(lines, j, col)
                continue
            key = DATA_KEY_RE.match(lines[j])
            if not key or _key_col(key) != col:
                continue
            if not EMPTY_VALUE_RE.match((key.group(5) or "").strip()):
                raise RedactionError(
                    f"{where}, line {j + 1}: the Secret's `{key.group(4)}:` "
                    "carries a value on its own line (flow style or a "
                    "template), which the redactor cannot bound")
            blocks.append(range(j + 1, _block_end(lines, j, col)))
        for block in blocks:
            for j in block:
                data.setdefault(j + 1, name or "<unnamed>")
    for k, line in enumerate(lines):
        if k not in placed and LOOSE_KIND_RE.search(line):
            raise RedactionError(
                f"{where}, line {k + 1}: reads as a Secret's kind but is not "
                "a block-style `kind: Secret` key (JSON, flow style, a quoted "
                "key or a comment), so its data cannot be bounded")
    return data


# -- the diff -----------------------------------------------------------------

def _unquote(raw: str, where: str) -> str:
    """A path git C-quoted (`"a/caf\\303\\251.yaml"`), unquoted."""
    if not (len(raw) >= 2 and raw[0] == raw[-1] == '"'):
        raise RedactionError(f"{where}: a quoted path without its closing "
                             "quote")
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            esc = body[i + 1:i + 2]
            if esc and esc in C_ESCAPES:
                out.append(C_ESCAPES[esc])
                i += 2
            elif re.fullmatch(r"[0-3][0-7]{2}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
            else:
                raise RedactionError(f"{where}: a quoted path with an escape "
                                     "git does not write")
        elif ch == '"':
            raise RedactionError(f"{where}: a quoted path with a bare quote "
                                 "inside")
        else:
            out += ch.encode("utf-8", "surrogateescape")
            i += 1
    return out.decode("utf-8", "surrogateescape")


def _path(raw: str, where: str) -> str | None:
    """One side's path off its `---`/`+++` line: None for `/dev/null`; git's
    trailing tab after a path with a space dropped; a C-quoted path
    unquoted. The `a/`/`b/` prefix is the caller's to strip."""
    raw = raw.removesuffix("\t")
    if raw == "/dev/null":
        return None
    return _unquote(raw, where) if raw.startswith('"') else raw


def _section_paths(header: list[str], at: int) -> tuple[str | None, str | None]:
    """(old, new) path of a diff section, from its `---`/`+++` lines — the
    `a/`/`b/` prefixes stripped when both sides carry them, a no-prefix diff's
    paths taken as written. A section without those lines (no hunks: a pure
    rename, a mode change, a binary file) falls back on its `diff --git`
    line, read the way git reads it: two equal halves."""
    where = f"diff line {at + 1}"
    minus = [line[4:] for line in header[1:] if line.startswith("--- ")]
    plus = [line[4:] for line in header[1:] if line.startswith("+++ ")]
    if minus and plus:
        old, new = _path(minus[0], where), _path(plus[0], where)
        if old is None and new is None:
            raise RedactionError(f"{where}: both sides of the section are "
                                 "/dev/null")
        if ((old is None or old.startswith("a/"))
                and (new is None or new.startswith("b/"))):
            old = old[2:] if old is not None else None
            new = new[2:] if new is not None else None
        return old, new
    if minus or plus:
        raise RedactionError(f"{where}: a section with a `---` line and no "
                             "`+++` line, or the other way round")
    rest = header[0][len("diff --git "):]
    size = (len(rest) - 5) // 2
    if size > 0 and rest == f"a/{rest[2:2 + size]} b/{rest[2:2 + size]}":
        return rest[2:2 + size], rest[2:2 + size]
    size = (len(rest) - 1) // 2
    if size > 0 and rest == f"{rest[:size]} {rest[:size]}":
        return rest[:size], rest[:size]
    return None, None


class _Side:
    """One end of a section: the file's lines and its Secret data lines."""

    def __init__(self, side: str, path: str | None,
                 blob: Callable[[str, str], str]):
        self.side = side
        self.path = path
        if path is None:
            self.lines: list[str] = []
            self.data: dict[int, str] = {}
            return
        text = blob(side, path)
        self.lines = _split(text)
        self.data = secret_data_lines(text, f"{path} ({side} side)")

    def check(self, number: int, text: str) -> None:
        """Whether the diff's line `number` on this side is the file's."""
        if not (1 <= number <= len(self.lines)
                and self.lines[number - 1] == text):
            raise RedactionError(
                f"{self.path} ({self.side} side), line {number}: the diff "
                "does not match the file there — a diff of another range, a "
                "whitespace-ignoring or textconv'd diff, or a blob read that "
                "went wrong")


def _stub(marker: str, name: str, count: int) -> str:
    return f"{marker}[Secret {name}: {count} data line{'' if count == 1 else 's'}]"


def _redact_section(header: list[str], body: list[str], at: int,
                    old: _Side, new: _Side) -> tuple[list[str], int]:
    """An examined section's lines, its hunks walked against both sides and
    each run of Secret data lines stubbed. `at` is the body's first line
    index in the whole diff, for the messages."""
    path = new.path or old.path
    scrub = bool(old.data or new.data)
    out = list(header)
    stubbed = 0
    k = 0
    while k < len(body):
        hunk = HUNK_RE.match(body[k])
        if not hunk:
            raise RedactionError(f"{path}: diff line {at + k + 1} is not a "
                                 "hunk header where one must stand")
        # The section-heading text after the second `@@` is a line of the
        # file git picked as context — in a file with Secret data, perhaps
        # one of those.
        out.append(body[k][:hunk.start(5)] if scrub else body[k])
        o, n = int(hunk.group(1)), int(hunk.group(3))
        left_o = int(hunk.group(2) or 1)
        left_n = int(hunk.group(4) or 1)
        k += 1
        rows: list[tuple[str, str | None, str]] = []
        while left_o or left_n or (k < len(body) and body[k][:1] == "\\"):
            if k >= len(body):
                raise RedactionError(f"{path}: the hunk at diff line "
                                     f"{at + k} ends short of its header's "
                                     "line counts")
            line = body[k]
            marker, text = line[:1], line[1:]
            name = None
            if marker == "\\":
                pass
            elif marker == " " and left_o and left_n:
                old.check(o, text)
                new.check(n, text)
                name = old.data.get(o) or new.data.get(n)
                o, n, left_o, left_n = o + 1, n + 1, left_o - 1, left_n - 1
            elif marker == "-" and left_o:
                old.check(o, text)
                name = old.data.get(o)
                o, left_o = o + 1, left_o - 1
            elif marker == "+" and left_n:
                new.check(n, text)
                name = new.data.get(n)
                n, left_n = n + 1, left_n - 1
            else:
                raise RedactionError(f"{path}: diff line {at + k + 1} does "
                                     "not fit its hunk's header line counts")
            rows.append((marker, name, line))
            k += 1
        i = 0
        while i < len(rows):
            marker, name, line = rows[i]
            if name is None:
                out.append(line)
                i += 1
                continue
            j = i
            while j < len(rows) and rows[j][:2] == (marker, name):
                j += 1
            out.append(_stub(marker, name, j - i))
            stubbed += j - i
            i = j
    return out, stubbed


def redact(diff: str, blob: Callable[[str, str], str]) -> tuple[str, int]:
    """`diff` (a two-sided `git diff`, as git wrote it) with every line inside
    a Secret's `data:`/`stringData:` stubbed, and how many lines were.

    `blob(side, path)` answers one end of the range — side `"old"` or
    `"new"` — with that file's whole text, unstripped; it is asked only for
    an examined file's sides that exist (`/dev/null` is not read), and may
    raise RedactionError itself. A section with no hunks passes through, as
    does every file that is not examined; everything outside the stubs is
    output unchanged."""
    if not diff:
        return "", 0
    lines = _split(diff)
    out: list[str] = []
    stubbed = 0
    i = 0
    while i < len(lines) and not lines[i].startswith("diff "):
        if lines[i].strip():
            raise RedactionError(f"diff line {i + 1}: text before the first "
                                 "`diff --git` header — not a `git diff`")
        out.append(lines[i])
        i += 1
    while i < len(lines):
        start = i
        if not lines[i].startswith("diff --git "):
            raise RedactionError(f"diff line {i + 1}: a combined or non-git "
                                 "diff header — only a two-sided `git diff` "
                                 "is redacted")
        i += 1
        while i < len(lines) and not lines[i].startswith(("@@", "diff ")):
            i += 1
        header = lines[start:i]
        end = i
        while end < len(lines) and not lines[end].startswith("diff "):
            end += 1
        body = lines[i:end]
        old_path, new_path = _section_paths(header, start)
        if body and old_path is None and new_path is None:
            raise RedactionError(f"diff line {start + 1}: a section whose "
                                 "paths cannot be read")
        if body and (is_examined(old_path) or is_examined(new_path)):
            red, count = _redact_section(
                header, body, i,
                _Side("old", old_path, blob), _Side("new", new_path, blob))
            out += red
            stubbed += count
        else:
            out += lines[start:end]
        i = end
    return "\n".join(out) + ("\n" if diff.endswith("\n") else ""), stubbed


# -- the CLI ------------------------------------------------------------------

def _decode(data: bytes) -> str:
    # Byte for byte, both ways: a byte that is not UTF-8 reads the same in
    # the diff and in the blob, and goes back out as it came in.
    return data.decode("utf-8", "surrogateescape")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        usage="git -C <root> diff <A>..<B> [-- <pathspec>...] | "
              "%(prog)s --root <root> <A>..<B>")
    parser.add_argument("--root", default=".",
                        help="the repo the diff was taken in (default: .)")
    parser.add_argument("range", help="the diff's range, <A>..<B>: the old "
                                      "side is read at A, the new at B")
    args = parser.parse_args(argv)
    rev_a, sep, rev_b = args.range.partition("..")
    if not (sep and rev_a and rev_b) or rev_b.startswith(".") or ".." in rev_b:
        parser.error(f"the range must be <A>..<B>, not {args.range!r}")

    def blob(side: str, path: str) -> str:
        rev = rev_a if side == "old" else rev_b
        result = subprocess.run(
            ["git", "-C", args.root, "show", f"{rev}:{path}"],
            capture_output=True)
        if result.returncode != 0:
            why = _decode(result.stderr).strip().splitlines()
            raise RedactionError(
                f"{path} ({side} side): `git show {rev}:{path}` failed"
                + (f" — {why[0]}" if why else ""))
        return _decode(result.stdout)

    try:
        text, _ = redact(_decode(sys.stdin.buffer.read()), blob)
    except RedactionError as e:
        print(f"redact_secrets: {e} — in {args.range} of {args.root} (old = "
              f"{rev_a}, new = {rev_b}); nothing was printed", file=sys.stderr)
        return 3
    sys.stdout.buffer.write(text.encode("utf-8", "surrogateescape"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
