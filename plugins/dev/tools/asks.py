#!/usr/bin/env python3
"""The asks a stage puts to the operator or to Pilot — one store, its render, its read-back.

Every ask a program acts on is data (${CLAUDE_PLUGIN_ROOT}/docs/pilot.md § The
documents). The agent that judges writes entries into a store,
`<slice>/asks/<n>-<slug>.json`; this tool renders the store to the document
beside it, `<n>-<slug>.md`, in the grammar of the `document-format` skill,
and the stage registers that document with Pilot. Once Pilot has written the
answers back into the document, `absorb` reads its answer lines into the
store, where the continuation finds each entry's ruling. Nobody writes a
block by hand, and nobody edits either file by hand. Stdlib only; importable
by the loops and by close_out.py, and a CLI for the skills and the
sub-agents:

  init     create `asks/<n>-<slug>.json` under a slice folder, numbered after
           every file already there, with its opening's typed fields; prints
           its path.
  append   add one ask; refused, naming each fault, when the entry does not
           carry what its kind does. Prints its id: the kind's letter and the
           next number under it (D, Q, A), unless --id names one.
  amend    replace an ask's fields, or with no id the document's own;
           --clear removes an optional one. The id and the kind never change.
  note     add a paragraph to an ask, with who wrote it and the date.
  list     one line per ask: its id, kind, headline and state.
  show     asks in full, as the document shows them, with any answer lines.
  render   write the document beside the store and print its path; refused
           while the store holds what Pilot would refuse, and over a
           document that already carries answers.
  absorb   read a written-back document's answer lines into its store and
           print each ask's state.

**The store.** `{title, summary?, step?, for?, context: [paragraph],
premises?: [{premise, fact, changes}], out_of_scope?: [line], size?: {phases,
repos: [name], tests?}, entries: [entry]}`, an entry `{id, kind, headline,
body, options?: [{label, line?}], recommend?, proposal?, default?, check?,
due?, notes?: [{by, date, text}], answer_lines?}`. The kind is the block's:
a `decision` carries `options` (with an optional `recommend`) or a
`proposal`, and may carry `check`; a `question` may carry `default`; an
`action` may carry `options` and `check`, and `due` (merge, test, push or
close), which the store keeps for the driver and the document never shows,
since no block takes it. A body, a context
paragraph and a note are Markdown, with no heading and no block in them.
The opening's typed fields are lines: each premise that does not hold, what
it holds, what is true and what that changes; each matter the work leaves
out; the size, the phases it comes to, the repositories it touches and the
existing tests it changes. A loop's context is its own paragraphs; an
author's is one line, what those fields do not say.

**The render.** The front matter (`title`; `summary` on a document of more
than one ask, where it is required; `step`; `for`), the context, the
opening built from its typed fields — the premises that do not hold, the
size, what is left out, each under a run-in head, a list where there are
several — then per entry `## <headline>`, the body, the notes as paragraphs
with a run-in head, and the block last, its keys in the format skill's
order. The headline, the body, the context and the notes are written as
given but for every `<` outside code and autolinks, escaped `\\<` (`escape_tags`), so that a viewer
that passes HTML through shows the words instead of a tag; the front matter
and the block's values, plain text in Pilot, are written as they are. A value
is written plain where YAML reads it back as written, double-quoted with
escapes where it would not, and as a literal block over several lines.
Refused, with every fault named: a document with no ask; two asks with one
id; a key the kind does not take; `recommend` naming no option; `options`
beside `proposal`; two options with one label; a heading or a block in the
prose, or a fence it leaves open; a first heading that repeats the title,
which Pilot would read as the title's own and so leave the ask without its
section.

**The read-back.** `absorb` finds each block by its fence's info string, as
Pilot's reader does, and reads the answer lines (`answer`, `by`, `at`,
`note`, `via`, `to`, `done`) with a parser of the subset the record writes:
`key: value` scalars, plain or quoted, and a literal block. Nothing else of
the document is read. The lines stand in the entry as `answer_lines`, read
as written, a value trimmed and an empty one absent; a block with none drops
them, so an Undo reads back as an open ask. A document whose blocks are not
the store's asks, by id and kind, is refused. The grammar whole is PilotApp's
`docs/block-dsl.md`.

**An author's text.** `init`, `append`, `amend` and `note` also refuse a
line cited by its number outside a fenced block, `path:12` or `path:12-30`
(`citation_problems`; the rule is `docs/spec-tree.md` § Citing a line).
`append` and `amend` refuse a `--proposal` of more than one line or longer
than `PROPOSAL_MAX` (`proposal_problems`): in Pilot a proposal is the label
of the decision's one Agree row, and the line the closed block shows as the
answer. `init` and `amend` refuse a context of more than one line, and a line
of the opening longer than `OPENING_MAX` (`opening_problems`): the evidence
is `grounding.md`'s, and a pick the operator could rule the other way is an
ask, never a sentence of the opening. The functions the loops import check
none of these: a driver's text quotes tool output.

`<store>` is the store's path or its document's: a `.md` argument resolves
to the `.json` beside it. Every read-modify-write holds an exclusive flock on
the store's folder; a filesystem that refuses it gets the write without it.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

KINDS = ("decision", "question", "action")
LETTERS = {"decision": "D", "question": "Q", "action": "A"}
_ARTICLE = {"decision": "a", "question": "a", "action": "an"}

# What each kind's block takes, of the keys a stage writes; `type` and
# `because` are Pilot's own confirmation and never a stage's.
TAKES = {
    "decision": ("options", "recommend", "proposal", "check"),
    "question": ("default",),
    "action": ("options", "check"),
}
# The keys in the order the format skill's table lists them.
BLOCK_KEYS = ("options", "recommend", "proposal", "default", "check")
DUES = ("merge", "test", "push", "close")
# How long a proposal an author's CLI takes may be (`proposal_problems`): in
# Pilot a proposal is the label of the decision's one Agree row, and the line
# its closed block shows as the answer.
PROPOSAL_MAX = 300
# The opening an author gives in typed fields, in place of free paragraphs of
# context: the premises that do not hold, what the work leaves out, its size.
# The render builds the paragraphs before the first ask from them.
OPENING_FIELDS = ("premises", "out_of_scope", "size")
PREMISE_PARTS = ("premise", "fact", "changes")
SIZE_FIELDS = ("phases", "repos", "tests")
# How long a line of the opening, the context's one line among them, an
# author's CLI takes (`opening_problems`).
OPENING_MAX = 300
ANSWER_KEYS = ("answer", "by", "at", "note", "via", "to", "done")
VIAS = ("app", "chat", "recommended", "autopilot")
DEFERRED = "deferred"
CLAIM = "Pilot does it"
AGENT = "agent"

ENTRY_FIELDS = ("id", "kind", "headline", "body", *BLOCK_KEYS, "due", "notes",
                "answer_lines")
FRAME_FIELDS = ("title", "summary", "step", "for", "context", *OPENING_FIELDS)
STORE_FIELDS = (*FRAME_FIELDS, "entries")

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NUMBERED = re.compile(r"(\d+)-")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Pilot's reader (PilotApp `docs/block-dsl.md`), as far as the render and
# the read-back need it.
_FENCE = re.compile(r"(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>.*)")
_HEADING = re.compile(
    r" {0,3}(?P<marks>#{1,6})(?:[ \t]+(?P<text>.*?))?(?:[ \t]+#+)?[ \t]*"
)
_LOCAL_ID = re.compile(r"id\s*=\s*(?P<id>\S+)")
_CARRIES_ID = re.compile(r"(?:^|\s)id\s*=")
_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_KEY_LINE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(?P<rest>.*?))?[ \t]*")
_BREAKS = "\n\r\x85\u2028\u2029"
_UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")
_NON_PRINTABLE = re.compile(
    "[^\x09\x0a\x0d\x20-\x7e\x85\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)

# A line cited by its number (`citation_problems`): a path-like token, then
# `:<digits>` and an optional range, not inside a URL and not followed by a
# path. `_cites_a_file` decides whether the token is a file.
_LINE_CITATION = re.compile(
    r"(?<![\w/.:~-])(?P<path>(?:[\w.~-]+/)*[\w.-]*[\w-]):\d+(?:[-\u2013]\d+)?(?![\w/])"
)
_EXTENSION = re.compile(r"\.([A-Za-z][A-Za-z0-9]{0,5})$")
_EXTENSIONLESS = frozenset((
    "Makefile", "Dockerfile", "Containerfile", "Jenkinsfile", "Procfile", "Justfile",
    "Vagrantfile", "Gemfile", "Rakefile", "Caddyfile", "Tiltfile",
))
_HOST_SUFFIXES = frozenset((
    "com", "org", "net", "nl", "io", "home", "local", "lan", "internal", "svc", "cluster",
))


class AskError(Exception):
    """A store, an entry or a document the tool refuses; the message names
    every fault."""


def _refuse(what: str, found: list[str]) -> None:
    if found:
        raise AskError(what + ":\n" + "\n".join(f"- {f}" for f in found))


# ---------------------------------------------------------------- paths

def store_of(path: Path | str) -> Path:
    """The store a path names: a `.json` itself, a `.md` the store beside it."""
    p = Path(path)
    if p.suffix == ".json":
        return p
    if p.suffix == ".md":
        return p.with_suffix(".json")
    raise AskError(f"{p} is neither a store (.json) nor its document (.md)")


def document_of(path: Path | str) -> Path:
    return store_of(path).with_suffix(".md")


def next_path(slice_dir: Path | str, slug: str) -> Path:
    """`<slice>/asks/<n>-<slug>.json`, `n` one past every numbered file in
    `asks/`, so the documents are numbered in the order written over the
    slice's life."""
    if not SLUG.fullmatch(slug):
        raise AskError(f"the slug `{slug}` is not lower-case words joined by hyphens")
    folder = Path(slice_dir) / "asks"
    taken = [int(m[1]) for f in (folder.iterdir() if folder.is_dir() else ())
             if (m := _NUMBERED.match(f.name))]
    return folder / f"{max(taken, default=0) + 1}-{slug}.json"


