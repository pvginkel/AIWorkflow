"""labeller_engine.py — one transcript's labels, whole and from its boundary on.

The binding test is the one the contract names (docs/labeller.md § The replay check): labelling a
file in parts, cut after any Call or at any byte of a line still being written, gives what
labelling it whole gives. Every transcript here is invented, written by `Script` the way Claude
Code writes one (an assistant message a line per block, its tool results after it), and the
file grows on disk between the parts. The parts are merged as Pilot merges them — the labels
before the boundary kept, those from it on replaced — and compared with the whole, label by
label.

Part 2's tie and records and Part 3's rules are stood in for (`Tie`, `Records`, `StubTools`)
with the shapes `labeller_records` and `labeller_tools` give, so the engine's own matter is what
is tested: the reading, the Calls, the classes, wait causes, Segments, background tasks and CI
waits, settledness, the boundary and the checkpoint. One test runs the real Part 3 as well.
"""

import copy
import importlib.util
import json
import random
import re
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("labeller_engine", _HERE / "labeller_engine.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)
tp = E.tp

OPUS = "claude-opus-5"


# -- stand-ins for Part 2 and Part 3 ------------------------------------------

class Tie:
    """Part 2's tie, as far as the engine reads it."""

    def __init__(self, rule=None, role=None, units=None, anchors=(), adopted_group=None):
        self.rule, self.role, self.anchors = rule, role, tuple(anchors)
        self.adopted_group, self.named = adopted_group, ()
        self._units = units or {}

    def unit_for(self, started_at):
        return self._units.get(started_at)


class Records:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def unit_rows(self, keys):
        return [self.rows.get(k, {"key": k}) for k in keys]

    def stage_rows(self, stage_key):
        return [{"key": stage_key}, {"key": f"{stage_key}|sweep|1"}]

    def test_runs(self, stage_key):
        return []


SUMMARY_ROW_RE = re.compile(r"^(\S+) #(\d+) (\S+)$", re.M)


class StubTools:
    """Part 3's `tool_labels`, `ci_builds` and `digest_sections` in its shapes, on a few
    invented commands: `pytest` is a test suite, `track_build.py <job>` a CI wait, `git` git;
    a summary is `=== Build tracking summary ===` and `<job> #<n> <RESULT>` rows."""

    ADD_ALL_ONLY_IN_SPEC_REPO = False

    @staticmethod
    def tool_labels(name, inp, result, ctx):
        text = result if isinstance(result, str) else "".join(
            b.get("text", "") for b in result or [] if isinstance(b, dict))
        cmd = str(inp.get("command") or "") if name == "Bash" else ""
        bg = bool(inp.get("run_in_background"))
        out = {"command_class": None, "effect_kind": None, "effect_subject": None, "rules": [],
               "events": [], "test_runs": [], "test_suites": [], "ci_wait": None,
               "ci_builds": [], "ci_summaries": [], "background": None,
               "reads": {"paths": [], "task_ids": []}}
        words = cmd.split()
        if "track_build.py" in cmd:
            job = words[words.index("track_build.py") + 1]
            out["command_class"] = "ci_wait"
            out["ci_wait"] = {"job": job, "named": [{"job": job, "commit": "c0ffee1"}],
                              "background": bg}
        elif "pytest" in cmd:
            out["command_class"] = "test_suite"
            m = re.search(r"(\d+) passed", text)
            if m and not bg:
                out["test_runs"] = [{"suite": "Repo/pytest", "passed": "failed" not in text,
                                     "tests": int(m.group(1)), "retries_allowed": 0,
                                     "started_at": ctx["requested_at"],
                                     "ended_at": ctx["result_at"], "failures": []}]
                out["test_suites"] = [{"code": "Repo/pytest", "name": "Repo pytest"}]
            if ctx["is_error"] or "failed" in text:
                out["events"] = [{"kind": "gate_red", "at": ctx["result_at"], "detail": "pytest"}]
        elif cmd.startswith("git "):
            out["command_class"] = "git"
        if words[:1] == ["tail"] and any(w in ctx["background_writes"] for w in words):
            out["rules"] = ["no_tail_on_background_log"]
        if name.endswith("__create_issue") and not ctx["is_error"]:
            out["effect_kind"], out["effect_subject"] = "card_created", text.strip()
        if bg:
            tid = re.search(r"with ID: (\w+)", text)
            f = re.search(r"written to: (\S+?)\.(?=\s|$)", text)
            writes = [f.group(1)] if f else []
            writes += re.findall(r">\s*(\S+)", cmd)
            out["background"] = {"task_id": tid.group(1) if tid else None,
                                 "output_file": f.group(1) if f else None, "writes": writes}
        if name == "Read":
            out["reads"]["paths"] = [inp.get("file_path")]
        elif name == "TaskOutput":
            out["reads"]["task_ids"] = [inp.get("task_id")]
        elif words[:1] in (["cat"], ["tail"]):
            out["reads"]["paths"] = [w for w in words[1:] if "/" in w]
        for block in text.split("=== Build tracking summary ===")[1:]:
            builds = [{"job": j, "number": int(n), "result": r, "queued_at": None,
                       "started_at": None, "ended_at": None}
                      for j, n, r in SUMMARY_ROW_RE.findall(block)]
            if builds:
                out["ci_summaries"].append({"job": builds[0]["job"], "builds": builds})
        if out["ci_wait"] and not bg:
            out["ci_builds"] = [b for s in out["ci_summaries"]
                                for b in StubTools.ci_builds(out["ci_wait"], s, ctx["result_at"])]
        return out

    @staticmethod
    def ci_builds(wait, summary, returned_at):
        named = {n["job"]: n["commit"] for n in wait["named"]}
        return [{**b, "commit": named.get(b["job"]), "deployed_at": returned_at}
                for b in summary["builds"]]

    @staticmethod
    def digest_sections(text):
        m = re.search(r"^# Orientation digest —", text, re.M)
        if not m:
            return []
        return [{"name": h, "characters": len(h)}
                for h in re.findall(r"^## (.+)$", text[m.start():], re.M)]


E.TOOLS = StubTools


# -- the fixture builder -----------------------------------------------------

def bash(cmd, res="", err=False, bg=False):
    return ("Bash", {"command": cmd, **({"run_in_background": True} if bg else {})}, res, err)


def read(path, res="text"):
    return ("Read", {"file_path": path}, res, False)


def tool(name, inp, res="", err=False):
    return (name, inp, res, err)


class Script:
    """An invented transcript, written as Claude Code writes one."""

    def __init__(self, agent=False):
        self.lines: list[dict] = []
        self.agent = agent
        self.launch = 1
        self.launch_of: dict[str, int] = {}
        self.starts = {1: "2026-11-15T10:00:00Z"}
        self.n = self.k = self.clock = 0
        self.deferred: list[dict] = []
        self.mids: list[str] = []

    def ts(self):
        self.clock += 7
        c = self.clock
        return f"2026-11-15T{10 + c // 3600:02d}:{c // 60 % 60:02d}:{c % 60:02d}Z"

    def _line(self, mid, block, model, ts):
        return {"type": "assistant", "timestamp": ts, "cwd": "/work/Repo",
                "message": {"id": mid, "model": model, "content": [block],
                            "usage": {"input_tokens": 1, "output_tokens": 1}}}

    def turn(self, *tools, text=None, synthetic=False, late=False, results=True):
        """One message, a line per block, then its tools' results (`late`: only after the next
        Call's first line). Returns its tool-use ids."""
        self.n += 1
        mid = f"msg_{self.n:04d}"
        self.mids.append(mid)
        ts = self.ts()
        blocks = [{"type": "text", "text": text}] if text else []
        tids = []
        for name, inp, _, _ in tools:
            self.k += 1
            tids.append(f"toolu_{self.k:04d}")
            blocks.append({"type": "tool_use", "id": tids[-1], "name": name, "input": inp})
        for k, b in enumerate(blocks or [{"type": "text", "text": "…"}]):
            self.lines.append(self._line(mid, b, tp.SYNTHETIC_MODEL if synthetic else OPUS, ts))
            if k == 0 and self.deferred:
                self.lines += self.deferred
                self.deferred = []
        self.launch_of[mid] = self.launch
        out = [self.result(tid, res, err) for tid, (_, _, res, err) in zip(tids, tools,
                                                                         strict=True)]
        if results:
            (self.deferred if late else self.lines).extend(out)
        return tids

    def result(self, tid, text, err=False):
        return {"type": "user", "timestamp": self.ts(),
                "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                         "content": text, "is_error": err}]}}

    def again(self, mid, *tools, results=True):
        """An assistant line of an earlier message, adding a call to it."""
        tids = []
        for name, inp, res, err in tools:
            self.k += 1
            tids.append(f"toolu_{self.k:04d}")
            self.lines.append(self._line(mid, {"type": "tool_use", "id": tids[-1],
                                               "name": name, "input": inp}, OPUS, self.ts()))
            if results:
                self.lines.append(self.result(tids[-1], res, err))
        return tids

    def unbilled(self, mid):
        """An assistant line of a new message with no usage, which `replay` skips."""
        line = self._line(mid, {"type": "text", "text": "…"}, OPUS, self.ts())
        del line["message"]["usage"]
        self.lines.append(line)

    def prompt(self, text):
        self.lines.append({"type": "user", "timestamp": self.ts(),
                           "message": {"content": text}})

    def note(self, task, tool_use, output):
        self.prompt(f"<task-notification>\n<task-id>{task}</task-id>\n"
                    f"<tool-use-id>{tool_use}</tool-use-id>\n<output-file>{output}</output-file>\n"
                    "<status>completed</status>\n</task-notification>")

    def relaunch(self):
        self.launch += 1
        self.starts[self.launch] = self.ts()

    def data(self) -> bytes:
        lines = self.lines + self.deferred
        return "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines).encode()


def bg_started(task):
    return (f"Command running in background with ID: {task}. Output is being written to: "
            f"/tmp/tasks/{task}.output. You will be notified when it completes.")


SUMMARY = "=== Build tracking summary ===\n{job} #{n} SUCCESS\n{job}-deploy #{m} SUCCESS\n"


# -- labelling, as the collector asks and as Pilot merges ---------------------

def _calls_in(data: bytes) -> list[str]:
    """The Calls the collector reads in a file as it stood: every message id, in the order
    of its first line."""
    out: list[str] = []
    for piece in data.split(b"\n"):
        try:
            o = json.loads(piece.decode("utf-8", "replace").strip())
        except json.JSONDecodeError:
            continue
        mid = (o.get("message") or {}).get("id") if isinstance(o, dict) else None
        if isinstance(o, dict) and o.get("type") == "assistant" and mid and mid not in out:
            out.append(mid)
    return out


def _conversation(sessions=(), documents=()):
    return {"session_id": "sess-1", "sessions": list(sessions), "documents": list(documents)}


def _item(path, data, script, mode="whole", prev=None, conversation=None, pilot=frozenset()):
    ids = _calls_in(data)
    agent = "agent-1" if script.agent else None
    calls = [{"id": m, "position": k + 1,
              **({} if agent else {"launch": script.launch_of[m]})} for k, m in enumerate(ids)]
    used = sorted({script.launch_of[m] for m in ids})
    launches = [] if agent else [{"n": n, "started_at": script.starts[n]} for n in used]
    it = {"session_id": "sess-1", "agent_id": agent, "path": "p/sess-1.jsonl", "file": str(path),
          "mode": mode, "stamp": "1:stamp", "pilot": pilot,
          "conversation": conversation or _conversation(),
          "launches": launches, "calls": calls}
    if mode == "appended":
        b = prev["boundary"]
        pos = ids.index(b["call"]) if b["call"] in ids else 0
        first = calls[pos].get("launch")
        it.update({"from": b, "checkpoint": prev["checkpoint"], "calls": calls[pos:],
                   "launches": [x for x in launches if first is None or x["n"] >= first]})
    return it


def _label(path, data, script, tie=None, records=None, **kw):
    path.write_bytes(data)
    item = _item(path, data, script, **kw)
    return E.label_one(item, tie or Tie(), records or Records()), item


def _owners(data):
    own = {}
    for piece in data.split(b"\n"):
        try:
            o = json.loads(piece)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and o.get("type") == "assistant":
            for b in o["message"]["content"]:
                if b.get("type") == "tool_use":
                    own.setdefault(b["id"], o["message"]["id"])
    return own


def _merge(acc, ans, handed, owner):
    """Pilot's merge: the labels of the Calls before the boundary kept, those of the handed
    Calls and every Segment from the boundary's on replaced."""
    new = copy.deepcopy(ans["labels"])
    if acc is None:
        return new
    out = {"calls": [c for c in acc["calls"] if c["id"] not in handed] + new["calls"]}
    first = min((s["position"] for s in new["segments"]), default=10 ** 9)
    out["segments"] = [s for s in acc["segments"] if s["position"] < first] + new["segments"]
    for f in ("events", "context_parts"):
        out[f] = [r for r in acc[f] if r["call"] not in handed] + new[f]
    for f in ("tool_calls", "test_runs", "ci_waits"):
        out[f] = [r for r in acc[f] if owner.get(r["tool_use_id"]) not in handed] + new[f]
    n0 = min((x["n"] for x in new["launches"]), default=10 ** 9)
    out["launches"] = [x for x in acc["launches"] if x["n"] < n0] + new["launches"]
    out["transcript"], out["documents"] = new["transcript"], new["documents"]
    return out


def _norm(labels):
    return {f: sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))
            for f, rows in labels.items()}


