#!/usr/bin/env python3
"""Keep a triage status document's inlined card text verbatim against the raw dump.

/dev:triage lands two working documents in the project's spec repo under
`handovers/` (${CLAUDE_PLUGIN_ROOT}/skills/triage/SKILL.md, step 1-2):

  triage_YYYY-MM-DD_raw.md   the dump — every card whole and verbatim, the archive
  triage_YYYY-MM-DD.md       the status document — one block per item, which the
                             operator rules on by writing on its `Ruling:` line

The status document inlines each card's text under `**Card text:**` so the operator
reads without looking anything up, with the source's headings demoted by two levels
so they don't collide with the document's own outline. That inlined copy is what a
slice later quotes as its source material — so it has to stay byte-identical to the
dump, and it doesn't: the operator rules by editing the file, and their editor
escapes markdown on save. `_is_stuck` comes back `\\_is_stuck`; worse,
`KUBECODER_CLIENT_TOKEN_<NAME>` comes back `KUBECODER*CLIENT_TOKEN*<NAME>` — a pair
of underscores eaten as emphasis, silently turning an identifier into a different
identifier. Nothing downstream can tell; the corruption rides into `slice.md` and
then into code.

So after every operator pass, the inlined text is checked against the dump and
restored from it. The operator's own lines — `Source:`, `Ask:`, `Category:`,
`Ruling:`, every heading, every word of the document outside a `**Card text:**`
block — are never touched: their prose is theirs, only the quoted source is ours.

    triage_verbatim.py check   <status.md> <raw.md>
    triage_verbatim.py restore <status.md> <raw.md>

`check` prints one line per item and changes nothing. `restore` rewrites the
`**Card text:**` block of every item that differs, in place, and leaves the rest of
the file byte-identical. Both are idempotent: a restored document checks clean, and
a second restore rewrites nothing.

How the two formats are read:

  * A card's section in the dump runs from its `## #NNN — …` line to the next
    line starting with `## ` (or end of file).
  * An item in the status document is a `### <id> — …` heading; its card-text block
    runs from the line after `**Card text:**` to where the document's own outline
    resumes — the next heading of depth one to three — or end of file. Ids are
    `#NNN`, or `#NNNa` / `#NNNb` when one card
    yielded several items — all of which share card `#NNN`'s section. An id that is
    not a card number (a findings-document section, a running number for a chat
    passage) is backed by no section: reported `no card` and skipped.
  * Demotion adds two `#` to every heading line, capped at six — markdown has no
    seventh level, and a dump's cards sit at depth 3 and deeper, so the cap is a
    guard rather than a case.
  * Headings are read outside fenced code blocks only, in both documents: a `## `
    inside a card's ``` fence is text, not a section boundary, and is not demoted.
  * Leading and trailing blank lines of a block are not significant. Nothing else
    is normalised — trailing whitespace included. The check is verbatim.

Exit codes: 0 every card-backed item is ok · 1 (`check`) an item differs or its card
is missing from the dump · 2 usage or format error — an unreadable file, a status
document with no items, an item with no `**Card text:**` block. `restore` reports a
missing card the same way but still exits 0: it restored everything it could, and
the dump is the thing to fix.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEMOTE_LEVELS = 2
MAX_HEADING_DEPTH = 6

# `## #703 — …` in the dump; `## Card #670 — …` is the older hand that some dumps
# still carry. The number is the whole handle — the title is not matched on.
CARD_HEADING_RE = re.compile(r"^##\s+(?:Card\s+)?#(\d+)(?:\s|$)")

# `### #778 — <short title> — <url>`; the `#` is optional because earlier status
# documents wrote the bare number.
ITEM_HEADING_RE = re.compile(r"^###\s+#?([A-Za-z0-9][A-Za-z0-9._-]*)\s+—\s")

# A card number, optionally suffixed when one card yielded several items (`#472b`).
CARD_ID_RE = re.compile(r"^(\d+)([a-z]?)$")

# Where the status document's own outline resumes, and so where a card-text block
# ends: a heading of depth one to three.
OUTLINE_RE = re.compile(r"^#{1,3}(\s|$)")

HEADING_RE = re.compile(r"^(#{1,6})(\s|$)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
CARD_TEXT_MARKER = "**Card text:**"

# How much of a differing line to show. The corruption this tool exists for hides
# mid-paragraph, so the excerpt is a window around the first differing character
# rather than the head of the line.
EXCERPT_WIDTH = 120


class Precondition(Exception):
    """A usage or format failure — exit 2."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_lines(path: Path) -> list[str]:
    """A document as lines, without the trailing empty one `split` leaves.

    `split("\\n")` rather than `splitlines()` on purpose: splitlines also breaks on
    form feed and U+2028, which a verbatim card body is entitled to contain.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise Precondition(f"cannot read {path}: {e}") from e
    except UnicodeDecodeError as e:
        raise Precondition(f"{path} is not UTF-8: {e}") from e
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def fenced(lines: list[str]) -> list[bool]:
    """Per line, whether it sits inside a fenced code block (delimiters included).

    Both documents are scanned through this, so a `## ` or a `### ` a card quotes
    inside a fence moves no boundary and takes no demotion.
    """
    out, inside = [], False
    for line in lines:
        if FENCE_RE.match(line):
            out.append(True)
            inside = not inside
        else:
            out.append(inside)
    return out


def demote(lines: list[str], levels: int = DEMOTE_LEVELS) -> list[str]:
    """Every heading line down `levels`, capped at six. Everything else as-is."""
    out = []
    for line, in_code in zip(lines, fenced(lines), strict=True):
        m = None if in_code else HEADING_RE.match(line)
        if m:
            depth = min(len(m.group(1)) + levels, MAX_HEADING_DEPTH)
            out.append("#" * depth + line[len(m.group(1)):])
        else:
            out.append(line)
    return out


def strip_blanks(lines: list[str]) -> list[str]:
    """A block without its leading and trailing blank lines."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