# ---------------------------------------------------------------- store I/O

@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    """An exclusive flock on the stores' folder for one read-modify-write; a
    filesystem that cannot lock gets the write without it."""
    fd = None
    try:
        fd = os.open(folder, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        if fd is not None:
            os.close(fd)
            fd = None
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load(path: Path | str) -> dict:
    path = store_of(path)
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AskError(f"{path} does not exist — `asks.py init` creates it") from None
    except (OSError, json.JSONDecodeError) as e:
        raise AskError(f"{path} cannot be read: {e}") from None
    if not isinstance(store, dict) or not isinstance(store.get("entries"), list):
        raise AskError(f"{path} is not an asks store")
    return store


def save(path: Path | str, store: dict) -> None:
    _write_atomic(store_of(path),
                  json.dumps(store, indent=2, ensure_ascii=False) + "\n")


@contextlib.contextmanager
def editing(path: Path | str) -> Iterator[dict]:
    """The store, locked for one read-modify-write; saved when the block
    ends without an exception."""
    path = store_of(path)
    with _locked(path.parent):
        store = load(path)
        yield store
        save(path, store)


# ---------------------------------------------------------------- checks

def _text_problems(value, what: str, *, one_line: bool) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return [f"{what} is empty"]
    found = []
    if one_line and any(c in value.strip() for c in _BREAKS):
        found.append(f"{what} is more than one line")
    if _UNSTORABLE.search(value):
        found.append(f"{what} holds a NUL or a lone surrogate, which no record holds")
    return found


def _closing(lines: list[str], opening: int, marker: str) -> int | None:
    closing = re.compile(rf" {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*")
    return next((i for i in range(opening + 1, len(lines)) if closing.fullmatch(lines[i])),
                None)


def _opening(line: str) -> re.Match | None:
    """A fence's opening line as Pilot reads one: a backtick fence whose info
    string holds a backtick is none."""
    m = _FENCE.fullmatch(line)
    if m is None or (m["marker"][0] == "`" and "`" in m["info"]):
        return None
    return m


def _is_heading(line: str) -> bool:
    m = _HEADING.fullmatch(line)
    return m is not None and bool(m["text"] and m["text"].strip())


def _markdown_problems(text: str, what: str) -> list[str]:
    """What prose would do to the document around it: a heading would end
    the ask's section, a block would be a second ask, a fence left open would
    swallow the block."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    found: list[str] = []
    i = 0
    while i < len(lines):
        m = _opening(lines[i])
        if m is not None:
            info = m["info"].strip()
            word = info.split(maxsplit=1)[0] if info else ""
            if word.lower() in KINDS or _CARRIES_ID.search(info):
                found.append(f"{what} holds a block (`{lines[i].strip()}`): an ask's "
                             "block is the store's to render")
            close = _closing(lines, i, m["marker"])
            if close is None:
                found.append(f"{what} opens a fence it does not close "
                             f"(`{lines[i].strip()}`), which would swallow the block")
                break
            i = close + 1
            continue
        if _is_heading(lines[i]):
            found.append(f"{what} holds a heading (`{lines[i].strip()}`): an ask's "
                         "sub-structure is run-in heads (`**Cost.** …`) and lists")
        i += 1
    return found


def _outside_fences(text: str) -> Iterator[str]:
    """The lines of `text` outside its fenced blocks; an unclosed fence
    holds the rest."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    i = 0
    while i < len(lines):
        m = _opening(lines[i])
        if m is not None:
            close = _closing(lines, i, m["marker"])
            if close is None:
                return
            i = close + 1
            continue
        yield lines[i]
        i += 1


def _cites_a_file(path: str) -> bool:
    """Whether what stands before `:<digits>` is a file: a path with a `/`,
    a name with an extension, or a build file with none — never a host and
    its port, a clock time or a ratio."""
    name = path.rsplit("/", 1)[-1]
    if "/" in path or name.split(".", 1)[0] in _EXTENSIONLESS:
        return True
    m = _EXTENSION.search(name)
    return m is not None and m[1].lower() not in _HOST_SUFFIXES


def citation_problems(text, what: str) -> list[str]:
    """A line cited by its number in an author's text, outside a fenced
    block: `path:12`, `path:12-30`. The number has moved by the time another
    session reads the text; the rule is the plugin's `docs/spec-tree.md`
    § Citing a line. The CLIs that take an author's text refuse one —
    this tool's and `close_out.py`'s — and a driver's own text, which
    quotes tool output, is never checked."""
    if not isinstance(text, str):
        return []
    found: list[str] = []
    for line in _outside_fences(text):
        for m in _LINE_CITATION.finditer(line):
            if _cites_a_file(m["path"]):
                found.append(
                    f"{what} cites a line by its number (`{m[0]}`), which will have moved "
                    f"when the next session reads it: cite `{m['path']}` and quote the line "
                    "itself (docs/spec-tree.md § Citing a line); a command's output goes in "
                    "a fenced block, which this check passes")
    return found


def proposal_problems(text, what: str) -> list[str]:
    """A proposal an author's CLI refuses: more than one line, or longer
    than `PROPOSAL_MAX`. It says what Agree does, in a ruling's words; what
    it rests on is the ask's body. This tool's CLI and `close_out.py`'s
    check it; a driver's own text is never checked."""
    if not isinstance(text, str):
        return []
    said = text.strip()
    if "\n" in said:
        return [f"{what} is one line: what Agree does, in a ruling's words — what it "
                "rests on goes into the body"]
    if len(said) > PROPOSAL_MAX:
        return [f"{what} is {len(said)} characters, and a proposal is a line of at most "
                f"{PROPOSAL_MAX}: what Agree does, in a ruling's words — what it rests "
                "on goes into the body"]
    return []


def opening_problems(context, premises, out_of_scope, tests) -> list[str]:
    """What an author's CLI refuses of a document's opening: a context of
    more than one line, and any line of it longer than `OPENING_MAX`. The
    opening is the typed fields; the context is the one line they do not
    say, and the evidence is `grounding.md`'s. A field not given is not
    checked; a driver's own text is never checked."""
    found: list[str] = []
    context = context or []
    said = [c.strip() for c in context if isinstance(c, str)]
    if len(context) > 1 or any(c in s for s in said for c in _BREAKS):
        found.append("the context is one line: what the opening's fields — the premises, "
                     "what is left out, the size — do not say; the evidence is "
                     "grounding.md's, never the document's")
    lines = [("the context", s) for s in said]
    for n, parts in enumerate(premises or (), 1):
        lines += [(f"premise {n}'s {part}", value.strip())
                  for part, value in zip(PREMISE_PARTS, parts, strict=False)]
    lines += [(f"out-of-scope line {n}", v.strip()) for n, v in enumerate(out_of_scope or (), 1)]
    if isinstance(tests, str):
        lines.append(("the size's tests", tests.strip()))
    found += [f"{what} is {len(value)} characters, and a line of the opening is at most "
              f"{OPENING_MAX}: a sentence, its evidence left to grounding.md"
              for what, value in lines if len(value) > OPENING_MAX]
    return found


def _options_problems(options, who: str) -> list[str]:
    if not isinstance(options, list) or not options:
        return [f"{who}: `options` is no list of options"]
    found: list[str] = []
    seen: set[str] = set()
    for opt in options:
        if not isinstance(opt, dict) or set(opt) - {"label", "line"}:
            found.append(f"{who}: an option is no {{label, line}}")
            continue
        label = opt.get("label")
        found += _text_problems(label, f"{who}: an option's label", one_line=True)
        if "line" in opt:
            found += _text_problems(opt["line"], f"{who}: the line of option `{label}`",
                                    one_line=True)
        if isinstance(label, str):
            if label.strip() in seen:
                found.append(f"{who}: two options with the label `{label.strip()}`")
            seen.add(label.strip())
    return found


def entry_problems(entry) -> list[str]:
    """Every fault of one ask on its own; the document's faults are
    `problems()`'s."""
    if not isinstance(entry, dict):
        return ["an ask is no mapping"]
    eid, kind = entry.get("id"), entry.get("kind")
    who = f"ask {eid}" if isinstance(eid, str) and eid else "the ask"
    found: list[str] = []
    unknown = [k for k in entry if k not in ENTRY_FIELDS]
    if unknown:
        found.append(f"{who}: no field {', '.join(f'`{k}`' for k in unknown)}")
    if not isinstance(eid, str) or not ID.fullmatch(eid):
        found.append(f"{who}: the id `{eid}` is not letters, digits, `.`, `_` and `-`")
    if kind not in KINDS:
        found.append(f"{who}: the kind `{kind}` is not decision, question or action")
        return found
    headline = entry.get("headline")
    found += _text_problems(headline, f"{who}: the headline", one_line=True)
    if isinstance(headline, str) and re.search(r"[ \t]#+[ \t]*$", headline):
        found.append(f"{who}: the headline ends in `#`, which Pilot reads as the "
                     "heading's closing marks")
    body = entry.get("body")
    found += _text_problems(body, f"{who}: the body", one_line=False)
    if isinstance(body, str):
        found += _markdown_problems(body, f"{who}: the body")
    for key in BLOCK_KEYS:
        if key in entry and key not in TAKES[kind]:
            found.append(f"{who}: {_ARTICLE[kind]} {kind} takes no `{key}`")
    if "due" in entry:
        if kind != "action":
            found.append(f"{who}: {_ARTICLE[kind]} {kind} takes no `due`")
        elif entry["due"] not in DUES:
            found.append(f"{who}: `due` is one of {', '.join(DUES)}, not `{entry['due']}`")
    if "options" in entry:
        found += _options_problems(entry["options"], who)
    if "recommend" in entry:
        labels = [o.get("label", "").strip() for o in entry.get("options") or ()
                  if isinstance(o, dict) and isinstance(o.get("label"), str)]
        if "options" not in entry:
            found.append(f"{who}: `recommend` with no options")
        elif not isinstance(entry["recommend"], str) or \
                entry["recommend"].strip() not in labels:
            found.append(f"{who}: `recommend: {entry['recommend']}` names no option")
    if "proposal" in entry and ("options" in entry or "recommend" in entry):
        found.append(f"{who}: `options` or `recommend` beside `proposal`")
    if kind == "decision" and "options" not in entry and "proposal" not in entry:
        found.append(f"{who}: a decision carries `options` or a `proposal`")
    for key in ("proposal", "default", "check"):
        if key in entry:
            found += _text_problems(entry[key], f"{who}: `{key}`", one_line=False)
    for note in entry.get("notes") or ():
        if not isinstance(note, dict) or set(note) != {"by", "date", "text"}:
            found.append(f"{who}: a note is no {{by, date, text}}")
            continue
        found += _text_problems(note["by"], f"{who}: a note's author", one_line=True)
        if not isinstance(note["date"], str) or not _DATE.fullmatch(note["date"]):
            found.append(f"{who}: a note's date `{note['date']}` is no YYYY-MM-DD")
        found += _text_problems(note["text"], f"{who}: a note", one_line=False)
        if isinstance(note["text"], str):
            found += _markdown_problems(note["text"], f"{who}: a note")
    lines = entry.get("answer_lines")
    if lines is not None and (not isinstance(lines, dict) or set(lines) - set(ANSWER_KEYS)
                              or not all(isinstance(v, str) for v in lines.values())):
        found.append(f"{who}: `answer_lines` is no mapping of answer lines")
    return found


def _frame_problems(store: dict) -> list[str]:
    found: list[str] = []
    unknown = [k for k in store if k not in STORE_FIELDS]
    if unknown:
        found.append(f"the store has no field {', '.join(f'`{k}`' for k in unknown)}")
    found += _text_problems(store.get("title"), "the title", one_line=True)
    for key in ("summary", "step", "for"):
        if key in store:
            found += _text_problems(store[key], f"`{key}`", one_line=True)
    context = store.get("context", [])
    if not isinstance(context, list):
        found.append("the context is no list of paragraphs")
    else:
        for n, paragraph in enumerate(context, 1):
            found += _text_problems(paragraph, f"context paragraph {n}", one_line=False)
            if isinstance(paragraph, str):
                found += _markdown_problems(paragraph, f"context paragraph {n}")
    return found + _opening_problems(store)


def _opening_problems(store: dict) -> list[str]:
    """The typed opening's shape: each premise its three parts, what is left
    out a list of lines, the size its phases, its repositories and the tests
    it changes where given — every value a line."""
    found: list[str] = []
    if "premises" in store:
        premises = store["premises"]
        if not isinstance(premises, list) or not premises:
            found.append("`premises` is no list of premises")
        else:
            for n, premise in enumerate(premises, 1):
                what = f"premise {n}"
                if not isinstance(premise, dict) or set(premise) != set(PREMISE_PARTS):
                    found.append(f"{what} is not its {', '.join(PREMISE_PARTS)}")
                    continue
                for part in PREMISE_PARTS:
                    found += _text_problems(premise[part], f"{what}'s {part}", one_line=True)
    if "out_of_scope" in store:
        left = store["out_of_scope"]
        if not isinstance(left, list) or not left:
            found.append("`out_of_scope` is no list of lines")
        else:
            for n, line in enumerate(left, 1):
                found += _text_problems(line, f"out-of-scope line {n}", one_line=True)
    if "size" in store:
        size = store["size"]
        if not isinstance(size, dict):
            return [*found, "`size` is not its phases, repos and tests"]
        unknown = set(size) - set(SIZE_FIELDS)
        if unknown:
            found.append(f"the size has no field {', '.join(f'`{k}`' for k in sorted(unknown))}")
        phases = size.get("phases")
        if isinstance(phases, bool) or not isinstance(phases, int) or phases < 1:
            found.append("the size's `phases` is no count of one or more")
        repos = size.get("repos")
        if not isinstance(repos, list) or not repos:
            found.append("the size names no repository")
        else:
            for n, repo in enumerate(repos, 1):
                found += _text_problems(repo, f"the size's repository {n}", one_line=True)
        if "tests" in size:
            found += _text_problems(size["tests"], "the size's tests", one_line=True)
    return found


def problems(store: dict) -> list[str]:
    """Every fault that keeps the store from rendering: the document's, then
    each ask's."""
    found = _frame_problems(store)
    entries = store.get("entries")
    if not isinstance(entries, list) or not entries:
        return [*found, "no ask: a stage with nothing to ask renders no document"]
    seen: set[str] = set()
    for entry in entries:
        found += entry_problems(entry)
        eid = entry.get("id") if isinstance(entry, dict) else None
        if eid in seen:
            found.append(f"two asks with the id {eid}")
        seen.add(eid)
    if len(entries) > 1 and "summary" not in store:
        found.append("a document of more than one ask has a `summary`: what it is "
                     "about, in one line")
    first = entries[0].get("headline") if isinstance(entries[0], dict) else None
    title = store.get("title")
    if isinstance(first, str) and isinstance(title, str) and first.strip() == title.strip():
        found.append(f"the first ask's headline repeats the title, so Pilot reads its "
                     f"heading as the title's own and the ask loses its section: "
                     f"`{title.strip()}`")
    return found


# ---------------------------------------------------------------- YAML out

def _plain(value: str) -> bool:
    """Whether YAML, with no implicit typing, reads `value` written plain
    back as written."""
    if not value or value != value.strip() or _NON_PRINTABLE.search(value):
        return False
    if any(c in value for c in "\t\ufeff" + _BREAKS):
        return False
    if value[0] in "#&*!|>'\"%@`[]{},":
        return False
    if value[0] in "-?:" and (len(value) == 1 or value[1] == " "):
        return False
    if value.startswith(("---", "...")):
        return False
    return ": " not in value and " #" not in value and not value.endswith(":")


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t",
            "\x85": "\\x85", "\u2028": "\\u2028", "\u2029": "\\u2029",
            "\ufeff": "\\ufeff"}


