"""The replay check: labelling a transcript in parts gives what labelling it whole gives.

    python3 -B labeller.py check [--projects DIR] [--plugins DIR] [--data DIR] [--sample N]
                                 [--cuts K] [--every N] [--seed S] [--context FILE]
                                 [--paths FILE] [PATH...]

`docs/labeller.md` § The replay check. A full replay is the specification (F152.16): for each
transcript the check labels the file whole, then grows it the way the collector meets it —
labelled whole as it stood at a cut, then from the boundary and checkpoint that handed back at
every later cut, an answer `whole` labelled whole again — merges the parts as Pilot does, and
compares the merge with the whole, label by label. It also asks `stamps` for every transcript
with the label's stamp held, which must give that stamp back.

The check stands in for the collector: it reads the Calls by `message.id` in order of their
first line, treats a main thread as one Launch, reads a sub-agent's `agent_type` from its
`agent-*.meta.json`, and takes Pilot's context from `--context` alone. It writes nothing: a cut
is the file read as it stood when it was that long. Exit 0 when every transcript agrees, 1 when
one differs or fails, 2 for arguments it cannot use.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

DEFAULT_SAMPLE = 50
DEFAULT_CUTS = 5
DEFAULT_EVERY = 200
LABEL_FIELDS = ("transcript", "launches", "calls", "segments", "tool_calls", "events",
                "context_parts", "test_runs", "ci_waits", "documents")


class Usage(Exception):
    """Arguments the check cannot use: exit 2."""


# ---------------------------------------------------------------------------
# The transcripts, as the collector finds them


def find_transcripts(projects: Path) -> list[Path]:
    """Every main thread (`<project>/<session>.jsonl`) and sub-agent (`agent-*.jsonl` under
    `<project>/<session>/subagents/`) under `projects`, sorted."""
    out = list(projects.glob("*/*.jsonl"))
    out += [p for p in projects.glob("*/*/subagents/**/agent-*.jsonl") if p.is_file()]
    return sorted(out)


def identify(path: Path, projects: Path) -> dict:
    """The session id, agent id, agent type and path relative to `projects` of a file."""
    rel = path.relative_to(projects)
    parts = rel.parts
    if len(parts) == 2:
        return {"session_id": path.stem, "agent_id": None, "agent_type": None,
                "path": rel.as_posix()}
    agent_id = path.stem[len("agent-"):] if path.stem.startswith("agent-") else path.stem
    agent_type = None
    try:
        meta = json.loads(path.with_name(f"{path.stem}.meta.json").read_text())
        agent_type = meta.get("agentType") if isinstance(meta, dict) else None
    except (OSError, ValueError):
        pass
    return {"session_id": parts[1], "agent_id": agent_id, "agent_type": agent_type,
            "path": rel.as_posix()}


class Facts:
    """What the collector reads off one file: each Call's id with the byte its first line
    starts at and the byte that line's JSON ends at (a cut at or past it reads the line), the
    owner Call of each tool use, and the first line's time."""

    def __init__(self, path: Path):
        self.size = path.stat().st_size
        self.calls: list[tuple[str, int, int]] = []
        self.owner: dict[str, str] = {}
        self.first_ts: str | None = None
        seen: set[str] = set()
        pos = 0
        with path.open("rb") as fh:
            for raw in fh:
                start, pos = pos, pos + len(raw)
                if b'"assistant"' not in raw and (self.first_ts is not None
                                                  or b'"timestamp"' not in raw):
                    continue
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(o, dict):
                    continue
                if self.first_ts is None and isinstance(o.get("timestamp"), str):
                    self.first_ts = o["timestamp"]
                msg = o.get("message")
                if o.get("type") != "assistant" or not isinstance(msg, dict):
                    continue
                mid = msg.get("id")
                if not isinstance(mid, str) or not mid:
                    continue
                if mid not in seen:
                    seen.add(mid)
                    self.calls.append((mid, start, start + len(raw.rstrip(b"\r\n"))))
                for b in msg.get("content") or ():
                    if isinstance(b, dict) and b.get("type") == "tool_use" and \
                            isinstance(b.get("id"), str):
                        self.owner.setdefault(b["id"], mid)

    def calls_at(self, size: int) -> list[str]:
        """The Calls the file held when it was `size` bytes long."""
        return [mid for mid, _, end in self.calls if end <= size]

    def starts(self) -> list[int]:
        return [start for _, start, _ in self.calls]