# ---------------------------------------------------------------------------
# The dump
# ---------------------------------------------------------------------------

def parse_raw(lines: list[str]) -> dict[str, list[str]]:
    """Card number → the section's body: every line after its `## #NNN — …` heading,
    up to the next `## ` line. Demotion is not applied here — the body is the
    archive's own text, and only the comparison sees the demoted form."""
    in_code = fenced(lines)
    starts: list[tuple[int, str | None]] = []
    for i, line in enumerate(lines):
        if in_code[i] or not line.startswith("## "):
            continue
        m = CARD_HEADING_RE.match(line)
        starts.append((i, m.group(1) if m else None))

    cards: dict[str, list[str]] = {}
    for k, (i, number) in enumerate(starts):
        if number is None:
            continue
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        # A card filed twice in one dump: the first section wins, so a re-fetch
        # appended at the end cannot silently redefine what was already checked.
        cards.setdefault(number, lines[i + 1:end])
    return cards


# ---------------------------------------------------------------------------
# The status document
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """One item block, by line index into the status document (0-based, end
    exclusive); `start`/`end` bound its card-text block alone."""

    item_id: str
    card: str | None
    heading: int
    start: int
    end: int


def parse_status(lines: list[str]) -> list[Item]:
    """Every item block in document order."""
    in_code = fenced(lines)

    def structural(i: int) -> bool:
        # The document's own outline: any heading of depth one to three. Demoted
        # card text starts at depth three, so only `### ` is ambiguous, and that
        # ambiguity is the format's, not this parser's.
        return not in_code[i] and OUTLINE_RE.match(lines[i]) is not None

    heads = [(i, m) for i, line in enumerate(lines)
             if structural(i) and (m := ITEM_HEADING_RE.match(line))]

    items = []
    for i, m in heads:
        item_id = m.group(1)
        # The block ends where the document's outline resumes.
        end = len(lines)
        for k in range(i + 1, len(lines)):
            if structural(k):
                end = k
                break
        marker = None
        for k in range(i + 1, end):
            if lines[k].strip() == CARD_TEXT_MARKER:
                marker = k
                break
        if marker is None:
            raise Precondition(
                f"item #{item_id} (line {i + 1}) has no `{CARD_TEXT_MARKER}` block — "
                "either the document drifted from the item shape or this heading is "
                "not an item")
        card_match = CARD_ID_RE.match(item_id)
        items.append(Item(item_id=item_id,
                          card=card_match.group(1) if card_match else None,
                          heading=i, start=marker + 1, end=end))
    if not items:
        raise Precondition(
            "no items found — a status document holds `### <id> — <title> — <url>` "
            "blocks; this file is not one, or the arguments are the wrong way round")
    return items


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

@dataclass
class Result:
    item_id: str
    verdict: str            # ok | diff | no card | missing in raw
    line: int = 0           # 1-based line in the status document
    status_text: str = ""
    raw_text: str = ""


NOTHING = "(end of block)"


