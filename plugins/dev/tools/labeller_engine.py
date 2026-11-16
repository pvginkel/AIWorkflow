"""The labeller's transcript engine: one transcript's labels, whole or from its boundary on.

Part 4 of the labeller (`docs/labeller.md` § Modules and build parts). `labeller.py`'s
`label_batch` calls `label_one(item, tie, records)` once per transcript and writes the line it
returns; `LabelError(code, message)` is an error line instead (§ Running it, the codes).

The engine reads the transcript's lines from a byte, assembles its turns with
`turn_profile.Replay` and classes them with `turn_profile.TurnClassifier`, so a Call's class is
`classify_turns`' for the file. It matches the collector's Calls by `message.id`, applies Part 3's
rules (`labeller_tools`) to every Tool Call and Part 2's tie (`labeller_records`) to every
Launch, and keeps what spans calls itself: the wait causes, the Segments, the background tasks
still running, the background CI waits still open, settledness, the boundary and the checkpoint.

**One engine.** A whole labelling is the appended path run from byte 0 with an empty state. An
appended one starts at the boundary with the checkpoint's state, which is the state a whole run
had at that byte, so the parts give what the whole gives. A Call is settled, and stands before a
boundary, once no later line can change its labels: the lines that touch a turn — a call added
to it, a result for its tools or attributed to it, the text that marks it `notified`, the match
or close of its background CI wait — all come before the next Call's first line. The boundary is
the latest counted Call before which every turn is settled at that Call's first line; a turn
still touched after it, or a CI wait still open there, holds the boundary back to its own Call.
A result for a call still owed one at the boundary, arriving in a later part, is `behind`.

Stdlib only.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import turn_profile as tp  # noqa: E402

CONTRACT = 1
CHECKPOINT_FORMAT = "1"
CHECKPOINT_CAP = 256 * 1024        # past this the checkpoint is not handed back
CI_UNREAD_BOUND = 20               # Calls after its notification a background CI wait stays open
BG_WAIT_TOOLS = {"TaskOutput", "BashOutput", "Monitor"}
# § The labels, by entity, *Segment*: a Call's class -> its Segment's kind.
CLS_KIND = {"orient-read": "start", "gate": "gate", "commit": "records", "record": "records",
            "wait": "wait"}
OTHER_KIND = "work"
READ_CLASSES = set(tp.READ_CLASSES)
AVOIDABLE_CLASSES = {"retry", "fumble"}

# The gap before a later Launch of a Pilot conversation (t17-labeller-2.md D6, ruled 2026-11-16),
# from the Holds and Turns Pilot hands with each Session: `hold` where a Hold overlaps it, else
# `person` where a Turn of one of these causes started the Launch, else `driver`.
PERSON_CAUSES = frozenset({"person", "continuation", "resume"})
TURN_SLACK_S = 5.0     # a Launch's Turn: started at or before its start + 5 s, as its Session

NOTE_TAG_RE = {tag: re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.S)
               for tag in ("task-id", "tool-use-id", "output-file")}
INF = float("inf")

# Set by a test to stand in for Part 3's module.
TOOLS = None


class LabelError(Exception):
    """A transcript that cannot be labelled: an error line with `code` (`unreadable`,
    `calls_mismatch`, `internal`) and `message`, its `detail`."""

    def __init__(self, code: str, message: str):
        super().__init__(code, message)
        self.code, self.message = code, message


class _Whole(Exception):
    """An appended request that cannot go on from its checkpoint: the answer `whole`."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def _tools():
    if TOOLS is not None:
        return TOOLS
    import labeller_tools
    return labeller_tools


def _version() -> str:
    import labeller_records
    return labeller_records.plugin_version()


# ---------------------------------------------------------------------------
# The entry


TRANSCRIPT_EXTRAS = ("session_id", "file", "stamp", "conversation", "pilot", "restamp", "size")