def _in_parts(path, full, script, cuts, **kw):
    """The file grown through `cuts`, labelled whole first and then from each boundary on,
    the answer `whole` labelled whole again as the collector does; the merged labels and the
    `why`s met on the way."""
    owner = _owners(full)
    acc = prev = None
    whys = []
    for c in [*cuts, len(full)]:
        data = full[:c]
        if prev is None or prev["boundary"] is None:
            ans, item = _label(path, data, script, **kw)
        else:
            ans, item = _label(path, data, script, mode="appended", prev=prev, **kw)
            if ans["answer"] == "whole":
                whys.append(ans["why"])
                ans, item = _label(path, data, script, **kw)
                acc = None
        assert ans["answer"] == "labels"
        acc = _merge(acc, ans, {x["id"] for x in item["calls"]}, owner)
        prev = ans
    return acc, whys


def _call_starts(full: bytes) -> list[int]:
    out, seen, off = [], set(), 0
    for piece in full.split(b"\n"):
        try:
            o = json.loads(piece)
        except json.JSONDecodeError:
            o = None
        if isinstance(o, dict) and o.get("type") == "assistant":
            mid = o["message"]["id"]
            if mid not in seen:
                seen.add(mid)
                out.append(off)
        off += len(piece) + 1
    return out


def _check_parts(script, seed=0, randoms=4, allowed=(), **kw):
    """Whole == parts, cut just before every Call's first line and at random bytes, two and
    three cuts at a time. Returns the whole answer."""
    full = script.data()
    rnd = random.Random(seed)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sess-1.jsonl"
        whole, _ = _label(path, full, script, **kw)
        want = _norm(whole["labels"])
        cuts = [[c] for c in _call_starts(full)[1:]]
        cuts += [sorted(rnd.sample(range(1, len(full)), k)) for k in (2, 3) * randoms]
        for cs in cuts:
            got, whys = _in_parts(path, full, script, cs, **kw)
            assert set(whys) <= set(allowed), (cs, whys)
            assert _norm(got) == want, cs
    return whole


