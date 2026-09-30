#!/usr/bin/env python3
"""Read the /dev:triage runs recorded in one or more spec repos.

A triage run writes a status document to ``handovers/triage_YYYY-MM-DD[_suffix].md`` in the
project's spec repo (beside a ``_raw`` dump) and deletes it when it closes out, so the documents
are read from git history. One run is one add→delete cycle of a status document path: the same
file name is reused by several runs on one day, so a run is its project, its file name and the
commit that added it. Each run's first committed version is compared with its last.

    triage_readout.py runs     <spec-repo>...           one row per run: items, words, versions
    triage_readout.py rulings  <spec-repo>...           the classified rulings, cross-tabbed
    triage_readout.py sessions <spec-repo>... -o <dir>  one timeline file per run: the operator's
                                                        side of the session that made its commits
    triage_readout.py cost     <spec-repo>...           per run: wall clock split into operator
                                                        latency and machine time, priced tokens

    e.g. triage_readout.py rulings /work/scratch/KubeCoderSpecs /work/scratch/AnsibleSpecs

Options for every command: ``--since <date>`` (runs whose document was added on or after it,
default 2026-08-28), ``--last <N>`` (keep the last N runs by first-commit time, default 20; 0
keeps all), ``--transcripts <project>=<dir>`` (repeatable). The project is the spec repo's
directory name less a trailing ``Specs``; for such a repo the transcripts default to
``~/.claude/projects/-work-<project>``. ``rulings`` takes ``--data <file>``, the hand
classification (default ``../data/triage-rulings-2026-09-29.json`` beside this tool).

A run is numbered by its position among all runs since ``--since``, so ``--last`` does not
renumber it. Run 2026-09-29's read on the default options: runs 6-25.

``rulings`` reads each item's class from the data file and derives none: a run matches its entry
by project, document and added-commit prefix, and an item or run without an entry is counted as
``unclassified``, apart. An item is *asked* when its first or last version carries a Question or
a Collides line; its category is its first version's (its last version's when it is new there);
a relabel is an item in both versions whose category differs.

``sessions`` and ``cost`` pick, among the project's interactive transcripts that mention a run's
commit subjects, the one whose own Bash calls made the most of those commits. ``cost`` opens the
window at that session's first /dev:triage invocation and closes it 90 s after the run's last
commit; operator latency is the time from the session's last assistant event (or from an
AskUserQuestion) to the operator's next message (or answer). Tokens are priced with the plugin's
``slice_cost.py``: the main session's in the window, and its sub-agents' in the window.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[2] / "plugins" / "dev" / "tools"
DEFAULT_DATA = HERE.parent / "data" / "triage-rulings-2026-09-29.json"

FIELDS = ("Source", "Ask", "Question", "Category", "Collides", "Note", "Research", "Ruling")
CARRIED = ("Collides", "Question", "Research", "Note")
ITEM_RE = re.compile(r"^### (.+?)\s*$", re.M)
SECTION_RE = re.compile(r"^## ", re.M)
CARD_RE = re.compile(r"^\*\*Card text:?\*\*", re.M)
FIELD_RE = re.compile(r"^- \*{0,2}([\w ]+?)\*{0,2}:\*{0,2}\s?(.*)$")
CATEGORY_RE = re.compile(
    r"(?i)(undetermined|nit ?pick|corner case|minor|major|improvement|feature|test gap|decision"
    r"|invalid|operator chore|chore)"
)
COMMIT_MSG_RE = re.compile(
    r"git[^\n]*commit[^\n]*-m\s+[\"']?(?:\$\(cat <<'?EOF'?\n)?([^\n\"']{10,160})"
)
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND_NAME_RE = re.compile(r"<command-name>([^<]*)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>([^<]*)</command-args>", re.S)
NOT_OPERATOR = ("<local-command", "<task-notification", "<persisted", "Caveat:")
END_GRACE = timedelta(seconds=90)  # the turn that makes the last commit ends after it


# ---------------------------------------------------------------- runs, from git history


@dataclass
class Commit:
    sha: str
    when: datetime
    subject: str


@dataclass
class Item:
    id: str
    title: str
    fields: dict[str, str]
    words_card: int


@dataclass
class Version:
    items: list[Item]
    words: int
    words_card: int
    words_head: int


@dataclass
class Row:
    """One item of a run's last version, beside its first version."""

    id: str
    cat0: str
    cat1: str
    carries: dict[str, str]  # CARRIED field -> its text in the last version, else the first
    ruling: str
    new: bool

    @property
    def asked(self) -> bool:
        return bool(self.carries["Question"] or self.carries["Collides"])

    @property
    def category(self) -> str:
        return self.cat1 if self.new else self.cat0


