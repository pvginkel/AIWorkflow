#!/usr/bin/env python3
"""The close-out report's mechanics — create, append, note, strike, list, render, stamp, count.

`<slice>/close-out.md` is the one document every plan and run agent writes
its out-of-scope observations to (${CLAUDE_PLUGIN_ROOT}/docs/close-out.md is
the contract; docs/close-out-template.md the shape). Every writer goes
through this tool — the shape is mechanical, the content is judgment — and
nobody edits the file by hand; importable by both loops (the way plan_loop
imports run_loop) and a CLI for the agents and the skills:

  init   create close-out.md from the template if absent — the title takes
         the slice's `NNN <slug>`; an existing file is never touched.
  append add one entry to a section: the next id from the section's letter
         (struck headings count), the standard entry shape — body, then the
         three bold labels `**Consequence:**` (required: the line the operator
         triages on), `**Provenance:**`, and a blank `**Disposition:**`.
         Prints the id.
  note   add a dated paragraph `<who>, <date> — <text>` at the end of one
         entry's body — above its `**Consequence:**` line (an old-shape entry
         without one: above `Provenance:`, else `Disposition:`, else at the
         end); a struck entry takes it inside its fold. Never a new entry.
  strike rewrite one live entry's heading to the struck form —
         `### ~~B3 — <rest>~~ — <reason>[; struck by <who>]`. The body stays;
         a struck entry needs no disposition. Prints the new heading.
  list   the triage view, without bodies: per section its `## name`, then per
         entry `B3 — <heading rest>` with its Consequence text under it
         (`~~B3~~ — …` for a struck one), in file order.
  render put every entry section in reading order, in place and idempotently:
         live entries first (Bugs by severity major → minor → nit → cosmetic,
         then ungraded; other sections by id), then `###` headings not in the
         entry shape as they were, then struck entries by id — each with its
         body folded once into `<details>` so the live ones lead. The section
         preamble (Focus line, charter), the head comment, the Run header
         and the Summary are not touched. Prints live/struck per section.
  stamp  replace the `Run:` header block with the run's shape read from
         state.json — window, phases planned/appended, bail-outs, test
         rounds, doc phase, and the `cost` block once slice_cost.py
         --write-state has run. Missing pieces are omitted, not guessed;
         re-stamping overwrites the same block.
  counts non-struck entries per section, one line — plus, when there are
         any, the number of `###` headings in the entry sections that are
         not in the entry shape (an author that drifted from the shape,
         which would otherwise count as zero entries) and the number of
         live entries without a `Consequence:` or a `Provenance:` line
         (bold or not — the check is for the content, not the typography).

Headings are read outside fenced code blocks and outside HTML comments
only — an entry that quotes a document's `## Bugs` or a `### B3` inside a
``` fence (the entry rules ask for liberal quoting) neither moves a section
boundary nor shifts an id, and the template's own head comment shows the
entry shape with a `### B2 — …` line in it.

Deliberately not here: any validation beyond "the section heading exists"
and those smoke counts, dedup, disposition parsing.

Usage:
    close_out.py init <slice-dir>
    close_out.py append <slice-dir> --section <name> --headline <text>
                 --body <text | -> --consequence <text>
                 [--provenance <text>] [--severity <s>]
    close_out.py note <slice-dir> <id> --by <who> --text <text | ->
                 [--date YYYY-MM-DD]
    close_out.py strike <slice-dir> <id> --reason <text> [--by <who>]
    close_out.py list <slice-dir>
    close_out.py render <slice-dir>
    close_out.py stamp <slice-dir>
    close_out.py counts <slice-dir>

Exit codes: 0 ok · 2 usage/precondition error.
"""

import argparse
import json
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

REPORT_NAME = "close-out.md"

# This file, resolved — the driver runs from the installed plugin clone, so
# a dispatch that names it names the copy that will run.
TOOL_PATH = Path(__file__).resolve()

# The one sentence every dispatch carries about the report: where it is and
# that this tool is the only way to write to it. Both loops use it as-is.
DISPATCH_LINE = """\
The slice's close-out report is {report}. Write to it only through
`python3 {tool} append|note|strike` (`list` shows what is there — ids,
headlines, Consequence lines); never edit the file by hand.\
"""

FOLD_OPEN = "<details><summary>struck — body kept for the record</summary>"
FOLD_CLOSE = "</details>"