def _whole(script, **kw):
    with tempfile.TemporaryDirectory() as d:
        return _label(Path(d) / "sess-1.jsonl", script.data(), script, **kw)[0]


def _col(ans, field="call_class"):
    return [c[field] for c in ans["labels"]["calls"]]


# -- the invented corpus ------------------------------------------------------

def s_work():
    """Reads, an edit, a gate, a fumble, its retry, a commit and the hand-back."""
    s = Script()
    s.prompt("Do the phase.")
    s.turn(read("/work/Repo/plan.md"))
    s.turn(bash("cat run_loop.py", "code"), bash("cat x.py", "code"))
    s.turn(tool("Edit", {"file_path": "run_loop.py"}, "ok"))
    s.turn(bash("uv run pytest -q", "3 passed in 0.1s"))
    s.turn(bash("close_out.py rep.md list", "usage: close_out.py [-h] slice_dir"))
    s.turn(bash("close_out.py /s/170 list", "B1"))
    s.turn(bash("git commit -am x", "1 file changed"))
    s.turn(text="Done.")
    return s


def s_waits():
    """A person's prompt, a sub-agent, a background task and its notification."""
    s = Script()
    s.prompt("Start.")
    s.turn(tool("Agent", {"subagent_type": "Explore", "description": "find"}, "found it"))
    s.turn(bash("uv run pytest -q", bg_started("b1"), bg=True))
    s.turn(text="Waiting.")
    s.note("b1", "toolu_0002", "/tmp/tasks/b1.output")
    s.turn(tool("TaskOutput", {"task_id": "b1"}, "4 passed in 1s"))
    s.turn(text="Anything else?")
    s.prompt("Yes, the docs.")
    s.turn(read("/work/Repo/README.md"))
    return s