@dataclass
class Run:
    n: int
    project: str
    repo: Path
    path: str
    commits: list[Commit]
    deleted: Commit | None = None
    _versions: tuple[Version, Version] | None = field(default=None, repr=False)

    @property
    def document(self) -> str:
        return Path(self.path).name

    @property
    def added(self) -> str:
        return self.commits[0].sha[:8]

    @property
    def end(self) -> datetime:
        return (self.deleted or self.commits[-1]).when

    @property
    def subjects(self) -> list[str]:
        return [c.subject for c in self.commits] + ([self.deleted.subject] if self.deleted else [])

    def versions(self) -> tuple[Version, Version]:
        if self._versions is None:
            first = parse(git(self.repo, "show", f"{self.commits[0].sha}:{self.path}"))
            last = parse(git(self.repo, "show", f"{self.commits[-1].sha}:{self.path}"))
            self._versions = (first, last)
        return self._versions

    def rows(self) -> list[Row]:
        first, last = self.versions()
        before = {it.id: it.fields for it in first.items}
        rows = []
        for it in last.items:
            f0, f1 = before.get(it.id, {}), it.fields
            rows.append(Row(
                id=it.id,
                cat0=category(f0.get("Category")),
                cat1=category(f1.get("Category")),
                carries={k: f1.get(k) or f0.get(k) or "" for k in CARRIED},
                ruling=f1.get("Ruling", "").strip(),
                new=it.id not in before,
            ))
        return rows


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout


def is_status_document(name: str) -> bool:
    return name.endswith(".md") and not any(
        s in name for s in ("_raw", "straightforward", "doc_changes"))


def enumerate_runs(repos: dict[str, Path], since: str) -> list[Run]:
    """Every add→delete cycle of a status document since ``since``, by first-commit time."""
    runs: list[Run] = []
    for project, repo in repos.items():
        log = git(repo, "log", "--reverse", f"--since={since}", "--format=@%H|%aI|%s",
                  "--name-status", "--", "handovers/triage_*")
        commit = None
        open_runs: dict[str, Run] = {}
        for line in log.splitlines():
            if line.startswith("@"):
                sha, when, subject = line[1:].split("|", 2)
                commit = Commit(sha, datetime.fromisoformat(when), subject)
                continue
            if not line.strip():
                continue
            cols = line.split("\t")
            status, path = cols[0], cols[-1]
            if not is_status_document(Path(path).name):
                continue
            if status.startswith("A"):
                open_runs[path] = Run(0, project, repo, path, [commit])
                runs.append(open_runs[path])
            elif status.startswith("M") and path in open_runs:
                open_runs[path].commits.append(commit)
            elif status.startswith("D") and path in open_runs:
                open_runs.pop(path).deleted = commit
    runs.sort(key=lambda r: r.commits[0].when)
    for n, run in enumerate(runs):
        run.n = n
    return runs


# ---------------------------------------------------------------- the status document


def parse(text: str) -> Version:
    parts = ITEM_RE.split(text)
    items = []
    for title, body in zip(parts[1::2], parts[2::2], strict=True):
        body = SECTION_RE.split(body, maxsplit=1)[0]
        m = CARD_RE.search(body)
        block, card = (body[:m.start()], body[m.start():]) if m else (body, "")
        fields: dict[str, str] = {}
        cur = None
        for line in block.splitlines():
            fm = FIELD_RE.match(line)
            if fm:
                cur = fm.group(1)
                fields[cur] = fm.group(2).strip()
            elif line.startswith("- "):
                cur = None
            elif cur and line.strip():
                fields[cur] += " " + line.strip()
        items.append(Item(title.split(" — ")[0].strip(), title, fields, len(card.split())))
    return Version(items, len(text.split()), sum(i.words_card for i in items),
                   len(parts[0].split()))


