#!/usr/bin/env python3
"""The close-out report's mechanics — create, append, stamp, count.

`<slice>/close-out.md` is the one document every plan and run agent writes
its out-of-scope observations to (${CLAUDE_PLUGIN_ROOT}/docs/close-out.md is
the contract; docs/close-out-template.md the shape). Agents write it by hand
in the shape the file's head comment shows; this tool is for the
deterministic parts — importable by both loops (the way plan_loop imports
run_loop) and a CLI for the skills:

  init   create close-out.md from the template if absent — the title takes
         the slice's `NNN <slug>`; an existing file is never touched.
  append add one entry to a section: the next id from the section's letter
         (struck headings count), the standard entry shape, a blank
         `Disposition:` line. Prints the id.
  stamp  replace the `Run:` header block with the run's shape read from
         state.json — window, phases planned/appended, bail-outs, test
         rounds, doc phase, and the `cost` block once slice_cost.py
         --write-state has run. Missing pieces are omitted, not guessed;
         re-stamping overwrites the same block.
  counts non-struck entries per section, one line — plus, when there are
         any, the number of `###` headings in the entry sections that are
         not in the entry shape (an author that drifted from the shape,
         which would otherwise count as zero entries).

Headings are read outside fenced code blocks and outside HTML comments
only — an entry that quotes a document's `## Bugs` or a `### B3` inside a
``` fence (the entry rules ask for liberal quoting) neither moves a section
boundary nor shifts an id, and the template's own head comment shows the
entry shape with a `### B2 — …` line in it.

Deliberately not here: any validation beyond "the section heading exists"
and that heading count, dedup, disposition parsing.

Usage:
    close_out.py init <slice-dir>
    close_out.py append <slice-dir> --section <name> --headline <text>
                 --body <text | -> [--provenance <text>] [--severity <s>]
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
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# An HTML comment counts only when it opens a line (the template's comments
# all do); `<!--` mentioned mid-line in prose opens nothing.
_COMMENT_OPEN_RE = re.compile(r"^\s*<!--")


class ReportError(Exception):
    """A precondition the caller must fix — no report, no such section."""


def report_path(slice_dir: Path | str) -> Path:
    return Path(slice_dir) / REPORT_NAME


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


def append_entry(slice_dir: Path | str, section: str, headline: str,
                 body: str, provenance: str | None = None,
                 severity: str | None = None) -> str:
    """Append one entry in the standard shape; returns its id."""
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
    if provenance:
        parts.append(f"Provenance: {' '.join(provenance.split())}")
    parts.append("Disposition:")
    entry = "\n".join(parts) + "\n"

    section_body = text[start:end].rstrip("\n")
    tail = text[end:]
    new = (text[:start] + section_body + "\n\n" + entry
           + ("\n" if tail else "") + tail)
    path.write_text(new)
    return eid


UNSHAPED = "unshaped"


def entry_counts(slice_dir: Path | str) -> dict[str, int]:
    """Non-struck entries per section, in section order — plus, under
    `UNSHAPED`, the `###` headings in the entry sections that are not in
    the entry shape and so counted as no entry at all."""
    _, text = _read(slice_dir)
    counts = dict.fromkeys(SECTIONS, 0)
    unshaped = 0
    for name, start, end in _sections(text):
        if name in counts:
            body, letter = text[start:end], SECTIONS[name]
            counts[name] = len(_entry_headings(body, letter, struck=False))
            unshaped += _unshaped_headings(body, letter)
    counts[UNSHAPED] = unshaped
    return counts


def counts_line(counts: dict[str, int]) -> str:
    """`A 1 · N 3 · B 2 · Q 0 · S 1` — the summary form; a trailing
    `· 6 headings not in entry shape` only when there are any."""
    line = " · ".join(f"{SECTIONS[name]} {counts.get(name, 0)}"
                      for name in SECTIONS)
    unshaped = counts.get(UNSHAPED, 0)
    if unshaped:
        line += f" · {_plural(unshaped, 'heading')} not in entry shape"
    return line


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


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


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
    p.add_argument("--provenance")
    p.add_argument("--severity", choices=SEVERITIES)

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
                               provenance=args.provenance,
                               severity=args.severity))
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