def s_ci():
    """Background CI waits: one read through TaskOutput, one through its output file, one
    by its job alone, one left past its 20 Calls, one cut off by a later Launch."""
    s = Script()
    s.prompt("Ship it.")
    (a,) = s.turn(bash("track_build.py App/Build --hash c0ffee1", bg_started("ta"), bg=True))
    s.turn(bash("git status", "clean"))
    s.note("ta", a, "/tmp/tasks/ta.output")
    s.turn(tool("TaskOutput", {"task_id": "ta"}, SUMMARY.format(job="App/Build", n=7, m=3)))
    (b,) = s.turn(bash("track_build.py App/Build --hash c0ffee2", bg_started("tb"), bg=True))
    s.note("tb", b, "/tmp/tasks/tb.output")
    s.turn(bash("tail -5 /tmp/tasks/tb.output", SUMMARY.format(job="App/Build", n=8, m=4)))
    s.turn(bash("track_build.py Lib/Build --hash c0ffee3", bg_started("tc"), bg=True))
    s.turn(bash("cat elsewhere.log", SUMMARY.format(job="Lib/Build", n=2, m=1)))
    (d,) = s.turn(bash("track_build.py App/Build", bg_started("td"), bg=True))
    s.note("td", d, "/tmp/tasks/td.output")
    for k in range(21):
        s.turn(bash(f"git log -{k + 1}", "log"))
    s.turn(bash("cat /tmp/tasks/td.output", SUMMARY.format(job="App/Build", n=9, m=5)))
    s.turn(bash("track_build.py Lib/Build", bg_started("te"), bg=True))
    s.turn(text="Waiting for the build.")
    s.relaunch()
    s.prompt("Resumed.")
    s.turn(bash("cat /tmp/tasks/te.output", SUMMARY.format(job="Lib/Build", n=3, m=2)))
    s.turn(bash("track_build.py App/Build --hash c0ffee4",
                SUMMARY.format(job="App/Build", n=10, m=6)))
    return s


def s_launches():
    """Three Launches, synthetic messages between Calls, leading and at the end."""
    s = Script()
    s.turn(text="API Error: overloaded", synthetic=True)
    s.prompt("Run the phase.\n\n# Orientation digest — P1\n## Plan (p)\nx\n## Files\ny\n")
    s.turn(read("/work/Repo/a.py"))
    s.turn(text="API Error: overloaded", synthetic=True)
    s.turn(read("/work/Repo/b.py"))
    s.turn(text="Question for the operator.")
    s.relaunch()
    s.prompt("The ruling.\n\n# Orientation digest — P1\n## Ruling\nz\n")
    s.turn(tool("Edit", {"file_path": "/work/Repo/a.py"}, "ok"))
    s.turn(text="Done.")
    s.relaunch()
    s.prompt("Again.")
    s.turn(bash("git diff", "diff"))
    s.turn(text="API Error", synthetic=True)
    return s


def s_late():
    """A result that arrives after the next Call began, and an earlier message that gains a
    call after a later one began: the parts answer `whole` where they reach behind."""
    s = Script()
    s.prompt("Go.")
    s.turn(bash("uv run pytest -q", "1 failed, 2 passed in 1s", err=True), late=True)
    s.turn(bash("uv run pytest -q", "3 passed in 1s"))
    s.turn(read("/work/Repo/c.py"))
    s.again("msg_0002", bash("cat later.py", "x"))
    s.turn(bash("sleep 1", "ok"), results=False)
    s.turn(read("/work/Repo/d.py"))
    s.turn(text="Done.")
    return s


def s_tail():
    """A tail of a file a background task of the same Launch is still writing."""
    s = Script()
    s.prompt("Go.")
    (t,) = s.turn(bash("make all > /tmp/build.log", bg_started("b9"), bg=True))
    s.turn(bash("tail -3 /tmp/build.log", "..."))
    s.note("b9", t, "/tmp/tasks/b9.output")
    s.turn(bash("tail -3 /tmp/build.log", "done"))
    s.turn(text="Built.")
    return s


def s_subagent():
    s = Script(agent=True)
    s.prompt("Find the callers of run().")
    s.turn(tool("Grep", {"pattern": "run(", "path": "."}, "a.py:3:run()"))
    s.turn(read("/work/Repo/a.py"))
    s.turn(text="They are in a.py.")
    return s


POOL = [
    lambda s: s.turn(read(f"/work/Repo/{random.choice('abc')}.py")),
    lambda s: s.turn(bash("cat a.py", "x"), bash("cat b.py", "y")),
    lambda s: s.turn(tool("Edit", {"file_path": "a.py"}, "ok")),
    lambda s: s.turn(bash("uv run pytest -q", "1 failed, 4 passed in 2s", err=True)),
    lambda s: s.turn(bash("uv run pytest -q", "5 passed in 2s")),
    lambda s: s.turn(bash("close_out.py rep.md list", "usage: close_out.py [-h] x")),
    lambda s: s.turn(bash("git commit -am x", "ok")),
    lambda s: s.turn(text="Thinking."),
    lambda s: s.turn(tool("Agent", {"subagent_type": "Explore", "description": "x"}, "r")),
    lambda s: s.turn(tool("mcp__tracker__create_issue", {"summary": "x"}, "CARD-1")),
    lambda s: s.turn(text="Overloaded", synthetic=True),
    lambda s: s.prompt("Carry on."),
    lambda s: s.turn(bash("sleep 30", "")),
    lambda s: s.turn(bash("git diff", "d"), late=True),
]