def _quoted(value: str) -> str:
    out = []
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif _NON_PRINTABLE.match(ch):
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def scalar(value: str) -> str:
    """`value`, trimmed, as one line of YAML that reads back as written:
    plain where YAML allows, else double-quoted with escapes."""
    value = value.strip()
    return value if _plain(value) else _quoted(value)


def _literal(value: str) -> bool:
    """Whether a value of several lines goes as a literal block: none of its
    lines ends in a blank, which the block would keep only by accident, and
    none holds a tab or a character YAML breaks a line at or cannot print,
    which Pilot's own writer double-quotes."""
    return ("\n" in value and not any(c in value for c in "\t\ufeff" + _BREAKS[1:])
            and not _NON_PRINTABLE.search(value)
            and not any(line != line.rstrip() for line in value.split("\n")))


def key_value(key: str, value: str) -> list[str]:
    """`key: value` as block YAML: a literal block over several lines, its
    lines four spaces in, past the three a closing fence may have."""
    value = value.strip()
    if _literal(value):
        return [f"{key}: |"] + [f"    {line}" if line else "" for line in value.split("\n")]
    return [f"{key}: {scalar(value)}"]


# ---------------------------------------------------------------- render

# What `escape_tags` stops at in a paragraph: a backslash escape (`\` and an
# ASCII punctuation character), a backtick run, a `<`.
_INLINE = re.compile(r"\\[!-/:-@\[-`{-~]|`+|<")
_BACKTICKS = re.compile(r"`+")
# CommonMark's autolinks: `<scheme:…>` and `<address@host>`.
_AUTOLINK = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\x00-\x20\x7f<>]*"
    r"|[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*)>"
)


