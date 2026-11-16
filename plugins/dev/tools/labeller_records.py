"""labeller_records.py — the run records as the labeller reads them.

Part 2 of the labeller (`docs/labeller.md` § Modules and build parts): the index of the plugin's
run records and its opaque blob, the ties from a conversation and a transcript to their Work
Units, the units themselves (keys, kinds, nesting, attributes, outcomes, rework, what occasioned
them, measures, anchors), the driver's Test Runs, the groups and the adoption rules, and the
stamp's record inputs. It reads the data folder alone (`runner-state.md` § The run records) and
writes nothing anywhere.

    records, blob = Records.load(data_dir, blob)     # blob: the last answer's, or None
    records.use_pilot(request.get("pilot"))          # the request's `pilot` header
    tie = records.tie(conversation, transcript)
    tie.unit_for(launch_started_at)                   # the Launch's unit key, or None
    records.unit_rows(keys) / records.stage_rows(stage_key) / records.test_runs(stage_key)
    records.stamp_inputs(tie, conversation) / records.stamp(tie, conversation)

The open points' defaults (§ Open points) each sit in one constant below.
"""

import base64
import hashlib
import json
import os
import re
import sys
import time
import tomllib
import zlib
from datetime import UTC, datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import labeller_vocab  # noqa: E402

_OWN_OUTCOMES = labeller_vocab.UNIT_OUTCOMES

# ---------------------------------------------------------------- the open points' defaults

# O4: the driver's gate and sweep records hold no test count, so no Test Run is handed from
# them. True hands them with `tests` null.
DRIVER_TEST_RUNS = False

# O6: the triage sessions of old slices stay on no project. True ties every session id that
# `slice.json`'s `triage_sessions` lists to the slice's `triage` stage, should the seed come
# to write them.
TRIAGE_SESSIONS = False

# ---------------------------------------------------------------- the records' vocabulary

INDEX_FORMAT = 2            # bump when the blob's content changes shape
MAX_BLOB = 16 * 1024 * 1024
STAMP_FORMAT = "1"
STATE_FILES = {"plan_state.json": "plan", "state.json": "run"}
STAGE_ORDER = ("triage", "plan", "run", "close-out")
STAGE_TITLES = {"triage": "Triage", "plan": "Plan", "run": "Run", "close-out": "Close out"}
GATE_ROLES = ("gate", "doc-gate", "wrap-up-gate", "fixes-gate", "fixes-doc-gate")
GATE_TITLES = {"gate": "Gate", "doc-gate": "Doc gate", "wrap-up-gate": "Wrap-up gate",
               "fixes-gate": "Fixes gate", "fixes-doc-gate": "Fixes doc gate"}
NOT_UNITS = ("orchestrator",)
# § Work Units, `outcome` (t17-labeller-2.md D5, ruled 2026-11-16): a history word that means one
# of the record's six takes it; every other word the driver writes is a Unit Outcome of its own,
# declared in labeller_vocab (`UNIT_OUTCOMES`); a word in neither has none.
FOLDED_OUTCOMES: dict[str, str] = {
    "done": "done", "clean": "done",
    "signoff": "signoff", "go": "signoff",
    "issues": "issues", "critical": "issues", "findings": "issues",
    "red": "red", "green": "green",
    "question": "question", "questions": "question",
}
CLOSE_OUT_MEASURES = (("entries", "close_out_entries"), ("fixed", "close_out_fixed"),
                      ("carded", "close_out_carded"), ("closed", "close_out_closed"))
PILOT_SLACK_S = 5.0         # a Launch's Pilot Session: created at or before its start + 5 s
PILOT_BRIEF_RE = re.compile(r"^\s*/dev:(plan|run)-slice\s+(\S+)")
SLICE_FOLDER_RE = re.compile(r"^\d+[a-z]?_")

# The adoption rules' readings, as the prototype's `adopted_db` has them.
CMD_NAME_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
CMD_ARGS_RE = re.compile(r"<command-args>([^<]*)</command-args>")
FOLDER_RE = re.compile(r"(?:([A-Za-z]+Specs)/slices/(?:[a-z]+/)?)?\b(\d{3}[a-z]?_[a-z0-9_]+)")
SLICE_NO_RE = re.compile(r"\bslice\s+#?(\d{1,3}[a-z]?)\b", re.I)
CLOSE_OUT_RE = re.compile(r"close[- ]?out", re.I)
CLOSE_OUT_CMD_RE = re.compile(r"/(?:dev:)?close-out\s+(\S+)")
WORKFLOW_COMMANDS = {"plan-slice", "run-slice", "close-out", "triage"}
NOT_PROMPTS = ("<task-notification>", "<local-command", "Caveat:", "[Request interrupted",
               "<system-reminder>", "<bash-input>", "<bash-stdout>")
NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")
# A headless session's first prompt -> (stage, role) of a discarded attempt (R3).
R3_ROLES = (
    (re.compile(r"completing the plan|plan-reviewer (?:did not sign off|signed off)|"
                r"plan-reviewer's findings"), "plan", "plan-writer"),
    (re.compile(r"Review the plan"), "plan", "plan-reviewer"),
    (re.compile(r"Execute phase P?(\w+)|resolving review findings for phase P?(\w+)"),
     "run", "code-writer"),
    (re.compile(r"(?:Re-review phase|Review the complete branch diff for phase) P?(\w+)|"
                r"Review the complete branch"), "run", "code-reviewer"),
    (re.compile(r"The phases of slice|\bconsult"), "run", "consult"),
)


def plugin_version() -> str:
    try:
        doc = json.loads((TOOLS_DIR.parent / ".claude-plugin" / "plugin.json").read_text())
        return str(doc.get("version") or "")
    except (OSError, ValueError):
        return ""


# ---------------------------------------------------------------- small readings

def _epoch(ts) -> float | None:
    """An ISO stamp -> seconds since the epoch; a naive one is UTC."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _iso(t: float | None) -> str | None:
    """Seconds since the epoch -> `YYYY-MM-DDTHH:MM:SS.ffffffZ`."""
    if t is None:
        return None
    whole, us = divmod(round(t * 1_000_000), 1_000_000)
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(whole))}.{us:06d}Z"


def _str(v) -> str | None:
    if v is None:
        return None
    s = str(v)
    return None if s in ("", "None", "null") else s


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_CANON = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode


def _canon(obj) -> str:
    return _CANON(obj)


# A unit's row is built with its keys in one order, so its JSON needs no sorting to be canonical.
_ROW_JSON = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False).encode


def _digest(obj) -> str:
    raw = hashlib.sha256(_canon(obj).encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()[:22]


def _digest_text(text: str) -> str:
    raw = hashlib.sha256(text.encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()[:22]


def _digest_rows(texts: list[str]) -> str:
    """A digest of rows already in canonical JSON, which holds no newline."""
    raw = hashlib.sha256("\n".join(texts).encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()[:22]


def _base(name: str | None) -> str | None:
    """A repo root's name: the last component of a path, as the run records name a repo."""
    s = _str(name)
    return s.rstrip("/").rsplit("/", 1)[-1] if s else None


# ---------------------------------------------------------------- reducing one file

def _phase_of(h: dict):
    """A row's phase: `phase`, or the task runner's `task`, its name for a phase."""
    return h.get("phase") if h.get("phase") is not None else h.get("task")


def _reduce_row(h: dict, stage: str) -> dict:
    phase = _phase_of(h) if stage == "run" else None
    f = h.get("findings")
    return {"ts": _str(h.get("ts")), "start": _str(h.get("started_at")),
            "dur": _num(h.get("duration_s")), "phase": _str(phase),
            "role": _str(h.get("role")) or "unknown", "round": _int(h.get("round")),
            "outcome": _str(h.get("outcome")), "session": _str(h.get("session")),
            "kind": _str(h.get("kind")), "site": _str(h.get("site")),
            "findings": len(f) if isinstance(f, list) else None}