def s_random(seed, agent=False):
    """Random sessions from the pool: background tasks and CI waits, notifications, reads
    of their output, prompts and Launches among them."""
    rnd = random.Random(seed)
    random.seed(seed)
    s = Script(agent=agent)
    s.prompt("Begin.")
    tasks = 0
    for _ in range(rnd.randint(4, 40)):
        x = rnd.random()
        if x < 0.08:
            tasks += 1
            job = rnd.choice(("App/Build", "Lib/Build"))
            (t,) = s.turn(bash(f"track_build.py {job}", bg_started(f"t{tasks}"), bg=True))
            if rnd.random() < 0.7:
                s.note(f"t{tasks}", t, f"/tmp/tasks/t{tasks}.output")
            if rnd.random() < 0.7:
                how = rnd.choice(("TaskOutput", "cat", "other"))
                text = SUMMARY.format(job=job, n=tasks, m=tasks)
                if how == "TaskOutput":
                    s.turn(tool("TaskOutput", {"task_id": f"t{tasks}"}, text))
                elif how == "cat":
                    s.turn(bash(f"cat /tmp/tasks/t{tasks}.output", text))
                else:
                    s.turn(bash("cat out.log", text))
        elif x < 0.12 and not agent:
            s.relaunch()
            s.prompt("Again.")
        else:
            rnd.choice(POOL)(s)
    s.turn(text="Done.")
    return s


CORPUS = {"work": s_work, "waits": s_waits, "ci": s_ci, "launches": s_launches,
          "tail": s_tail, "subagent": s_subagent}


# -- whole == parts -----------------------------------------------------------

def test_parts_give_the_whole_cut_after_every_call_and_at_random_bytes():
    """The binding property, on every invented transcript: no part reached behind, so no
    answer `whole` came back, except where a late line made one necessary."""
    for name, make in CORPUS.items():
        _check_parts(make(), seed=len(name))
    _check_parts(s_late(), allowed=("behind", "calls"))


def test_parts_give_the_whole_on_random_sessions():
    for seed in range(40):
        _check_parts(s_random(seed, agent=seed % 5 == 0), seed=seed, randoms=2,
                     allowed=("behind", "calls"))


def test_parts_give_the_whole_under_a_dispatchs_tie_and_a_pilot_conversation():
    s = s_launches()
    units = {s.starts[n]: f"Specs/001_x|run|P1|code-writer|{n}" for n in s.starts}
    _check_parts(s, tie=Tie(rule="dispatch", role="code-writer", units=units))
    _check_parts(s_launches(), tie=Tie(rule="pilot", role="orchestrator:run"),
                 conversation=_conversation([{"id": "p1", "kind": "work"}]))


def test_parts_give_the_whole_under_the_real_tool_rules():
    """Part 3's own rules in place of the stand-in."""
    import labeller_tools
    E.TOOLS = labeller_tools
    try:
        for make in (s_ci, s_tail, s_work):
            _check_parts(make(), randoms=1)
    finally:
        E.TOOLS = StubTools


def test_a_git_add_all_breaches_only_in_a_spec_repo_the_records_name():
    """D10: the engine hands the real rules the run records' spec repos."""
    import labeller_tools

    class SpecRecords(Records):
        spec_repos = {"OrchardSpecs"}

    s = Script()
    s.prompt("Commit it.")
    s.turn(bash("cd /work/Orchard && git add -A", ""))
    s.turn(bash("cd /work/OrchardSpecs && git add -A", ""))
    s.turn(text="Done.")
    E.TOOLS = labeller_tools
    try:
        rows = _whole(s, records=SpecRecords())["labels"]["tool_calls"]
    finally:
        E.TOOLS = StubTools
    assert [r["rules"] for r in rows] == [[], ["no_git_add_all"]]


# -- the classes are turn_profile's --------------------------------------------

def test_a_calls_class_is_classify_turns_for_the_file():
    for make in [*CORPUS.values(), s_late] + [lambda k=k: s_random(k) for k in range(10)]:
        s = make()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.jsonl"
            path.write_bytes(s.data())
            ans, _ = _label(path, s.data(), s)
            turns = tp.replay(path)["turns"]
        want = [r["cls"] for r in tp.classify_turns(turns, tp.first_edit_turn(turns))]
        got = [c["call_class"] for c in ans["labels"]["calls"] if c["call_class"]]
        assert got == want


def test_the_role_sets_the_classifier_flags():
    """A reviewer's reads are its work (slice_cost.turn_flags)."""
    assert _col(_whole(s_work()))[:2] == ["orient-read", "orient-read"]
    assert _col(_whole(s_work(), tie=Tie(rule="dispatch", role="code-reviewer")))[:2] == [
        "work-read", "work-read"]


def test_avoidable_and_batchable_come_from_the_class():
    ans = _whole(s_work())
    assert _col(ans, "avoidable_kind")[4:6] == ["fumble", "retry"]
    reads = [c for c in ans["labels"]["calls"] if c["call_class"] in E.READ_CLASSES]
    assert all(c["batchable_condition"] in tp.BATCHABLE_WHY_CODES for c in reads)
    assert all(c["batchable_condition"] is None for c in ans["labels"]["calls"]
               if c["call_class"] not in E.READ_CLASSES)


# -- wait causes --------------------------------------------------------------

def test_what_woke_each_call():
    assert _col(_whole(s_waits()), "wait_cause") == [
        "startup", "sub_agent", "command", "background_task", "background_task", "person"]
    assert _col(_whole(s_work()), "wait_cause")[1:4] == ["command"] * 3


def test_a_later_launch_is_the_drivers_a_persons_or_open():
    s = s_launches()
    later = [s.mids.index("msg_0006"), s.mids.index("msg_0008")]
    dispatch = _whole(s_launches(), tie=Tie(rule="dispatch"))
    assert [_col(dispatch, "wait_cause")[k] for k in later] == ["driver", "driver"]
    nobody = _whole(s_launches())
    assert [_col(nobody, "wait_cause")[k] for k in later] == ["person", "person"]
    pilot = _whole(s_launches(), conversation=_conversation([{"id": "p1", "kind": "work"}]))
    assert [_col(pilot, "wait_cause")[k] for k in later] == [E.O3_LATER_LAUNCH_OF_PILOT] * 2
    assert E.O3_LATER_LAUNCH_OF_PILOT is None
    # a stage's own session run by hand: the rules after the Launch's decide
    stage = _whole(s_launches(), tie=Tie(rule="stage"))
    assert [_col(stage, "wait_cause")[k] for k in later] == ["person", "person"]
    # the first Call is the startup's, though a synthetic message came before it
    assert _col(nobody, "wait_cause")[:2] == [None, "startup"]


