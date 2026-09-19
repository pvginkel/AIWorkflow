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
restored from it. The `Ask:` line goes the same way: it is the session's own
verbatim quote of the card, and it is what `slice.md` later quotes, so it is
checked against the card's text and restored from it too. A real run lost a card's
`TF_VAR_*` that way — the quote came back `TF*VAR*\\*`, this tool reported the item
ok, and the corrupted identifier is what the slice was written against. The
operator's own lines — `Source:`, `Category:`, `Ruling:`, every heading, every word
of the document outside a `**Card text:**` block — are never touched: their prose
is theirs, only the quoted source is ours.

    triage_verbatim.py check   <status.md> <raw.md>
    triage_verbatim.py restore <status.md> <raw.md>

`check` prints one line per item, plus an `ASK` line per fragment of its quote the
card does not carry, and changes nothing. `restore` rewrites the `**Card text:**`
block of every item that differs and every quoted fragment it can place in the
card's text, in place, and leaves the rest of the file byte-identical. Both are
idempotent: a restored document checks clean, and a second restore rewrites nothing.

How the two formats are read:

  * A card's section in the dump runs from its `## KC-NNN — …` or `## #NNN — …`
    line to the next line starting with `## ` (or end of file).
  * An item in the status document is a `### <id> — …` heading; its card-text block
    runs from the line after `**Card text:**` to where the document's own outline
    resumes — the next heading of depth one to three — or end of file. An id is a
    card's id as the tracker writes it — `KC-NNN` or `#NNN` — or that id suffixed
    `a` / `b` when one card yielded several items, all of which share that one
    card's section. Both shapes are read, so a document written across a tracker
    cutover carries both. An id that is not a card id (a findings-document section,
    a running number for a chat passage) is backed by no section: reported `no
    card` and skipped. Every message cites an id as it was written.
  * Demotion adds two `#` to every heading line, capped at six — markdown has no
    seventh level, and a dump's cards sit at depth 3 and deeper, so the cap is a
    guard rather than a case.
  * Headings are read outside fenced code blocks only, in both documents: a `## `
    inside a card's ``` fence is text, not a section boundary, and is not demoted.
  * Leading and trailing blank lines of a block are not significant. Nothing else
    is normalised — trailing whitespace included. The check is verbatim.
  * An item's ask is the line starting `- Ask:` plus the lines under it, up to the
    next `- ` bullet, a blank line or the card-text marker, joined with single
    spaces. An item that carries none is not a format error; it is simply not
    checked for one.
  * That value is read as one quote — with a single outer pair of double quotes,
    straight or curly, taken off — and, if that does not place it, as the pieces
    between straight double quotes, because a session sometimes writes `"a" and
    "b"` and a card's own text may contain quotes. Either reading splits on an
    elision (`…`, `...`, `[…]`, `[...]`) and drops the whitespace and stray quote
    characters at each fragment's ends. A fragment is carried when it is a
    substring of the card's heading line and body — the title is part of the ask —
    with the whitespace of both collapsed, so a quote may wrap where the card does
    not. The card text is the dump's own, undemoted. Of two readings that both
    fail, the one with fewer unplaced fragments is reported.
  * `restore` places a fragment through a canonical form of it and of the card's
    text: backslashes dropped, `*` read as `_`, whitespace runs collapsed — which
    is exactly what the editor's damage costs. What the dump holds there goes back
    into the quote. A fragment that matches nowhere, or in two different shapes,
    is left for the session to settle by hand.

Exit codes: 0 every card-backed item is ok · 1 (`check`) an item differs, a
fragment of its ask is not in the card's text, or its card is missing from the
dump; (`restore`) a fragment of an ask could not be placed · 2 usage or format
error — an unreadable file, a status document with no items, an item with no
`**Card text:**` block. `restore` reports a missing card the same way but still
exits 0: it restored everything it could, and the dump is the thing to fix.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEMOTE_LEVELS = 2
MAX_HEADING_DEPTH = 6