def _excerpt(a: str, b: str) -> tuple[str, str]:
    """The two lines, windowed on the first character that differs — the escape this
    tool hunts sits mid-paragraph, and the head of the line would not show it."""
    if max(len(a), len(b)) <= EXCERPT_WIDTH:
        return a, b
    j = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
             min(len(a), len(b)))
    start = max(0, j - EXCERPT_WIDTH // 2)

    def window(s: str) -> str:
        piece = s[start:start + EXCERPT_WIDTH]
        return ("…" if start else "") + piece + ("…" if start + EXCERPT_WIDTH < len(s) else "")

    return window(a), window(b)


def compare(item: Item, status: list[str], cards: dict[str, list[str]]) -> Result:
    """One item's verdict, and where it first differs."""
    if item.card is None:
        return Result(item.item_id, "no card")
    if item.card not in cards:
        return Result(item.item_id, "missing in raw")

    have = strip_blanks(status[item.start:item.end])
    want = strip_blanks(demote(cards[item.card]))
    # The first line index at which they part; the offset back to the document is
    # the block's start plus the leading blanks the strip took off.
    offset = item.start + next(
        (k for k, line in enumerate(status[item.start:item.end]) if line.strip()), 0)
    for k in range(max(len(have), len(want))):
        a = have[k] if k < len(have) else None
        b = want[k] if k < len(want) else None
        if a == b:
            continue
        shown_a, shown_b = _excerpt(a or "", b or "")
        return Result(item.item_id, "diff", line=offset + k + 1,
                      status_text=NOTHING if a is None else shown_a,
                      raw_text=NOTHING if b is None else shown_b)
    return Result(item.item_id, "ok")


def format_result(result: Result, restored: bool = False) -> str:
    if result.verdict != "diff":
        return f"#{result.item_id}  {result.verdict}"
    if restored:
        return f"#{result.item_id}  restored"
    return (f"#{result.item_id}  DIFF  line {result.line}: {result.status_text}"
            f"  ≠  {result.raw_text}")


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def check(status_path: Path, raw_path: Path) -> tuple[list[Result], int]:
    """Every item's verdict, plus the exit code."""
    status = read_lines(status_path)
    cards = parse_raw(read_lines(raw_path))
    results = [compare(item, status, cards) for item in parse_status(status)]
    bad = any(r.verdict in ("diff", "missing in raw") for r in results)
    return results, 1 if bad else 0


def restore(status_path: Path, raw_path: Path) -> list[Result]:
    """Rewrite every differing card-text block from the dump, in place.

    Only the block's body is replaced; the blank lines that pad it are kept exactly
    as they were, so the bytes outside `**Card text:**` blocks do not move. Items
    that already match are not rewritten at all.
    """
    status = read_lines(status_path)
    cards = parse_raw(read_lines(raw_path))
    items = parse_status(status)
    results = [compare(item, status, cards) for item in items]

    out = list(status)
    # Back to front, so an earlier item's rewrite cannot shift a later item's bounds.
    for item, result in reversed(list(zip(items, results, strict=True))):
        if result.verdict != "diff":
            continue
        block = status[item.start:item.end]
        body = strip_blanks(demote(cards[item.card]))
        lead = next((k for k, line in enumerate(block) if line.strip()), len(block))
        tail = next((k for k, line in enumerate(reversed(block)) if line.strip()), 0)
        if lead == len(block):
            # The block held nothing but blanks, or nothing at all — an item whose
            # card text was lost. There is no padding to keep, so pad it the way
            # the shape does: a blank line each side, and none past end of file.
            head = [""]
            foot = [""] if item.end < len(status) else []
        else:
            head = block[:lead]
            foot = block[len(block) - tail:] if tail else []
        out[item.start:item.end] = head + body + foot

    if out != status:
        status_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb, help_text in (("check", "report each item's card text against the dump"),
                            ("restore", "rewrite every differing card text from the dump")):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("status", help="the status document, triage_YYYY-MM-DD.md")
        p.add_argument("raw", help="the raw dump, triage_YYYY-MM-DD_raw.md")
    args = parser.parse_args(argv)

    restored = args.verb == "restore"
    try:
        if restored:
            results, code = restore(Path(args.status), Path(args.raw)), 0
        else:
            results, code = check(Path(args.status), Path(args.raw))
    except Precondition as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for result in results:
        print(format_result(result, restored=restored))
    return code


if __name__ == "__main__":
    sys.exit(main())