# The template ships one level up, next to the contract doc; the skeleton is
# the doc's first fenced block.
TEMPLATE_DOC = Path(__file__).resolve().parents[1] / "docs" / "close-out-template.md"
TEMPLATE_TITLE = "# Close-out — slice NNN <slug>"

# Section heading → the letter its entry ids carry. Summary holds no entries.
SECTIONS: dict[str, str] = {
    "Outstanding actions": "A",
    "Notable events": "N",
    "Bugs": "B",
    "Open questions and rulings": "Q",
    "Suggestions": "S",
}
SEVERITIES = ("major", "minor", "nit", "cosmetic")

HEADER_WIDTH = 96

_SECTION_RE = re.compile(r"^## (?P<name>.+?)\s*$")
_ENTRY_RE = re.compile(r"^### (~~)?(?P<letter>[A-Z])(?P<num>\d+)\b")
_ANY_HEADING_RE = re.compile(r"^### ")
# The two labels every live entry carries above the operator's line. Bold in
# the shape; a bare `Consequence:` counts too — the check is for the content.
_LABEL_RES: dict[str, re.Pattern] = {
    "Consequence": re.compile(r"^\*{0,2}Consequence:"),
    "Provenance": re.compile(r"^\*{0,2}Provenance:"),
}
_DISPOSITION_RE = re.compile(r"^\*{0,2}Disposition:")
_ANY_LABEL_RE = re.compile(r"^\*{0,2}(Consequence|Provenance|Disposition):")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# An HTML comment counts only when it opens a line (the template's comments
# all do); `<!--` mentioned mid-line in prose opens nothing.
_COMMENT_OPEN_RE = re.compile(r"^\s*<!--")


class ReportError(Exception):
    """A precondition the caller must fix — no report, no such section."""


def report_path(slice_dir: Path | str) -> Path:
    return Path(slice_dir) / REPORT_NAME


def dispatch_line(report: Path | str) -> str:
    """The report pointer a dispatch prompt carries — the path and the
    tool, once."""
    return DISPATCH_LINE.format(report=report, tool=TOOL_PATH)


def template_body() -> str:
    """The skeleton, lifted from the template doc's first fenced block."""
    text = TEMPLATE_DOC.read_text()
    match = re.search(r"^```markdown\n(.*?)^```", text, re.S | re.M)
    if not match or not match.group(1).startswith(TEMPLATE_TITLE):
        raise ReportError(f"{TEMPLATE_DOC} does not open with the close-out "
                          "skeleton as its first fenced block")
    return match.group(1)


def init_report(slice_dir: Path | str) -> bool:
    """Create close-out.md from the template. True when created; False when
    it already existed (untouched)."""
    path = report_path(slice_dir)
    if path.exists():
        return False
    slice_name = Path(slice_dir).resolve().name
    num, _, slug = slice_name.partition("_")
    title = f"# Close-out — slice {num} {slug}".rstrip()
    path.write_text(template_body().replace(TEMPLATE_TITLE, title, 1))
    return True


def _read(slice_dir: Path | str) -> tuple[Path, str]:
    path = report_path(slice_dir)
    try:
        return path, path.read_text()
    except OSError:
        raise ReportError(f"{path} does not exist — run `close_out.py init` "
                          "(both loops do at start)") from None