def label_one(item: dict, tie, records) -> dict:
    """One transcript's answer line (§ The label request and answer): its labels, whole or
    from its boundary on, or the answer `whole` with its `why`."""
    path = Path(item["file"])
    try:
        fh = path.open("rb")
    except OSError as e:
        raise LabelError("unreadable", f"{item.get('path') or path}: {e}") from e
    if isinstance(item.get("size"), int):
        fh = _Prefix(fh, item["size"])
    with fh:
        stamp, tie = _restamped(item, tie, records, path)
        job = _Job(item, tie, records, stamp)
        if item.get("mode") == "appended":
            try:
                ck = job.checkpoint_in(fh)
                run = job.run(fh, ck)
            except _Whole as w:
                return {"session_id": job.sid, "agent_id": job.aid, "answer": "whole",
                        "why": w.why}
        else:
            run = job.run(fh, None)
    return job.answer(run)


def _restamped(item: dict, tie, records, path: Path):
    """(stamp, tie), re-tied with the slices the file's own content names where only that can
    tie it (the adoption rules R2 to R5): Part 2 reads them (`read_facts`,
    `named_from_facts`), and Part 1's `restamp` gives the stamp and tie for them."""
    stamp = item.get("stamp")
    needs = getattr(records, "needs_facts", None)
    conv = item.get("conversation") or {}
    transcript = {k: v for k, v in item.items() if k not in TRANSCRIPT_EXTRAS}
    if needs is None or item.get("restamp") is None or not needs(conv, transcript):
        return stamp, tie
    import labeller_records
    named = list(records.named_from_facts(labeller_records.read_facts(path, item.get("size"))))
    if not named:
        return stamp, tie
    return item["restamp"](named)


# ---------------------------------------------------------------------------
# The job: what the request, the context and the tie say of one transcript


