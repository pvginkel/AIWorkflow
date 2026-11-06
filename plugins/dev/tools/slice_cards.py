#!/usr/bin/env python3
"""Check that every card a slice.md embeds is whole — /dev:triage step 7 runs it
over the slices it has just filed, before it commits, with the run's committed
raw dump (`<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md`).

Triage copies each card it files into the slice's slice.md. When the copy wrapped
a card's body in a ``` fence, a fence or a `### B9 — …` heading inside the body
broke the nesting, and PilotAppSpecs slice 023 lost most of one card and all of
another without anyone noticing. The tool has no tracker access, so the dump is
the reference: "whole" means the slice's copy matches the dump's.

Both files embed a card the same way: a column-0 `### <ID> — <title>` heading
(an em dash, a single space either side), then the card's whole body — marks,
description, comments — as ONE blockquote, `> ` before every line and `>` alone
for a blank one. The card's section runs to the next column-0 heading of any
level; inside the blockquote a heading or a fence is only text. Other `###`
headings (`### Plan row 012`) are not cards and are passed over.

For each card a slice.md embeds it reports a card outside its blockquote or in
two, one missing from the dump, one the dump itself holds broken or twice over
differently, and a title or body that differs from the dump's — the body by its
first differing line. Bodies compare with each line's `>` and one space after it
dropped, trailing whitespace ignored and the blank lines at either end trimmed.
Cards of the dump no slice embeds are not checked.

Usage:
    slice_cards.py <dump.md> <slice_dir> [<slice_dir> ...]

Exit codes: 0 every embedded card whole in every slice · 2 a card not whole, or
a usage error (the dump missing, a slice dir with no slice.md) · 1 unexpected
error. Every slice dir is reported before the exit code is decided.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CARD_RE = re.compile(r"^### (?P<id>[A-Z][A-Z0-9]*-\d+) — (?P<title>.*\S)\s*$")
HEADING_RE = re.compile(r"^#{1,6}(\s|$)")

EVERY_LINE = "every line of the card starts with `>`, a blank one too"
OUTSIDE = f"this line is outside the card's blockquote — {EVERY_LINE}"
NO_QUOTE = f"no blockquote — {EVERY_LINE}, and none here does"
SPLIT = ("a blank line splits the card's blockquote in two — a blank line of the card "
         "is `>` alone")
EMPTY = "no blockquote — nothing under the heading"
SHORTEN_AT = 80


class Usage(Exception):
    """A usage problem — exit 2."""


@dataclass(frozen=True)
class Card:
    """One card section. `body` is normalized; `numbers` holds each body line's
    1-based line in its file. A structural defect leaves the body unread."""

    id: str
    title: str
    line: int
    body: tuple[str, ...] = ()
    numbers: tuple[int, ...] = ()
    defect: str | None = None
    defect_line: int | None = None


def unquote(line: str) -> str:
    """A blockquote line's text: the `>`, then one space if present, dropped."""
    text = line[1:]
    if text.startswith(" "):
        text = text[1:]
    return text.rstrip()


def read_card(match: re.Match, lines: list[str], start: int, end: int) -> Card:
    """The card whose heading is lines[start], its section ending before end."""
    card = {"id": match.group("id"), "title": match.group("title").rstrip(),
            "line": start + 1}
    quoted = any(lines[index].startswith(">") for index in range(start + 1, end))
    body: list[tuple[int, str]] = []
    state = "before"  # before the blockquote, in it, or after it
    blank_at = None
    for index in range(start + 1, end):
        line = lines[index]
        if line.startswith(">"):
            if state == "after":
                return Card(**card, defect=SPLIT, defect_line=blank_at)
            state = "in"
            body.append((index + 1, unquote(line)))
        elif not line.strip():
            if state == "in":
                state, blank_at = "after", index + 1
        else:
            return Card(**card, defect=OUTSIDE if quoted else NO_QUOTE,
                        defect_line=index + 1)
    if not body:
        return Card(**card, defect=EMPTY, defect_line=start + 1)
    while body and not body[0][1]:
        body.pop(0)
    while body and not body[-1][1]:
        body.pop()
    return Card(**card, body=tuple(text for _, text in body),
                numbers=tuple(number for number, _ in body))


def parse_cards(text: str) -> list[Card]:
    """Every card section of a file, in document order. Split on newlines alone,
    so a line number is the one an editor shows."""
    lines = text.split("\n")
    cards = []
    index = 0
    while index < len(lines):
        match = CARD_RE.match(lines[index])
        if not match:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not HEADING_RE.match(lines[end]):
            end += 1
        cards.append(read_card(match, lines, index, end))
        index = end
    return cards