# -- Segments -----------------------------------------------------------------

def test_segments_are_runs_of_one_kind_and_cover_every_call():
    ans = _whole(s_work())
    assert ans["labels"]["segments"] == [
        {"position": 1, "kind": "start"}, {"position": 2, "kind": "work"},
        {"position": 3, "kind": "gate"}, {"position": 4, "kind": "work"},
        {"position": 5, "kind": "records"}]
    assert _col(ans, "segment") == [1, 1, 2, 3, 4, 4, 5, 5]


def test_an_uncounted_call_takes_the_segment_before_it_or_after_it_where_it_leads():
    ans = _whole(s_launches())
    calls = ans["labels"]["calls"]
    assert [c["call_class"] for c in calls] == [
        None, "orient-read", None, "orient-read", "think", "edit", "think", "git-inspect",
        None]
    assert [c["segment"] for c in calls] == [1, 1, 1, 1, 2, 2, 2, 2, 2]
    assert ans["labels"]["segments"] == [{"position": 1, "kind": "start"},
                                         {"position": 2, "kind": "work"}]
    assert all(calls[k]["wait_cause"] is None for k in (0, 2, 8))


# -- Tool Calls, Events, Test Runs, Context Parts -----------------------------

def test_the_tool_rules_reach_the_rows_with_their_times_and_calls():
    ans = _whole(s_work())
    L = ans["labels"]
    assert [r["command_class"] for r in L["tool_calls"]] == ["test_suite", "git"]
    (run,) = L["test_runs"]
    assert run["tool_use_id"] == "toolu_0005" and run["tests"] == 3
    assert run["started_at"] and run["ended_at"] > run["started_at"]
    assert ans["test_suites"] == [{"code": "Repo/pytest", "name": "Repo pytest"}]
    late = _whole(s_late())
    (ev,) = late["labels"]["events"]
    assert ev["call"] == "msg_0001" and ev["kind"] == "gate_red" and ev["at"]


def test_a_tail_of_a_running_background_tasks_file_breaches_its_rule():
    rows = _whole(s_tail())["labels"]["tool_calls"]
    assert [r["rules"] for r in rows] == [["no_tail_on_background_log"]]


def test_a_dispatchs_launches_carry_their_opening_digest():
    s = s_launches()
    units = {s.starts[n]: f"Specs/001_x|run|P1|code-writer|{n}" for n in s.starts}
    ans = _whole(s_launches(), tie=Tie(rule="dispatch", units=units))
    assert [(p["call"], p["name"]) for p in ans["labels"]["context_parts"]] == [
        ("msg_0002", "Plan (p)"), ("msg_0002", "Files"), ("msg_0006", "Ruling")]
    assert ans["labels"]["launches"] == [{"n": n, "work_unit": units[s.starts[n]]}
                                         for n in (1, 2, 3)]
    assert [u["key"] for u in ans["units"]] == list(units.values())
    assert _whole(s_launches())["labels"]["context_parts"] == []


# -- background CI waits --------------------------------------------------------

def test_background_ci_waits_are_matched_left_unread_or_cut_off():
    ans = _whole(s_ci())
    waits = {(w["tool_use_id"], w["job"], w["number"]) for w in ans["labels"]["ci_waits"]}
    assert waits == {("toolu_0001", "App/Build", 7), ("toolu_0001", "App/Build-deploy", 3),
                     ("toolu_0004", "App/Build", 8), ("toolu_0004", "App/Build-deploy", 4),
                     ("toolu_0006", "Lib/Build", 2), ("toolu_0006", "Lib/Build-deploy", 1),
                     ("toolu_0033", "App/Build", 10), ("toolu_0033", "App/Build-deploy", 6)}
    # past its 20 Calls (toolu_0008) and across a Launch (toolu_0031): no CI Build
    builds = {(b["job"], b["number"]): b for b in ans["ci_builds"]}
    assert ("App/Build", 9) not in builds and ("Lib/Build", 3) not in builds
    assert builds[("App/Build", 7)]["commit"] == "c0ffee1"
    # the wait returned at its notification
    note = next(x for x in s_ci().lines if "<task-id>ta</task-id>" in json.dumps(x))
    assert builds[("App/Build", 7)]["deployed_at"] == note["timestamp"]


def _bound(k):
    """A background wait whose summary is read in the result of the k-th Call after its
    notification."""
    s = Script()
    s.prompt("Ship.")
    (t,) = s.turn(bash("track_build.py App/Build", bg_started("t1"), bg=True))
    s.note("t1", t, "/tmp/tasks/t1.output")
    for j in range(k - 1):
        s.turn(bash(f"git log -{j + 1}", "log"))
    s.turn(bash("cat /tmp/tasks/t1.output", SUMMARY.format(job="App/Build", n=1, m=1)))
    s.turn(text="Done.")
    return s


def test_a_background_wait_is_read_within_20_calls_of_its_notification():
    assert len(_whole(_bound(20))["labels"]["ci_waits"]) == 2
    assert _whole(_bound(21))["labels"]["ci_waits"] == []
    _check_parts(_bound(21), randoms=1)