class _Job:
    def __init__(self, item: dict, tie, records, stamp):
        self.item, self.tie, self.records, self.stamp = item, tie, records, stamp
        self.sid = item["session_id"]
        self.aid = item.get("agent_id")
        self.main = self.aid is None
        self.version = _version()
        self.tools = _tools()
        conv = item.get("conversation") or {}
        self.conv = conv
        role = getattr(tie, "role", None)
        if role:
            import slice_cost
            self.flags = slice_cost.turn_flags(role)
        else:
            self.flags = {}
        calls = [c for c in item.get("calls") or [] if isinstance(c, dict)]
        self.calls = sorted(calls, key=lambda c: c.get("position") or 0)
        self.launch_of = {c.get("id"): c.get("launch") for c in self.calls}
        self.launches = sorted((x for x in item.get("launches") or [] if isinstance(x, dict)),
                               key=lambda x: x.get("n") or 0)
        rule = getattr(tie, "rule", None)
        self.dispatch = rule == "dispatch"
        self.records_know = rule in ("dispatch", "stage")
        self.pilot_knows = bool(conv.get("sessions")) or self.sid in (item.get("pilot") or ())
        self.launch_start = {x.get("n"): _epoch(x.get("started_at")) for x in self.launches}
        self.unit_of = {}
        if self.main:
            for x in self.launches:
                self.unit_of[x.get("n")] = tie.unit_for(x.get("started_at"))
        # the Launches whose first Call carries the opening prompt's digest sections
        self.digest_launches = {n for n, u in self.unit_of.items() if u and self.dispatch}
        self.spec_repos = frozenset()
        if getattr(self.tools, "ADD_ALL_ONLY_IN_SPEC_REPO", False):
            self.spec_repos = frozenset(getattr(records, "spec_repos", None) or ())

    def pilot_wait(self, launch: int | None) -> str | None:
        """The wait cause of a later Launch of a Pilot conversation (D6): `hold` where one of
        its Sessions' Holds overlaps the gap before it, from the start of the Turn before the
        Launch's own, else `person` where the Launch's Turn has a person's cause
        (`PERSON_CAUSES`), else `driver`. The Launch's Turn is the latest of the conversation's
        Turns started at or before the Launch's start + 5 s. None where Pilot handed no Turn,
        or none that started it: a request without them keeps the cause unknown."""
        at = self.launch_start.get(launch)
        if at is None:
            return None
        turns, holds = [], []
        for s in self.conv.get("sessions") or []:
            if not isinstance(s, dict):
                continue
            for t in s.get("turns") or []:
                if isinstance(t, dict) and (t0 := _epoch(t.get("started_at"))) is not None:
                    turns.append((t0, t.get("cause")))
            for h in s.get("holds") or []:
                if isinstance(h, dict) and (h0 := _epoch(h.get("started_at"))) is not None:
                    h1 = _epoch(h.get("ended_at"))
                    holds.append((h0, INF if h1 is None else h1))
        turns.sort(key=lambda t: t[0])
        k = next((i for i in range(len(turns) - 1, -1, -1)
                  if turns[i][0] <= at + TURN_SLACK_S), None)
        if k is None:
            return None
        since = turns[k - 1][0] if k > 0 else turns[k][0]
        if any(h0 < at and h1 > since for h0, h1 in holds):
            return "hold"
        return "person" if turns[k][1] in PERSON_CAUSES else "driver"

    # -- the checkpoint

    def checkpoint_in(self, fh) -> dict:
        """The handed checkpoint, checked against the request and the file, or `_Whole`."""
        ck = decode_checkpoint(self.item.get("checkpoint"), self.version)
        frm = self.item.get("from") or {}
        if (ck is None or [ck.get("session_id"), ck.get("agent_id")] != [self.sid, self.aid]
                or ck.get("boundary") != {"call": frm.get("call"), "byte": frm.get("byte")}):
            raise _Whole("checkpoint")
        if ck.get("stamp") != self.stamp:
            raise _Whole("stamp")
        byte = ck["boundary"]["byte"]
        if not isinstance(byte, int) or byte < 0 or _line_call(fh, byte) != ck["boundary"]["call"]:
            raise _Whole("boundary")
        if not self.calls or self.calls[0].get("id") != ck["boundary"]["call"]:
            raise _Whole("calls")
        return ck

    def checkpoint_out(self, ck: dict) -> str | None:
        return encode_checkpoint(ck, self.version)

    # -- the run

    def run(self, fh, ck: dict | None) -> _Run:
        r = _Run(self, ck)
        r.read(fh, ck["boundary"]["byte"] if ck else 0)
        r.finish()
        handed = [c.get("id") for c in self.calls]
        if r.calls_read != handed:
            k = next((k for k, (a, b) in enumerate(zip(r.calls_read, handed, strict=False))
                      if a != b), min(len(r.calls_read), len(handed)))
            got = r.calls_read[k] if k < len(r.calls_read) else None
            want = handed[k] if k < len(handed) else None
            if ck is not None:
                raise _Whole("calls")
            raise LabelError("calls_mismatch",
                             f"Call {k + 1}: handed {want!r}, the file has {got!r}")
        return r

    # -- the answer

    def answer(self, r: _Run) -> dict:
        tie = self.tie
        out_calls, tool_rows, events, parts, test_runs, ci_waits = [], [], [], [], [], []
        suites: dict[str, dict] = {}
        builds: dict[tuple, dict] = {}
        for c in self.calls:
            mid = c.get("id")
            t = r.by_id.get(mid)
            row = {"id": mid, "segment": r.segment_of.get(mid), "call_class": None,
                   "avoidable_kind": None, "batchable_condition": None, "wait_cause": None}
            if t is not None:
                rec = t["_rec"]
                cls = rec["cls"]
                row["call_class"] = cls
                row["avoidable_kind"] = (cls if cls in AVOIDABLE_CLASSES else
                                         "batchable" if rec.get("batchable_strict") else None)
                if cls in READ_CLASSES:
                    row["batchable_condition"] = rec.get("batchable_why")
                row["wait_cause"] = t["_wake"]
                parts += [{"call": mid, "kind": "digest_section", "name": s["name"],
                           "characters": s["characters"]} for s in t.get("_parts") or ()]
                for tool in t["tools"]:
                    lab = tool.get("_lab") or {}
                    if (lab.get("command_class") or lab.get("effect_kind")
                            or lab.get("effect_subject") or lab.get("rules")):
                        tool_rows.append({"tool_use_id": tool["id"],
                                          "command_class": lab.get("command_class"),
                                          "effect_kind": lab.get("effect_kind"),
                                          "effect_subject": lab.get("effect_subject"),
                                          "rules": list(lab.get("rules") or [])})
                    events += [{"call": mid, **e} for e in lab.get("events") or ()]
                    test_runs += [{"tool_use_id": tool["id"], **x}
                                  for x in lab.get("test_runs") or ()]
                    for s in lab.get("test_suites") or ():
                        suites[s["code"]] = dict(s)
                    for b in tool.get("_ci") or ():
                        ci_waits.append({"tool_use_id": tool["id"], "job": b["job"],
                                         "number": b["number"]})
                        builds[(b["job"], b["number"])] = dict(b)
            out_calls.append(row)
        anchors = tuple(getattr(tie, "anchors", ()) or ())
        for stage_key in anchors:
            if hasattr(self.records, "test_runs"):
                test_runs += self.records.test_runs(stage_key)
        launches = [{"n": x.get("n"), "work_unit": self.unit_of.get(x.get("n"))}
                    for x in self.launches] if self.main else []
        labels = {
            "transcript": ([{"adopted_group": getattr(tie, "adopted_group", None)}]
                           if self.main else []),
            "launches": launches,
            "calls": out_calls,
            "segments": r.segments,
            "tool_calls": tool_rows,
            "events": events,
            "context_parts": parts,
            "test_runs": test_runs,
            "ci_waits": ci_waits,
            "documents": document_labels(self.conv, tie) if self.main else [],
        }
        units = self._units([x["work_unit"] for x in launches if x["work_unit"]], anchors)
        boundary = None
        checkpoint = None
        if r.boundary is not None:
            boundary = {"call": r.boundary["call"], "byte": r.boundary["byte"]}
            checkpoint = self.checkpoint_out(r.boundary)
        return {"session_id": self.sid, "agent_id": self.aid, "answer": "labels",
                "stamp": self.stamp, "boundary": boundary, "checkpoint": checkpoint,
                "labels": labels, "units": units, "test_suites": list(suites.values()),
                "ci_builds": list(builds.values())}

    def _units(self, keys: list[str], anchors: tuple) -> list[dict]:
        """Every unit the labels name and every one above them; on an anchor every unit of its
        stage. A unit's `part_of` and `occasioned_by` stand before it, as Part 2 orders them."""
        rows: list[dict] = []
        if keys:
            rows += self.records.unit_rows(keys)
        for stage_key in anchors:
            rows += self.records.stage_rows(stage_key)
        seen: set = set()
        out = []
        for row in rows:
            if row.get("key") not in seen:
                seen.add(row.get("key"))
                out.append(row)
        return out