def _escape_inline(text: str) -> str:
    """One paragraph's `<`s escaped, its code spans, autolinks and backslash
    escapes as written: whichever starts first holds, as CommonMark reads
    them, and a backtick run with no run of its length after it is text."""
    out: list[str] = []
    pos = 0
    while (m := _INLINE.search(text, pos)) is not None:
        out.append(text[pos:m.start()])
        token = m.group(0)
        if token == "<":
            link = _AUTOLINK.match(text, m.start())
            end = m.end() if link is None else link.end()
            out.append("\\<" if link is None else link.group(0))
        elif token[0] == "`":
            close = next((c for c in _BACKTICKS.finditer(text, m.end())
                          if len(c.group(0)) == len(token)), None)
            end = m.end() if close is None else close.end()
            out.append(text[m.start():end])
        else:
            end = m.end()
            out.append(token)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def escape_tags(text: str) -> str:
    """An author's Markdown with every `<` escaped (`\\<`), so that a viewer
    that passes HTML through, as VSCode's and GitHub's do, shows the words
    and does not swallow them as a tag; Pilot draws a `<` as text either way,
    and `\\<` as `<`. Left as written: a fenced block, found as Pilot's reader
    finds one, an unclosed fence holding the rest; a code span, read as
    CommonMark reads one within a paragraph, over its line breaks; an
    autolink; and a backslash escape, so that `\\<` stays one and a second
    pass changes nothing. An indented code block is not told from prose: a
    `<` in one is escaped too. Nothing but a `<` is ever escaped."""
    lines = text.split("\n")
    bare = [line.removesuffix("\r") for line in lines]
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.extend(_escape_inline("\n".join(paragraph)).split("\n"))
            paragraph.clear()

    i = 0
    while i < len(lines):
        m = _opening(bare[i])
        if m is not None:
            flush()
            close = _closing(bare, i, m["marker"])
            end = len(lines) if close is None else close + 1
            out.extend(lines[i:end])
            i = end
            continue
        if bare[i].strip():
            paragraph.append(lines[i])
        else:
            flush()
            out.append(lines[i])
        i += 1
    flush()
    return "\n".join(out)


def _paragraph(text: str) -> list[str]:
    return [*text.strip("\n").rstrip().split("\n"), ""]


def _block(entry: dict, *, answers: bool = False) -> list[str]:
    lines = [f"```{entry['kind']} id={entry['id']}"]
    for key in BLOCK_KEYS:
        if key not in entry:
            continue
        if key == "options":
            lines.append("options:")
            for opt in entry["options"]:
                label, line = opt["label"].strip(), (opt.get("line") or "").strip()
                item = f"{scalar(label)}: {scalar(line)}" if line else scalar(label)
                lines.append(f"  - {item}")
        else:
            lines += key_value(key, entry[key])
    if answers:
        for key, value in (entry.get("answer_lines") or {}).items():
            lines += key_value(key, value)
    return [*lines, "```"]


def section(entry: dict, *, answers: bool = False) -> list[str]:
    """One ask as the document shows it: its heading, its body, its notes,
    its block last; with `answers`, the answer lines read back. The heading,
    the body and the notes are Markdown and escaped (`escape_tags`); the
    block's values are plain text in Pilot and written as they are."""
    lines = [f"## {escape_tags(entry['headline'].strip())}", "",
             *_paragraph(escape_tags(entry["body"]))]
    for note in entry.get("notes") or ():
        lines += _paragraph(escape_tags(f"**{note['by'].strip()}, {note['date']}.** "
                                        f"{note['text'].strip()}"))
    return [*lines, *_block(entry, answers=answers), ""]


