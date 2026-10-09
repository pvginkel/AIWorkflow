#!/usr/bin/env python3
"""The close-out report's mechanics — the store, its verbs, the routing table, the render.

`<slice>/close-out.json` is the record every plan and run agent writes its
out-of-scope observations to, and `<slice>/close-out.md` is rendered from it
(${CLAUDE_PLUGIN_ROOT}/docs/close-out.md is the contract — the labels, the
routes, who writes what; docs/close-out-template.md the shapes of both files).
Every writer goes through this tool — the shape is mechanical, the content
is judgment — and nobody edits either file by hand; importable by both loops
(the way plan_loop imports run_loop) and a CLI for the agents and the skills:

  init         create the store (no entries) and render it; an existing
               store is never touched.
  labels       print the contract's `## The labels` section.
  append       add one entry with the labels its kind carries — refused,
               naming the flag, when one is missing, belongs to the other
               family, or contradicts the Consequence line. Prints the id:
               the kind's letter and the next number under it.
  list         the view an agent takes before it appends: per kind, ids,
               headlines and Consequence lines, struck entries marked.
  note         add a dated paragraph `<who>, <date> — <text>` to one entry.
  strike       strike one entry, with the reason and the commit.
  relabel      give an entry its labels or correct them, with a note of what
               changed and why. The id never changes, not even with the kind.
  propose      give an entry its proposal — what the author would do about
               it — or replace it, the old one kept as a note.
  request-card the wrap-up asks for a card on an entry; its words become the
               entry's proposal.
  leave        the wrap-up looked at an entry and changed nothing.
  worklist     what waits for the wrap-up, with what is asked of each.
  show         one or more entries in full — the view a reader of the
               evidence takes, now that the report carries the ask alone.
  rule         the operator's words on an entry, and what was done on them;
               without an id, the `Disposition:` lines of close-out.md read
               back into the store.
  close        close the report on the operator's word.
  render       read the `Disposition:` lines back, then write close-out.md:
               sections by route, each entry in its form — the ask (headline,
               Proposal, Consequence) where something is asked, the route
               where it is closed, the heading alone in the record — the run
               header from state.json.
  stamp        render, printing the run header.
  counts       live entries per section of the report and per id letter.
  import       read a close-out.md of the old, parsed shape into a store.

The route is computed at every render, never stored: `route()` reads an
entry's kind and labels, and the repositories the slice touched, against the
two tables of the contract (§ The routes) — the policy is the operator's and
lives here only.

A report written before the store existed is imported by the first call that
finds a `close-out.md` and no store beside it. The old parser stays as the
reader behind that import: sections, `###` blocks read outside fenced code and
outside HTML comments (an entry that quotes `## Bugs` or `### B3` inside a
fence moves no boundary), struck headings, folds, the three bold label lines.

Every read-modify-write of the store holds an exclusive flock on the slice
directory itself (no lock file lands in the spec repo's tree): the close-out
session rules while the wrap-up it dispatched strikes and relabels, and a
write lost to an overlap can be the operator's ruling. Under the same lock,
every write reads the `Disposition:` lines back first and, when the store
changed, writes close-out.md from it after it saves, so the report never
lags its store and no write loses what the operator wrote there; `render`
writes it whether or not anything changed. A filesystem that refuses the
flock gets the write without it.

`<slice>` is the slice directory or its close-out.md — the dispatch names the
report, so the report's path is what an agent has in hand; a `.md` or `.json`
argument resolves to its directory.

Exit codes: 0 ok · 2 usage/precondition error.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import string
import sys
import tempfile
import textwrap
import threading
from datetime import datetime
from pathlib import Path

REPORT_NAME = "close-out.md"
STORE_NAME = "close-out.json"
STORE_VERSION = 1

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
{store}. Write to it only through `python3 {tool} <verb> {report} …` —
`append`, `note`, `strike`; `list` shows what is there (ids, headlines,
Consequence lines) — never edit either file by hand, and commit the store
with your own commit, staged by name. An entry carries labels that say
what it is, and the tool routes it from them: you state what you know
and, where `append` asks for a proposal, what you would do — never where
the entry goes. `python3 {tool} labels` prints what each label means —
read it before your first append. The labels each kind carries, every one
of them, `unknown` where you cannot tell:
{kind_labels}
{label_pairing}
The verbs take:
{verb_usage}
The report is about the work; what got in your way while working, and any
improvement of the workflow itself, goes to the `fieldnotes` MCP tool
`post` instead.\
"""

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
# passes one (the loops still do), and the letter an imported entry's id
# carried under each.
SECTIONS: dict[str, str] = {
    "Outstanding actions": "action",
    "Notable events": "event",
    "Bugs": "defect",
    "Open questions and rulings": "decision",
    "Suggestions": "improvement",
}
SECTION_LETTERS: dict[str, str] = {
    "Outstanding actions": "A",
    "Notable events": "N",
    "Bugs": "B",
    "Open questions and rulings": "Q",
    "Suggestions": "S",
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

# -- the report (docs/close-out-template.md § The report) ---------------------

REPORT_SECTIONS = ("Comes to you", "Card requests", "For the wrap-up",
                   "Unlabelled", "Closed", "Record")
# The counts line's word for each section, in the same order.
COUNT_NAMES = ("to you", "card requests", "wrap-up", "unlabelled", "closed",
               "record")
# The smoke counts that trail the counts line when there are any.
NO_CONSEQUENCE = "no_consequence"
NO_PROVENANCE = "no_provenance"
NO_PROPOSAL = "no_proposal"

HEAD_COMMENT = """\
<!-- Generated by `close_out.py render` from close-out.json, the record. The `Disposition:`
     lines are yours to write; everything else is overwritten by the next render.
     `close_out.py show <id>` prints an entry in full. -->"""
UNSTAMPED = "Run: <not yet stamped>"

# A report rendered before 0.9.70 folded bodies in `<details>`; the read-back
# still ends an entry's Disposition at a fold's close, and import takes the
# oldest fold off.
FOLD_CLOSE = "</details>"
OLD_FOLD_OPEN = "<details><summary>struck — body kept for the record</summary>"

# The kinds whose author owes a proposal: what comes to the operator by kind.
PROPOSAL_KINDS = ("action", "decision", "improvement")
PROPOSAL_HELP = "what you would do about it and why, in a sentence or two"

HEADER_WIDTH = 96

RULED_BY = "the operator's ruling"

_SECTION_RE = re.compile(r"^## (?P<name>.+?)\s*$")
_ENTRY_RE = re.compile(r"^### (~~)?(?P<letter>[A-Z])(?P<num>\d+)\b")
_ANY_HEADING_RE = re.compile(r"^### ")
_ID_RE = re.compile(r"([A-Z])(\d+)")
# The three label lines of an old-shape entry; bold in the shape, bare too.
_LABEL_LINE_RES: dict[str, re.Pattern] = {
    "Consequence": re.compile(r"^\*{0,2}Consequence:\*{0,2}\s*"),
    "Provenance": re.compile(r"^\*{0,2}Provenance:\*{0,2}\s*"),
    "Disposition": re.compile(r"^\*{0,2}Disposition:\*{0,2}\s*"),
}
_ANY_LABEL_LINE_RE = re.compile(
    r"^\*{0,2}(Consequence|Provenance|Disposition|Triage|Route):")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# An HTML comment counts only when it opens a line (the template's comments
# all do); `<!--` mentioned mid-line in prose opens nothing.
_COMMENT_OPEN_RE = re.compile(r"^\s*<!--")
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


def dispatch_line(report: Path | str) -> str:
    """The report pointer a dispatch prompt carries — the path, the store,
    the tool, the labels each kind carries and how they pair, as
    `check_labels` holds them, and the arguments of the three verbs it
    names, rendered from the parser."""
    return DISPATCH_LINE.format(report=report, store=STORE_NAME, tool=TOOL_PATH,
                                kind_labels=kind_labels_text(),
                                label_pairing=LABEL_PAIRING,
                                verb_usage=verb_usage("append", "note", "strike"))


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
    """The store — imported first from a close-out.md of the old shape when
    that is all the slice holds. Called under the lock."""
    path = store_path(slice_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if report_path(slice_dir).exists():
            store = _import(slice_dir)
            _save(slice_dir, store)
            return store
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
def _writing(slice_dir: Path | str, receipt: dict | None = None):
    """The one path every change takes: lock, load, read the `Disposition:`
    lines of close-out.md back, change, save and render close-out.md (only
    when something changed), release. The read-back comes first, so a write
    never overwrites words the operator wrote on the report and the store
    has not taken yet. With `receipt`, close-out.md is rendered whether or
    not anything changed, and the receipt gets the (id, words) taken
    (`taken`) and the entries per section written (`tally`). An exception
    inside writes nothing."""
    with _locked(slice_dir):
        store = _load(slice_dir)
        before = _dump(store)
        taken = _read_back(slice_dir, store)
        yield store
        changed = _dump(store) != before
        if changed:
            _save(slice_dir, store)
        if changed or receipt is not None:
            tally = _write_report(slice_dir, store)
            if receipt is not None:
                receipt.update(taken=taken, tally=tally)


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
           proposal: str | None = None) -> dict:
    evidence, author = _split_provenance(provenance)
    return {
        "id": eid, "kind": kind, "grade": severity,
        "headline": _collapse(headline), "body": body,
        "consequence": _collapse(consequence) or None,
        "proposal": _collapse(proposal) or None,
        "evidence": evidence, "author": author,
        "labels": _ordered_labels(labels) if labels is not None else None,
        "notes": [], "wrap_up": None, "strike": None, "ruling": None,
    }


# -- the API both loops import -----------------------------------------------

def init_report(slice_dir: Path | str) -> bool:
    """Create the store, without entries, and render it. True when created;
    False when a store — or a close-out.md to import — was already there
    (the second is imported, nothing else)."""
    with _locked(slice_dir):
        if store_path(slice_dir).exists():
            return False
        if report_path(slice_dir).exists():
            _load(slice_dir)
            return False
        _save(slice_dir, _new_store(slice_dir))
        render_report(slice_dir)
        return True


def append_entry(slice_dir: Path | str, section: str, headline: str,
                 body: str, consequence: str | None = None,
                 provenance: str | None = None,
                 severity: str | None = None,
                 labels: dict | None = None,
                 proposal: str | None = None) -> str:
    """Append one entry; returns its id. `section` is a kind or one of the
    old section names. The loops' path, and it refuses nothing about labels
    or the proposal: without labels, an action, an event or a decision gets
    the tool's own (`tool_labels`) and any other kind is stored unlabelled.
    The CLI checks an author's labels and proposal before it gets here."""
    kind = _kind_of(section)
    if severity is not None and severity not in SEVERITIES:
        raise ReportError(f"unknown severity {severity!r}; one of "
                          + ", ".join(SEVERITIES))
    if labels is None:
        labels = tool_labels(kind, consequence)
    with _writing(slice_dir) as store:
        eid = _next_id(store, KINDS[kind])
        store["entries"].append(_entry(eid, kind, headline, _lines(body),
                                       consequence, provenance, severity,
                                       labels, proposal))
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
                          + _struck_heading(entry)[4:])
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