# A card's id, in either of the two shapes a tracker writes: a readable id — a
# project key, a dash and a number — or the bare number. A working document may
# straddle a cutover and carry both, so both are read wherever an id is.
BARE_ID = r"\d+"
READABLE_ID = r"[A-Za-z][A-Za-z0-9]*-\d+"

# `## #703 — …` / `## KC-703 — …` in the dump; `## Card #670 — …` is the older
# hand that some dumps still carry. A readable id is written without the `#`, but
# one is tolerated; a bare number keeps needing it, or every `## 2026 …` heading
# would read as a card. The id is the whole handle — the title is not matched on.
CARD_HEADING_RE = re.compile(
    rf"^##\s+(?:Card\s+)?(?:#({BARE_ID})|#?({READABLE_ID}))(?:\s|$)")

# `### #778 — <short title> — …`, `### KC-778 — …`; the `#` is optional because
# earlier status documents wrote the bare number.
ITEM_HEADING_RE = re.compile(r"^###\s+#?([A-Za-z0-9][A-Za-z0-9._-]*)\s+—\s")

# A card id, optionally suffixed when one card yielded several items (`#472b`,
# `KC-472b` — both of which belong to card `472` and `KC-472` respectively).
CARD_ID_RE = re.compile(rf"^({BARE_ID}|{READABLE_ID})([a-z]?)$")

# An id a message writes bare. Everything else keeps the `#` a bare card number
# has always been cited with — a non-card id (`S2`) included.
READABLE_ITEM_RE = re.compile(rf"^{READABLE_ID}[a-z]?$")

# Where the status document's own outline resumes, and so where a card-text block
# ends: a heading of depth one to three.
OUTLINE_RE = re.compile(r"^#{1,3}(\s|$)")