def _and(items: list[str]) -> str:
    items = [i.strip() for i in items]
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _run_in(head: str, heads: str, items: list[str]) -> list[str]:
    """One item as a paragraph under its run-in head, several as a list
    under the plural head."""
    if len(items) == 1:
        return _paragraph(escape_tags(f"**{head}.** {items[0]}"))
    return [f"**{heads}.**", "", *(f"- {escape_tags(i)}" for i in items), ""]


def _opening_lines(store: dict) -> list[str]:
    """The opening built from the typed fields, before the first ask: the
    premises that do not hold, each its premise, its fact and what it
    changes; the size; what the work leaves out."""
    lines: list[str] = []
    premises = [" ".join(p[part].strip() for part in PREMISE_PARTS)
                for p in store.get("premises") or ()]
    if premises:
        lines += _run_in("A premise that does not hold", "Premises that do not hold",
                         premises)
    size = store.get("size")
    if size:
        n = size["phases"]
        said = f"**The size.** About {n} phase{'' if n == 1 else 's'}, over {_and(size['repos'])}."
        if size.get("tests"):
            said += f" {size['tests'].strip()}"
        lines += _paragraph(escape_tags(said))
    left = [line.strip() for line in store.get("out_of_scope") or ()]
    if left:
        lines += _run_in("Left out of this slice", "Left out of this slice", left)
    return lines


def render(store: dict) -> str:
    """The document's text; AskError naming every fault while there are any."""
    _refuse("the document cannot be rendered", problems(store))
    entries = store["entries"]
    lines = ["---", f"title: {scalar(store['title'])}"]
    if len(entries) > 1:
        lines.append(f"summary: {scalar(store['summary'])}")
    for key in ("step", "for"):
        if key in store:
            lines.append(f"{key}: {scalar(store[key])}")
    lines += ["---", ""]
    for paragraph in store.get("context", []):
        lines += _paragraph(escape_tags(paragraph))
    lines += _opening_lines(store)
    for entry in entries:
        lines += section(entry)
    return "\n".join(lines).rstrip("\n") + "\n"


def render_file(path: Path | str) -> Path:
    """Write the document beside the store. A document already there that
    carries answers is Pilot's write-back and is never rendered over."""
    spath = store_of(path)
    doc = document_of(spath)
    with _locked(spath.parent):
        text = render(load(spath))
        if doc.exists():
            try:
                old = read_back(doc.read_text(encoding="utf-8"))
            except AskError as e:
                raise AskError(f"{doc} is there and cannot be read ({e}); move it aside "
                               "if no one has answered it") from None
            answered = [bid for bid, block in old.items() if block["lines"]]
            if answered:
                raise AskError(f"{doc} carries answers ({', '.join(answered)}): Pilot "
                               "wrote it back, so it is never rendered over. Absorb it; "
                               "a revised ask goes into a new document (`init`)")
        _write_atomic(doc, text)
    return doc


# ---------------------------------------------------------------- read-back

_DQ = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
       "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
       "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029"}
_DQ_HEX = {"x": 2, "u": 4, "U": 8}


def _fold(text: str, i: int, out: list[tuple[str, bool]]) -> int:
    """A line break inside a quoted value, at `text[i]`: the blanks before it
    dropped, the next lines' leading blanks dropped, one break read as a
    space and each empty line after it as a newline. Returns the index after."""
    while out and out[-1][0] in " \t" and not out[-1][1]:
        out.pop()
    i += 1
    breaks = 0
    while True:
        j = i
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == "\n":
            breaks += 1
            i = j + 1
            continue
        out.append(("\n" * breaks if breaks else " ", True))
        return j


def _after_quote(text: str, i: int, where: str) -> None:
    rest = text[i:].split("\n")
    if rest[0].strip() and not re.fullmatch(r"[ \t]+#.*", rest[0]):
        raise AskError(f"{where}: `{rest[0].strip()}` after the closing quote")
    if any(line.strip() and not line.strip().startswith("#") for line in rest[1:]):
        raise AskError(f"{where}: more after the quoted value")


def _double_quoted(text: str, where: str) -> str:
    out: list[tuple[str, bool]] = []
    i = 1
    while True:
        if i >= len(text):
            raise AskError(f"{where}: the double-quoted value is not closed")
        ch = text[i]
        if ch == '"':
            break
        if ch == "\n":
            i = _fold(text, i, out)
            continue
        if ch != "\\":
            out.append((ch, False))
            i += 1
            continue
        esc = text[i + 1] if i + 1 < len(text) else ""
        if esc == "\n":     # an escaped line break joins the lines with nothing
            i += 2
            while i < len(text) and text[i] in " \t":
                i += 1
        elif esc in _DQ:
            out.append((_DQ[esc], True))
            i += 2
        elif esc in _DQ_HEX:
            digits = text[i + 2:i + 2 + _DQ_HEX[esc]]
            if not re.fullmatch(rf"[0-9A-Fa-f]{{{_DQ_HEX[esc]}}}", digits):
                raise AskError(f"{where}: `\\{esc}{digits}` is no escape")
            out.append((chr(int(digits, 16)), True))
            i += 2 + _DQ_HEX[esc]
        else:
            raise AskError(f"{where}: `\\{esc}` is no escape")
    _after_quote(text, i + 1, where)
    return "".join(ch for ch, _ in out)


def _single_quoted(text: str, where: str) -> str:
    out: list[tuple[str, bool]] = []
    i = 1
    while True:
        if i >= len(text):
            raise AskError(f"{where}: the single-quoted value is not closed")
        ch = text[i]
        if ch == "'":
            if text[i + 1:i + 2] == "'":
                out.append(("'", True))
                i += 2
                continue
            break
        if ch == "\n":
            i = _fold(text, i, out)
            continue
        out.append((ch, False))
        i += 1
    _after_quote(text, i + 1, where)
    return "".join(ch for ch, _ in out)


def _plain_part(text: str, where: str) -> str:
    text = re.split(r"[ \t]#", text, maxsplit=1)[0].strip()
    if ": " in text or text.endswith(":"):
        raise AskError(f"{where}: `{text}` holds `: `, which YAML reads as a mapping; "
                       "quote the value")
    return text


def _value(rest: str, more: list[str], base: int, where: str) -> str:
    """One answer line's value, from the rest of its key's line and the lines
    under it: the subset the record writes, a plain or quoted scalar or a
    literal block, read as written."""
    rest = rest.strip()
    if rest.startswith("|"):
        header = re.fullmatch(r"\|(?:([1-9])[-+]?|[-+]([1-9])?)?(?:[ \t]+#.*)?", rest)
        if header is None:
            raise AskError(f"{where}: `{rest}` is no literal block's header")
        given = header[1] or header[2]
        first = next((line for line in more if line.strip()), None)
        if first is None:
            return ""
        indent = base + int(given) if given else len(first) - len(first.lstrip(" "))
        if indent <= base:
            raise AskError(f"{where}: the literal block's lines stand no further in "
                           "than its key")
        lines = []
        for line in more:
            if not line.strip():
                lines.append(line[indent:])
            elif len(line) - len(line.lstrip(" ")) < indent:
                raise AskError(f"{where}: a line of the literal block stands left of "
                               "its first")
            else:
                lines.append(line[indent:])
        return "\n".join(lines).strip()
    if rest.startswith(">"):
        raise AskError(f"{where}: a folded value (`>`) is not read; write a value of "
                       "several lines as a literal block (`|`)")
    text = "\n".join([rest, *more])
    if rest.startswith('"'):
        return _double_quoted(text, where).strip()
    if rest.startswith("'"):
        return _single_quoted(text, where).strip()
    if rest[:1] in ("[", "{"):
        raise AskError(f"{where}: a list or a mapping where one value is wanted")
    if rest[:1] in ("&", "*", "!"):
        raise AskError(f"{where}: an anchor, an alias or a tag is not read; write the "
                       "value plain or quoted")
    if rest[:1] and (rest[0] in ",]}%@`" or (rest[0] in "-?:" and rest[1:2] in ("", " "))):
        raise AskError(f"{where}: `{rest}` cannot be written plain; quote it")
    value = _plain_part(rest, where) if rest and not rest.startswith("#") else ""
    blanks = 0
    for line in more:
        part = line.strip()
        if not part:
            blanks += 1
            continue
        if part.startswith("#"):
            break
        if part == "-" or part.startswith("- "):
            raise AskError(f"{where}: a list where one value is wanted")
        if not value and _KEY_LINE.fullmatch(part):
            raise AskError(f"{where}: a mapping where one value is wanted")
        part = _plain_part(part, where)
        value = value + ("\n" * blanks if blanks else " ") + part if value else part
        blanks = 0
    return value.strip()