def relabel_entry(slice_dir: Path | str, eid: str, by: str, note: str,
                  kind: str | None = None, labels: dict | None = None,
                  date: str | None = None) -> str:
    """Merge `labels` into an entry's (an unlabelled one gets its first),
    correct its kind where given — the id stays — and leave a note saying
    what changed and why. The refusals of `append` apply to the labels as
    they are after the change, but not the one against the Consequence line
    (that is the author's text; the wrap-up corrects a label from the code).
    Moving the kind to the other family drops the labels of the old one.
    Returns the note's paragraph."""
    note_lines = _lines(note.strip())
    if not note_lines:
        raise ReportError("relabel needs a --note: what was found")
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        old_kind = entry.get("kind")
        new_kind = kind or old_kind
        if new_kind not in KINDS:
            raise ReportError(f"{eid} has no kind; relabel it with --kind")
        old = effective_labels(entry) or {}
        merged = dict(old)
        if (old_kind == "improvement") != (new_kind == "improvement"):
            drop = IMPROVEMENT_FAMILY if old_kind == "improvement" else FIX_FAMILY
            for k in drop:
                merged.pop(k, None)
        merged.update({k: v for k, v in (labels or {}).items() if v is not None})
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
        text = [f"relabelled ({said}): {note_lines[0]}", *note_lines[1:]]
        record = {"by": _collapse(by), "date": day, "text": text,
                  "relabel": changes}
        if not record["by"]:
            raise ReportError("relabel needs --by")
        entry["notes"].append(record)
        return _note_text(record)


def _set_proposal(entry: dict, who: str, day: str, text: str) -> None:
    """Give the entry `text` as its proposal; one it already had, and that
    says something else, stays as a note signed by whoever replaced it."""
    old = entry.get("proposal")
    if old and old != text:
        entry["notes"].append({"by": who, "date": day,
                               "text": [f"proposal replaced — was: {old}"]})
    entry["proposal"] = text


def propose_entry(slice_dir: Path | str, eid: str, by: str, text: str,
                  date: str | None = None) -> str:
    """Give a live entry its proposal — what its author would do about it
    and why — or replace the one it has, the old one kept as a note.
    Returns the Proposal line."""
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
        _set_proposal(entry, who, day, proposal)
    return f"**Proposal:** {proposal}"


def _mark_wrap_up(slice_dir: Path | str, eid: str, outcome: str, by: str,
                  text: str, date: str | None, propose: bool = False) -> str:
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
        if entry.get("wrap_up"):
            # A second mark replaces the first; the first stays, as a note.
            prior = entry["wrap_up"]
            entry["notes"].append({"by": prior["by"], "date": prior["date"],
                                   "text": _wrap_up_lines(prior)})
        entry["wrap_up"] = {"outcome": outcome, "by": who, "date": day,
                            "text": lines}
        if propose:
            _set_proposal(entry, who, day, _collapse(text))
        return _note_text({"by": who, "date": day,
                           "text": _wrap_up_lines(entry["wrap_up"])})


