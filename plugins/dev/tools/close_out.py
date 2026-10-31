#!/usr/bin/env python3
"""The close-out report's mechanics — the store, its verbs, the routing table, the render.

`<slice>/close-out.json` is the record every plan and run agent writes its
out-of-scope observations to (${CLAUDE_PLUGIN_ROOT}/docs/close-out.md is the
contract — the labels, the routes, who writes what; docs/close-out-template.md
the shapes). At the run's end it is rendered, once, into two files:
`close-out.md`, the document Pilot reads — one ask per entry that comes to
the operator, rendered by `asks.py` in the format of `/dev:document-format` —
and `close-out-record.md`, the record attached to it. Pilot writes the
answers back into close-out.md; `absorb` reads them into the store, where
the run's continuation finds each ruling, carries it out and records what it
did. Every writer goes through this tool — the shape is mechanical, the
content is judgment — and nobody edits any of the three files by hand;
importable by both loops (the way plan_loop imports run_loop) and a CLI for
the agents and the skills:

  init         create the store (no entries); an existing store is never
               touched.
  labels       print the contract's `## The labels` section.
  append       add one entry with the labels its kind carries, and what its
               kind owes: an action and an improvement a proposal, a
               decision its options and the one it recommends — refused,
               naming the flag, when one is missing, belongs to another
               kind, or contradicts the Consequence line. `--check` and
               `--due` are an action's check and what an entry must land
               before. Prints the id: the kind's letter and the next number
               under it.
  list         the view an agent takes before it appends: per kind, ids,
               headlines and Consequence lines, struck entries marked.
  note         add a dated paragraph `<who>, <date> — <text>` to one entry;
               `--left` is the wrap-up's mark that it looked and changed
               nothing.
  strike       strike one entry, with the reason and the commit.
  amend        correct a live entry: each field given replaces the entry's,
               checked as `append` checks it, no note left. The id and the
               kind never change.
  relabel      give an entry its labels or correct them, with a note of what
               changed and why. The id never changes, not even with the kind.
               `--dry-run` prints the note and the route it would give the
               entry, and writes nothing.
  restate      give an entry the section the document shows for it — the
               heading, the body, the consequence and the provenance, in
               place of its author's, which the record keeps; a second
               restatement replaces the first, kept as a note.
  propose      give an entry its proposal, or replace it, the old one kept as
               a note; `--card` and `--word` make it the wrap-up's request
               for a card, or for the operator's word on an edit, and take a
               restated entry: the section is the card, or the edit.
  fold         append an entry verbatim — its `show`, quoted, under a line
               naming the slice, the entry and the report — to the slice.md
               of the slice still unplanned it is `for` (or `--into`), and
               stage that file; prints the strike that follows its commit.
               Writes neither the store nor the report.
  worklist     what waits for the wrap-up, with what is asked of each.
  show         one or more entries in full — what the document and the
               record cut short; `--card`, the card an agreed card request
               files: the section's heading, then its body.
  render       write close-out-record.md, and close-out.md through asks.py
               — unless Pilot wrote that one back, its answers in it;
               `--step`, `--summary` and `--context` set the document's own
               fields.
  absorb      read close-out.md, as Pilot wrote it back, into the store:
               each block's answer lines into its entry's ruling; a
               `deferred` closes the entry as Pilot's, an action's `done`
               is what was done on it.
  rule         record what the continuation did on an entry's ruling, which
               strikes it.
  settle       settle a criterion owed after an operator's action, once it
               has happened: its verdict, rationale and evidence written
               into verification.json in the file's own escaping, and the
               action that waited on it struck — a push hold's action that
               lists more criteria takes a note until the last is settled.
  close        close the report once its answers are carried out: every
               live entry struck, but one whose ruling nobody carried out.

The store is open to every author — the appender, the reviewers, the
consults, the wrap-up — until the report is rendered at the run's end; after
it, only the continuation writes, through `absorb`, `rule`, `fold`, `settle`
and `close`. Nothing renders on a write. `append`, `amend`, `note` and
`propose` refuse an author's text that cites a line by its number outside a
fenced block (`asks.citation_problems`; the rule is `docs/spec-tree.md`
§ Citing a line), and `restate` does too; `append`, `amend` and `propose`
refuse a proposal longer than `asks.PROPOSAL_MAX` once its lines are
joined (`asks.proposal_problems`); `propose --card`, and `restate` on a card
request, refuse a section — the card it files — over `CARD_WORDS_MAX` words.
The functions the loops call check neither of the first two, since a
driver's text quotes tool output.

The route is computed at every render, never stored: `route()` reads an
entry's kind and labels, the repositories the slice touched, and the stage
of the slice a `for` names (still unplanned, planned or running, or not
created yet) against the two tables of the contract (§ The routes) — the
policy is the operator's and lives here only. So do the run loop's triggers
for what is owed before the push (`owed_before_push()`) and before the test
phase (`owed_before_test()`), which read the `due` an author set: the live
entries it hands the completion consult.

Every read-modify-write of the store holds an exclusive flock on the slice
directory itself (no lock file lands in the spec repo's tree). A filesystem
that refuses the flock gets the write without it.

`<slice>` is the slice directory or its close-out.md — the dispatch names the
report, so the report's path is what an agent has in hand; a `.md` or `.json`
argument resolves to its directory.

Exit codes: 0 ok · 2 usage/precondition error.
"""

import argparse
import contextlib
import difflib
import fcntl
import json
import os
import re
import shlex
import string
import subprocess
import sys
import tempfile
import textwrap
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asks  # noqa: E402
import checks  # noqa: E402

REPORT_NAME = "close-out.md"
RECORD_NAME = "close-out-record.md"
STORE_NAME = "close-out.json"
STORE_VERSION = 2

# This file, resolved — the driver runs from the installed plugin clone, so
# a dispatch that names it names the copy that will run.
TOOL_PATH = Path(__file__).resolve()

# The contract ships one level up; `labels` prints a section of it.
CONTRACT_DOC = TOOL_PATH.parents[1] / "docs" / "close-out.md"
TEMPLATE_DOC = TOOL_PATH.parents[1] / "docs" / "close-out-template.md"
LABELS_HEADING = "## The labels"

# What every dispatch carries about the report: where it is, that this tool
# is the only way to write to it, the labels, `append`'s arguments, and what
# does not belong in it (close-out.md § What it is). Both loops use it
# as-is; it is the one text a bare consult, which has no agent definition,
# is sure to read.
DISPATCH_LINE = """\
The slice's close-out report is {report}, rendered from its store,
{store}, once, at the run's end. Write to it only through `python3 {tool}
<verb> {report} …` — `append`, `note`, `strike`, and `amend <id>`, which
corrects an entry (any of `append`'s flags but --kind, each replacing its
field);{relabel_line} `list` shows what is there (ids, headlines,
Consequence lines) — never edit either file by hand, and commit the store
with your own commit, staged by name. An entry carries labels that say what
it is, and the tool routes it from them: you state what you know and what
you would do (`--proposal`; a decision's `--option` lines and the one it
`--recommend`s) — never where the entry goes. `python3 {tool} labels` prints
what each label means — read it before your first append. The labels each
kind carries, every one of them, `unknown` where you cannot tell:
{kind_labels}
{label_pairing}
The verbs take:
{verb_usage}
The report is about the work; what got in your way while working, and any
improvement of the workflow itself, goes to the `fieldnotes` MCP tool
`post` instead.\
"""
# What DISPATCH_LINE says of `relabel` where a dispatch offers it (`dispatch_line(...,
# relabel=True)`) — wrapped where it falls in the paragraph.
DISPATCH_RELABEL = """ `relabel <id> --by <who> --note
<what you found>` corrects an entry's labels where you can show they are
wrong, whoever appended it: the tool routes an entry from its labels,
never from a note;"""

# -- the vocabulary (close-out.md § The labels) -------------------------------

# Kind → the letter its ids carry, in the contract's order.
KINDS: dict[str, str] = {
    "action": "A",
    "decision": "D",
    "event": "E",
    "defect": "B",
    "prose": "P",
    "test-gap": "T",
    "improvement": "I",
}
# The letters of the Markdown report the store replaced; an imported entry
# keeps its id, so these stay in the count wherever the store holds one.
OLD_LETTERS = ("N", "Q", "S")

# The five sections of the old report, taken as kinds wherever a caller
# passes one (the loops still do).
SECTIONS: dict[str, str] = {
    "Outstanding actions": "action",
    "Notable events": "event",
    "Bugs": "defect",
    "Open questions and rulings": "decision",
    "Suggestions": "improvement",
}

SEVERITIES = ("major", "minor", "nit", "cosmetic")
# The reading order inside a section: an ungraded entry between minor and nit.
GRADE_ORDER = ("major", "minor", None, "nit", "cosmetic")

# Every label, in the order the Triage line says them, with its values; None
# for a free value (`repo`, `for`).
LABELS: dict[str, tuple[str, ...] | None] = {
    "trigger": ("normal-use", "ordinary-condition", "fault", "future-change",
                "none", "unknown"),
    "impact": ("severe", "broken", "degraded", "none", "unknown"),
    "signal": ("loud", "silent", "none", "unknown"),
    "fix": ("one-edit", "several-places", "design", "unknown"),
    "benefit": ("user", "operations", "workflow", "code", "unknown"),
    "felt": ("in-use", "after-change", "after-incident", "not-observable",
             "unknown"),
    "change": ("remove", "adjust", "add", "unknown"),
    "size": ("one-edit", "several-places", "design", "investigate", "unknown"),
    "product-call": ("yes", "no"),
    "prevents": ("severe", "broken", "degraded", "nothing", "unknown"),
    "area": ("plain", "sensitive"),
    "repo": None,
    "for": None,
}
# What is wrong, or could go wrong — and what could be better. `area`,
# `repo` and `for` are both families'.
FIX_FAMILY = ("trigger", "impact", "signal", "fix")
IMPROVEMENT_FAMILY = ("benefit", "felt", "change", "size", "product-call",
                      "prevents")

# The kinds the tool labels itself when a loop enters one without labels.
TOOL_LABELLED = ("action", "event", "decision")

# The labels an entry's kind asks of its author (close-out.md, "Which labels
# an entry carries"); an event with an impact other than `none` owes
# EVENT_PROBLEM as well.
REQUIRED: dict[str, tuple[str, ...]] = {
    "defect": ("trigger", "impact", "signal", "fix", "area", "repo"),
    "test-gap": ("trigger", "impact", "signal", "fix", "area", "repo"),
    "prose": ("trigger", "impact", "signal", "fix", "repo"),
    "event": ("trigger", "impact", "signal"),
    "action": ("trigger", "impact", "signal"),
    "decision": ("trigger", "impact", "signal"),
    "improvement": ("benefit", "felt", "change", "size", "product-call",
                    "prevents", "area", "repo"),
}
EVENT_PROBLEM = ("fix", "area", "repo")

# The labels a kind carries at all, `for` with every one: what a relabel to
# that kind keeps of the old labels. An event keeps EVENT_PROBLEM whatever
# its impact, an action or a decision the labels of a fix it names.
CARRIES: dict[str, tuple[str, ...]] = {
    "defect": FIX_FAMILY + ("area", "repo", "for"),
    "test-gap": FIX_FAMILY + ("area", "repo", "for"),
    "prose": FIX_FAMILY + ("repo", "for"),
    "event": FIX_FAMILY + ("area", "repo", "for"),
    "action": FIX_FAMILY + ("area", "repo", "for"),
    "decision": FIX_FAMILY + ("area", "repo", "for"),
    "improvement": IMPROVEMENT_FAMILY + ("area", "repo", "for"),
}

# The labels in words, for the Triage line; a value mapped to None is left
# out of it.
WORDS: dict[str, dict[str, str | None]] = {
    "kind": {"action": "action", "decision": "decision", "event": "event",
             "defect": "defect", "prose": "prose", "test-gap": "test gap",
             "improvement": "improvement"},
    "trigger": {"normal-use": "shows in normal use",
                "ordinary-condition": "shows on an ordinary condition",
                "fault": "needs a fault", "future-change": "needs a future change",
                "none": "nothing that could show", "unknown": "trigger unknown"},
    "impact": {"severe": "severe", "broken": "breaks a flow", "degraded": "degrades",
               "none": "no impact", "unknown": "impact unknown"},
    "signal": {"loud": "loud", "silent": "silent", "none": None,
               "unknown": "signal unknown"},
    "fix": {"one-edit": "fix is one edit",
            "several-places": "fix is known, in several places",
            "design": "fix needs design", "unknown": "fix unknown"},
    "benefit": {"user": "a user is better off",
                "operations": "operations are better off",
                "workflow": "the workflow is better off",
                "code": "the code is better off", "unknown": "benefit unknown"},
    "felt": {"in-use": "felt in use", "after-change": "felt after a change",
             "after-incident": "felt after an incident",
             "not-observable": "not observable", "unknown": "felt unknown"},
    "change": {"remove": "removes something", "adjust": "adjusts what exists",
               "add": "adds something", "unknown": "change unknown"},
    "size": {"one-edit": "one edit", "several-places": "several places",
             "design": "needs design", "investigate": "needs a look first",
             "unknown": "size unknown"},
    "product-call": {"yes": "a product call", "no": None},
    "prevents": {"severe": "prevents something severe",
                 "broken": "prevents a broken flow",
                 "degraded": "prevents a degradation", "nothing": None,
                 "unknown": "prevents unknown"},
    "area": {"sensitive": "sensitive area", "plain": None},
}
TRIAGE_ORDER = ("trigger", "impact", "signal", "fix", "benefit", "felt",
                "change", "size", "product-call", "prevents", "area", "repo",
                "for")

# "Not felt in use": the improvement table's rows 3 and 4. `unknown` is not
# taken as unfelt.
UNFELT = ("after-change", "after-incident", "not-observable")

# -- the report (docs/close-out-template.md) -----------------------------------

# Where a route puts an entry: the document's three places, then the record's
# two. The asks of the document are what comes to the operator, the card
# requests, and what waits for a wrap-up that did not reach it (or an entry
# without labels, which nobody routed); the record holds the rest.
PLACES = ("Comes to you", "Card requests", "For the wrap-up", "Unlabelled", "Closed",
          "Record")
ASKED = ("Comes to you", "Card requests", "For the wrap-up", "Unlabelled")
# The sections of close-out-record.md, in order: what was ruled, what is asked
# and open, what the table closed, and the record.
RECORD_SECTIONS = ("Ruled", "Asked", "Closed", "Record")
# The counts line's word for each place, in the same order.
COUNT_NAMES = ("to you", "card requests", "wrap-up", "unlabelled", "closed", "record")
# The smoke counts that trail the counts line when there are any.
NO_CONSEQUENCE = "no_consequence"
NO_PROVENANCE = "no_provenance"
NO_PROPOSAL = "no_proposal"

UNSTAMPED = "Run: <not yet stamped>"

# The kinds whose author owes a proposal: an action and an improvement; a
# decision owes its options and the one recommended in its place.
PROPOSAL_KINDS = ("action", "improvement")
PROPOSAL_HELP = "what you would do about it and why, in a sentence or two"

# What must land before a step of the run (`--due`): the store keeps it for
# the driver, and the document never shows it.
DUES = asks.DUES

HEADER_WIDTH = 96

# Who strikes an entry the continuation executed (`rule --did`), and one
# Pilot's answer closed (`deferred`).
RULED_BY = "the operator's ruling"
PILOT = "Pilot"
PILOT_RULED_BY = "Pilot's ruling"

_ID_RE = re.compile(r"([A-Z])(\d+)")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MARKUP = string.punctuation + "—–…“”‘’"


class ReportError(Exception):
    """A precondition the caller must fix — no store, no such entry, a label
    the entry's kind does not take."""


def report_path(slice_dir: Path | str) -> Path:
    return Path(slice_dir) / REPORT_NAME


def store_path(slice_dir: Path | str) -> Path:
    return Path(slice_dir) / STORE_NAME


def slice_dir_of(arg: Path | str) -> Path:
    """The slice directory a CLI argument names: itself, or — for the
    report's own path, which is what every dispatch hands an agent, or the
    store's — its parent. Resolved present or not, so the first call works
    before `init` too."""
    path = Path(arg)
    return path.parent if path.suffix in (".md", ".json") else path


def dispatch_line(report: Path | str, *, relabel: bool = False) -> str:
    """The report pointer a dispatch prompt carries — the path, the store,
    the tool, the labels each kind carries and how they pair, as
    `check_labels` holds them, and the arguments of three of the verbs it
    names, rendered from the parser; `amend`, whose flags are `append`'s,
    is named without them. With `relabel`, it offers `relabel` too, for
    an entry whose labels the role can show wrong, and gives its
    arguments."""
    verbs = ("append", "note", "strike") + (("relabel",) if relabel else ())
    return DISPATCH_LINE.format(report=report, store=STORE_NAME, tool=TOOL_PATH,
                                relabel_line=DISPATCH_RELABEL if relabel else "",
                                kind_labels=kind_labels_text(),
                                label_pairing=LABEL_PAIRING,
                                verb_usage=verb_usage(*verbs))


def _collapse(text: str | None) -> str:
    return " ".join((text or "").split())