# ---------------------------------------------------------------------------
# One transcript: the whole, the parts, the merge


def _request_item(ident: dict, facts: Facts, size: int, prev: dict | None) -> dict:
    """The transcript of a `label` request for the file as it stood at `size`: whole, or from
    the last answer's boundary on with its checkpoint."""
    ids = facts.calls_at(size)
    main = ident["agent_id"] is None
    calls = [{"id": m, "position": k + 1, **({"launch": 1} if main else {})}
             for k, m in enumerate(ids)]
    item = {"agent_id": ident["agent_id"], "path": ident["path"], "mode": "whole",
            "launches": [{"n": 1, "started_at": facts.first_ts}] if main and ids else [],
            "calls": calls, "size": size}
    if ident["agent_type"]:
        item["agent_type"] = ident["agent_type"]
    if prev is not None:
        b = prev["boundary"]
        pos = ids.index(b["call"]) if b["call"] in ids else len(ids)
        item.update({"mode": "appended", "from": b, "checkpoint": prev["checkpoint"],
                     "calls": calls[pos:]})
    return item


def merge(acc: dict | None, labels: dict, handed: set, owner: dict) -> dict:
    """Pilot's merge (assertion 561): the rows of the Calls before the boundary kept, those of
    the handed Calls replaced, every Segment from the first one handed on replaced, and the
    rows an appended answer always gives taken whole."""
    new = json.loads(json.dumps(labels))
    if acc is None:
        return new
    out = {"calls": [c for c in acc["calls"] if c["id"] not in handed] + new["calls"]}
    first = min((s["position"] for s in new["segments"]), default=10 ** 9)
    out["segments"] = [s for s in acc["segments"] if s["position"] < first] + new["segments"]
    for f in ("events", "context_parts"):
        out[f] = [r for r in acc[f] if r["call"] not in handed] + new[f]
    # A stage's own Test Runs, with no Tool Call, come with every answer of its anchor.
    for f in ("tool_calls", "test_runs", "ci_waits"):
        out[f] = [r for r in acc[f] if r.get("tool_use_id") is not None
                  and owner.get(r["tool_use_id"]) not in handed] + new[f]
    n0 = min((x["n"] for x in new["launches"]), default=10 ** 9)
    out["launches"] = [x for x in acc["launches"] if x["n"] < n0] + new["launches"]
    out["transcript"], out["documents"] = new["transcript"], new["documents"]
    return out


def _keyed(store: dict, line: dict) -> None:
    """The rows Pilot writes by their keys and never deletes at a relabel: units, Test
    Suites, CI Builds."""
    for u in line.get("units") or ():
        store[("unit", u.get("key"))] = u
    for s in line.get("test_suites") or ():
        store[("suite", s.get("code"))] = s
    for b in line.get("ci_builds") or ():
        store[("build", b.get("job"), b.get("number"))] = b


def _norm(labels: dict) -> dict:
    return {f: sorted(json.dumps(r, sort_keys=True) for r in labels.get(f) or ())
            for f in LABEL_FIELDS}


def first_difference(want: dict, got: dict) -> str | None:
    """The first label that differs, as `field: whole <row> / parts <row>`, or None."""
    a, b = _norm(want), _norm(got)
    for f in LABEL_FIELDS:
        if a[f] != b[f]:
            only_w = [r for r in a[f] if r not in b[f]]
            only_p = [r for r in b[f] if r not in a[f]]
            return (f"{f}: whole {_short(only_w[0]) if only_w else '-'}"
                    f" / parts {_short(only_p[0]) if only_p else '-'}")
    return None


