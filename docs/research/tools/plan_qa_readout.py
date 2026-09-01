#!/usr/bin/env python3
"""Read the operator interaction of every /dev:plan-slice session.

Walks the interactive transcripts under ~/.claude/projects/<project>/ that invoked
``/dev:plan-slice``, and extracts, in order, every AskUserQuestion dialog (the questions, the
options, which was marked Recommended, and what the operator answered), every free-text operator
message, and the plan-loop launches that split a session into the pre-loop interview and the
post-loop adjudication.

    plan_qa_readout.py table            # one row per slice: dialogs, questions, answer classes
    plan_qa_readout.py dump <out-dir>   # one markdown file per slice with every dialog verbatim
    plan_qa_readout.py stats            # the aggregate numbers behind the readout

Answer classes per question: ``rec`` (picked the option marked Recommended), ``alt`` (picked
another option while one was marked Recommended), ``pick`` (picked an option, none marked),
``custom`` (typed their own answer via Other), ``none`` (the dialog was dismissed or interrupted).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PROJECTS = {
    "KubeCoder": Path.home() / ".claude/projects/-work-KubeCoder",
    "Ansible": Path.home() / ".claude/projects/-work-Ansible",
}
INVOKE_MARK = "<command-name>/dev:plan-slice"
ARGS_RE = re.compile(r"<command-args>([^<]*)</command-args>")
SLICE_RE = re.compile(r"(\d{3}[a-z]?)")
REC_RE = re.compile(r"\(recommended\)", re.I)
IDENT_RE = re.compile(
    r"(?<![\w/])(?:[RFVDOPSAB]\d{1,3}[a-z]?|#\d{3,4}|§\s?\d|[\w./-]+\.\w+:\d+)(?![\w-])"
)
BAIL_WORDS = re.compile(
    r"\b(just pick|you pick|you decide|you choose|your call|don't ask|do not ask|stop asking|"
    r"no q&a|talk|discuss|i don't know|no idea|faintest|don't care|whatever you)\b",
    re.I,
)


@dataclass
class Question:
    header: str
    question: str
    options: list[dict]
    multi: bool
    answer: str | None = None
    preview: bool = False
    notes: str | None = None  # free text the operator typed beside (or instead of) a selection

    @property
    def rec_label(self) -> str | None:
        for o in self.options:
            if REC_RE.search(o.get("label", "")):
                return o["label"]
        return None

    @property
    def klass(self) -> str:
        if self.answer is None:
            return "none"
        if self.answer == "(notes only)":
            return "custom"
        labels = {o.get("label", "") for o in self.options}
        parts = [self.answer] if not self.multi else [p.strip() for p in self.answer.split(", ")]
        if self.multi:
            # multi-select: every part a label → pick; else custom
            if all(p in labels for p in parts):
                return "pick"
            return "custom"
        if self.answer in labels:
            rec = self.rec_label
            if rec is None:
                return "pick"
            return "rec" if self.answer == rec else "alt"
        return "custom"

    @property
    def amended(self) -> bool:
        """An option was picked *and* the operator typed a note beside it."""
        return self.klass in {"rec", "alt", "pick"} and bool(self.notes)

    @property
    def identifiers(self) -> int:
        """Slice-internal handles the question leans on: R1/F2/V12/D191/#724/§4.3/file:line."""
        return len(IDENT_RE.findall(self.question))

    @property
    def option_chars(self) -> int:
        return sum(len(o.get("label", "")) + len(o.get("description", "")) for o in self.options)


@dataclass
class Dialog:
    ts: str
    stage: str  # pre | post | after (before loop, after an exit-4, after exit 0)
    questions: list[Question]
    preceding_assistant_chars: int
    interrupted: bool = False
    answered_at: str = ""

    @property
    def kind(self) -> str:
        """interview (pre-loop) | writer-q (post-loop, plan-writer questions) | adjudication
        (post-loop, plan-reviewer findings — F-numbered or accept/reject shaped)."""
        if self.stage == "pre":
            return "interview"
        txt = " ".join(q.header + " " + q.question for q in self.questions)
        labels = " ".join(o.get("label", "") for q in self.questions for o in q.options)
        if re.search(r"\bF\d\b", txt) or re.search(r"\b(accept|reject)\b", labels, re.I) \
                or re.search(r"\b(review|reviewer|finding|advisor)", txt, re.I):
            return "adjudication"
        return "writer-q"

    @property
    def latency_s(self) -> float | None:
        if not self.answered_at or not self.ts:
            return None
        from datetime import datetime
        f = "%Y-%m-%dT%H:%M:%S.%fZ"
        try:
            a, b = datetime.strptime(self.answered_at, f), datetime.strptime(self.ts, f)
            return (a - b).total_seconds()
        except ValueError:
            return None