# ---------------------------------------------------------------------------
# The run: one pass over the lines from a byte


def _empty_wake() -> dict:
    return {"person": False, "note": False, "last": None, "digest": None}


class _Run(tp.Replay):
    """The lines from a byte, assembled as `replay` does, with what the labels need beside."""

    def __init__(self, job: _Job, ck: dict | None):
        super().__init__(first_i=(ck["turns"] + 1) if ck else 1)
        self.job = job
        self.ck = ck
        self.byte = 0
        self.calls_read: list[str] = []      # every message id, in order of its first line
        self.first_byte: dict[str, int] = {}
        self.snaps: dict[str, dict] = {}      # message id -> the state at its first line
        self.wake = dict(ck["wake"]) if ck else _empty_wake()
        self.ck_prev = ck["prev"] if ck else None   # the Call before the part: tools, launch
        self.seen = bool(ck["seen"]) if ck else False
        self.tasks: list[dict] = [dict(x) for x in ck["tasks"]] if ck else []
        self.owed: set[str] = set(ck["owed"]) if ck else set()
        self.stretches: list[dict] = []
        self.boundary: dict | None = None
        self.segments: list[dict] = []
        self.segment_of: dict[str, int] = {}

    # -- reading

    def read(self, fh, start: int) -> None:
        fh.seek(start)
        pos = start
        for raw in fh:
            self.byte = pos
            pos += len(raw)
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(o, dict):
                continue
            if o.get("type") == "assistant":
                self._call_line(o)
            self.feed(o)

    def _call_line(self, o: dict) -> None:
        msg = o.get("message")
        mid = msg.get("id") if isinstance(msg, dict) else None
        if not isinstance(mid, str) or not mid or mid in self.first_byte:
            return
        if msg.get("model") != tp.SYNTHETIC_MODEL:
            self.snaps[mid] = self._snapshot()
        self.first_byte[mid] = self.byte
        self.calls_read.append(mid)

    def _snapshot(self) -> dict:
        """The state a part starting at this line goes on from (the classifier's and the
        Segments' are taken in `finish`)."""
        tools, launch = self._prev()
        return {"turns": self.first_i - 1 + len(self.turns), "wake": dict(self.wake),
                "prev": {"tools": tools, "launch": launch}, "seen": self.seen,
                "tasks": [dict(x) for x in self.tasks],
                "owed": sorted(self.owed | {k for k in self.pending if isinstance(k, str)})}

    def _prev(self) -> tuple[list[str], int | None]:
        if self.turns:
            t = self.turns[-1]
            return [r["name"] for r in t["tools"]], t.get("_launch")
        if self.ck_prev:
            return list(self.ck_prev["tools"]), self.ck_prev["launch"]
        return [], None

    @staticmethod
    def _touch(turn: dict, at: float) -> None:
        if at > turn.get("_settle", 0):
            turn["_settle"] = at

    # -- the replay's steps

    def on_turn(self, turn: dict, o: dict) -> None:
        job = self.job
        mid = (o.get("message") or {}).get("id")
        turn["_call"] = mid if isinstance(mid, str) else None
        launch = job.launch_of.get(mid) if job.main else None
        turn["_launch"] = launch
        prev_tools, prev_launch = self._prev_of(turn)
        first = not self.seen
        later = (job.main and not first and launch is not None and prev_launch is not None
                 and launch != prev_launch)
        turn["_wake"] = self._wake_cause(first, later, prev_tools, launch)
        if job.main and (first or later) and launch in job.digest_launches and \
                self.wake["digest"]:
            turn["_parts"] = self.wake["digest"]
        if later:
            for s in self.stretches:
                if s["open"]:
                    self._close(s)
            self.tasks = []
        else:
            for s in self.stretches:
                if s["open"] and s["notified"] is not None:
                    s["count"] += 1
                    if s["count"] > CI_UNREAD_BOUND:
                        self._close(s)
        self.seen = True
        self.wake = _empty_wake()

    def _prev_of(self, turn: dict) -> tuple[list[str], int | None]:
        if len(self.turns) >= 2:
            t = self.turns[-2]
            return [r["name"] for r in t["tools"]], t.get("_launch")
        if self.ck_prev:
            return list(self.ck_prev["tools"]), self.ck_prev["launch"]
        return [], None

    def _wake_cause(self, first: bool, later: bool, prev_tools: list[str],
                    launch: int | None = None) -> str | None:
        """What woke the transcript before a Call (§ The labels, by entity, `wait_cause`)."""
        job = self.job
        if first:
            return "startup"
        if later:
            if job.dispatch:
                return "driver"
            if not job.pilot_knows and not job.records_know:
                return "person"
            if job.pilot_knows:
                return job.pilot_wait(launch)
        w = self.wake
        if w["person"]:
            return "person"
        if w["note"] or any(n in BG_WAIT_TOOLS for n in prev_tools):
            return "background_task"
        if prev_tools:
            last = w["last"] or prev_tools[-1]
            return "sub_agent" if last in tp.DISPATCH_TOOLS else "command"
        return None

    def on_tool(self, rec: dict, inp: dict, turn: dict, o: dict) -> None:
        if turn is not self.turns[-1]:
            self._touch(turn, self.byte + 1)
        rec["_inp"] = inp
        rec["_req"] = o.get("timestamp")
        rec["_cwd"] = o.get("cwd")
        rec["_bgw"] = sorted({w for x in self.tasks for w in x.get("writes") or ()})
        rec["_turn"] = turn

    def on_result(self, tid, rec: dict | None, txt: str, blk: dict, o: dict) -> None:
        if rec is None:
            if isinstance(tid, str) and tid in self.owed:
                raise _Whole("behind")
            return
        turn = rec["_turn"]
        self._touch(turn, self.byte + 1)
        if turn is self.turns[-1]:
            self.wake["last"] = rec["name"]
        lab = self._labels(rec, blk.get("content"), o.get("timestamp"), bool(blk.get("is_error")))
        bg = lab.get("background")
        if bg:
            self.tasks.append({"task": bg.get("task_id"), "tool": rec["id"],
                               "writes": list(bg.get("writes") or ())})
        wait = lab.get("ci_wait")
        if wait is not None:
            if wait.get("background"):
                self.stretches.append({
                    "rec": rec, "wait": wait, "job": wait.get("job"),
                    "task": bg.get("task_id") if bg else None,
                    "output": bg.get("output_file") if bg else None,
                    "launch": turn.get("_launch"), "notified": None, "count": 0, "open": True})
            else:
                rec["_ci"] = list(lab.get("ci_builds") or ())
            return
        for summary in lab.get("ci_summaries") or ():
            self._match(summary, lab.get("reads") or {}, turn.get("_launch"),
                        o.get("timestamp"))

    def on_text(self, o: dict, txt: str, kind: str | None, marked: dict | None) -> None:
        if kind == "prompt":
            self.wake["person"] = True
            if self.job.digest_launches and self.wake["digest"] is None:
                sections = self.job.tools.digest_sections(txt)
                if sections:
                    self.wake["digest"] = [{"name": s["name"], "characters": s["characters"]}
                                           for s in sections]
        elif kind == "notification":
            self.wake["note"] = True
            self._notified(txt, o.get("timestamp"))

    # -- background tasks and CI waits

    def _notified(self, txt: str, ts) -> None:
        tag = {k: (m.group(1) if (m := rx.search(txt)) else None)
               for k, rx in NOTE_TAG_RE.items()}
        task, tool, output = tag["task-id"], tag["tool-use-id"], tag["output-file"]
        self.tasks = [x for x in self.tasks
                      if not ((task and x["task"] == task) or (tool and x["tool"] == tool))]
        for s in self.stretches:
            if s["open"] and s["notified"] is None and (
                    (tool and s["rec"]["id"] == tool) or (task and s["task"] == task)):
                s["notified"] = ts
                s["count"] = 0
                if output:
                    s["output"] = output

    def _match(self, summary: dict, reads: dict, launch, at) -> None:
        """The open background wait a summary in a later call's result belongs to: the one whose
        output file the call read, or whose task it asked for, else the latest one on the same
        job in the same Launch (§ Test Runs and CI Builds)."""
        paths = set(reads.get("paths") or ())
        tasks = set(reads.get("task_ids") or ())
        live = [s for s in self.stretches if s["open"]]
        s = (next((s for s in live if s["output"] and s["output"] in paths), None)
             or next((s for s in live if s["task"] and s["task"] in tasks), None)
             or next((s for s in reversed(live) if s["job"] and s["job"] == summary.get("job")
                      and s["launch"] == launch), None))
        if s is None:
            return
        s["open"] = False
        # The moment the wait returned: its task notification's, else the read's (O5's
        # default, which Part 3's `deployed_at` holds).
        s["rec"]["_ci"] = list(self.job.tools.ci_builds(s["wait"], summary,
                                                        s["notified"] or at))
        self._touch(s["rec"]["_turn"], self.byte + 1)

    @staticmethod
    def _close(s: dict) -> None:
        """A background wait left unread: its Launch ended, or 20 Calls passed its
        notification. It makes no CI Build, and no later summary is matched to it. Its Call
        keeps the labels it had while open, so the close holds no boundary."""
        s["open"] = False

    def _labels(self, rec: dict, result, result_at, is_error: bool) -> dict:
        ctx = {"cwd": rec.get("_cwd"), "requested_at": rec.get("_req"), "result_at": result_at,
               "is_error": is_error, "background_writes": frozenset(rec.get("_bgw") or ()),
               "spec_repos": self.job.spec_repos}
        lab = self.job.tools.tool_labels(rec["name"], rec.get("_inp") or {}, result, ctx) or {}
        rec["_lab"] = lab
        rec["_inp"] = None
        return lab

    # -- the end of the part

    def finish(self) -> None:
        turns = self.turns
        for t in turns:
            for rec in t["tools"]:
                if "_lab" not in rec:
                    self._labels(rec, None, None, False)
        for s in self.stretches:
            if s["open"]:
                self._touch(s["rec"]["_turn"], INF)
        b = self._boundary_index()
        job = self.job
        if self.ck:
            c = tp.TurnClassifier(state=self.ck["classifier"])
        else:
            c = tp.TurnClassifier(**job.flags)
        cls_state = None
        n = len(turns)
        for k, t in enumerate(turns):
            if k == b:
                cls_state = c.state()
            t["_rec"] = c.step(t, last=k == n - 1)
        seg_at_b = self._segment(turns[b]["_call"] if b is not None else None)
        if b is not None:
            mid = turns[b]["_call"]
            snap = self.snaps[mid]
            self.boundary = {
                "contract": CONTRACT, "session_id": job.sid, "agent_id": job.aid,
                "stamp": job.stamp, "call": mid, "byte": self.first_byte[mid],
                "boundary": {"call": mid, "byte": self.first_byte[mid]},
                "turns": snap["turns"], "classifier": cls_state, "segment": seg_at_b,
                "wake": snap["wake"], "prev": snap["prev"], "seen": snap["seen"],
                "tasks": snap["tasks"], "owed": snap["owed"]}

    def _boundary_index(self) -> int | None:
        """The latest counted Call before whose first line every earlier turn of the part is
        settled; None for a part with no counted Call. What a line after it did to an earlier
        turn within this part is in that turn's labels already, the classifier's state being
        taken once the part is read; what holds the boundary is a turn a later part could
        still touch — a call added to it, a result for one of them, a CI wait still open — or
        one whose touch a later part could not see, as a wait matched after a later wait on
        its job opened."""
        turns = self.turns
        settled_by = []
        m = 0.0
        for t in turns:
            settled_by.append(m)
            m = max(m, t.get("_settle", 0))
        for k in range(len(turns) - 1, -1, -1):
            mid = turns[k]["_call"]
            if mid in self.snaps and settled_by[k] <= self.first_byte[mid]:
                return k
        return None

    def _segment(self, boundary_call: str | None):
        """Every Call's Segment, in the order of their first lines: a run of one kind is one
        Segment; a Call no rule counts takes the Segment of the Call before it, or after it
        where it leads. Gives the Segment as it stood before the boundary Call."""
        pos, kind = (self.ck["segment"] if self.ck and self.ck["segment"] else (0, None))
        resumed = self.ck is not None and pos > 0
        at_b = None
        leading: list[str] = []
        for mid in self.calls_read:
            if mid == boundary_call:
                at_b = [pos, kind] if pos else None
            t = self.by_id.get(mid)
            if t is None or "_rec" not in t:
                if pos:
                    self.segment_of[mid] = pos
                else:
                    leading.append(mid)
                continue
            kd = CLS_KIND.get(t["_rec"]["cls"], OTHER_KIND)
            if kd != kind:
                pos, kind = pos + 1, kd
                self.segments.append({"position": pos, "kind": kd})
            elif resumed and not self.segments:
                self.segments.append({"position": pos, "kind": kd})
            self.segment_of[mid] = pos
            for x in leading:
                self.segment_of[x] = pos
            leading = []
        if leading:
            pos, kind = pos + 1, OTHER_KIND
            self.segments.append({"position": pos, "kind": kind})
            for x in leading:
                self.segment_of[x] = pos
        return at_b