HEADING_RE = re.compile(r"^(#{1,6})(\s|$)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
CARD_TEXT_MARKER = "**Card text:**"

# The item's ask, and what a session elides out of the middle of it. The quote
# characters are the ones a quote is written with — straight, and the curly pair an
# editor turns them into — trimmed off a fragment's ends, never from inside it.
ASK_RE = re.compile(r"^(\s*)- Ask:\s*(.*)$")
ELISION_RE = re.compile(r"\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.")
QUOTE_CHARS = "\"“”"

# How much of a differing line to show. The corruption this tool exists for hides
# mid-paragraph, so the excerpt is a window around the first differing character
# rather than the head of the line.
EXCERPT_WIDTH = 120


class Precondition(Exception):
    """A usage or format failure — exit 2."""


def cite(item_id: str) -> str:
    """An id the way it was written: `KC-701` stands alone, `701` keeps its `#`."""
    return item_id if READABLE_ITEM_RE.match(item_id) else f"#{item_id}"


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

@dataclass
class Card:
    """One card's section of the dump: its `## <id> — <title>` heading line, which
    only an ask reads — the title is part of what a card asks for — and the body,
    which is what the status document inlines."""

    heading: str
    body: list[str]


def parse_raw(lines: list[str]) -> dict[str, Card]:
    """Card id → its section: the `## <id> — …` heading and every line after it, up
    to the next `## ` line. Demotion is not applied here — the section is the
    archive's own text, and only the card-text comparison sees the demoted form."""
    in_code = fenced(lines)
    starts: list[tuple[int, str | None]] = []
    for i, line in enumerate(lines):
        if in_code[i] or not line.startswith("## "):
            continue
        m = CARD_HEADING_RE.match(line)
        # One group per id shape; whichever matched is the id.
        starts.append((i, (m.group(1) or m.group(2)) if m else None))

    cards: dict[str, Card] = {}
    for k, (i, card) in enumerate(starts):
        if card is None:
            continue
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        # A card filed twice in one dump: the first section wins, so a re-fetch
        # appended at the end cannot silently redefine what was already checked.
        cards.setdefault(card, Card(heading=lines[i], body=lines[i + 1:end]))
    return cards


# ---------------------------------------------------------------------------
# The status document
# ---------------------------------------------------------------------------

@dataclass
class Ask:
    """One item's `- Ask:` value: the lines it occupies (0-based, end exclusive),
    the indentation its line carries, and the value itself — the continuation lines
    joined on with single spaces."""

    line: int
    end: int
    indent: str
    value: str


@dataclass
class Item:
    """One item block, by line index into the status document (0-based, end
    exclusive); `start`/`end` bound its card-text block alone, and `ask` is the
    quote above it, which not every item carries."""

    item_id: str
    card: str | None
    heading: int
    start: int
    end: int
    ask: Ask | None = None


def parse_ask(lines: list[str], start: int, end: int) -> Ask | None:
    """The `- Ask:` value between `start` and `end` — the item's heading and its
    card-text marker — or None for an item that carries no ask."""
    for i in range(start, end):
        m = ASK_RE.match(lines[i])
        if not m:
            continue
        parts = [m.group(2).strip()]
        k = i + 1
        # The value wraps until the block's next bullet or a blank line; the marker
        # stops it too, being where this range ends.
        while k < end and lines[k].strip() and not lines[k].strip().startswith("- "):
            parts.append(lines[k].strip())
            k += 1
        return Ask(line=i, end=k, indent=m.group(1),
                   value=" ".join(p for p in parts if p))
    return None


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
                f"item {cite(item_id)} (line {i + 1}) has no `{CARD_TEXT_MARKER}` block — "
                "either the document drifted from the item shape or this heading is "
                "not an item")
        card_match = CARD_ID_RE.match(item_id)
        items.append(Item(item_id=item_id,
                          card=card_match.group(1) if card_match else None,
                          heading=i, start=marker + 1, end=end,
                          ask=parse_ask(lines, i + 1, marker)))
    if not items:
        raise Precondition(
            "no items found — a status document holds `### <id> — <title>` "
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
    # The item's ask, judged apart from its card text: the fragments the card does
    # not carry, and — after a restore — which of them went back and which did not.
    ask_line: int = 0       # 1-based line of the `- Ask:` line
    ask_missing: list[str] = field(default_factory=list)
    ask_restored: bool = False
    ask_unrestorable: list[str] = field(default_factory=list)


NOTHING = "(end of block)"


def _window(s: str, start: int) -> str:
    """`s` from `start`, EXCERPT_WIDTH wide, with an ellipsis for each end cut off."""
    piece = s[start:start + EXCERPT_WIDTH]
    return ("…" if start else "") + piece + ("…" if start + EXCERPT_WIDTH < len(s) else "")


def _excerpt(a: str, b: str) -> tuple[str, str]:
    """The two lines, windowed on the first character that differs — the escape this
    tool hunts sits mid-paragraph, and the head of the line would not show it."""
    if max(len(a), len(b)) <= EXCERPT_WIDTH:
        return a, b
    j = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]),
             min(len(a), len(b)))
    start = max(0, j - EXCERPT_WIDTH // 2)
    return _window(a, start), _window(b, start)


def _collapse(text: str) -> str:
    """Whitespace runs as one space: a quote may wrap where the card does not."""
    return re.sub(r"\s+", " ", text)


def searchable(card: Card) -> str:
    """What an ask may quote: the card's heading line and its body, as the dump
    writes them. Undemoted — the quote was taken from the dump, not from the copy
    the status document inlines."""
    return "\n".join([card.heading, *card.body])


def _fragments(value: str) -> list[str]:
    """What a quote actually claims: the pieces its elisions leave, each without the
    whitespace and the stray quote characters at its ends."""
    pieces = (piece.strip().strip(QUOTE_CHARS).strip()
              for piece in ELISION_RE.split(value))
    return [piece for piece in pieces if piece]


def _unquote(value: str) -> str:
    """One outer pair of double quotes off. Only the outer pair: a card's own text
    may contain quotes, and the whole value is read as one quote first."""
    if len(value) > 1 and value[0] in QUOTE_CHARS and value[-1] in QUOTE_CHARS:
        return value[1:-1]
    return value


def ask_missing(value: str, card: Card) -> list[str]:
    """The fragments of an ask the card's text does not carry — empty when it does.

    Two readings, in order: the value as one quote, and the pieces between straight
    double quotes, which is what a session writes when it quotes twice in a sentence
    of its own (`"a" and "b"`). Of two readings that both fail, the one with fewer
    unplaced fragments is the one to report — a tie goes to the first, which is the
    shape the format asks for.
    """
    text = _collapse(searchable(card))

    def unplaced(fragments: list[str]) -> list[str]:
        return [f for f in fragments if _collapse(f) not in text]

    missing = unplaced(_fragments(_unquote(value)))
    if not missing:
        return []
    pieces = [f for part in value.split('"')[1::2] for f in _fragments(part)]
    if pieces:
        quoted = unplaced(pieces)
        if not quoted:
            return []
        if len(quoted) < len(missing):
            return quoted
    return missing


def compare(item: Item, status: list[str], cards: dict[str, Card]) -> Result:
    """One item's verdict: where its card text first differs, and which fragments of
    its ask the card does not carry."""
    if item.card is None:
        return Result(item.item_id, "no card")
    if item.card not in cards:
        return Result(item.item_id, "missing in raw")

    result = _compare_card_text(item, status, cards[item.card])
    if item.ask is not None:
        result.ask_line = item.ask.line + 1
        result.ask_missing = ask_missing(item.ask.value, cards[item.card])
    return result


def _compare_card_text(item: Item, status: list[str], card: Card) -> Result:
    """The inlined card text against the dump's, verbatim."""
    have = strip_blanks(status[item.start:item.end])
    want = strip_blanks(demote(card.body))
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
    item = cite(result.item_id)
    if result.verdict != "diff":
        return f"{item}  {result.verdict}"
    if restored:
        return f"{item}  restored"
    return (f"{item}  DIFF  line {result.line}: {result.status_text}"
            f"  ≠  {result.raw_text}")


def format_ask(result: Result, restored: bool = False) -> list[str]:
    """The item's ask lines, which follow its card-text line: one per fragment the
    card does not carry, and on a restore the one line that says they went back."""
    item = cite(result.item_id)
    if not restored:
        return [f"{item}  ASK  line {result.ask_line}: {_window(f, 0)}"
                "  ≠  not in the card's text" for f in result.ask_missing]
    lines = [f"{item}  ask restored"] if result.ask_restored else []
    return lines + [f"{item}  ASK unrestorable  line {result.ask_line}: {_window(f, 0)}"
                    for f in result.ask_unrestorable]


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def check(status_path: Path, raw_path: Path) -> tuple[list[Result], int]:
    """Every item's verdict, plus the exit code."""
    status = read_lines(status_path)
    cards = parse_raw(read_lines(raw_path))
    results = [compare(item, status, cards) for item in parse_status(status)]
    bad = any(r.verdict in ("diff", "missing in raw") or r.ask_missing
              for r in results)
    return results, 1 if bad else 0


def _canonicalise(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`text` in the form the editor's damage leaves comparable — backslashes
    dropped, `*` read as `_`, whitespace runs one space — with the span of `text`
    each canonical character came from, so a match reads back as the original."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 1
            continue
        if text[i].isspace():
            k = i
            while k < len(text) and text[k].isspace():
                k += 1
            out.append(" ")
            spans.append((i, k))
            i = k
            continue
        out.append("_" if text[i] == "*" else text[i])
        spans.append((i, i + 1))
        i += 1
    return "".join(out), spans


def locate(fragment: str, card: Card) -> str | None:
    """What the dump holds where the status document holds `fragment` — or None
    when the two do not meet canonically, or meet in two different shapes and only
    the session can say which was quoted."""
    text = searchable(card)
    canonical, spans = _canonicalise(text)
    needle, _ = _canonicalise(fragment)
    if not needle:
        return None
    seen = set()
    at = canonical.find(needle)
    while at != -1:
        start, end = spans[at][0], spans[at + len(needle) - 1][1]
        seen.add(_collapse(text[start:end]))
        at = canonical.find(needle, at + 1)
    return seen.pop() if len(seen) == 1 else None


def _restore_card_text(item: Item, status: list[str], out: list[str],
                       card: Card) -> None:
    """The item's card-text block, back to the dump's own text."""
    block = status[item.start:item.end]
    body = strip_blanks(demote(card.body))
    lead = next((k for k, line in enumerate(block) if line.strip()), len(block))
    tail = next((k for k, line in enumerate(reversed(block)) if line.strip()), 0)
    if lead == len(block):
        # The block held nothing but blanks, or nothing at all — an item whose card
        # text was lost. There is no padding to keep, so pad it the way the shape
        # does: a blank line each side, and none past end of file.
        head = [""]
        foot = [""] if item.end < len(status) else []
    else:
        head = block[:lead]
        foot = block[len(block) - tail:] if tail else []
    out[item.start:item.end] = head + body + foot


def _restore_ask(item: Item, result: Result, status: list[str],
                 card: Card) -> list[str] | None:
    """The lines the item's ask becomes, once every fragment that can be placed in
    the card's text is back — or None when none of them could be.

    A one-line ask is edited in place, so the rest of the line keeps its bytes; an
    ask that wrapped is rewritten as the one `- Ask:` line the format asks for.
    Fragments that could not be placed are left as they are and recorded on the
    result: the line needs the session's hand, and this tool would only guess.
    """
    placed = [(f, locate(f, card)) for f in result.ask_missing]
    result.ask_unrestorable = [f for f, original in placed if original is None]
    repairs = [(f, original) for f, original in placed if original is not None]
    if not repairs:
        return None
    result.ask_restored = True
    ask = item.ask
    if ask.end == ask.line + 1:
        line = status[ask.line]
        for fragment, original in repairs:
            line = line.replace(fragment, original, 1)
        return [line]
    value = ask.value
    for fragment, original in repairs:
        value = value.replace(fragment, original, 1)
    return [f"{ask.indent}- Ask: {value}"]


def restore(status_path: Path, raw_path: Path) -> list[Result]:
    """Rewrite every differing card-text block, and every misquoted ask fragment,
    from the dump, in place.

    Only the block's body is replaced; the blank lines that pad it are kept exactly
    as they were, so the bytes outside `**Card text:**` blocks and the asks that
    differ do not move. Items that already match are not rewritten at all.
    """
    status = read_lines(status_path)
    cards = parse_raw(read_lines(raw_path))
    items = parse_status(status)
    results = [compare(item, status, cards) for item in items]

    out = list(status)
    # Back to front, so an earlier item's rewrite cannot shift a later item's
    # bounds; within an item, the card text before the ask above it, for the same
    # reason.
    for item, result in reversed(list(zip(items, results, strict=True))):
        if result.verdict == "diff":
            _restore_card_text(item, status, out, cards[item.card])
        if result.ask_missing:
            lines = _restore_ask(item, result, status, cards[item.card])
            if lines is not None:
                out[item.ask.line:item.ask.end] = lines

    if out != status:
        status_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb, help_text in (("check", "report each item's card text and ask against the dump"),
                            ("restore", "rewrite every differing card text and ask from the dump")):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("status", help="the status document, triage_YYYY-MM-DD.md")
        p.add_argument("raw", help="the raw dump, triage_YYYY-MM-DD_raw.md")
    args = parser.parse_args(argv)

    restored = args.verb == "restore"
    try:
        if restored:
            results = restore(Path(args.status), Path(args.raw))
            # A restore answers for what it could not place, and for nothing else:
            # a missing card stays the dump's problem, and exits 0.
            code = 1 if any(r.ask_unrestorable for r in results) else 0
        else:
            results, code = check(Path(args.status), Path(args.raw))
    except Precondition as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for result in results:
        print(format_result(result, restored=restored))
        for line in format_ask(result, restored=restored):
            print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