def _reduce_state(doc: dict, stage: str) -> dict:
    """The facts of a state file the labeller reads, and nothing else: what a rewrite that
    changes none of them leaves the same."""
    if not isinstance(doc, dict):
        return {}
    phases_doc = doc.get("phases") if isinstance(doc.get("phases"), dict) else None
    if phases_doc is None and isinstance(doc.get("tasks"), dict):
        phases_doc = doc["tasks"]            # the task runner's name for a phase
    phases = {}
    for pid, p in (phases_doc or {}).items():
        p = p if isinstance(p, dict) else {}
        landed = p.get("landed") if isinstance(p.get("landed"), dict) else {}
        phases[str(pid)] = {"status": _str(p.get("status")), "target": _str(p.get("target")),
                            "root": _str(landed.get("root")) or _str(p.get("worktree"))}
    labels = {}
    for step in doc.get("progress") or []:
        if isinstance(step, dict) and str(step.get("code", "")).endswith(".code"):
            code = str(step["code"])
            if code.startswith("P"):
                labels[code[1:-5]] = _str(step.get("label"))
    if stage == "run":
        done = doc.get("run_phase") == "done" if "run_phase" in doc else doc.get("phase") == "done"
    else:
        done = doc.get("phase") == "done"
    ex = doc.get("exit") if isinstance(doc.get("exit"), dict) else None
    inf = doc.get("in_flight") if isinstance(doc.get("in_flight"), dict) else None
    orch = doc.get("orchestrator") if isinstance(doc.get("orchestrator"), dict) else {}
    targets = doc.get("target_roots")
    return {
        "created_at": _str(doc.get("created_at")),
        "orch": _str(orch.get("session")),
        "done": bool(done),
        "exit": {"code": _int(ex.get("code")), "ts": _str(ex.get("ts"))} if ex else None,
        "tasks": "tasks" in doc,
        "appended": [str(p) for p in doc.get("appended_phases") or []],
        "known": [str(p) for p in doc.get("known_phases") or []],
        "phases": phases,
        "labels": labels,
        "roots": [str(t) for t in targets] if isinstance(targets, list) else [],
        "rows": [_reduce_row(h, stage) for h in doc.get("history") or [] if isinstance(h, dict)],
        "in_flight": None if inf is None else {
            "phase": _str(_phase_of(inf)) if stage == "run" else None,
            "role": _str(inf.get("role")) or "unknown", "round": _int(inf.get("round")),
            "session": _str(inf.get("session")), "start": _str(inf.get("started_at")),
            "kind": _str(inf.get("kind")), "site": _str(inf.get("site"))},
    }