class _Prefix:
    """A transcript read as it stood when it was `size` bytes long: the replay check's cuts
    (`labeller_check`), an item's `size`, which no request of the collector's carries."""

    def __init__(self, fh, size: int):
        self.fh, self.size = fh, size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fh.close()

    def seek(self, pos: int) -> None:
        self.fh.seek(pos)

    def read(self, n: int = -1) -> bytes:
        left = self.size - self.fh.tell()
        return self.fh.read(left if n < 0 else min(n, left)) if left > 0 else b""

    def readline(self) -> bytes:
        left = self.size - self.fh.tell()
        return self.fh.readline(left) if left > 0 else b""

    def __iter__(self):
        while raw := self.readline():
            yield raw


def _line_call(fh, byte: int) -> str | None:
    """The message id of the assistant line at `byte`, if a line starts there."""
    if byte > 0:
        fh.seek(byte - 1)
        if fh.read(1) != b"\n":
            return None
    fh.seek(byte)
    raw = fh.readline()
    try:
        o = json.loads(raw.decode("utf-8", "replace").strip())
    except json.JSONDecodeError:
        return None
    msg = o.get("message") if isinstance(o, dict) else None
    if not isinstance(msg, dict) or o.get("type") != "assistant" \
            or msg.get("model") == tp.SYNTHETIC_MODEL:
        return None
    mid = msg.get("id")
    return mid if isinstance(mid, str) else None