def _short(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


class Checker:
    """The check over one home: the run records loaded once, Pilot's context by
    conversation, and the timings."""

    def __init__(self, api, home: dict, context: dict, pilot: frozenset):
        import labeller_engine
        import labeller_records
        self.api, self.home, self.context, self.pilot = api, home, context, pilot
        self.engine = labeller_engine
        self.projects = Path(home["projects"])
        t0 = time.perf_counter()
        self.records, self.index = labeller_records.Records.load(api.data_dir(home), None)
        self.load_s = time.perf_counter() - t0
        self.whole_s: list[tuple[float, int]] = []   # (seconds, bytes)
        self.appended_s: list[float] = []

    def conversation(self, ident: dict) -> dict:
        ctx = self.context.get(ident["session_id"]) or {}
        return {"session_id": ident["session_id"], "sessions": list(ctx.get("sessions") or []),
                "documents": list(ctx.get("documents") or [])}

    def label(self, ident: dict, facts: Facts, size: int, prev: dict | None,
              timed: bool = False):
        item = _request_item(ident, facts, size, prev)
        conv = self.conversation(ident)
        conv["transcripts"] = [item]
        t0 = time.perf_counter()
        line = self.api.label_one_transcript(self.engine, self.records, conv, item,
                                             self.projects, self.pilot)
        took = time.perf_counter() - t0
        if timed:
            self.whole_s.append((took, size))
        elif prev is not None:
            self.appended_s.append(took)
        return json.loads(json.dumps(line)), item

    def grow(self, ident: dict, facts: Facts, cuts: list[int]):
        """The file grown through `cuts` to its end, as the collector labels it: (the merged
        labels, the keyed rows, the `why`s of the answers `whole`), or (None, error, whys)."""
        acc = prev = None
        keyed: dict = {}
        whys: list[str] = []
        for size in [*cuts, facts.size]:
            go_on = prev if prev is not None and prev.get("boundary") and \
                prev.get("checkpoint") else None
            line, item = self.label(ident, facts, size, go_on)
            if line.get("answer") == "whole":
                whys.append(line.get("why") or "?")
                line, item = self.label(ident, facts, size, None)
                acc = None
            if line.get("answer") != "labels":
                err = line.get("error") or {}
                return None, f"{err.get('code')} at byte {size}: {err.get('detail')}", whys
            if item["mode"] == "whole":
                acc = None
            acc = merge(acc, line["labels"], {c["id"] for c in item["calls"]}, facts.owner)
            _keyed(keyed, line)
            prev = line
        return acc, keyed, whys

    def plans(self, facts: Facts, rnd: random.Random, cuts: int, every: int) -> list[list[int]]:
        """The cuts to grow the file through: just before every Call's first line, one at a
        time, for a transcript of fewer than `every` Calls, else `cuts` of them at random; and
        `cuts` runs of one to three random bytes."""
        starts = facts.starts()[1:]
        if len(facts.calls) < every:
            out = [[c] for c in starts]
        else:
            out = [[c] for c in sorted(rnd.sample(starts, min(cuts, len(starts))))]
        if facts.size > 1:
            for _ in range(cuts):
                k = rnd.randint(1, 3)
                out.append(sorted(rnd.sample(range(1, facts.size), min(k, facts.size - 1))))
        return out

    def check_one(self, path: Path, rnd: random.Random, cuts: int, every: int) -> dict:
        """One transcript's result: `ok`, `differs` with the first label and the cut, or
        `error`."""
        ident = identify(path, self.projects)
        out = {"path": ident["path"], "calls": 0, "cuts": 0, "whys": {}, "status": "ok",
               "detail": None, "stamp": None}
        try:
            facts = Facts(path)
        except OSError as e:
            return {**out, "status": "error", "detail": f"unreadable: {e}"}
        out["calls"] = len(facts.calls)
        whole, _ = self.label(ident, facts, facts.size, None, timed=True)
        if whole.get("answer") != "labels":
            err = whole.get("error") or {}
            return {**out, "status": "error", "detail": f"{err.get('code')}: {err.get('detail')}"}
        out["stamp"] = whole.get("stamp")
        keyed_whole: dict = {}
        _keyed(keyed_whole, whole)
        for plan in self.plans(facts, rnd, cuts, every):
            out["cuts"] += 1
            got, keyed, whys = self.grow(ident, facts, plan)
            for w in whys:
                out["whys"][w] = out["whys"].get(w, 0) + 1
            if got is None:
                return {**out, "status": "error", "detail": f"cut {plan}: {keyed}"}
            diff = first_difference(whole["labels"], got)
            if diff is None and keyed != keyed_whole:
                k = next(k for k in sorted(set(keyed) | set(keyed_whole), key=str)
                         if keyed.get(k) != keyed_whole.get(k))
                diff = f"{k[0]} {k[1:]}: whole {_short(json.dumps(keyed_whole.get(k)))}" \
                       f" / parts {_short(json.dumps(keyed.get(k)))}"
            if diff is not None:
                return {**out, "status": "differs", "detail": f"cut {plan}: {diff}"}
        return out

    def stamps(self, results: list[dict], idents: dict) -> tuple[float, list[str]]:
        """One `stamps` call over every labelled transcript with its label's stamp held: the
        time it took, and the paths whose stamp it did not give back."""
        convs: dict[str, dict] = {}
        paths: dict[str, list[str]] = {}
        for r in results:
            if r["status"] == "error" or r["stamp"] is None:
                continue
            ident = idents[r["path"]]
            sid = ident["session_id"]
            conv = convs.setdefault(sid, {**self.conversation(ident), "transcripts": []})
            t = {"agent_id": ident["agent_id"], "held": r["stamp"]}
            if ident["agent_type"]:
                t["agent_type"] = ident["agent_type"]
            conv["transcripts"].append(t)
            paths.setdefault(sid, []).append(r["path"])
        request = {"contract": 1, "home": self.home, "index": self.index,
                   "pilot": {"conversations": sorted(self.pilot)},
                   "conversations": list(convs.values())}
        t0 = time.perf_counter()
        answer = self.api.stamps(request, self.records, self.index)
        took = time.perf_counter() - t0
        # The answer is in request order, conversation by conversation.
        asked = [(p, t["held"]) for sid, conv in convs.items()
                 for p, t in zip(paths[sid], conv["transcripts"], strict=True)]
        bad = [p for (p, held), s in zip(asked, answer["stamps"], strict=True)
               if s["stamp"] != held]
        return took, bad


# ---------------------------------------------------------------------------
# The command


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="labeller.py check",
        description="The replay check (docs/labeller.md § The replay check): label each "
                    "transcript whole and in parts, and compare.")
    home = Path.home() / ".claude"
    p.add_argument("--projects", default=str(home / "projects"),
                   help="the home's projects folder (default ~/.claude/projects)")
    p.add_argument("--plugins", default=str(home / "plugins"),
                   help="the home's plugins folder (default ~/.claude/plugins)")
    p.add_argument("--data", help="the run records' folder, in place of the plugins' own")
    p.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                   help=f"transcripts drawn from --projects when none is named "
                        f"(default {DEFAULT_SAMPLE}; 0 for all)")
    p.add_argument("--cuts", type=int, default=DEFAULT_CUTS,
                   help=f"random cut runs per transcript (default {DEFAULT_CUTS})")
    p.add_argument("--every", type=int, default=DEFAULT_EVERY,
                   help=f"a transcript of fewer Calls is cut before every Call "
                        f"(default {DEFAULT_EVERY})")
    p.add_argument("--seed", type=int, default=0, help="the random seed (default 0)")
    p.add_argument("--context", help="a JSON file of conversations as Pilot hands them, a list "
                                     "or {\"pilot\", \"conversations\"}")
    p.add_argument("--paths", help="a file of transcript paths, one a line")
    p.add_argument("path", nargs="*", help="transcripts, absolute or under --projects")
    return p