def _unfenced_lines(text: str):
    """(offset, line) for every line outside a fenced code block and outside
    an HTML comment — the only lines a heading can stand on. A comment runs
    from a line it opens to the line holding its `-->`; a fence opened
    inside a comment, or a comment inside a fence, is text."""
    offset, fenced, commented = 0, False, False
    for line in text.split("\n"):
        hidden = True
        if commented:
            commented = "-->" not in line
        elif _FENCE_RE.match(line):
            fenced = not fenced
        elif fenced:
            pass
        elif _COMMENT_OPEN_RE.match(line):
            commented = "-->" not in line
        else:
            hidden = False
        if not hidden:
            yield offset, line
        offset += len(line) + 1


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(name, body_start, body_end) per `## ` heading; the body runs to the
    next `## ` heading or the end of the file."""
    heads = []
    for offset, line in _unfenced_lines(text):
        m = _SECTION_RE.match(line)
        if m:
            heads.append((m.group("name"), offset + len(line), offset))
    out = []
    for i, (name, body_start, _) in enumerate(heads):
        end = heads[i + 1][2] if i + 1 < len(heads) else len(text)
        out.append((name, body_start, end))
    return out


def _section_span(text: str, section: str) -> tuple[int, int]:
    for name, start, end in _sections(text):
        if name == section:
            return start, end
    raise ReportError(f"no `## {section}` section in the report; sections are "
                      + ", ".join(SECTIONS))


def _entry_headings(body: str, letter: str,
                    struck: bool = True) -> list[int]:
    """The entry numbers under a section, from `### <letter><n>` headings
    outside fences and comments — struck ones included when `struck` (ids
    are never reused), excluded for a live count."""
    numbers = []
    for _, line in _unfenced_lines(body):
        m = _ENTRY_RE.match(line)
        if m and m.group("letter") == letter and (struck or not m.group(1)):
            numbers.append(int(m.group("num")))
    return numbers


def _unshaped_headings(body: str, letter: str) -> int:
    """`###` headings under a section that are not entries of it — no id,
    or another section's letter. Zero in a report every author wrote in
    the file's shape."""
    count = 0
    for _, line in _unfenced_lines(body):
        if not _ANY_HEADING_RE.match(line):
            continue
        m = _ENTRY_RE.match(line)
        if m is None or m.group("letter") != letter:
            count += 1
    return count


def _entries_missing_labels(body: str, letter: str) -> dict[str, int]:
    """Live entries under a section that lack a `Consequence:` or a
    `Provenance:` line — bold or bare — before the next `###` heading.
    Struck entries are nobody's to decide on and are not checked."""
    missing = dict.fromkeys(_LABEL_RES, 0)
    seen: dict[str, bool] | None = None   # None outside a live entry

    def close_entry() -> None:
        if seen is not None:
            for label, found in seen.items():
                if not found:
                    missing[label] += 1

    for _, line in _unfenced_lines(body):
        if _ANY_HEADING_RE.match(line):
            close_entry()
            m = _ENTRY_RE.match(line)
            live = (m is not None and m.group("letter") == letter
                    and not m.group(1))
            seen = dict.fromkeys(_LABEL_RES, False) if live else None
        elif seen is not None:
            for label, pattern in _LABEL_RES.items():
                if pattern.match(line):
                    seen[label] = True
    close_entry()
    return missing


def append_entry(slice_dir: Path | str, section: str, headline: str,
                 body: str, consequence: str | None = None,
                 provenance: str | None = None,
                 severity: str | None = None) -> str:
    """Append one entry in the standard shape; returns its id. The driver
    always passes a `consequence` (the CLI requires one); an entry minted
    without it is one `counts` will name."""
    if section not in SECTIONS:
        raise ReportError(f"unknown section {section!r}; sections are "
                          + ", ".join(SECTIONS))
    if severity is not None and severity not in SEVERITIES:
        raise ReportError(f"unknown severity {severity!r}; one of "
                          + ", ".join(SEVERITIES))
    path, text = _read(slice_dir)
    start, end = _section_span(text, section)
    letter = SECTIONS[section]
    numbers = _entry_headings(text[start:end], letter)
    eid = f"{letter}{max(numbers, default=0) + 1}"

    head = f"### {eid} — {' '.join(headline.split())}"
    if severity:
        head += f" · {severity}"
    parts = [head, "", body.strip(), ""]
    if consequence:
        parts += [f"**Consequence:** {' '.join(consequence.split())}", ""]
    if provenance:
        parts.append(f"**Provenance:** {' '.join(provenance.split())}")
    parts.append("**Disposition:**")
    entry = "\n".join(parts) + "\n"

    section_body = text[start:end].rstrip("\n")
    tail = text[end:]
    new = (text[:start] + section_body + "\n\n" + entry
           + ("\n" if tail else "") + tail)
    path.write_text(new)
    return eid


UNSHAPED = "unshaped"
NO_CONSEQUENCE = "no_consequence"
NO_PROVENANCE = "no_provenance"