def _epoch(ts) -> float | None:
    """An ISO time -> seconds since the epoch, a naive one UTC; None for none or a bad one."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


# ---------------------------------------------------------------------------
# The checkpoint's text


CK_KEYS = ("contract", "session_id", "agent_id", "stamp", "boundary", "turns", "classifier",
           "segment", "wake", "prev", "seen", "tasks", "owed")


def encode_checkpoint(ck: dict, version: str) -> str | None:
    """`1:<version>:<base64 of zlib-compressed JSON>`, or None past CHECKPOINT_CAP."""
    body = {k: ck[k] for k in CK_KEYS}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    text = (f"{CHECKPOINT_FORMAT}:{version}:"
            + base64.b64encode(zlib.compress(raw.encode(), 6)).decode("ascii"))
    return text if len(text) <= CHECKPOINT_CAP else None


def decode_checkpoint(text, version: str) -> dict | None:
    """The checkpoint's state, or None for one of another format, version or contract, or
    one that does not read."""
    if not isinstance(text, str):
        return None
    parts = text.split(":", 2)
    if len(parts) != 3 or parts[0] != CHECKPOINT_FORMAT or parts[1] != version:
        return None
    try:
        ck = json.loads(zlib.decompress(base64.b64decode(parts[2], validate=True)))
    except (ValueError, zlib.error):
        return None
    if not isinstance(ck, dict) or ck.get("contract") != CONTRACT or \
            any(k not in ck for k in CK_KEYS):
        return None
    return ck


# ---------------------------------------------------------------------------
# Documents


def _doc_re():
    import labeller_files
    return re.compile(r"(?:^|/)slices/(?:(?:" + "|".join(labeller_files.SLICE_STATUSES)
                      + r")/)?" + labeller_files.SLICE_FOLDER + r"/(?P<rest>.+)$")


def document_labels(conv: dict, tie) -> list[dict]:
    """Each Document's `ask_category`, from its source path and the Session that put it
    (§ The labels, by entity, *Document*); the stage is the conversation's, its tie's."""
    docs = [d for d in conv.get("documents") or [] if isinstance(d, dict)]
    if not docs:
        return []
    role = getattr(tie, "role", None) or ""
    stage = role.split(":", 1)[1] if role.startswith("orchestrator:") else None
    kinds = {s.get("id"): s.get("kind") for s in conv.get("sessions") or []
             if isinstance(s, dict)}
    rx = _doc_re()
    out = []
    for d in docs:
        src = d.get("source_path")
        cat = None
        if not src or kinds.get(d.get("session")) in ("chat", "job"):
            cat = "pilots_own"
        elif m := rx.search(str(src)):
            rest = m.group("rest")
            ask = re.fullmatch(r"asks/\d+-(?P<slug>[^/]+)\.md", rest)
            if rest == "close-out.md":
                cat = "close_out"
            elif ask and ask.group("slug") == "requirements":
                cat = "requirements"
            elif ask and ask.group("slug") == "plan-review":
                cat = "plan_review"
            elif ask and stage == "plan":
                cat = "plan_question"
            elif ask and stage == "run":
                cat = "run_question"
        out.append({"id": d.get("id"), "ask_category": cat})
    return out