def request_card(slice_dir: Path | str, eid: str, by: str, text: str,
                 date: str | None = None) -> str:
    """The wrap-up asks for a card on an entry: its route becomes a card
    request, and what it asks — how the problem is reached and what the
    fix takes — becomes the entry's proposal, as `propose` would set it."""
    return _mark_wrap_up(slice_dir, eid, "card", by, text, date, propose=True)


def leave_entry(slice_dir: Path | str, eid: str, by: str, text: str,
                date: str | None = None) -> str:
    """The wrap-up looked at an entry and changed nothing: what waited for
    it is closed; every other route stands."""
    return _mark_wrap_up(slice_dir, eid, "left", by, text, date)


def _rule(entry: dict, words: str | None, did: str | None,
          commit: str | None, day: str) -> None:
    ruling = entry.get("ruling")
    if words is not None:
        words = words.strip()
        if not words:
            raise ReportError("--words is empty")
        if ruling and ruling.get("words") and ruling["words"] != words:
            entry["notes"].append({"by": "the operator", "date": day,
                                   "text": _lines("ruled earlier: "
                                                  + ruling["words"])})
        if not ruling or ruling.get("words") != words:
            ruling = entry["ruling"] = {"words": words,
                                        "did": (ruling or {}).get("did"),
                                        "date": day}
    if did is not None:
        if not ruling or not ruling.get("words"):
            raise ReportError(f"{entry['id']} has no ruling to act on — give "
                              "the operator's --words with --did")
        did = _collapse(did)
        if not did:
            raise ReportError("--did is empty")
        ruling["did"] = did
        if not entry.get("strike"):
            _strike(entry, did, RULED_BY, commit, day)


def rule_entry(slice_dir: Path | str, eid: str, words: str | None = None,
               did: str | None = None, commit: str | None = None,
               date: str | None = None) -> str:
    """Record the operator's words on an entry, verbatim — a second ruling
    replaces the words and keeps the old ones in a note — and what the
    session did on them, which strikes the entry. Returns the Disposition
    line as the report shows it."""
    if words is None and did is None:
        raise ReportError("rule <id> needs --words, --did, or both")
    day = _date(date)
    with _writing(slice_dir) as store:
        entry = _find(store, eid)
        _rule(entry, words, did, commit, day)
        return f"{entry['id']}: {_disposition(entry)}"


def close_report(slice_dir: Path | str, words: str,
                 date: str | None = None) -> tuple[int, list[str]]:
    """Close the report on the operator's word: every live entry without a
    ruling takes the words as its ruling and is struck. An entry that
    carries a ruling nobody executed — a `defer`, words read back and not
    acted on yet — stays live, and a report that keeps a live entry is not
    closed. Returns how many entries were closed, and the ids that stay."""
    words = (words or "").strip()
    if not words:
        raise ReportError("close needs the operator's --words")
    day = _date(date)
    with _writing(slice_dir) as store:
        if store.get("closed"):
            raise ReportError(f"the report was closed on "
                              f"{store['closed']['date']} — "
                              f"{store['closed']['words']}")
        n, stay = 0, []
        for entry in store["entries"]:
            if entry.get("strike"):
                continue
            if _ruled(entry):
                stay.append(entry["id"])
                continue
            entry["ruling"] = {"words": words, "did": None, "date": day}
            _strike(entry, f"closed with the report, {day}", None, None, day)
            n += 1
        if not stay:
            store["closed"] = {"date": day, "words": words}
        return n, stay


# -- labels: the checks of `append` and `relabel` -----------------------------

def slices_to_run(slice_dir: Path | str) -> dict[int, str] | None:
    """Number → folder number as written, of every slice still to run: a
    `<number>_*` folder directly under the nearest `slices` ancestor of the
    slice folder, or under its `backlog/` — the slice itself left out. None
    without such an ancestor."""
    here = Path(slice_dir).resolve()
    root = next((p for p in here.parents if p.name == "slices"), None)
    if root is None:
        return None
    out: dict[int, str] = {}
    for parent in (root, root / "backlog"):
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            m = re.match(r"(\d+)_", child.name)
            if m and child.is_dir() and child.resolve() != here:
                out.setdefault(int(m.group(1)), m.group(1))
    return out


def _flag(label: str) -> str:
    return f"--{label}"


def _flags(labels) -> str:
    names = [_flag(k) for k in labels]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


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

FOR_RULE = ("--for names another slice, still to run, that should take the "
            "entry, never the slice being run — leave it out for an entry "
            "about this one")


def check_labels(kind: str, labels: dict, consequence: str | None,
                 slice_dir: Path | str, given: dict | None = None,
                 relabel: bool = False) -> list[str]:
    """What `append` (and `relabel`) refuse, one message per refusal, each
    naming the flag: a label the kind carries that is missing, a label of
    the other family, an impact that contradicts the Consequence line (not
    on a relabel), a signal that contradicts the impact (not on a relabel),
    a benefit of the workflow, a `for` naming no slice still to run.
    `labels` are the entry's labels as they would be stored; `given` the
    flags of this call, for the other-family check."""
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
    if target is not None:
        m = re.match(r"(\d+)(?:_|$)", str(target))
        pending = slices_to_run(slice_dir)
        if pending is None:
            errors.append(f"--for {target}: the slice folder has no `slices` "
                          "ancestor, so no slice still to run can be named")
        elif not m or int(m.group(1)) not in pending:
            own = re.match(r"(\d+)_", Path(slice_dir).resolve().name)
            if m and own and int(m.group(1)) == int(own.group(1)):
                errors.append(f"--for {target} is the slice being run: {FOR_RULE}")
            else:
                errors.append(f"--for {target}: no other slice still to run has "
                              "that number (a <number>_* folder in slices/ or "
                              f"slices/backlog/): {FOR_RULE}")
    return errors


def normalise_for(labels: dict, slice_dir: Path | str) -> dict:
    """`for` as the folder's number is written (`12`, `012` and `012_slug`
    all name 012)."""
    target = labels.get("for")
    if target is None:
        return labels
    m = re.match(r"(\d+)", str(target))
    pending = slices_to_run(slice_dir) or {}
    if m and int(m.group(1)) in pending:
        return {**labels, "for": pending[int(m.group(1))]}
    return labels


# -- the routes (close-out.md § The routes) ------------------------------------

def effective_labels(entry: dict) -> dict | None:
    """The entry's labels — or, for a kind the tool labels itself that
    arrived without any, the tool's."""
    if entry.get("labels") is not None:
        return entry["labels"]
    return tool_labels(entry.get("kind"), entry.get("consequence"))