def _context(path: str | None) -> tuple[dict, frozenset]:
    if not path:
        return {}, frozenset()
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Usage(f"--context {path}: {e}") from None
    convs = doc.get("conversations") if isinstance(doc, dict) else doc
    if not isinstance(convs, list):
        raise Usage(f"--context {path}: no list of conversations")
    pilot = doc.get("pilot") if isinstance(doc, dict) else None
    named = (pilot or {}).get("conversations") if isinstance(pilot, dict) else None
    by_id = {c["session_id"]: c for c in convs
             if isinstance(c, dict) and isinstance(c.get("session_id"), str)}
    return by_id, frozenset(x for x in named or () if isinstance(x, str))


def _selected(args, projects: Path) -> list[Path]:
    named = list(args.path)
    if args.paths:
        try:
            named += [ln.strip() for ln in Path(args.paths).read_text().splitlines()
                      if ln.strip()]
        except OSError as e:
            raise Usage(f"--paths {args.paths}: {e}") from None
    if named:
        out = []
        for n in named:
            p = Path(n)
            p = p if p.is_absolute() else projects / p
            try:
                p.resolve().relative_to(projects.resolve())
            except ValueError:
                raise Usage(f"{n} is not under {projects}") from None
            out.append(p)
        return out
    every = find_transcripts(projects)
    if args.sample <= 0 or args.sample >= len(every):
        return every
    return sorted(random.Random(args.seed).sample(every, args.sample))


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms"