def entry_counts(slice_dir: Path | str) -> dict[str, int]:
    """Non-struck entries per section, in section order — plus the smoke
    counts: under `UNSHAPED`, the `###` headings in the entry sections that
    are not in the entry shape and so counted as no entry at all; under
    `NO_CONSEQUENCE` / `NO_PROVENANCE`, the live entries lacking that
    line."""
    _, text = _read(slice_dir)
    counts = dict.fromkeys(SECTIONS, 0)
    unshaped = no_consequence = no_provenance = 0
    for name, start, end in _sections(text):
        if name in counts:
            body, letter = text[start:end], SECTIONS[name]
            counts[name] = len(_entry_headings(body, letter, struck=False))
            unshaped += _unshaped_headings(body, letter)
            missing = _entries_missing_labels(body, letter)
            no_consequence += missing["Consequence"]
            no_provenance += missing["Provenance"]
    counts[UNSHAPED] = unshaped
    counts[NO_CONSEQUENCE] = no_consequence
    counts[NO_PROVENANCE] = no_provenance
    return counts


def counts_line(counts: dict[str, int]) -> str:
    """`A 1 · N 3 · B 2 · Q 0 · S 1` — the summary form; the smoke counts
    trail it (`· 6 headings not in entry shape · 2 entries without a
    Consequence line · 1 entry without a Provenance line`) only when there
    are any."""
    line = " · ".join(f"{SECTIONS[name]} {counts.get(name, 0)}"
                      for name in SECTIONS)
    unshaped = counts.get(UNSHAPED, 0)
    if unshaped:
        line += f" · {_plural(unshaped, 'heading')} not in entry shape"
    for key, label in ((NO_CONSEQUENCE, "Consequence"),
                       (NO_PROVENANCE, "Provenance")):
        n = counts.get(key, 0)
        if n:
            line += (f" · {_plural(n, 'entry', 'entries')} without a "
                     f"{label} line")
    return line


# -- entries: blocks, note, strike, list, render ----------------------------

class _Block:
    """One `###` block of an entry section — the heading line and everything
    to the next unfenced `###` heading (or the section's end). `kind` is
    `live` or `struck` for a heading in the section's entry shape,
    `unshaped` for any other `###` heading."""

    __slots__ = ("start", "end", "heading", "kind", "num", "eid")

    def __init__(self, start: int, end: int, heading: str, letter: str):
        self.start, self.end, self.heading = start, end, heading
        m = _ENTRY_RE.match(heading)
        if m is None or m.group("letter") != letter:
            self.kind, self.num, self.eid = "unshaped", 0, None
        else:
            self.kind = "struck" if m.group(1) else "live"
            self.num = int(m.group("num"))
            self.eid = f"{letter}{self.num}"


def _blocks(text: str, start: int, end: int, letter: str) -> list[_Block]:
    """The `###` blocks of one section body, in file order, with absolute
    offsets into `text`."""
    body = text[start:end]
    heads = [(off, line) for off, line in _unfenced_lines(body)
             if _ANY_HEADING_RE.match(line)]
    blocks = []
    for i, (off, line) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(body)
        blocks.append(_Block(start + off, start + nxt, line, letter))
    return blocks


def _find_entry(text: str, eid: str) -> _Block:
    """The block whose heading carries `eid`, live or struck, under the
    section its letter names."""
    eid = eid.strip()
    m = re.fullmatch(r"([A-Z])\d+", eid)
    by_letter = {letter: name for name, letter in SECTIONS.items()}
    section = by_letter.get(m.group(1)) if m else None
    if section is None:
        raise ReportError(f"{eid!r} is not an entry id — ids are a section "
                          "letter (" + ", ".join(SECTIONS.values())
                          + ") and a number, like B3")
    start, end = _section_span(text, section)
    for block in _blocks(text, start, end, SECTIONS[section]):
        if block.eid == eid:
            return block
    raise ReportError(f"no entry {eid} under `## {section}`")


def _label_offset(block: str, pattern: re.Pattern) -> int | None:
    """Offset (within the block) of the first unfenced line matching the
    label pattern, bold or bare — None when the block has none."""
    for off, line in _unfenced_lines(block):
        if pattern.match(line):
            return off
    return None


def _fold_close_offset(block: str) -> int | None:
    """Offset of the fold's closing line in a rendered struck block."""
    for off, line in _unfenced_lines(block):
        if line.strip() == FOLD_CLOSE:
            return off
    return None


def _is_folded(block: str) -> bool:
    _, _, body = block.partition("\n")
    return body.lstrip("\n").startswith(FOLD_OPEN)


