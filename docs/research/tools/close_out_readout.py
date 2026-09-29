#!/usr/bin/env python3
"""Close-out readout — what the reports hand over against what the operator rules.

Research tooling, not plugin. Reads every slice's close-out report under the given spec repos'
``slices/`` trees into one row per entry (section, severity, evidence class, author role, the
Consequence line, the strike reason, the ``Disposition:`` line), classifies each entry's fate
from the words on its heading and its disposition, and prints the tables of the 2026-09-28
read (``docs/research/close-out-read-2026-09-28.md``) and of the discussion that followed it
(``docs/research/close-out-triage-plan-2026-09-29.md`` § 3).

    close_out_readout.py extract <spec-repo>... [-o entries.json]
    close_out_readout.py report  [entries.json]
    close_out_readout.py dump    [entries.json] --fate card,fix,fold   # the progressed entries
    close_out_readout.py unclassified [entries.json]
    close_out_readout.py snapshots [entries.json] -o <dir>    # each report as handed over
    close_out_readout.py sessions <transcript-dir>... -o <dir> # the close-out chats, digested
    close_out_readout.py score <sorted-dir>... [--modes report-mode.json]
    close_out_readout.py order [entries.json] [--arm heldout-v2]  # where the picks sit
    close_out_readout.py focus [entries.json]         # § 3.1 the Focus line, by place
    close_out_readout.py who [entries.json]           # § 3.2 whose ruling; the sorts against it
    close_out_readout.py labels [entries.json] [--misses]   # § 3.3 labels, § 3.4 tables tried
    close_out_readout.py improvements [entries.json] [--misses]  # § 3.8
    close_out_readout.py tables [entries.json]        # § 3.9 the tables as ruled, § 3.5 misses
    close_out_readout.py signal [entries.json] [--misses] [--list]  # § 3.10 loud and silent
    close_out_readout.py appended <spec-repo>... [--why]   # § 3.6 the appended phases
    close_out_readout.py testgaps [entries.json] [--gaps-out <file>]  # § 3.7
    close_out_readout.py table-check [entries.json]   # the tool's table routes § 3.9/§ 3.10's
    close_out_readout.py corpus-check <snapshots-dir> [--before <rev>]  # import + render

``extract`` reads a slice folder's ``close-out.json`` (plugin 0.9.57 on) where it has one, and
its ``close-out.md`` otherwise. From a store the fate is the ruling's fields — what was done on
it, else the operator's words — not the pattern classifier; a strike without a ruling (the
consult, the doc phase, the wrap-up) is ``in-run``. Such a row carries the columns the other
subcommands read, and ``kind``, ``labels``, ``notes``, ``strike``, ``ruling``, ``route`` (the
plugin's ``close_out.route``, the entry taken as live) and ``wrap_up`` (its mark, or its strike).

``who``, ``labels``, ``improvements``, ``tables``, ``signal``, ``table-check`` and ``testgaps``
read the committed data under ``docs/research/data/`` — whose ruling an entry is from the read's
session coding (``close-out-read-2026-09-28.json``), the three label passes of 2026-09-29
(``close-out-labels-``, ``close-out-improvement-labels-``, ``close-out-signal-labels-``) — beside
the entries with their fates; ``focus`` the read's data file alone. Where they route an entry as
the plugin does, the labels are mapped onto the tool's vocabulary and routed by
``plugins/dev/tools/close_out.py`` itself: with the signal label, § 3.10's table as amended;
without, § 3.9's as ruled. The tables that were tried and not built — § 3.4's three, § 3.8's
first treatment and simpler rules, § 3.10's "silent is not closed" and "both", severity first
(note 26) — are this tool's own code. ``table-check`` holds the tool's routes against the plan's
numbers, ``corpus-check`` imports and renders each hand-over snapshot with the plugin's tool and
holds it against the tool before the store (``--before``); both exit 1 on a difference.

``order`` says where in a report the entries the operator progressed sit, under three reading
orders: the one ``close_out.py render`` gives today, a mechanical one (severity across kinds),
and the order of a sort from the read's data file (the sorter plan of 2026-09-29, commit
2cdf7db, since replaced by close-out-triage-plan-2026-09-29.md).
``snapshots`` recovers, from the spec repo's history, each report as the run left it: the newest
commit in which no ``Disposition:`` line carries words and no heading is struck by the
operator's pass. ``sessions`` finds the interactive sessions that wrote dispositions or struck
entries and writes one digest per session (what the operator typed, the assistant's prose, the
strikes). ``score`` reads a sort of those snapshots — one ``<project>-<slice>.json`` per report,
``{"rows": [{"id", "bucket", "why"}]}`` — against the fates in ``entries.json``.

The fate classes:

    in-run      struck during the run — a consult, the doc phase, a refutation, a supersede
    close       closed at the operator's pass (``blanket`` says the ruling named no entry)
    fix         fixed at the operator's pass (fix now / inline)
    card        carded (a tracker card or URL on the line)
    fold        folded into a slice or a handover
    done        an Outstanding action the operator carried out
    defer       deferred
    blank       live, no disposition

``progressed`` is card + fix + fold: the entries the operator spent anything on.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import importlib.util
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

SECTIONS = {
    "Outstanding actions": "A",
    "Notable events": "N",
    "Bugs": "B",
    "Open questions and rulings": "Q",
    "Suggestions": "S",
}
SEVERITIES = ("major", "minor", "nit", "cosmetic")
DEFAULT_DATA = Path("/tmp/close-out-entries.json")

_HEADING = re.compile(r"^### (?P<strike>~~)?(?P<id>[A-Z]\d+[a-z]?)\s*[—–-]\s*(?P<rest>.*)$")
_LABEL = re.compile(r"^\*{0,2}(Consequence|Provenance|Disposition):\*{0,2}\s?(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_ROLE = re.compile(
    r"(plan-writer|plan-reviewer|code-writer|code-reviewer|test-agent|test-fixer|doc-writer|"
    r"doc-unit|completion consult|consult|driver|operator|planning session|plan-slice|"
    r"run-slice|close-out)", re.I)


def _split_struck(rest: str) -> tuple[str, str]:
    """`headline~~ — reason` -> (headline, reason)."""
    if "~~" in rest:
        head, _, reason = rest.partition("~~")
        return head.strip(), reason.strip(" —–-").strip()
    return rest.strip(), ""


def parse_report(path: Path, project: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    slice_name = path.parent.name
    run = ""
    summary: list[str] = []
    focus: dict[str, str] = {}
    entries: list[dict] = []
    section = None
    cur: dict | None = None
    label = None
    in_fence = False
    in_comment = False
    focus_open = False

    def close_entry():
        nonlocal cur, label
        if cur is not None:
            cur["body_words"] = len(" ".join(cur.pop("_body")).split())
            for key in ("consequence", "provenance", "disposition"):
                cur[key] = " ".join(cur[key].split())
            entries.append(cur)
        cur = None
        label = None

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if _FENCE.match(line):
            in_fence = not in_fence
        if in_fence:
            if cur is not None and label is None:
                cur["_body"].append(line)
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        stripped = line.strip()
        if stripped.startswith("<!--") and not focus_open:
            if "-->" not in stripped:
                in_comment = True
            continue
        if line.startswith("Run:") and section is None and not run:
            run = line[4:].strip()
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "<!--")):
                run += " " + lines[i].strip()
                i += 1
            continue
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            close_entry()
            section = m.group(1)
            focus_open = False
            continue
        if section == "Summary":
            if stripped:
                summary.append(stripped)
            continue
        if section not in SECTIONS:
            continue
        m = _HEADING.match(line)
        if m:
            close_entry()
            focus_open = False
            struck = bool(m.group("strike"))
            headline, reason = _split_struck(m.group("rest")) if struck else (m.group("rest"), "")
            severity = ""
            sm = re.search(r"·\s*(major|minor|nit|cosmetic)\b", headline + " " + reason)
            if sm:
                severity = sm.group(1)
            cur = {
                "project": project, "slice": slice_name, "section": SECTIONS[section],
                "id": m.group("id"), "headline": headline, "severity": severity,
                "struck": struck, "strike_reason": reason,
                "consequence": "", "provenance": "", "disposition": "", "_body": [],
            }
            continue
        if line.startswith("### "):
            close_entry()
            focus_open = False
            cur = {
                "project": project, "slice": slice_name, "section": SECTIONS[section],
                "id": "?", "headline": line[4:].strip(), "severity": "", "struck": "~~" in line,
                "strike_reason": "", "consequence": "", "provenance": "", "disposition": "",
                "_body": [], "unshaped": True,
            }
            continue
        if cur is None:
            if line.startswith("Focus:"):
                focus_open = True
                focus[SECTIONS[section]] = re.sub(r"<!--.*?(-->|$)", "", line[6:]).strip()
                continue
            if focus_open:
                if not stripped:
                    focus_open = False
                else:
                    focus[SECTIONS[section]] += " " + re.sub(r"<!--.*?(-->|$)", "", stripped)
            continue
        lm = _LABEL.match(line)
        if lm:
            label = lm.group(1).lower()
            cur[label] = (cur[label] + " " + lm.group(2)).strip()
            continue
        if stripped in ("</details>", "") or stripped.startswith("<details>"):
            if not stripped and label in ("consequence", "provenance"):
                label = "after"
            continue
        if label in ("consequence", "provenance", "disposition"):
            cur[label] += " " + stripped
        else:
            cur["_body"].append(line)
    close_entry()

    for e in entries:
        prov = e["provenance"].lower()
        e["evidence"] = ("witnessed" if prov.startswith("witnessed")
                         else "read" if prov.startswith("read") else "")
        rm = _ROLE.search(e["provenance"])
        role = rm.group(1).lower() if rm else ""
        if role in ("completion consult",):
            role = "consult"
        if role in ("planning session", "plan-slice"):
            role = "plan-session"
        e["role"] = role
        f = focus.get(e["section"], "")
        e["in_focus"] = bool(re.search(rf"\b{re.escape(e['id'])}\b", f))
        e["consequence_none"] = bool(re.match(r"^none\b", e["consequence"].strip(), re.I))
        classify(e)
    return {
        "project": project, "slice": slice_name, "path": str(path), "run": run,
        "summary_words": len(" ".join(summary).split()),
        "focus": focus, "words": len(text.split()), "entries": entries,
    }


# --- fate -----------------------------------------------------------------------------------

_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
_ID_IN_TEXT = re.compile(r"\b([ANBQS]\d+)\b")
# a struck heading whose reason names the run's own machinery
_INRUN = re.compile(
    r"(consult \d|by (the )?(completion )?consult|consult'?s? (residue|rider)|the doc phase"
    r"|doc-writer|\babsorbed\b|superseded|refuted|duplicate of|does not reproduce"
    r"|(resolved|fixed|closed|landed) (by|in|with) P\d|mechanical residue|the test phase"
    r"|withdrawn|by the driver|resolved in-run|by its (own )?author|fixed in this session"
    r"|fixed in place by|struck by (the )?(doc phase|consult|doc-writer)|\bmoot\b)", re.I)
# the report's own card and the tracker's housekeeping are not an entry being carded
_NOT_A_CARD = re.compile(
    r"(close-out card|tracking card|tracking triage card|the card (can|once|please|when)"
    r"|(archive|archived|close|closed|closing) (the |close-out |tracking |triage )*card( #\d+)?"
    r"|card( #\d+)? (is |was )?(already )?archived|and the card|the live pass card)", re.I)
_CARD = re.compile(
    r"(trello\.com/c/|\btriage (card )?#\d+|\bcard(ed)?\b[^.;]{0,80}(#\d+|\b[A-Z]{2,6}-\d+\b)"
    r"|\b(filed|raised|carded|transferred)\b[^.;]{0,80}(#\d+|\b[A-Z]{2,6}-\d+\b)"
    r"|^\W*raise\b[^—]*—\s*(already raised as )?[A-Z]{2,6}-\d+|operator actions #\d+"
    r"|\bto [A-Z]{2,6}-\d+\b|— [A-Z]{2,6}-\d+\s*$|comment on (triage )?#\d+)", re.I)
_FOLD = re.compile(
    r"(\bfolded (verbatim )?into\b|\bfold(ed)? into (slice )?\d{3}|appended (verbatim )?to "
    r"(`?slices/|slice )|— to the \S+ handover|folded into [A-Z]\d|into the \S+ re-cut"
    r"|notes? (in|to|after) "
    r"(each|the outstanding|0\d\d))", re.I)
_FIX = re.compile(
    r"(\bfix(ed)? (now|inline|in place|at close-out)\b|fix-now|\bfixed\b|\bapplied (at|inline)"
    r"|resolved (inline|at close-out|by close-out)|\bdone inline\b|\bdone, [A-Z]\w+@|\badded in "
    r"[A-Z]\w+ [0-9a-f]{7}|resolved — fixed)", re.I)
_CLOSE = re.compile(
    r"(\bclos(e|ed|ing)\b|\bstruck\b|\bstrike\b|not progress|n't progress|not going to file"
    r"|no further action|won't fix|wontfix|\barchive\b|^\W*(ok|go|yes|agree)\b)", re.I)
_DEFER = re.compile(r"\bdefer", re.I)
_DONE = re.compile(
    r"\b(done|completed|actioned|executed|pushed|tapped|carried out|landed|complete)\b", re.I)
_SHEET = re.compile(
    r"(suggest(ed|ion)|standing rules|recommendation|the proposed|as proposed|auto close"
    r"|on the (close-out )?session's)", re.I)
_BLANKET = re.compile(
    r"(the rest|everything|the ones that|anything|the remaining|still.blank|auto close"
    r"|your suggestions|your recommendations|as suggested|^\W*(go|ok|yes)\b|the entries i didn't"
    r"|otherwise|those|the reset|have a disposition or need)", re.I)


def classify(e: dict) -> None:
    disp = e["disposition"]
    reason = e["strike_reason"]
    both = f"{disp} || {reason}"
    carding = _NOT_A_CARD.sub(" ", both)
    sm = re.search(r"suggest(?:ed|ion)[^.;]{0,40}?\b(close|card|fix now|fix-now|fold|defer)\b",
                   disp, re.I)
    e["suggested"] = sm.group(1).lower().replace("-", " ") if sm else ""
    e["sheet"] = bool(_SHEET.search(both))

    operator_close = re.search(r"closed by the operator|closed on the close-out|closed at close",
                               reason, re.I)
    if e["struck"] and _INRUN.search(reason) and not re.search(
            r"operator's (fix-now|inline|D\d+ ruling|ruling)|at close-out \(", reason, re.I):
        fate = "in-run"
    elif e["struck"] and not disp and not re.search(r"operator|close-out", reason, re.I):
        fate = "in-run"
    elif e["section"] == "A" and _DONE.search(both) and not operator_close and not re.search(
            r"operator actions", both, re.I):
        fate = "done"
    elif _CARD.search(carding):
        fate = "card"
    elif _FOLD.search(both):
        fate = "fold"
    elif _FIX.search(reason) or (_FIX.search(disp) and _SHA.search(both)) or re.search(
            r"(fix|apply)[^—]{0,60}inline[^—]*—\s*(yes|done|fixed|added)", disp, re.I):
        fate = "fix"
    elif e["section"] == "A" and _DONE.search(both) and not operator_close:
        fate = "done"
    elif _DEFER.search(disp):
        fate = "defer"
    elif e["struck"]:
        fate = "close" if (disp or re.search(r"operator|close", reason, re.I)) else "in-run"
    elif not disp:
        fate = "blank"
    elif _CLOSE.search(disp):
        fate = "close"
    else:
        fate = "other"
    e["fate"] = fate
    words = disp.split(" — ")[0]
    e["blanket"] = fate == "close" and not re.search(
        rf"\b{re.escape(e['id'])}\b", words) and bool(_BLANKET.search(words) or not disp)
    e["progressed"] = fate in ("card", "fix", "fold")


# --- a report's store (plugin 0.9.57 on) -----------------------------------------------------

# A store's kinds in the read's five letters: what should be fixed as a Bug, an improvement as a
# Suggestion. An imported entry keeps the section it stood under.
_KIND_SECTION = {"action": "A", "event": "N", "decision": "Q", "defect": "B", "prose": "B",
                 "test-gap": "B", "improvement": "S"}
# What was done on a ruling, or the ruling's words: the suggested vocabulary of the contract
# (card · fix now · fold into · close · defer) and what a session writes after it.
_DID = (
    ("card", re.compile(r"\bcard(ed|s)?\b|\bfiled\b|\b[A-Z]{2,6}-\d+\b|#\d+", re.I)),
    ("fold", re.compile(r"\bfold(ed|s)?\b|\bappended (verbatim )?to\b", re.I)),
    ("fix", re.compile(r"\bfix(ed|es)?\b|\bapplied\b|\bresolved\b", re.I)),
    ("defer", _DEFER),
    ("close", _CLOSE),
)


def _ruled_fate(ruling: dict, struck: bool, section: str) -> str:
    """The fate of a ruled entry from the ruling's fields: what was done on it first, then the
    operator's words; a struck entry that says neither was closed."""
    for text in (ruling.get("did") or "", ruling.get("words") or ""):
        if section == "A" and _DONE.search(text):
            return "done"
        text = _NOT_A_CARD.sub(" ", text)
        for fate, rx in _DID:
            if rx.search(text):
                return fate
    return "close" if struck else "other"