@dataclass
class OperatorMsg:
    ts: str
    stage: str
    text: str
    after_dialog: bool  # immediately follows a dismissed dialog


@dataclass
class Session:
    project: str
    file: Path
    slice_id: str
    started: str
    events: list = field(default_factory=list)  # Dialog | OperatorMsg | ("loop", ts)


def _content_blocks(msg: dict) -> list:
    c = (msg.get("message") or {}).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c if isinstance(c, list) else []


def _text_of(block) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text", "")
        c = block.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(_text_of(x) for x in c)
    return ""


def parse_session(project: str, path: Path) -> Session | None:
    lines = []
    for raw in path.open():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    slice_id = "?"
    started = ""
    for d in lines:
        if d.get("type") != "user":
            continue
        for b in _content_blocks(d):
            t = _text_of(b)
            if INVOKE_MARK in t:
                m = ARGS_RE.search(t)
                arg = (m.group(1) if m else "").strip()
                sm = SLICE_RE.search(arg)
                started = started or d.get("timestamp", "")
                if sm:
                    slice_id = sm.group(1)
                    break
        if slice_id != "?":
            break
    if not started:
        return None
    sess = Session(project, path, slice_id, started)
    stage = "pre"
    pending: dict[str, Dialog] = {}
    last_assistant_chars = 0
    last_dialog_dismissed = False
    for d in lines:
        if d.get("isSidechain"):
            continue
        typ = d.get("type")
        ts = d.get("timestamp", "")
        if typ == "assistant":
            for b in _content_blocks(d):
                if b.get("type") == "text":
                    last_assistant_chars += len(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    name = b.get("name")
                    inp = b.get("input") or {}
                    if name == "AskUserQuestion":
                        qs = [
                            Question(
                                q.get("header", ""),
                                q.get("question", ""),
                                q.get("options", []),
                                bool(q.get("multiSelect")),
                                preview=any("preview" in o for o in q.get("options", [])),
                            )
                            for q in inp.get("questions", [])
                        ]
                        dlg = Dialog(ts, stage, qs, last_assistant_chars)
                        pending[b["id"]] = dlg
                        sess.events.append(dlg)
                        last_assistant_chars = 0
                    elif name == "Bash" and "plan_loop.py" in (inp.get("command") or ""):
                        cmd = inp["command"]
                        if " run " in cmd or cmd.rstrip().endswith("run"):
                            sess.events.append(("loop", ts, cmd.strip()[:120]))
                            stage = "post"
                            last_assistant_chars = 0
        elif typ == "user":
            blocks = _content_blocks(d)
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    dlg = pending.pop(b.get("tool_use_id", ""), None)
                    if dlg is None:
                        continue
                    tur = d.get("toolUseResult")
                    answers = tur.get("answers") if isinstance(tur, dict) else None
                    if answers:
                        notes = tur.get("annotations") or {}
                        dlg.answered_at = ts
                        for q in dlg.questions:
                            q.answer = answers.get(q.question)
                            q.notes = (notes.get(q.question) or {}).get("notes") or None
                        last_dialog_dismissed = any(q.answer is None for q in dlg.questions)
                    else:
                        dlg.interrupted = True
                        last_dialog_dismissed = True
                    continue
                t = _text_of(b).strip()
                if not t:
                    continue
                if t.startswith("<command-name>") or t.startswith("<local-command"):
                    continue
                if t.startswith("<system-reminder>") and "</system-reminder>" in t:
                    t2 = re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S)
                    t2 = t2.strip()
                    if not t2:
                        continue
                    t = t2
                if t.startswith("[Request interrupted"):
                    # a dismissed dialog surfaces as this marker before the operator's text
                    if pending:
                        for dlg in pending.values():
                            dlg.interrupted = True
                        pending.clear()
                        last_dialog_dismissed = True
                    continue
                if t.startswith("<task-notification>") or t.startswith("<persisted"):
                    continue
                sess.events.append(OperatorMsg(ts, stage, t, last_dialog_dismissed))
                last_dialog_dismissed = False
                last_assistant_chars = 0
    for dlg in pending.values():
        dlg.interrupted = True
    return sess