def _insert_paragraph(block: str, off: int | None, para: str) -> str:
    """`para` as a paragraph of its own before offset `off` in the block —
    or, with no offset, at the block's end (its trailing newlines kept)."""
    if off is None:
        stripped = block.rstrip("\n")
        return stripped + "\n\n" + para + block[len(stripped):]
    before, after = block[:off], block[off:]
    if not before.endswith("\n\n"):
        before = before.rstrip("\n") + "\n\n"
    return before + para + "\n\n" + after


def add_note(slice_dir: Path | str, eid: str, by: str, text: str,
             date: str | None = None) -> str:
    """Append `<who>, <date> — <text>` to an entry's body: above its
    Consequence line, else its Provenance line, else its Disposition line,
    else at the end — inside the fold when the entry is struck and
    rendered. Returns the paragraph."""
    path, report = _read(slice_dir)
    block = _find_entry(report, eid)
    body = text.strip()
    if not body:
        raise ReportError("a note needs text")
    who = " ".join(by.split())
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ReportError(f"--date {date!r} is not YYYY-MM-DD") from None
    day = date or datetime.now().strftime("%Y-%m-%d")
    para = f"{who}, {day} — {body}"
    old = report[block.start:block.end]
    off = None
    for pattern in (_LABEL_RES["Consequence"], _LABEL_RES["Provenance"],
                    _DISPOSITION_RE):
        off = _label_offset(old, pattern)
        if off is not None:
            break
    if off is None and _is_folded(old):
        off = _fold_close_offset(old)
    new = _insert_paragraph(old, off, para)
    path.write_text(report[:block.start] + new + report[block.end:])
    return para


def strike_entry(slice_dir: Path | str, eid: str, reason: str,
                 by: str | None = None) -> str:
    """Rewrite a live entry's heading to the struck form; returns the new
    heading. The body stays as it is — `render` folds it."""
    path, report = _read(slice_dir)
    block = _find_entry(report, eid)
    if block.kind == "struck":
        raise ReportError(f"{eid} is already struck: {block.heading}")
    heading = f"### ~~{block.heading[4:].rstrip()}~~ — {' '.join(reason.split())}"
    if by:
        heading += f"; struck by {' '.join(by.split())}"
    hstart = block.start
    hend = hstart + len(block.heading)
    path.write_text(report[:hstart] + heading + report[hend:])
    return heading


def _consequence_text(block: str) -> str | None:
    """The Consequence paragraph of a block, collapsed to one line — None
    when the block has no Consequence line."""
    off = _label_offset(block, _LABEL_RES["Consequence"])
    if off is None:
        return None
    lines = block[off:].split("\n")
    para = [re.sub(r"^\*{0,2}Consequence:\*{0,2}\s*", "", lines[0])]
    for line in lines[1:]:
        if not line.strip() or _ANY_LABEL_RE.match(line):
            break
        para.append(line)
    return " ".join(" ".join(para).split())


def _list_line(block: _Block) -> str:
    rest = block.heading[4:].rstrip()
    if block.kind == "live":
        return rest
    if block.kind == "struck":
        # `~~B3 — headline~~ — reason` → `~~B3~~ — headline — reason`
        eid = block.eid
        tail = rest[len("~~" + eid):].replace("~~", "", 1)
        return f"~~{eid}~~{tail}"
    return f"(not in entry shape) {rest}"


def list_view(slice_dir: Path | str) -> str:
    """The triage view: per entry section its `## name`, then one line per
    `###` block in file order — `B3 — <heading rest>`, with the Consequence
    text indented under a live entry (or `(no Consequence line)`); a struck
    entry as `~~B3~~ — <heading rest>`; `(none)` for an empty section."""
    _, text = _read(slice_dir)
    out: list[str] = []
    for name, start, end in _sections(text):
        if name not in SECTIONS:
            continue
        out.append(f"## {name}")
        blocks = _blocks(text, start, end, SECTIONS[name])
        if not blocks:
            out.append("(none)")
        for block in blocks:
            out.append(_list_line(block))
            if block.kind == "live":
                consequence = _consequence_text(text[block.start:block.end])
                out.append(f"    Consequence: {consequence}" if consequence
                           else "    (no Consequence line)")
    return "\n".join(out)


def _severity_rank(heading: str) -> int:
    """Position in SEVERITIES of the ` · <severity>` token a Bugs heading
    carries; past the end when it carries none."""
    for token in heading.split(" · ")[1:]:
        grade = token.strip().lower()
        if grade in SEVERITIES:
            return SEVERITIES.index(grade)
    return len(SEVERITIES)