def test_a_wait_matched_after_a_later_wait_on_its_job_opened_holds_the_boundary():
    """The summary is the first wait's, by its task; had the part begun at the second wait,
    the summary would have gone to it by its job."""
    s = Script()
    s.prompt("Ship.")
    s.turn(bash("track_build.py App/Build", bg_started("t1"), bg=True))
    s.turn(bash("track_build.py App/Build", bg_started("t2"), bg=True))
    s.turn(tool("TaskOutput", {"task_id": "t1"}, SUMMARY.format(job="App/Build", n=1, m=1)))
    ans = _whole(s)
    assert {w["tool_use_id"] for w in ans["labels"]["ci_waits"]} == {"toolu_0001"}
    assert ans["boundary"]["call"] == "msg_0001"
    s.turn(tool("TaskOutput", {"task_id": "t2"}, SUMMARY.format(job="App/Build", n=2, m=2)))
    _check_parts(s)


def test_a_background_task_ends_with_its_launch():
    s = Script()
    s.prompt("Go.")
    s.turn(bash("make all > /tmp/build.log", bg_started("b9"), bg=True))
    s.turn(text="Waiting.")
    s.relaunch()
    s.prompt("Resumed.")
    s.turn(bash("tail -3 /tmp/build.log", "..."))
    s.turn(text="Done.")
    assert _whole(s)["labels"]["tool_calls"] == []
    _check_parts(s)


def test_an_open_ci_wait_holds_the_boundary_at_its_call():
    s = Script()
    s.prompt("Ship.")
    (t,) = s.turn(bash("track_build.py App/Build", bg_started("t1"), bg=True))
    s.turn(bash("git status", "clean"))
    s.turn(bash("git log", "log"))
    assert _whole(s)["boundary"]["call"] == "msg_0001"
    s.note("t1", t, "/tmp/tasks/t1.output")
    s.turn(bash("cat /tmp/tasks/t1.output", SUMMARY.format(job="App/Build", n=1, m=1)))
    s.turn(text="Shipped.")
    assert _whole(s)["boundary"]["call"] == "msg_0005"
    _check_parts(s)


# -- the boundary and the checkpoint ------------------------------------------

def test_the_boundary_is_the_last_call_and_its_first_line():
    s = s_work()
    ans = _whole(s)
    data = s.data()
    assert ans["boundary"] == {"call": "msg_0008", "byte": _call_starts(data)[-1]}
    ck = E.decode_checkpoint(ans["checkpoint"], E._version())
    assert ck["turns"] == 7 and ck["segment"] == [5, "records"]
    assert ans["checkpoint"].startswith(f"1:{E._version()}:")


def test_a_late_line_holds_the_boundary_back_to_the_call_it_touched():
    s = Script()
    s.prompt("Go.")
    s.turn(bash("uv run pytest -q", "2 passed in 1s"), late=True)
    s.turn(text="Waiting.")
    full = s.data()
    with tempfile.TemporaryDirectory() as d:
        ans, _ = _label(Path(d) / "t.jsonl", full, s)
    assert ans["boundary"]["call"] == "msg_0001"


def test_an_earlier_message_that_gains_a_call_holds_the_boundary_back_to_it():
    """A call added to an earlier message after a later one began, whose result comes in a
    later part: the earlier Call was not settled, and the part goes on from it."""
    s = Script()
    s.prompt("Go.")
    s.turn(read("/work/Repo/a.py"))
    s.turn(read("/work/Repo/b.py"))
    (t,) = s.again("msg_0001", bash("make x", ""), results=False)
    cut = len(s.data())
    s.lines.append(s.result(t, "Exit code 2\nmake: *** No rule to make target 'x'.", True))
    s.turn(text="Done.")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.jsonl"
        first, _ = _label(path, s.data()[:cut], s)
        assert first["boundary"]["call"] == "msg_0001"
        got, whys = _in_parts(path, s.data(), s, [cut])
    assert not whys
    assert _norm(got) == _norm(_whole(s)["labels"])
    assert _col(_whole(s))[0] == "fumble"


def test_a_call_whose_first_line_is_unbilled_goes_on_from_that_line():
    """Its turn opens at a later line; what comes between touches the turn before it (the
    notification marks it), and the parts still agree with the whole."""
    s = Script()
    s.prompt("Go.")
    s.turn(bash("make x", "Command running in background with ID: b1.", bg=True))
    s.turn(text="Waiting.")
    s.unbilled("msg_0003")
    cut = len(s.data())
    s.note("b1", "toolu_0001", "/tmp/tasks/b1.output")
    s.n = 2
    s.turn(read("/work/Repo/a.py"))
    s.turn(text="Done.")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.jsonl"
        first, _ = _label(path, s.data()[:cut], s)
        assert first["boundary"]["call"] == "msg_0002"
        got, whys = _in_parts(path, s.data(), s, [cut])
        # the whole file but its last Call: the unbilled line opened no turn of its own
        mid, _ = _label(path, s.data()[:_call_starts(s.data())[-1]], s)
        assert mid["boundary"]["call"] == "msg_0003"
    assert not whys
    assert _norm(got) == _norm(_whole(s)["labels"])
    assert _col(_whole(s))[:3] == ["other", "wait", "orient-read"]
    _check_parts(s)


def test_a_transcript_with_no_counted_call_has_no_boundary():
    s = Script()
    s.prompt("Hello.")
    s.turn(text="API Error", synthetic=True)
    ans = _whole(s)
    assert ans["boundary"] is None and ans["checkpoint"] is None
    assert ans["labels"]["segments"] == [{"position": 1, "kind": "work"}]
    assert _whole(Script())["labels"]["calls"] == []


def _appended(script, mutate, cut=None):
    """Label the file up to `cut` whole, then ask from its boundary with the request
    changed by `mutate`."""
    full = script.data()
    cut = cut or _call_starts(full)[-2]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.jsonl"
        first, _ = _label(path, full[:cut], script)
        path.write_bytes(full)
        item = _item(path, full, script, mode="appended", prev=first)
        mutate(item)
        return E.label_one(item, Tie(), Records())