def load_all() -> list[Session]:
    out = []
    for project, root in PROJECTS.items():
        if not root.exists():
            continue
        for f in sorted(root.glob("*.jsonl")):
            try:
                if INVOKE_MARK not in f.read_text(errors="replace"):
                    continue
            except OSError:
                continue
            s = parse_session(project, f)
            if s:
                out.append(s)
    out.sort(key=lambda s: s.started)
    return out


def by_slice(sessions: list[Session]) -> dict[tuple[str, str], list[Session]]:
    g: dict[tuple[str, str], list[Session]] = defaultdict(list)
    for s in sessions:
        g[(s.project, s.slice_id)].append(s)
    return dict(sorted(g.items(), key=lambda kv: min(s.started for s in kv[1])))


def cmd_table(sessions: list[Session]) -> None:
    print(
        "| proj | slice | date | sess | dialogs pre/post | Qs | rec | alt | pick | custom | none |"
        " op msgs | bails |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (proj, sid), ss in by_slice(sessions).items():
        dlgs = [e for s in ss for e in s.events if isinstance(e, Dialog)]
        msgs = [e for s in ss for e in s.events if isinstance(e, OperatorMsg)]
        qs = [q for d in dlgs for q in d.questions]
        cls = Counter(q.klass for q in qs)
        pre = sum(1 for d in dlgs if d.stage == "pre")
        post = len(dlgs) - pre
        bails = sum(1 for m in msgs if m.after_dialog or BAIL_WORDS.search(m.text))
        print(
            f"| {proj[:4]} | {sid} | {ss[0].started[:10]} | {len(ss)} | {pre}/{post} | {len(qs)} |"
            f" {cls['rec']} | {cls['alt']} | {cls['pick']} | {cls['custom']} | {cls['none']} |"
            f" {len(msgs)} | {bails} |"
        )


def cmd_stats(sessions: list[Session]) -> None:
    dlgs = [e for s in sessions for e in s.events if isinstance(e, Dialog)]
    qs = [q for d in dlgs for q in d.questions]
    cls = Counter(q.klass for q in qs)
    n = len(qs)
    print(f"sessions {len(sessions)}, slices {len(by_slice(sessions))}, dialogs {len(dlgs)}, "
          f"questions {n}")
    print("answer classes:", dict(cls))
    withrec = [q for q in qs if q.rec_label]
    print(f"questions with a Recommended option: {len(withrec)}/{n}")
    if withrec:
        c = Counter(q.klass for q in withrec)
        print("  of those: ", dict(c),
              f" → deviation (alt+custom) {(c['alt'] + c['custom']) / len(withrec):.0%}")
    norec = [q for q in qs if not q.rec_label]
    if norec:
        c = Counter(q.klass for q in norec)
        print(f"questions without a Recommended option: {len(norec)}: ", dict(c))
    for stage in ("pre", "post"):
        sq = [q for d in dlgs if d.stage == stage for q in d.questions]
        c = Counter(q.klass for q in sq)
        wr = [q for q in sq if q.rec_label]
        cw = Counter(q.klass for q in wr)
        dev = (cw["alt"] + cw["custom"]) / len(wr) if wr else 0
        print(f"stage {stage}: dialogs {sum(1 for d in dlgs if d.stage == stage)}, questions "
              f"{len(sq)}, classes {dict(c)}, with-rec {len(wr)} deviation {dev:.0%}")
    opts = Counter(len(q.options) for q in qs)
    print("options per question:", dict(sorted(opts.items())))
    print("questions per dialog:", dict(sorted(Counter(len(d.questions) for d in dlgs).items())))
    chars = sorted(q.option_chars for q in qs)
    if chars:
        print(f"option text per question (chars): median {chars[len(chars) // 2]}, "
              f"p90 {chars[int(len(chars) * 0.9)]}, max {chars[-1]}")
    pre_chars = sorted(d.preceding_assistant_chars for d in dlgs)
    if pre_chars:
        print(f"assistant prose before a dialog (chars): median {pre_chars[len(pre_chars) // 2]}, "
              f"p90 {pre_chars[int(len(pre_chars) * 0.9)]}")
    kinds = Counter(d.kind for d in dlgs)
    print("dialog kinds:", dict(kinds))
    for k in ("interview", "writer-q", "adjudication"):
        kq = [q for d in dlgs if d.kind == k for q in d.questions]
        wr = [q for q in kq if q.rec_label]
        cw = Counter(q.klass for q in wr)
        dev = (cw["alt"] + cw["custom"]) / len(wr) if wr else 0
        print(f"  {k}: questions {len(kq)}, classes {dict(Counter(q.klass for q in kq))}, "
              f"with-rec {len(wr)} deviation {dev:.0%}")
    noted = [q for q in qs if q.notes]
    print(f"questions where the operator typed notes: {len(noted)} "
          f"(beside a pick: {sum(1 for q in noted if q.amended)}, notes only: "
          f"{sum(1 for q in noted if q.answer == '(notes only)')})")
    idq = [q for q in qs if q.identifiers]
    print(f"questions leaning on slice-internal handles (R1/F2/V12/D191/#724/§/file:line): "
          f"{len(idq)}/{n}; median handles among those "
          f"{sorted(q.identifiers for q in idq)[len(idq) // 2] if idq else 0}")
    code = sum(1 for q in qs for o in q.options if "`" in o.get("description", ""))
    print(f"options carrying inline code (backticks): {code} of {sum(len(q.options) for q in qs)}")
    lat = sorted(d.latency_s for d in dlgs if d.latency_s)
    if lat:
        print(f"answer latency per dialog (min): median {lat[len(lat) // 2] / 60:.1f}, "
              f"p90 {lat[int(len(lat) * 0.9)] / 60:.1f}, max {lat[-1] / 60:.0f}")
    inter = sum(1 for d in dlgs if d.interrupted)
    print(f"dialogs dismissed/interrupted: {inter}")
    msgs = [e for s in sessions for e in s.events if isinstance(e, OperatorMsg)]
    print(f"operator free-text messages: {len(msgs)}; after a dismissed dialog: "
          f"{sum(1 for m in msgs if m.after_dialog)}; bail-worded: "
          f"{sum(1 for m in msgs if BAIL_WORDS.search(m.text))}")
    # two-option accept/reject questions
    ar = [q for q in qs if len(q.options) == 2 and any(
        re.match(r"(accept|reject|yes|no)\b", o.get('label', ''), re.I) for o in q.options)]
    print(f"two-option accept/reject-shaped questions: {len(ar)}: "
          f"{dict(Counter(q.klass for q in ar))}")


def cmd_dump(sessions: list[Session], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for (proj, sid), ss in by_slice(sessions).items():
        lines = [f"# {proj} slice {sid}", ""]
        for s in ss:
            lines.append(f"## session {s.file.stem[:8]} started {s.started}")
            lines.append("")
            for e in s.events:
                if isinstance(e, tuple):
                    lines.append(f"**[{e[1][11:19]}] LOOP LAUNCH** `{e[2]}`")
                    lines.append("")
                elif isinstance(e, OperatorMsg):
                    flag = " (after dismissed dialog)" if e.after_dialog else ""
                    lines.append(f"**[{e.ts[11:19]}] OPERATOR ({e.stage}){flag}:**")
                    lines.append("")
                    lines.append("> " + e.text[:1500].replace("\n", "\n> "))
                    lines.append("")
                elif isinstance(e, Dialog):
                    tag = " INTERRUPTED" if e.interrupted else ""
                    lat = f", answered after {e.latency_s / 60:.1f} min" if e.latency_s else ""
                    lines.append(
                        f"**[{e.ts[11:19]}] DIALOG ({e.kind}){tag}** — {len(e.questions)} q, "
                        f"{e.preceding_assistant_chars} chars of assistant prose before it{lat}"
                    )
                    lines.append("")
                    for i, q in enumerate(e.questions, 1):
                        lines.append(f"- Q{i} [{q.header}] ({q.klass}) {q.question}")
                        for o in q.options:
                            mark = "★" if REC_RE.search(o.get("label", "")) else "·"
                            lines.append(f"    - {mark} **{o.get('label', '')}** — "
                                         f"{o.get('description', '')[:400]}")
                        lines.append(f"    - → **answer:** {q.answer!r}")
                        if q.notes:
                            lines.append(f"    - → **operator notes:** {q.notes!r}")
                    lines.append("")
        (out_dir / f"{proj}_{sid}.md").write_text("\n".join(lines))
    print(f"wrote {len(by_slice(sessions))} files to {out_dir}")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"table", "dump", "stats"}:
        print(__doc__)
        return 2
    sessions = load_all()
    if argv[1] == "table":
        cmd_table(sessions)
    elif argv[1] == "stats":
        cmd_stats(sessions)
    else:
        cmd_dump(sessions, Path(argv[2] if len(argv) > 2 else "tmp/plan-qa"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