def _store_row(s: dict, project: str, slice_name: str, closed: dict, touched) -> dict:
    co = _close_out()
    strike, ruling = s.get("strike"), s.get("ruling")
    words = (ruling or {}).get("words") or ""
    did = (ruling or {}).get("did") or ""
    section = SECTIONS.get(s.get("section") or "") or _KIND_SECTION.get(s.get("kind"), "?")
    provenance = " — ".join(filter(None, (s.get("evidence"), s.get("author"))))
    if ruling:
        fate = _ruled_fate(ruling, bool(strike), section)
    else:
        fate = "in-run" if strike else "blank"     # a strike without a ruling is the run's
    mark = s.get("wrap_up")
    if mark:
        wrap_up = dict(mark)
    elif strike and "wrap-up" in (strike.get("by") or ""):
        wrap_up = {"outcome": "struck", "by": strike["by"], "date": strike.get("date"),
                   "commit": strike.get("commit"), "text": [strike["reason"]]}
    else:
        wrap_up = None
    role = _ROLE.search(s.get("author") or "")
    role = role.group(1).lower() if role else ""
    role = {"completion consult": "consult", "planning session": "plan-session",
            "plan-slice": "plan-session"}.get(role, role)
    consequence = s.get("consequence") or ""
    return {
        "project": project, "slice": slice_name, "section": section, "id": s["id"],
        "kind": s.get("kind"), "headline": s["headline"], "severity": s.get("grade") or "",
        "struck": bool(strike), "strike_reason": (strike or {}).get("reason", ""),
        "strike": strike, "consequence": consequence, "provenance": provenance,
        "disposition": f"{words} — {did}" if words and did else words, "ruling": ruling,
        "body_words": len(" ".join(s.get("body") or []).split()),
        "evidence": s.get("evidence") or "",
        "role": role,
        "in_focus": False, "consequence_none": bool(re.match(r"^none\b", consequence, re.I)),
        "labels": s.get("labels"),
        # the route the entry stood on until it was struck: the tool's, with the wrap-up's mark
        "route": co.route({**s, "strike": None}, touched)[0],
        "wrap_up": wrap_up,
        "notes": [{"by": n.get("by"), "date": n.get("date"), "text": " ".join(n.get("text") or []),
                   **({"relabel": n["relabel"]} if n.get("relabel") else {})}
                  for n in s.get("notes") or []],
        "fate": fate, "progressed": fate in ("card", "fix", "fold"),
        "blanket": fate == "close" and bool(closed) and words == closed.get("words"),
        "suggested": "", "sheet": False,
    }


def parse_store(folder: Path, project: str) -> dict:
    """A slice folder's ``close-out.json``, read into the rows ``parse_report`` gives, the fate
    taken from the ruling's fields instead of the pattern classifier."""
    co = _close_out()
    store = json.loads((folder / co.STORE_NAME).read_text(encoding="utf-8"))
    md = folder / co.REPORT_NAME
    text = md.read_text(encoding="utf-8", errors="replace") if md.exists() else ""
    run = next((ln[4:].strip() for ln in text.splitlines() if ln.startswith("Run:")), "")
    touched = co.touched_repos(folder)
    closed = store.get("closed") or {}
    return {
        "project": project, "slice": folder.name, "path": str(md),
        "store": str(folder / co.STORE_NAME), "closed": store.get("closed"), "run": run,
        "summary_words": 0, "focus": {}, "words": len(text.split()),
        "entries": [_store_row(s, project, folder.name, closed, touched)
                    for s in store["entries"]],
    }


# --- commands -------------------------------------------------------------------------------

def cmd_extract(args) -> int:
    reports = []
    for repo in args.repos:
        repo = Path(repo)
        project = repo.name.removesuffix("Specs")
        folders = {p.parent for name in ("close-out.md", "close-out.json")
                   for p in (repo / "slices").rglob(name)}
        for folder in sorted(folders):
            if "archive" in folder.parts:
                continue
            if (folder / "close-out.json").exists():
                reports.append(parse_store(folder, project))
            else:
                reports.append(parse_report(folder / "close-out.md", project))
    Path(args.out).write_text(json.dumps(reports, indent=1), encoding="utf-8")
    n = sum(len(r["entries"]) for r in reports)
    print(f"{len(reports)} reports, {n} entries -> {args.out}")
    return 0


def _load(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f} %" if d else "—"