def main(argv: list[str], api, stdout=None) -> int:
    out = stdout or sys.stdout

    def say(text: str = "") -> None:
        out.write(text + "\n")
        out.flush()

    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    projects = Path(args.projects)
    home = {"projects": str(projects), "plugins": args.plugins}
    if args.data:
        home["data"] = args.data
    try:
        if not projects.is_dir():
            raise Usage(f"{projects} is not a folder")
        context, pilot = _context(args.context)
        paths = _selected(args, projects)
        checker = Checker(api, home, context, pilot)
    except Usage as e:
        say(f"labeller.py check: {e}")
        return 2
    except api.Refusal as r:
        say(f"labeller.py check: {r.detail}")
        return 2
    rnd = random.Random(args.seed)
    results, idents = [], {}
    t0 = time.perf_counter()
    for path in paths:
        r = checker.check_one(path, rnd, args.cuts, args.every)
        idents[r["path"]] = identify(path, projects)
        results.append(r)
        whys = "".join(f" {w}×{n}" for w, n in sorted(r["whys"].items()))
        tail = f"  {r['detail']}" if r["detail"] else ""
        say(f"{r['status']:7} {r['path']}  calls {r['calls']}, cuts {r['cuts']}"
            f"{', answered whole:' + whys if whys else ''}{tail}")
    total = time.perf_counter() - t0
    stamp_s, bad = checker.stamps(results, idents)
    for p in bad:
        say(f"stamp   {p}  `stamps` did not give back the label's stamp")
    ok = sum(r["status"] == "ok" for r in results)
    differ = sum(r["status"] == "differs" for r in results)
    errors = sum(r["status"] == "error" for r in results)
    say()
    say(f"{len(results)} transcripts: {ok} agree, {differ} differ, {errors} failed; "
        f"{len(bad)} stamps not given back")
    whole = checker.whole_s
    if whole:
        secs = sum(s for s, _ in whole)
        mb = sum(b for _, b in whole) / 1e6
        biggest = max(whole, key=lambda x: x[1])
        say(f"whole labelling: {len(whole)} transcripts, {secs:.2f} s over {mb:.1f} MB "
            f"({secs / mb * 1000 if mb else 0:.1f} ms/MB); the largest, "
            f"{biggest[1] / 1e6:.1f} MB, {_ms(biggest[0])}")
    app = sorted(checker.appended_s)
    if app:
        p95 = app[min(len(app) - 1, int(len(app) * 0.95))]
        say(f"appended labelling: {len(app)} runs, median {_ms(statistics.median(app))}, "
            f"p95 {_ms(p95)}, max {_ms(app[-1])}")
    n = sum(r["stamp"] is not None for r in results)
    say(f"stamps: {n} transcripts in one call, {_ms(stamp_s)}; the run records loaded "
        f"cold in {_ms(checker.load_s)}")
    say(f"the check: {total:.1f} s")
    return 0 if ok == len(results) and not bad else 1