def touched_repos(slice_dir: Path | str) -> set[str] | None:
    """The basenames of every `root` in the slice's state.json — the
    repositories its phases landed in. None without a state.json, or one
    that names no root: every repository is then the slice's own."""
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


def _card_or_close(repo: str, card: bool) -> tuple[str, str]:
    where = f"the fix lives in {repo}, which the slice did not touch"
    return ("card:table", f"card request — {where}") if card \
        else ("closed:elsewhere", f"closed — {where}")


def _route_fix(entry: dict, lab: dict, touched: set[str] | None) -> tuple[str, str]:
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
    if lab.get("for"):                                              # 4
        return _fold(lab)
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


def _route_improvement(entry: dict, lab: dict,
                       touched: set[str] | None) -> tuple[str, str]:
    """What could be better: the first row that fits."""
    if lab.get("for"):                                              # 1
        return _fold(lab)
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


def table_route(entry: dict, touched: set[str] | None = None) -> tuple[str, str]:
    """(key, the Route line's words) of a live entry by the tables alone —
    the wrap-up's mark not applied. `unlabelled` when the entry has no
    labels and is not a kind the tool labels itself."""
    lab = effective_labels(entry)
    if lab is None or entry.get("kind") not in KINDS:
        return "unlabelled", "none yet — the entry has no labels"
    if entry["kind"] == "improvement":
        return _route_improvement(entry, lab, touched)
    return _route_fix(entry, lab, touched)


def route(entry: dict, touched: set[str] | None = None) -> tuple[str, str]:
    """(key, the Route line's words) of an entry — computed, never stored.
    A struck entry has none: it is in the record. The wrap-up's mark
    overrides the table: a card asked for makes a card request; an entry
    it looked at and left is closed, where the table sent it to the
    wrap-up."""
    if entry.get("strike"):
        return "record", "the record"
    key, words = table_route(entry, touched)
    mark = (entry.get("wrap_up") or {}).get("outcome")
    if mark == "card":
        return "card:wrap-up", "card request — the wrap-up asks for a card"
    if mark == "left" and key.startswith("wrap-up:"):
        return "closed:left", "closed — the wrap-up looked and left it"
    return key, words


def report_section(key: str) -> str:
    """The section of the report a route key lands in."""
    head = key.split(":", 1)[0]
    return {"operator": "Comes to you", "card": "Card requests",
            "wrap-up": "For the wrap-up", "unlabelled": "Unlabelled",
            "closed": "Closed", "record": "Record"}[head]


# -- worklist ----------------------------------------------------------------

def _ruled(entry: dict) -> bool:
    return bool((entry.get("ruling") or {}).get("words"))


def _asked(entry: dict, touched: set[str] | None) -> str | None:
    """What the wrap-up is asked to do with an entry, None when it waits for
    nothing. An entry the operator has ruled on is theirs, whatever its
    route: it does not wait."""
    if entry.get("strike") or entry.get("wrap_up") or _ruled(entry):
        return None
    key, _ = table_route(entry, touched)
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
    if key == "operator:risk":
        return "note — note what the code says under it; the entry stays the operator's"
    return None