def _fold(block: str) -> str:
    """A struck block with its body wrapped once in the fold; a block that
    already carries it, or has no body, comes back as it was."""
    heading, _, body = block.partition("\n")
    if not body.strip() or _is_folded(block):
        return block
    return (heading + "\n\n" + FOLD_OPEN + "\n\n" + body.strip("\n") + "\n\n"
            + FOLD_CLOSE + block[len(block.rstrip("\n")):])


def _render_section(text: str, name: str, start: int, end: int
                    ) -> tuple[str, dict[str, int]]:
    """One entry section's body in reading order — preamble verbatim, then
    live (Bugs by severity, else by id), unshaped as they were, struck by
    id and folded — plus its live/struck/unshaped tally."""
    letter = SECTIONS[name]
    body = text[start:end]
    blocks = _blocks(text, start, end, letter)
    tally = {"live": 0, "struck": 0, "unshaped": 0}
    for b in blocks:
        tally[b.kind] += 1
    if not blocks:
        return body, tally
    live = [b for b in blocks if b.kind == "live"]
    if name == "Bugs":
        live.sort(key=lambda b: (_severity_rank(b.heading), b.num))
    else:
        live.sort(key=lambda b: b.num)
    unshaped = [b for b in blocks if b.kind == "unshaped"]
    struck = sorted((b for b in blocks if b.kind == "struck"),
                    key=lambda b: b.num)
    pieces = [text[b.start:b.end] for b in live + unshaped]
    pieces += [_fold(text[b.start:b.end]) for b in struck]
    preamble = text[start:blocks[0].start]
    trailing = body[len(body.rstrip("\n")):]
    return (preamble + "\n\n".join(p.rstrip("\n") for p in pieces) + trailing,
            tally)


def render_report(slice_dir: Path | str) -> str:
    """Put every entry section in reading order, in place; idempotent — a
    second run changes nothing. Nothing outside the entry sections is
    touched. Returns the one-line tally (`Bugs: 6 live, 10 struck; …`)."""
    path, text = _read(slice_dir)
    out, cursor, summary = [], 0, []
    for name, start, end in _sections(text):
        if name not in SECTIONS:
            continue
        rendered, tally = _render_section(text, name, start, end)
        out.append(text[cursor:start])
        out.append(rendered)
        cursor = end
        line = f"{name}: {tally['live']} live, {tally['struck']} struck"
        if tally["unshaped"]:
            line += f", {tally['unshaped']} not in entry shape"
        summary.append(line)
    out.append(text[cursor:])
    new = "".join(out)
    if new != text:
        path.write_text(new)
    return "; ".join(summary)


# -- the run header ----------------------------------------------------------