def _table(rows: list[list], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    print("| " + " | ".join(str(h).ljust(w) for h, w in zip(header, widths, strict=True)) + " |")
    print("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for r in rows:
        print("| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)) + " |")
    print()


FATES = ("in-run", "close", "fix", "card", "fold", "done", "defer", "blank", "other")


def _fate_row(label: str, es: list[dict]) -> list:
    c = Counter(e["fate"] for e in es)
    decided = [e for e in es if e["fate"] in ("close", "fix", "card", "fold", "defer")]
    prog = sum(1 for e in decided if e["progressed"])
    return [label, len(es)] + [c.get(f, 0) for f in FATES] + [_pct(prog, len(decided))]


def cmd_report(args) -> int:
    reports = _load(args.data)
    entries = [e for r in reports for e in r["entries"]]
    header = ["", "entries"] + list(FATES) + ["progressed of ruled"]

    print(f"## Corpus\n\n{len(reports)} reports, {len(entries)} entries\n")
    rows = []
    for proj in sorted({r["project"] for r in reports}):
        rs = [r for r in reports if r["project"] == proj]
        n = [len(r["entries"]) for r in rs]
        w = [r["words"] for r in rs]
        live = [sum(1 for e in r["entries"] if e["fate"] != "in-run") for r in rs]
        rows.append([proj, len(rs), sum(n), statistics.median(n), max(n),
                     statistics.median(live), int(statistics.median(w)), max(w)])
    _table(rows, ["project", "reports", "entries", "median", "max", "median handed over",
                  "median words", "max words"])

    print("## Fate by project\n")
    _table([_fate_row(p, [e for e in entries if e["project"] == p])
            for p in sorted({e["project"] for e in entries})] + [_fate_row("all", entries)],
           header)

    print("## Fate by section\n")
    _table([_fate_row(s, [e for e in entries if e["section"] == s]) for s in "ANBQS"], header)

    print("## Bugs by severity\n")
    bugs = [e for e in entries if e["section"] == "B"]
    _table([_fate_row(s or "(none)", [e for e in bugs if e["severity"] == s])
            for s in SEVERITIES + ("",)], header)

    print("## By evidence class (handed-over entries)\n")
    _table([_fate_row(c or "(unstated)", [e for e in entries if e["evidence"] == c])
            for c in ("witnessed", "read", "")], header)

    print("## By author role\n")
    roles = Counter(e["role"] for e in entries)
    _table([_fate_row(r or "(unstated)", [e for e in entries if e["role"] == r])
            for r, _ in roles.most_common()], header)

    print("## Named in the section's Focus line\n")
    _table([_fate_row("named", [e for e in entries if e["in_focus"]]),
            _fate_row("not named", [e for e in entries if not e["in_focus"]])], header)

    print("## Consequence line says `none`\n")
    _table([_fate_row("none", [e for e in entries if e["consequence_none"]]),
            _fate_row("states one", [e for e in entries
                                     if e["consequence"] and not e["consequence_none"]]),
            _fate_row("no line", [e for e in entries if not e["consequence"]])], header)

    print("## How the closes were ruled\n")
    closes = [e for e in entries if e["fate"] == "close"]
    _table([["blanket (no entry named)", sum(1 for e in closes if e["blanket"])],
            ["named or reasoned", sum(1 for e in closes if not e["blanket"])],
            ["from a session's sheet", sum(1 for e in closes if e["sheet"])]],
           ["closes", len(closes)])

    print("## The sheet's suggestion against the recorded fate\n")
    sug = [e for e in entries if e["suggested"]]
    pairs = Counter((e["suggested"], e["fate"]) for e in sug)
    _table([[s, f, n] for (s, f), n in sorted(pairs.items(), key=lambda kv: -kv[1])],
           ["suggested", "fate", "entries"])

    print("## Per report\n")
    rows = []
    for r in reports:
        es = r["entries"]
        c = Counter(e["fate"] for e in es)
        rows.append([r["project"][:4], r["slice"][:34], r["words"], len(es), c["in-run"],
                     c["close"], c["fix"], c["card"], c["fold"], c["done"], c["defer"],
                     c["blank"], c["other"]])
    _table(rows, ["proj", "slice", "words", "n", "in-run", "close", "fix", "card", "fold",
                  "done", "defer", "blank", "other"])
    return 0


def cmd_dump(args) -> int:
    fates = set(args.fate.split(","))
    for r in _load(args.data):
        for e in r["entries"]:
            if e["fate"] in fates:
                print(f"{r['project']} {r['slice'][:3]} {e['id']:<4} [{e['fate']}] "
                      f"{e['severity'] or '-':<8} {e['evidence'] or '-':<9} {e['role'] or '-':<14}"
                      f" focus={'y' if e['in_focus'] else 'n'}")
                print(f"    H: {e['headline'][:150]}")
                print(f"    C: {e['consequence'][:260]}")
                print(f"    D: {e['disposition'][:260]}")
                if e["strike_reason"]:
                    print(f"    X: {e['strike_reason'][:160]}")
    return 0


def cmd_unclassified(args) -> int:
    by = defaultdict(list)
    for r in _load(args.data):
        for e in r["entries"]:
            if e["fate"] == "other" or e.get("unshaped"):
                by[r["slice"]].append(e)
    for s, es in by.items():
        for e in es:
            print(f"{s[:3]} {e['id']} struck={e['struck']} D: {e['disposition'][:200]} "
                  f"|| X: {e['strike_reason'][:120]}")
    return 0


# --- the report as handed over -----------------------------------------------------------------

def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          errors="replace", check=False).stdout


def _ruled(text: str) -> bool:
    for line in text.splitlines():
        m = re.match(r"^\*{0,2}Disposition:\*{0,2}(.*)$", line)
        if m and m.group(1).strip():
            return True
        if line.startswith("### ~~") and re.search(
                r"operator|close-out|closed at|fix-now", line.split("~~")[-1], re.I):
            return True
    return False


def cmd_snapshots(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for r in _load(args.data):
        parts = Path(r["path"]).parts
        at = parts.index("slices")
        repo, rel = str(Path(*parts[:at])), str(Path(*parts[at:]))
        log = _git(repo, "log", "--follow", "--name-only", "--format=@%H %cI", "--", rel)
        commits, cur = [], None
        for line in log.splitlines():
            if line.startswith("@"):
                cur = line[1:].split(" ")
            elif line.strip() and cur:
                commits.append((cur[0], cur[1], line.strip()))
                cur = None
        texts = ((c, _git(repo, "show", f"{c[0]}:{c[2]}")) for c in commits)  # newest first
        found = next(((c, text) for c, text in texts if text and not _ruled(text)), None)
        if not found:
            continue
        (sha, when, _name), text = found
        target = out / f"{r['project']}-{r['slice']}.md"
        target.write_text(text, encoding="utf-8")
        live = re.sub(r"<details>.*?</details>", "", text, flags=re.S)
        live = re.sub(r"<!--.*?-->", "", live, flags=re.S)
        index.append({
            "project": r["project"], "slice": r["slice"], "snapshot": str(target),
            "sha": sha[:9], "when": when, "words": len(text.split()),
            "live": len(re.findall(r"^### (?!~~)", text, re.M)),
            "struck": len(re.findall(r"^### ~~", text, re.M)),
            "live_words": len(live.split()), "stamped": "not yet stamped" not in text,
        })
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    words = sorted(x["live_words"] for x in index)
    entries = sorted(x["live"] for x in index)

    def pick(xs, q):
        return xs[min(len(xs) - 1, int(len(xs) * q))]

    print(f"{len(index)} snapshots -> {out}")
    print(f"live entries at hand-over: median {statistics.median(entries)}, "
          f"p75 {pick(entries, .75)}, p90 {pick(entries, .9)}, max {entries[-1]}")
    print(f"live words at hand-over:   median {statistics.median(words)}, "
          f"p75 {pick(words, .75)}, p90 {pick(words, .9)}, max {words[-1]}")
    return 0


# --- the close-out chats -----------------------------------------------------------------------

_STRIKE = re.compile(r"close_out\.py\"? +strike")
_STRIKE_ARGS = re.compile(r"strike\s+\S+\s+(\w+)\s+--reason\s+(\"[^\"]*\"|'[^']*')")
_SLICE_IN_CMD = re.compile(
    r"close_out\.py\"? +(?:strike|render|list|note|counts|append)\s+\S*?slices/(?:\w+/)?"
    r"(\d{3}[a-z]?)_")
_SLICE_IN_PATH = re.compile(r"slices/(?:\w+/)?(\d{3}[a-z]?)_[a-z0-9_]+/close-out\.md")


def _digest(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if "close-out" not in raw and "close_out" not in raw:
        return None
    if '"promptSource":"typed"' not in raw and '"promptSource": "typed"' not in raw:
        return None
    turns, slices = [], Counter()
    typed = strikes = edits = 0
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        ts = rec.get("timestamp", "")
        if rec.get("type") == "user":
            if rec.get("promptSource") == "typed":
                texts = [content] if isinstance(content, str) else [
                    b["text"] for b in content or [] if b.get("type") == "text"]
                for text in texts:
                    typed += 1
                    turns.append(("OPERATOR", ts, text))
            if isinstance(content, list):
                for b in content:
                    if b.get("type") != "tool_result":
                        continue
                    body = b.get("content")
                    body = body if isinstance(body, str) else json.dumps(body)
                    if "answered your questions" in body or "User has answered" in body:
                        turns.append(("OPERATOR-DIALOG", ts, body[:3000]))
        elif rec.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    turns.append(("ASSISTANT", ts, b["text"]))
                if b.get("type") != "tool_use":
                    continue
                inp = b.get("input") or {}
                if b.get("name") == "AskUserQuestion":
                    turns.append(("ASSISTANT-DIALOG", ts, json.dumps(inp)[:3000]))
                elif b.get("name") == "Bash" and "close_out.py" in inp.get("command", ""):
                    cmd = inp["command"]
                    slices.update(_SLICE_IN_CMD.findall(cmd))
                    n = len(_STRIKE.findall(cmd))
                    if n:
                        strikes += n
                        what = "; ".join(f"{a} {b}" for a, b in _STRIKE_ARGS.findall(cmd))
                        turns.append(("ACTION", ts, "strike: " + what[:1500]))
                elif b.get("name") in ("Edit", "Write") and "close-out.md" in inp.get(
                        "file_path", ""):
                    slices.update(_SLICE_IN_PATH.findall(inp["file_path"]))
                    lines = re.findall(r"\*\*Disposition:\*\*[^\n]*", inp.get("new_string", ""))
                    if lines:
                        edits += 1
                        turns.append(("ACTION", ts, "disposition written: "
                                      + " | ".join(x[:400] for x in lines)))
    if not typed or not (strikes or edits):
        return None
    return {"session": path.stem, "typed": typed, "strikes": strikes, "edits": edits,
            "slices": slices.most_common(), "turns": turns,
            "start": next(t[1] for t in turns if t[0] == "OPERATOR")}


def cmd_sessions(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for folder in args.dirs:
        folder = Path(folder)
        project = folder.name.removeprefix("-work-")
        for path in sorted(folder.glob("*.jsonl")):
            d = _digest(path)
            if not d:
                continue
            turns = d.pop("turns")
            d["project"] = project
            index.append(d)
            with open(out / f"{project}-{d['session']}.md", "w", encoding="utf-8") as fh:
                fh.write(f"# {project} session {d['session']}\nslices touched: {d['slices']}\n"
                         f"strikes: {d['strikes']}, disposition edits: {d['edits']}\n")
                for who, ts, text in turns:
                    fh.write(f"\n## {who} [{ts[:16]}]\n\n{text.strip()}\n")
    index.sort(key=lambda d: d["start"])
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(index)} sessions -> {out}")
    return 0


# --- a sort of the snapshots, scored ---------------------------------------------------------

_MOOT = re.compile(
    r"already (fixed|closed|resolved|done|struck|landed)|nothing left to (change|fix)"
    r"|no action owed|verified already|(fixed|closed|resolved) in the doc phase"
    r"|by the doc phase|the doc phase had already", re.I)
UNFLAGGED = ("close", "moot")
READ_WHOLE = ("needs-eyes", "card", "action")


def _sorted_rows(folder: Path, entries: dict, modes: dict) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "index.json":
            continue
        project, slice_name = path.stem.split("-", 1)
        number = re.match(r"\d+[a-z]?", slice_name).group(0)
        for row in json.loads(path.read_text(encoding="utf-8"))["rows"]:
            e = entries.get((project, slice_name, row["id"]))
            if not e or e["fate"] not in ("card", "fold", "fix", "close"):
                continue
            moot = _MOOT.search(e["disposition"] + " " + e["strike_reason"])
            rows.append({
                "report": path.stem, "id": row["id"], "bucket": row["bucket"].strip().lower(),
                "why": row.get("why", ""), "truth": "moot" if moot else e["fate"],
                "mode": modes.get(f"{project}-{number}", "unknown"), "section": e["section"],
                "words": e["body_words"] + len(e["consequence"].split())
                + len(e["headline"].split()),
                "headline_words": len(e["headline"].split()),
            })
    return rows


def _score(label: str, rows: list[dict]) -> None:
    if not rows:
        return
    ruled = [r for r in rows if r["truth"] != "moot"]
    progressed = [r for r in ruled if r["truth"] != "close"]
    carded = [r for r in progressed if r["truth"] in ("card", "fold")]
    fixed = [r for r in progressed if r["truth"] == "fix"]
    closed = [r for r in ruled if r["bucket"] in UNFLAGGED]

    def kept(xs):
        n = sum(r["bucket"] not in UNFLAGGED for r in xs)
        return f"{n}/{len(xs)} = {_pct(n, len(xs))}"

    lost = sum(r["truth"] != "close" for r in closed)
    per = defaultdict(int)
    for r in ruled:
        per[r["report"]] += r["bucket"] in UNFLAGGED and r["truth"] != "close"
    whole = sum(r["words"] for r in rows if r["bucket"] in READ_WHOLE)
    lines = sum(r["headline_words"] + len(r["why"].split())
                for r in rows if r["bucket"] not in READ_WHOLE)
    total = sum(r["words"] for r in rows)
    print(f"### {label}: {len(per)} reports, {len(ruled)} ruled entries "
          f"(+{len(rows) - len(ruled)} already fixed), progressed {len(progressed)} "
          f"({_pct(len(progressed), len(ruled))})\n")
    _table([
        ["the sort closes", f"{len(closed)} ({_pct(len(closed), len(ruled))})"],
        ["… of which the operator progressed", f"{lost} ({_pct(lost, len(closed))})"],
        ["progressed entries the sort kept", kept(progressed)],
        ["… carded or folded", kept(carded)],
        ["… fixed inline", kept(fixed)],
        ["reports with no progressed entry closed",
         f"{sum(1 for v in per.values() if not v)}/{len(per)}"],
        ["progressed entries closed, per report", f"{statistics.mean(per.values()):.1f}"],
        ["words to read (whole: needs-eyes, card, action; a line for the rest)",
         f"{whole + lines} of {total} ({_pct(whole + lines, total)})"],
    ], ["", label])
    buckets = Counter(r["bucket"] for r in ruled)
    _table([[b, n, *(sum(1 for r in ruled if r["bucket"] == b and r["truth"] == t)
                     for t in ("close", "fix", "card", "fold")),
             _pct(sum(1 for r in ruled if r["bucket"] == b and r["truth"] != "close"), n)]
            for b, n in buckets.most_common()],
           ["bucket", "entries", "closed", "fixed", "carded", "folded", "progressed"])


def cmd_score(args) -> int:
    entries = {(e["project"], e["slice"], e["id"]): e
               for r in _load(args.data) for e in r["entries"]}
    modes = json.loads(Path(args.modes).read_text(encoding="utf-8")) if args.modes else {}
    for folder in args.dirs:
        rows = _sorted_rows(Path(folder), entries, modes)
        _score(f"{folder} — all", rows)
        if modes:
            own = ("direct", "mixed", "unknown")
            _score(f"{folder} — ruled by the operator's own reading",
                   [r for r in rows if r["mode"] in own])
            _score(f"{folder} — ruled from a session's sheet",
                   [r for r in rows if r["mode"] not in own])
    return 0


# --- where in the report the progressed entries sit ------------------------------------------

_GRADES = ("major", "minor", "", "nit", "cosmetic")     # ungraded reads between minor and nit
READING = ("action", "needs-eyes", "card", "fix now", "fold", "test gaps", "close", "moot")


def _number(e: dict) -> int:
    m = re.search(r"\d+", e["id"])
    return int(m.group(0)) if m else 0


def _key_today(e: dict) -> tuple:
    """`close_out.py render` as it is: sections A N B Q S, Bugs by severity, the rest by id."""
    grade = (*SEVERITIES, "").index(e["severity"]) if e["section"] == "B" else 0
    return ("ANBQS".index(e["section"]), grade, _number(e))


def _key_mechanical(e: dict) -> tuple:
    """No judgment: actions, then graded by severity across kinds, nits and `Consequence:
    none` after them, events of the run last — those without a consequence at the very end."""
    if e["section"] == "A":
        tier = 0
    elif e["section"] == "N":
        tier = 4 if e["consequence_none"] else 3
    elif e["severity"] in ("nit", "cosmetic") or e["consequence_none"]:
        tier = 2
    else:
        tier = 1
    return (tier, _GRADES.index(e["severity"]), "BQSNA".index(e["section"]), _number(e))


def _key_sorted(buckets: dict):
    def key(e: dict) -> tuple:
        bucket = buckets.get(e["id"], "needs-eyes")
        return (READING.index(bucket) if bucket in READING else 1,
                _GRADES.index(e["severity"]), "AQBSN".index(e["section"]), _number(e))
    return key


def _positions(entries: list[dict], key) -> list[tuple[float, dict]]:
    """Each entry with the share of the report's words that precede it in that order."""
    order = sorted(entries, key=key)
    words = [e["body_words"] + len(e["consequence"].split()) + len(e["headline"].split())
             for e in order]
    total, before, out = sum(words) or 1, 0, []
    for e, w in zip(order, words, strict=True):
        out.append((before / total, e))
        before += w
    return out


def cmd_order(args) -> int:
    sorts = json.loads(Path(args.sorts).read_text(encoding="utf-8"))["sorts"][args.arm]
    reports = []
    for r in _load(args.data):
        handed = [e for e in r["entries"]
                  if e["fate"] != "in-run" and re.fullmatch(r"[ANBQS]\d+", e["id"])
                  and e["severity"] in _GRADES]
        if sum(e["fate"] in ("card", "fix", "fold", "close") for e in handed) >= 4:
            reports.append((f"{r['project']}-{r['slice']}", handed))
    held = [(name, es) for name, es in reports if name in sorts]

    def row(label: str, which: list, key_of) -> list:
        ruled, picked = Counter(), Counter()
        starts = []
        for name, es in which:
            for at, e in _positions(es, key_of(name)):
                if e["fate"] not in ("card", "fix", "fold", "close"):
                    continue
                fifth = min(int(at * 5), 4)
                ruled[fifth] += 1
                if e["progressed"]:
                    picked[fifth] += 1
                    starts.append(at)
        return [label, len(which), *(_pct(picked[i], ruled[i]) for i in range(5)),
                _pct(sum(s < 1 / 3 for s in starts), len(starts)),
                _pct(sum(s >= 2 / 3 for s in starts), len(starts))]

    print("Progressed share of the entries ruled, by fifth of the report in reading order "
          "(by words);\nthen the share of all progressed entries that start in the first and "
          "in the last third.\n")
    _table([
        row("today's order", reports, lambda _: _key_today),
        row("mechanical order", reports, lambda _: _key_mechanical),
        row(f"today's order, {args.arm}", held, lambda _: _key_today),
        row(f"mechanical order, {args.arm}", held, lambda _: _key_mechanical),
        row(f"sorted, {args.arm}", held, lambda name: _key_sorted(sorts[name])),
    ], ["order", "reports", "1st fifth", "2nd", "3rd", "4th", "5th", "first third",
        "last third"])

    # What stays open when the sorted report folds what one line settles: a sheet line per
    # entry, the read-in-full buckets whole, and the events without a consequence as headlines.
    n = Counter()
    total = sheet = whole = labels = 0
    shares = []
    for name, es in held:
        r_total = r_open = 0
        for e in es:
            bucket = sorts[name].get(e["id"])
            if bucket is None:
                continue
            head, claim = len(e["headline"].split()), len(e["consequence"].split())
            words = head + e["body_words"] + claim
            r_total += words
            if e["section"] == "N" and e["consequence_none"]:
                n["record"] += 1
                r_open += head
                continue
            sheet += head + 12          # the headline and a why-clause
            r_open += head + 12
            if bucket in READ_WHOLE:
                n["whole"] += 1
                whole += words
                r_open += words
            else:
                n["folded"] += 1
                labels += claim
        total += r_total
        shares.append(r_open / (r_total or 1))
    print(f"\nSorted, {args.arm}: {n['whole']} entries read in full, {n['folded']} folded, "
          f"{n['record']} events without a consequence to the record.\n"
          f"Open words — the sheet and the bodies read in full: "
          f"{_pct(sheet + whole, total)} of today's (median report "
          f"{round(100 * statistics.median(shares))} %); with the Consequence line of every folded "
          f"entry read as well: {_pct(sheet + whole + labels, total)}.")
    return 0


# --- the discussion of 2026-09-29: whose ruling, the labels, the routes ----------------------

TOOLS = Path(__file__).resolve().parents[3] / "plugins" / "dev" / "tools"
DATA = Path(__file__).resolve().parents[1] / "data"
READ_DATA = DATA / "close-out-read-2026-09-28.json"
LABELS_DATA = DATA / "close-out-labels-2026-09-29.json"
IMPROVEMENT_DATA = DATA / "close-out-improvement-labels-2026-09-29.json"
SIGNAL_DATA = DATA / "close-out-signal-labels-2026-09-29.json"
RULED = ("card", "fix", "fold", "close")
REST = ("unclear", "uncoded")   # neither the operator's own, advice, nor a sheet's
_ENTRY_ID = re.compile(r"[ANBQS]\d+")
_GRADE_RANK = {"major": 0, "minor": 1, "": 2, "nit": 3, "cosmetic": 4}


@functools.cache
def _close_out():
    """The plugin's close_out.py in this checkout — the routes are its own."""
    spec = importlib.util.spec_from_file_location("close_out", TOOLS / "close_out.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report_key(project: str, slice_name: str) -> str:
    """`KubeCoder-163`: the read's key. Two reports share one, and are one wherever it is used."""
    return f"{project}-{slice_name[:3]}"


def _key_of(name: str) -> str:
    """`Ansible-008_slug` -> `Ansible-008`."""
    return name[:name.index("-") + 4]


# The replay's vocabulary onto the tool's (plan § 7, "The tables in the tool are the tables that
# were tested"); a value not named here is the same word in both.
_TO_TOOL = {
    "kind": {"question": "decision", "slice-input": "defect", "cleanup": "defect",
             "hardening": "defect", "idea": "defect"},
    "trigger": {"fault-or-coincidence": "fault"},
    "impact": {"wrong-or-lost": "severe", "broken-or-stuck": "broken",
               "misleading": "degraded", "none-observable": "none"},
    "fix": {"known-several": "several-places", "na": None},
    "felt": {"every-use": "in-use", "some-uses": "in-use", "after-a-change": "after-change",
             "after-an-incident": "after-incident"},
    "prevents": {"misleading": "degraded", "wrong-or-lost": "severe",
                 "broken-or-stuck": "broken"},
}


def _tool_value(label: str, value):
    return _TO_TOOL.get(label, {}).get(value, value)


# The routes in the plan's words, in the order of § 3.9's table.
ORDER = ("to the operator: an action", "to the operator: a decision",
         "to the operator: severe or major, in place of a close",
         "to the operator: a potential improvement", "to the wrap-up: fix",
         "to the wrap-up: a potential improvement", "to the wrap-up: fix, or ask for a card",
         "to the wrap-up: look", "input for a later slice", "to Fieldnotes", "closed",
         "the record")
RISK, FIX_OR_CARD = ORDER[2], ORDER[6]
_ROUTE_NAME = {
    "operator:action": ORDER[0], "operator:decision": ORDER[1], "operator:risk": ORDER[2],
    "operator:improvement": ORDER[3], "wrap-up:fix": ORDER[4], "wrap-up:improvement": ORDER[5],
    "wrap-up:fix-or-card": ORDER[6], "wrap-up:look": ORDER[7], "wrap-up:fold": ORDER[8],
    "record": ORDER[11],
}
GROUPS = ("comes to the operator", "goes to the wrap-up", "input for a later slice",
          "to Fieldnotes", "closed", "the record")


def _group(route: str) -> str:
    if route.startswith("to the operator"):
        return GROUPS[0]
    if route.startswith("to the wrap-up"):
        return GROUPS[1]
    return route


class Discussion:
    """The entries with their fates (``entries.json``), whose ruling each is (the read's session
    coding), and the committed label data of the three passes — keyed by (report key, id)."""

    def __init__(self, data):
        self.reports = _load(data)
        self.read = json.loads(READ_DATA.read_text(encoding="utf-8"))
        self.entries: dict[tuple[str, str], dict] = {}
        for r in self.reports:
            rep = _report_key(r["project"], r["slice"])
            for e in r["entries"]:
                if _ENTRY_ID.fullmatch(e["id"]):
                    e["_rep"] = rep
                    self.entries[(rep, e["id"])] = e
        self.modes: dict[str, set] = {}
        on_sheet, named, advised = set(), set(), set()
        for s in self.read["sessions"]:
            if s["mode"] == "other":
                continue
            p = s["project"]
            for sl in s["slices"]:
                self.modes.setdefault(f"{p}-{sl}", set()).add(s["mode"])
            on_sheet |= {(f"{p}-{sl}", i) for sl, i, _ in s["sheet"]}
            named |= {(f"{p}-{row[0]}", row[1]) for row in s["named_rulings"] + s["overrides"]}
            advised |= {(f"{p}-{a[0]}", a[1]) for a in s["advice"]}
        for key, e in self.entries.items():
            modes = self.modes.get(key[0], set())
            if e["fate"] not in RULED:
                who = None
            elif key in advised:
                who = "advice"
            elif key in named:
                who = "operator"
            elif key in on_sheet:
                who = "sheet"
            elif modes and modes <= {"direct", "blanket-close"}:
                who = "operator"
            else:
                who = "unclear" if modes else "uncoded"
            e["who"] = who
        self._routes: dict = {}

    # the label data
    @functools.cached_property
    def labels(self) -> dict:
        """The first pass: kind, trigger, impact, fix, sensitive, basis."""
        raw = json.loads(LABELS_DATA.read_text(encoding="utf-8"))["labels"]
        return {(_key_of(name), i): lab for name, data in raw.items() for i, lab in data.items()}

    @functools.cached_property
    def label_reports(self) -> int:
        return len(json.loads(LABELS_DATA.read_text(encoding="utf-8"))["labels"])

    @functools.cached_property
    def improvement(self) -> dict:
        """The second pass: the potential improvements."""
        raw = json.loads(IMPROVEMENT_DATA.read_text(encoding="utf-8"))["labels"]
        return {tuple(k.split(" ")): v for k, v in raw.items()}

    @functools.cached_property
    def signal_labels(self) -> dict:
        """The third pass: signal and basis."""
        raw = json.loads(SIGNAL_DATA.read_text(encoding="utf-8"))["labels"]
        return {tuple(k.split(" ")): v for k, v in raw.items()}

    @functools.cached_property
    def signal(self) -> dict:
        return {k: v["signal"] for k, v in self.signal_labels.items()}

    @functools.cached_property
    def handed(self) -> list[tuple]:
        """(key, first-pass labels, entry) of every labelled entry handed over."""
        return [(k, lab, self.entries[k]) for k, lab in self.labels.items()
                if k in self.entries and self.entries[k]["fate"] != "in-run"]

    @functools.cached_property
    def own(self) -> list[tuple]:
        """The handed-over entries the operator ruled themselves: § 3.4's 234."""
        return [x for x in self.handed if x[2]["fate"] in RULED and x[2]["who"] == "operator"]

    # the routes
    def tool_entry(self, k: tuple, signal: bool = True) -> dict | None:
        """The entry as the tool would store it, its labels mapped onto the tool's vocabulary;
        None for an improvement of the workflow, which the tool refuses (it is Fieldnotes').
        Without ``signal`` a fix-family entry carries none, which the table takes as `unknown`:
        row 8 as it stood before the amendment."""
        co = _close_out()
        e = self.entries[k]
        grade = e["severity"] if e["severity"] in co.SEVERITIES else None
        if k in self.improvement:
            il = self.improvement[k]
            if il["benefit"] == "workflow":
                return None
            labels = {"benefit": il["benefit"], "felt": _tool_value("felt", il["felt"]),
                      "change": il["change"], "size": il["size"],
                      "product-call": il["product_call"],
                      "prevents": _tool_value("prevents", il["prevents"])}
            return {"id": k[1], "kind": "improvement", "grade": grade, "labels": labels}
        lab = self.labels[k]
        labels = {"trigger": _tool_value("trigger", lab["trigger"]),
                  "impact": _tool_value("impact", lab["impact"])}
        if signal:
            labels["signal"] = self.signal.get(k, "unknown")
        fix = _tool_value("fix", lab["fix"])
        if fix:
            labels["fix"] = fix
        if lab["sensitive"] in ("yes", "no"):
            labels["area"] = "sensitive" if lab["sensitive"] == "yes" else "plain"
        if lab["kind"] == "slice-input":
            labels["for"] = "999"       # a slice still to run; which one does not route
        return {"id": k[1], "kind": _tool_value("kind", lab["kind"]), "grade": grade,
                "labels": labels}

    def route(self, k: tuple, signal: bool = True) -> str:
        """The route the plugin's table gives the entry, every repository taken as the slice's
        own: with the third pass's signal, § 4.3 as amended (§ 3.10); without, as ruled
        (§ 3.9). The 89 potential improvements go by the second pass's labels."""
        if (k, signal) not in self._routes:
            entry = self.tool_entry(k, signal)
            if entry is None:
                name = "to Fieldnotes"
            else:
                key, _ = _close_out().route(entry, None)
                name = _ROUTE_NAME.get(key) or ("closed" if key.startswith("closed:") else key)
            self._routes[(k, signal)] = name
        return self._routes[(k, signal)]

    def variant(self, name: str, k: tuple) -> str:
        """§ 3.10's rules. `as ruled` and `loud is closed` are the tool's table without and with
        the signal; `silent is not closed` and `both` were tried and not built — this tool's
        own: what the table closes and is silent goes to the wrap-up to fix or card."""
        if name == "as ruled":
            return self.route(k, signal=False)
        if name == "loud is closed":
            return self.route(k)
        base = self.route(k, signal=(name == "both"))
        return FIX_OR_CARD if base == "closed" and self.signal.get(k) == "silent" else base


def _fates_line(es: list[dict]) -> str:
    c = Counter(e["fate"] for e in es)
    n = len(es)
    return (f"{n:>4}  progressed {_pct(c['card'] + c['fix'] + c['fold'], n):>5}   "
            f"carded or folded {_pct(c['card'] + c['fold'], n):>5}   fixed {_pct(c['fix'], n):>5}"
            f"   closed {_pct(c['close'], n):>5}")


def _kept(routes: list[tuple[dict, str]]) -> tuple[str, list]:
    """Picks kept, cards and folds kept, the share closed — of (entry, route) pairs; and the
    picks the routes close."""
    closed = [(e, r) for e, r in routes if r in ("closed", "the record", "close", "record")]
    picks = [e for e, _ in routes if e["progressed"]]
    cards = [e for e, _ in routes if e["fate"] in ("card", "fold")]
    lost = [e for e, _ in closed if e["progressed"]]
    lost_cards = [e for e in lost if e["fate"] in ("card", "fold")]
    return (f"picks kept {len(picks) - len(lost)}/{len(picks)} "
            f"({_pct(len(picks) - len(lost), len(picks))}); cards and folds kept "
            f"{len(cards) - len(lost_cards)}/{len(cards)} "
            f"({_pct(len(cards) - len(lost_cards), len(cards))}); closed "
            f"{len(closed)} ({_pct(len(closed), len(routes))})"), lost


def _route_table(routes: list[tuple[dict, str]], order) -> None:
    print(f"  {'route':<56}{'n':>4}{'':>6}{'closed':>8}{'fixed':>7}{'carded':>8}{'folded':>8}")
    for rt in order:
        c = Counter(e["fate"] for e, r in routes if r == rt)
        m = sum(c.values())
        if m or rt in ORDER:
            print(f"  {rt:<56}{m:>4}{_pct(m, len(routes)):>6}{c['close']:>8}{c['fix']:>7}"
                  f"{c['card']:>8}{c['fold']:>8}")


def _spread(handed: list[tuple], route_of, groups) -> None:
    """Over everything handed over: per group, the entries and a report's median and max."""
    per, total = defaultdict(Counter), Counter()
    for k, _, _ in handed:
        g = route_of(k)
        per[k[0]][g] += 1
        total[g] += 1
    print(f"  over everything handed over ({len(handed)} entries, {len(per)} reports)")
    for g in groups:
        xs = [per[r][g] for r in per]
        print(f"    {g:<26}{total[g]:>4} {_pct(total[g], len(handed)):>5}  a report: median "
              f"{statistics.median(xs)}, max {max(xs)}")


# --- § 3.1 the Focus line --------------------------------------------------------------------

def cmd_focus(args) -> int:
    d = Discussion(args.data)
    report_mode = d.read["report_mode"]
    rows, sections = [], []
    for r in d.reports:
        mode = report_mode.get(_report_key(r["project"], r["slice"]), "uncoded")
        for sec in ("B", "S", "Q", "N"):
            es = [e for e in r["entries"] if e["section"] == sec and e["fate"] != "in-run"
                  and _ENTRY_ID.fullmatch(e["id"])]
            if not es:
                continue
            focus = r["focus"].get(sec, "")
            ids = {e["id"] for e in es}
            order: list[str] = []
            for m in re.finditer(r"\b([ANBQS]\d+)\b", focus):
                if m.group(1) in ids and m.group(1) not in order:
                    order.append(m.group(1))
            for e in es:
                e["_pos"] = order.index(e["id"]) if e["id"] in order else None
                e["_own"] = mode in ("direct", "mixed")
                e["_mode"] = mode
                e["_sec"] = sec
            sections.append({"sec": sec, "entries": es, "order": order, "focus": focus,
                             "own": mode in ("direct", "mixed"), "mode": mode})
            rows.extend(e for e in es if e["fate"] in RULED)

    def line(label, es):
        print(f"  {label:<46} {_fates_line(es)}")

    def first(es):
        return [e for e in es if e["_pos"] == 0]

    def later(es):
        return [e for e in es if e["_pos"] not in (None, 0)]

    def unnamed(es):
        return [e for e in es if e["_pos"] is None]

    sheet_modes = ("handed-over", "auto")
    print("§ 3.1 A. Bugs + Suggestions, ruled entries, by place in the Focus line")
    bs = [e for e in rows if e["_sec"] in "BS"]
    line("all", bs)
    line("named first", first(bs))
    line("named second", [e for e in bs if e["_pos"] == 1])
    line("named third or later", [e for e in bs if e["_pos"] is not None and e["_pos"] >= 2])
    line("not named", unnamed(bs))

    print("\nB. The same, split by how the report was ruled")
    for label, sel in (("own reading (direct, mixed)", lambda e: e["_own"]),
                       ("from a sheet (handed-over, auto)", lambda e: e["_mode"] in sheet_modes),
                       ("uncoded", lambda e: e["_mode"] == "uncoded")):
        print(f" {label}")
        sub = [e for e in bs if sel(e)]
        line("all", sub)
        line("named first", first(sub))
        line("named later", later(sub))
        line("not named", unnamed(sub))

    print("\nC. Holding the grade still (Bugs + Suggestions)")
    for sev in ("major", "minor", "", "nit", "cosmetic"):
        sub = [e for e in bs if e["severity"] == sev]
        print(f" grade: {sev or 'ungraded'}")
        line("named first", first(sub))
        line("named later", later(sub))
        line("not named", unnamed(sub))

    print("\nD. Sections where the first pick had a choice: >=2 ruled entries, a first-named "
          "one,\n   and the operator progressed some but not all")
    for label, sel in (("all reports", lambda s: True), ("own reading", lambda s: s["own"]),
                       ("from a sheet", lambda s: s["mode"] in sheet_modes)):
        n = hit = sev_n = 0
        chance = sev_hit = 0.0
        for s in sections:
            if s["sec"] not in "BS" or not sel(s):
                continue
            es = [e for e in s["entries"] if e["fate"] in RULED]
            if len(es) < 2 or not s["order"]:
                continue
            top_pick = next((e for e in es if e["_pos"] == 0), None)
            if top_pick is None:
                continue
            p = sum(e["progressed"] for e in es)
            if p in (0, len(es)):
                continue
            n += 1
            hit += top_pick["progressed"]
            chance += p / len(es)
            top = min(_GRADE_RANK[e["severity"]] for e in es)
            tops = [e for e in es if _GRADE_RANK[e["severity"]] == top]
            if len(tops) < len(es):     # the grade makes a choice too
                sev_n += 1
                sev_hit += sum(e["progressed"] for e in tops) / len(tops)
        print(f"  {label:<14} sections {n:>3}   first pick progressed {_pct(hit, n):>5}   "
              f"a random entry {_pct(chance, n):>5}   the top grade ({sev_n} sections) "
              f"{_pct(sev_hit, sev_n):>5}")

    print("\nE. Sections with at least one entry progressed: where was the operator's pick?")
    for label, sel in (("all reports", lambda s: True), ("own reading", lambda s: s["own"])):
        secs = picks = named_first = named_later = not_named = first_closed = 0
        for s in sections:
            if s["sec"] not in "BS" or not sel(s):
                continue
            es = [e for e in s["entries"] if e["fate"] in RULED]
            pr = [e for e in es if e["progressed"]]
            if not pr or not s["order"]:
                continue
            secs += 1
            picks += len(pr)
            named_first += len(first(pr))
            named_later += len(later(pr))
            not_named += len(unnamed(pr))
            top_pick = next((e for e in es if e["_pos"] == 0), None)
            if top_pick is not None and not top_pick["progressed"]:
                first_closed += 1
        print(f"  {label:<12} sections {secs}, picks {picks}: named first "
              f"{_pct(named_first, picks)}, named later {_pct(named_later, picks)}, not named "
              f"{_pct(not_named, picks)}; first pick closed while another was progressed: "
              f"{first_closed} sections ({_pct(first_closed, secs)})")

    print("\nF. How much the line names")
    live = [e for s in sections if s["sec"] in "BS" for e in s["entries"]]
    named = [e for e in live if e["_pos"] is not None]
    print(f"  B+S live entries {len(live)}, named {len(named)} ({_pct(len(named), len(live))})")
    per = [len(s["order"]) / len(s["entries"]) for s in sections
           if s["sec"] in "BS" and len(s["entries"]) >= 3]
    full = sum(1 for p in per if p >= 0.99)
    print(f"  sections with >=3 live entries: {len(per)}; the line names every entry in {full} "
          f"({_pct(full, len(per))})")
    words = sorted(len(s["focus"].split()) for s in sections if s["sec"] in "BS")
    print(f"  words per B/S Focus line over a non-empty section: median "
          f"{words[len(words) // 2]}, p90 {words[int(len(words) * .9)]}")
    return 0


# --- § 3.2 whose ruling ------------------------------------------------------------------------

_SORT_TO_FATE = {"card": "card", "fix now": "fix", "fold": "fold", "close": "close",
                 "moot": "close"}
_PROPOSES = ("card", "fix now", "fold", "test gaps")


def _sorted_as(d: Discussion, arm: str):
    """(key, bucket) of every entry a sort of the read placed."""
    for rep, items in d.read["sorts"][arm].items():
        for i, bucket in items.items():
            yield (_key_of(rep), i), bucket


def _against_sort(d: Discussion, arm: str, keep, label: str) -> None:
    conf = defaultdict(Counter)
    for k, b in _sorted_as(d, arm):
        e = d.entries.get(k)
        if e and keep(e):
            conf[b][e["fate"]] += 1

    def progressed(buckets):
        return sum(conf[b]["card"] + conf[b]["fix"] + conf[b]["fold"] for b in buckets)

    def count(buckets):
        return sum(sum(conf[b].values()) for b in buckets)

    n = count(conf)
    prog = progressed(conf)
    closing = [b for b in conf if b in ("close", "moot")]
    lost, nclose = progressed(closing), count(closing)
    mapped = [b for b in _SORT_TO_FATE if b in conf]
    exact = sum(conf[b][_SORT_TO_FATE[b]] for b in mapped)
    flagged = [b for b in conf if b in _PROPOSES]
    nfl = count(flagged)
    closed_work = nfl - progressed(flagged)
    print(f"\n  {arm} · {label}: entries {n}, progressed by the operator {prog} "
          f"({_pct(prog, n)})")
    print(f"    the sort closes {nclose} ({_pct(nclose, n)}); of those the operator progressed "
          f"{lost} ({_pct(lost, nclose)})")
    print(f"    picks kept {prog - lost}/{prog} ({_pct(prog - lost, prog)});  exact disposition "
          f"{exact}/{count(mapped)} ({_pct(exact, count(mapped))})")
    print(f"    proposes work (card, fix now, fold, test gaps) {nfl}; the operator closed "
          f"{closed_work} of them ({_pct(closed_work, nfl)})")
    print(f"    {'':<12}{'n':>4}{'close':>7}{'fix':>6}{'card':>6}{'fold':>6}")
    for b in ("card", "fix now", "fold", "test gaps", "needs-eyes", "action", "close", "moot"):
        c = conf[b]
        if sum(c.values()):
            print(f"    {b:<12}{sum(c.values()):>4}{c['close']:>7}{c['fix']:>6}{c['card']:>6}"
                  f"{c['fold']:>6}")


def cmd_who(args) -> int:
    d = Discussion(args.data)
    ent = d.entries
    print("§ 3.2 A. Whose ruling (entries ruled, all kinds)")
    for who in ("operator", "advice", "sheet", "unclear", "uncoded"):
        es = [e for e in ent.values() if e["who"] == who]
        c = Counter(e["fate"] for e in es)
        n = len(es)
        print(f"  {who:<9} {n:>4}  progressed {_pct(c['card'] + c['fix'] + c['fold'], n):>5}  "
              f"card {_pct(c['card'], n):>5} fix {_pct(c['fix'], n):>5} fold "
              f"{_pct(c['fold'], n):>5} close {_pct(c['close'], n):>5}")
    print("  by mode of the report, 'unclear':",
          dict(Counter(tuple(sorted(d.modes[e["_rep"]]))
                       for e in ent.values() if e["who"] == "unclear")))

    print("\nB. The sorts against the operator's own rulings only, and against sheet rulings")
    for arm in ("heldout-v1", "heldout-v2"):
        _against_sort(d, arm, lambda e: e["who"] == "operator", "operator's own rulings")
    for arm in ("heldout-v1", "heldout-v2"):
        _against_sort(d, arm, lambda e: e["who"] == "sheet", "rulings taken from a sheet")
    _against_sort(d, "heldout-v2", lambda e: e["who"] == "advice",
                  "entries the operator asked advice on")
    _against_sort(d, "sample-v1", lambda e: e["who"] == "operator", "operator's own rulings")

    print("\nC. What the rules were derived from: the picks the current rules lost on the 55 "
          "sample reports")
    lost = Counter(ent[k]["who"] for k, b in _sorted_as(d, "sample-v1")
                   if k in ent and ent[k]["fate"] in ("card", "fix", "fold")
                   and b in ("close", "moot"))
    print("  ", dict(lost))
    held = Counter(tuple(sorted(d.modes.get(_key_of(rep), {"uncoded"})))
                   for rep in d.read["sorts"]["heldout-v2"])
    print("  held-out reports by mode:", dict(held))

    print("\nD. Direct-mode reports only (every ruling the operator's, blanket closes included)")
    direct = {k for k, v in d.modes.items() if v <= {"direct"}}
    es = [e for e in ent.values() if e["_rep"] in direct and e["fate"] in RULED]
    c = Counter(e["fate"] for e in es)
    print(f"  reports {len(direct)}, entries ruled {len(es)}: progressed "
          f"{_pct(c['card'] + c['fix'] + c['fold'], len(es))}, card {_pct(c['card'], len(es))}, "
          f"fix {_pct(c['fix'], len(es))}, fold {_pct(c['fold'], len(es))}, close "
          f"{_pct(c['close'], len(es))}")
    bs = [e for e in es if e["section"] in "BS"]
    c = Counter(e["fate"] for e in bs)
    print(f"  Bugs+Suggestions {len(bs)}: progressed "
          f"{_pct(c['card'] + c['fix'] + c['fold'], len(bs))}")
    op = [e for e in ent.values() if e["who"] == "operator"]
    print(f"  the 'operator' set: {sum(e['_rep'] in direct for e in op)} in direct reports, "
          f"{sum(e['_rep'] not in direct for e in op)} named in mixed or handed-over reports")
    for arm in ("sample-v1", "heldout-v1", "heldout-v2"):
        conf = defaultdict(Counter)
        reps = set()
        for k, b in _sorted_as(d, arm):
            e = ent.get(k)
            if e and e["_rep"] in direct and e["fate"] in RULED:
                conf[b][e["fate"]] += 1
                reps.add(k[0])
        n = sum(sum(c.values()) for c in conf.values())
        prog = sum(c["card"] + c["fix"] + c["fold"] for c in conf.values())
        closing = [b for b in conf if b in ("close", "moot")]
        wrong = sum(conf[b]["card"] + conf[b]["fix"] + conf[b]["fold"] for b in closing)
        nclose = sum(sum(conf[b].values()) for b in closing)
        flagged = [b for b in conf if b in _PROPOSES]
        nfl = sum(sum(conf[b].values()) for b in flagged)
        flp = sum(conf[b]["card"] + conf[b]["fix"] + conf[b]["fold"] for b in flagged)
        print(f"  {arm}: reports {len(reps)}, entries {n}, picks {prog}; closes {nclose} "
              f"({_pct(nclose, n)}), wrongly {wrong} ({_pct(wrong, nclose)}); kept "
              f"{prog - wrong}/{prog} ({_pct(prog - wrong, prog)}); proposes work {nfl}, "
              f"operator closed {nfl - flp} ({_pct(nfl - flp, nfl)})")

    print("\nE. Entries the operator asked advice on, corpus-wide: what the sheets and the sorts "
          "made of them")
    adv = [e for e in ent.values() if e["who"] == "advice"]
    print("  fates:", dict(Counter(e["fate"] for e in adv)),
          " grades:", dict(Counter(e["severity"] or "ungraded" for e in adv)),
          " kinds:", dict(Counter(e["section"] for e in adv)))
    sorted_as = Counter((arm, b) for arm in ("sample-v1", "heldout-v2")
                        for k, b in _sorted_as(d, arm)
                        if k in ent and ent[k]["who"] == "advice")
    print("  sorted as:", dict(sorted_as))
    return 0


# --- § 3.3, § 3.4 the labels, and the tables tried before the severity ruling --------------

_VOCAB = {
    "kind": {"action", "event", "question", "idea", "prose", "test-gap", "defect", "hardening",
             "cleanup", "slice-input"},
    "trigger": {"normal-use", "ordinary-condition", "fault-or-coincidence", "future-change",
                "none", "unknown"},
    "impact": {"wrong-or-lost", "broken-or-stuck", "misleading", "none-observable", "unknown"},
    "fix": {"one-edit", "known-several", "design", "unknown", "na"},
    "sensitive": {"yes", "no", "na"},
    "basis": {"stated", "partly", "inferred"},
}
_BULLETS = ("yours: action", "yours: decide", "sweep: fix", "sweep: fix or card",
            "sweep: investigate", "fold", "close", "record")
_BEFORE_D9 = ("to the operator: an action", "to the operator: a decision",
              "to the operator: severe, or graded major", "to the wrap-up: fix",
              "to the wrap-up: fix, or ask for a card", "to the wrap-up: look",
              "input for a later slice", "closed", "the record")


def _easy(lab: dict) -> bool:
    return lab["fix"] in ("one-edit", "known-several") and lab["sensitive"] != "yes"


def _severe_replay(lab: dict, e: dict) -> bool:
    """The replay's severe: the wide label `wrong-or-lost` with a trigger, or graded major."""
    return (lab["impact"] == "wrong-or-lost" and lab["trigger"] != "none") \
        or e["severity"] == "major"


def _route_bullets(lab: dict) -> str:
    """§ 3.4's first table, tried and not built: the operator's three bullets as stated."""
    k = lab["kind"]
    if k == "action":
        return "yours: action"
    if k == "event":
        return "record"
    if k in ("question", "idea"):
        return "yours: decide"
    if k == "slice-input":
        return "fold"
    if k == "prose" or _easy(lab):
        return "sweep: fix"
    if lab["trigger"] == "unknown" or lab["impact"] == "unknown":
        return "sweep: investigate"
    if lab["trigger"] in ("normal-use", "ordinary-condition") \
            and lab["impact"] != "none-observable":
        return "sweep: fix or card"
    return "close"


def _route_before_d9(lab: dict, e: dict, severe_first: bool) -> str:
    """§ 3.4's second and third tables, tried and not built: impact in the rule, an event that
    describes a problem routed as that problem, what is severe kept from the close — and, with
    ``severe_first``, placed ahead of the easy fix (D9's default before the operator ruled)."""
    k = lab["kind"]
    if k == "action":
        return _BEFORE_D9[0]
    if k in ("question", "idea"):
        return _BEFORE_D9[1]
    problem = lab["impact"] != "none-observable" and lab["trigger"] != "none"
    if k == "event" and not problem:
        return _BEFORE_D9[8]
    if severe_first and _severe_replay(lab, e):
        return _BEFORE_D9[2]
    if k == "slice-input":
        return _BEFORE_D9[6]
    if k == "prose" or _easy(lab):
        return _BEFORE_D9[3]
    if "unknown" in (lab["trigger"], lab["impact"]):
        return _BEFORE_D9[5]
    if lab["trigger"] in ("normal-use", "ordinary-condition") \
            and lab["impact"] != "none-observable":
        return _BEFORE_D9[4]
    return _BEFORE_D9[2] if _severe_replay(lab, e) else _BEFORE_D9[7]


def cmd_labels(args) -> int:
    d = Discussion(args.data)
    bad = Counter(f"{a}={lab.get(a)}" for lab in d.labels.values()
                  for a, vs in _VOCAB.items() if lab.get(a) not in vs)
    print(f"§ 3.3 label reports {d.label_reports}, entries labelled {len(d.labels)}, matched to "
          f"the corpus {sum(k in d.entries for k in d.labels)}; off-vocabulary: {dict(bad)}")
    handed = d.handed
    print(f"handed over {len(handed)}")
    moot = {k for k, b in _sorted_as(d, "heldout-v2") if b == "moot"}

    def matrix(title, sel):
        sub = [(k, lab, e) for k, lab, e in handed if e["fate"] in RULED and sel(k, e)]
        print(f"\n{title}: entries ruled {len(sub)}, progressed "
              f"{_pct(sum(e['progressed'] for _, _, e in sub), len(sub))}")
        print(f"  {'route':<20}{'n':>4}{'share':>7}{'closed':>8}{'fixed':>7}{'carded':>8}"
              f"{'folded':>8}")
        for rt in _BULLETS:
            c = Counter(e["fate"] for _, lab, e in sub if _route_bullets(lab) == rt)
            n = sum(c.values())
            if n:
                print(f"  {rt:<20}{n:>4}{_pct(n, len(sub)):>7}{c['close']:>8}{c['fix']:>7}"
                      f"{c['card']:>8}{c['fold']:>8}")
        routes = [(e, _route_bullets(lab)) for _, lab, e in sub]
        closed = [e for e, r in routes if r in ("close", "record")]
        lost = [e for e in closed if e["progressed"]]
        lost_cards = [e for e in closed if e["fate"] in ("card", "fold")]
        print(f"  the table closes {len(closed)} ({_pct(len(closed), len(sub))}); of those the "
              f"operator progressed {len(lost)} ({_pct(len(lost), len(closed))}), carded or "
              f"folded {len(lost_cards)}")
        print("  " + _kept(routes)[0])
        return sub

    print("\nThe first table of § 3.4 (the three bullets as stated), by who ruled")
    own = matrix("A. The operator's own rulings", lambda k, e: e["who"] == "operator")
    matrix("A2. … without entries already fixed in the run (where known)",
           lambda k, e: e["who"] == "operator" and k not in moot)
    matrix("B. Entries the operator asked advice on", lambda k, e: e["who"] == "advice")
    matrix("C. Rulings taken from a sheet or handed over",
           lambda k, e: e["who"] in ("sheet", *REST))

    print("\nD. Each label against the operator's own rulings (§ 3.3's table)")
    for a in ("kind", "trigger", "impact", "fix", "sensitive", "basis"):
        print(f"  {a}")
        for v in sorted(_VOCAB[a]):
            s = [e for _, lab, e in own if lab.get(a) == v]
            if s:
                print(f"    {v:<22}{_fates_line(s)}")

    print("\nE. What reaches the operator, per report (all handed-over entries of the labelled "
          "reports), by the first table")
    per = defaultdict(Counter)
    for k, lab, _ in handed:
        rt = _route_bullets(lab)
        grp = ("yours" if rt.startswith("yours")
               else "sweep" if rt.startswith("sweep") or rt == "fold" else "closed or record")
        per[k[0]][grp] += 1
    for grp in ("yours", "sweep", "closed or record"):
        xs = [per[r][grp] for r in per]
        print(f"  {grp:<18} total {sum(xs):>4} ({_pct(sum(xs), len(handed))}), per report "
              f"median {statistics.median(xs)}, max {max(xs)}")
    unknown = [x for x in handed if "unknown" in (x[1]["trigger"], x[1]["impact"])]
    basis = Counter(lab["basis"] for _, lab, _ in handed)
    print(f"  trigger or impact unknown: {len(unknown)} ({_pct(len(unknown), len(handed))}); "
          f"basis: {dict(basis)}; stated {_pct(basis['stated'], len(handed))}")
    advice = [x for x in handed if x[2]["fate"] in RULED and x[2]["who"] == "advice"]
    print(f"  asked advice on {len(advice)}, of which trigger or impact unknown "
          f"{sum('unknown' in (lab['trigger'], lab['impact']) for _, lab, _ in advice)}")
    kinds = Counter(lab["kind"] for _, lab, e in handed if e["section"] == "S")
    n_s = sum(kinds.values())
    as_bug = kinds["prose"] + kinds["test-gap"] + kinds["defect"]
    better = kinds["idea"] + kinds["hardening"] + kinds["cleanup"]
    print(f"  Suggestions handed over {n_s}: prose, test gap or defect {as_bug} "
          f"({_pct(as_bug, n_s)}); idea, hardening or cleanup {better} ({_pct(better, n_s)}); "
          f"input for a later slice {kinds['slice-input']}; question {kinds['question']}")
    labelled_better = Counter(e["fate"] for _, lab, e in own
                              if lab["kind"] in ("idea", "hardening", "cleanup"))
    print(f"  the operator's own rulings labelled idea, hardening or cleanup "
          f"{sum(labelled_better.values())}: carded or folded "
          f"{labelled_better['card'] + labelled_better['fold']}, fixed {labelled_better['fix']}, "
          f"closed {labelled_better['close']}")

    if args.misses:
        print("\nF. The operator's own cards and folds that the first table closes")
        for k, lab, e in own:
            if _route_bullets(lab) in ("close", "record") and e["fate"] in ("card", "fold"):
                print(f"  {k[0]} {k[1]:<4} [{e['fate']}] {e['severity'] or '-':<6} "
                      f"{lab['kind']}/{lab['trigger']}/{lab['impact']}/{lab['fix']}/"
                      f"{lab['sensitive']}")

    print("\n§ 3.4 The three tables tried before the operator ruled on severity (not built; "
          "§ 3.9 has the table as ruled), against the operator's own rulings")
    tables = (("the three bullets as stated",
               lambda lab, e: {"yours: action": "action", "record": "record",
                               "close": "close"}.get(_route_bullets(lab), "kept")),
              ("impact in the rule; events by their problem",
               lambda lab, e: _route_before_d9(lab, e, False)),
              ("… and severe ahead of the easy fix",
               lambda lab, e: _route_before_d9(lab, e, True)))
    for name, fn in tables:
        print(f"  {name:<46} {_kept([(e, fn(lab, e)) for _, lab, e in own])[0]}")
    last = {k: _route_before_d9(lab, e, True) for k, lab, e in handed}
    print(f"\nThe last table, by route ({len(own)} entries, "
          f"{sum(e['progressed'] for _, _, e in own)} picks)")
    _route_table([(e, last[k]) for k, _, e in own], _BEFORE_D9)
    print()
    _spread(handed, lambda k: _group(last[k]),
            ("comes to the operator", "goes to the wrap-up", "input for a later slice",
             "closed", "the record"))
    sheet = [(e, last[k]) for k, _, e in handed if e["fate"] in RULED
             and e["who"] in ("sheet", *REST)]
    text, lost = _kept(sheet)
    closes = sum(r in ("closed", "the record") for _, r in sheet)
    print(f"  rulings taken from a sheet or handed over ({len(sheet)}): {text}; of what it "
          f"closes progressed {_pct(len(lost), closes)}")
    ideas = sum(1 for _, lab, _ in handed if lab["kind"] == "idea")
    print(f"  ideas sent to the operator as a decision, all reports: {ideas}")
    return 0


# --- § 3.8 the potential improvements ------------------------------------------------------

_HYPOTHETICAL = ("after-a-change", "after-an-incident", "not-observable")


def _improvement_proposed(lab: dict) -> str:
    """§ 3.8's first proposed treatment, tried and not built."""
    if lab["prevents"] == "severe":
        return "to the operator: severe"
    if lab["benefit"] == "workflow":
        return "fieldnotes"
    felt_now = lab["felt"] in ("every-use", "some-uses")
    grounded = lab["ground"] in ("met-in-run", "left-by-slice")
    known = lab["size"] in ("one-edit", "several-places")
    if lab["ground"] == "left-by-slice" and lab["change"] in ("remove", "adjust") and known \
            and lab["product_call"] == "no":
        return "wrap-up: does it"
    if felt_now and (grounded or lab["product_call"] == "yes"):
        return "to the operator"
    return "closed"


# § 3.8's simpler rules, tried: `keep` is not closed by the rule. The last is § 4.4's rows 3–4.
_IMPROVEMENT_RULES = (
    ("felt in use, or prevents severe",
     lambda lab: lab["felt"] in ("every-use", "some-uses") or lab["prevents"] == "severe"),
    ("felt in use, or grounded, or severe",
     lambda lab: lab["felt"] in ("every-use", "some-uses")
     or lab["ground"] in ("met-in-run", "left-by-slice") or lab["prevents"] == "severe"),
    ("close only what is hypothetical and adds",
     lambda lab: not (lab["felt"] in _HYPOTHETICAL and lab["change"] == "add"
                      and lab["prevents"] != "severe")),
)


def cmd_improvements(args) -> int:
    d = Discussion(args.data)
    rows = [(k, lab, d.entries[k]) for k, lab in d.improvement.items() if k in d.entries]
    ruled = [r for r in rows if r[2]["fate"] in RULED]
    own = [r for r in ruled if r[2]["who"] in ("operator", "advice")]
    print(f"§ 3.8 labelled {len(d.improvement)}, matched {len(rows)}, ruled {len(ruled)}, the "
          f"operator's own rulings (advice included) {len(own)}; Suggestions among the "
          f"labelled {sum(e['section'] == 'S' for _, _, e in rows)}")

    def row(label, es, indent=2):
        if es:
            print(f"{' ' * indent}{label:<40}{_fates_line([r[2] for r in es])}")

    for title, es in (("A. the operator's own rulings", own), ("B. all rulings", ruled)):
        print(f"\n{title}")
        row("all", es)
        for a in ("benefit", "felt", "ground", "change", "size", "product_call", "prevents"):
            print(f"  {a}")
            for v, _ in Counter(r[1][a] for r in es).most_common():
                row(f"{v}", [r for r in es if r[1][a] == v], 4)
            if a == "felt":
                row("in use (every-use + some-uses)",
                    [r for r in es if r[1][a] in ("every-use", "some-uses")], 4)

    print("\nC. § 4.4's routes — the tool's table — against the operator's own rulings")
    routes = [(e, d.route(k)) for k, _, e in own]
    _route_table(routes, ("to Fieldnotes", "to the wrap-up: a potential improvement", RISK,
                          "closed", "to the operator: a potential improvement"))
    print("  " + _kept(routes)[0])
    print("  over all", len(rows), "labelled:", dict(Counter(d.route(k) for k, _, _ in rows)))
    unfelt = [r for r in ruled if not _IMPROVEMENT_RULES[2][1](r[1])]
    progressed = [r for r in unfelt if r[2]["progressed"]]
    print(f"  adds something for a benefit not felt in use, prevents nothing severe: own rulings "
          f"{sum(r in own for r in unfelt)}, progressed "
          f"{sum(r in own for r in progressed)}; all rulings {len(unfelt)}, progressed "
          f"{len(progressed)}, by {dict(Counter(r[2]['who'] for r in progressed))}")

    print("\nD. Tried and not built: the first proposed treatment, against the operator's own "
          "rulings")
    for rt in ("to the operator: severe", "to the operator", "wrap-up: does it", "fieldnotes",
               "closed"):
        row(rt, [r for r in own if _improvement_proposed(r[1]) == rt])
    closed = [r for r in own if _improvement_proposed(r[1]) == "closed"]
    picks = [r for r in own if r[2]["progressed"]]
    lost = [r for r in closed if r[2]["progressed"]]
    print(f"  closes {len(closed)} of {len(own)} ({_pct(len(closed), len(own))}); of those "
          f"progressed {len(lost)}; picks kept {len(picks) - len(lost)}/{len(picks)} "
          f"({_pct(len(picks) - len(lost), len(picks))})")
    print(f"  over all {len(rows)} handed over:",
          dict(Counter(_improvement_proposed(r[1]) for r in rows)))
    print("  the simpler rules (keep = not closed by the rule)")
    for name, keep in _IMPROVEMENT_RULES:
        cl = [r for r in own if not keep(r[1])]
        lo = [r for r in cl if r[2]["progressed"]]
        print(f"  {name:<44} closes {len(cl):>3} ({_pct(len(cl), len(own))}), of which "
              f"progressed {len(lo)} ({_pct(len(lo), len(cl))}); picks kept "
              f"{_pct(len(picks) - len(lo), len(picks))}")

    if args.misses:
        print("\nE. picks § 4.4 closes")
        for k, lab, e in own:
            if d.route(k) == "closed" and e["progressed"]:
                print(f"  {k[0]} {k[1]:<4} [{e['fate']}] {lab['benefit']}/{lab['felt']}/"
                      f"{lab['ground']}/{lab['change']}/{lab['size']}/"
                      f"pc={lab['product_call']}/{lab['prevents']}")
    return 0


# --- § 3.9, § 3.5 the tables as ruled ------------------------------------------------------

def cmd_tables(args) -> int:
    d = Discussion(args.data)
    own, handed = d.own, d.handed
    print(f"§ 3.9 labelled and handed over {len(handed)}; the operator's own rulings "
          f"{len(own)}\n")
    routes = [(e, d.route(k, signal=False)) for k, _, e in own]
    _route_table(routes, ORDER)
    text, lost = _kept(routes)
    print(f"\n{text}")
    print("the misses (§ 3.5):")
    lost = {id(e) for e in lost}
    for k, lab, e in own:
        if id(e) in lost:
            print(f"  {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<6} "
                  f"{lab['kind']} / {lab['trigger']} / {lab['impact']} / {lab['fix']}")
    print()
    _spread(handed, lambda k: _group(d.route(k, signal=False)), GROUPS)

    # D7: the closes whose impact breaks a flow
    def breaks(k, lab):
        return k not in d.improvement and lab["impact"] == "broken-or-stuck"

    cl_own = [(k, lab, e) for k, lab, e in own if d.route(k, signal=False) == "closed"]
    br_own = [x for x in cl_own if breaks(x[0], x[1])]
    cl_all = [(k, lab, e) for k, lab, e in handed if d.route(k, signal=False) == "closed"]
    br_all = [x for x in cl_all if breaks(x[0], x[1])]
    reports = len({k[0] for k, _, _ in handed})
    print(f"\nD7: closes on own rulings {len(cl_own)}, breaking a flow {len(br_own)}, lost cards "
          f"among them {sum(1 for x in br_own if x[2]['fate'] in ('card', 'fold'))}; over all "
          f"reports {len(br_all)} of {len(cl_all)}, {len(br_all) / reports:.1f} a report")

    # note 26: what the severity ruling (D9) moved; severe first is this tool's, not built
    def severe(k, lab, e):
        if k in d.improvement:
            return d.improvement[k]["prevents"] == "severe" or e["severity"] == "major"
        return _severe_replay(lab, e)

    def severe_first(k, lab, e):
        base = d.route(k, signal=False)
        if severe(k, lab, e) and base in (ORDER[4], ORDER[5], FIX_OR_CARD, ORDER[7], ORDER[8]):
            return RISK
        return base

    first = sum(_group(severe_first(k, lab, e)) == GROUPS[0] for k, lab, e in handed)
    ruled = sum(_group(d.route(k, signal=False)) == GROUPS[0] for k, _, _ in handed)
    moved = Counter(d.route(k, signal=False) for k, lab, e in handed
                    if severe_first(k, lab, e) != d.route(k, signal=False))
    print(f"severity first, then the table (D9's default, not built): {first} come to the "
          f"operator, {ruled} as ruled; what is severe or graded major the ruling leaves where "
          f"the table sends it: {dict(moved)}")
    wrap_own = Counter(e["fate"] for e, r in routes if _group(r) == GROUPS[1])
    print(f"the wrap-up's among the operator's own rulings: {sum(wrap_own.values())}, fixed "
          f"{wrap_own['fix']}, carded or folded {wrap_own['card'] + wrap_own['fold']}, closed "
          f"{wrap_own['close']}")
    return 0


# --- § 3.10 the signal ------------------------------------------------------------------------

_SIGNALS = ("silent", "loud", "unknown")
_VARIANTS = ("as ruled", "silent is not closed", "loud is closed", "both")


def cmd_signal(args) -> int:
    d = Discussion(args.data)
    signal = d.signal

    def row(name, es):
        print(f"  {name:<48}{_fates_line(es)}")

    def rows(title, es):
        print(f"   {title}")
        for v in _SIGNALS:
            row(v, [e for k, _, e in es if signal[k] == v])

    own = [x for x in d.own if x[0] in signal]
    fixes = [x for x in own if x[0] not in d.improvement]
    basis = Counter(v["basis"] for v in d.signal_labels.values())
    print(f"§ 3.10 labelled {len(signal)}: {dict(Counter(signal.values()))}; basis "
          f"{dict(basis)} (stated {_pct(basis['stated'], len(signal))})")
    print(f"of the operator's own rulings {len(own)} carry the label\n")

    print("A. the label against the operator's own rulings")
    rows("every labelled entry", own)
    rows("what should be fixed: a defect, a test gap, an event that describes a problem", fixes)
    rows("… defects", [x for x in fixes if x[1]["kind"] == "defect"])
    rows("… test gaps, by what they would prevent",
         [x for x in fixes if x[1]["kind"] == "test-gap"])
    rows("potential improvements, by what they would prevent",
         [x for x in own if x[0] in d.improvement])
    rows("what should be fixed, an easy fix (the policy's first two bullets)",
         [x for x in fixes if _easy(x[1])])
    rows("what should be fixed, not an easy fix (its third bullet)",
         [x for x in fixes if not _easy(x[1])])

    print("\nB. rulings that are not the operator's own: a sheet's, a handed-over rest")
    rest = [(k, lab, e) for k, lab, e in d.handed
            if e["fate"] in RULED and e["who"] in ("sheet", *REST) and k in signal]
    rows("every labelled entry", rest)

    print("\nC. the routes of the table as ruled (§ 3.9), split by the label — own rulings")
    for r in ORDER:
        for v in _SIGNALS:
            es = [e for k, _, e in own if d.route(k, signal=False) == r and signal[k] == v]
            if es:
                row(f"{r[:38]} / {v}", es)

    print("\nD. the row that fixes or asks for a card, by the label — every ruling, whoever "
          "ruled")
    ruled = [(k, lab, e) for k, lab, e in d.handed if e["fate"] in RULED and k in signal
             and d.route(k, signal=False) == FIX_OR_CARD]
    for who in ("operator", "advice", "sheet", "other"):
        whos = REST if who == "other" else (who,)
        for v in _SIGNALS:
            es = [e for k, _, e in ruled if e["who"] in whos and signal[k] == v]
            if es:
                row(f"{who} / {v}", es)
    for v in _SIGNALS:
        row(f"all / {v}", [e for k, _, e in ruled if signal[k] == v])
    for v in _SIGNALS:
        row(f"all, on an ordinary condition / {v}",
            [e for k, lab, e in ruled if signal[k] == v and lab["trigger"] == "ordinary-condition"])

    print(f"\nE. the table with the label in it, against the {len(d.own)} rulings of § 3.9 — "
          "`as ruled` and `loud is closed` are the tool's table, the other two were tried")
    for name in _VARIANTS:
        routes = [(e, d.variant(name, k)) for k, _, e in d.own]
        text, lost = _kept(routes)
        print(f"\n  {name}: {text}")
        if name == "loud is closed":
            _route_table(routes, ORDER)
        _spread(d.handed, lambda k, name=name: _group(d.variant(name, k)), GROUPS)
        if args.misses:
            lost = {id(e) for e in lost}
            for k, lab, e in d.own:
                if id(e) in lost:
                    print(f"    lost: {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<6} "
                          f"{lab['kind']} / {lab['trigger']} / {lab['impact']} / {lab['fix']} / "
                          f"{signal.get(k, '-')}")

    # the entries the amendment moves; D7's closes are those that rest on the trigger
    moved = [(k, lab, e) for k, lab, e in d.handed
             if d.route(k) != d.route(k, signal=False)]
    cl = [x for x in d.handed if d.route(x[0]) == "closed"]
    new = [x for x in cl if d.route(x[0], signal=False) != "closed"]
    reports = len({k[0] for k, _, _ in d.handed})
    print(f"\nF. the amendment moves {len(moved)} entries ({len(moved) / reports:.1f} a report): "
          f"{dict(Counter(d.route(k) for k, _, _ in moved))}; of those ruled "
          f"{dict(Counter(e['fate'] for _, _, e in moved if e['fate'] in RULED))}, the "
          f"operator's own "
          f"{dict(Counter(e['fate'] for _, _, e in moved if e['who'] == 'operator'))}")
    print(f"   closes over all reports {len(cl)}, of which on the label {len(new)} "
          f"({len(new) / reports:.1f} a report); breaking a flow among those "
          f"{sum(1 for x in new if x[1]['impact'] == 'broken-or-stuck')}")

    if args.list:
        print("\nG. the entries of the row, own rulings")
        for k, lab, e in d.own:
            if d.route(k, signal=False) == FIX_OR_CARD:
                print(f"  {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<8} "
                      f"{signal.get(k, '-'):<8} {lab['kind']} / {lab['trigger']} / "
                      f"{lab['impact']} / {lab['fix']} -> {d.route(k)}")
    return 0


# --- § 3.6 the appended phase --------------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _phase_time(state: dict) -> dict:
    t = defaultdict(float)
    for h in state.get("history", []):
        t[str(h.get("phase"))] += h.get("duration_s") or 0
    return t


def cmd_appended(args) -> int:
    slices = []
    for repo in args.repos:
        project = Path(repo).name.removesuffix("Specs")
        for folder in sorted(p for p in (Path(repo) / "slices" / "completed").iterdir()
                             if p.is_dir()):
            state = _read_json(folder / "state.json")
            if state is None:
                continue
            consults = [(p.name, c) for p in sorted(folder.glob("consult_*.json"))
                        if (c := _read_json(p)) is not None]
            tests = [(p.name, t) for p in sorted(folder.glob("test_phase_result_r*.json"))
                     if (t := _read_json(p)) is not None]
            slices.append({"proj": project, "dir": folder, "name": folder.name, "s": state,
                           "consults": consults, "tests": tests})

    print("§ 3.6 slices with a state.json:", len(slices), dict(Counter(x["proj"] for x in slices)))
    print(" generations spent:", dict(Counter(x["s"].get("generation") for x in slices)))
    print(" consult outcomes:",
          dict(Counter(c.get("outcome") for x in slices for _, c in x["consults"])))
    print(" test phase outcomes:",
          dict(Counter(t.get("outcome") for x in slices for _, t in x["tests"])))
    listed = [x for x in slices if x["s"].get("appended_phases")]
    print(f" state.json's own `appended_phases`: {len(listed)} slices, "
          f"{sum(len(x['s']['appended_phases']) for x in listed)} phases — it was recorded late")

    # appended = a phase whose first executor row follows the first completion consult row
    tot_cost = app_cost = all_cost = 0.0
    per_slice = []
    for x in slices:
        hist = x["s"].get("history", [])
        at = next((i for i, h in enumerate(hist) if "consult" in str(h.get("role"))
                   and str(h.get("phase")) in ("None", "completion", "", "null")), None)
        if at is None:
            at = next((i for i, h in enumerate(hist) if "completion" in json.dumps(h)[:200]),
                      None)
        t = _phase_time(x["s"])
        cost = (x["s"].get("cost") or {}).get("cost_usd") or 0
        all_cost += cost
        total_t = sum((h.get("duration_s") or 0) for h in hist)
        appended: list[str] = []
        if at is not None:
            before = {str(h.get("phase")) for h in hist[:at] if h.get("role") == "code-writer"}
            for h in hist[at:]:
                pid = str(h.get("phase"))
                if h.get("role") == "code-writer" and pid not in before \
                        and pid not in appended and pid in x["s"].get("phases", {}):
                    appended.append(pid)
        x["_ap"] = appended
        if appended:
            spent = sum(t[p] for p in appended)
            est = cost * spent / total_t if total_t else 0
            app_cost += est
            tot_cost += cost
            per_slice.append((x["name"], x["s"].get("plugin_version"), appended, spent / 60, est,
                              cost))
    with_ap = [x for x in slices if x["_ap"]]
    print(f"\nslices with appended phases (by history order): {len(with_ap)} of {len(slices)} "
          f"({_pct(len(with_ap), len(slices))}); appended phases "
          f"{sum(len(x['_ap']) for x in slices)}")
    minutes = [_phase_time(x["s"])[p] / 60 for x in with_ap for p in x["_ap"]]
    rounds = [(x["s"].get("phases", {}).get(p) or {}) for x in with_ap for p in x["_ap"]]
    print(f" per appended phase: median {statistics.median(minutes):.0f} min of session time; "
          f"executor rounds mean "
          f"{statistics.mean(r.get('executor_rounds') or 0 for r in rounds):.2f}, review rounds "
          f"mean {statistics.mean(r.get('review_rounds') or 0 for r in rounds):.2f}")
    print(f" their session time priced at the slice's cost: ${app_cost:.0f} of ${tot_cost:.0f} "
          f"({_pct(app_cost, tot_cost)}) in those slices; of all slices' ${all_cost:.0f}: "
          f"{_pct(app_cost, all_cost)}")
    for name, version, phases, mins, est, cost in per_slice:
        print(f"  {name[:44]:<44} v{version}  phases {phases}  {mins:.0f} min  ~${est:.1f} "
              f"of ${cost:.0f}")

    print("\nbefore and since 2026-08-16 (the 0.5.1 bar)")
    for label, since in (("created before 2026-08-16", False), ("created since", True)):
        sub = [x for x in slices if ((x["s"].get("created_at") or "")[:10] >= "2026-08-16")
               == since]
        w = [x for x in sub if x["_ap"]]
        ts = [_phase_time(x["s"])[p] / 60 for x in w for p in x["_ap"]]
        print(f"  {label}: slices {len(sub)}, with an appended phase {len(w)} "
              f"({_pct(len(w), len(sub))}), appended phases {sum(len(x['_ap']) for x in w)}, "
              f"median minutes {statistics.median(ts) if ts else 0:.0f}; "
              f"{[x['name'][:3] for x in w]}")
    print("  without a date:", sum(1 for x in slices if not x["s"].get("created_at")))

    if args.why:
        print("\nwhy: consult and test-phase summaries that appended")
        for x in slices:
            if not x["_ap"] and not any(c.get("outcome") in ("appended", "fix_tasks")
                                        for _, c in x["consults"]):
                continue
            head = f"{x['proj']} {x['name']}"
            for n, c in x["consults"]:
                if c.get("outcome") in ("appended", "fix_tasks"):
                    print(f"\n--- {head} · {n} · {c.get('outcome')} · "
                          f"v{x['s'].get('plugin_version')}")
                    print(re.sub(r"\s+", " ", c.get("summary", ""))[:1100])
            for n, t in x["tests"]:
                if t.get("outcome") == "findings":
                    print(f"\n--- {head} · {n} · findings · v{x['s'].get('plugin_version')}")
                    print(re.sub(r"\s+", " ", t.get("summary", ""))[:1100])
    return 0


# --- § 3.7 test gaps ---------------------------------------------------------------------------

_GAP = re.compile(
    r"no test\b|test gap|unpinned|not pinned|pins? nothing|pinned only|pins only"
    r"|survives? (a |the )?mutation|vacuous|cannot fail|can never fail"
    r"|no \S+( \S+)? test (pins|drives|covers|exercises|observes|renders)"
    r"|untested|uncovered|has no (\S+ )?test|nothing (pins|observes|exercises|holds|checks)"
    r"|no (\S+ )?gate (holds|on)|not (covered|exercised|reached|reachable) (by|from) (a |any )?test"
    r"|no (\S+ )?(drift )?(test|gate)\b|test witness|without a test|lacks? a test|is not tested"
    r"|(test|assertion)s? .{0,60}(cannot observe|never fails|passes either way|proves nothing)",
    re.I)
_IDENT = re.compile(r"`([A-Za-z_][\w./:-]{7,}(?:\(\))?)`")
_GAP_THEMES = {
    "wiring / composition root / call site unpinned":
        r"wiring|composition root|call site|field-injected|main\.py",
    "cross-component or cross-repo contract without a gate":
        r"hand-mirror|hand-maintain|cross-repo|cross-compo|drift|contract .{0,40}no gate"
        r"|against each other",
    "boundary or threshold value": r"boundary|threshold|exact-fit|default val|only from below",
    "a test that cannot fail as written":
        r"vacuous|catches its own|try/catch|cannot observe|never writes|50 ms sleep|survives",
}


def _bodies(path: Path) -> dict[str, str]:
    """Id -> the entry's heading and body, read off the report as it is on disk."""
    out: dict[str, str] = {}
    cur = None
    fence = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^### (?:~~)?([ANBQS]\d+) — (.*)", line)
        if m:
            cur = m.group(1)
            out[cur] = line + "\n"
        elif not fence and line.startswith("## "):
            cur = None
        elif cur:
            out[cur] += line + "\n"
    return out


def cmd_testgaps(args) -> int:
    d = Discussion(args.data)
    truth = dict(_sorted_as(d, "heldout-v2"))
    allent = []
    for r in d.reports:
        path = Path(r["path"])
        bodies = _bodies(path) if path.exists() else {}
        for e in r["entries"]:
            if not _ENTRY_ID.fullmatch(e["id"]):
                continue
            e["_num"] = int(r["slice"][:3])
            e["_proj"] = r["project"]
            e["_body"] = bodies.get(e["id"], "")
            e["_gap"] = e["section"] in "BS" and bool(_GAP.search(e["headline"]))
            allent.append(e)

    held = [e for e in allent if (e["_rep"], e["id"]) in truth]
    both = sum(1 for e in held if truth[(e["_rep"], e["id"])] == "test gaps" and e["_gap"])
    sorter = sum(1 for e in held if truth[(e["_rep"], e["id"])] == "test gaps" and not e["_gap"])
    keyword = sum(1 for e in held if truth[(e["_rep"], e["id"])] != "test gaps" and e["_gap"])
    print(f"§ 3.7 keyword class vs the sorter's bucket (held-out): both {both}, sorter only "
          f"{sorter}, keyword only {keyword}")

    def classes(es):
        c = Counter(e["fate"] for e in es)
        n = len(es)
        return (f"{n:>3}  card/fold {_pct(c['card'] + c['fold'], n):>5}  fix "
                f"{_pct(c['fix'], n):>5}  close {_pct(c['close'], n):>5}")

    gaps = [e for e in allent if e["_gap"] and e["fate"] != "in-run"]
    ruled = [e for e in gaps if e["fate"] in RULED]
    c = Counter(e["fate"] for e in ruled)
    print(f"\ncorpus: test-gap entries handed over {len(gaps)}, ruled {len(ruled)}")
    print(" fates:", dict(c), " progressed", _pct(c["card"] + c["fix"] + c["fold"], len(ruled)))
    for sev in ("major", "minor", "", "nit", "cosmetic"):
        print(f"  {sev or 'ungraded':<9} {classes([e for e in ruled if e['severity'] == sev])}")
    for ev in ("witnessed", "read"):
        print(f"  {ev:<9} {classes([e for e in ruled if e['evidence'] == ev])}")
    print(" struck in the run (fixed, refuted, superseded):",
          sum(1 for e in allent if e["_gap"] and e["fate"] == "in-run"))
    rest = [e for e in allent if e["section"] in "BS" and not e["_gap"] and e["fate"] in RULED]
    print(f" for comparison, other Bugs+Suggestions ruled {classes(rest)}")
    per = Counter(e["_rep"] for e in gaps)
    print(f" reports with a test-gap entry: {len(per)} of {len({e['_rep'] for e in allent})}; "
          f"per report with any: median {sorted(per.values())[len(per) // 2]}, max "
          f"{max(per.values())}")

    print("\nKubeCoder, test-gap entries per report by slice range")
    for lo, hi in ((146, 170), (171, 195), (196, 215), (216, 240)):
        reps = {e["_rep"] for e in allent if e["_proj"] == "KubeCoder" and lo <= e["_num"] <= hi}
        g = [e for e in gaps if e["_proj"] == "KubeCoder" and lo <= e["_num"] <= hi]
        print(f"  {lo}-{hi}: reports {len(reps)}, gap entries {len(g)}, per report "
              f"{len(g) / max(1, len(reps)):.1f}")

    # identifiers a closed gap names, met again later in a Bug entry
    common = Counter(t for e in allent for t in set(_IDENT.findall(e["headline"] + e["_body"])))
    closed = [e for e in gaps if e["fate"] == "close"]
    hits = []
    for g in closed:
        toks = {t for t in _IDENT.findall(g["headline"] + g["_body"]) if common[t] <= 6}
        for e in allent if toks else ():
            if e["_proj"] != g["_proj"] or e["_num"] <= g["_num"] or e["section"] != "B" \
                    or e["_gap"]:
                continue
            shared = toks & set(_IDENT.findall(e["headline"] + e["_body"]))
            if shared:
                hits.append((g, e, shared))
    print(f"\nclosed gap entries: {len(closed)}; with a later non-gap Bug entry sharing a rare "
          f"identifier: {len({(g['_rep'], g['id']) for g, _, _ in hits})} gaps, "
          f"{len(hits)} pairs")
    for g, e, shared in hits:
        print(f"  {g['_rep']} {g['id']} -> {e['_rep']} {e['id']} [{e['fate']}]   shared: "
              f"{sorted(shared)[:4]}")

    allgap = [e for e in allent if e["section"] in "BS" and e["fate"] == "close"
              and (e["_gap"] or truth.get((e["_rep"], e["id"])) == "test gaps")]
    print(f"\nclosed gap entries, keyword class or sorter's bucket: {len(allgap)}")
    for name, rx in _GAP_THEMES.items():
        s = [e for e in allgap if re.search(rx, e["headline"], re.I)]
        print(f"  {name}: {len(s)} in {len({e['_rep'] for e in s})} reports")
    if args.gaps_out:
        runs = {_report_key(r["project"], r["slice"]): (r["slice"], r["run"][:10])
                for r in d.reports}
        with open(args.gaps_out, "w", encoding="utf-8") as f:
            for e in sorted(allgap, key=lambda e: (e["_proj"], e["_num"], e["id"])):
                slug, date = runs[e["_rep"]]
                body = re.sub(r"\s+", " ", e["_body"])[:900]
                f.write(f"## {e['_proj']} slice {slug} — {e['id']} — closed; run of {date}; "
                        f"grade {e['severity'] or 'none'}; {e['evidence'] or 'evidence unstated'}"
                        f"\n\n{body}\n\n")
        print(f"written {len(allgap)} -> {args.gaps_out}")
    return 0


# --- the build's checks (plan § 7) -----------------------------------------------------------

# § 3.10's table as amended and § 3.9's as ruled: per route, the entries and the fates
# (closed, fixed, carded, folded) of the operator's own rulings; per group over everything
# handed over, the entries and a report's median and max.
_EXPECT = {
    "loud is closed": ({
        ORDER[0]: (14, 11, 0, 3, 0), ORDER[1]: (11, 3, 4, 3, 1), ORDER[2]: (9, 5, 1, 3, 0),
        ORDER[3]: (10, 3, 2, 5, 0), ORDER[4]: (89, 32, 40, 16, 1), ORDER[5]: (13, 8, 3, 2, 0),
        ORDER[6]: (7, 2, 2, 3, 0), ORDER[7]: (3, 1, 0, 2, 0), ORDER[8]: (22, 9, 4, 3, 6),
        ORDER[9]: (4, 2, 0, 2, 0), ORDER[10]: (40, 34, 1, 5, 0), ORDER[11]: (12, 12, 0, 0, 0),
    }, {
        GROUPS[0]: (126, 2, 8), GROUPS[1]: (260, 5, 21), GROUPS[2]: (43, 0, 8),
        GROUPS[3]: (13, 0, 2), GROUPS[4]: (84, 1, 7), GROUPS[5]: (35, 0, 4),
    }),
    "as ruled": ({
        ORDER[0]: (14, 11, 0, 3, 0), ORDER[1]: (11, 3, 4, 3, 1), ORDER[2]: (8, 4, 1, 3, 0),
        ORDER[3]: (10, 3, 2, 5, 0), ORDER[4]: (89, 32, 40, 16, 1), ORDER[5]: (13, 8, 3, 2, 0),
        ORDER[6]: (11, 5, 2, 4, 0), ORDER[7]: (3, 1, 0, 2, 0), ORDER[8]: (22, 9, 4, 3, 6),
        ORDER[9]: (4, 2, 0, 2, 0), ORDER[10]: (37, 32, 1, 4, 0), ORDER[11]: (12, 12, 0, 0, 0),
    }, {
        GROUPS[0]: (124, 2, 8), GROUPS[1]: (279, 5, 24), GROUPS[2]: (43, 0, 8),
        GROUPS[3]: (13, 0, 2), GROUPS[4]: (67, 1, 6), GROUPS[5]: (35, 0, 4),
    }),
}


def cmd_table_check(args) -> int:
    """The committed labels routed by the tool's table: § 3.10's numbers, and § 3.9's without
    the signal. Prints report keys and counts only."""
    d = Discussion(args.data)
    differences = 0
    for name, (by_route, by_group) in _EXPECT.items():
        print(f"{name} — the {len(d.own)} own rulings: route, the tool (n closed fixed carded "
              "folded), the plan")
        for route, want in by_route.items():
            c = Counter(e["fate"] for k, _, e in d.own if d.variant(name, k) == route)
            got = (sum(c.values()), c["close"], c["fix"], c["card"], c["fold"])
            differences += got != want
            print(f"  {route:<56}{got!s:<24}{want!s:<24}{'' if got == want else 'DIFFERENT'}")
        extra = Counter(d.variant(name, k) for k, _, _ in d.own
                        if d.variant(name, k) not in by_route)
        if extra:
            differences += 1
            print("  routes the plan does not have:", dict(extra))
        per, total = defaultdict(Counter), Counter()
        for k, _, _ in d.handed:
            g = _group(d.variant(name, k))
            per[k[0]][g] += 1
            total[g] += 1
        print(f"  all {len(d.handed)} handed over: group, the tool (n median max), the plan")
        for g, want in by_group.items():
            xs = [per[r][g] for r in per]
            got = (total[g], statistics.median(xs), max(xs))
            differences += got != want
            print(f"  {g:<26}{got!s:<24}{want!s:<24}{'' if got == want else 'DIFFERENT'}")
        print()
    print("PASS" if not differences else f"{differences} difference(s)")
    return 1 if differences else 0


BEFORE_STORE = "ccfcf72"    # origin/main at 0.9.56, the last close_out.py without the store


def _tool_at(rev: str, into: Path):
    text = subprocess.run(
        ["git", "-C", str(TOOLS), "show", f"{rev}:plugins/dev/tools/close_out.py"],
        capture_output=True, text=True, check=True).stdout
    path = into / "close_out_before.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("close_out_before", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _collapse(s) -> str:
    return " ".join((s or "").split())


def cmd_corpus_check(args) -> int:
    """Each snapshot imported and rendered by the plugin's tool in a scratch slice directory,
    held against the tool before the store on the untouched snapshot. Prints no entry text."""
    snaps = sorted(Path(args.snapshots).glob("*.md"))
    if not snaps:
        print(f"no snapshots under {args.snapshots}", file=sys.stderr)
        return 2
    new = _close_out()
    label_re = re.compile(r"^\*{0,2}(Consequence|Provenance|Disposition):\*{0,2}\s*")
    results = {k: [] for k in ("ids_in_store_once", "ids_in_report_once", "body_lines",
                               "counts_equal_plus_unshaped", "readback_took_nothing",
                               "second_render_identical", "errors")}
    headings_without_id = []     # the old tool counted none of these; expected, not a failure
    n_reports = n_entries = n_unshaped = 0
    with tempfile.TemporaryDirectory() as scratch:
        old = _tool_at(args.before, Path(scratch))
        folds = {old.FOLD_OPEN, old.FOLD_CLOSE, "</details>"}
        for snap in snaps:
            key = snap.stem
            _, _, slug = key.partition("-")
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp) / "specs" / "slices" / slug
                d.mkdir(parents=True)
                shutil.copy(snap, d / "close-out.md")
                text = snap.read_text(encoding="utf-8")
                n_reports += 1
                oc = old.entry_counts(d)
                blocks = []
                for name, start, end in old._sections(text):
                    if name in old.SECTIONS:
                        for b in old._blocks(text, start, end, old.SECTIONS[name]):
                            blocks.append((name, b.eid, text[b.start:b.end].split("\n")[1:],
                                           b.kind))
                unshaped = Counter(old.SECTIONS[name] for name, _, _, kind in blocks
                                   if kind == "unshaped")
                err = io.StringIO()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    c1 = new.main(["import", str(d)])
                    after_import = (d / "close-out.json").read_text(encoding="utf-8")
                    c2 = new.main(["render", str(d)])
                if c1 or c2:
                    results["errors"].append((key, f"exit {c1}/{c2}: {err.getvalue()[:200]}"))
                    continue
                md1 = (d / "close-out.md").read_text(encoding="utf-8")
                st1 = (d / "close-out.json").read_text(encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    new.main(["render", str(d)])
                if (d / "close-out.md").read_text(encoding="utf-8") != md1 \
                        or (d / "close-out.json").read_text(encoding="utf-8") != st1:
                    results["second_render_identical"].append((key, "changed"))
                if st1 != after_import:
                    results["readback_took_nothing"].append((key, "store changed by render"))
                entries = json.loads(st1)["entries"]
                n_entries += len(entries)
                n_unshaped += sum(unshaped.values())
                sids = [e["id"] for e in entries]
                rids = []
                for line, hidden in new._scan(md1):
                    m = None if hidden else re.match(r"^### (~~)?([A-Z]\d+) — ", line)
                    if m:
                        rids.append(m.group(2))
                for eid in (eid for _, eid, _, _ in blocks if eid):
                    if sids.count(eid) != 1:
                        results["ids_in_store_once"].append((key, eid, sids.count(eid)))
                    if rids.count(eid) != 1:
                        results["ids_in_report_once"].append((key, eid, rids.count(eid)))
                if len(sids) != len(set(sids)):
                    results["ids_in_store_once"].append((key, "duplicate ids in the store"))
                if sorted(sids) != sorted(rids):
                    results["ids_in_report_once"].append((key, "store ids != report ids"))
                # every old non-blank line (heading and fold markers aside) is kept: in the
                # body, in order, or inside the label text it continued
                by_section = defaultdict(list)
                for e in entries:
                    by_section[e["section"]].append(e)
                pos = Counter()
                for name, eid, lines, _ in blocks:
                    e = by_section[name][pos[name]]
                    pos[name] += 1
                    if eid and e["id"] != eid:
                        results["body_lines"].append((key, eid, f"order mismatch -> {e['id']}"))
                        continue
                    body = [ln.rstrip() for ln in e["body"]]
                    labels = _collapse(" ".join(filter(None, [
                        e.get("consequence"), e.get("evidence"), e.get("author"),
                        " — ".join(filter(None, [e.get("evidence"), e.get("author")])),
                        (e.get("ruling") or {}).get("words")])))
                    i = lost = 0
                    for ln in lines:
                        if not ln.strip() or ln.strip() in folds:
                            continue
                        j = i
                        while j < len(body) and body[j] != ln.rstrip():
                            j += 1
                        if j < len(body):
                            i = j + 1
                            continue
                        stripped = _collapse(label_re.sub("", ln))
                        if not stripped or stripped in labels:
                            continue
                        # the evidence class and its separator are split off by design
                        m = re.match(r"(?i)^(witnessed|read)[\s—–\-:;,]*(.*)$", stripped)
                        if m and e.get("evidence") == m.group(1).lower() \
                                and _collapse(m.group(2)) == (e.get("author") or ""):
                            continue
                        lost += 1
                    if lost:
                        results["body_lines"].append((key, e["id"], f"{lost} line(s) lost"))
                nc = new.entry_counts(d)
                for section, letter in old.SECTIONS.items():
                    o, n = oc[section], nc.get(letter, 0)
                    if o != n:
                        headings_without_id.append((key, letter, o, n))
                    if o + unshaped.get(letter, 0) != n:
                        results["counts_equal_plus_unshaped"].append(
                            (key, letter, o, unshaped.get(letter, 0), n))

    print(f"{n_reports} reports, {n_entries} entries in the stores, {n_unshaped} headings not in "
          f"the entry shape imported as entries (the tool at {args.before} counted none)")
    if headings_without_id:
        print("  counts that differ by those headings alone:", headings_without_id)
    for k, v in results.items():
        print(f"\n{k}: {'PASS' if not v else f'{len(v)} difference(s)'}")
        for row in v[:60]:
            print("  ", row)
    return 1 if any(results.values()) else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("extract")
    x.add_argument("repos", nargs="+")
    x.add_argument("-o", "--out", default=str(DEFAULT_DATA))
    x.set_defaults(fn=cmd_extract)
    for name, fn in (("report", cmd_report), ("unclassified", cmd_unclassified)):
        s = sub.add_parser(name)
        s.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
        s.set_defaults(fn=fn)
    d = sub.add_parser("dump")
    d.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
    d.add_argument("--fate", default="card,fix,fold")
    d.set_defaults(fn=cmd_dump)
    n = sub.add_parser("snapshots")
    n.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
    n.add_argument("-o", "--out", required=True)
    n.set_defaults(fn=cmd_snapshots)
    t = sub.add_parser("sessions")
    t.add_argument("dirs", nargs="+")
    t.add_argument("-o", "--out", required=True)
    t.set_defaults(fn=cmd_sessions)
    c = sub.add_parser("score")
    c.add_argument("dirs", nargs="+")
    c.add_argument("--data", default=str(DEFAULT_DATA))
    c.add_argument("--modes")
    c.set_defaults(fn=cmd_score)
    o = sub.add_parser("order")
    o.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
    o.add_argument("--sorts", default=str(
        Path(__file__).resolve().parents[1] / "data" / "close-out-read-2026-09-28.json"))
    o.add_argument("--arm", default="heldout-v2")
    o.set_defaults(fn=cmd_order)
    for name, fn, flags in (("focus", cmd_focus, ()), ("who", cmd_who, ()),
                            ("labels", cmd_labels, ("--misses",)),
                            ("improvements", cmd_improvements, ("--misses",)),
                            ("tables", cmd_tables, ()),
                            ("signal", cmd_signal, ("--misses", "--list")),
                            ("table-check", cmd_table_check, ())):
        s = sub.add_parser(name)
        s.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
        for flag in flags:
            s.add_argument(flag, action="store_true")
        s.set_defaults(fn=fn)
    g = sub.add_parser("testgaps")
    g.add_argument("data", nargs="?", default=str(DEFAULT_DATA))
    g.add_argument("--gaps-out", help="write the closed gap entries, with their bodies, here")
    g.set_defaults(fn=cmd_testgaps)
    a = sub.add_parser("appended")
    a.add_argument("repos", nargs="+")
    a.add_argument("--why", action="store_true",
                   help="print the consult and test-phase summaries behind the appended phases")
    a.set_defaults(fn=cmd_appended)
    k = sub.add_parser("corpus-check")
    k.add_argument("snapshots")
    k.add_argument("--before", default=BEFORE_STORE,
                   help="the commit whose close_out.py counts the untouched snapshot")
    k.set_defaults(fn=cmd_corpus_check)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