def category(label: str | None) -> str:
    if not label:
        return "?"
    label = label.strip().strip("*")
    m = CATEGORY_RE.match(label)
    base = m.group(1).lower() if m else label.split("—")[0].strip().lower()[:30]
    if "borderline" in label.lower()[:60]:
        base += " (borderline)"
    return base


# ---------------------------------------------------------------- transcripts


def parse_ts(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None


@cache
def load_transcript(path: Path) -> list[dict]:
    lines = []
    with path.open(errors="replace") as fh:
        for raw in fh:
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines


def blocks(d: dict) -> list:
    content = (d.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def tool_uses(d: dict):
    for b in blocks(d):
        if isinstance(b, dict) and b.get("type") == "tool_use":
            yield b.get("name"), b.get("input") or {}, b.get("id")


def user_text(b) -> str:
    text = b.get("text", "") if isinstance(b, dict) else str(b)
    return REMINDER_RE.sub("", text).strip()


def main_line(lines: list[dict]) -> list[dict]:
    return [d for d in lines if not d.get("isSidechain")]


@cache
def triage_transcripts(root: Path) -> dict[Path, str]:
    """The top-level transcripts under ``root`` that mention a status document, with their text."""
    out = {}
    for p in sorted(root.glob("*.jsonl")):
        text = p.read_text(errors="replace")
        if "handovers/triage_" in text:
            out[p] = text
    return out


def pick_session(run: Run, root: Path) -> Path | None:
    """The transcript whose own Bash calls made the most of the run's commits; on a tie (a run
    spread over sessions), the one that made the latest of them — the session that closed it."""
    keys = set()
    for subject in run.subjects:
        keys.add(json.dumps(subject[:60], ensure_ascii=False)[1:-1])
        keys.add(json.dumps(subject[:60])[1:-1])
    prefixes = [s[:50] for s in run.subjects]
    best, best_key = None, (0, "")
    for p, text in triage_transcripts(root).items():
        if not any(k in text for k in keys):
            continue
        made, latest = 0, ""
        for d in main_line(load_transcript(p)):
            if d.get("type") != "assistant":
                continue
            for name, inp, _ in tool_uses(d):
                cmd = (inp.get("command") or "") if name == "Bash" else ""
                if "git" in cmd and "commit" in cmd and any(s in cmd for s in prefixes):
                    made += 1
                    latest = max(latest, d.get("timestamp", ""))
        if made and (made, latest) > best_key:
            best, best_key = p, (made, latest)
    return best


# ---------------------------------------------------------------- commands


def selected(args) -> tuple[list[Run], dict[str, Path | None]]:
    repos: dict[str, Path] = {}
    roots: dict[str, Path | None] = {}
    for spec in args.repos:
        repo = Path(spec).resolve()
        project = repo.name.removesuffix("Specs")
        repos[project] = repo
        roots[project] = (Path.home() / ".claude/projects" / f"-work-{project}"
                          if project != repo.name else None)
    for spec in args.transcripts:
        project, _, root = spec.partition("=")
        roots[project] = Path(root).expanduser()
    runs = enumerate_runs(repos, args.since)
    return (runs[-args.last:] if args.last else runs), roots


def fmt_counts(c: Counter, order: list[str]) -> str:
    keys = sorted(c, key=lambda k: (order.index(k) if k in order else len(order), k))
    return " ".join(f"{k} {c[k]}" for k in keys if c[k])


def cmd_runs(args) -> int:
    runs, _ = selected(args)
    print(f"{'n':>3} {'project':10} {'document':32} {'first commit':16} {'items':>5} {'words':>6} "
          f"{'card':>6} {'rest':>6} {'head':>5} {'ver':>3}")
    tot = Counter()
    for r in runs:
        first, last = r.versions()
        print(f"{r.n:>3} {r.project:10} {r.document:32} {r.commits[0].when:%Y-%m-%d %H:%M} "
              f"{len(last.items):>5} {first.words:>6} {first.words_card:>6} "
              f"{first.words - first.words_card:>6} {first.words_head:>5} {len(r.commits):>3}")
        tot.update(items=len(last.items), words=first.words, card=first.words_card,
                   head=first.words_head)
    per_project = Counter(r.project for r in runs)
    print(f"\n{len(runs)} runs ({', '.join(f'{p} {n}' for p, n in per_project.items())}), "
          f"{tot['items']} items; words {tot['words']:,} total, {tot['card']:,} card text, "
          f"{tot['words'] - tot['card']:,} rest ({tot['head']:,} header)")
    return 0


def cmd_rulings(args) -> int:
    runs, _ = selected(args)
    data = json.loads(Path(args.data).read_text())
    order = [*data["classes"], "unclassified"]

    total, carried = Counter(), Counter()
    by_asked: dict[str, Counter] = defaultdict(Counter)
    by_cat: dict[str, Counter] = defaultdict(Counter)
    per_run, relabels, unmatched, stale = [], [], [], []
    for r in runs:
        entry = next((e for e in data["runs"] if e["project"] == r.project
                      and e["document"] == r.document and r.commits[0].sha.startswith(e["added"])),
                     None)
        if entry is None:
            unmatched.append(r)
        classes = entry["items"] if entry else {}
        rows = r.rows()
        c = Counter()
        for row in rows:
            k = classes.get(row.id, "unclassified")
            c[k] += 1
            by_asked["asked" if row.asked else "not asked"][k] += 1
            by_cat[row.category][k] += 1
            carried.update(f for f in CARRIED if row.carries[f])
            if not row.new and row.cat0 != row.cat1:
                relabels.append((r, row))
        total.update(c)
        stale += [(r, i) for i in classes if i not in {row.id for row in rows}]
        per_run.append((r, len(rows), r.versions()[0].words,
                        entry["ruled_in"] if entry else "-", c))

    print(f"{sum(total.values())} items in {len(runs)} runs: {fmt_counts(total, order)}")
    for k in ("asked", "not asked"):
        print(f"  {k:9} {sum(by_asked[k].values()):4}  {fmt_counts(by_asked[k], order)}")
    print("  (asked: a Question or a Collides line in the item's first or last version)")
    print("\ncarrying: " + ", ".join(f"{f} {carried[f]}" for f in CARRIED))

    print("\nby category (first version's; last version's for a new item)")
    for cat, c in sorted(by_cat.items(), key=lambda x: (-sum(x[1].values()), x[0])):
        n = sum(c.values())
        print(f"  {cat:22} {n:4}  culled {c['cull']}/{n}  {fmt_counts(c, order)}")

    print("\nper run")
    for r, n_items, words, ruled_in, c in per_run:
        print(f"  {r.n:>3} {r.project:10} {r.document:32} {n_items:3} items {words:6} words "
              f"{ruled_in:9} {fmt_counts(c, order)}")

    print(f"\nrelabels: {len(relabels)}")
    for r, row in relabels:
        print(f"  {r.n:>3} {row.id:10} {row.cat0} -> {row.cat1}: {row.ruling[:80]}")

    if unmatched:
        print(f"\nruns with no data entry ({len(unmatched)}, their items unclassified):")
        for r in unmatched:
            print(f"  {r.n:>3} {r.project} {r.document} {r.added}")
    if stale:
        print(f"\ndata items with no item in the run's last version ({len(stale)}):")
        for r, i in stale:
            print(f"  {r.n:>3} {r.project} {r.document} {i}")
    return 0


def timeline(lines: list[dict]) -> list[tuple[str, str, str]]:
    """The operator's side of a session: what they typed and answered, and the machine's steps
    between (commits, sub-agents, skills), each with how much the assistant said before it."""
    events = []
    pending: dict[str, tuple[str, list]] = {}
    said: list[str] = []
    for d in main_line(lines):
        ts = d.get("timestamp", "")
        if d.get("type") == "assistant":
            for b in blocks(d):
                if b.get("type") == "text":
                    said.append(b.get("text", ""))
            for name, inp, use_id in tool_uses(d):
                if name == "AskUserQuestion":
                    pending[use_id] = (ts, inp.get("questions", []))
                elif name == "Bash":
                    cmd = inp.get("command") or ""
                    m = COMMIT_MSG_RE.search(cmd)
                    if m and ("riage" in cmd or "slice" in cmd):
                        events.append((ts, "COMMIT", m.group(1)))
                elif name in ("Agent", "Task"):
                    what = (inp.get("description") or "")[:80]
                    kind = inp.get("subagent_type") or inp.get("model") or ""
                    events.append((ts, "SUBAGENT", f"{what} [{kind}]"))
                elif name == "Skill":
                    events.append((ts, "SKILL", str(inp.get("skill"))))
        elif d.get("type") == "user":
            for b in blocks(d):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    asked = pending.pop(b.get("tool_use_id", ""), None)
                    if asked:
                        events += dialog_events(ts, asked, d.get("toolUseResult"))
                    continue
                text = user_text(b)
                if text.startswith("[Request interrupted"):
                    events.append((ts, "INTERRUPT", ""))
                    continue
                if not text or text.startswith(NOT_OPERATOR) or d.get("isMeta"):
                    continue
                if "<command-name>" in text[:200]:
                    m = COMMAND_NAME_RE.search(text)
                    a = COMMAND_ARGS_RE.search(text)
                    events.append((ts, "SLASH", f"{m.group(1) if m else ''} "
                                                f"{a.group(1)[:1500] if a else ''}"))
                    continue
                prev = "".join(said)
                events.append((ts, "ASSISTANT_SAID",
                               f"[{len(prev)} chars since last operator turn] …{prev[-1800:]}"))
                said = []
                more = f" …[+{len(text) - 2500} chars]" if len(text) > 2500 else ""
                events.append((ts, "OPERATOR", text[:2500] + more))
    return events


def dialog_events(ts: str, asked: tuple[str, list], result) -> list[tuple[str, str, str]]:
    asked_at, questions = asked
    answers = result.get("answers") if isinstance(result, dict) else None
    notes = (result.get("annotations") or {}) if isinstance(result, dict) else {}
    out = []
    for q in questions:
        opts = " | ".join(o.get("label", "") for o in q.get("options", []))
        answer = (answers or {}).get(q.get("question"))
        note = (notes.get(q.get("question")) or {}).get("notes")
        out.append((ts, "DIALOG", f"asked {asked_at[11:19]} Q: {q.get('question')}\n"
                                  f"      OPTIONS: {opts}\n"
                                  f"      ANSWER: {answer!r} NOTES: {note!r}"))
    return out


def sessions_of(runs: list[Run], roots: dict[str, Path | None]) -> dict[int, Path | None]:
    missing = sorted({r.project for r in runs if roots.get(r.project) is None})
    if missing:
        raise SystemExit(f"no transcripts for {', '.join(missing)}: pass --transcripts "
                         f"<project>=<dir>")
    return {r.n: pick_session(r, roots[r.project]) for r in runs}


def cmd_sessions(args) -> int:
    runs, roots = selected(args)
    picks = sessions_of(runs, roots)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for r in runs:
        p = picks[r.n]
        if p is None:
            print(f"{r.n:>3} {r.project:10} {r.document:32} no session made its commits")
            continue
        events = timeline(load_transcript(p))
        f = out / f"run{r.n:02}_{r.project}_{Path(r.document).stem}.txt"
        with f.open("w") as fh:
            fh.write(f"# run {r.n} {r.project} {r.document} — session {p.name}\n")
            for ts, kind, text in events:
                fh.write(f"\n[{ts[5:19]}] {kind}: {text}\n")
        kinds = Counter(e[1] for e in events)
        print(f"{r.n:>3} {r.project:10} {r.document:32} {p.name[:8]} "
              f"operator {kinds['OPERATOR']:3} dialogs {kinds['DIALOG']:3} -> {f}")
    return 0


def load_slice_cost():
    spec = importlib.util.spec_from_file_location("slice_cost", TOOLS / "slice_cost.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def priced(sc, lines: list[dict], t0: datetime, t1: datetime) -> float:
    """The priced tokens of the assistant messages in [t0, t1], each message once."""
    seen, total = set(), 0.0
    for d in lines:
        if d.get("type") != "assistant":
            continue
        t = parse_ts(d.get("timestamp"))
        if t is None or not t0 <= t <= t1:
            continue
        msg = d.get("message") or {}
        if msg.get("id") is not None:
            if msg["id"] in seen:
                continue
            seen.add(msg["id"])
        usage = msg.get("usage") or {}
        total += sc.cost_for(msg.get("model", ""),
                             {k: int(usage.get(v, 0) or 0) for k, v in sc.USAGE_KEYS.items()})
    return total


def triage_start(main: list[dict]) -> datetime | None:
    for d in main:
        for b in blocks(d):
            if d.get("type") == "user" and "<command-name>/dev:triage" in user_text(b):
                return parse_ts(d.get("timestamp"))
        if any(name == "Skill" and "triage" in str(inp.get("skill"))
               for name, inp, _ in tool_uses(d)):
            return parse_ts(d.get("timestamp"))
    return None


def operator_seconds(main: list[dict], t0: datetime, t1: datetime) -> float:
    """Operator latency in [t0, t1]: from the last assistant event to the operator's next message,
    and from an AskUserQuestion to its answer."""
    last_assistant, asked, waits = None, {}, []
    for d in main:
        t = parse_ts(d.get("timestamp"))
        if t is None or not t0 <= t <= t1:
            continue
        if d.get("type") == "assistant":
            last_assistant = t
            asked.update((use_id, t) for name, _, use_id in tool_uses(d)
                         if name == "AskUserQuestion")
        elif d.get("type") == "user":
            for b in blocks(d):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    if b.get("tool_use_id") in asked:
                        waits.append((t - asked.pop(b["tool_use_id"])).total_seconds())
                    continue
                text = user_text(b)
                if (not text or text.startswith((*NOT_OPERATOR, "<command-name>"))
                        or d.get("isMeta")):
                    continue
                if last_assistant and t > t0:
                    waits.append((t - last_assistant).total_seconds())
    return sum(w for w in waits if w > 0)


def cmd_cost(args) -> int:
    runs, roots = selected(args)
    sc = load_slice_cost()
    picks = sessions_of(runs, roots)
    print(f"{'n':>3} {'project':10} {'document':32} {'items':>5} {'words':>6} {'wall':>5} "
          f"{'oper':>5} {'mach':>5} {'$main':>7} {'$sub':>6}")
    tot = Counter()
    for r in runs:
        head = f"{r.n:>3} {r.project:10} {r.document:32}"
        p = picks[r.n]
        lines = load_transcript(p) if p else []
        main = main_line(lines)
        t0 = triage_start(main)
        if t0 is None:
            print(f"{head} {'no session' if p is None else 'no /dev:triage in ' + p.name[:8]}")
            continue
        t1 = r.end.astimezone(UTC) + END_GRACE
        wall = (t1 - t0).total_seconds() / 60
        oper = operator_seconds(main, t0, t1) / 60
        cost_main = priced(sc, lines, t0, t1)
        cost_sub = sum(priced(sc, load_transcript(f), t0, t1)
                       for f in sorted((p.with_suffix("") / "subagents").glob("*.jsonl")))
        words = r.versions()[0].words
        print(f"{head} {len(r.rows()):>5} {words:>6} {wall:>5.0f} {oper:>5.0f} "
              f"{wall - oper:>5.0f} {cost_main:>7.2f} {cost_sub:>6.2f}")
        tot.update(wall=wall, oper=oper, main=cost_main, sub=cost_sub)
    print(f"\ntotal: wall {tot['wall']:.0f} min = operator {tot['oper']:.0f} + machine "
          f"{tot['wall'] - tot['oper']:.0f}; cost ${tot['main'] + tot['sub']:.2f} "
          f"(main ${tot['main']:.2f}, sub-agents ${tot['sub']:.2f})")
    return 0


def main(argv: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("repos", nargs="+", metavar="spec-repo")
    common.add_argument("--since", default="2026-08-28")
    common.add_argument("--last", type=int, default=20)
    common.add_argument("--transcripts", action="append", default=[],
                        metavar="PROJECT=DIR")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("runs", parents=[common]).set_defaults(fn=cmd_runs)
    p = sub.add_parser("rulings", parents=[common])
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.set_defaults(fn=cmd_rulings)
    p = sub.add_parser("sessions", parents=[common])
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_sessions)
    sub.add_parser("cost", parents=[common]).set_defaults(fn=cmd_cost)
    args = ap.parse_args(argv[1:])
    try:
        return args.fn(args)
    except subprocess.CalledProcessError as e:
        print(f"{' '.join(e.cmd)}: {e.stderr.strip()}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
