#!/usr/bin/env python3
"""Close-out readout — what the reports hand over against what the operator rules.

Research tooling, not plugin. Reads every ``close-out.md`` under the given spec repos'
``slices/`` trees into one row per entry (section, severity, evidence class, author role, the
Consequence line, the strike reason, the ``Disposition:`` line), classifies each entry's fate
from the words on its heading and its disposition, and prints the tables of the 2026-09-28
read (``docs/research/close-out-read-2026-09-28.md``).

    close_out_readout.py extract <spec-repo>... [-o entries.json]
    close_out_readout.py report  [entries.json]
    close_out_readout.py dump    [entries.json] --fate card,fix,fold   # the progressed entries
    close_out_readout.py unclassified [entries.json]
    close_out_readout.py snapshots [entries.json] -o <dir>    # each report as handed over
    close_out_readout.py sessions <transcript-dir>... -o <dir> # the close-out chats, digested
    close_out_readout.py score <sorted-dir>... [--modes report-mode.json]
    close_out_readout.py order [entries.json] [--arm heldout-v2]  # where the picks sit

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
import json
import re
import statistics
import subprocess
import sys
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


# --- commands -------------------------------------------------------------------------------

def cmd_extract(args) -> int:
    reports = []
    for repo in args.repos:
        repo = Path(repo)
        project = repo.name.removesuffix("Specs")
        for path in sorted((repo / "slices").rglob("close-out.md")):
            if "archive" in path.parts:
                continue
            reports.append(parse_report(path, project))
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
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