def worklist(slice_dir: Path | str) -> list[tuple[dict, str]]:
    """(entry, what is asked) for every entry that waits for the wrap-up,
    in order of arrival."""
    store = _read_store(slice_dir)
    touched = touched_repos(slice_dir)
    out = []
    for entry in store["entries"]:
        asked = _asked(entry, touched)
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
    """Live entries per section of the report — the events in the record
    counted, the struck ones not — then live entries per id letter (the
    old letters only where the store holds such entries), then the smoke
    counts: live entries without a Consequence or a Provenance line, and
    those that come to the operator (to you, card requests) without a
    proposal."""
    store = _read_store(slice_dir)
    touched = touched_repos(slice_dir)
    counts = dict.fromkeys(COUNT_NAMES, 0)
    by_name = dict(zip(REPORT_SECTIONS, COUNT_NAMES, strict=True))
    letters = dict.fromkeys(KINDS.values(), 0)
    for entry in store["entries"]:
        m = _ID_RE.fullmatch(entry["id"])
        if m and m.group(1) in OLD_LETTERS:
            letters.setdefault(m.group(1), 0)
    no_consequence = no_provenance = no_proposal = 0
    for entry in store["entries"]:
        if entry.get("strike"):
            continue
        key, _ = route(entry, touched)
        counts[by_name[report_section(key)]] += 1
        letter = _ID_RE.fullmatch(entry["id"]).group(1)
        letters[letter] = letters.get(letter, 0) + 1
        no_consequence += not entry.get("consequence")
        no_provenance += not (entry.get("evidence") or entry.get("author"))
        no_proposal += (key.startswith(("operator:", "card:"))
                        and not entry.get("proposal"))
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
    glued = line.replace(" · ", "\u00a0· ")
    return [part.replace("\u00a0", " ")
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
    said = "asks for a card" if mark["outcome"] == "card" else "looked and left it"
    return [f"{said}: {mark['text'][0]}", *mark["text"][1:]]


def _notes(entry: dict) -> list[str]:
    paras = [_note_text(n) for n in entry.get("notes") or []]
    if entry.get("wrap_up"):
        mark = entry["wrap_up"]
        paras.append(_note_text({"by": mark["by"], "date": mark["date"],
                                 "text": _wrap_up_lines(mark)}))
    return paras


def _disposition(entry: dict) -> str:
    """What the Disposition line carries: the operator's words, then ` — `
    and what was done on them; empty until they rule."""
    ruling = entry.get("ruling") or {}
    words = ruling.get("words") or ""
    if words and ruling.get("did"):
        return f"{words} — {ruling['did']}"
    return words


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


def _disposition_line(entry: dict) -> str:
    disposition = _disposition(entry)
    return f"**Disposition:** {disposition}" if disposition else "**Disposition:**"


def _tail(entry: dict, route_words: str | None) -> list[str]:
    """The lines under the body in the full view: Consequence, then the
    block the entry is triaged on — Triage, Provenance, Route,
    Disposition."""
    out: list[str] = []
    if entry.get("consequence"):
        out += [f"**Consequence:** {entry['consequence']}", ""]
    triage = _triage_words(entry)
    if triage:
        out += _wrap(f"**Triage:** {triage}")
    provenance = _provenance(entry)
    if provenance:
        out.append(f"**Provenance:** {provenance}")
    if route_words:
        out.append(f"**Route:** {route_words}")
    out.append(_disposition_line(entry))
    return out


# What plan_loop.py writes into every owed-after action: true of each one,
# so the report leaves it out (`show` keeps it).
_OWED_HEADLINE_RE = re.compile(r"^Settle (?P<vid>V\d+) after\b")
_OWED_CONSEQUENCE_RE = re.compile(r"^V\d+ stays unproven until then; the test phase "
                                  r"does not settle it\.?$")
_OWED_PROPOSAL_RE = re.compile(r"^When that has happened, say so: the session settles V\d+")
# A Route that only says the kind, which the Triage line names already; a
# risk's says why it came, and stays.
_KIND_ONLY_ROUTES = ("to you — an action", "to you — a decision", "to you — an improvement")


def _verification(slice_dir: Path | str) -> dict[str, dict]:
    """verification.json's items by id; empty when it is missing or unreadable."""
    try:
        data = json.loads((Path(slice_dir) / "verification.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    return {i["id"]: i for i in items or [] if isinstance(i, dict) and i.get("id")}


def _ask_heading(entry: dict, vmap: dict[str, dict]) -> str:
    """The heading, with an owed-after action's criterion named by its area
    and its owed-after in full, where plan_loop.py shortened them."""
    m = _OWED_HEADLINE_RE.match(entry.get("headline") or "")
    item = vmap.get(m.group("vid")) if m else None
    if entry.get("strike") or not item or not item.get("owed_after"):
        return _heading(entry)
    area = f" ({item['area']})" if item.get("area") else ""
    return f"### {entry['id']} — Settle {m.group('vid')}{area} after {item['owed_after']}"


def _latest(entry: dict) -> list[str]:
    """The newest note (a wrap-up mark counts as one) in full, and how many
    there are; nothing without one."""
    notes = list(entry.get("notes") or [])
    if entry.get("wrap_up"):
        mark = entry["wrap_up"]
        notes.append({"by": mark["by"], "date": mark["date"], "text": _wrap_up_lines(mark)})
    if not notes:
        return []
    last = notes[-1]
    count = f" · {len(notes)} notes" if len(notes) > 1 else ""
    text = "\n".join(last.get("text") or [])
    return [f"**Latest** ({last['by']}, {last['date']}{count}): {text}", ""]


def _short_strike_tail(strike: dict) -> str:
    """The struck heading's tail as the report gives it: the reason up to its
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


def _render_entry(entry: dict, form: str, route_words: str | None,
                  vmap: dict[str, dict] | None = None) -> str:
    """One entry in one of its forms. The report's three: `ask` (the
    headline, the body, the Proposal and the Consequence where they say
    more than every entry of their kind, the newest note, then Triage,
    Provenance, Route unless it only names the kind, and Disposition),
    `closed` (the heading, the Consequence unless it says none, Triage,
    Provenance, Route and Disposition) and `record` (the heading alone, a
    struck one's reason cut short). And `show`'s: `full`, the body, every
    note, the proposal and every label line."""
    if form == "record":
        if entry.get("strike"):
            return (f"### ~~{entry['id']} — {_headline_with_grade(entry)}~~ — "
                    + _short_strike_tail(entry["strike"]))
        return _heading(entry)
    if form == "full":
        lines = [_heading(entry), ""]
        body = _body_and_notes(entry)
        if body:
            lines += [body, ""]
        lines += _proposal_lines(entry)
        struck = bool(entry.get("strike"))
        return "\n".join(lines + _tail(entry, None if struck else route_words))
    consequence = entry.get("consequence")
    if form == "closed":
        lines = [_heading(entry), ""]
        if consequence and not opens_with_none(consequence):
            lines += [f"**Consequence:** {consequence}", ""]
        return "\n".join([*lines, *_triage_lines(entry), f"**Route:** {route_words}",
                          _disposition_line(entry)])
    lines = [_ask_heading(entry, vmap or {}), ""]
    body = "\n".join(entry.get("body") or []).strip()
    if body:
        lines += [body, ""]
    if entry.get("proposal") and not _OWED_PROPOSAL_RE.match(entry["proposal"]):
        lines += _proposal_lines(entry)
    if consequence and not _OWED_CONSEQUENCE_RE.match(consequence):
        lines += [f"**Consequence:** {consequence}", ""]
    lines += _latest(entry)
    lines += _triage_lines(entry)
    if route_words and route_words not in _KIND_ONLY_ROUTES:
        lines.append(f"**Route:** {route_words}")
    return "\n".join([*lines, _disposition_line(entry)])


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


def _title(store: dict) -> str:
    num, _, slug = str(store.get("slice") or "").partition("_")
    return f"# Close-out — slice {num} {slug}".rstrip()


def _header(slice_dir: Path | str) -> str:
    try:
        state = json.loads((Path(slice_dir) / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return UNSTAMPED
    return run_header(state, slice_dir) if isinstance(state, dict) else UNSTAMPED


def _placed(store: dict, slice_dir: Path | str,
            live_only: bool = False) -> list[tuple[str, list[tuple[dict, str]]]]:
    """(section, [(entry, its Route words)]) in the report's order: the
    sections as REPORT_SECTIONS, a section's entries as the render sorts
    them — the record's events first, then what was struck. With
    `live_only`, struck entries are left out."""
    touched = touched_repos(slice_dir)
    placed: dict[str, list[tuple[dict, str]]] = {s: [] for s in REPORT_SECTIONS}
    for entry in store["entries"]:
        if live_only and entry.get("strike"):
            continue
        key, words = route(entry, touched)
        placed[report_section(key)].append((entry, words))
    out = []
    for section in REPORT_SECTIONS:
        items = placed[section]
        if section == "Record":
            items = sorted(items, key=lambda x: (bool(x[0].get("strike")),
                                                 _id_key(x[0])))
        else:
            items = sorted(items, key=lambda x: _sort_key(x[0]))
        out.append((section, items))
    return out


def _render(store: dict, slice_dir: Path | str) -> tuple[str, dict[str, int]]:
    """The report's text and the number of entries in each section it
    wrote."""
    out = [_title(store), "", HEAD_COMMENT, "", *_wrap(_header(slice_dir))]
    if store.get("closed"):
        closed = store["closed"]
        out += ["", *_wrap(f"Closed: {closed['date']} — {_collapse(closed['words'])}")]
    tally: dict[str, int] = {}
    vmap = _verification(slice_dir)
    for section, items in _placed(store, slice_dir):
        if not items:
            continue
        form = {"Record": "record", "Closed": "closed"}.get(section, "ask")
        out += ["", f"## {section}"]
        for entry, words in items:
            out += ["", _render_entry(entry, form, words, vmap)]
        tally[section] = len(items)
    return "\n".join(out) + "\n", tally


def show_view(slice_dir: Path | str, ids: list[str] | None = None) -> str:
    """Entries in full — body, every note, Proposal, Consequence, Triage,
    Provenance, Route, Disposition: what the report cuts short, for the
    wrap-up, the close-out session and a card filing to read. The
    named ids in the order given, struck ones too; without ids every live
    entry, under its section's `## ` line, in the report's order."""
    store = _read_store(slice_dir)
    touched = touched_repos(slice_dir)
    if ids:
        entries = [_find(store, eid) for eid in ids]
        return "\n\n".join(_render_entry(e, "full", route(e, touched)[1])
                            for e in entries)
    out: list[str] = []
    for section, items in _placed(store, slice_dir, live_only=True):
        if not items:
            continue
        out.append(f"## {section}")
        out += [_render_entry(entry, "full", words) for entry, words in items]
    return "\n\n".join(out) or "no live entries"


def _read_back(slice_dir: Path | str, store: dict) -> list[tuple[str, str]]:
    """Take into the store every `Disposition:` line of close-out.md that
    differs from what the store would render there: the text is the
    operator's (`ruling.words`) — where it ends in ` — <did>` as the store
    has it, the words are what stands before that. Returns (id, words) per
    entry taken; changes `store` in place."""
    try:
        text = report_path(slice_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ReportError(f"{report_path(slice_dir)} is unreadable: {e}") from None
    found = _dispositions(text)
    by_id = {e["id"]: e for e in store["entries"]}
    taken: list[tuple[str, str]] = []
    day = _today()
    for eid, written in found.items():
        entry = by_id.get(eid)
        said = _collapse(written)
        if entry is None or not said or said == _collapse(_disposition(entry)):
            continue
        ruling = entry.get("ruling") or {}
        did = ruling.get("did")
        words = written.strip()
        if did and said.endswith(" — " + _collapse(did)):
            words = said[:-len(" — " + _collapse(did))].strip()
        if _collapse(words) == _collapse(ruling.get("words")):
            continue
        _rule(entry, words, None, None, day)
        taken.append((eid, words))
    return taken


def _dispositions(text: str) -> dict[str, str]:
    """Id → the text after an entry's last `Disposition:` label, up to the
    end of the entry (the next heading, or — in a report rendered before
    0.9.70, read back before its first re-render — the `</details>` of a
    fold), read off headings outside fences and comments."""
    out: dict[str, str] = {}
    current: str | None = None
    collected: list[str] | None = None

    def close() -> None:
        if current and collected is not None:
            out[current] = "\n".join(collected).strip()

    for line, what in _scan(text, kinds=True):
        hidden = what is not None
        if not hidden and (line.startswith("## ") or _ANY_HEADING_RE.match(line)):
            close()
            m = _ENTRY_RE.match(line)
            current = f"{m.group('letter')}{m.group('num')}" if m else None
            collected = None
            continue
        if current is None:
            continue
        if not hidden and _LABEL_LINE_RES["Disposition"].match(line):
            collected = [_LABEL_LINE_RES["Disposition"].sub("", line, count=1)]
            continue
        if collected is not None:
            if not hidden and line.strip() == FOLD_CLOSE:
                close()
                collected = None
                continue
            if what != "comment":   # a report's charter comment is nobody's words
                collected.append(line)
    close()
    return out


def _write_report(slice_dir: Path | str, store: dict) -> dict[str, int]:
    """Write close-out.md from the store, left alone when it already holds
    those bytes. Returns the number of entries in each section written.
    Called under the lock."""
    text, tally = _render(store, slice_dir)
    path = report_path(slice_dir)
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old != text:
        _write_atomic(path, text)
    return tally


def _rendered(slice_dir: Path | str) -> dict:
    """A write with no change of its own: the read-back, and close-out.md
    rendered even when the store stays as it was. Returns the receipt."""
    receipt: dict = {}
    with _writing(slice_dir, receipt):
        pass
    return receipt


def read_back(slice_dir: Path | str) -> list[tuple[str, str]]:
    """`rule` without an id: the `Disposition:` lines of close-out.md into
    the store, and close-out.md rendered from it. (id, words) per entry
    taken."""
    return _rendered(slice_dir)["taken"]


def render_report(slice_dir: Path | str) -> str:
    """Read the `Disposition:` lines back, then write close-out.md from the
    store, under the store's lock — whether or not the store changed, so a
    report that is missing or lags the run header is written; the same bytes
    when nothing changed. Returns a one-line tally of the sections
    written."""
    tally = _rendered(slice_dir)["tally"]
    return " · ".join(f"{name} {n}" for name, n in tally.items()) or "no entries"


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


# -- import: the old Markdown report -------------------------------------------

def _scan(text: str, kinds: bool = False):
    """(line, hidden) for every line: hidden inside a fenced code block or
    an HTML comment — with `kinds`, what hides it (`fence`, `comment`, or
    None). A comment runs from a line it opens to the line holding its
    `-->`; a fence opened inside a comment, or a comment inside a fence, is
    text."""
    fenced = commented = False
    for line in text.split("\n"):
        hidden = "fence"
        if commented:
            commented = "-->" not in line
            hidden = "comment"
        elif _FENCE_RE.match(line):
            fenced = not fenced
        elif fenced:
            pass
        elif _COMMENT_OPEN_RE.match(line):
            commented = "-->" not in line
            hidden = "comment"
        else:
            hidden = None
        yield line, (hidden if kinds else hidden is not None)


def _unfenced_lines(text: str):
    """(offset, line) for every line outside a fenced code block and outside
    an HTML comment — the only lines a heading can stand on."""
    offset = 0
    for line, hidden in _scan(text):
        if not hidden:
            yield offset, line
        offset += len(line) + 1


def _sections(text: str) -> list[tuple[str, int, int, int]]:
    """(name, heading_start, body_start, body_end) per `## ` heading; the
    body runs to the next `## ` heading or the end of the file."""
    heads = []
    for offset, line in _unfenced_lines(text):
        m = _SECTION_RE.match(line)
        if m:
            heads.append((m.group("name"), offset, offset + len(line)))
    out = []
    for i, (name, head, body_start) in enumerate(heads):
        end = heads[i + 1][1] if i + 1 < len(heads) else len(text)
        out.append((name, head, body_start, end))
    return out


def _blocks(body: str) -> list[tuple[str, str]]:
    """(heading, the text under it) per unfenced `###` heading of one
    section body, in file order."""
    heads = [(off, line) for off, line in _unfenced_lines(body)
             if _ANY_HEADING_RE.match(line)]
    out = []
    for i, (off, line) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(body)
        out.append((line, body[off + len(line):nxt]))
    return out


def _split_grade(text: str) -> tuple[str, str | None]:
    stem, sep, grade = text.rpartition(" · ")
    if sep and grade.strip().lower() in SEVERITIES:
        return stem.strip(), grade.strip().lower()
    return text.strip(), None


def _parse_heading(heading: str, letter: str) -> dict:
    """An old heading as (id, headline, grade, strike): `### B3 — <headline>
    · <grade>`, or the struck `### ~~B3 — <headline>~~ — <reason>; struck by
    <who>`. A heading not in that shape, or under another section's letter,
    has no id."""
    m = _ENTRY_RE.match(heading)
    if m is None or m.group("letter") != letter:
        return {"id": None, "headline": _collapse(heading[4:]), "grade": None,
                "strike": None}
    rest = heading[m.end():]
    strike = None
    if m.group(1):
        inside, _, tail = rest.partition("~~")
        rest = inside
        reason = re.sub(r"^\s*—\s*", "", tail).strip()
        by = None
        stem, sep, who = reason.rpartition("; struck by ")
        if sep:
            reason, by = stem.strip(), _collapse(who)
        strike = {"reason": _collapse(reason) or "struck", "by": by or None,
                  "date": None, "commit": None}
    headline, grade = _split_grade(_collapse(re.sub(r"^\s*—", "", rest)))
    return {"id": f"{letter}{m.group('num')}", "headline": headline,
            "grade": grade, "strike": strike}


def _take_label(lines: list[str], hidden: list[bool], label: str
                ) -> tuple[str | None, list[int]]:
    """The first unfenced paragraph opening with `label:` — its text,
    collapsed, and the line numbers it spans."""
    pattern = _LABEL_LINE_RES[label]
    for i, line in enumerate(lines):
        if hidden[i] or not pattern.match(line):
            continue
        span = [i]
        para = [pattern.sub("", line, count=1)]
        j = i + 1
        while (j < len(lines) and lines[j].strip() and not hidden[j]
               and not _ANY_LABEL_LINE_RE.match(lines[j])
               and not _ANY_HEADING_RE.match(lines[j])
               and lines[j].strip() != FOLD_CLOSE):
            para.append(lines[j])
            span.append(j)
            j += 1
        return "\n".join(para).strip(), span
    return None, []


def _parse_block(text: str) -> dict:
    """The body of one old block — its label lines and the fold taken off,
    nothing else lost — and the three labels."""
    lines = text.strip("\n").split("\n") if text.strip() else []
    hidden = [h for _, h in _scan("\n".join(lines))]
    drop: set[int] = set()
    # The old render's fold: its opening line, and the last `</details>`.
    opens = [i for i, line in enumerate(lines)
             if not hidden[i] and line.strip() == OLD_FOLD_OPEN]
    if opens:
        drop.add(opens[0])
        closes = [i for i, line in enumerate(lines)
                  if not hidden[i] and line.strip() == FOLD_CLOSE and i > opens[0]]
        if closes:
            drop.add(closes[-1])
    found: dict[str, str | None] = {}
    for label in ("Consequence", "Provenance", "Disposition"):
        value, span = _take_label(lines, hidden, label)
        found[label] = value
        drop.update(span)
    body: list[str] = []
    for i, line in enumerate(lines):
        if i in drop:
            continue
        # Squeeze the blank lines a removed line leaves behind.
        if not line.strip() and (not body or not body[-1].strip()):
            continue
        body.append(line.rstrip())
    while body and not body[-1].strip():
        body.pop()
    return {"body": body, "consequence": found["Consequence"],
            "provenance": found["Provenance"], "disposition": found["Disposition"]}


def _import(slice_dir: Path | str) -> dict:
    """A store from a close-out.md of the old shape. Every entry keeps its
    id and carries the section it stood under; the kind is the section's —
    with the tool's labels for an action, an event or a decision, none for
    a Bugs or Suggestions entry, which stays unlabelled until the wrap-up
    labels it. A `###` heading not in the entry shape becomes an entry with
    the next id under its section's letter. The head, the Summary, the
    sections' `Focus:` lines and charters are kept under `imported`, not
    rendered."""
    text = report_path(slice_dir).read_text(encoding="utf-8")
    store = _new_store(slice_dir)
    sections = _sections(text)
    imported: dict[str, list[str]] = {}
    head = _lines(text[:sections[0][1]] if sections else text)
    if head:
        imported["head"] = head
    pending: list[tuple[str, str, dict, dict]] = []
    taken: dict[str, set[int]] = {}
    for name, _, start, end in sections:
        body = text[start:end]
        if name not in SECTIONS:
            kept = _lines(body)
            if kept:
                imported[name] = kept
            continue
        letter = SECTION_LETTERS[name]
        blocks = _blocks(body)
        first = next((off for off, line in _unfenced_lines(body)
                      if _ANY_HEADING_RE.match(line)), len(body))
        preamble = _lines(body[:first])
        if preamble:
            imported[name] = preamble
        for heading, rest in blocks:
            parsed = _parse_heading(heading, letter)
            if parsed["id"]:
                num = int(parsed["id"][1:])
                if num in taken.setdefault(letter, set()):
                    parsed["id"] = None     # a duplicate id: a fresh one below
                    parsed["headline"] = _collapse(heading[4:])
                    parsed["strike"] = None
                    parsed["grade"] = None
                else:
                    taken[letter].add(num)
            pending.append((name, letter, parsed, _parse_block(rest)))
    for name, letter, parsed, block in pending:
        eid = parsed["id"]
        if eid is None:
            num = max(taken.get(letter) or {0}) + 1
            taken.setdefault(letter, set()).add(num)
            eid = f"{letter}{num}"
        kind = SECTIONS[name]
        entry = _entry(eid, kind, parsed["headline"], block["body"],
                       block["consequence"], block["provenance"], parsed["grade"],
                       tool_labels(kind, block["consequence"]))
        entry = {"id": entry.pop("id"), "kind": entry.pop("kind"), "section": name,
                 **entry}
        entry["strike"] = parsed["strike"]
        if block["disposition"]:
            entry["ruling"] = {"words": block["disposition"], "did": None,
                               "date": None}
        store["entries"].append(entry)
    if imported:
        store["imported"] = imported
    return store


def import_report(slice_dir: Path | str) -> int:
    """`import`: read close-out.md into a new store; refused when a store
    exists. Returns the number of entries."""
    with _locked(slice_dir):
        if store_path(slice_dir).exists():
            raise ReportError(f"{store_path(slice_dir)} exists — import reads a "
                              "report into a new store only")
        if not report_path(slice_dir).exists():
            raise ReportError(f"{report_path(slice_dir)} does not exist — "
                              "nothing to import")
        return len(_load(slice_dir)["entries"])


# -- CLI --------------------------------------------------------------------

def _label_value(value: str) -> str:
    """A label value as the tool keeps it: lower-case, spaces and
    underscores as hyphens (`test gap`, `ordinary_condition`)."""
    return re.sub(r"[\s_]+", "-", value.strip().lower())


# The help strings are prompt text: `verb_usage("append", "note",
# "strike")` is rendered into every dispatch.
LABEL_HELP = {
    "trigger": "what has to happen for the problem to show",
    "impact": "what is then experienced",
    "signal": "whether it then says so itself",
    "fix": "what is decided about the fix",
    "area": "sensitive: concurrency or timing, stored data, a wire contract, "
            "authentication or secrets",
    "repo": "the repository the fix lives in, by its directory name",
    "for": "the number of another slice, still to run, that should take the "
           "entry — never the slice being run; leave it out for an entry about "
           "this one",
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


def _add_label_args(p: argparse.ArgumentParser) -> None:
    for label in LABEL_FLAG_ORDER:
        values = LABELS[label]
        kwargs: dict = {"dest": f"label_{label.replace('-', '_')}",
                        "help": LABEL_HELP[label]}
        if values is None:
            kwargs["metavar"] = "NAME" if label == "repo" else "SLICE"
        else:
            kwargs.update(choices=values, type=_label_value)
        p.add_argument(f"--{label}", **kwargs)


def _labels_from(args) -> dict:
    return {label: getattr(args, f"label_{label.replace('-', '_')}")
            for label in LABELS
            if getattr(args, f"label_{label.replace('-', '_')}", None) is not None}


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
        p = sub.add_parser(name, help=help_)
        p.add_argument("slice", metavar="<close-out.md>", help=slice_help)
        if entry:
            p.add_argument("id", metavar="<id>", help=id_help)
        return p

    verb("init", "create the store and render it, if absent")

    sub.add_parser("labels", help="print what each label means")

    p = verb("append", "add one entry with its labels; prints its id")
    p.add_argument("--kind", choices=list(KINDS), type=_label_value,
                   help="what the entry is — it decides which of the labels "
                        "below the entry carries")
    p.add_argument("--section", help=argparse.SUPPRESS)
    p.add_argument("--headline", required=True,
                   help="one line, the claim itself — the ask, as the operator reads it: "
                        "a defect names its repo or component, an action is an "
                        "imperative, a decision asks its question, an improvement says "
                        "what it proposes")
    p.add_argument("--body", required=True, help="entry body, or - for stdin")
    p.add_argument("--consequence", required=True,
                   help="what an operator or user experiences if this stays as it is, "
                        "or none — the line the operator triages on")
    p.add_argument("--proposal",
                   help=f"{PROPOSAL_HELP}, in a ruling's words (card · fix now · "
                        "fold into <slice> · close · do it) — the operator reads it "
                        "with the headline and the Consequence and nothing else; "
                        "required for an action, a decision and an improvement")
    p.add_argument("--provenance",
                   help="witnessed | read, then role, phase, round, and the artifact "
                        "with the full record")
    p.add_argument("--severity", choices=SEVERITIES, type=_label_value,
                   help="the grade, where the entry has one")
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
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("strike", "strike one live entry; prints its heading", entry=True)
    p.add_argument("--reason", required=True,
                   help="why — resolved/refuted names the commit and the re-run")
    p.add_argument("--by", help="who strikes, e.g. `consult 1`")
    p.add_argument("--commit", help="the commit that resolved the entry")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("relabel", "give an entry its labels or correct them", entry=True)
    p.add_argument("--by", required=True, help="who relabels")
    p.add_argument("--note", required=True,
                   help="what was found that the labels now say, or - for stdin")
    p.add_argument("--kind", choices=list(KINDS), type=_label_value,
                   help="the corrected kind; the id stays")
    _add_label_args(p)
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("propose", "give an entry its proposal, or replace it", entry=True)
    p.add_argument("--by", required=True, help="who proposes")
    p.add_argument("--text", required=True,
                   help="what you would do about it and why, or - for stdin")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("request-card", "the wrap-up asks for a card on an entry", entry=True)
    p.add_argument("--by", required=True, help="who asks")
    p.add_argument("--text", required=True,
                   help="how it is reached and what the fix takes — it becomes the "
                        "entry's proposal; or - for stdin")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("leave", "the wrap-up looked at an entry and changed nothing", entry=True)
    p.add_argument("--by", required=True, help="who looked")
    p.add_argument("--text", required=True, help="why it stays, or - for stdin")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    verb("worklist", "what waits for the wrap-up, with what is asked of each")

    p = verb("show", "one or more entries in full — body, notes, labels, marks; "
                     "without an id, every live entry")
    p.add_argument("ids", nargs="*", metavar="<id>", help=id_help)

    p = verb("rule", "the operator's words on an entry; without an id, read the "
                     "Disposition lines back")
    p.add_argument("id", nargs="?", metavar="<id>", help=id_help)
    p.add_argument("--words", help="the operator's words, verbatim")
    p.add_argument("--did", help="what was done on them — strikes the entry")
    p.add_argument("--commit", help="the commit of what was done")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = verb("close", "close the report on the operator's word")
    p.add_argument("--words", required=True, help="the operator's words, verbatim")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    verb("render", "read the Disposition lines back, then write close-out.md")
    verb("stamp", "render, printing the run header from state.json")
    verb("counts", "live entries per section and per id letter, one line")
    verb("import", "read a close-out.md of the old shape into a new store")
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
    errors = check_labels(kind, labels, args.consequence, slice_dir)
    if kind in PROPOSAL_KINDS and not _collapse(args.proposal):
        errors.append(f"a{'n' if kind[0] in 'aeiou' else ''} {kind} needs "
                      f"--proposal: {PROPOSAL_HELP}")
    if errors:
        raise ReportError("\n".join(errors))
    labels = normalise_for(labels, slice_dir)
    return append_entry(slice_dir, kind, args.headline, _stdin_or(args.body),
                        consequence=args.consequence, provenance=args.provenance,
                        severity=args.severity, labels=labels,
                        proposal=args.proposal)


def _rule_cli(slice_dir: Path, args) -> str:
    if args.id is None:
        if args.words or args.did or args.commit:
            raise ReportError("--words, --did and --commit need an entry id")
        taken = read_back(slice_dir)
        if not taken:
            return "nothing to take from the Disposition lines"
        return "\n".join(f"{eid}: {_collapse(words)}" for eid, words in taken)
    return rule_entry(slice_dir, args.id, words=args.words, did=args.did,
                      commit=args.commit, date=args.date)


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
            add_note(slice_dir, args.id, args.by, _stdin_or(args.text), date=args.date)
            print(f"{args.id} noted")
        elif command == "strike":
            print(strike_entry(slice_dir, args.id, args.reason, by=args.by,
                               commit=args.commit, date=args.date))
        elif command == "relabel":
            print(relabel_entry(slice_dir, args.id, args.by, _stdin_or(args.note),
                                kind=args.kind,
                                labels=normalise_for(_labels_from(args), slice_dir),
                                date=args.date))
        elif command == "propose":
            print(propose_entry(slice_dir, args.id, args.by, _stdin_or(args.text),
                                date=args.date))
        elif command == "request-card":
            print(request_card(slice_dir, args.id, args.by, _stdin_or(args.text),
                               date=args.date))
        elif command == "leave":
            print(leave_entry(slice_dir, args.id, args.by, _stdin_or(args.text),
                              date=args.date))
        elif command == "worklist":
            print(worklist_view(slice_dir))
        elif command == "show":
            print(show_view(slice_dir, args.ids))
        elif command == "rule":
            print(_rule_cli(slice_dir, args))
        elif command == "close":
            n, stay = close_report(slice_dir, args.words, date=args.date)
            if stay:
                print(f"{_plural(n, 'entry', 'entries')} closed; the report stays "
                      f"open over {', '.join(stay)}, ruled and not executed")
            else:
                print(f"closed, {_plural(n, 'entry', 'entries')} with it")
        elif command == "render":
            print(render_report(slice_dir))
        elif command == "stamp":
            print(stamp_header(slice_dir))
        elif command == "counts":
            print(counts_line(entry_counts(slice_dir)))
        elif command == "import":
            n = import_report(slice_dir)
            print(f"imported {_plural(n, 'entry', 'entries')} into "
                  f"{store_path(slice_dir)}")
    except ReportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