def test_an_appended_request_that_cannot_go_on_is_answered_whole():
    s = s_work()

    def whole(why):
        return {"session_id": "sess-1", "agent_id": None, "answer": "whole", "why": why}
    assert _appended(s, lambda it: it.update(
        checkpoint="1:0.0.0:" + it["checkpoint"].split(":", 2)[2])) == whole("checkpoint")
    assert _appended(s, lambda it: it.update(checkpoint="garbage")) == whole("checkpoint")
    assert _appended(s, lambda it: it.update(session_id="sess-2"))["why"] == "checkpoint"
    assert _appended(s, lambda it: it.update(stamp="1:other")) == whole("stamp")

    def moved(it):
        ck = E.decode_checkpoint(it["checkpoint"], E._version())
        ck["boundary"]["byte"] += 1
        it["from"] = ck["boundary"]
        it["checkpoint"] = E.encode_checkpoint(ck, E._version())
    assert _appended(s, moved) == whole("boundary")
    assert _appended(s, lambda it: it.update(calls=it["calls"][1:])) == whole("calls")
    assert _appended(s, lambda it: it["calls"].append(
        {"id": "msg_9999", "position": 99, "launch": 1})) == whole("calls")


def test_a_result_owed_at_the_boundary_is_behind():
    s = Script()
    s.prompt("Go.")
    s.turn(bash("uv run pytest -q", "2 passed in 1s"), results=False)
    s.turn(read("/work/Repo/a.py"))
    s.turn(text="Next.")
    cut = len(s.data())
    s.lines.append(s.result("toolu_0001", "2 passed in 1s"))
    s.turn(text="Done.")
    assert _appended(s, lambda it: None, cut=cut)["why"] == "behind"
    _check_parts(s, allowed=("behind",))


def test_a_checkpoint_past_its_cap_is_not_handed_back():
    big = dict.fromkeys(E.CK_KEYS)
    big["owed"] = [f"toolu_{random.getrandbits(64):016x}" for _ in range(30_000)]
    assert E.encode_checkpoint(big, "0.1.0") is None


# -- errors -------------------------------------------------------------------

def test_a_whole_labelling_whose_calls_differ_is_an_error():
    s = s_work()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.jsonl"
        path.write_bytes(s.data())
        item = _item(path, s.data(), s)
        item["calls"][3]["id"] = "msg_other"
        try:
            E.label_one(item, Tie(), Records())
        except E.LabelError as e:
            assert e.code == "calls_mismatch" and "msg_other" in e.message
        else:
            raise AssertionError("no error")
        item["file"] = str(Path(d) / "gone.jsonl")
        try:
            E.label_one(item, Tie(), Records())
        except E.LabelError as e:
            assert e.code == "unreadable"
        else:
            raise AssertionError("no error")


# -- the rest of the answer ---------------------------------------------------

def test_the_answer_line_and_its_main_thread_rows():
    docs = [{"id": "d1", "session": "p1", "source_path": None},
            {"id": "d2", "session": "p1", "source_path": "/w/XSpecs/slices/001_a/close-out.md"},
            {"id": "d3", "session": "p1",
             "source_path": "/w/XSpecs/slices/completed/002_b/asks/1-requirements.md"},
            {"id": "d4", "session": "p1",
             "source_path": "/w/XSpecs/slices/001_a/asks/2-plan-review.md"},
            {"id": "d5", "session": "p1", "source_path": "/w/XSpecs/slices/001_a/asks/3-x.md"},
            {"id": "d6", "session": "c1", "source_path": "/w/XSpecs/slices/001_a/asks/3-x.md"},
            {"id": "d7", "session": "p1", "source_path": "/w/X/README.md"}]
    conv = _conversation([{"id": "p1", "kind": "work"}, {"id": "c1", "kind": "chat"}], docs)
    tie = Tie(rule="stage", role="orchestrator:plan", anchors=("Specs/001_a|plan",),
              adopted_group="Specs/001_a")
    ans = _whole(s_work(), tie=tie, conversation=conv)
    assert set(ans) == {"session_id", "agent_id", "answer", "stamp", "boundary", "checkpoint",
                        "labels", "units", "test_suites", "ci_builds"}
    assert ans["stamp"] == "1:stamp"
    L = ans["labels"]
    assert L["transcript"] == [{"adopted_group": "Specs/001_a"}]
    assert [d["ask_category"] for d in L["documents"]] == [
        "pilots_own", "close_out", "requirements", "plan_review", "plan_question",
        "pilots_own", None]
    assert [u["key"] for u in ans["units"]] == ["Specs/001_a|plan", "Specs/001_a|plan|sweep|1"]
    run = E.document_labels(conv, Tie(role="orchestrator:run"))
    assert run[4]["ask_category"] == "run_question"
    sub = _whole(s_subagent(), tie=tie, conversation=conv)
    assert sub["labels"]["transcript"] == sub["labels"]["documents"] == []
    assert sub["labels"]["launches"] == []


def test_an_old_session_is_restamped_with_what_its_file_names():
    """Where only the file's own content can tie the transcript, the engine reads what it
    names through Part 2 and takes the stamp and tie Part 1's `restamp` gives for it."""
    class Old(Records):
        def needs_facts(self, conversation, transcript):
            return True

        def named_from_facts(self, facts):
            assert facts["first_prompt"] == "/dev:run-slice 001_a"
            return ["Specs/001_a@run"]
    s = Script()
    s.prompt("/dev:run-slice 001_a")
    s.turn(text="Done.")
    asked = []
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.jsonl"
        path.write_bytes(s.data())
        item = _item(path, s.data(), s)
        item["restamp"] = lambda named: (asked.append(named) or "1:x:Specs/001_a@run",
                                         Tie(adopted_group="Specs/001_a"))
        ans = E.label_one(item, Tie(), Old())
    assert asked == [["Specs/001_a@run"]]
    assert ans["stamp"] == "1:x:Specs/001_a@run"
    assert ans["labels"]["transcript"] == [{"adopted_group": "Specs/001_a"}]


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