def shorten(text: str) -> str:
    return text if len(text) <= SHORTEN_AT else text[:SHORTEN_AT - 1] + "…"


def show(lines: tuple[str, ...], index: int) -> str:
    if index >= len(lines):
        return "(missing)"
    return f'"{shorten(lines[index])}"' if lines[index] else "(blank)"


def at(line: int) -> str:
    return f"slice.md line {line}"


def body_defect(dump: Card, card: Card) -> tuple[str, str] | None:
    """The first body line where the slice's copy parts from the dump's, as a
    message and where in slice.md it is; None when the bodies match."""
    if dump.body == card.body:
        return None
    index = next((i for i, (a, b) in enumerate(zip(dump.body, card.body, strict=False))
                  if a != b), min(len(dump.body), len(card.body)))
    if index < len(card.numbers):
        where = at(card.numbers[index])
    else:  # slice.md's copy ran out: point past its last line
        where = f"after {at(card.numbers[-1] if card.numbers else card.line)}"
    message = (f"body differs from the dump's at its line {index + 1} (the dump's copy has "
               f"{len(dump.body)} lines, slice.md's {len(card.body)}): the dump has "
               f"{show(dump.body, index)}, slice.md {show(card.body, index)}")
    return message, where


def card_defect(card: Card, dump: dict[str, list[Card]]) -> tuple[str, str | None] | None:
    """What keeps one embedded card from being whole: a message and where in
    slice.md it points (None when it points into the dump); None for a whole card."""
    if card.defect:
        return card.defect, at(card.defect_line)
    copies = dump.get(card.id)
    if not copies:
        return "not in the dump", at(card.line)
    broken = next((copy for copy in copies if copy.defect), None)
    if broken:
        return (f"the dump's copy is not whole itself: {broken.defect} "
                f"(dump line {broken.defect_line})", None)
    if len({(copy.title, copy.body) for copy in copies}) > 1:
        lines = ", ".join(str(copy.line) for copy in copies)
        return f"the dump holds it {len(copies)} times, not alike (dump lines {lines})", None
    reference = copies[0]
    if reference.title != card.title:
        return (f'title differs from the dump\'s: the dump has "{shorten(reference.title)}", '
                f'slice.md "{shorten(card.title)}"', at(card.line))
    return body_defect(reference, card)


def say(line: str) -> None:
    """A stdout line, flushed so it keeps its place among the stderr ones."""
    print(line, flush=True)


def check_slice(slice_dir: Path, dump: dict[str, list[Card]]) -> bool:
    """Report one slice dir; True when every card it embeds is whole."""
    name = slice_dir.resolve().name
    slice_md = slice_dir / "slice.md"
    if not slice_md.is_file():
        print(f"{name}: no slice.md in {slice_dir}", file=sys.stderr)
        return False
    cards = parse_cards(slice_md.read_text(encoding="utf-8"))
    if not cards:
        say(f"{name}: no card embedded")
        return True
    failed = 0
    for card in cards:
        defect = card_defect(card, dump)
        if defect is None:
            continue
        failed += 1
        message, where = defect
        print(f"{name}: {card.id}: {message}" + (f" ({where})" if where else ""),
              file=sys.stderr)
    if failed:
        say(f"{name}: {failed} of {len(cards)} cards not whole")
        return False
    ids = ", ".join(card.id for card in cards)
    say(f"{name}: {len(cards)} card{'' if len(cards) == 1 else 's'} whole ({ids})")
    return True


def load_dump(path: Path) -> dict[str, list[Card]]:
    """The dump's cards by id — a list, since a dump may hold one twice."""
    if not path.is_file():
        raise Usage(f"dump not found: {path}")
    cards: dict[str, list[Card]] = {}
    for card in parse_cards(path.read_text(encoding="utf-8")):
        cards.setdefault(card.id, []).append(card)
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check every card a slice.md embeds against the triage dump's copy.")
    parser.add_argument("dump", help="the triage run's committed raw dump, "
                                     "<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md")
    parser.add_argument("slice_dir", nargs="+", help="a slice folder holding slice.md")
    args = parser.parse_args(argv)
    try:
        dump = load_dump(Path(args.dump))
        results = [check_slice(Path(raw), dump) for raw in args.slice_dir]
    except Usage as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # anything unexpected is exit 1 by contract
        print(f"slice_cards failed: {exc}", file=sys.stderr)
        return 1
    return 0 if all(results) else 2


if __name__ == "__main__":
    sys.exit(main())