def _answer_lines(body: list[str], first: int, bid: str) -> dict[str, str]:
    """The answer lines of one block's body, read as written. `first` is the
    body's first line in the file, for the messages."""
    entries: list[list] = []        # [key, rest, lines under it, line number]
    current: list | None = None
    base: int | None = None
    seen: set[str] = set()
    for n, line in enumerate(body):
        where = f"block {bid}, line {first + n}"
        if not line.strip():
            if current is not None:
                current[2].append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if base is None:
            if line.strip().startswith("#"):
                continue
            base = indent
        stripped = line.strip()
        if indent > base or (indent == base and current is not None
                             and (stripped == "-" or stripped.startswith("- "))):
            if current is None:
                raise AskError(f"{where}: `{stripped}` belongs to no key")
            current[2].append(line)
            continue
        if indent < base:
            raise AskError(f"{where}: `{stripped}` stands left of the block's first key")
        if stripped.startswith("#"):
            current = None
            continue
        m = _KEY_LINE.fullmatch(line[indent:])
        if m is None:
            raise AskError(f"{where}: `{stripped}` is no `key: value` line")
        if m["key"] in seen:
            raise AskError(f"{where}: `{m['key']}` is written twice")
        seen.add(m["key"])
        current = [m["key"], m["rest"] or "", [], first + n]
        entries.append(current)
    found: dict[str, str] = {}
    for key, rest, more, number in entries:
        if key in ANSWER_KEYS:
            where = f"block {bid}, line {number}, `{key}`"
            value = _value(rest, more, base or 0, where)
            if _UNSTORABLE.search(value):
                raise AskError(f"{where}: a NUL or a lone surrogate, which no record holds")
            if value:
                found[key] = value
    where = f"block {bid}"
    if (found.get("answer") == DEFERRED) != ("to" in found):
        raise AskError(f"{where}: `answer: deferred` goes with a `to`, and a `to` with it")
    if "via" in found and found["via"] not in VIAS:
        raise AskError(f"{where}: `via: {found['via']}` is not one of {', '.join(VIAS)}")
    for key in ("at", "done"):
        if key in found and not _TIME.fullmatch(found[key]):
            raise AskError(f"{where}: `{key}: {found[key]}` is no date and time")
    return found


def _body_start(lines: list[str]) -> int:
    """The first line after the front matter, as Pilot reads one: a first
    line `---` and a later `---` closing it."""
    if not lines or lines[0].rstrip() != "---":
        return 0
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    return 0 if close is None else close + 1


def read_back(text: str) -> dict[str, dict]:
    """Every block of a document, in order, by its local id: `{kind, line,
    lines}`, `lines` its answer lines. AskError where Pilot would find a
    fault in a block or a fence, or where an answer line is not in the subset
    the record writes."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    found: dict[str, dict] = {}
    i = _body_start(lines)
    while i < len(lines):
        m = _opening(lines[i])
        if m is None:
            i += 1
            continue
        close = _closing(lines, i, m["marker"])
        if close is None:
            raise AskError(f"line {i + 1}: a fence opened with {m['marker']} is not closed")
        info = m["info"].strip()
        word = info.split(maxsplit=1)[0] if info else ""
        if word in KINDS:
            local = _LOCAL_ID.fullmatch(info[len(word):].strip())
            if local is None:
                raise AskError(f"line {i + 1}: {_ARTICLE[word]} {word} block without "
                               "`id=<id>`")
            bid = local["id"]
            if bid in found:
                raise AskError(f"line {i + 1}: a second block {bid}")
            indent = len(m["indent"])
            body = [line[min(indent, len(line) - len(line.lstrip(" "))):]
                    for line in lines[i + 1:close]]
            found[bid] = {"kind": word, "line": i + 1,
                          "lines": _answer_lines(body, i + 2, bid)}
        elif word.lower() in KINDS or _CARRIES_ID.search(info):
            raise AskError(f"line {i + 1}: `{info}` is a fault to Pilot: a block's kind "
                           "is decision, question or action, in lower case")
        i = close + 1
    return found


def state(entry: dict) -> str:
    """Where an ask stands, from its answer lines: open, answered, deferred,
    claimed or done, and by whom; no `by` is Pilot's, as `by: agent` is."""
    lines = entry.get("answer_lines") or {}
    by = lines.get("by", AGENT)
    if "done" in lines:
        return f"done by {by}"
    answer = lines.get("answer")
    if answer is None:
        return "open"
    if answer == DEFERRED:
        return f"deferred to {lines.get('to')} by {by}"
    if answer == CLAIM and by == AGENT:
        return "claimed by Pilot, not done"
    return f"answered by {by}: {answer}"


def absorb(store: dict, text: str) -> list[str]:
    """Read a written-back document's answer lines into its store: each
    ask's `answer_lines`, dropped from an ask whose block has none. Returns a
    line per ask, its id and state."""
    read = read_back(text)
    entries = store["entries"]
    ids = [e["id"] for e in entries]
    found = [f"ask {i} has no block in the document" for i in ids if i not in read]
    found += [f"block {b} is no ask of the store" for b in read if b not in ids]
    found += [f"ask {e['id']} is {_ARTICLE[e['kind']]} {e['kind']} in the store and "
              f"{_ARTICLE[read[e['id']]['kind']]} {read[e['id']]['kind']} in the document"
              for e in entries if e["id"] in read and read[e["id"]]["kind"] != e["kind"]]
    _refuse("the document is not this store's", found)
    for entry in entries:
        lines = read[entry["id"]]["lines"]
        if lines:
            entry["answer_lines"] = lines
        else:
            entry.pop("answer_lines", None)
    return [f"{e['id']}  {state(e)}" for e in entries]


def absorb_file(path: Path | str) -> list[str]:
    doc = document_of(path)
    try:
        text = doc.read_text(encoding="utf-8")
    except OSError as e:
        raise AskError(f"{doc} cannot be read: {e}") from None
    with editing(doc) as store:
        return absorb(store, text)


# ---------------------------------------------------------------- writes

def new_store(title: str, *, summary: str | None = None, step: str | None = None,
              for_: str | None = None, context: list[str] | tuple = (),
              premises: list[dict] | None = None, out_of_scope: list[str] | None = None,
              size: dict | None = None) -> dict:
    store: dict = {"title": title.strip()}
    for key, value in (("summary", summary), ("step", step), ("for", for_)):
        if value is not None and value.strip():
            store[key] = value.strip()
    store["context"] = list(context)
    for key, value in (("premises", premises), ("out_of_scope", out_of_scope),
                       ("size", size)):
        _set_opening(store, key, value)
    store["entries"] = []
    _refuse("the store cannot be created", _frame_problems(store))
    return store


def create(slice_dir: Path | str, slug: str, title: str, **frame) -> Path:
    """A new store, `asks/<n>-<slug>.json` under the slice folder; its path."""
    store = new_store(title, **frame)
    folder = Path(slice_dir) / "asks"
    folder.mkdir(parents=True, exist_ok=True)
    with _locked(folder):
        path = next_path(slice_dir, slug)
        save(path, store)
    return path