def _fmt_ts(value, day_of: str | None = None) -> str | None:
    """`2026-08-14 19:49`, or `23:53` when the day equals `day_of`."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    day = dt.strftime("%Y-%m-%d")
    hm = dt.strftime("%H:%M")
    return hm if day_of == day else f"{day} {hm}"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def run_header(state: dict) -> str:
    """The `Run:` line from a run loop state.json — each piece only when
    the state carries it."""
    bits: list[str] = []
    start = _fmt_ts(state.get("created_at"))
    if start:
        end = _fmt_ts(state.get("updated_at"), day_of=start[:10])
        bits.append(f"{start} → {end}" if end else start)
    known = list(state.get("known_phases") or [])
    if known:
        appended = [p for p in state.get("appended_phases") or [] if p in known]
        phrase = _plural(len(known), "phase")
        if appended:
            phrase += (f" ({len(known) - len(appended)} planned, "
                       + ", ".join(f"P{p}" for p in appended) + " appended)")
        bits.append(phrase)
    if isinstance(state.get("bailouts"), list):
        bailouts = state["bailouts"]
        phrase = _plural(len(bailouts), "bail-out")
        questions = sum(1 for b in bailouts
                        if isinstance(b, dict) and b.get("question"))
        if questions:
            phrase += f" ({_plural(questions, 'operator question')})"
        bits.append(phrase)
    if isinstance(state.get("test_rounds"), int):
        bits.append(_plural(state["test_rounds"], "test round"))
    doc = state.get("doc_phase")
    if isinstance(doc, dict) and doc.get("stage"):
        stage = doc["stage"]
        bits.append("doc phase done" if stage == "done"
                    else f"doc phase at stage {stage}")
    run_phase = state.get("run_phase")
    if run_phase and run_phase != "done":
        bits.append(f"run {run_phase}")
    cost = state.get("cost")
    if isinstance(cost, dict) and isinstance(cost.get("cost_usd"), int | float):
        phrase = f"${cost['cost_usd']:,.2f}"
        shares = [(k, cost.get(f"{k}_share"))
                  for k in ("planner", "research", "rework")]
        shares = [(k, v) for k, v in shares if isinstance(v, int | float)]
        if shares:
            phrase += " (" + ", ".join(f"{k} {round(v * 100)} %"
                                       for k, v in shares) + ")"
        bits.append(phrase)
    return "Run: " + (" · ".join(bits) if bits else "(no run record)")


def stamp_header(slice_dir: Path | str) -> str:
    """Replace the report's `Run:` block (the `Run:` line and the non-blank
    lines that follow it) with the header from state.json. Idempotent."""
    path, text = _read(slice_dir)
    state_path = Path(slice_dir) / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        raise ReportError(f"{state_path} is missing or unreadable — nothing "
                          "to stamp from") from None
    header = run_header(state)
    lines = text.split("\n")
    idx = next((i for i, line in enumerate(lines) if line.startswith("Run:")),
               None)
    if idx is None:
        raise ReportError(f"{path} has no `Run:` line to stamp")
    j = idx + 1
    while j < len(lines) and lines[j].strip() and not lines[j].startswith("#"):
        j += 1
    lines[idx:j] = textwrap.wrap(header, width=HEADER_WIDTH,
                                 break_long_words=False,
                                 break_on_hyphens=False)
    path.write_text("\n".join(lines))
    return header


# -- CLI --------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create close-out.md if absent")
    p.add_argument("slice_dir")

    p = sub.add_parser("append", help="append one entry; prints its id")
    p.add_argument("slice_dir")
    p.add_argument("--section", required=True, choices=list(SECTIONS))
    p.add_argument("--headline", required=True)
    p.add_argument("--body", required=True, help="entry body, or - for stdin")
    p.add_argument("--consequence", required=True,
                   help="the line the operator triages on")
    p.add_argument("--provenance")
    p.add_argument("--severity", choices=SEVERITIES)

    p = sub.add_parser("note", help="add a dated paragraph to one entry's body")
    p.add_argument("slice_dir")
    p.add_argument("id", help="the entry's id, like B3")
    p.add_argument("--by", required=True, help="who notes — role and round")
    p.add_argument("--text", required=True, help="the note, or - for stdin")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = sub.add_parser("strike", help="strike one live entry; prints the heading")
    p.add_argument("slice_dir")
    p.add_argument("id", help="the entry's id, like B3")
    p.add_argument("--reason", required=True,
                   help="why — resolved/refuted names the commit and the re-run")
    p.add_argument("--by", help="who strikes, e.g. `consult 1`")

    p = sub.add_parser("list", help="the triage view: ids, headlines, Consequence lines")
    p.add_argument("slice_dir")

    p = sub.add_parser("render", help="put the entry sections in reading order, in place")
    p.add_argument("slice_dir")

    p = sub.add_parser("stamp", help="stamp the Run: header from state.json")
    p.add_argument("slice_dir")

    p = sub.add_parser("counts", help="non-struck entries per section")
    p.add_argument("slice_dir")

    args = parser.parse_args(argv)
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
        return 2
    try:
        if args.command == "init":
            created = init_report(slice_dir)
            print(f"{'created' if created else 'exists'} {report_path(slice_dir)}")
        elif args.command == "append":
            body = sys.stdin.read() if args.body == "-" else args.body
            print(append_entry(slice_dir, args.section, args.headline, body,
                               consequence=args.consequence,
                               provenance=args.provenance,
                               severity=args.severity))
        elif args.command == "note":
            text = sys.stdin.read() if args.text == "-" else args.text
            add_note(slice_dir, args.id, args.by, text, date=args.date)
            print(f"{args.id} noted")
        elif args.command == "strike":
            print(strike_entry(slice_dir, args.id, args.reason, by=args.by))
        elif args.command == "list":
            print(list_view(slice_dir))
        elif args.command == "render":
            print(render_report(slice_dir))
        elif args.command == "stamp":
            print(stamp_header(slice_dir))
        elif args.command == "counts":
            print(counts_line(entry_counts(slice_dir)))
    except ReportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