def _reduce_slice_json(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    out = {k: doc[k] for k in ("card", "title") if k in doc}
    plan = doc.get("plan")
    if isinstance(plan, dict):
        out["plan"] = {k: _int(plan.get(k)) for k in ("phases", "acceptance_criteria")
                       if _int(plan.get(k)) is not None}
    co = doc.get("close_out")
    if isinstance(co, dict):
        out["close_out"] = {k: _int(co.get(k)) for k, _ in CLOSE_OUT_MEASURES
                            if _int(co.get(k)) is not None}
    prf = doc.get("plan_review_findings")
    if isinstance(prf, dict):
        out["prf"] = {str(r): len(f) for r, f in prf.items() if isinstance(f, list)}
    crf = doc.get("code_review_findings")
    if isinstance(crf, dict):
        out["crf"] = {str(p): {str(r): len(f) for r, f in rounds.items() if isinstance(f, list)}
                      for p, rounds in crf.items() if isinstance(rounds, dict)}
    ts = doc.get("triage_sessions")
    if isinstance(ts, list):
        out["triage"] = [str(s) for s in ts if _str(s)]
    return out


def _reduce_gate(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    projects = []
    for p in doc.get("projects") or []:
        if isinstance(p, dict):
            projects.append([_str(p.get("project")), _str(p.get("outcome"))])
    return {"ts": _str(doc.get("ts")), "start": _str(doc.get("started_at")),
            "dur": _num(doc.get("duration_s")), "phase": _str(doc.get("phase")),
            "role": _str(doc.get("role")), "projects": projects}


def _reduce_sweep(doc: dict) -> dict:
    if not isinstance(doc, dict):
        return {}
    results = []
    for r in doc.get("results") or []:
        if isinstance(r, dict):
            results.append({"repo": _base(r.get("repo")), "component": _str(r.get("component")),
                            "verb": _str(r.get("verb")), "outcome": _str(r.get("outcome")),
                            "dur": _num(r.get("duration_s")), "reused": bool(r.get("reused"))})
    return {"run": _int(doc.get("run")), "ran_at": _str(doc.get("ran_at")), "results": results}


def _reduce_groups(raw: bytes, stem: str) -> dict:
    g = tomllib.loads(raw.decode())
    projects = []
    for p in g.get("project") or []:
        if isinstance(p, dict):
            projects.append({"name": _str(p.get("name")), "summary": _str(p.get("summary")),
                             "slices": [str(s) for s in p.get("slices") or []]})
    return {"spec_repo": _str(g.get("spec_repo")) or stem, "repo": _str(g.get("repo")),
            "projects": projects}


def _reduce(rel: str, path: Path) -> dict | None:
    """One records file -> what the labeller keeps of it, or None for a file it does not read
    (or cannot: a half-written or broken file counts as absent)."""
    parts = rel.split("/")
    try:
        raw = path.read_bytes()
        if parts[0] == "groups":
            return {"t": "groups", **_reduce_groups(raw, path.stem)}
        doc = json.loads(raw)
    except (OSError, ValueError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    if parts[0] == "projects":
        rules = doc.get("file_classes") if isinstance(doc, dict) else None
        return {"t": "project", "repo": _str(doc.get("repo")) if isinstance(doc, dict) else None,
                "rules": rules if isinstance(rules, list) else []}
    name = parts[-1]
    if len(parts) == 4 and name in STATE_FILES:
        return {"t": "state", "stage": STATE_FILES[name], **_reduce_state(doc, STATE_FILES[name])}
    if len(parts) == 4 and name == "slice.json":
        return {"t": "slice", **_reduce_slice_json(doc)}
    if len(parts) == 5 and parts[3] == "gates" and "_gate_" in name or (
            len(parts) == 5 and parts[3] == "gates" and re.match(r"[a-z-]+_\d+\.json$", name)):
        return {"t": "gate", "name": name, **_reduce_gate(doc)}
    if len(parts) == 5 and parts[3] == "sweeps" and re.match(r"r\d+\.json$", name):
        return {"t": "sweep", **_reduce_sweep(doc)}
    return None


def _walk(data_dir: Path) -> dict[str, tuple[Path, list[int]]]:
    """Every records file the labeller reads, relative path -> (path, [size, mtime_ns, ino])."""
    out: dict[str, tuple[Path, list[int]]] = {}

    def add(entry: os.DirEntry, rel: str) -> None:
        try:
            st = entry.stat()
        except OSError:
            return
        out[rel] = (Path(entry.path), [st.st_size, st.st_mtime_ns, st.st_ino])

    def files(d: Path, rel: str, suffix: str):
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name.endswith(suffix) and e.is_file():
                        add(e, f"{rel}/{e.name}")
        except OSError:
            pass

    files(data_dir / "groups", "groups", ".toml")
    files(data_dir / "projects", "projects", ".json")
    runs = data_dir / "runs"
    try:
        specs = sorted((e for e in os.scandir(runs) if e.is_dir()), key=lambda e: e.name)
    except OSError:
        specs = []
    for spec in specs:
        try:
            slices = sorted((e for e in os.scandir(spec.path) if e.is_dir()), key=lambda e: e.name)
        except OSError:
            continue
        for sl in slices:
            rel = f"runs/{spec.name}/{sl.name}"
            try:
                with os.scandir(sl.path) as it:
                    for e in it:
                        if e.name in STATE_FILES or e.name == "slice.json":
                            if e.is_file():
                                add(e, f"{rel}/{e.name}")
                        elif e.name in ("gates", "sweeps") and e.is_dir():
                            files(Path(e.path), f"{rel}/{e.name}", ".json")
            except OSError:
                continue
    return out


# ---------------------------------------------------------------- the blob

def _blob_prefix(data_dir: Path) -> str:
    return f"{INDEX_FORMAT}:{plugin_version()}:"


def _decode_blob(blob, data_dir: Path) -> tuple[dict, dict, dict]:
    """(files, units, chunks) of a blob this version wrote for this data folder; else empty.
    The blob is its head, then each slice's rows' chunk, in the head's `chunks` order, all
    joined by `.`; a chunk is decoded only when one of its rows is read."""
    if not isinstance(blob, str) or not blob.startswith(_blob_prefix(data_dir)):
        return {}, {}, {}
    head, *chunks = blob[len(_blob_prefix(data_dir)):].split(".")
    try:
        doc = json.loads(zlib.decompress(base64.b64decode(head)))
    except (ValueError, zlib.error, TypeError):
        return {}, {}, {}
    if not isinstance(doc, dict) or doc.get("dir") != str(data_dir):
        return {}, {}, {}
    files, units, order = doc.get("files"), doc.get("units"), doc.get("chunks")
    if not isinstance(files, dict):
        return {}, {}, {}
    if not isinstance(units, dict) or not isinstance(order, list) or len(order) != len(chunks):
        return files, {}, {}
    return files, units, dict(zip(order, chunks, strict=True))


def _encode_blob(files: dict, units: dict, chunks: dict, data_dir: Path) -> str | None:
    """The blob: every file's key and what it holds for the labeller, and each slice's units
    under its files' keys, with their rows in a chunk of their own; none past MAX_BLOB."""
    order = sorted(chunks)
    raw = json.dumps({"dir": str(data_dir), "files": files, "units": units, "chunks": order},
                     separators=(",", ":"))
    text = ".".join([_blob_prefix(data_dir) + base64.b64encode(zlib.compress(raw.encode(), 1))
                     .decode(), *(chunks[k] for k in order)])
    return text if len(text) <= MAX_BLOB else None


def _encode_chunk(doc: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(doc, separators=(",", ":"))
                                          .encode(), 6)).decode()


def _decode_chunk(chunk) -> dict | None:
    """A slice's chunk: its files' reduced contents and its units' order, meta and rows; None
    for a broken one."""
    try:
        doc = json.loads(zlib.decompress(base64.b64decode(chunk)))
    except (ValueError, zlib.error, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- the tie

class Tie:
    """What the run records (and the context) say a transcript served.

    `units` is every Work Unit its labels may name, whichever Launch names which; `unit_for`
    picks a Launch's. `anchors` are the stages it is the anchor of, `named` the slices its own
    content named (the stamp's `<named>`), `slices` the slices it serves. `stage` is an
    adoption rule's stage, or R3's phase unit. A plain class rather than a dataclass, whose
    module costs a `stamps` call its import."""

    FIELDS = ("session_id", "agent_id", "agent_type", "rule", "role", "units", "anchors",
              "adopted_group", "named", "slices", "pilot", "stage")

    def __init__(self, session_id: str, agent_id: str | None = None,
                 agent_type: str | None = None, rule: str | None = None,
                 role: str | None = None, units: tuple = (), anchors: tuple = (),
                 adopted_group: str | None = None, named: tuple = (), slices: tuple = (),
                 pilot: bool = False, stage: str | None = None, _windows=None, _stages=None,
                 _sessions=None, _fixed: str | None = None, _digest: str | None = None):
        self.session_id, self.agent_id, self.agent_type = session_id, agent_id, agent_type
        self.rule, self.role, self.units, self.anchors = rule, role, units, anchors
        self.adopted_group, self.named, self.slices = adopted_group, named, slices
        self.pilot, self.stage = pilot, stage
        self._windows = [] if _windows is None else _windows      # (start, end, key)
        self._stages = [] if _stages is None else _stages         # (created, stage_key)
        self._sessions = [] if _sessions is None else _sessions   # (created, clarification)
        self._fixed = _fixed
        self._digest = _digest      # `units`' rows' digest, where the records held it

    def __repr__(self) -> str:
        return "Tie(" + ", ".join(f"{f}={getattr(self, f)!r}" for f in self.FIELDS) + ")"

    def __eq__(self, other) -> bool:
        return type(other) is Tie and self.__dict__ == other.__dict__

    __hash__ = None

    def copy(self) -> "Tie":
        """A shallow copy, as `copy.copy` makes one, for less."""
        out = object.__new__(Tie)
        out.__dict__.update(self.__dict__)
        return out

    @property
    def is_anchor(self) -> bool:
        return bool(self.anchors)

    def unit_for(self, started_at) -> str | None:
        """The lowest Work Unit a Launch starting at `started_at` carried out (§ Work Units, *How
        a session is tied to its unit*)."""
        if self.agent_id is not None:
            return None
        if self._fixed is not None:
            return self._fixed
        t = _epoch(started_at)
        if self.rule == "dispatch":
            return self._dispatch_for(t)
        if self.rule == "stage":
            return self._stage_for(t)
        return None

    def _dispatch_for(self, t: float | None) -> str | None:
        ended = [w for w in self._windows if w[1] is not None]
        running = [w for w in self._windows if w[1] is None]
        if t is None:
            return (running or ended or [(None, None, None)])[0][2]
        for start, end, key in ended:
            if (start if start is not None else end) <= t <= end:
                return key
        for start, _, key in running:
            if start is None or start <= t + PILOT_SLACK_S:
                return key
        later = sorted((w for w in ended if w[1] >= t), key=lambda w: w[1])
        if later:
            return later[0][2]
        return running[0][2] if running else None

    def _stage_for(self, t: float | None) -> str | None:
        if self._sessions and t is not None:
            cur = None
            for created, clar in self._sessions:
                if created is not None and created <= t + PILOT_SLACK_S:
                    cur = clar
            if cur:
                return self.slices[0] if self.slices else None
        if not self._stages:
            return None
        if t is None or len(self._stages) == 1:
            return self._stages[0][1]
        pick = self._stages[0][1]
        for created, key in self._stages:
            if created is not None and created <= t + PILOT_SLACK_S:
                pick = key
        return pick


# The Sessions of a conversation Pilot handed none with: one object, so that its ties are cached.
_NO_SESSIONS: tuple = ()
# A sub-agent's main thread that no run record names: all a sub-agent's tie reads of it.
_UNTIED = Tie("")


# ---------------------------------------------------------------- one slice's units

class _Slice:
    """One slice's records, and its units once compiled. A slice the blob holds unchanged
    keeps its files' reduced contents in its chunk, unread, and its head's `sessions`,
    `task_runner` and `facts` stand for them."""

    def __init__(self, spec: str, folder: str):
        self.spec, self.folder = spec, folder
        self.key = f"{spec}/{folder}"
        self.states: dict[str, dict] = {}
        self.facts: dict = {}
        self.gates: list[dict] = []
        self.sweeps: list[dict] = []
        self._compiled = None
        self._sessions: set[str] | None = None
        self._task_runner: bool | None = None
        self.sig: list = []                       # its files' keys, which its units follow
        self.reds: dict[str, dict] = {}           # rel -> its file's reduced contents
        self.cached: dict | None = None           # its units as the blob held them
        self.chunk: str | None = None             # and its chunk: their rows, its files
        self.data_dir: Path | None = None

    def take(self, rel: str, red: dict) -> None:
        self.reds[rel] = red
        t = red.get("t")
        if t == "state":
            self.states[red["stage"]] = red
        elif t == "slice":
            self.facts = red
        elif t == "gate":
            self.gates.append(red)
        elif t == "sweep":
            self.sweeps.append(red)

    def use_cache(self, head: dict, chunk: str) -> None:
        self.cached, self.chunk = head, chunk
        self._sessions = set(head["sessions"])
        self._task_runner = head["task_runner"]
        self.facts = head["facts"]

    def read_again(self) -> None:
        """Its files' reduced contents read from the data folder again, for a broken chunk."""
        self.states, self.gates, self.sweeps, self.reds = {}, [], [], {}
        for rel, *_ in self.sig:
            red = _reduce(rel, self.data_dir / rel) if self.data_dir else None
            if red is not None:
                self.take(rel, red)

    def sessions(self) -> set[str]:
        if self._sessions is not None:
            return self._sessions
        out = set()
        for st in self.states.values():
            if st.get("orch"):
                out.add(st["orch"])
            out.update(r["session"] for r in st.get("rows") or [] if r.get("session"))
            inf = st.get("in_flight")
            if inf and inf.get("session"):
                out.add(inf["session"])
        self._sessions = out
        return out

    @property
    def task_runner(self) -> bool:
        if self._task_runner is None:
            self._task_runner = any(st.get("tasks") for st in self.states.values())
        return self._task_runner

    def compiled(self) -> "_Units":
        if self._compiled is None:
            self._compiled = _Units(self, self.cached, self.chunk if self.cached else None)
            self.cached = None
        return self._compiled

    def to_head(self) -> dict:
        return {**self.compiled().to_cache(), "sessions": sorted(self.sessions()),
                "task_runner": self.task_runner, "facts": self.facts}

    def to_chunk(self) -> str:
        """Its chunk of the blob: the one it was read from, else its units' rows and order
        and its files' reduced contents."""
        if self.chunk is None:
            self.chunk = _encode_chunk({"files": self.reds, **self.compiled().to_chunk_doc()})
        return self.chunk


def _row_start(r: dict) -> float | None:
    start = _epoch(r.get("start"))
    if start is not None:
        return start
    ts, dur = _epoch(r.get("ts")), r.get("dur")
    return ts - dur if ts is not None and dur is not None else None


def _unit(key, kind, part_of, title, **kw) -> dict:
    row = {"key": key, "kind": kind, "part_of": part_of, "occasioned_by": None,
           "rework_kind": None, "title": title, "variant": None, "role": None, "round": None,
           "outcome": None, "started_at": None, "ended_at": None, "card": None, "measures": []}
    row.update(kw)
    return row


def _measures(pairs) -> list[dict]:
    return [{"measure": m, "amount": a} for m, a in pairs if a is not None]


class _Units:
    """A slice's Work Units in an order where a unit's `part_of` and `occasioned_by` stand
    before it, with what ties and anchors read off them."""

    # What the blob's head keeps of a slice's units: what `stamps` reads. Their order, meta,
    # rows, row digests and stages' members go into the slice's chunk, read only when one of
    # them is asked for (`label`), never by `stamps`.
    CACHED = ("up", "loose", "whole", "stages", "by_session", "windows", "roles", "orch",
              "anchor", "test_runs")
    CHUNKED = ("order", "meta", "rows", "dig", "members")

    def __init__(self, sl: _Slice, cached: dict | None = None, chunk: str | None = None):
        self.slice = sl
        self._order: list[str] | None = []           # every unit's key, in order
        # key -> [kind, variant, part_of, occasioned_by, place in order]
        self._meta: dict[str, list] | None = {}
        self._json: dict[str, str] | None = {}       # key -> its row's JSON
        self._dig: dict[str, str] | None = {}        # key -> the digest of its row's JSON
        self._members: dict[str, list[str]] | None = {}   # stage key -> its units, it first
        # key -> the digest of its row and every row above it (`Records._up`), where they
        # are all this slice's; `loose` the keys of the others
        self.up: dict[str, str] = {}
        self.loose: list[str] = []
        self.whole: str = ""                         # the digest of the slice's state
        self.stages: dict[str, str] = {}             # stage key -> its members' rows' digest
        self.by_session: dict[str, str] = {}         # session -> its units' rows' digest
        self._above: dict[str, frozenset] | None = {}   # key -> those keys, while building
        self.windows: dict[str, list] = {}           # session -> [(start, end, key)]
        self.roles: dict[str, str] = {}              # session -> its first row's role
        self.orch: dict[str, list] = {}              # session -> [(created, stage key)]
        self.anchor: dict[str, str] = {}             # stage key -> anchor session
        self.test_runs: dict[str, list] = {}         # stage key -> driver Test Runs
        self._rows: dict[str, dict] = {}
        self._pending: list = []                     # units added before the chunk is read
        self._added: dict[str, str] = {}             # their row digests
        self.chunk = chunk
        if cached is not None:
            for name in self.CACHED:
                setattr(self, name, cached[name])
            self._order = self._meta = self._json = self._dig = self._members = None
        else:
            self._build()
            meta, up = self._meta, self.up
            self.whole = _digest_rows([self._dig[k] for k in self._order
                                       if meta[k][0] != "stage" or meta[k][1] in ("plan", "run")])
            self.loose = [k for k in self._order if k not in up]
            self.stages = {st: _digest_rows(sorted({up[k] for k in keys}))
                           for st, keys in self._members.items() if all(k in up for k in keys)}
            for sid in {*self.windows, *self.orch}:
                keys = [w[2] for w in self.windows.get(sid, ())] + \
                    [st for _, st in self.orch.get(sid, ())]
                if keys and all(k in up for k in keys):
                    self.by_session[sid] = _digest_rows(sorted({up[k] for k in keys}))
        self._above = None

    def to_cache(self) -> dict:
        return {name: getattr(self, name) for name in self.CACHED}

    def to_chunk_doc(self) -> dict:
        return {"order": self.order, "meta": self.meta, "rows": self.json, "dig": self.dig,
                "members": self.members}

    order = property(lambda self: self._open() or self._order)
    meta = property(lambda self: self._open() or self._meta)
    json = property(lambda self: self._open() or self._json)
    dig = property(lambda self: self._open() or self._dig)
    members = property(lambda self: self._open() or self._members)

    def _open(self) -> None:
        """The chunk read, once: the units' order, meta, rows, row digests and members; a
        broken one is built again from the slice's files."""
        if self._order is not None:
            return
        doc = _decode_chunk(self.chunk)
        types = (("order", list), ("meta", dict), ("rows", dict), ("dig", dict),
                 ("members", dict))
        if isinstance(doc, dict) and all(isinstance(doc.get(k), t) for k, t in types) and \
                set(doc["order"]) == set(doc["meta"]) == set(doc["rows"]) == set(doc["dig"]) \
                and all(k in doc["dig"] for k in self.up):
            got = doc
        else:
            self.slice.read_again()
            got = _Units(self.slice).to_chunk_doc()
        self._order, self._meta, self._json = got["order"], got["meta"], got["rows"]
        self._dig, self._members = got["dig"], got["members"]
        for row, stage_key in self._pending:
            self._place(row, _ROW_JSON(row), stage_key)
        self._pending = []

    def has(self, key: str) -> bool:
        if self._order is None:
            return key in self.up or key in self._added or key in self.loose
        return key in self._dig

    def digest_of(self, key: str) -> str:
        return self._added.get(key) or self.dig[key]

    def row(self, key: str) -> dict | None:
        if key not in self._rows:
            if not self.has(key):
                return None
            self._rows[key] = json.loads(self.json[key])
        return self._rows[key]

    def _place(self, row: dict, text: str, stage_key: str | None) -> None:
        key = row["key"]
        if key in self._meta:
            return
        self._order.append(key)
        self._meta[key] = [row["kind"], row["variant"], row["part_of"], row["occasioned_by"],
                           len(self._order) - 1]
        self._json[key] = text
        self._dig[key] = _digest_text(text)
        if stage_key is not None:
            self._members.setdefault(stage_key, []).append(key)

    def _add(self, row: dict, stage_key: str | None) -> dict:
        key = row["key"]
        text = _ROW_JSON(row)
        if self._order is None:
            self._pending.append((row, stage_key))
            self._added[key] = _digest_text(text)
        else:
            self._place(row, text, stage_key)
        if self._above is not None:
            above = [x for x in (row["part_of"], row["occasioned_by"]) if x]
            if all(x in self._above for x in above):
                closure = {key}.union(*(self._above[x] for x in above))
                self._above[key] = frozenset(closure)
                self.up[key] = _digest_rows(sorted(self._dig[x] for x in closure))
        self._rows[key] = row
        return row

    def _build(self) -> None:
        sl = self.slice
        facts = sl.facts
        skey = sl.key
        starts, run_end, run_done = [], None, False
        stage_info = {}
        for stage in ("plan", "run"):
            st = sl.states.get(stage)
            if st is None:
                continue
            created = _epoch(st.get("created_at"))
            rows = st.get("rows") or []
            end = None
            if st.get("done"):
                ex = st.get("exit") or {}
                end = _epoch(ex.get("ts")) if ex.get("code") == 0 else None
                if end is None and rows:
                    end = _epoch(rows[-1].get("ts"))
            if created is not None:
                starts.append(created)
            if stage == "run":
                run_end, run_done = end, bool(st.get("done"))
            stage_info[stage] = (created, end, bool(st.get("done")))
        slice_row = _unit(
            skey, "slice", None, facts.get("title") or sl.folder,
            card=facts.get("card"), started_at=_iso(min(starts) if starts else None),
            ended_at=_iso(run_end) if run_done else None, outcome="done" if run_done else None,
            measures=_measures([("planned_phases", (facts.get("plan") or {}).get("phases")),
                                ("acceptance_criteria",
                                 (facts.get("plan") or {}).get("acceptance_criteria"))]))
        self._add(slice_row, None)
        for stage in ("plan", "run"):
            if stage not in stage_info:
                continue
            created, end, done = stage_info[stage]
            st_key = f"{skey}|{stage}"
            co = (facts.get("close_out") or {}) if stage == "run" else {}
            self._add(_unit(st_key, "stage", skey, STAGE_TITLES[stage], variant=stage,
                            started_at=_iso(created), ended_at=_iso(end) if done else None,
                            outcome="done" if done else None,
                            measures=_measures((m, co.get(k)) for k, m in CLOSE_OUT_MEASURES)),
                      st_key)
            st = sl.states[stage]
            if st.get("orch"):
                self.orch.setdefault(st["orch"], []).append((created, st_key))
                self.anchor[st_key] = st["orch"]
            self._history(stage, st_key, st)
            if st_key not in self.anchor:
                first = next((r["session"] for r in st.get("rows") or [] if r.get("session")),
                             None)
                if first:
                    self.anchor[st_key] = first
        if TRIAGE_SESSIONS and facts.get("triage"):
            for sid in facts["triage"]:
                self.orch.setdefault(sid, [])

    def _history(self, stage: str, st_key: str, st: dict) -> None:
        sl = self.slice
        rows = st.get("rows") or []
        phase_rows: dict[str | None, list[dict]] = {}
        if stage == "run":
            order = list(st.get("known") or [])
            for pid in st.get("phases") or {}:
                if pid not in order:
                    order.append(pid)
            for r in rows:
                if r["phase"] is not None and r["phase"] not in order:
                    order.append(r["phase"])
            if st.get("in_flight") and st["in_flight"].get("phase"):
                if st["in_flight"]["phase"] not in order:
                    order.append(st["in_flight"]["phase"])
            for r in rows:
                phase_rows.setdefault(r["phase"], []).append(r)
            for pid in order:
                info = (st.get("phases") or {}).get(pid) or {}
                mine = phase_rows.get(pid) or []
                first = next((r for r in mine if r["role"] not in GATE_ROLES), None) or (
                    mine[0] if mine else None)
                merged = info.get("status") == "merged"
                pkey = f"{st_key}|P{pid}"
                self._add(_unit(pkey, "phase", st_key,
                                (st.get("labels") or {}).get(pid) or f"P{pid}",
                                started_at=_iso(_row_start(first)) if first else None,
                                ended_at=_iso(_epoch(mine[-1]["ts"])) if merged and mine else None,
                                outcome="done" if merged else None), st_key)
        appended = set(st.get("appended") or [])
        completion_first = None
        if stage == "run" and not any(r["site"] for r in rows if r["role"] == "consult"):
            completion_first = next((i for i, r in enumerate(rows)
                                     if r["role"] == "consult" and r["phase"] is None), None)
        elif stage == "run":
            first = next((i for i, r in enumerate(rows)
                          if r["role"] == "consult" and r["phase"] is None), None)
            if first is not None and not rows[first]["site"]:
                completion_first = first
        triples: dict[tuple, int] = {}
        role_counts: dict[tuple, int] = {}
        last: dict[str | None, tuple[str, str | None]] = {}
        seen: dict[str | None, list[tuple[str, dict]]] = {}     # phase -> [(key, row)]
        sweep_n = 0
        sweeps_by_run = {s.get("run"): s for s in sl.sweeps}
        gate_files = {(g.get("phase"), g.get("role"), g.get("ts")): g for g in sl.gates}

        def key_of(r: dict) -> tuple[str, int | None]:
            base = f"{st_key}|P{r['phase']}" if r["phase"] is not None else st_key
            rnd = r["round"]
            if rnd is None:
                rc = (r["phase"], r["role"])
                role_counts[rc] = role_counts.get(rc, 0) + 1
                rnd = role_counts[rc]
            t = (r["phase"], r["role"], rnd)
            triples[t] = triples.get(t, 0) + 1
            n = triples[t]
            return f"{base}|{r['role']}|{rnd}" + (f".{n}" if n > 1 else ""), rnd

        def back(phase, pred):
            for k, r in reversed(seen.get(phase) or []):
                if pred(r):
                    return k
            return None

        def occasion(r: dict, kind: str | None) -> str | None:
            role, phase = r["role"], r["phase"]
            prev = (seen.get(phase) or [(None, None)])[-1][1]
            writer = role.endswith("-writer")
            if writer and (kind == "ruling" or (prev is not None and prev["role"] == role
                                                and prev["outcome"] == "question")):
                k = back(phase, lambda x: x["role"] == role and x["outcome"] == "question")
                if k:
                    return k
            if role == "code-writer":
                if kind == "review-fix" or (kind is None and prev is not None
                                            and prev["role"] == "code-reviewer"
                                            and prev["outcome"] == "issues"):
                    return back(phase, lambda x: x["role"] == "code-reviewer")
                if kind == "gate-fix" or (kind is None and prev is not None and (
                        (prev["role"] in GATE_ROLES and prev["outcome"] == "red")
                        or prev["role"] == "test-fixer")):
                    return back(phase, lambda x: x["role"] in GATE_ROLES and x["outcome"] == "red")
                return None
            if role == "test-fixer":
                if phase is not None:
                    return back(phase, lambda x: x["role"] in GATE_ROLES and x["outcome"] == "red")
                return back(None, lambda x: x["role"] == "sweep")
            if role == "consult" and phase is not None:
                return back(phase, lambda x: x["role"] == "code-reviewer")
            if role == "plan-writer" and (r["round"] or 1) > 1:
                return back(None, lambda x: x["role"] == "plan-reviewer")
            return None

        def rework(r: dict, i: int | None) -> str | None:
            if stage != "run":
                return None
            role, phase = r["role"], r["phase"]
            if role == "consult":
                if r["site"]:
                    return "consult" if r["site"] == "completion" else "rework"
                return "consult" if i is not None and i == completion_first else "rework"
            if phase is not None and phase in appended:
                return "rework"
            prev = last.get(phase)
            cont = prev is not None and prev[0] == role and prev[1] in ("question", "blocked")
            return "rework" if (r["round"] or 0) >= 2 and not cont else None

        def findings(r: dict) -> int | None:
            if r["findings"] is not None:
                return r["findings"]
            rnd = str(r["round"])
            if r["role"] == "code-reviewer":
                return ((sl.facts.get("crf") or {}).get(str(r["phase"])) or {}).get(rnd)
            if r["role"] == "plan-reviewer":
                return (sl.facts.get("prf") or {}).get(rnd)
            return None

        def place(r: dict, i: int | None) -> None:
            nonlocal sweep_n
            role, phase = r["role"], r["phase"]
            part_of = f"{st_key}|P{phase}" if phase is not None else st_key
            start = _row_start(r) if i is not None else _epoch(r.get("start"))
            end = _epoch(r.get("ts")) if i is not None else None
            if role in NOT_UNITS:
                last[phase] = (role, r["outcome"])
                return
            if role == "sweep" and stage == "run":
                sweep_n += 1
                key = f"{st_key}|sweep|{sweep_n}"
                row = _unit(key, "sweep", st_key, f"Gate sweep {sweep_n}", round=sweep_n,
                            outcome=self._outcome(r), started_at=_iso(start), ended_at=_iso(end))
                self._add(row, st_key)
                rec = sweeps_by_run.get(sweep_n)
                if rec is not None:
                    self.test_runs.setdefault(st_key, []).extend(
                        _sweep_runs(rec, key, start, end))
            elif role in GATE_ROLES:
                key, rnd = key_of(r)
                row = _unit(key, "gate", part_of,
                            f"{GATE_TITLES.get(role, role)} {rnd}", variant=role, round=rnd,
                            outcome=self._outcome(r), started_at=_iso(start), ended_at=_iso(end))
                self._add(row, st_key)
                rec = gate_files.get((phase, role, r.get("ts")))
                if rec is not None and phase is not None:
                    info = (sl.states["run"].get("phases") or {}).get(phase) or {}
                    repo = _base(info.get("root")) or _base(info.get("target"))
                    self.test_runs.setdefault(st_key, []).extend(
                        _gate_runs(rec, key, repo, start, end))
            else:
                key, rnd = key_of(r)
                kind = r["kind"]
                row = _unit(key, "dispatch", part_of, f"{role} {rnd}",
                            variant=r["kind"] or r["site"], role=role, round=r["round"] or rnd,
                            outcome=self._outcome(r) if i is not None else None,
                            started_at=_iso(start), ended_at=_iso(end),
                            occasioned_by=occasion(r, kind), rework_kind=rework(r, i),
                            measures=_measures([("review_findings", findings(r))])
                            if role in ("code-reviewer", "plan-reviewer") and i is not None
                            else [])
                self._add(row, st_key)
                if r.get("session"):
                    self.windows.setdefault(r["session"], []).append(
                        (start, end, key))
                    self.roles.setdefault(r["session"], role)
            last[phase] = (role, r["outcome"])
            seen.setdefault(phase, []).append((row["key"], r))

        for i, r in enumerate(rows):
            place(r, i)
        inf = st.get("in_flight")
        if inf:
            place({"ts": None, "start": inf.get("start"), "dur": None, "phase": inf.get("phase"),
                   "role": inf.get("role") or "unknown", "round": inf.get("round"),
                   "outcome": None, "session": inf.get("session"), "kind": inf.get("kind"),
                   "site": inf.get("site"), "findings": None}, None)

    @staticmethod
    def _outcome(r: dict) -> str | None:
        word = r["outcome"]
        return FOLDED_OUTCOMES.get(word) or (word if word in _OWN_OUTCOMES else None)

    def stage_keys(self) -> list[str]:
        return list(self.members)

    def close_out_row(self, stage: str) -> dict:
        """An old slice's triage or close-out stage, which no state file records."""
        key = f"{self.slice.key}|{stage}"
        if not self.has(key):
            self._add(_unit(key, "stage", self.slice.key, STAGE_TITLES[stage], variant=stage),
                      None)
        return self.row(key)


def _sweep_runs(rec: dict, key: str, start, end) -> list[dict]:
    """A sweep's Test Runs: one per `verb: test` result that ran in the sweep itself."""
    out = []
    ended = _epoch(rec.get("ran_at")) or end
    for r in rec.get("results") or []:
        if r.get("verb") != "test" or r.get("outcome") not in ("green", "red") or r.get("reused"):
            continue
        dur = r.get("dur")
        out.append({"work_unit": key, "suite": f"{r.get('repo')}/{r.get('component')}/test",
                    "passed": r.get("outcome") == "green", "tests": None,
                    "retries_allowed": None,
                    "started_at": _iso(ended - dur if ended is not None and dur is not None
                                       else start),
                    "ended_at": _iso(ended)})
    return out


def _gate_runs(rec: dict, key: str, repo: str | None, start, end) -> list[dict]:
    """A phase gate's Test Runs: one per `projects` entry that ran a component's tests."""
    out = []
    for project, outcome in rec.get("projects") or []:
        if outcome not in ("green", "red") or project in (None, "spec_check", "migration_check"):
            continue
        out.append({"work_unit": key, "suite": f"{repo}/{project}/test",
                    "passed": outcome == "green", "tests": None, "retries_allowed": None,
                    "started_at": _iso(_epoch(rec.get("start")) or start),
                    "ended_at": _iso(_epoch(rec.get("ts")) or end)})
    return out


# What the blob's head holds of each slice.
_HEAD = (*_Units.CACHED, "sessions", "task_runner", "facts")


# ---------------------------------------------------------------- the records

# What the blob's head holds of each slice.
_HEAD = (*_Units.CACHED, "sessions", "task_runner", "facts")


class Records:
    """Every slice of the data folder, the groups and the projects' file-class rules."""

    def __init__(self, data_dir: Path, files: dict, cached: dict | None = None):
        """`files` maps each records file to its [size, mtime_ns, ino, reduced contents]; a
        slice's file whose contents its chunk holds has 0 for them, and `cached` maps such a
        slice to (its files' keys, its head, its chunk)."""
        self.data_dir = data_dir
        self.version = plugin_version()
        self.slices: dict[str, _Slice] = {}
        self.group_files: dict[str, dict] = {}
        self.project_rules: dict[str, list] = {}
        self._by_session: dict[str, list[str]] = {}
        self._pilot: frozenset = frozenset()
        self._cache: dict = {}
        self._ups: dict[str, frozenset] = {}
        self._digs: dict[str, str] = {}             # key -> its row's digest, as _up meets it
        self._finds: dict = {}
        self._numbers: dict[str, dict] = {}         # spec repo -> (number, letter) -> slice
        lazy: dict[str, list[str]] = {}
        for rel in sorted(files):
            red = files[rel][3]
            if red is None:
                continue
            parts = rel.split("/")
            if red == 0 or red.get("t") in ("state", "slice", "gate", "sweep"):
                sl = self.slices.get(f"{parts[1]}/{parts[2]}")
                if sl is None:
                    sl = self.slices[f"{parts[1]}/{parts[2]}"] = _Slice(parts[1], parts[2])
                    sl.data_dir = data_dir
                sl.sig.append([rel, *files[rel][:3]])
                if red != 0:
                    sl.take(rel, red)
                else:
                    lazy.setdefault(sl.key, []).append(rel)
            elif red.get("t") == "groups":
                self.group_files[red["spec_repo"]] = red
            elif red.get("t") == "project":
                self.project_rules[red.get("repo") or Path(rel).stem] = red["rules"]
        for key, sl in self.slices.items():
            prev = (cached or {}).get(key)
            if prev is not None and prev[0] == sl.sig:
                sl.use_cache(prev[1], prev[2])
            elif key in lazy:
                # A slice whose files changed: the unchanged ones' contents from its old chunk,
                # else from the data folder.
                doc = _decode_chunk(prev[2]) if prev is not None else None
                held = doc.get("files") if isinstance(doc, dict) else None
                held = held if isinstance(held, dict) else {}
                for rel in lazy[key]:
                    red = held.get(rel)
                    red = red if isinstance(red, dict) else _reduce(rel, data_dir / rel)
                    if red is not None:
                        sl.take(rel, red)
        for key, sl in self.slices.items():
            for sid in sl.sessions():
                self._by_session.setdefault(sid, []).append(key)
            if TRIAGE_SESSIONS:
                for sid in sl.facts.get("triage") or []:
                    self._by_session.setdefault(sid, []).append(key)
        self._folders: dict[str, dict[str, str]] = {}
        for key, sl in self.slices.items():
            self._folders.setdefault(sl.spec, {})[sl.folder] = key

    # -- loading

    @classmethod
    def load(cls, data_dir, blob=None) -> tuple["Records", str | None]:
        """The records of `data_dir`, and the blob to hand back next time. Only the files whose
        size, mtime_ns or inode differ from the blob's are read again; a missing, stale or
        foreign blob is rebuilt."""
        data_dir = Path(data_dir)
        old, old_units, old_chunks = _decode_blob(blob, data_dir)
        found = _walk(data_dir)
        files: dict[str, list] = {}
        changed = len(old) != len(found) or not old
        for rel, (path, key) in found.items():
            prev = old.get(rel)
            if isinstance(prev, list) and len(prev) == 4 and prev[:3] == key:
                files[rel] = prev
            else:
                files[rel] = [*key, _reduce(rel, path)]
                changed = True
        cached = {}
        for key, prev in old_units.items():
            if isinstance(prev, list) and len(prev) == 2 and isinstance(prev[1], dict) and \
                    key in old_chunks and all(n in prev[1] for n in _HEAD):
                cached[key] = (prev[0], prev[1], old_chunks[key])
        records = cls(data_dir, files, cached)
        if any(sl.cached is None for sl in records.slices.values()) or \
                len(cached) != len(records.slices):
            changed = True
        if not changed:
            return records, blob
        heads = {key: [sl.sig, sl.to_head()] for key, sl in records.slices.items()}
        chunks = {key: sl.to_chunk() for key, sl in records.slices.items()}
        out = {rel: [*v[:3], 0] if v[3] is not None and rel.startswith("runs/") else v
               for rel, v in files.items()}
        return records, _encode_blob(out, heads, chunks, data_dir)

    def use_pilot(self, pilot) -> "Records":
        """The request's `pilot` header (or the list of its conversations): only the adoption
        rule and the stamp's Pilot bit read it."""
        if isinstance(pilot, dict):
            pilot = pilot.get("conversations")
        if pilot is self._pilot:
            return self
        ids = pilot if isinstance(pilot, frozenset) and all(type(c) is str for c in pilot) \
            else frozenset(str(c) for c in pilot or [])
        if ids != self._pilot:
            self._pilot = ids
            self._cache = {}
        return self

    # -- what other parts read

    @property
    def spec_repos(self) -> set[str]:
        """Every spec repo the records name: the `runs/` folders and the groups' `spec_repo`."""
        return {sl.spec for sl in self.slices.values()} | set(self.group_files)

    @property
    def spec_digest(self) -> str:
        """The digest of `spec_repos`, which every stamp covers: where a `git add -A` breaches
        `no_git_add_all` (D10) is a label of any transcript."""
        got = self.__dict__.get("_spec_dig")
        if got is None:
            got = self._spec_dig = _digest(sorted(self.spec_repos))
        return got

    def _units(self, slice_key: str) -> _Units | None:
        sl = self.slices.get(slice_key)
        return sl.compiled() if sl is not None else None

    def _row(self, key: str) -> dict | None:
        slice_key = key.split("|", 1)[0]
        units = self._units(slice_key)
        if units is None:
            return None
        row = units.row(key)
        if row is None and key.count("|") == 1 and key.endswith(("|close-out", "|triage")):
            row = units.close_out_row(key.rsplit("|", 1)[1])
        return row

    def _up(self, key: str) -> frozenset:
        """The unit and every unit above it through `part_of` and `occasioned_by`; empty for
        a key no unit has. Each unit's is taken once per load."""
        memo = self._ups
        if key in memo:
            return memo[key]
        stack, path = [key], []
        while stack:
            k = stack[-1]
            if k in memo:
                stack.pop()
                continue
            units = self._units(k.split("|", 1)[0])
            if units is None or (not units.has(k) and self._row(k) is None):
                memo[k] = frozenset()
                stack.pop()
                continue
            _, _, part_of, occ, _ = units.meta[k]
            above = [x for x in (part_of, occ) if x and x != k]
            todo = [x for x in above if x not in memo]
            if todo and k not in path:
                path.append(k)
                stack.extend(todo)
                continue
            out = {k}
            for x in above:
                out.update(memo.get(x, ()))
            memo[k] = frozenset(out)
            self._digs[k] = units.digest_of(k)
            stack.pop()
        return memo[key]

    def _closure(self, keys) -> list[str]:
        """The keys and every unit above them through `part_of` and `occasioned_by`, in an
        order where each unit's `part_of` and `occasioned_by` stand before it."""
        want: set[str] = set()
        for k in keys:
            if k:
                want |= self._up(k)

        def place(k: str) -> tuple[str, int]:
            slice_key = k.split("|", 1)[0]
            return slice_key, self._units(slice_key).meta[k][4]
        return sorted(want, key=place)

    def unit_rows(self, keys) -> list[dict]:
        """The whole row of every unit `keys` names and of every unit above them, ordered."""
        return [dict(self._row(k)) for k in self._closure(keys)]

    def stage_rows(self, stage_key: str) -> list[dict]:
        """An anchor's units: every unit of the stage, and the slice above it, ordered."""
        units = self._units(stage_key.split("|", 1)[0])
        if units is None:
            return []
        return self.unit_rows(units.members.get(stage_key) or [stage_key])

    def test_runs(self, stage_key: str) -> list[dict]:
        """The driver's Test Runs of a stage, which its anchor carries: none while O4 stands."""
        if not DRIVER_TEST_RUNS:
            return []
        return self.driver_test_runs(stage_key)

    def driver_test_runs(self, stage_key: str) -> list[dict]:
        """The driver's Test Runs of a stage, whatever O4 rules."""
        units = self._units(stage_key.split("|", 1)[0])
        return [dict(t) for t in (units.test_runs.get(stage_key) or [])] if units else []

    # -- the groups and adoption

    def _find(self, spec: str | None, ref: str | None) -> str | None:
        """A slice of one spec repo by its folder name, its path, or its number."""
        k = (spec, ref)
        if k not in self._finds:
            self._finds[k] = self._find_now(spec, ref)
        return self._finds[k]

    def _find_now(self, spec: str | None, ref: str | None) -> str | None:
        folders = self._folders.get(spec or "")
        if not folders or not ref:
            return None
        a = ref.strip().rstrip("/").split("/")[-1]
        if a in folders:
            return folders[a]
        m = re.match(r"(\d+)([a-z]?)(?:_|$)", a)
        if not m:
            return None
        numbers = self._numbers.get(spec)
        if numbers is None:
            numbers = self._numbers[spec] = {}
            for name, key in sorted(folders.items()):
                fm = re.match(r"(\d+)([a-z]?)_", name)
                if fm:
                    numbers.setdefault((int(fm.group(1)), fm.group(2)), key)
        return numbers.get((int(m.group(1)), m.group(2)))

    def adopted(self, slice_key: str) -> bool:
        """A slice of a spec repo with a groups file, run by no task runner and by no Pilot
        session (§ Work Units, *The groups*)."""
        cache = self._cache.setdefault("adopted", {})
        if slice_key not in cache:
            sl = self.slices.get(slice_key)
            cache[slice_key] = bool(
                sl is not None and sl.spec in self.group_files and not sl.task_runner
                and not (sl.sessions() & self._pilot))
        return cache[slice_key]

    def pilot_ran(self, slice_key: str) -> bool:
        if not self._pilot:
            return False
        cache = self._cache.setdefault("pilot_ran", {})
        if slice_key not in cache:
            sl = self.slices.get(slice_key)
            cache[slice_key] = bool(sl is not None and sl.sessions() & self._pilot)
        return cache[slice_key]

    def groups(self) -> list[dict]:
        """The groups `vocabularies` declares: each groups file's projects, then a group of its
        own for each adopted slice no project lists. A key is `<SpecRepo>/<lowest folder>`."""
        if "groups" in self._cache:
            return self._cache["groups"]
        out, group_of = [], {}
        for spec in sorted(self.group_files):
            gf = self.group_files[spec]
            for p in gf.get("projects") or []:
                listed = []
                for ref in p.get("slices") or []:
                    key = self._find(spec, ref)
                    listed.append(key.split("/", 1)[1] if key else str(ref).rstrip("/")
                                  .rsplit("/", 1)[-1])
                if not listed:
                    continue
                members = []
                for ref in p.get("slices") or []:
                    key = self._find(spec, ref)
                    if key and key not in group_of and self.adopted(key):
                        members.append(key)
                if not members:
                    continue
                grp = {"key": f"{spec}/{min(listed)}", "spec_repo": spec,
                       "name": p.get("name") or min(listed), "summary": p.get("summary"),
                       "slices": members}
                for key in members:
                    group_of[key] = grp["key"]
                out.append(grp)
            for folder, key in sorted(self._folders.get(spec, {}).items()):
                if key in group_of or not self.adopted(key):
                    continue
                grp = {"key": key, "spec_repo": spec,
                       "name": self.slices[key].facts.get("title") or folder, "summary": None,
                       "slices": [key]}
                group_of[key] = key
                out.append(grp)
        self._cache["groups"] = out
        self._cache["group_of"] = group_of
        return out

    def group_of(self, slice_key: str) -> str | None:
        self.groups()
        return self._cache["group_of"].get(slice_key)

    # -- the tie

    def needs_facts(self, conversation: dict, transcript: dict) -> bool:
        """Whether only the transcript's own head can tie it (R2 to R4): a main thread no run
        record names, of a conversation Pilot does not know."""
        sid = str(conversation.get("session_id"))
        return (transcript.get("agent_id") is None and sid not in self._by_session
                and not conversation.get("sessions") and sid not in self._pilot)

    def tie(self, conversation: dict, transcript: dict) -> Tie:
        """A transcript's tie (§ Work Units, *How a session is tied to its unit*). For R2 to R4
        the transcript carries `facts` (`read_facts`), or, for `stamps`, its `held` stamp,
        whose `<named>` part stands for them."""
        sid = str(conversation.get("session_id"))
        agent_id = transcript.get("agent_id")
        sessions = conversation.get("sessions") or _NO_SESSIONS
        if agent_id is not None:
            main = self._main_tie(conversation)
            return Tie(sid, agent_id=agent_id, agent_type=transcript.get("agent_type"),
                       role=f"subagent:{transcript.get('agent_type')}"
                       if transcript.get("agent_type") else None,
                       slices=main.slices, pilot=main.pilot)
        hits = self._by_session.get(sid)
        if hits:
            return self._cached_tie(sid, hits, sessions).copy()
        m = PILOT_BRIEF_RE.match(str(sessions[0].get("brief") or "")) if sessions else None
        if m:
            return Tie(sid, rule="pilot", role=f"orchestrator:{m.group(1)}")
        if sessions or sid in self._pilot:
            return Tie(sid)
        named = transcript.get("named")
        if named is None and transcript.get("facts") is not None:
            named = self.named_from_facts(transcript["facts"])
        if named is None:
            named = _named_of(transcript.get("held"))
        return self._from_named(sid, named) if named else Tie(sid)

    def _main_tie(self, conversation: dict) -> Tie:
        sid = str(conversation.get("session_id"))
        hits = self._by_session.get(sid)
        if hits:
            return self._cached_tie(sid, hits, conversation.get("sessions") or _NO_SESSIONS)
        return _UNTIED

    def _cached_tie(self, sid: str, hits: list[str], sessions: list) -> Tie:
        cache = self._cache.setdefault("ties", {})
        k = (sid, id(sessions))
        if k not in cache or cache[k][0] is not sessions:
            cache[k] = (sessions, self._recorded_tie(sid, hits, sessions))
        return cache[k][1]

    def _recorded_tie(self, sid: str, hits: list[str], sessions: list) -> Tie:
        windows, stages, units, anchors, role, slices = [], [], [], [], None, []
        for slice_key in hits:
            u = self._units(slice_key)
            if sid in u.windows:
                windows.extend(u.windows[sid])
                role = role or u.roles.get(sid)
            if sid in u.orch:
                stages.extend(u.orch[sid])
            anchors.extend(k for k, s in u.anchor.items() if s == sid)
            slices.append(slice_key)
            if TRIAGE_SESSIONS and sid in (self.slices[slice_key].facts.get("triage") or []):
                stages.append((None, u.close_out_row("triage")["key"]))
        windows.sort(key=lambda w: (w[1] is None, w[1] or 0))
        stages.sort(key=lambda s: (s[0] is None, s[0] or 0))
        units = [w[2] for w in windows] + [s[1] for s in stages]
        if windows:
            rule = "dispatch"
        else:
            rule = "stage"
            stage_name = stages[0][1].rsplit("|", 1)[1] if stages else None
            role = f"orchestrator:{stage_name}" if stage_name in ("plan", "run") else None
            if any(s.get("clarification") for s in sessions):
                units.extend(slices)
        # One slice's session: its units' rows' digest as the slice's units hold it, which is
        # `_rows_digest` over them, unless the context added the slice to them.
        digest = self._units(slices[0]).by_session.get(sid) \
            if len(slices) == 1 and len(units) == len(windows) + len(stages) and \
            not TRIAGE_SESSIONS else None
        group = None
        for slice_key in slices:
            if self.adopted(slice_key):
                group = self.group_of(slice_key)
                break
        return Tie(sid, rule=rule, role=role, units=tuple(dict.fromkeys(units)),
                   anchors=tuple(dict.fromkeys(anchors)), adopted_group=group,
                   slices=tuple(slices), pilot=any(self.pilot_ran(k) for k in slices),
                   _windows=windows, _stages=stages, _digest=digest,
                   _sessions=[(_epoch(s.get("created_at")), bool(s.get("clarification")))
                              for s in sessions])

    def named_from_facts(self, facts: dict) -> list[str]:
        """R2, R4 and R3, in that order, on what a main transcript's own head holds
        (`read_facts`): the stamp's `<named>`. Every name a rule tried is listed, as named,
        `<SpecRepo>/<ref>`, up to the one that took the transcript, which carries the rule's
        unit after an `@`: `@plan`, `@run`, `@close-out`, or R3's `@run.P<id>`."""
        named: list[str] = []
        spec = spec_of_cwd(facts.get("cwd"))
        entry = facts.get("entrypoint")

        def hit(ref_spec: str | None, ref: str | None) -> tuple[str, str] | None:
            ref = (ref or "").strip()
            ref = NAME_SAFE_RE.sub("", ref.split()[0].strip(".,;:'\"`").rstrip("/")
                                   .rsplit("/", 1)[-1]) if ref else ""
            if not ref_spec or not ref:
                return None
            name = f"{ref_spec}/{ref}"
            if name not in named:
                named.append(name)
            key = self._find(ref_spec, ref)
            return (name, key) if key and self.adopted(key) else None

        def in_text(text: str) -> tuple[str, str] | None:
            for m in FOLDER_RE.finditer(text or ""):
                sp = m.group(1) or spec
                if sp in self._folders and m.group(2) in self._folders[sp]:
                    return hit(sp, m.group(2))
            return None

        def took(found: tuple[str, str], unit: str) -> list[str]:
            named[named.index(found[0])] = f"{found[0]}@{unit}"
            return named

        if entry in ("cli", None):
            fc = facts.get("first_cmd")
            if fc and str(fc[0]).split(":")[-1] in ("plan-slice", "run-slice"):
                found = hit(spec, fc[1] if len(fc) > 1 else "")
                if found:
                    return took(found, str(fc[0]).split(":")[-1].removesuffix("-slice"))
            for loop, _verb, args in sorted(facts.get("loops") or [],
                                            key=lambda x: x[0] != "run_loop"):
                found = in_text(args)
                if found:
                    return took(found, "plan" if loop == "plan_loop" else "run")
            co = [c for c in facts.get("cmds") or [] if str(c[0]).split(":")[-1] == "close-out"]
            fp = facts.get("first_prompt") or ""
            found = None
            if co:
                found = hit(spec, co[0][1] if len(co[0]) > 1 else "")
            elif fp and CLOSE_OUT_RE.search(fp[:400]):
                found = in_text(fp)
                if found is None:
                    m = SLICE_NO_RE.search(fp) or CLOSE_OUT_CMD_RE.match(fp)
                    found = hit(spec, m.group(1)) if m else None
            if found:
                return took(found, "close-out")
        elif entry == "sdk-cli" and facts.get("first_prompt"):
            fp = facts["first_prompt"]
            for rx, stage, _role in R3_ROLES:
                m = rx.search(fp[:400])
                if m:
                    found = in_text(fp)
                    if found:
                        phase = next((g for g in m.groups() if g), None) if m.groups() else None
                        phase = NAME_SAFE_RE.sub("", phase or "")
                        return took(found, f"{stage}.P{phase}" if phase else stage)
                    break
        return named

    def _from_named(self, sid: str, named) -> Tie:
        """An R2-R4 tie from its `<named>` alone: the slices that are adopted, the group, and
        the unit of the name that took it (the one with an `@`)."""
        slices, group, unit, rule = [], None, None, None
        for name in named:
            spec, _, ref = name.partition("/")
            ref, _, took = ref.partition("@")
            key = self._find(spec, ref)
            if not (key and self.adopted(key)):
                continue
            slices.append(key)
            if not took or unit is not None:
                continue
            units = self._units(key)
            stage, _, phase = took.partition(".")
            if stage == "close-out":
                unit, rule = units.close_out_row("close-out")["key"], "R4"
            elif stage in ("plan", "run"):
                unit = f"{key}|{stage}" if units.has(f"{key}|{stage}") else key
                rule = "adopted"
                if phase and units.has(f"{key}|run|{phase}"):
                    unit = f"{key}|run|{phase}"
            group = self.group_of(key)
        if unit is None:
            return Tie(sid, named=tuple(named), slices=tuple(dict.fromkeys(slices)))
        return Tie(sid, rule=rule, named=tuple(named), slices=tuple(dict.fromkeys(slices)),
                   adopted_group=group, stage=unit, units=(unit,), _fixed=unit)

    # -- the stamp

    def _updig(self, key: str) -> str | None:
        """The digest of a unit's row and of every row above it; None for a key no unit has.
        Taken when the units were built, else from `_up`, alike."""
        units = self._units(key.split("|", 1)[0])
        if units is None:
            return None
        got = units.up.get(key)
        if got is None:
            above = self._up(key)
            if not above:
                return None
            got = units.up[key] = _digest_rows(sorted(map(self._digs.__getitem__, above)))
        return got

    def _rows_digest(self, keys) -> str:
        """A digest of the rows of the units `keys` names and of every unit above them: of
        each unit's `_updig`, in their sorted order."""
        cache = self._cache.setdefault("rows", {})
        k = tuple(keys)
        if k not in cache:
            digs = {d for d in map(self._updig, k) if d is not None}
            cache[k] = _digest_rows(sorted(digs))
        return cache[k]

    def _stage_digest(self, stage_key: str) -> str:
        cache = self._cache.setdefault("stage", {})
        if stage_key not in cache:
            units = self._units(stage_key.split("|", 1)[0])
            rows = units.stages.get(stage_key) if units else None
            if rows is None:
                keys = (units.members.get(stage_key) if units else None) or [stage_key]
                rows = self._rows_digest(keys)
            cache[stage_key] = _digest([rows, self.test_runs(stage_key)])
        return cache[stage_key]

    def _slice_digest(self, slice_key: str) -> str:
        cache = self._cache.setdefault("slice", {})
        if slice_key not in cache:
            units = self._units(slice_key)
            cache[slice_key] = units.whole if units else _digest_rows([])
        return cache[slice_key]

    def stamp_inputs(self, tie: Tie, context: dict | None = None) -> dict:
        """The run records' half of the stamp's inputs (§ The stamp): the rows of every unit
        the tie's labels may name and every unit above them, for an anchor its stages' units
        and their Test Runs, the role, the adopted group, each named slice's state, the Pilot
        bit and the spec repos (`spec_digest`). `context` is `{"conversation", "transcript", "pilot"}`; where its `pilot`
        set is not the one the tie was taken under, the tie is taken again under it, in
        place, so that the caller's tie and these inputs agree."""
        context = context or {}
        pilot = context.get("pilot")
        if pilot is not None and pilot is not self._pilot:
            if frozenset(pilot) != self._pilot:
                self.use_pilot(pilot)
                if context.get("conversation") is not None and \
                        context.get("transcript") is not None:
                    fresh = self.tie(context["conversation"], context["transcript"])
                    tie.__dict__.update(fresh.__dict__)
            elif isinstance(pilot, frozenset):
                self._pilot = pilot         # the same set: the next asks compare by identity
        recs: dict = {"role": tie.role, "group": tie.adopted_group, "pilot": tie.pilot,
                      "spec_repos": self.spec_digest}
        if tie.named:
            recs["named"] = []
            for name in tie.named:
                spec, _, ref = name.partition("/")
                key = self._find(spec, ref.partition("@")[0])
                ok = bool(key and self.adopted(key))
                recs["named"].append((name, key, ok, self.group_of(key) if ok else None,
                                      self._slice_digest(key) if ok else None))
            recs["named"] = tuple(recs["named"])
        elif tie.units:
            recs["units"] = tie._digest or self._rows_digest(sorted(tie.units))
        if tie.anchors:
            recs["stages"] = tuple((s, self._stage_digest(s)) for s in tie.anchors)
        return recs

    def stamp(self, tie: Tie, context: dict | None = None) -> str:
        """A stamp text, `1:<digest>[:<named>]`, over the records' half alone (the command
        adds the context's)."""
        text = f"{STAMP_FORMAT}:{_digest(self.stamp_inputs(tie, context))}"
        return f"{text}:{','.join(tie.named)}" if tie.named else text


def _named_of(held) -> list[str]:
    if not isinstance(held, str) or not held.startswith(f"{STAMP_FORMAT}:"):
        return []
    parts = held.split(":", 2)
    return [n for n in parts[2].split(",") if n] if len(parts) == 3 else []


def spec_of_cwd(cwd: str | None) -> str | None:
    """The spec repo of a session's working directory: /work/<Repo>[/…] or an older machine's
    /home/<user>/source/<Repo>[-2]; a spec repo is its own."""
    m = re.match(r"^/(?:work|home/[^/]+/source)/([^/]+)", cwd or "")
    if not m:
        return None
    name = re.sub(r"-\d+$", "", m.group(1))
    return name if name.endswith("Specs") else f"{name}Specs"


# ---------------------------------------------------------------- a transcript's head

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _text_lines(fh, size: int | None):
    """A binary file's lines as text, up to `size` bytes when it is given."""
    pos = 0
    for raw in fh:
        if size is not None:
            if pos >= size:
                return
            raw = raw[:size - pos]
        pos += len(raw)
        yield raw.decode("utf-8", "replace")


def read_facts(path, size: int | None = None) -> dict:
    """What the adoption rules read of a main transcript (R2 to R4): its working directory and
    entrypoint, its first person prompt and that prompt's command, its workflow commands, and
    the runs of a slice loop its Bash calls make, read with `turn_profile`'s shell reading.
    `size` reads the file as it stood when it was that long (the replay check's cuts)."""
    import sys
    sys.path.insert(0, str(TOOLS_DIR))
    import turn_profile as tp

    facts = {"cwd": None, "entrypoint": None, "first_prompt": None, "first_cmd": None,
             "cmds": [], "loops": []}
    with open(path, "rb") as fh:
        for line in _text_lines(fh, size):
            user = '"type":"user"' in line and '"tool_result"' not in line
            bash = '"name":"Bash"' in line and "_loop.py" in line
            head = facts["cwd"] is None or facts["entrypoint"] is None
            if not (user or bash or head):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(d, dict):
                continue
            if head:
                facts["cwd"] = facts["cwd"] or d.get("cwd")
                facts["entrypoint"] = facts["entrypoint"] or d.get("entrypoint")
            m = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and user and not d.get("isMeta"):
                content = m.get("content")
                if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                origin = d.get("origin")
                if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
                    continue
                t = _text_of(content).strip()
                if not t or t.startswith(NOT_PROMPTS):
                    continue
                cmd = None
                cn = CMD_NAME_RE.search(t[:600])
                if cn:
                    name = cn.group(1)
                    if ":" not in name and name not in WORKFLOW_COMMANDS:
                        continue
                    ca = CMD_ARGS_RE.search(t)
                    cmd = [name, (ca.group(1) if ca else "").strip()[:300]]
                    facts["cmds"].append(cmd)
                if facts["first_prompt"] is None:
                    facts["first_prompt"], facts["first_cmd"] = t[:600], cmd
            elif d.get("type") == "assistant" and bash:
                for b in m.get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"
                            and b.get("name") == "Bash"):
                        continue
                    command = str((b.get("input") or {}).get("command") or "")
                    for seg in tp.bash_segments(command):
                        s = tp._unwrap(seg)
                        wm = tp.WORKFLOW_RE.match(s)
                        if wm and wm.group(1) in ("run_loop", "plan_loop"):
                            rest = s[wm.end():]
                            facts["loops"].append([wm.group(1), tp._verb(rest), rest[:300]])
    return facts