def _lines(text: str) -> list[str]:
    """Text as the store keeps it: one string per line, the outer blank
    lines and trailing spaces taken off."""
    lines = [line.rstrip() for line in (text or "").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _date(date: str | None) -> str:
    if date is None:
        return _today()
    if not _DATE_RE.fullmatch(date):
        raise ReportError(f"--date {date!r} is not YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ReportError(f"--date {date!r} is not YYYY-MM-DD") from None
    return date


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def opens_with_none(consequence: str | None) -> bool:
    """Whether a Consequence line says `none`: its first word, any case, with
    markup and punctuation stripped."""
    words = (consequence or "").split()
    return bool(words) and words[0].strip(_MARKUP).lower() == "none"


def tool_labels(kind: str, consequence: str | None) -> dict | None:
    """The labels the tool gives an entry a loop enters without any: an
    action, an event or a decision describes no problem when its
    Consequence opens with "none", and one whose trigger and impact are
    unknown when it says anything else — the wrap-up then looks. Any other
    kind is left unlabelled."""
    if kind not in TOOL_LABELLED:
        return None
    value = "none" if opens_with_none(consequence) else "unknown"
    return dict.fromkeys(("trigger", "impact", "signal"), value)


def _ordered_labels(labels: dict) -> dict:
    return {k: labels[k] for k in LABELS if labels.get(k) is not None}


def _kind_of(section: str) -> str:
    """A caller's `section` — one of the five old section names, or a
    kind — as a kind."""
    if section in SECTIONS:
        return SECTIONS[section]
    if section in KINDS:
        return section
    raise ReportError(f"unknown kind {section!r}; kinds are " + ", ".join(KINDS)
                      + " (or the sections " + ", ".join(SECTIONS) + ")")


def _home_kind(entry: dict) -> str | None:
    """The kind a section-or-kind argument matches an entry on: the section
    it stood under, for an imported entry; its kind otherwise."""
    if entry.get("section") in SECTIONS:
        return SECTIONS[entry["section"]]
    return entry.get("kind")


# -- the store: lock, load, save ---------------------------------------------

_HELD = threading.local()


@contextlib.contextmanager
def _locked(slice_dir: Path | str):
    """An exclusive flock on the slice directory for the length of one
    read-modify-write. Re-entrant within a thread (a second fd on the
    directory would be a second flock owner and wait on itself); a lock
    that is held is waited for; a filesystem that cannot lock gets the
    write without it — a write never fails for the lock."""
    key = os.path.abspath(slice_dir)
    held = getattr(_HELD, "dirs", None)
    if held is None:
        held = _HELD.dirs = {}
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    fd = None
    try:
        fd = os.open(key, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        if fd is not None:
            os.close(fd)
            fd = None
    held[key] = 1
    try:
        yield
    finally:
        del held[key]
        if fd is not None:
            os.close(fd)


def _write_atomic(path: Path, text: str) -> None:
    """Write through a temp file in the same directory and os.replace, so a
    reader never sees half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _dump(store: dict) -> str:
    return json.dumps(store, indent=2, ensure_ascii=False) + "\n"


def _save(slice_dir: Path | str, store: dict) -> None:
    _write_atomic(store_path(slice_dir), _dump(store))


def _new_store(slice_dir: Path | str) -> dict:
    return {"store": STORE_VERSION, "slice": Path(slice_dir).resolve().name,
            "closed": None, "entries": []}


def _load(slice_dir: Path | str) -> dict:
    """The store. Called under the lock."""
    path = store_path(slice_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ReportError(f"{path} does not exist — run `close_out.py init` "
                          "(both loops do at start)") from None
    except OSError as e:
        raise ReportError(f"{path} is unreadable: {e}") from None
    try:
        store = json.loads(text)
    except json.JSONDecodeError as e:
        raise ReportError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(store, dict) or not isinstance(store.get("entries"), list):
        raise ReportError(f"{path} is not a close-out store")
    return store


def _read_store(slice_dir: Path | str) -> dict:
    with _locked(slice_dir):
        return _load(slice_dir)


@contextlib.contextmanager
def _writing(slice_dir: Path | str):
    """The one path every change of the store takes: lock, load, change,
    save when something changed, release. Nothing is rendered: the report is
    rendered once, at the run's end (`render_report`). An exception inside
    writes nothing."""
    with _locked(slice_dir):
        store = _load(slice_dir)
        before = _dump(store)
        yield store
        if _dump(store) != before:
            _save(slice_dir, store)


def _find(store: dict, eid: str) -> dict:
    eid = eid.strip()
    if not _ID_RE.fullmatch(eid):
        raise ReportError(f"{eid!r} is not an entry id — a letter and a "
                          "number, like B3")
    for entry in store["entries"]:
        if entry["id"] == eid:
            return entry
    raise ReportError(f"no entry {eid} in the report")


def _next_id(store: dict, letter: str) -> str:
    """The letter and the next number under it — every entry that carries
    the letter counts, struck ones included; ids are never reused."""
    nums = [int(m.group(2)) for e in store["entries"]
            if (m := _ID_RE.fullmatch(e["id"])) and m.group(1) == letter]
    return f"{letter}{max(nums, default=0) + 1}"


def _split_provenance(provenance: str | None) -> tuple[str | None, str | None]:
    """(`witnessed` | `read` | None, the rest) — the evidence class is the
    first word when it is one; otherwise the provenance is kept whole."""
    text = _collapse(provenance)
    if not text:
        return None, None
    first, _, rest = text.partition(" ")
    word = first.strip(_MARKUP).lower()
    if word in ("witnessed", "read") and first.rstrip(_MARKUP).lower() == word:
        # `witnessed — author`, `read: author`, `read, author`: the
        # separator goes with the word.
        tail = first[len(first.rstrip(_MARKUP)):] + (" " + rest if rest else "")
        author = tail.strip().lstrip("—–-:;,").strip()
        return word, author or None
    return None, text


def _entry(eid: str, kind: str | None, headline: str, body: list[str],
           consequence: str | None, provenance: str | None,
           severity: str | None, labels: dict | None,
           proposal: str | None = None, by: str | None = None) -> dict:
    evidence, author = _split_provenance(provenance)
    return {
        "id": eid, "kind": kind, "grade": severity,
        "headline": _collapse(headline), "body": body,
        "consequence": _collapse(consequence) or None,
        "proposal": _collapse(proposal) or None,
        "evidence": evidence, "author": author, "by": _collapse(by) or None,
        "labels": _ordered_labels(labels) if labels is not None else None,
        "notes": [], "wrap_up": None, "strike": None, "ruling": None,
    }


# The kinds that take each field an entry carries for the block it renders
# to, each only where given; `due`, the driver's, any kind takes.
# `_ask_problems` applies it.
_ASK_TAKES = {"options": ("decision", "action"), "recommend": ("decision",),
              "check": ("action",)}


def _ask_problems(entry: dict) -> list[str]:
    """What keeps an entry's options, recommendation, check or due from the
    block it renders to: a field its kind does not take, an option list
    `asks.py` would refuse, a recommendation naming no option, a due that is
    no step of the run."""
    kind = entry.get("kind")
    found: list[str] = []
    for key, kinds in _ASK_TAKES.items():
        if entry.get(key) is not None and kind not in kinds:
            takers = " or ".join(f"a{'n' if k[0] in 'aeiou' else ''} {k}" for k in kinds)
            found.append(f"--{'option' if key == 'options' else key} is {takers}'s, "
                         f"not a{'n' if (kind or ' ')[0] in 'aeiou' else ''} {kind}'s")
    options = entry.get("options")
    if options is not None:
        found += [f.removeprefix("the ask: ") for f in
                  asks._options_problems(options, "the ask")]
        if kind == "decision" and len(options) < 2:
            found.append("a decision puts two options or more (--option, repeated)")
    recommend = entry.get("recommend")
    if recommend is not None and recommend not in [o.get("label") for o in options or ()
                                                   if isinstance(o, dict)]:
        found.append(f"--recommend {recommend!r} names no --option")
    if entry.get("check") is not None and kind == "action":
        found += [f"--check: {fault}" for fault in checks.problems(entry["check"])]
    elif entry.get("check") is not None and not _collapse(entry["check"]):
        found.append("--check is empty")
    if entry.get("due") is not None and entry["due"] not in DUES:
        found.append(f"--due is one of {', '.join(DUES)}, not {entry['due']!r}")
    return found


def _set_ask_fields(entry: dict, options=None, recommend: str | None = None,
                    check: str | None = None, due: str | None = None) -> None:
    """Each field given in place of the entry's; an empty one removes it."""
    given = {"options": options, "recommend": recommend, "check": check, "due": due}
    for key, value in given.items():
        if value is None:
            continue
        if value in ("", []):
            entry.pop(key, None)
        elif key == "options":
            entry[key] = asks._options(value)
        else:
            entry[key] = _collapse(value)


# -- the API both loops import -----------------------------------------------

def init_report(slice_dir: Path | str) -> bool:
    """Create the store, without entries. True when created; False when a
    store was already there, which is left as it is."""
    with _locked(slice_dir):
        if store_path(slice_dir).exists():
            return False
        _save(slice_dir, _new_store(slice_dir))
        return True


def append_entry(slice_dir: Path | str, section: str, headline: str,
                 body: str, consequence: str | None = None,
                 provenance: str | None = None,
                 severity: str | None = None,
                 labels: dict | None = None,
                 proposal: str | None = None,
                 by: str | None = None, *, options=None,
                 recommend: str | None = None, check: str | None = None,
                 due: str | None = None) -> str:
    """Append one entry; returns its id. `section` is a kind or one of the
    old section names. The loops' path, and it refuses nothing about labels
    or the proposal: without labels, an action, an event or a decision gets
    the tool's own (`tool_labels`) and any other kind is stored unlabelled.
    The CLI checks an author's labels and proposal before it gets here.
    `options` (labels, or (label, line) pairs), `recommend`, `check` and
    `due` are the block's and the driver's, refused where the kind does not
    take them (`_ask_problems`). `by` is the appender, kept as the record of
    who wrote it."""
    kind = _kind_of(section)
    if severity is not None and severity not in SEVERITIES:
        raise ReportError(f"unknown severity {severity!r}; one of "
                          + ", ".join(SEVERITIES))
    if labels is None:
        labels = tool_labels(kind, consequence)
    with _writing(slice_dir) as store:
        eid = _next_id(store, KINDS[kind])
        entry = _entry(eid, kind, headline, _lines(body), consequence, provenance,
                       severity, labels, proposal, by)
        _set_ask_fields(entry, options, recommend, check, due)
        errors = _ask_problems(entry)
        if errors:
            raise ReportError("\n".join(errors))
        store["entries"].append(entry)
    return eid


def _headline_with_grade(entry: dict) -> str:
    return entry["headline"] + (f" · {entry['grade']}" if entry.get("grade") else "")


def find_by_headline(slice_dir: Path | str, section: str,
                     headline: str) -> str | None:
    """The id of the entry of that kind (or, imported, under that old
    section) whose headline is `headline`, live or struck, or None. The
    comparison is whitespace-collapsed on both sides, a ` · <grade>` tail
    ignored. For a writer that must enter a thing once however often it
    runs — a struck entry counts, because striking is how the entry was
    settled, not a request to write it again."""
    kind = _kind_of(section)
    want = _collapse(headline)
    for entry in _read_store(slice_dir)["entries"]:
        if _home_kind(entry) != kind:
            continue
        if want in (entry["headline"], _headline_with_grade(entry)):
            return entry["id"]
    return None


# An action the run needs before it starts — the plan-writer heads it
# `Before /dev:run-slice: …`. After-run ones (the plan loop's push-hold and
# settle-V entries) never match.
PRERUN_HEADLINE_RE = re.compile(r"^before\s+`?/dev:run-slice\b`?", re.IGNORECASE)


def is_prerun(entry: dict) -> bool:
    return (entry.get("kind") == "action"
            and bool(PRERUN_HEADLINE_RE.match(entry.get("headline") or "")))


def prerun_actions(slice_dir: Path | str) -> list[dict]:
    """Every action the run needs before it starts, struck or live, in order
    of arrival: `{id, headline, body, check, struck}`, the body as one text.
    A missing or unreadable store has none."""
    try:
        store = _read_store(slice_dir)
    except ReportError:
        return []
    return [{"id": e["id"], "headline": _headline_with_grade(e),
             "body": "\n".join(e.get("body") or []), "check": e.get("check"),
             "struck": bool(e.get("strike"))}
            for e in store["entries"] if is_prerun(e)]


def live_entries(slice_dir: Path | str, section: str) -> list[tuple[str, str]]:
    """(id, headline) of every live entry of that kind (or, imported, under
    that old section), in order of arrival — the headline with its
    ` · <grade>` tail, as `find_by_headline` compares it."""
    kind = _kind_of(section)
    return [(e["id"], _headline_with_grade(e))
            for e in _read_store(slice_dir)["entries"]
            if _home_kind(e) == kind and not e.get("strike")]


def add_note(slice_dir: Path | str, eid: str, by: str, text: str,
             date: str | None = None, relabel: dict | None = None) -> str:
    """Add `{by, date, text}` to an entry's notes — struck or not. Returns
    the paragraph as the report shows it."""
    lines = _lines(text.strip())
    if not lines:
        raise ReportError("a note needs text")
    who = _collapse(by)
    if not who:
        raise ReportError("a note needs --by")
    day = _date(date)
    note = {"by": who, "date": day, "text": lines}
    if relabel:
        note["relabel"] = relabel
    with _writing(slice_dir) as store:
        _find(store, eid)["notes"].append(note)
    return _note_text(note)


def _strike_tail(strike: dict) -> str:
    """What a struck heading carries after its `~~…~~`: the reason, the
    commit where the reason does not name it, the striker."""
    tail = strike["reason"]
    commit = strike.get("commit")
    if commit and commit not in tail:
        tail += f" ({commit})"
    if strike.get("by"):
        tail += f"; struck by {strike['by']}"
    return tail


def _struck_heading(entry: dict) -> str:
    return (f"### ~~{entry['id']} — {_headline_with_grade(entry)}~~ — "
            + _strike_tail(entry["strike"]))


def _strike(entry: dict, reason: str, by: str | None, commit: str | None,
            date: str) -> None:
    if entry.get("strike"):
        raise ReportError(f"{entry['id']} is already struck: "
                          + _struck_heading(entry)[4:] + ". A note adds to it.")
    reason = _collapse(reason)
    if not reason:
        raise ReportError("a strike needs a --reason")
    entry["strike"] = {"reason": reason, "by": _collapse(by) or None,
                       "date": date, "commit": _collapse(commit) or None}


def strike_entry(slice_dir: Path | str, eid: str, reason: str,
                 by: str | None = None, commit: str | None = None,
                 date: str | None = None) -> str:
    """Strike a live entry; returns its struck heading. The entry stays in
    the store — in the Record of the report."""
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        _strike(entry, reason, by, commit, day)
        return _struck_heading(entry)


UNLABELLED_MARK = "—"


def _label_changes(old: dict | None, new: dict) -> dict:
    old = old or {}
    return {k: [old.get(k), new.get(k)] for k in LABELS
            if old.get(k) != new.get(k)}


def _relabel(entry: dict, who: str, day: str, note_lines: list[str],
             kind: str | None, labels: dict | None,
             slice_dir: Path | str) -> dict:
    """Apply a relabel to `entry` in place — the merged labels, the kind —
    and append the note that says what changed, its `relabel` record the
    (old, new) of every key it changed. Returns the note."""
    eid = entry["id"]
    old_kind = entry.get("kind")
    new_kind = kind or old_kind
    if new_kind not in KINDS:
        raise ReportError(f"{eid} has no kind; relabel it with --kind")
    old = effective_labels(entry) or {}
    given = {k: v for k, v in (labels or {}).items() if v is not None}
    clear = _clears_for(given)
    if clear:
        del given["for"]
    dropped = ([k for k in old if k not in CARRIES[new_kind] and k not in given]
               if new_kind != old_kind else [])
    merged = {k: v for k, v in old.items() if k not in dropped}
    merged.update(given)
    if clear:
        merged.pop("for", None)
    merged = _ordered_labels(merged)
    errors = check_labels(new_kind, merged, entry.get("consequence"),
                          slice_dir, given=labels or {}, relabel=True)
    if errors:
        raise ReportError("\n".join(errors))
    changes = _label_changes(entry.get("labels"), merged)
    if new_kind != old_kind:
        changes = {"kind": [old_kind, new_kind], **changes}
    if not changes:
        raise ReportError(f"relabel changes nothing on {eid}: its labels "
                          "are already those")
    entry["kind"] = new_kind
    entry["labels"] = merged
    said = ", ".join(f"{k}: {o or UNLABELLED_MARK} → {n or UNLABELLED_MARK}"
                     for k, (o, n) in changes.items())
    if dropped:
        said += (f"; dropped {_join(dropped)}, which a"
                 f"{'n' if new_kind[0] in 'aeiou' else ''} {new_kind} does not carry")
    text = [f"relabelled ({said}): {note_lines[0]}", *note_lines[1:]]
    record = {"by": who, "date": day, "text": text, "relabel": changes}
    entry["notes"].append(record)
    return record


def relabel_entry(slice_dir: Path | str, eid: str, by: str, note: str,
                  kind: str | None = None, labels: dict | None = None,
                  date: str | None = None, dry_run: bool = False) -> str:
    """Merge `labels` into an entry's (an unlabelled one gets its first),
    correct its kind where given — the id stays — and leave a note saying
    what changed and why; `for` given as `none` (FOR_CLEAR) removes the
    label. The refusals of `append` apply to the labels as they are after
    the change, but not the one against the Consequence line (that is the
    author's text; the wrap-up corrects a label from the code), and `for`
    is checked only where the call gives one.
    A new kind drops every old label it does not carry (CARRIES), and the
    note names them. Returns the note's paragraph. With `dry_run`, the same
    relabel is made on a copy of the store and nothing is written: the
    paragraph is followed by a `route:` line — the section of the report
    and the Route the entry would take after it."""
    note_lines = _lines(note.strip())
    if not note_lines:
        raise ReportError("relabel needs a --note: what was found")
    who = _collapse(by)
    if not who:
        raise ReportError("relabel needs --by")
    day = _date(date)
    if dry_run:
        entry = _find(_read_store(slice_dir), eid)
        record = _relabel(entry, who, day, note_lines, kind, labels, slice_dir)
        key, words = route(entry, touched_repos(slice_dir), slice_stages(slice_dir))
        return f"{_note_text(record)}\nroute: {report_section(key)} — {words}"
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        return _note_text(_relabel(entry, who, day, note_lines, kind, labels,
                                   slice_dir))


def _amended(entry: dict, slice_dir: Path | str, headline: str | None,
             body: str | None, consequence: str | None, proposal: str | None,
             provenance: str | None, severity: str | None,
             labels: dict | None, asked: dict | None = None) -> dict:
    """A copy of `entry` with each field given in place of its own, and the
    checks `append` makes run on the result: the labels as they would be
    stored (the given merged over the entry's, `for` given as `none`
    removed), against the Consequence line as it would read, what an
    author owes by kind (`author_problems`), and the block's fields
    (`asked`: options, recommend, check, due). Refused — every refusal in
    one error — when it would not pass them."""
    kind = entry["kind"]
    new = json.loads(json.dumps(entry))
    errors: list[str] = []
    if headline is not None:
        new["headline"] = _collapse(headline)
        if not new["headline"]:
            errors.append("--headline needs text: the claim itself")
    if body is not None:
        new["body"] = _lines(body)
        if not new["body"]:
            errors.append("--body needs text")
    if consequence is not None:
        new["consequence"] = _collapse(consequence)
        if not new["consequence"]:
            errors.append("--consequence needs text: what an operator or user "
                          "experiences, or none")
    if proposal is not None:
        new["proposal"] = _collapse(proposal) or None
    if provenance is not None:
        new["evidence"], new["author"] = _split_provenance(provenance)
    if severity is not None:
        if severity not in SEVERITIES:
            errors.append(f"unknown severity {severity!r}; one of " + ", ".join(SEVERITIES))
        new["grade"] = severity
    _set_ask_fields(new, **(asked or {}))
    given = {k: v for k, v in (labels or {}).items() if v is not None}
    merged = dict(entry.get("labels") or {})
    if given:
        clear = _clears_for(given)
        if clear:
            del given["for"]
            merged.pop("for", None)
        given = normalise_for(given, slice_dir)
        merged.update(given)
        new["labels"] = merged = _ordered_labels(merged)
    errors += check_labels(kind, merged, new["consequence"], slice_dir, given=given)
    errors += author_problems(new)
    if errors:
        raise ReportError("\n".join(errors))
    return new


def amend_entry(slice_dir: Path | str, eid: str, *, by: str | None = None,
                headline: str | None = None, body: str | None = None,
                consequence: str | None = None, proposal: str | None = None,
                provenance: str | None = None, severity: str | None = None,
                labels: dict | None = None, options=None,
                recommend: str | None = None, check: str | None = None,
                due: str | None = None) -> str:
    """Correct a live entry: each field given replaces the entry's, the
    labels merged over its own (`for` given as `none`, the FOR_CLEAR,
    removes the label), and the result checked as `append` checks an
    author's entry (`_amended`); `by` replaces who wrote it. Anyone with the
    pen amends, until the
    report is rendered at the run's end. No note is left; the id and the
    kind never change. Returns the entry's heading."""
    asked = {"options": options, "recommend": recommend, "check": check, "due": due}
    fields = (by, headline, body, consequence, proposal, provenance, severity,
              *asked.values())
    if all(f is None for f in fields) and not any(
            v is not None for v in (labels or {}).values()):
        raise ReportError("amend needs a field to replace: any of `append`'s flags "
                          "but --kind")
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        eid = entry["id"]
        if entry.get("strike"):
            raise ReportError(f"{eid} is struck — a struck entry is settled; a note "
                              "adds to it")
        new = _amended(entry, slice_dir, headline, body, consequence, proposal,
                       provenance, severity, labels, asked)
        if _collapse(by):
            new["by"] = _collapse(by)
        if new == entry:
            raise ReportError(f"amend changes nothing on {eid}: it already holds that")
        entry.clear()
        entry.update(new)
        return _heading(entry)


# The wrap-up's marks: outcome → (the flag that makes it, what its note says
# the wrap-up did). A card request and a request for the operator's word are
# proposals (`propose --card`, `propose --word`); a look that changed nothing
# is a note (`note --left`).
MARKS = {
    "left": ("note --left", "looked and left it"),
    "card": ("propose --card", "asks for a card"),
    "word": ("propose --word", "asks for the operator's word"),
}


# A card request's section — the card it files, as `show --card` prints it:
# its heading, then its body, consequence and provenance — is at most this
# many words: the tracker's limit for a card an agent writes ("descriptions are
# pointers, not mirrors"). What does not fit stays in the record, where the
# author's text and every note already are.
CARD_WORDS_MAX = 200


def _card_text(entry: dict, vmap: dict[str, dict]) -> str:
    """The card an entry files once its card request is agreed: the
    section's heading, then its paragraphs."""
    return "\n\n".join([_ask_headline(entry, vmap), *_section(entry)])


def _card_problems(entry: dict, vmap: dict[str, dict]) -> list[str]:
    """What keeps an entry's section from being the card it files: more
    words than `CARD_WORDS_MAX`, heading and body counted."""
    words = len(_card_text(entry, vmap).split())
    if words <= CARD_WORDS_MAX:
        return []
    return [f"{entry['id']}'s section is {words} words, and a card request's is at most "
            f"{CARD_WORDS_MAX}, heading and body counted: the tracker's limit for a card an "
            f"agent writes. `restate` it shorter, the card's text alone: the detail stays in "
            f"the record, where the author's text and every note already are"]


def _proposal_note(who: str, day: str, old: str) -> dict:
    return {"by": who, "date": day, "text": [f"proposal replaced — was: {old}"],
            "history": "proposal"}


def _set_proposal(entry: dict, who: str, day: str, text: str) -> None:
    """Give the entry `text` as its proposal; one it already had, and that
    says something else, stays as a history note signed by whoever replaced
    it."""
    old = entry.get("proposal")
    if old and old != text:
        entry["notes"].append(_proposal_note(who, day, old))
    entry.pop("proposed", None)
    entry["proposal"] = text


def _mark(entry: dict, outcome: str, who: str, day: str, lines: list[str]) -> None:
    """The wrap-up's mark on the entry; a mark it had already stays, as a
    history note."""
    prior = entry.get("wrap_up") or None
    if prior:
        entry["notes"].append(_mark_note(prior))
    entry["wrap_up"] = {"outcome": outcome, "by": who, "date": day, "text": lines}


def propose_entry(slice_dir: Path | str, eid: str, by: str, text: str,
                  date: str | None = None, mark: str | None = None) -> str:
    """Give a live entry its proposal — what its author would do about it
    and why — or replace the one it has, the old one kept as a note. With
    `mark`, the proposal is the wrap-up's mark too: `card` asks for a card,
    and makes the entry a card request; `word` asks for the operator's word
    on an edit a rule of the project reserves for them, and brings the entry
    to them, whatever the table's route. Returns the Proposal line."""
    if mark is not None and mark not in ("card", "word"):
        raise ReportError(f"unknown mark {mark!r}; card or word")
    proposal = _collapse(text)
    if not proposal:
        raise ReportError("a proposal needs --text")
    who = _collapse(by)
    if not who:
        raise ReportError("a proposal needs --by")
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        if entry.get("strike"):
            raise ReportError(f"{eid} is struck — a struck entry is settled")
        if mark is not None and not entry.get("restated"):
            what = ("the card's summary, its body the card's text" if mark == "card"
                    else "the edit asked for, its body the exact edit and the rule "
                         "that reserves it")
            raise ReportError(
                f"{entry['id']} is not restated: the section is what Agree carries out, so "
                f"`restate` it first — its heading {what} — and propose in one line")
        if mark == "card":
            problems = _card_problems(entry, _verification(slice_dir))
            if problems:
                raise ReportError(problems[0])
        _set_proposal(entry, who, day, proposal)
        if mark is not None:
            _mark(entry, mark, who, day, _lines(text.strip()))
    return f"**Proposal:** {proposal}"


def _restated_note(who: str, day: str, old: dict) -> dict:
    """The history note a restatement becomes when a later one replaces it."""
    return {"by": who, "date": day,
            "text": [f"restatement replaced — was: {old['headline']}", "", *old["body"]],
            "history": "restated"}


def restate_entry(slice_dir: Path | str, eid: str, by: str, headline: str, body: str,
                  consequence: str | None = None, provenance: str | None = None,
                  date: str | None = None) -> str:
    """Give a live entry the section the document shows for it: its
    heading, its body, and the consequence and the provenance where given,
    in place of its author's — the current story, told once, where a note
    would have told it again under the author's. The author's text stays
    in the entry, and the record shows it; a restatement already there,
    and that says something else, stays as a history note. Returns the
    section's heading."""
    who = _collapse(by)
    if not who:
        raise ReportError("a restatement needs --by")
    head = _collapse(headline)
    if not head:
        raise ReportError("a restatement needs --headline: the ask, in one line")
    lines = _lines(body)
    if not lines:
        raise ReportError("a restatement needs --body: the story the section tells")
    day = _date(date)
    new: dict = {"by": who, "date": day, "headline": head, "body": lines}
    if _collapse(consequence):
        new["consequence"] = _collapse(consequence)
    evidence, author = _split_provenance(provenance)
    if evidence or author:
        new.update(evidence=evidence, author=author)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        if entry.get("strike"):
            raise ReportError(f"{entry['id']} is struck — a struck entry is settled")
        old = entry.get("restated")
        if (entry.get("wrap_up") or {}).get("outcome") == "card":
            problems = _card_problems({**entry, "restated": new}, _verification(slice_dir))
            if problems:
                raise ReportError(problems[0])
        said = {k: v for k, v in new.items() if k not in ("by", "date")}
        if old and {k: v for k, v in old.items() if k not in ("by", "date")} != said:
            entry["notes"].append(_restated_note(who, day, old))
        entry["restated"] = new
    return f"## {head}"


def _mark_note(mark: dict) -> dict:
    """The history note a mark becomes when a later mark replaces it."""
    return {"by": mark["by"], "date": mark["date"], "text": _wrap_up_lines(mark),
            "history": "wrap-up"}


def _mark_text(mark: dict) -> str:
    return _note_text({"by": mark["by"], "date": mark["date"],
                       "text": _wrap_up_lines(mark)})


def leave_entry(slice_dir: Path | str, eid: str, by: str, text: str,
                date: str | None = None) -> str:
    """The wrap-up looked at an entry and changed nothing (`note --left`):
    what waited for it is closed; every other route stands. Returns the
    mark as the record shows it."""
    lines = _lines(text.strip())
    if not lines:
        raise ReportError("the wrap-up's mark needs --text")
    who = _collapse(by)
    if not who:
        raise ReportError("the wrap-up's mark needs --by")
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        if entry.get("strike"):
            raise ReportError(f"{eid} is struck — a struck entry is settled")
        _mark(entry, "left", who, day, lines)
        return _mark_text(entry["wrap_up"])


# -- the continuation: the answers read back, executed, the report closed ------

def _ruled(entry: dict) -> bool:
    """Whether the entry holds a ruling: the answer lines read back from the
    document, or the words a report before 0.10 recorded."""
    ruling = entry.get("ruling") or {}
    return bool(ruling.get("answer_lines") or ruling.get("words"))


def _pending(entry: dict) -> bool:
    """A ruling nobody has carried out yet: the entry is live and holds one."""
    return not entry.get("strike") and _ruled(entry) and not entry["ruling"].get("did")


def _answered_by(lines: dict) -> str:
    """Who the answer lines say answered: a handle, or Pilot, whose `by` is
    `agent` or absent."""
    by = lines.get("by", asks.AGENT)
    return PILOT if by == asks.AGENT else by


def _striker(entry: dict) -> str:
    """Who a strike on a ruling is signed by: the operator's ruling, or
    Pilot's where Pilot chose the answer."""
    lines = (entry.get("ruling") or {}).get("answer_lines") or {}
    return PILOT_RULED_BY if lines and _answered_by(lines) == PILOT else RULED_BY


def _absorb(store: dict, blocks: dict[str, dict], day: str) -> list[str]:
    """The answer lines of each block into the entry of its id: the ruling's
    `answer_lines`. `deferred` closes the entry as Pilot's (struck, its `to`
    named); an action's `done` is what was done on it, which strikes it.
    A block with no answer lines — never answered, or Undone — drops a
    ruling nobody carried out. Returns a line per block."""
    by_id = {e["id"]: e for e in store["entries"]}
    unknown = [bid for bid in blocks if bid not in by_id]
    if unknown:
        raise ReportError(f"close-out.md holds block{'s' if len(unknown) > 1 else ''} "
                          f"{', '.join(unknown)}, which no entry of the store is: it is "
                          "not this store's document")
    out = []
    for bid, block in blocks.items():
        entry, lines = by_id[bid], block["lines"]
        ruling = entry.get("ruling") or {}
        if not lines:
            if _pending(entry):
                entry["ruling"] = None
            out.append(f"{bid}  open")
            continue
        if ruling.get("answer_lines") != lines:
            entry["ruling"] = ruling = {"answer_lines": lines, "did": ruling.get("did"),
                                        "date": day}
        who = _answered_by(lines)
        if not entry.get("strike"):
            if lines.get("answer") == asks.DEFERRED:
                _strike(entry, f"deferred to {lines.get('to')} by {who}", PILOT, None, day)
            elif "done" in lines:
                ruling["did"] = _collapse(lines.get("note")) or f"done {lines['done']}"
                _strike(entry, f"done by {who}: {ruling['did']}", _striker(entry), None, day)
        out.append(f"{bid}  {asks.state({'answer_lines': lines})}")
    return out


def absorb_report(slice_dir: Path | str, date: str | None = None) -> list[str]:
    """Read close-out.md, as Pilot wrote it back, into the store: every
    block's answer lines into its entry's ruling (`_absorb`). Refused,
    nothing written, on a document Pilot's reader would refuse or one whose
    blocks are no entries of the store. Returns a line per block, its id and
    state."""
    day = _date(date)
    path = report_path(slice_dir)
    with _writing(slice_dir) as store:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ReportError(f"{path} cannot be read: {e}") from None
        try:
            blocks = asks.read_back(text)
        except asks.AskError as e:
            raise ReportError(f"{path} cannot be read back: {e}") from None
        if not blocks:
            raise ReportError(f"{path} holds no block: there is nothing to read back")
        return _absorb(store, blocks, day)


def rule_entry(slice_dir: Path | str, eid: str, did: str,
               commit: str | None = None, date: str | None = None) -> str:
    """Record what the continuation did on an entry's ruling — "carded as
    P-12", "folded into slice 031", "closed" — which strikes the entry. The
    ruling is the answer lines `absorb` read back; an entry without one has
    nothing to act on. Returns the ruling as the record shows it."""
    did = _collapse(did)
    if not did:
        raise ReportError("--did is empty")
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        if not _ruled(entry):
            raise ReportError(f"{entry['id']} holds no ruling to act on: `absorb` reads "
                              "the answers of close-out.md back first")
        if entry["ruling"].get("did"):
            raise ReportError(f"{entry['id']} is done already: {entry['ruling']['did']}")
        entry["ruling"]["did"] = did
        if not entry.get("strike"):
            _strike(entry, did, _striker(entry), commit, day)
        elif commit and not entry["strike"].get("commit"):
            entry["strike"]["commit"] = _collapse(commit)
        return f"{entry['id']}: {_ruling_text(entry)}"


def close_report(slice_dir: Path | str, by: str | None = None,
                 date: str | None = None) -> tuple[int, list[str]]:
    """Close the report once the continuation has carried out its answers:
    every entry still live is struck as closed with the report, but one that
    holds a ruling nobody carried out, which stays, and a report that keeps
    one is not closed. Returns how many entries were closed, and the ids
    that stay."""
    day = _date(date)
    who = _collapse(by) or None
    with _writing(slice_dir) as store:
        if store.get("closed"):
            raise ReportError(f"the report was closed on {store['closed']['date']}")
        n, stay = 0, []
        for entry in store["entries"]:
            if entry.get("strike"):
                continue
            if _pending(entry):
                stay.append(entry["id"])
                continue
            _strike(entry, f"closed with the report, {day}", who, None, day)
            n += 1
        if not stay:
            store["closed"] = {"date": day, "by": who}
        return n, stay


VERIFICATION_NAME = "verification.json"
SETTLE_VERDICTS = ("pass", "fail")
# A push hold's action, as plan_loop.py seeds it, lists the criteria owed
# after the push under this paragraph, one `- V01 — <description>` row each.
_HOLD_CRITERIA = "Criteria owed after that push"
_HOLD_ROW_RE = re.compile(r"^- (?P<vid>V\d+)\b")


def _verification_doc(slice_dir: Path | str) -> tuple[Path, str, dict]:
    """verification.json's path, its text and its data — refused when it is
    missing, unreadable, or not an object with an `items` list."""
    path = Path(slice_dir) / VERIFICATION_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ReportError(f"{path} does not exist — no criterion to settle") from None
    except OSError as e:
        raise ReportError(f"{path} is unreadable: {e}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ReportError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ReportError(f"{path} is not an object with an `items` list")
    return path, raw, data


def _dump_like(raw: str, data) -> str:
    """`data` as JSON written the way `raw`, the file it replaces, is: the
    first of ensure_ascii off or on × indent 2 or 4 whose dump of `raw`'s
    own data gives `raw` back byte for byte, its trailing newline or none
    kept; when none does, the one whose dump differs from it in the fewest
    lines. The slices' verification.json files are written both ways — one
    holds `\\u2014` escapes, another a literal `—` — so no one setting is
    safe: a round-trip under the wrong one rewrites every line that holds
    an escape, and a one-item change becomes a diff of the whole file."""
    original = json.loads(raw)
    newline = "\n" if raw.endswith("\n") else ""
    old = raw.splitlines()

    def dump(obj, ensure_ascii: bool, indent: int) -> str:
        return json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii) + newline

    def lines_changed(fmt: tuple[bool, int]) -> int:
        matcher = difflib.SequenceMatcher(None, old, dump(original, *fmt).splitlines(),
                                          autojunk=False)
        return sum(max(i2 - i1, j2 - j1)
                   for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal")

    formats = [(ensure_ascii, indent) for ensure_ascii in (False, True) for indent in (2, 4)]
    fmt = next((f for f in formats if dump(original, *f) == raw), None)
    if fmt is None:
        fmt = min(formats, key=lines_changed)
    return dump(data, *fmt)


def _hold_criteria(entry: dict) -> list[str]:
    """The criteria a push hold's action lists as owed after the push: the
    `- V01 — …` rows under its `Criteria owed after that push` paragraph,
    up to the first other line after them; none for any other entry."""
    vids: list[str] = []
    under = False
    for line in entry.get("body") or []:
        if not under:
            under = line.startswith(_HOLD_CRITERIA)
            continue
        m = _HOLD_ROW_RE.match(line)
        if m:
            vids.append(m.group("vid"))
        elif line.strip() and vids:
            break
    return vids


def _settle_entries(store: dict, vid: str, verdicts: dict, by: str | None,
                    day: str) -> list[str]:
    """The live actions a settle of `vid` answers: the `Settle <vid> after …`
    one is struck; a push hold's that lists `vid` is struck once every
    criterion it lists is `pass` or `fail` in `verdicts` (verification.json
    as the settle leaves it), and takes a note naming what is still owed
    until then. Returns one line per entry changed."""
    done: list[str] = []
    for entry in store["entries"]:
        if entry.get("strike"):
            continue
        m = _OWED_HEADLINE_RE.match(entry.get("headline") or "")
        if m and m.group("vid") == vid:
            _strike(entry, f"settled {vid} {verdicts[vid]} in {VERIFICATION_NAME}", by,
                    None, day)
            done.append(_struck_heading(entry))
            continue
        listed = list(dict.fromkeys(_hold_criteria(entry)))
        if vid not in listed:
            continue
        owed = [v for v in listed if verdicts.get(v) not in SETTLE_VERDICTS]
        if not owed:
            settled = ", ".join(f"{v} {verdicts[v]}" for v in listed)
            _strike(entry, f"settled {settled} in {VERIFICATION_NAME}", by, None, day)
            done.append(_struck_heading(entry))
            continue
        note = {"by": _collapse(by) or "settle", "date": day,
                "text": _lines(f"{vid} settled {verdicts[vid]} in {VERIFICATION_NAME}; "
                               f"{', '.join(owed)} still owed.")}
        entry["notes"].append(note)
        done.append(f"{entry['id']} noted: {_note_text(note)}")
    return done


def settle_criterion(slice_dir: Path | str, vid: str, verdict: str,
                     evidence: list[str], rationale: str | None = None,
                     by: str | None = None) -> list[str]:
    """Settle a criterion owed after an operator's action, once it has
    happened: its verdict, rationale and evidence into verification.json —
    `owed_after` kept, the record that it was proven after the run, the
    evidence added after the test phase's, the rationale naming the action
    and the date unless one is given — and the actions that waited on it
    struck or noted (`_settle_entries`). Refused, nothing written, on a
    criterion without `owed_after` or with a verdict other than `owed` or
    none. verification.json is written after the store, so a store write
    refused leaves both as they were; a slice without a store has nothing
    to strike and gets verification.json alone. An action the read-back
    struck as done already stays as it is. Returns one line per thing
    done."""
    vid = vid.strip()
    if verdict not in SETTLE_VERDICTS:
        raise ReportError(f"unknown verdict {verdict!r}; one of " + ", ".join(SETTLE_VERDICTS))
    evidence = [e.strip() for e in evidence]
    if not evidence or not all(evidence):
        raise ReportError("settle needs --evidence: the operator's words, or what was "
                          "observed once the action had happened")
    if rationale is not None and not rationale.strip():
        raise ReportError("--rationale is empty")
    day = _date(None)
    with _locked(slice_dir):
        path, raw, data = _verification_doc(slice_dir)
        item = next((i for i in data["items"]
                     if isinstance(i, dict) and i.get("id") == vid), None)
        if item is None:
            raise ReportError(f"no criterion {vid} in {path}")
        after = item.get("owed_after")
        if not isinstance(after, str) or not after.strip():
            raise ReportError(f"{vid} has no owed_after — settle takes a criterion owed "
                              "after an operator's action; the test phase settles the rest")
        held = item.get("verdict")
        if held not in (None, "owed"):
            raise ReportError(f"{vid}'s verdict is {held!r} already — settle takes a "
                              "criterion still owed (verdict owed, or none)")
        kept = item.get("evidence")
        if isinstance(kept, str):
            kept = [kept] if kept.strip() else []
        elif not isinstance(kept, list):
            kept = [kept] if kept else []
        item["verdict"] = verdict
        item["rationale"] = (rationale.strip() if rationale is not None
                             else f"Settled {verdict} after {_collapse(after)}, {day}.")
        item["evidence"] = [*kept, *evidence]
        text = _dump_like(raw, data)
        verdicts = {i.get("id"): i.get("verdict") for i in data["items"]
                    if isinstance(i, dict)}
        done = [f"{vid} settled {verdict} in {VERIFICATION_NAME}"]
        if store_path(slice_dir).exists():
            with _writing(slice_dir) as store:
                done += _settle_entries(store, vid, verdicts, by, day)
        _write_atomic(path, text)
    return done


# -- labels: the checks of `append` and `relabel` -----------------------------

# A phase heading as the run loop's parser reads one (run_loop.PHASE_RE;
# run_loop imports this file, so it is not imported from there).
PHASE_RE = re.compile(r"^###\s+P([A-Za-z0-9]+)\s+—\s+(.+?)\s*$")


def _stage(folder: Path) -> str:
    """`planned` for a slice folder that holds a state.json, or a plan.md
    with a phase heading — its run reads the plan, never slice.md again;
    `unplanned` otherwise. An unreadable plan.md has no phases."""
    if (folder / "state.json").exists():
        return "planned"
    try:
        plan = (folder / "plan.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unplanned"
    return "planned" if any(PHASE_RE.match(line) for line in plan.splitlines()) \
        else "unplanned"


def _slices_root(slice_dir: Path | str) -> Path | None:
    """The nearest `slices` ancestor of the slice folder, resolved; None
    without one. Its parent is the spec repo's root."""
    here = Path(slice_dir).resolve()
    return next((p for p in here.parents if p.name == "slices"), None)


def _folders_to_run(slice_dir: Path | str) -> dict[int, Path] | None:
    """Number → folder of every slice still to run: a `<number>_*` folder
    directly under the nearest `slices` ancestor of the slice folder, or
    under its `backlog/` — the slice itself left out, the first folder
    found for a number taken. None without such an ancestor."""
    here = Path(slice_dir).resolve()
    root = _slices_root(here)
    if root is None:
        return None
    out: dict[int, Path] = {}
    for parent in (root, root / "backlog"):
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            m = re.match(r"(\d+)_", child.name)
            if m and child.is_dir() and child.resolve() != here \
                    and int(m.group(1)) not in out:
                out[int(m.group(1))] = child
    return out


_FOLDER_RE = re.compile(r"(\d+)_")
# The stage of a slice folder that exists and is no longer to run: it has
# run, or was cancelled (`slice_stages`).
PAST = "past"
# The width a `for` naming a slice not created yet is padded to when the
# spec repo has no slice folder to take it from.
FOR_WIDTH = 3


def _slice_folders(root: Path) -> list[Path]:
    """Every slice folder under the `slices` root, at any depth: a
    `<number>_*` directory, whose own contents are not searched — every
    other directory (backlog/, completed/, cancelled/ …) is. Hidden
    directories and symlinked ones that are no slice folder are skipped."""
    out: list[Path] = []
    stack = [root]
    while stack:
        try:
            children = sorted(stack.pop().iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith(".") or not child.is_dir():
                continue
            if _FOLDER_RE.match(child.name):
                out.append(child)
            elif not child.is_symlink():
                stack.append(child)
    return out


def slice_stages(slice_dir: Path | str) -> dict[int, tuple[str, str]] | None:
    """Number → (folder number as written, stage) of every slice folder
    under the nearest `slices` ancestor (`_slice_folders`): `planned` or
    `unplanned` (`_stage`) for one still to run (`_folders_to_run`), `own`
    for the slice itself, PAST for any other — it has run, or was
    cancelled. A number no folder holds is not in it: a slice not created
    yet, which an entry's `for` holds it for. The routes take this map.
    None without a `slices` ancestor."""
    here = Path(slice_dir).resolve()
    to_run = _folders_to_run(here)
    if to_run is None:
        return None
    out = {n: (_FOLDER_RE.match(f.name).group(1), _stage(f)) for n, f in to_run.items()}
    own = _FOLDER_RE.match(here.name)
    if own:
        out.setdefault(int(own.group(1)), (own.group(1), "own"))
    for folder in _slice_folders(_slices_root(here)):
        m = _FOLDER_RE.match(folder.name)
        out.setdefault(int(m.group(1)), (m.group(1), PAST))
    return out


def _for_width(stages: dict[int, tuple[str, str]]) -> int:
    """The width the spec repo writes its folder numbers in: the most
    common, the wider of a tie; FOR_WIDTH without a folder."""
    widths: dict[int, int] = {}
    for written, _ in stages.values():
        widths[len(written)] = widths.get(len(written), 0) + 1
    return max(widths, key=lambda w: (widths[w], w)) if widths else FOR_WIDTH


def _slice_number(target) -> int | None:
    """The slice number a `for` names — `12`, `012` and `012_slug` all
    name 12 — or None for a value that names none."""
    m = re.match(r"(\d+)(?:_|$)", str(target))
    return int(m.group(1)) if m else None


def _flag(label: str) -> str:
    return f"--{label}"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _flags(labels) -> str:
    return _join([_flag(k) for k in labels])


def kind_labels_text() -> str:
    """The labels each kind carries, one indented line per group of kinds
    that carry the same, rendered from REQUIRED and EVENT_PROBLEM — what
    `check_labels` refuses an append without."""
    groups: dict[tuple, list[str]] = {}
    for kind in KINDS:
        groups.setdefault((REQUIRED[kind], kind == "event"), []).append(kind)
    out = []
    for (required, event), kinds in groups.items():
        line = f"  {', '.join(kinds)}: {_flags(required)}"
        if event:
            line += f"; with an --impact other than none also {_flags(EVENT_PROBLEM)}"
        out.append(line)
    return "\n".join(out)


# The pairings `check_labels` refuses an append without, in a dispatch's
# words.
LABEL_PAIRING = """\
They pair on every kind but an improvement: a --consequence that opens
with none takes --impact none or unknown, and only it takes --impact
none; --impact none takes --signal none, and --signal none takes
--impact none or unknown.\
"""

FOR_RULE = ("--for names another slice that should take the entry — one still "
            "to run, or one triage has not created yet, which holds the entry "
            "until it does — never the slice being run: leave it out for an "
            "entry about this one; an entry for a slice already planned or "
            "running comes to the operator, since that run never reads slice.md")

# What `relabel --for` takes to remove the label.
FOR_CLEAR = "none"


def _clears_for(labels: dict) -> bool:
    return str(labels.get("for") or "").strip().lower() == FOR_CLEAR


def check_labels(kind: str, labels: dict, consequence: str | None,
                 slice_dir: Path | str, given: dict | None = None,
                 relabel: bool = False) -> list[str]:
    """What `append` (and `relabel`) refuse, one message per refusal, each
    naming the flag: a label the kind carries that is missing, a label of
    the other family, an impact that contradicts the Consequence line (not
    on a relabel), a signal that contradicts the impact (not on a relabel),
    a benefit of the workflow, a `for` naming no slice still to run (on a
    relabel, only a `for` the call gives: a stored one whose slice has run
    since stops no relabel). `labels` are the entry's labels as they would
    be stored; `given` the flags of this call, for the other-family check
    and a relabel's `for`."""
    errors: list[str] = []
    improvement = kind == "improvement"
    required = list(REQUIRED[kind])
    if kind == "event" and labels.get("impact") not in (None, "none"):
        required += EVENT_PROBLEM
    missing = [k for k in required if labels.get(k) is None]
    if missing:
        errors.append(f"a{'n' if kind[0] in 'aeiou' else ''} {kind} carries "
                      f"{_flags(required)}; missing: {_flags(missing)}")
    other = FIX_FAMILY if improvement else IMPROVEMENT_FAMILY
    wrong = [k for k in other if (given or labels).get(k) is not None]
    if wrong:
        errors.append(f"{_flags(wrong)}: not a label of a{'n' if kind[0] in 'aeiou' else ''}"
                      f" {kind}, which carries {_flags(REQUIRED[kind])}")
    impact, signal = labels.get("impact"), labels.get("signal")
    if not improvement and not relabel:
        if impact is not None and consequence is not None:
            none = opens_with_none(consequence)
            if none and impact not in ("none", "unknown"):
                errors.append(f"--impact {impact} over a --consequence that opens "
                              "with none: an entry nobody would notice has "
                              "--impact none")
            elif not none and impact == "none":
                errors.append("--impact none over a --consequence that is not "
                              "none: say in --impact what is experienced, or "
                              "open the consequence with none")
        if impact == "none" and signal not in (None, "none"):
            errors.append(f"--signal {signal} with --impact none: an entry with "
                          "no impact has nothing to announce — --signal none")
        elif signal == "none" and impact not in (None, "none", "unknown"):
            errors.append(f"--signal none with --impact {impact}: say whether it "
                          "is loud, silent or unknown when it happens")
    if labels.get("benefit") == "workflow":
        errors.append("--benefit workflow: an improvement of the workflow — the "
                      "agents that build slices, their suites and gates, CI, the "
                      "tools they run — is not an entry. Post it to Fieldnotes "
                      "instead: the `fieldnotes` MCP tool `post`, category `idea`")
    target = labels.get("for")
    if target is not None and (not relabel or (given or {}).get("for") is not None):
        number = _slice_number(target)
        stages = slice_stages(slice_dir)
        slot = None if stages is None else stages.get(number)
        if stages is None:
            errors.append(f"--for {target}: the slice folder has no `slices` "
                          "ancestor, so no slice still to run can be named")
        elif number is None:
            errors.append(f"--for {target} names no slice — a slice is named by its "
                          f"number: {FOR_RULE}")
        elif slot and slot[1] == "own":
            errors.append(f"--for {target} is the slice being run: {FOR_RULE}")
        elif slot and slot[1] == PAST:
            errors.append(f"--for {target}: slice {slot[0]} is no longer to run — its "
                          "folder is outside slices/ and slices/backlog/ (it has run, "
                          f"or was cancelled): {FOR_RULE}")
    return errors


def normalise_for(labels: dict, slice_dir: Path | str) -> dict:
    """`for` as the folder's number is written (`12`, `012` and `012_slug`
    all name 012); a slice not created yet at the width the spec repo
    writes its folder numbers in (`_for_width`), so 11 and 011 store
    alike. One `check_labels` refuses — the slice itself, one no longer to
    run — stays as given, so the refusal names it."""
    target = labels.get("for")
    if target is None:
        return labels
    number = _slice_number(target)
    stages = slice_stages(slice_dir)
    if number is None or stages is None:
        return labels
    if number not in stages:
        return {**labels, "for": str(number).zfill(_for_width(stages))}
    written, stage = stages[number]
    return {**labels, "for": written} if stage in ("planned", "unplanned") else labels


# -- the routes (close-out.md § The routes) ------------------------------------

def effective_labels(entry: dict) -> dict | None:
    """The entry's labels — or, for a kind the tool labels itself that
    arrived without any, the tool's."""
    if entry.get("labels") is not None:
        return entry["labels"]
    return tool_labels(entry.get("kind"), entry.get("consequence"))


def touched_repos(slice_dir: Path | str) -> set[str] | None:
    """The basenames of the slice's repositories, read off its state.json:
    every `root` in it — the repositories its phases landed in — plus its
    `target_roots`, those the plan's unfinished phases target, as the run
    loop resolved them at its last plan load. None without a state.json, or
    one that names neither: every repository is then the slice's own."""
    try:
        state = json.loads((Path(slice_dir) / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    roots: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "root" and isinstance(value, str) and value:
                    roots.add(Path(value).name)
                elif key != "history":
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(state)
    targets = state.get("target_roots") if isinstance(state, dict) else None
    if isinstance(targets, list):
        roots.update(Path(value).name for value in targets
                     if isinstance(value, str) and value)
    return roots or None


def _elsewhere(lab: dict, touched: set[str] | None) -> str | None:
    repo = lab.get("repo")
    if touched is None or not repo or repo in touched:
        return None
    return repo


def _severe(entry: dict, lab: dict) -> str | None:
    """`severe` / `graded major` where severity stands in for a close."""
    if entry.get("kind") == "improvement":
        if lab.get("prevents") == "severe":
            return "severe"
    elif lab.get("impact") == "severe" and lab.get("trigger") != "none":
        return "severe"
    return "graded major" if entry.get("grade") == "major" else None


def _risk(why: str) -> tuple[str, str]:
    return "operator:risk", f"to you — a risk: {why}, in place of a close"


def _fold(lab: dict) -> tuple[str, str]:
    return "wrap-up:fold", f"the wrap-up — fold into slice {lab['for']}"


def _for_route(lab: dict, stages: dict | None) -> tuple[str, str] | None:
    """Where the entry's `for` sends it, at the row the fold sits at, by the
    stage `slice_stages` gives the slice it names: a fold into a slice
    still unplanned; to the operator for one planned or running, whose run
    never reads slice.md again; to the operator for one no folder holds,
    not created yet, to hold for it — Pilot defers it to that slice's task;
    None — the table's next rows, as if the label were not there —
    for a slice no longer to run, the slice itself, or a value that names
    no slice. Without `stages` (no `slices` ancestor, no context given), a
    fold."""
    target = lab.get("for")
    if not target:
        return None
    if stages is None:
        return _fold(lab)
    number = _slice_number(target)
    if number is None:
        return None
    slot = stages.get(number)
    if slot is None:
        return ("operator:held",
                f"to you — for slice {target}, which no folder holds yet: hold it for "
                "that slice")
    if slot[1] == "planned":
        return ("operator:action",
                f"to you — an action: slice {target} is planned or running and its run "
                "never reads slice.md; add a phase or rule on its run")
    if slot[1] == "unplanned":
        return _fold(lab)
    return None


def _card_or_close(repo: str, card: bool) -> tuple[str, str]:
    where = f"the fix lives in {repo}, which the slice did not touch"
    return ("card:table", f"card request — {where}") if card \
        else ("closed:elsewhere", f"closed — {where}")


def _route_fix(entry: dict, lab: dict, touched: set[str] | None,
               stages: dict | None = None) -> tuple[str, str]:
    """What should be fixed — every kind but `improvement`: the first row
    that fits."""
    kind = entry.get("kind")
    trigger = lab.get("trigger", "unknown")
    impact = lab.get("impact", "unknown")
    signal = lab.get("signal", "unknown")
    no_impact = impact == "none" or trigger == "none"
    # Row 8's test: it has an impact, and shows in normal use, or on an
    # ordinary condition without saying so itself.
    shows = impact != "none" and (
        trigger == "normal-use"
        or (trigger == "ordinary-condition" and signal != "loud"))
    if kind == "action":                                            # 1
        return "operator:action", "to you — an action"
    if kind == "decision":                                          # 2
        return "operator:decision", "to you — a decision"
    if kind == "event" and no_impact:                               # 3
        return "record", "the record"
    taken = _for_route(lab, stages)
    if taken:                                                       # 4
        return taken
    repo = _elsewhere(lab, touched)
    if repo:                                                        # 5
        # An unknown trigger counts as one that shows, an unknown impact as
        # one that has an impact.
        shows_here = shows or (impact != "none" and trigger == "unknown")
        return _card_or_close(repo, shows_here or bool(_severe(entry, lab)))
    if kind == "prose" or (lab.get("fix") in ("one-edit", "several-places")
                           and lab.get("area") != "sensitive"):     # 6
        return "wrap-up:fix", "the wrap-up — fix"
    unknown = [k for k, v in (("trigger", trigger), ("impact", impact))
               if v == "unknown"]
    if unknown:                                                     # 7
        what = " and ".join(unknown)
        verb = "are" if len(unknown) > 1 else "is"
        return "wrap-up:look", f"the wrap-up — look: its {what} {verb} unknown"
    if shows:                                                       # 8
        return ("wrap-up:fix-or-card",
                "the wrap-up — fix within its bar, or ask for a card")
    severe = _severe(entry, lab)
    if severe:                                                      # 9
        return _risk(severe)
    if no_impact:                                                   # 10
        return "closed:no-impact", "closed — it has no impact"
    if trigger == "fault":
        return "closed:fault", "closed — it needs a fault"
    if trigger == "future-change":
        return "closed:future-change", "closed — it cannot show with the code as it is"
    return "closed:loud", "closed — it is loud on an ordinary condition"


def _route_improvement(entry: dict, lab: dict, touched: set[str] | None,
                       stages: dict | None = None) -> tuple[str, str]:
    """What could be better: the first row that fits."""
    taken = _for_route(lab, stages)
    if taken:                                                       # 1
        return taken
    change = lab.get("change")
    if (change in ("adjust", "remove")
            and lab.get("size") in ("one-edit", "several-places")
            and lab.get("product-call") == "no"):                    # 2
        repo = _elsewhere(lab, touched)
        if repo:
            return _card_or_close(repo, bool(_severe(entry, lab)))
        return "wrap-up:improvement", "the wrap-up — a small change, within its bar"
    if change == "add" and lab.get("felt") in UNFELT:
        severe = _severe(entry, lab)
        if severe:                                                  # 3
            return _risk(severe)
        return ("closed:unfelt", "closed — it adds something for a benefit "  # 4
                "that is not felt in use")
    return "operator:improvement", "to you — an improvement"        # 5


def table_route(entry: dict, touched: set[str] | None = None,
                stages: dict | None = None) -> tuple[str, str]:
    """(key, the Route line's words) of a live entry by the tables alone —
    the wrap-up's mark not applied. `unlabelled` when the entry has no
    labels and is not a kind the tool labels itself. `touched` is
    `touched_repos()`, `stages` `slice_stages()`, of the slice."""
    lab = effective_labels(entry)
    if lab is None or entry.get("kind") not in KINDS:
        return "unlabelled", "none yet — the entry has no labels"
    if entry["kind"] == "improvement":
        return _route_improvement(entry, lab, touched, stages)
    return _route_fix(entry, lab, touched, stages)


def route(entry: dict, touched: set[str] | None = None,
          stages: dict | None = None) -> tuple[str, str]:
    """(key, the Route line's words) of an entry — computed, never stored.
    A struck entry has none: it is in the record. The wrap-up's mark
    overrides the table: a card asked for makes a card request; the
    operator's word asked for brings the entry to them, whatever the
    table's route; an entry it looked at and left is closed, where the
    table sent it to the wrap-up."""
    if entry.get("strike"):
        return "record", "the record"
    key, words = table_route(entry, touched, stages)
    mark = (entry.get("wrap_up") or {}).get("outcome")
    if mark == "card":
        return "card:wrap-up", "card request — the wrap-up asks for a card"
    if mark == "word":
        return "operator:word", "to you — the wrap-up asks for your word on its edit"
    if mark == "left" and key.startswith("wrap-up:"):
        return "closed:left", "closed — the wrap-up looked and left it"
    return key, words


def report_section(key: str) -> str:
    """The place a route key puts an entry: one of PLACES."""
    head = key.split(":", 1)[0]
    return {"operator": "Comes to you", "card": "Card requests",
            "wrap-up": "For the wrap-up", "unlabelled": "Unlabelled",
            "closed": "Closed", "record": "Record"}[head]


# What the slice's push must not carry, and what its test phase would fail
# as worded. The report is worked after the doc phase, the push follows the
# completion consult, the test phase checks every criterion as worded, and
# nothing reads the report between them — so the run loop hands that consult
# the entries whose author said they are due before the push or the test
# phase (`--due`), and those whose labels say a push would expose them
# (DHCPApp slice 001's B3: production addresses in a public repo's tests;
# AnsibleSpecs slice 058's P3: V15 worded against ruling D2).
_CRITERION_RE = re.compile(r"\bV(\d+)\b")


def owed_before_push(slice_dir: Path | str) -> list[tuple[dict, list[str]]]:
    """(entry, the reasons) for every live entry that may describe what the
    slice's push must not carry, in id order: one due before the push,
    whatever its kind, and one whose impact is `severe` — what a push
    exposes is, by the labels — unless it is an improvement or its fix lives
    in a repository the slice did not touch. Reads the store, never writes
    it."""
    store = _read_store(slice_dir)
    touched = touched_repos(slice_dir)
    out = []
    for entry in store["entries"]:
        if entry.get("strike"):
            continue
        reasons = []
        lab = effective_labels(entry) or {}
        if (entry.get("kind") != "improvement" and lab.get("impact") == "severe"
                and _elsewhere(lab, touched) in (None, "unknown")):
            reasons.append("impact severe")
        if entry.get("due") == "push":
            reasons.append("due before the push")
        if reasons:
            out.append((entry, reasons))
    return sorted(out, key=lambda item: _id_key(item[0]))


def owed_before_test(slice_dir: Path | str) -> list[tuple[dict, list[str]]]:
    """(entry, what it names) for every live entry due before the test
    phase, in id order: the criteria of the slice's verification.json its
    headline, body or proposal names, as verification.json spells them, in
    number order (`V1` names V01) — or, naming none, that it is due. Reads
    the store, never writes it."""
    store = _read_store(slice_dir)
    criteria: dict[int, str] = {}
    for vid in _verification(slice_dir):
        m = re.fullmatch(r"V(\d+)", str(vid))
        if m:
            criteria.setdefault(int(m.group(1)), str(vid))
    out = []
    for entry in store["entries"]:
        if entry.get("strike") or entry.get("due") != "test":
            continue
        texts = [_collapse(entry.get("headline")), _collapse(entry.get("proposal")),
                 *(entry.get("body") or [])]
        named = {int(n) for text in texts for n in _CRITERION_RE.findall(text)}
        held = sorted(named & criteria.keys())
        out.append((entry, [criteria[n] for n in held] or ["due before the test phase"]))
    return sorted(out, key=lambda item: _id_key(item[0]))


# -- worklist ----------------------------------------------------------------

# The --by the wrap-up signs with: its dispatch names none, and it writes
# `wrap-up`, at times with the slice after it (`wrap-up, slice 022`).
_WRAP_UP_BY_RE = re.compile(r"(the )?wrap[- ]up\b", re.I)


def _noted_since(entry: dict) -> bool:
    """Whether someone but the wrap-up wrote a note with `note` on the
    entry since its labels last changed. A relabel's note re-routed the
    entry already, and settles every note before it; a note the tool
    keeps as history (a replaced
    proposal, an earlier mark, the operator's earlier words, which the
    read-back writes too) is nobody's finding."""
    for note in reversed(entry.get("notes") or []):
        if note.get("relabel"):
            return False
        if not note.get("history") and not _WRAP_UP_BY_RE.match(_collapse(note.get("by"))):
            return True
    return False


def _asked(entry: dict, touched: set[str] | None,
           stages: dict | None = None) -> str | None:
    """What the wrap-up is asked to do with an entry, None when it waits for
    nothing. An entry the operator has ruled on is theirs, whatever its
    route: it does not wait. One the table closed is asked a `check` where
    it breaks a flow, else a `recheck` where it was noted since its labels
    last changed (`_noted_since`). One that comes to the operator is asked a
    `note` where it is a risk, else a `vet`: the checks the operator would
    otherwise have to make before ruling."""
    if entry.get("strike") or entry.get("wrap_up") or _ruled(entry):
        return None
    key, _ = table_route(entry, touched, stages)
    if key == "unlabelled":
        return "label — give it its labels from its text"
    if key == "wrap-up:fold":
        return f"fold — fold it into slice {entry['labels']['for']}"
    if key == "wrap-up:fix":
        return "fix"
    if key == "wrap-up:look":
        return "look — give the label the author could not"
    if key == "wrap-up:fix-or-card":
        return "fix or card"
    if key == "wrap-up:improvement":
        return "improve — a small change, within the bar"
    lab = effective_labels(entry) or {}
    if key.startswith("closed:") and lab.get("impact") == "broken":
        what = "signal" if key == "closed:loud" else "trigger"
        return f"check — the {what} the close rests on"
    if key.startswith("closed:") and _noted_since(entry):
        return ("recheck — a note came after the table closed it; check its labels "
                "against the note")
    if key == "operator:risk":
        return "note — note what the code says under it; the entry stays the operator's"
    if key.startswith(("operator:", "card:")):
        return ("vet — before the operator reads it: what a command settles, a proposal "
                "where none, its vehicle")
    return None


def worklist(slice_dir: Path | str) -> list[tuple[dict, str]]:
    """(entry, what is asked) for every entry that waits for the wrap-up,
    in order of arrival."""
    store = _read_store(slice_dir)
    touched, stages = touched_repos(slice_dir), slice_stages(slice_dir)
    out = []
    for entry in store["entries"]:
        asked = _asked(entry, touched, stages)
        if asked:
            out.append((entry, asked))
    return out


def worklist_view(slice_dir: Path | str) -> str:
    items = worklist(slice_dir)
    if not items:
        return "nothing waits for the wrap-up"
    verb = "waits" if len(items) == 1 else "wait"
    out = [f"{_plural(len(items), 'entry', 'entries')} {verb} for the wrap-up"]
    for entry, asked in items:
        out.append(f"{entry['id']} · {asked}")
        out.append(f"    {_headline_with_grade(entry)}")
        triage = _triage_words(entry)
        if triage:
            out.append(f"    Triage: {triage}")
        out.append(f"    Consequence: {entry['consequence']}" if entry.get("consequence")
                   else "    (no Consequence line)")
        if entry.get("proposal"):
            out.append(f"    Proposal: {entry['proposal']}")
    return "\n".join(out)


# -- counts ------------------------------------------------------------------

def entry_counts(slice_dir: Path | str) -> dict[str, int]:
    """Live entries per place of the report — the events in the record
    counted, the struck ones not — then live entries per id letter (the
    old letters only where the store holds such entries), then the smoke
    counts: live entries without a Consequence or a Provenance line, and
    those that come to the operator (to you, card requests) without a
    proposal, or a decision without its options."""
    store = _read_store(slice_dir)
    touched, stages = touched_repos(slice_dir), slice_stages(slice_dir)
    counts = dict.fromkeys(COUNT_NAMES, 0)
    by_name = dict(zip(PLACES, COUNT_NAMES, strict=True))
    letters = dict.fromkeys(KINDS.values(), 0)
    for entry in store["entries"]:
        m = _ID_RE.fullmatch(entry["id"])
        if m and m.group(1) in OLD_LETTERS:
            letters.setdefault(m.group(1), 0)
    no_consequence = no_provenance = no_proposal = 0
    for entry in store["entries"]:
        if entry.get("strike"):
            continue
        key, _ = route(entry, touched, stages)
        counts[by_name[report_section(key)]] += 1
        letter = _ID_RE.fullmatch(entry["id"]).group(1)
        letters[letter] = letters.get(letter, 0) + 1
        no_consequence += not entry.get("consequence")
        no_provenance += not (entry.get("evidence") or entry.get("author"))
        no_proposal += (key.startswith(("operator:", "card:"))
                        and not (entry.get("proposal") or entry.get("options")))
    counts.update(letters)
    counts[NO_CONSEQUENCE] = no_consequence
    counts[NO_PROVENANCE] = no_provenance
    counts[NO_PROPOSAL] = no_proposal
    return counts


def counts_line(counts: dict[str, int]) -> str:
    """`to you 2 · card requests 1 · wrap-up 5 · unlabelled 0 · closed 3 ·
    record 9 — A 1 · D 0 · E 3 · B 2 · P 1 · T 0 · I 1` — one line; the
    old letters after those when present, and the smoke counts (`· 2
    entries without a Consequence line`, `· 1 entry that comes to you
    without a Proposal line`) only when there are any."""
    line = " · ".join(f"{name} {counts.get(name, 0)}" for name in COUNT_NAMES)
    letters = [*KINDS.values(), *(k for k in OLD_LETTERS if k in counts)]
    line += " — " + " · ".join(f"{k} {counts.get(k, 0)}" for k in letters)
    for key, label in ((NO_CONSEQUENCE, "Consequence"),
                       (NO_PROVENANCE, "Provenance")):
        n = counts.get(key, 0)
        if n:
            line += f" · {_plural(n, 'entry', 'entries')} without a {label} line"
    n = counts.get(NO_PROPOSAL, 0)
    if n:
        line += (f" · {_plural(n, 'entry', 'entries')} that "
                 f"{'comes' if n == 1 else 'come'} to you without a Proposal line")
    return line


# -- list --------------------------------------------------------------------

def list_view(slice_dir: Path | str) -> str:
    """The view an agent takes before it appends: per kind, in the
    contract's order, `B3 — <headline> · <grade>` with the Consequence
    indented under it; a struck entry as `~~B3~~ — <headline> — <reason>`;
    `(none)` under an empty kind. An entry without a kind stands under
    `## unlabelled`."""
    store = _read_store(slice_dir)
    groups: dict[str, list[dict]] = {k: [] for k in KINDS}
    for entry in store["entries"]:
        groups.setdefault(entry.get("kind") if entry.get("kind") in KINDS
                          else "unlabelled", []).append(entry)
    out: list[str] = []
    for kind, entries in groups.items():
        out.append(f"## {kind}")
        if not entries:
            out.append("(none)")
        for entry in entries:
            if entry.get("strike"):
                out.append(f"~~{entry['id']}~~ — {_headline_with_grade(entry)} — "
                           + _strike_tail(entry["strike"]))
                continue
            out.append(f"{entry['id']} — {_headline_with_grade(entry)}")
            out.append(f"    Consequence: {entry['consequence']}"
                       if entry.get("consequence") else "    (no Consequence line)")
    return "\n".join(out)


# -- render ------------------------------------------------------------------

def _wrap(line: str) -> list[str]:
    """A line wrapped at the report's width; a ` · ` separator stays with
    the word before it, so no line opens with one."""
    glued = line.replace(" · ", " · ")
    return [part.replace(" ", " ")
            for part in textwrap.wrap(glued, width=HEADER_WIDTH,
                                      break_long_words=False,
                                      break_on_hyphens=False)] or [line]


def _triage_words(entry: dict) -> str | None:
    lab = effective_labels(entry)
    if lab is None or entry.get("kind") not in KINDS:
        return None
    words = [WORDS["kind"][entry["kind"]]]
    for key in TRIAGE_ORDER:
        value = lab.get(key)
        if value is None:
            continue
        if key == "repo":
            words.append(f"in {value}")
        elif key == "for":
            words.append(f"for slice {value}")
        else:
            said = WORDS[key].get(value, value)
            if said:
                words.append(said)
    return " · ".join(words)


def _note_text(note: dict) -> str:
    return f"{note['by']}, {note['date']} — " + "\n".join(note["text"])


def _wrap_up_lines(mark: dict) -> list[str]:
    said = MARKS.get(mark["outcome"], MARKS["left"])[1]
    return [f"{said}: {mark['text'][0]}", *mark["text"][1:]]


def _notes(entry: dict) -> list[str]:
    paras = [_note_text(n) for n in entry.get("notes") or []]
    if entry.get("wrap_up"):
        mark = entry["wrap_up"]
        paras.append(_note_text({"by": mark["by"], "date": mark["date"],
                                 "text": _wrap_up_lines(mark)}))
    return paras


def _ruling_text(entry: dict) -> str:
    """The ruling as the record and `show` give it: the answer lines as
    Pilot wrote them — the answer, where it was deferred to, when it was
    done, the note — and who answered, an answer Pilot chose said as Pilot's
    and not the operator's; then ` — ` and what the continuation did on it.
    A report before 0.10 recorded the operator's words instead. Empty
    without a ruling."""
    ruling = entry.get("ruling") or {}
    lines = ruling.get("answer_lines")
    if lines:
        bits = [f"{key}: {lines[key]}" for key in ("answer", "to", "done", "note")
                if key in lines]
        if _answered_by(lines) == PILOT:
            bits.append("chosen by Pilot; the operator did not decide this")
        else:
            bits.append(f"by {lines['by']}" + (f" via {lines['via']}"
                                               if lines.get("via") else ""))
        if lines.get("at"):
            bits.append(f"at {lines['at']}")
        said = " · ".join(bits)
    else:
        said = ruling.get("words") or ""
    if said and ruling.get("did"):
        return f"{said} — {ruling['did']}"
    return said


def _provenance(entry: dict) -> str | None:
    evidence, author = entry.get("evidence"), entry.get("author")
    if evidence and author:
        return f"{evidence} — {author}"
    return evidence or author


def _body_and_notes(entry: dict) -> str:
    return "\n\n".join(p for p in ["\n".join(entry.get("body") or []), *_notes(entry)]
                       if p.strip())


def _heading(entry: dict) -> str:
    """`### B3 — <headline> · <grade>`, or the struck heading."""
    if entry.get("strike"):
        return _struck_heading(entry)
    return f"### {entry['id']} — {_headline_with_grade(entry)}"


def _proposal_lines(entry: dict) -> list[str]:
    """The Proposal line, wrapped, and its blank; nothing without one."""
    if not entry.get("proposal"):
        return []
    return [*_wrap(f"**Proposal:** {entry['proposal']}"), ""]


def _ask_field_lines(entry: dict) -> list[str]:
    """An entry's options, the recommended one marked, its check and what it
    is due before, as `show` and the record give them."""
    out: list[str] = []
    for opt in entry.get("options") or []:
        mark = " (recommended)" if opt.get("label") == entry.get("recommend") else ""
        line = f": {opt['line']}" if opt.get("line") else ""
        out.append(f"- **{opt.get('label')}**{mark}{line}")
    if out:
        out = ["**Options:**", "", *out, ""]
    if entry.get("check"):
        out += [f"**Check:** {entry['check']}", ""]
    if entry.get("due"):
        out += [f"**Due:** before the {entry['due']}", ""]
    return out


def _tail(entry: dict, route_words: str | None) -> list[str]:
    """The lines under the body in the full view: Consequence, then the
    lines the entry is triaged on — Triage, Provenance, Route — and the
    ruling where it has one."""
    out: list[str] = []
    if entry.get("consequence"):
        out += [f"**Consequence:** {entry['consequence']}", ""]
    out += _triage_lines(entry)
    if route_words:
        out.append(f"**Route:** {route_words}")
    if _ruled(entry):
        # the answer lines verbatim, never wrapped
        out.append(f"**Ruling:** {_ruling_text(entry)}")
    return out


# What plan_loop.py writes into every owed-after action: true of each one,
# so the document leaves it out (`show` keeps it).
_OWED_HEADLINE_RE = re.compile(r"^Settle (?P<vid>V\d+) after\b")
_OWED_CONSEQUENCE_RE = re.compile(r"^V\d+ stays unproven until then; the test phase "
                                  r"does not settle it\.?$")
_OWED_PROPOSAL_RE = re.compile(r"^When that has happened, say so: the session settles V\d+")


def _verification(slice_dir: Path | str) -> dict[str, dict]:
    """verification.json's items by id; empty when it is missing or unreadable."""
    try:
        data = json.loads((Path(slice_dir) / "verification.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return {i["id"]: i for i in items or [] if isinstance(i, dict) and i.get("id")}


def _short_strike_tail(strike: dict) -> str:
    """The struck heading's tail as the record gives it: the reason up to its
    first `; `, at most a couple of lines, then the striker. `show` keeps the
    whole reason."""
    reason = strike["reason"].split("; ", 1)[0].strip()
    reason = textwrap.shorten(reason, width=220, placeholder=" …")
    commit = strike.get("commit")
    if commit and commit not in reason:
        reason += f" ({commit})"
    if strike.get("by"):
        reason += f"; struck by {strike['by']}"
    return reason


def _triage_lines(entry: dict) -> list[str]:
    """The Triage and Provenance lines, each only when the entry has it."""
    out: list[str] = []
    triage = _triage_words(entry)
    if triage:
        out += _wrap(f"**Triage:** {triage}")
    provenance = _provenance(entry)
    if provenance:
        out.append(f"**Provenance:** {provenance}")
    return out


def _render_entry(entry: dict, form: str, route_words: str | None) -> str:
    """One entry as the record or `show` gives it: `full` (the body, every
    note, the proposal, the options, check and due, then every line the
    entry is triaged on and its ruling — `show`'s), `closed` (the heading,
    the Consequence unless it says none, Triage, Provenance and Route — what
    the table closed), `asked` (the heading the document asks it under and
    its trail), `ruled` (that heading, the ruling and the trail) and
    `record` (the heading alone, a struck one's reason cut short). All of it
    is Markdown, so every `<` outside code is escaped (`asks.escape_tags`)."""
    return asks.escape_tags(_entry_markdown(entry, form, route_words))


def _asked_heading(entry: dict) -> str:
    """The record's heading of an entry the document asked: the section's
    headline — the restatement's, where there is one — with the grade."""
    told = entry.get("restated")
    head = (f"{told['headline']} · {entry['grade']}" if told and entry.get("grade")
            else told["headline"] if told else _headline_with_grade(entry))
    if entry.get("strike"):
        return f"### ~~{entry['id']} — {head}~~ — " + _strike_tail(entry["strike"])
    return f"### {entry['id']} — {head}"


def _trail(entry: dict) -> list[str]:
    """What the document's section leaves to the record, in paragraphs:
    the author's own text where a restatement took its place, then every
    note in order — the consults', the relabels', a replaced proposal or
    restatement — and the wrap-up's mark last."""
    paras: list[str] = []
    if entry.get("restated"):
        paras.append(f"**As its author wrote it:** {entry['headline']}")
        paras.append(_prose(entry.get("body") or []))
        if entry.get("consequence"):
            paras.append(f"**Consequence:** {entry['consequence']}")
        if _provenance(entry):
            paras.append(f"**Provenance:** {_provenance(entry)}")
    notes = list(entry.get("notes") or [])
    if entry.get("wrap_up"):
        mark = entry["wrap_up"]
        notes.append({"by": mark["by"], "date": mark["date"], "text": _wrap_up_lines(mark)})
    for note in notes:
        paras.append(f"**{note['by']}, {note['date']}.** " + _prose(note["text"]))
    return [p for p in paras if p.strip()]


def _entry_markdown(entry: dict, form: str, route_words: str | None) -> str:
    if form == "record":
        if entry.get("strike"):
            return (f"### ~~{entry['id']} — {_headline_with_grade(entry)}~~ — "
                    + _short_strike_tail(entry["strike"]))
        return _heading(entry)
    if form in ("asked", "ruled"):
        ruling = [f"**Ruling:** {_ruling_text(entry)}"] if form == "ruled" else []
        return "\n\n".join([_asked_heading(entry), *ruling, *_trail(entry)])
    if form == "full":
        lines = [_heading(entry), ""]
        told = entry.get("restated")
        if told:
            lines += [f"**Restated** ({told['by']}, {told['date']}): {told['headline']}", "",
                      _prose(told["body"]), ""]
            if told.get("consequence"):
                lines += [f"**Restated consequence:** {told['consequence']}", ""]
            if _provenance(told):
                lines += [f"**Restated provenance:** {_provenance(told)}", ""]
            lines += ["**As its author wrote it:**", ""]
        body = _body_and_notes(entry)
        if body:
            lines += [body, ""]
        lines += _proposal_lines(entry)
        lines += _ask_field_lines(entry)
        struck = bool(entry.get("strike"))
        return "\n".join(lines + _tail(entry, None if struck else route_words)).rstrip("\n")
    lines = [_heading(entry), ""]
    consequence = entry.get("consequence")
    if consequence and not opens_with_none(consequence):
        lines += [f"**Consequence:** {consequence}", ""]
    return "\n".join([*lines, *_triage_lines(entry), f"**Route:** {route_words}"])


def _sort_key(entry: dict) -> tuple:
    grade = entry.get("grade")
    kinds = list(KINDS)
    m = _ID_RE.fullmatch(entry["id"])
    return (GRADE_ORDER.index(grade) if grade in GRADE_ORDER else GRADE_ORDER.index(None),
            kinds.index(entry["kind"]) if entry.get("kind") in kinds else len(kinds),
            m.group(1), int(m.group(2)))


def _id_key(entry: dict) -> tuple:
    m = _ID_RE.fullmatch(entry["id"])
    return m.group(1), int(m.group(2))


def _slice_name(store: dict) -> tuple[str, str]:
    """(the slice's number, its name in words), from the folder name the
    store records: `029_notifications` is ("029", "notifications")."""
    num, _, slug = str(store.get("slice") or "").partition("_")
    return num, re.sub(r"[_-]+", " ", slug).strip()


def _state(slice_dir: Path | str) -> dict | None:
    try:
        state = json.loads((Path(slice_dir) / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _header(slice_dir: Path | str) -> str:
    state = _state(slice_dir)
    return UNSTAMPED if state is None else run_header(state, slice_dir)


def _placed(store: dict, slice_dir: Path | str, live_only: bool = False
            ) -> list[tuple[str, list[tuple[dict, str, str]]]]:
    """(place, [(entry, its route key, its Route words)]) in PLACES' order,
    a place's entries as the render sorts them — the record's events first,
    then what was struck. With `live_only`, struck entries are left out."""
    touched, stages = touched_repos(slice_dir), slice_stages(slice_dir)
    placed: dict[str, list[tuple[dict, str, str]]] = {p: [] for p in PLACES}
    for entry in store["entries"]:
        if live_only and entry.get("strike"):
            continue
        key, words = route(entry, touched, stages)
        placed[report_section(key)].append((entry, key, words))
    out = []
    for place in PLACES:
        items = placed[place]
        if place == "Record":
            items = sorted(items, key=lambda x: (bool(x[0].get("strike")), _id_key(x[0])))
        else:
            items = sorted(items, key=lambda x: _sort_key(x[0]))
        out.append((place, items))
    return out


# -- the document: what Pilot reads (asks.py renders it) --------------------------

_FENCE_LINE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
_HEADING_LINE_RE = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")


def _prose(lines: list[str]) -> str:
    """An author's text as the document carries it: a line Markdown reads as
    a heading, outside a fence, has its first `#` escaped, so that it stays
    the author's text and does not end the ask's section."""
    out: list[str] = []
    fence: str | None = None
    for line in lines:
        if fence is None:
            m = _FENCE_LINE_RE.match(line)
            if m:
                fence = m.group(1)
            elif _HEADING_LINE_RE.match(line) and line.strip("# \t"):
                line = line.replace("#", "\\#", 1)
        elif re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", line):
            fence = None
        out.append(line)
    return "\n".join(out).strip("\n")


def _ask_headline(entry: dict, vmap: dict[str, dict]) -> str:
    """The ask's heading: the restatement's, else the entry's headline, its
    grade left off; an owed-after action's criterion named by its area and
    its owed-after in full, where plan_loop.py shortened them."""
    if entry.get("restated"):
        return entry["restated"]["headline"]
    m = _OWED_HEADLINE_RE.match(entry.get("headline") or "")
    item = vmap.get(m.group("vid")) if m else None
    if item and item.get("owed_after"):
        area = f" ({item['area']})" if item.get("area") else ""
        return _collapse(f"Settle {m.group('vid')}{area} after {item['owed_after']}")
    return entry["headline"]


def _for_planned(entry: dict, key: str) -> bool:
    """Whether the entry comes to the operator because the slice its `for`
    names is planned or running (`_for_route`), not for its kind."""
    return key == "operator:action" and entry.get("kind") != "action"


def _ask_lead(entry: dict, place: str, key: str, words: str) -> str | None:
    """What an entry that comes to the operator for a reason of its own is
    said as, before its body: one the wrap-up did not reach, one nobody
    routed, one for a later slice."""
    target = (effective_labels(entry) or {}).get("for")
    if place == "For the wrap-up":
        asked = words.removeprefix("the wrap-up — ")
        return (f"**Not reached.** The table gave this entry to the wrap-up ({asked}), "
                "and no wrap-up reached it: nobody has looked at it since its author.")
    if place == "Unlabelled":
        return "**Unlabelled.** The entry carries no labels, so nothing routed it."
    if key == "operator:held":
        return f"**For slice {target}**, which no folder holds yet."
    if _for_planned(entry, key):
        return (f"**For slice {target}**, which is planned or running: its run never "
                "reads slice.md again.")
    return None


def _ask_proposal(entry: dict, key: str) -> str | None:
    """The proposal a block other than an action's or a decision's with its
    options carries: the entry's own, or — where the table brought the entry
    for a reason its author did not state — the one that reason makes; an
    entry for a slice not created yet is proposed to be held for it, and
    Pilot defers it to that slice's task."""
    lab = effective_labels(entry) or {}
    own = entry.get("proposal")
    if key == "operator:held":
        hold = f"Hold it for slice {lab.get('for')}, which is not created yet."
        return f"{hold} The author proposes: {own}" if own else hold
    if own:
        return own
    if key == "card:table":
        return (f"Card it for {lab.get('repo')}: the fix lives there, and this slice "
                "did not touch it.")
    if _for_planned(entry, key):
        return f"Add a phase to slice {lab.get('for')}'s plan, or rule on its run."
    return None


def _section(entry: dict) -> list[str]:
    """The paragraphs of the entry's section, the current story told once:
    the body, an action's proposal, the consequence and the provenance —
    each the restatement's where it gives one, else the author's. No note:
    every note is the record's, and what one changed is the restatement's
    to say."""
    told = entry.get("restated") or {}
    paras = [_prose(told.get("body") or entry.get("body") or [])]
    proposal = entry.get("proposal")
    if entry.get("kind") == "action" and proposal and not _OWED_PROPOSAL_RE.match(proposal):
        paras.append(f"**Proposal:** {proposal}")
    consequence = told.get("consequence") or entry.get("consequence")
    if consequence and not _OWED_CONSEQUENCE_RE.match(consequence):
        paras.append(f"**Consequence:** {consequence}")
    provenance = _provenance(told) or _provenance(entry)
    if provenance:
        paras.append(f"**Provenance:** {provenance}")
    return [p for p in paras if p and p.strip()]


def _ask(entry: dict, place: str, key: str, words: str,
         vmap: dict[str, dict]) -> dict:
    """The entry as an ask of the document, in asks.py's shape: the block
    by kind — an action's with its options and check, a decision's with
    its options and the one recommended, any other a decision on its
    proposal, or a question where nobody proposed anything — and above it
    the section (`_section`), opening with what a reason of the table's own
    says. The id is the entry's, so the answers come back to it."""
    kind = entry.get("kind")
    lead = _ask_lead(entry, place, key, words)
    paras = ([lead] if lead else []) + _section(entry)
    ask: dict = {"id": entry["id"], "headline": _ask_headline(entry, vmap),
                 "body": "\n\n".join(paras) or "The entry has no body."}
    if kind == "action":
        ask["kind"] = "action"
        for field in ("options", "check", "due"):
            if entry.get(field):
                ask[field] = entry[field]
    elif kind == "decision" and entry.get("options"):
        ask.update(kind="decision", options=entry["options"])
        if entry.get("recommend"):
            ask["recommend"] = entry["recommend"]
    elif (said := _ask_proposal(entry, key)) is not None:
        ask.update(kind="decision", proposal=said)
    else:
        ask["kind"] = "question"
    return ask


def card_view(slice_dir: Path | str, ids: list[str]) -> str:
    """The card each named entry files once its card request is agreed:
    the section's heading as the card's summary, on the first line, then
    its body as the card's description — the text the operator agreed to,
    as the document showed it. Several are separated by a `---` line."""
    store = _read_store(slice_dir)
    vmap = _verification(slice_dir)
    cards = []
    for eid in ids:
        cards.append(asks.escape_tags(_card_text(_find(store, eid), vmap)))
    return "\n\n---\n\n".join(cards)


# What a document's summary says it holds, by the place its asks come from.
SUMMARY_WORDS = {"Comes to you": "what is yours to rule or to do",
                 "Card requests": "the cards asked for",
                 "For the wrap-up": "what no wrap-up reached",
                 "Unlabelled": "what nobody routed"}


def _shipped(slice_dir: Path | str) -> list[str]:
    """The phases plan.md stamps done, `P3 <title>` each, in plan order."""
    try:
        text = (Path(slice_dir) / "plan.md").read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.split("\n"):
        m = PHASE_RE.match(line)
        if m and re.search(r"✅\s*DONE\b", m.group(2)):
            title = re.sub(r"\s*✅\s*DONE\b.*$", "", m.group(2)).strip()
            out.append(f"P{m.group(1)} {title}")
    return out


def _wrap_up_said(store: dict) -> str | None:
    """What the wrap-up settled, in a line: the entries it fixed, a commit
    each, and those it folded into later slices."""
    fixed, folded = [], []
    for entry in store["entries"]:
        strike = entry.get("strike") or {}
        if not _WRAP_UP_BY_RE.match(_collapse(strike.get("by"))):
            continue
        if strike.get("reason", "").startswith("folded into"):
            folded.append(entry["id"])
        elif strike.get("commit"):
            fixed.append(entry["id"])
    said = []
    if fixed:
        said.append(f"fixed {_join(fixed)}, a commit each")
    if folded:
        said.append(f"folded {_join(folded)} into later slices")
    return f"**The wrap-up** {' and '.join(said)}." if said else None


def _context(store: dict, slice_dir: Path | str) -> list[str]:
    """The paragraphs the asks share: those the session gave (`render
    --context`), then the run in a line, what shipped, what the wrap-up
    settled, and where the record is."""
    paras = list(store.get("context") or [])
    state = _state(slice_dir)
    if state is not None:
        paras.append(f"**The run.** {run_header(state, slice_dir).removeprefix('Run: ')}.")
    shipped = _shipped(slice_dir)
    if shipped:
        paras.append("**What shipped.** " + "; ".join(shipped) + ".")
    wrap_up = _wrap_up_said(store)
    if wrap_up:
        paras.append(wrap_up)
    paras.append(f"**The record**, `{RECORD_NAME}`, attached, holds the rest: what the "
                 "table closed, the run's events, and every entry struck.")
    return [_prose(p.split("\n")) for p in paras]


def _document(store: dict, slice_dir: Path | str) -> dict | None:
    """The close-out as an asks.py store, rendered to close-out.md: one ask
    per entry that comes to the operator, is a card request, or waits for a
    wrap-up that did not reach it or for labels nobody gave — None when
    there is none."""
    vmap = _verification(slice_dir)
    entries, present = [], []
    for place, items in _placed(store, slice_dir, live_only=True):
        if place not in ASKED or not items:
            continue
        present.append(place)
        entries += [_ask(entry, place, key, words, vmap) for entry, key, words in items]
    if not entries:
        return None
    num, name = _slice_name(store)
    doc: dict = {"title": f"Close-out of slice {num} — {name}" if name
                 else f"Close-out of slice {num}"}
    if len(entries) > 1:
        doc["summary"] = store.get("summary") or (
            f"Slice {num}'s close-out: " + _join([SUMMARY_WORDS[p] for p in present]))
    if store.get("step"):
        doc["step"] = store["step"]
    doc["context"] = _context(store, slice_dir)
    doc["entries"] = entries
    return doc


def _record(store: dict, slice_dir: Path | str) -> str:
    """close-out-record.md, the record attached to the document: the run
    header; what the operator ruled and what was done on it; what is asked
    and open; what the table closed, with its ground; and the record — the
    run's events, then every entry struck."""
    num, name = _slice_name(store)
    out = [f"# Close-out record — slice {num} {name}".rstrip(), "",
           *_wrap(asks.escape_tags(_header(slice_dir)))]
    closed = store.get("closed")
    if closed:
        said = closed.get("words") or (f"by {closed['by']}" if closed.get("by") else "")
        out += ["", *_wrap(asks.escape_tags(
            f"Closed: {closed['date']}" + (f" — {_collapse(said)}" if said else "")))]
    placed = dict(_placed(store, slice_dir))
    ruled = sorted((e for e in store["entries"] if _ruled(e)), key=_id_key)
    asked = [(e, w) for place in ASKED for e, _, w in placed[place] if not _ruled(e)]
    sections = dict(zip(RECORD_SECTIONS, (
        [_render_entry(e, "ruled", None) for e in ruled],
        [_render_entry(e, "asked", None) for e, _ in asked],
        [_render_entry(e, "closed", w) for e, _, w in placed["Closed"]],
        [_render_entry(e, "record", None) for e, _, _ in placed["Record"] if not _ruled(e)],
    ), strict=True))
    for title, blocks in sections.items():
        if blocks:
            out += ["", f"## {title}"]
            for block in blocks:
                out += ["", block]
    return "\n".join(out) + "\n"


def show_view(slice_dir: Path | str, ids: list[str] | None = None) -> str:
    """Entries in full — body, every note, Proposal, the options, check and
    due, Consequence, Triage, Provenance, Route, the ruling: what the
    document and the record cut short, for the wrap-up, the continuation
    and a card filing to read. The named ids in the order given, struck ones
    too; without ids every live entry, under its place's `## ` line."""
    store = _read_store(slice_dir)
    if ids:
        touched, stages = touched_repos(slice_dir), slice_stages(slice_dir)
        entries = [_find(store, eid) for eid in ids]
        return "\n\n".join(_render_entry(e, "full", route(e, touched, stages)[1])
                            for e in entries)
    out: list[str] = []
    for place, items in _placed(store, slice_dir, live_only=True):
        if not items:
            continue
        out.append(f"## {place}")
        out += [_render_entry(entry, "full", words) for entry, _, words in items]
    return "\n\n".join(out) or "no live entries"


# -- fold: an entry into a later slice's slice.md ----------------------------------

FOLD_INTRO = ("Slice {own}'s close-out, entry {eid}, verbatim (`close_out.py show`, "
              "{date}; report `{report}`):")
FOLD_WIDTH = 100
# How long staging the fold may take before it is reported as failed.
GIT_ADD_TIMEOUT = 30
_BACKTICKED_RE = re.compile(r"`[^`]*`")


def _fold_intro(own: str, eid: str, day: str, report: str) -> str:
    """The paragraph a fold opens with, wrapped at FOLD_WIDTH without
    breaking a word, a hyphenated name or a backticked span."""
    text = FOLD_INTRO.format(own=own, eid=eid, date=day, report=report)
    glued = _BACKTICKED_RE.sub(lambda m: m.group(0).replace(" ", "\0"), text)
    return textwrap.fill(glued, width=FOLD_WIDTH, break_long_words=False,
                         break_on_hyphens=False).replace("\0", " ")


def _folded_already(text: str, own: str, eid: str, folder: str) -> bool:
    """Whether `text` holds the intro of a fold of entry `eid` of slice
    `own` — the report the slice folder `folder` holds, wherever in the
    spec tree it stood when it was folded (`slices/` or
    `slices/completed/`), however the line was wrapped."""
    flat = " ".join(text.split())
    return re.search(re.escape(f"Slice {own}'s close-out, entry {eid}, verbatim (")
                     + r"[^)]*?; report `(?:[^`]*/)?"
                     + re.escape(f"{folder}/{REPORT_NAME}`):"), flat) is not None


def fold_entry(slice_dir: Path | str, eid: str, into: str | None = None,
               date: str | None = None) -> str:
    """Append entry `eid` verbatim to the slice.md of the slice it is for —
    its `for` label, or `into` in its place — under the intro FOLD_INTRO
    gives, as `show` prints it, every line quoted; then stage that file in
    the spec repo (`git add`, by name). The target is a slice still to run
    and unplanned: one planned or running never reads slice.md again. The
    report's own slice, a struck entry, an entry with no target, and a
    slice.md that holds this fold already are refused, and nothing is
    written. Neither the store nor the report is written — the strike that
    follows the commit is the caller's. Returns what was done and the
    strike to run; a staging that fails is a ReportError that says so, the
    fold left in slice.md."""
    day = _date(date)
    here = Path(slice_dir).resolve()
    with _locked(slice_dir):
        entry = _find(_load(slice_dir), eid)
        eid = entry["id"]
        if entry.get("strike"):
            raise ReportError(f"{eid} is struck — a struck entry is settled: "
                              + _struck_heading(entry)[4:])
        target = into if into is not None else (entry.get("labels") or {}).get("for")
        target = _collapse(None if target is None else str(target))
        if not target:
            raise ReportError(f"{eid} has no `for` label: name the slice to fold it "
                              "into with --into")
        named = f"--into {target}" if into is not None else f"{eid}'s `for` {target}"
        number = _slice_number(target)
        if number is None:
            raise ReportError(f"{named} names no slice: a slice is named by its number "
                              "— 12, 012 or 012_slug")
        own_m = re.match(r"(\d+)_", here.name)
        own = own_m.group(1) if own_m else here.name
        if own_m and number == int(own):
            raise ReportError(f"{named} is the report's own slice: an entry folds into "
                              "another slice, still to run")
        root = _slices_root(here)
        if root is None:
            raise ReportError(f"{here} has no `slices` ancestor, so no slice still to "
                              "run can be folded into")
        folder = (_folders_to_run(here) or {}).get(number)
        stages = slice_stages(here) or {}
        if folder is None and number not in stages:
            raise ReportError(f"{named}: slice {str(number).zfill(_for_width(stages))} is "
                              "not created yet — the entry comes to the operator, "
                              "to hold for that slice")
        if folder is None:
            raise ReportError(f"{named}: no other slice still to run has that number "
                              "(a <number>_* folder in slices/ or slices/backlog/)")
        written = re.match(r"(\d+)_", folder.name).group(1)
        if _stage(folder) == "planned":
            raise ReportError(f"slice {written} is planned or running, and its run never "
                              "reads slice.md again: add a phase or rule on its run — "
                              "nothing was folded")
        spec_root = root.parent
        path = folder / "slice.md"
        rel = path.relative_to(spec_root)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ReportError(f"{rel} does not exist: slice {written} has no slice.md "
                              "to fold into — nothing was folded") from None
        except OSError as e:
            raise ReportError(f"{rel} is unreadable: {e}") from None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ReportError(f"{rel} is not UTF-8 — nothing was folded") from None
        if _folded_already(text, own, eid, here.name):
            raise ReportError(f"{rel} holds this fold already — slice {own}'s entry "
                              f"{eid}; nothing was folded")
        intro = _fold_intro(own, eid, day, str((here / REPORT_NAME).relative_to(spec_root)))
        shown = show_view(slice_dir, [eid]).rstrip("\n").split("\n")
        quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in shown)
        head = data.rstrip(b"\n")
        path.write_bytes((head + b"\n\n" if head.strip() else b"")
                         + f"{intro}\n\n{quoted}\n".encode())
    strike = (f"close_out.py strike {shlex.quote(str(report_path(slice_dir)))} {eid} "
              f'--reason "folded into slice {written}" --commit <sha> --by <you>')
    add = ["git", "-C", str(spec_root), "add", "--", str(rel)]
    try:
        result = subprocess.run(add, capture_output=True, text=True,
                                timeout=GIT_ADD_TIMEOUT,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        failed = None if result.returncode == 0 else (
            result.stderr.strip() or f"exit {result.returncode}")
    except subprocess.TimeoutExpired:
        failed = f"it did not answer within {GIT_ADD_TIMEOUT}s"
    except OSError as e:
        failed = str(e)
    if failed:
        raise ReportError(f"folded {eid} into {rel}, but staging it failed — "
                          f"`{shlex.join(add)}`: {failed}. The fold stays in slice.md, "
                          f"unstaged: stage it by name, commit it, then: {strike}")
    return f"folded {eid} into {rel} (staged) — commit it, then: {strike}"



def _write_if_changed(path: Path, text: str) -> None:
    """Write `text`, left alone when the file already holds those bytes.
    Called under the lock."""
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old != text:
        _write_atomic(path, text)


def record_path(slice_dir: Path | str) -> Path:
    return Path(slice_dir) / RECORD_NAME


def _answered(path: Path) -> list[str]:
    """The ids of the blocks of a close-out.md that carry answer lines: one
    Pilot wrote back, which is never rendered over. None of them in a file
    that is missing or is no document Pilot reads."""
    try:
        blocks = asks.read_back(path.read_text(encoding="utf-8"))
    except (OSError, asks.AskError):
        return []
    return [bid for bid, block in blocks.items() if block["lines"]]


def render_report(slice_dir: Path | str, *, step: str | None = None,
                  summary: str | None = None,
                  context: list[str] | None = None) -> str:
    """Write the record, close-out-record.md, and the document,
    close-out.md, through asks.py (`_document`): the asks, or — with none —
    no document, an unanswered one left from an earlier render removed. A
    document Pilot wrote back, its answers in it, is never rendered over:
    the record alone is written. `step`, `summary` and `context` set the
    document's own fields in the store, for this render and every later
    one; an empty one removes it. A ReportError names the entries Pilot
    would refuse, the record written. Returns a line saying what was
    written."""
    with _locked(slice_dir):
        store = _load(slice_dir)
        before = _dump(store)
        for key, value in (("step", step), ("summary", summary)):
            if value is not None:
                if _collapse(value):
                    store[key] = _collapse(value)
                else:
                    store.pop(key, None)
        if context is not None:
            paragraphs = [c.strip() for c in context if c.strip()]
            if paragraphs:
                store["context"] = paragraphs
            else:
                store.pop("context", None)
        store.pop("rendered", None)
        if _dump(store) != before:
            _save(slice_dir, store)
        _write_if_changed(record_path(slice_dir), _record(store, slice_dir))
        report = report_path(slice_dir)
        answered = _answered(report)
        if answered:
            return (f"{RECORD_NAME} written; {REPORT_NAME} left as Pilot wrote it back "
                    f"(answers on {', '.join(answered)}): `absorb` reads it")
        doc = _document(store, slice_dir)
        if doc is None:
            if report.exists():
                report.unlink()
            return f"{RECORD_NAME} written; nothing to ask, so no {REPORT_NAME}"
        try:
            text = asks.render(doc)
        except asks.AskError as e:
            raise ReportError(f"{REPORT_NAME} cannot be rendered: {e}\nCorrect each entry "
                              "it names (`amend`), then render again.") from None
        _write_if_changed(report, text)
        return (f"{RECORD_NAME} and {REPORT_NAME} written: "
                f"{_plural(len(doc['entries']), 'ask')}")


# -- the run header ------------------------------------------------------------

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


def run_header(state: dict, slice_dir: Path | str | None = None) -> str:
    """The `Run:` line from a run loop state.json — each piece only when
    the state carries it. `slice_dir` is read for one fact state.json does
    not carry: a bailout.json beside it (unlinked at the start of every run)
    means the run stopped in the stage `run_phase` names."""
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
    # A project with no doc phase still runs its ladder for the wrap-up,
    # marked `writer: false`: that is no doc phase done.
    if isinstance(doc, dict) and doc.get("stage") and doc.get("writer", True):
        stage = doc["stage"]
        bits.append("doc phase done" if stage == "done"
                    else f"doc phase at stage {stage}")
    wrap_up = state.get("wrap_up")
    outcome = wrap_up.get("outcome") if isinstance(wrap_up, dict) else None
    if outcome in ("landed", "left_out"):
        bits.append("wrap-up landed" if outcome == "landed"
                    else "wrap-up left out")
    run_phase = state.get("run_phase")
    if run_phase and run_phase != "done":
        bailed = bool(slice_dir
                      and (Path(slice_dir) / "bailout.json").exists())
        # A pre-0.9.28 state literally carrying "bailed" says it already;
        # a stage plus the file reads `run bailed in docs`.
        bits.append(f"run bailed in {run_phase}"
                    if bailed and run_phase != "bailed"
                    else f"run {run_phase}")
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
    """Render, and return the run header — raising ReportError, before
    anything is written, when the slice holds no readable state.json."""
    state_path = Path(slice_dir) / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        raise ReportError(f"{state_path} is missing or unreadable — nothing "
                          "to stamp from") from None
    render_report(slice_dir)
    return run_header(state, slice_dir)



def author_problems(entry: dict) -> list[str]:
    """What an author owes by the entry's kind, beyond its labels: an action
    and an improvement their proposal; a decision its options, two or more,
    and the one it would recommend, in place of a proposal; an improvement
    whose headline is a question is a decision; and the block's fields as
    their kinds take them (`_ask_problems`)."""
    kind = entry.get("kind") or ""
    article = f"a{'n' if kind[:1] in 'aeiou' else ''}"
    found: list[str] = []
    if kind in PROPOSAL_KINDS and not _collapse(entry.get("proposal")):
        found.append(f"{article} {kind} needs --proposal: {PROPOSAL_HELP}")
    if kind == "decision":
        if not entry.get("options"):
            found.append("a decision needs its --option lines, two or more — the label, "
                         "then a line saying what it costs — and the one it would "
                         "--recommend")
        elif not entry.get("recommend"):
            found.append("a decision needs --recommend: the label of the option you "
                         "would pick")
        if _collapse(entry.get("proposal")):
            found.append("a decision takes no --proposal: what you would pick is its "
                         "--recommend, and why goes in that option's line or the body")
    if kind == "improvement" and _collapse(entry.get("headline")).endswith("?"):
        found.append("a question in an improvement's headline makes it a decision: "
                     "append it as --kind decision, with its --option lines and the one "
                     "it would --recommend")
    if is_prerun(entry) and entry.get("check") is None:
        found.append("an action owed before the run needs --check: the fact that shows "
                     "it done, one of " + ", ".join(f"`{v}`" for v in checks.VOCABULARY)
                     + f" — `{checks.MANUAL}` where no check captures it")
    return found + _ask_problems(entry)


# -- CLI --------------------------------------------------------------------

def _label_value(value: str) -> str:
    """A label value as the tool keeps it: lower-case, spaces and
    underscores as hyphens (`test gap`, `ordinary_condition`)."""
    return re.sub(r"[\s_]+", "-", value.strip().lower())


# The help strings are prompt text: `verb_usage("append", "note", "strike")`
# is rendered into every dispatch, and `relabel`'s into those that offer it.
LABEL_HELP = {
    "trigger": "what has to happen for the problem to show",
    "impact": "what is then experienced",
    "signal": "whether it then says so itself",
    "fix": "what is decided about the fix",
    "area": "sensitive: concurrency or timing, stored data, a wire contract, "
            "authentication or secrets",
    "repo": "the repository the fix lives in, by its directory name",
    "for": "the number of another slice that should take the entry — one still "
           "to run, or one the plan names that triage has not created yet, for "
           "which the operator is asked to hold it — never the slice being run; "
           "leave it out for an entry about this one. One already planned or "
           "running brings the entry to the operator, since that run never reads "
           "slice.md",
    "benefit": "improvement: who is better off",
    "felt": "improvement: when that is felt",
    "change": "improvement: whether it removes, adjusts or adds",
    "size": "improvement: what the change takes",
    "product-call": "improvement: whether it changes what a user of the product "
                    "sees or can do",
    "prevents": "improvement: the worst it would prevent",
}
LABEL_FLAG_ORDER = ("trigger", "impact", "signal", "fix", "area", "repo", "for",
                    "benefit", "felt", "change", "size", "product-call", "prevents")


def _add_label_args(p: argparse.ArgumentParser, relabel: bool = False) -> None:
    for label in LABEL_FLAG_ORDER:
        values = LABELS[label]
        help_ = LABEL_HELP[label]
        if relabel and label == "for":
            help_ += f". --for {FOR_CLEAR} clears it"
        kwargs: dict = {"dest": f"label_{label.replace('-', '_')}", "help": help_}
        if values is None:
            kwargs["metavar"] = "NAME" if label == "repo" else "SLICE"
        else:
            kwargs.update(choices=values, type=_label_value)
        p.add_argument(f"--{label}", **kwargs)


def _labels_from(args) -> dict:
    return {label: getattr(args, f"label_{label.replace('-', '_')}")
            for label in LABELS
            if getattr(args, f"label_{label.replace('-', '_')}", None) is not None}


def _add_ask_args(p: argparse.ArgumentParser) -> None:
    """The block's flags, `append`'s and `amend`'s: one definition each."""
    p.add_argument("--option", action="append", nargs="+", metavar=("LABEL", "LINE"),
                   help="a decision's option, or an answer an action asks for: the "
                        "label, then one line saying what it is or costs; repeat it "
                        "for each — a decision puts two or more")
    p.add_argument("--recommend", metavar="LABEL",
                   help="a decision: the label of the option you would pick — required "
                        "for a decision, in place of --proposal")
    p.add_argument("--check", action="append",
                   help="an action: the fact that shows it done — `env <NAME>`, `file "
                        "<repo>:<path>`, `origin <repo> <branch>:<path> contains <text>`, "
                        "`slice <NNN> completed`, or `manual` where none captures it; "
                        "repeat it for each fact. Never a commit or an environment. An "
                        "action owed before the run needs one")
    p.add_argument("--due", choices=DUES, type=_label_value,
                   help="what must not happen before the entry is dealt with: the "
                        "phase's merge, the test phase, the push, or the report's "
                        "close")


def _options_from(args) -> list | None:
    if args.option is None:
        return None
    for tokens in args.option:
        if len(tokens) > 2:
            raise ReportError(f"--option takes a label and one line, not {len(tokens)} "
                              f"words: quote each — {tokens!r}")
    return [tuple(tokens) for tokens in args.option]


def build_parser() -> tuple[argparse.ArgumentParser,
                            dict[str, argparse.ArgumentParser]]:
    """The CLI, plus its verbs by name — the second is what `verb_usage`
    renders a dispatch's verb block from, so the block and the CLI are one
    definition. `prog` is fixed: an importing script's argv[0] must not
    leak into the usage lines. Every verb's usage leads with its
    positionals (`_positionals_first`), in `--help` and error messages as
    in the dispatch block."""
    parser = argparse.ArgumentParser(prog="close_out.py",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    slice_help = "the slice directory, or its close-out.md"
    id_help = "the entry's id, like B3"

    def verb(name: str, help_: str, entry: bool = False) -> argparse.ArgumentParser:
        # `help` is the line under the tool's own -h; `description`, the verb's -h
        p = sub.add_parser(name, help=help_, description=help_)
        p.add_argument("slice", metavar="<close-out.md>", help=slice_help)
        if entry:
            p.add_argument("id", metavar="<id>", help=id_help)
        return p

    verb("init", "create the store, if absent")

    sub.add_parser("labels", help="print what each label means")

    # `append`'s content flags, which `amend` takes too: one definition each.
    headline_help = ("one line, the claim itself — the ask, as the operator reads it: "
                     "a defect names its repo or component, an action is an "
                     "imperative, a decision asks its question, an improvement says "
                     "what it proposes")
    body_help = "entry body, or - for stdin"
    consequence_help = ("what an operator or user experiences if this stays as it is, "
                        "or none — the line the operator triages on")
    proposal_help = (f"{PROPOSAL_HELP}, in a ruling's words (card · fix now · "
                     "fold into <slice> · close · do it), one line of at most "
                     f"{asks.PROPOSAL_MAX} characters — the operator reads it "
                     "with the headline and the Consequence; required for an "
                     "action and an improvement, refused on a decision")
    provenance_help = ("witnessed | read, then role, phase, round, and the artifact "
                       "with the full record")
    severity_help = "the grade, where the entry has one"

    p = verb("append", "add one entry with its labels; prints its id")
    p.add_argument("--kind", choices=list(KINDS), type=_label_value,
                   help="what the entry is — it decides which of the labels "
                        "below the entry carries")
    p.add_argument("--section", help=argparse.SUPPRESS)
    p.add_argument("--headline", required=True, help=headline_help)
    p.add_argument("--body", required=True, help=body_help)
    p.add_argument("--consequence", required=True, help=consequence_help)
    p.add_argument("--proposal", help=proposal_help)
    _add_ask_args(p)
    p.add_argument("--provenance", help=provenance_help)
    p.add_argument("--by", help="who appends — role, phase and round")
    p.add_argument("--severity", choices=SEVERITIES, type=_label_value, help=severity_help)
    _add_label_args(p)
    # `--kind` is required unless the suppressed `--section` stands in for
    # it; the usage line an author reads says it is required.
    usage = " ".join(p.format_usage().removeprefix("usage:").split())
    p.usage = "%(prog)s" + re.sub(r"\[(--kind \{[^}]*\})\]", r"\1",
                                  usage.removeprefix(p.prog), count=1)

    verb("list", "ids, headlines and Consequence lines by kind")

    p = verb("note", "add a dated paragraph to one entry", entry=True)
    p.add_argument("--by", required=True, help="who notes — role and round")
    p.add_argument("--text", required=True, help="the note, or - for stdin")
    p.add_argument("--left", action="store_true",
                   help="the wrap-up: you looked at the entry and changed nothing — "
                        "the note says why, and is the entry's mark")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("strike", "strike one live entry; prints its heading", entry=True)
    p.add_argument("--reason", required=True,
                   help="why — resolved/refuted names the commit and the re-run")
    p.add_argument("--by", help="who strikes, e.g. `consult 1`")
    p.add_argument("--commit", help="the commit that resolved the entry")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("amend", "correct a live entry: each field given replaces the entry's; "
                      "prints its heading", entry=True)
    p.add_argument("--by", help="who wrote the entry, in place of who appended it")
    p.add_argument("--headline", help=headline_help)
    p.add_argument("--body", help=body_help)
    p.add_argument("--consequence", help=consequence_help)
    p.add_argument("--proposal", help=proposal_help)
    _add_ask_args(p)
    p.add_argument("--provenance", help=provenance_help)
    p.add_argument("--severity", choices=SEVERITIES, type=_label_value, help=severity_help)
    _add_label_args(p, relabel=True)

    p = verb("relabel", "give an entry its labels or correct them", entry=True)
    p.add_argument("--by", required=True, help="who relabels")
    p.add_argument("--note", required=True,
                   help="what was found that the labels now say, or - for stdin")
    p.add_argument("--kind", choices=list(KINDS), type=_label_value,
                   help="the corrected kind; the id stays")
    _add_label_args(p, relabel=True)
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")
    p.add_argument("--dry-run", action="store_true",
                   help="print the note and the route the entry would take, and "
                        "write nothing")

    p = verb("restate", "give an entry the section the document shows for it, in place "
                        "of its author's text, which the record keeps", entry=True)
    p.add_argument("--by", required=True, help="who restates")
    p.add_argument("--headline", required=True,
                   help="the section's heading: the ask, as the operator reads it")
    p.add_argument("--body", required=True,
                   help="the story as it stands, told once — for a card request the "
                        "card's text, for a word request the exact edit and the rule; "
                        "or - for stdin")
    p.add_argument("--consequence", help="the Consequence line, where the story changed it")
    p.add_argument("--provenance", help="the Provenance line, where you witnessed or read "
                                        "it anew: " + provenance_help)
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("propose", "give an entry its proposal, or replace it", entry=True)
    p.add_argument("--by", required=True, help="who proposes")
    p.add_argument("--text", required=True,
                   help="what Agree does, in a ruling's words, one line of at most "
                        f"{asks.PROPOSAL_MAX} characters, or - for stdin")
    mark = p.add_mutually_exclusive_group()
    mark.add_argument("--card", dest="mark", action="store_const", const="card",
                      help="the wrap-up asks for a card, the entry restated as the card; "
                           "it becomes a card request")
    mark.add_argument("--word", dest="mark", action="store_const", const="word",
                      help="the wrap-up asks for the operator's word on an edit a rule of "
                           "the project reserves for them, the entry restated as the exact "
                           "edit and the rule; the entry comes to them")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("fold", "append an entry verbatim to the slice.md of the slice still "
                     "unplanned it is for, and stage it; prints the strike that follows "
                     "its commit", entry=True)
    p.add_argument("--into", metavar="SLICE",
                   help="the slice to fold it into, by its number (12, 012 or "
                        "012_slug), in place of the one its for label names")
    p.add_argument("--date", help="YYYY-MM-DD, the date the fold's first line "
                                  "carries; today when omitted")

    verb("worklist", "what waits for the wrap-up, with what is asked of each")

    p = verb("show", "one or more entries in full — body, notes, labels, marks, the "
                     "ruling; without an id, every live entry")
    p.add_argument("ids", nargs="*", metavar="<id>", help=id_help)
    p.add_argument("--card", action="store_true",
                   help="the card each named entry files: the section's heading, then "
                        "its body")

    p = verb("render", "write close-out-record.md, and close-out.md — the document "
                       "Pilot reads — unless Pilot wrote it back")
    p.add_argument("--step", help="the plan task the brief names, as the document's "
                                  "`step`; kept for every later render")
    p.add_argument("--summary", help="what the document is about, in one line; kept")
    p.add_argument("--context", action="append", metavar="PARAGRAPH",
                   help="a paragraph the asks share, before the run's own — the slice "
                        "in two lines; repeat it for each; kept")

    p = verb("absorb", "read close-out.md, as Pilot wrote it back, into the store: each "
                       "block's answer lines into its entry's ruling")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("rule", "record what was done on an entry's ruling — strikes the entry",
             entry=True)
    p.add_argument("--did", required=True,
                   help="what was done: carded as <card>, fixed in <commit>, folded "
                        "into <slice>, closed")
    p.add_argument("--commit", help="the commit of what was done")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("settle", "settle a criterion owed after an operator's action — writes its "
                       "verdict into verification.json and strikes the action that waited "
                       "on it")
    p.add_argument("vid", metavar="<Vid>",
                   help="the criterion's id in verification.json, like V17")
    p.add_argument("--verdict", required=True, choices=SETTLE_VERDICTS,
                   help="what the criterion is, now that the action has happened")
    p.add_argument("--evidence", required=True, action="append",
                   help="the operator's words, or what was observed once the action had "
                        "happened, or - for stdin; repeatable, each added after the "
                        "evidence the criterion holds")
    p.add_argument("--rationale",
                   help="replaces the criterion's rationale; `Settled <verdict> after "
                        "<owed_after>, <date>.` when omitted")
    p.add_argument("--by", help="who settles — signs the strike, and the note on a push "
                                "hold's action that still waits on another criterion")

    p = verb("close", "close the report once its answers are carried out: every live "
                      "entry struck, but one whose ruling nobody carried out")
    p.add_argument("--by", help="who closes")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    for p in sub.choices.values():
        _positionals_first(p)
    return parser, sub.choices


def _positionals_first(p: argparse.ArgumentParser) -> None:
    """Set `p`'s usage to argparse's own line with the positionals moved
    from its tail to right after the verb, in their order — `strike
    <close-out.md> <id> --reason REASON …`. A custom usage already set
    (append's required `--kind`) is reordered the same way."""
    usage = " ".join(p.format_usage().removeprefix("usage:").split())
    shapes = {"?": "[{}]", "*": "[{} ...]"}
    tokens = [shapes.get(a.nargs, "{}").format(a.metavar)
              for a in p._actions if not a.option_strings]
    if not tokens:
        return
    tail = " " + " ".join(tokens)
    assert usage.startswith(p.prog) and usage.endswith(tail), usage
    rest = usage.removeprefix(p.prog).removesuffix(tail)
    p.usage = "%(prog)s" + tail + rest


def verb_usage(*verbs: str) -> str:
    """The named verbs as a dispatch carries them: each verb's usage line
    (one line, `-h` dropped) followed by one indented line per argument
    with its help, a positional labelled by its metavar. Rendered from the
    parser, so an agent handed this block has the argument shapes without a
    `--help` round trip and the block cannot say something the CLI does
    not. The positionals lead the line: an agent reads it as the call's
    shape, and argparse's positionals-last order had agents type a
    trailing `slice` literally and put the id before the report."""
    _, subs = build_parser()
    out: list[str] = []
    for verb in verbs:
        sub = subs[verb]
        usage = " ".join(sub.format_usage().removeprefix("usage:").split())
        out.append(usage.replace(" [-h]", ""))
        for action in sub._actions:
            # `slice` is the report path the dispatch line already names
            if action.dest in ("help", "slice") or not action.help \
                    or action.help == argparse.SUPPRESS:
                continue
            name = ", ".join(action.option_strings) or action.metavar or action.dest
            if isinstance(name, tuple):
                name = " ".join(name)
            out.append(f"    {name}: {action.help}")
    return "\n".join(out)


def labels_text() -> str:
    """The contract's `## The labels` section, verbatim, up to the next
    `## ` heading."""
    try:
        text = CONTRACT_DOC.read_text(encoding="utf-8")
    except OSError as e:
        raise ReportError(f"{CONTRACT_DOC} is unreadable: {e}") from None
    lines = text.split("\n")
    try:
        start = lines.index(LABELS_HEADING)
    except ValueError:
        raise ReportError(f"{CONTRACT_DOC} has no `{LABELS_HEADING}` "
                          "section") from None
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).rstrip("\n")


def _check_of(args) -> str | None:
    """`--check`, repeated, as the one value the entry keeps: the checks
    joined by `; `; None when not given, and empty to remove it."""
    given = getattr(args, "check", None)
    return None if given is None else checks.join(given)


def _stdin_or(value: str) -> str:
    return sys.stdin.read() if value == "-" else value


def _append_cli(slice_dir: Path, args) -> str:
    if args.kind:
        kind = args.kind
    elif args.section:
        kind = _kind_of(args.section)
    else:
        raise ReportError("append needs --kind")
    labels = _labels_from(args)
    options = _options_from(args)
    body = _stdin_or(args.body)
    candidate = {"kind": kind, "headline": args.headline, "proposal": args.proposal}
    _set_ask_fields(candidate, options, args.recommend, _check_of(args), args.due)
    errors = check_labels(kind, labels, args.consequence, slice_dir)
    errors += author_problems(candidate)
    errors += _citations(args, body)
    errors += asks.proposal_problems(_collapse(args.proposal), "--proposal")
    if errors:
        raise ReportError("\n".join(errors))
    labels = normalise_for(labels, slice_dir)
    return append_entry(slice_dir, kind, args.headline, body,
                        consequence=args.consequence, provenance=args.provenance,
                        severity=args.severity, labels=labels,
                        proposal=args.proposal, by=args.by, options=options,
                        recommend=args.recommend, check=_check_of(args), due=args.due)


def _citations(args, body: str | None) -> list[str]:
    """An author's text, as `append` and `amend` take it, where it cites a
    line by its number (`asks.citation_problems`, the rule
    `docs/spec-tree.md` § Citing a line); a field not given is not checked.
    The loops' path is not checked: a driver's text quotes tool output."""
    return asks._cli_citations({
        "--headline": args.headline, "--body": body, "--consequence": args.consequence,
        "--proposal": args.proposal, "an --option": args.option})


def _refuse_citations(what: str, text: str) -> str:
    """`text` as given, refused where it cites a line by its number."""
    found = asks.citation_problems(text, what)
    if found:
        raise ReportError("\n".join(found))
    return text


def _amend_cli(slice_dir: Path, args) -> str:
    body = None if args.body is None else _stdin_or(args.body)
    errors = _citations(args, body)
    if args.proposal is not None:
        errors += asks.proposal_problems(_collapse(args.proposal), "--proposal")
    if errors:
        raise ReportError("\n".join(errors))
    return amend_entry(slice_dir, args.id, by=args.by, headline=args.headline,
                       body=body,
                       consequence=args.consequence, proposal=args.proposal,
                       provenance=args.provenance, severity=args.severity,
                       labels=_labels_from(args), options=_options_from(args),
                       recommend=args.recommend, check=_check_of(args), due=args.due)


def _restate_cli(slice_dir: Path, args) -> str:
    body = _stdin_or(args.body)
    errors = asks._cli_citations({"--headline": args.headline, "--body": body,
                                  "--consequence": args.consequence})
    if errors:
        raise ReportError("\n".join(errors))
    return restate_entry(slice_dir, args.id, args.by, args.headline, body,
                         consequence=args.consequence, provenance=args.provenance,
                         date=args.date)


def _propose_cli(slice_dir: Path, args) -> str:
    text = _refuse_citations("the proposal", _stdin_or(args.text))
    errors = asks.proposal_problems(_collapse(text), "the proposal")
    if errors:
        raise ReportError("\n".join(errors))
    return propose_entry(slice_dir, args.id, args.by, text, date=args.date, mark=args.mark)


def main(argv=None) -> int:
    parser, _ = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "labels":
            print(labels_text())
            return 0
        slice_dir = slice_dir_of(args.slice)
        if not slice_dir.is_dir():
            print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
            return 2
        command = args.command
        if command == "init":
            created = init_report(slice_dir)
            print(f"{'created' if created else 'exists'} {store_path(slice_dir)}")
        elif command == "append":
            print(_append_cli(slice_dir, args))
        elif command == "list":
            print(list_view(slice_dir))
        elif command == "note":
            text = _refuse_citations("the note", _stdin_or(args.text))
            if args.left:
                print(leave_entry(slice_dir, args.id, args.by, text, date=args.date))
            else:
                add_note(slice_dir, args.id, args.by, text, date=args.date)
                print(f"{args.id} noted")
        elif command == "strike":
            print(strike_entry(slice_dir, args.id, args.reason, by=args.by,
                               commit=args.commit, date=args.date))
        elif command == "amend":
            print(_amend_cli(slice_dir, args))
        elif command == "relabel":
            print(relabel_entry(slice_dir, args.id, args.by, _stdin_or(args.note),
                                kind=args.kind,
                                labels=normalise_for(_labels_from(args), slice_dir),
                                date=args.date, dry_run=args.dry_run))
        elif command == "restate":
            print(_restate_cli(slice_dir, args))
        elif command == "propose":
            print(_propose_cli(slice_dir, args))
        elif command == "fold":
            print(fold_entry(slice_dir, args.id, into=args.into, date=args.date))
        elif command == "worklist":
            print(worklist_view(slice_dir))
        elif command == "show":
            if args.card and not args.ids:
                raise ReportError("show --card names the entries whose card it prints")
            print(card_view(slice_dir, args.ids) if args.card
                  else show_view(slice_dir, args.ids))
        elif command == "render":
            print(render_report(slice_dir, step=args.step, summary=args.summary,
                                context=args.context))
        elif command == "absorb":
            print("\n".join(absorb_report(slice_dir, date=args.date)))
        elif command == "rule":
            print(rule_entry(slice_dir, args.id, args.did, commit=args.commit,
                             date=args.date))
        elif command == "settle":
            print("\n".join(settle_criterion(slice_dir, args.vid, args.verdict,
                                             [_stdin_or(e) for e in args.evidence],
                                             rationale=args.rationale, by=args.by)))
        elif command == "close":
            n, stay = close_report(slice_dir, by=args.by, date=args.date)
            if stay:
                print(f"{_plural(n, 'entry', 'entries')} closed; the report stays "
                      f"open over {', '.join(stay)}, ruled and not carried out")
            else:
                print(f"closed, {_plural(n, 'entry', 'entries')} with it")
    except ReportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