def _options(options) -> list[dict] | None:
    """Options as the store keeps them, from labels, (label, line) pairs or
    {label, line} mappings; an empty line is none."""
    if options is None:
        return None
    out = []
    for opt in options:
        if isinstance(opt, str):
            label, line = opt, None
        elif isinstance(opt, dict):
            label, line = opt.get("label"), opt.get("line")
        else:
            label, line = (list(opt) + [None])[:2]
        item = {"label": label.strip() if isinstance(label, str) else label}
        if isinstance(line, str) and line.strip():
            item["line"] = line.strip()
        out.append(item)
    return out


def next_id(store: dict, kind: str) -> str:
    letter = LETTERS[kind]
    taken = [int(m[1]) for e in store["entries"]
             if (m := re.fullmatch(rf"{letter}(\d+)", e.get("id", "")))]
    return f"{letter}{max(taken, default=0) + 1}"


def _set(entry: dict, key: str, value) -> None:
    """A field given: an empty one removes it, any other replaces it."""
    if value is None:
        return
    if value in ("", []):
        entry.pop(key, None)
    elif key == "options":
        entry[key] = _options(value)
    elif key in ("headline", "recommend", "due"):
        entry[key] = value.strip() if isinstance(value, str) else value
    else:
        entry[key] = value


def append(store: dict, kind: str, headline: str, body: str, *, id: str | None = None,
           **fields) -> str:
    """Add one ask; its id. Refused, naming every fault, when the ask does not
    carry what its kind does. `fields` are the block's keys and `due`."""
    if kind not in KINDS:
        raise AskError(f"the kind `{kind}` is not decision, question or action")
    unknown = set(fields) - set(BLOCK_KEYS) - {"due"}
    if unknown:
        raise AskError(f"no field {', '.join(sorted(unknown))}")
    eid = id or next_id(store, kind)
    if any(e.get("id") == eid for e in store["entries"]):
        raise AskError(f"the store holds an ask {eid} already")
    entry: dict = {"id": eid, "kind": kind}
    _set(entry, "headline", headline)
    _set(entry, "body", body)
    for key in (*BLOCK_KEYS, "due"):
        _set(entry, key, fields.get(key))
    _refuse(f"ask {eid} is refused", entry_problems(entry))
    store["entries"].append(entry)
    return eid


def _find(store: dict, eid: str) -> dict:
    for entry in store["entries"]:
        if entry.get("id") == eid:
            return entry
    raise AskError(f"the store holds no ask {eid}")


def amend(store: dict, eid: str, **fields) -> None:
    """Replace the fields given of one ask; an empty value removes an
    optional one. The id and the kind never change."""
    unknown = set(fields) - {"headline", "body", *BLOCK_KEYS, "due"}
    if unknown:
        raise AskError(f"amend changes no {', '.join(sorted(unknown))}")
    entry = _find(store, eid)
    changed = json.loads(json.dumps(entry))
    for key, value in fields.items():
        _set(changed, key, value)
    _refuse(f"ask {eid} cannot be amended so", entry_problems(changed))
    entry.clear()
    entry.update(changed)


def _set_opening(store: dict, key: str, value) -> None:
    """A typed field of the opening given: an empty one removes it. A size
    given in part keeps the rest of the one there, its repositories replaced
    whole where given."""
    if value is None:
        return

    def strip(v):
        return v.strip() if isinstance(v, str) else v

    if key == "premises" and isinstance(value, list):
        value = [{k: strip(v) for k, v in p.items()} if isinstance(p, dict) else p
                 for p in value]
    elif key == "out_of_scope" and isinstance(value, list):
        value = [strip(v) for v in value]
    elif key == "size" and isinstance(value, dict) and value:
        value = {**(store.get("size") or {}),
                 **{k: v for k, v in value.items() if v is not None}}
        if isinstance(value.get("repos"), list):
            value["repos"] = [strip(r) for r in value["repos"]]
        if isinstance(value.get("tests"), str):
            value["tests"] = value["tests"].strip()
            if not value["tests"]:
                del value["tests"]
    if value in ([], {}):
        store.pop(key, None)
    else:
        store[key] = value


def amend_frame(store: dict, **fields) -> None:
    """Replace the document's own fields given: `title`, `summary`, `step`,
    `for_`, `context`, and the opening's `premises`, `out_of_scope` and
    `size` (in part: its fields given replace the size's); an empty value
    removes an optional one."""
    unknown = (set(fields) - {"title", "summary", "step", "for_", "context"}
               - set(OPENING_FIELDS))
    if unknown:
        raise AskError(f"amend changes no {', '.join(sorted(unknown))}")
    changed = json.loads(json.dumps(store))
    for key, value in fields.items():
        key = "for" if key == "for_" else key
        if value is None:
            continue
        if key in OPENING_FIELDS:
            _set_opening(changed, key, value)
        elif key == "context":
            changed["context"] = list(value)
        elif value.strip():
            changed[key] = value.strip()
        else:
            changed.pop(key, None)
    _refuse("the document cannot be amended so", _frame_problems(changed))
    store.clear()
    store.update(changed)


def note(store: dict, eid: str, by: str, text: str, date: str | None = None) -> None:
    """Add a paragraph to one ask, shown under its body with who wrote it."""
    entry = _find(store, eid)
    changed = json.loads(json.dumps(entry))
    changed.setdefault("notes", []).append(
        {"by": by.strip(), "date": date or dt.date.today().isoformat(), "text": text})
    _refuse(f"ask {eid} cannot take the note", entry_problems(changed))
    entry.clear()
    entry.update(changed)


# ---------------------------------------------------------------- views

def list_view(store: dict) -> str:
    return "\n".join(f"{e['id']}  {e['kind']}  {e['headline']}  [{state(e)}]"
                     for e in store["entries"])


def show_view(store: dict, ids: list[str] | None = None) -> str:
    entries = [_find(store, i) for i in ids] if ids else store["entries"]
    out = []
    for entry in entries:
        due = f", due before the {entry['due']}" if "due" in entry else ""
        out += [f"{entry['id']} — {entry['kind']}, {state(entry)}{due}",
                *section(entry, answers=True)]
    return "\n".join(out).rstrip("\n")


# ---------------------------------------------------------------- CLI

def _frame_args(p: argparse.ArgumentParser, *, title_required: bool) -> None:
    p.add_argument("--title", required=title_required,
                   help="the document's title, one line")
    p.add_argument("--summary", help="what a document of more than one ask is about, "
                                     "one line, no counts")
    p.add_argument("--step", help="the plan task the brief names, as `step`")
    p.add_argument("--for", dest="for_", metavar="HANDLE",
                   help="the handle of the person who should answer")
    p.add_argument("--context", action="append", metavar="LINE",
                   help="the one line the asks share that the opening's fields do not "
                        f"say, at most {OPENING_MAX} characters; - for stdin")
    p.add_argument("--premise", action="append", nargs=3,
                   metavar=("PREMISE", "FACT", "CHANGES"),
                   help="a premise of the slice that does not hold: what it holds, what "
                        "is true, what that changes — a sentence each, no evidence; "
                        "repeat it for each")
    p.add_argument("--out-of-scope", dest="out_of_scope", action="append", metavar="LINE",
                   help="a matter the work found and leaves out, a line; repeat it for each")
    p.add_argument("--phases", type=int, metavar="N",
                   help="the size: the phases the work comes to")
    p.add_argument("--repo", action="append", metavar="NAME",
                   help="the size: a repository the work touches; repeat it for each")
    p.add_argument("--tests", metavar="SENTENCE",
                   help="the size: the existing tests the work changes, a sentence")


def _ask_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--option", action="append", nargs="+", metavar=("LABEL", "LINE"),
                   help="an option: its label, and one line of text if it has one; "
                        "repeat it for each")
    p.add_argument("--recommend", help="the label of the option recommended")
    p.add_argument("--proposal", help="what is proposed, in place of options: one line of "
                                      f"at most {PROPOSAL_MAX} characters; - for stdin")
    p.add_argument("--default", help="a question's suggested answer")
    p.add_argument("--check", help="what tells that the ask is met; read and kept, "
                                   "never acted on by Pilot")
    p.add_argument("--due", help=f"an action's deadline: {', '.join(DUES)}; kept in the "
                                 "store, never rendered")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asks.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    store_help = "the store, asks/<n>-<slug>.json, or the document beside it"

    p = sub.add_parser("init", help="create a store under a slice folder; prints its path")
    p.add_argument("slice", metavar="<slice-dir>", help="the slice's folder")
    p.add_argument("slug", metavar="<slug>",
                   help="lower-case words joined by hyphens, e.g. requirements")
    _frame_args(p, title_required=True)

    p = sub.add_parser("append", help="add one ask; prints its id")
    p.add_argument("store", metavar="<store>", help=store_help)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--headline", required=True, help="the ask in one line, its heading")
    p.add_argument("--body", required=True, help="Markdown, or - for stdin")
    p.add_argument("--id", help="the ask's id; the kind's letter and the next number "
                                "when omitted")
    _ask_args(p)

    p = sub.add_parser("amend", help="replace an ask's fields, or with no id the "
                                     "document's; an empty value removes one")
    p.add_argument("store", metavar="<store>", help=store_help)
    p.add_argument("id", metavar="<id>", nargs="?", help="the ask's id, like D1")
    p.add_argument("--headline")
    p.add_argument("--body", help="Markdown, or - for stdin")
    _ask_args(p)
    _frame_args(p, title_required=False)
    p.add_argument("--clear", action="append", choices=(*_CLEAR_ASK, *_CLEAR_FRAME),
                   metavar="FIELD", help="remove an optional field: of the ask, "
                   f"{', '.join(_CLEAR_ASK)}; of the document, {', '.join(_CLEAR_FRAME)}")

    p = sub.add_parser("note", help="add a paragraph to one ask")
    p.add_argument("store", metavar="<store>", help=store_help)
    p.add_argument("id", metavar="<id>", help="the ask's id, like D1")
    p.add_argument("--by", required=True, help="who writes the note")
    p.add_argument("--text", required=True, help="the paragraph, or - for stdin")
    p.add_argument("--date", help="YYYY-MM-DD; today when omitted")

    p = sub.add_parser("list", help="one line per ask")
    p.add_argument("store", metavar="<store>", help=store_help)

    p = sub.add_parser("show", help="asks in full, with their answer lines")
    p.add_argument("store", metavar="<store>", help=store_help)
    p.add_argument("ids", metavar="<id>", nargs="*", help="the asks; all when omitted")

    p = sub.add_parser("render", help="write the document beside the store")
    p.add_argument("store", metavar="<store>", help=store_help)

    p = sub.add_parser("absorb", help="read a written-back document's answer lines "
                                      "into its store")
    p.add_argument("document", metavar="<document>",
                   help="the document Pilot wrote back, asks/<n>-<slug>.md")
    return parser


def _stdin(args: argparse.Namespace, *names: str) -> None:
    """Replace the one argument given as `-` with stdin."""
    taken = False
    for name in names:
        value = getattr(args, name, None)
        values = value if isinstance(value, list) else [value]
        if "-" not in values:
            continue
        if taken or values.count("-") > 1:
            raise AskError("only one argument reads stdin")
        taken = True
        text = sys.stdin.read()
        setattr(args, name, [text if v == "-" else v for v in values]
                if isinstance(value, list) else text)


_CLEAR_ASK = ("options", "recommend", "proposal", "default", "check", "due")
_CLEAR_FRAME = ("summary", "step", "for", "context", "premises", "out-of-scope", "size")


def _ask_fields(args: argparse.Namespace) -> dict:
    if args.option is not None and any(len(o) > 2 for o in args.option):
        raise AskError("an --option is a label and at most one line of text")
    if args.due not in (None, "") and args.due not in DUES:
        raise AskError(f"--due is one of {', '.join(DUES)}")
    return {"options": args.option, "recommend": args.recommend, "proposal": args.proposal,
            "default": args.default, "check": args.check, "due": args.due}


def _frame_fields(args: argparse.Namespace) -> dict:
    premises = None if args.premise is None else [
        dict(zip(PREMISE_PARTS, parts, strict=True)) for parts in args.premise]
    size = None
    if (args.phases, args.repo, args.tests) != (None, None, None):
        size = {"phases": args.phases, "repos": args.repo, "tests": args.tests}
    return {"title": args.title, "summary": args.summary, "step": args.step,
            "for_": args.for_, "context": args.context, "premises": premises,
            "out_of_scope": args.out_of_scope, "size": size}


def _cli_citations(fields: dict) -> list[str]:
    """`citation_problems` over an author's text as the CLI takes it: a
    value, a list of them (`--context`), or a list of lists (`--option`'s
    label and line). A field not given is not checked, so an amend is
    checked on what it changes."""
    found: list[str] = []
    for what, value in fields.items():
        items = value if isinstance(value, list) else [value]
        for item in items:
            for text in item if isinstance(item, list) else [item]:
                found += citation_problems(text, what)
    return found


def _ask_texts(args: argparse.Namespace) -> dict:
    return {"the headline": args.headline, "the body": args.body,
            "`--proposal`": args.proposal, "`--default`": args.default,
            "an `--option`": args.option}


def _frame_texts(args: argparse.Namespace) -> dict:
    return {"the title": args.title, "the summary": args.summary,
            "the context": args.context, "a `--premise`": args.premise,
            "an `--out-of-scope`": args.out_of_scope, "`--tests`": args.tests}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _stdin(args, "body", "proposal", "text", "context")
        command = args.command
        texts = {"init": _frame_texts, "append": _ask_texts, "note": lambda a: {
            "the note": a.text}, "amend": lambda a: {**_ask_texts(a), **_frame_texts(a)}}
        if command in texts:
            _refuse(f"{command} is refused", _cli_citations(texts[command](args)))
        if command in ("append", "amend"):
            _refuse(f"{command} is refused", proposal_problems(args.proposal, "`--proposal`"))
        if command in ("init", "amend"):
            _refuse(f"{command} is refused", opening_problems(
                args.context, args.premise, args.out_of_scope, args.tests))
        if command == "init":
            frame = _frame_fields(args)
            title = frame.pop("title")
            frame["context"] = frame["context"] or []
            print(create(args.slice, args.slug, title, **frame))
        elif command == "append":
            with editing(args.store) as store:
                print(append(store, args.kind, args.headline, args.body, id=args.id,
                             **_ask_fields(args)))
        elif command == "amend":
            ask = {k: v for k, v in _ask_fields(args).items() if v is not None}
            ask.update({k: v for k, v in (("headline", args.headline),
                                          ("body", args.body)) if v is not None})
            frame = {k: v for k, v in _frame_fields(args).items() if v is not None}
            for field in args.clear or ():
                if field in _CLEAR_ASK:
                    ask[field] = ""
                elif field in ("context", "premises", "out-of-scope"):
                    frame[field.replace("-", "_")] = []
                elif field == "size":
                    frame["size"] = {}
                else:
                    frame["for_" if field == "for" else field] = ""
            with editing(args.store) as store:
                if args.id is None:
                    if ask:
                        raise AskError("an ask's fields are amended with its id")
                    amend_frame(store, **frame)
                    print("the document amended")
                else:
                    if frame:
                        raise AskError("the document's fields are amended with no id")
                    amend(store, args.id, **ask)
                    print(f"{args.id} amended")
        elif command == "note":
            with editing(args.store) as store:
                note(store, args.id, args.by, args.text, args.date)
            print(f"{args.id} noted")
        elif command == "list":
            print(list_view(load(args.store)))
        elif command == "show":
            print(show_view(load(args.store), args.ids))
        elif command == "render":
            print(render_file(args.store))
        elif command == "absorb":
            print("\n".join(absorb_file(args.document)))
    except AskError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
