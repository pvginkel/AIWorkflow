#!/usr/bin/env python3
"""Slice-scoped token / cost / wall-clock accounting for AI-workflow runs.

Attributes EVERY conversation to a *slice* and counts the whole thing:

  * top-level "manager" sessions  — the root orchestrator (`run-slice`) and the
    per-project sessions (controller/worker/bot/contracts/vscode-extension) that
    `claude_session.py` drives. This is where the orchestrator test-running cost
    lands, and it is easy to miss if you count only the sub-agents.
  * their sub-agent transcripts    — plan/code writer+reviewer, slice-verifier,
    Explore, etc. (the `*/subagents/agent-*.jsonl` files).

Two accounting details:
  1. DEDUP by message.id. The stream-json transcript logs each assistant message
     multiple times (same message.id, identical usage). Naive summation
     overcounts; we keep one record per (file, message.id).
  2. We attribute per slice by the dominant `slice NNN` mention across the
     conversation and its sub-agents' task descriptions.

Outputs (into the same dir as this script unless --out given):
  * slice_ranking.csv   — one row per slice: conversations, tokens, $, wall-clock
  * sessions.csv        — one row per conversation (for drilling into a slice)
  * slice_roles.json    — per-slice role breakdown (manager:<proj> / subagent:<type>)
  * prints a ranked table to stdout

Usage:
  python3 slice_costs.py                       # default KubeCoder project globs
  python3 slice_costs.py --slice 058           # detail one slice
  python3 slice_costs.py ~/.claude/projects/-work-KubeCoder*
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# Price table: USD per 1,000,000 tokens (public Anthropic sticker prices).
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8":            {"input": 5.0,  "output": 25.0},
    "claude-sonnet-5":           {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0,  "output": 5.0},
    "claude-haiku-4-5":          {"input": 1.0,  "output": 5.0},
    "claude-fable-5":            {"input": 10.0, "output": 50.0},
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10
USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}
SLICE_RE = re.compile(r"slice[ _#]*0*(\d{2,3})", re.I)
DEFAULT_FOLDERS = ["~/.claude/projects/-work-KubeCoder*"]

# project folder slug -> short manager role name
PROJECT_ROLE = {
    "-work-KubeCoder": "root",
    "-work-KubeCoder-controller": "controller",
    "-work-KubeCoder-worker": "worker",
    "-work-KubeCoder-bot": "bot",
    "-work-KubeCoder-packages-kubecoder-contracts": "contracts",
    "-work-KubeCoder-vscode-extension": "vscode-extension",
}


def cost_for(model: str, tok: dict[str, int]) -> float:
    base = PRICES.get(model)
    if base is None:
        return 0.0
    rates = {
        "input": base["input"],
        "output": base["output"],
        "cache_write": base["input"] * CACHE_WRITE_MULT,
        "cache_read": base["input"] * CACHE_READ_MULT,
    }
    return sum(tok.get(t, 0) / 1_000_000 * rates[t] for t in USAGE_KEYS)


def parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, AttributeError):
        return None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    out.append(json.dumps(b.get("input", ""))[:2000])
                elif b.get("type") == "tool_result":
                    c = b.get("content", "")
                    out.append(c if isinstance(c, str) else json.dumps(c)[:2000])
        return " ".join(out)
    return ""


class Conv:
    """One conversation = one top-level session OR one sub-agent transcript."""

    __slots__ = ("path", "kind", "role", "project", "parent", "agent_type",
                 "tok_by_model", "turns", "raw_turns", "start", "end",
                 "slice_hist", "desc", "_slice")

    def __init__(self, path: Path, kind: str, role: str, project: str):
        self.path = path
        self.kind = kind            # "manager" | "subagent"
        self.role = role            # manager:<proj>  or  subagent:<agentType>
        self.project = project
        self.parent: str | None = None
        self.agent_type: str | None = None
        self.tok_by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: dict.fromkeys(USAGE_KEYS, 0))
        self.turns = 0              # deduped billed messages
        self.raw_turns = 0          # every assistant record (for dup ratio)
        self.start: datetime | None = None
        self.end: datetime | None = None
        self.slice_hist: dict[str, int] = defaultdict(int)
        self.desc = ""

    def total_tokens(self) -> int:
        return sum(t[k] for t in self.tok_by_model.values() for k in USAGE_KEYS)

    def cost(self) -> float:
        return sum(cost_for(m, t) for m, t in self.tok_by_model.items())

    def duration_s(self) -> float:
        if self.start and self.end:
            return (self.end - self.start).total_seconds()
        return 0.0


def scan_file(path: Path, conv: Conv) -> None:
    seen: set[str] = set()
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = obj.get("type")
        if typ not in ("assistant", "user"):
            continue
        msg = obj.get("message") or {}
        txt = text_of(msg.get("content"))
        if txt:
            for m in SLICE_RE.finditer(txt):
                conv.slice_hist["%03d" % int(m.group(1))] += 1
        ts = parse_ts(obj.get("timestamp", ""))
        if ts:
            conv.start = ts if conv.start is None else min(conv.start, ts)
            conv.end = ts if conv.end is None else max(conv.end, ts)
        if typ != "assistant":
            continue
        usage = msg.get("usage")
        if not usage:
            continue
        conv.raw_turns += 1
        mid = msg.get("id")
        if mid and mid in seen:
            continue          # duplicate billed message — dedup
        if mid:
            seen.add(mid)
        conv.turns += 1
        model = msg.get("model", "unknown")
        bucket = conv.tok_by_model[model]
        for t, uk in USAGE_KEYS.items():
            bucket[t] += usage.get(uk, 0) or 0


def load(folders: list[str]) -> list[Conv]:
    convs: list[Conv] = []
    for spec in folders:
        for root in glob.glob(os.path.expanduser(spec)):
            rootp = Path(root)
            slug = rootp.name
            proj = PROJECT_ROLE.get(slug, slug)
            # top-level manager sessions: <folder>/<session>.jsonl
            for f in sorted(rootp.glob("*.jsonl")):
                c = Conv(f, "manager", f"manager:{proj}", proj)
                scan_file(f, c)
                if c.turns:
                    convs.append(c)
            # sub-agents: <folder>/<session>/subagents/agent-*.jsonl
            for f in sorted(rootp.glob("*/subagents/agent-*.jsonl")):
                meta = f.with_suffix(".meta.json")
                atype, desc = None, ""
                if meta.exists():
                    try:
                        md = json.loads(meta.read_text())
                        atype = md.get("agentType")
                        desc = md.get("description", "") or ""
                    except (json.JSONDecodeError, OSError):
                        pass
                c = Conv(f, "subagent", "", proj)
                c.parent = f.parents[1].name
                c.agent_type = atype or "unknown"
                c.role = f"subagent:{c.agent_type}"
                c.desc = desc
                if desc:
                    for m in SLICE_RE.finditer(desc):
                        c.slice_hist["%03d" % int(m.group(1))] += 3  # explicit → weight
                scan_file(f, c)
                if c.turns:
                    convs.append(c)
    return convs


def attribute(convs: list[Conv]) -> dict[str, str]:
    """session_path -> slice. Managers vote from own+subagents' histograms."""
    # index subagents by parent session id
    subs_by_parent: dict[str, list[Conv]] = defaultdict(list)
    for c in convs:
        if c.kind == "subagent" and c.parent:
            subs_by_parent[c.parent].append(c)
    slice_of: dict[str, str] = {}
    for c in convs:
        if c.kind != "manager":
            continue
        hist: dict[str, int] = defaultdict(int)
        for k, v in c.slice_hist.items():
            hist[k] += v
        sid = c.path.stem
        for s in subs_by_parent.get(sid, []):
            for k, v in s.slice_hist.items():
                hist[k] += v
        if hist:
            top = max(hist.items(), key=lambda kv: kv[1])
            total = sum(hist.values())
            slice_of[str(c.path)] = top[0]
            c.slice_hist = dict(hist)              # store merged for reporting
            c.desc = f"{top[1]}/{total} mentions -> {top[0]}"
        else:
            slice_of[str(c.path)] = "none"
    # subagents inherit their parent manager's slice
    parent_slice: dict[str, str] = {}
    for c in convs:
        if c.kind == "manager":
            parent_slice[c.path.stem] = slice_of[str(c.path)]
    for c in convs:
        if c.kind == "subagent":
            slice_of[str(c.path)] = parent_slice.get(c.parent or "", "none")
    return slice_of


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", default=DEFAULT_FOLDERS)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--slice", help="print per-conversation detail for one slice")
    ap.add_argument("--min-cost", type=float, default=0.0)
    args = ap.parse_args(argv)

    convs = load(args.folders)
    slice_of = attribute(convs)
    for c in convs:
        c._slice = slice_of[str(c.path)]  # type: ignore[attr-defined]

    # ---- per-slice aggregation ------------------------------------------
    agg: dict[str, dict] = defaultdict(lambda: {
        "cost": 0.0, "tokens": 0, "turns": 0, "raw_turns": 0,
        "convs": 0, "managers": 0, "subagents": 0,
        "roles": defaultdict(lambda: {"cost": 0.0, "tokens": 0, "turns": 0, "n": 0}),
        "projects": defaultdict(int),
        "start": None, "end": None, "active_s": 0.0,
    })
    for c in convs:
        s = c._slice  # type: ignore[attr-defined]
        a = agg[s]
        a["cost"] += c.cost()
        a["tokens"] += c.total_tokens()
        a["turns"] += c.turns
        a["raw_turns"] += c.raw_turns
        a["convs"] += 1
        a["managers"] += c.kind == "manager"
        a["subagents"] += c.kind == "subagent"
        r = a["roles"][c.role]
        r["cost"] += c.cost(); r["tokens"] += c.total_tokens()
        r["turns"] += c.turns; r["n"] += 1
        if c.kind == "manager":
            a["projects"][c.project] += 1
        if c.start:
            a["start"] = c.start if a["start"] is None else min(a["start"], c.start)
        if c.end:
            a["end"] = c.end if a["end"] is None else max(a["end"], c.end)
        a["active_s"] += c.duration_s()

    out = Path(args.out)
    # ---- sessions.csv ---------------------------------------------------
    with (out / "sessions.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slice", "kind", "role", "project", "agent_type", "session_id",
                    "start", "end", "dur_s", "turns", "raw_turns", "tokens", "cost_usd", "note"])
        for c in sorted(convs, key=lambda c: (c._slice, -c.cost())):  # type: ignore[attr-defined]
            w.writerow([c._slice, c.kind, c.role, c.project, c.agent_type or "",  # type: ignore[attr-defined]
                        c.path.stem if c.kind == "manager" else c.path.name,
                        c.start.isoformat() if c.start else "",
                        c.end.isoformat() if c.end else "",
                        f"{c.duration_s():.0f}", c.turns, c.raw_turns,
                        c.total_tokens(), f"{c.cost():.2f}", c.desc])

    # ---- slice_ranking.csv + slice_roles.json ---------------------------
    ranking = []
    roles_json = {}
    for s, a in agg.items():
        span = (a["end"] - a["start"]).total_seconds() if a["start"] and a["end"] else 0.0
        ranking.append({
            "slice": s, "cost_usd": round(a["cost"], 2), "tokens": a["tokens"],
            "turns": a["turns"], "raw_turns": a["raw_turns"], "convs": a["convs"],
            "managers": a["managers"], "subagents": a["subagents"],
            "wall_h": round(span / 3600, 2), "active_h": round(a["active_s"] / 3600, 2),
            "projects": dict(a["projects"]),
        })
        roles_json[s] = {r: {"cost": round(v["cost"], 2), "tokens": v["tokens"],
                             "turns": v["turns"], "n": v["n"]}
                         for r, v in sorted(a["roles"].items(),
                                            key=lambda kv: -kv[1]["cost"])}
    ranking.sort(key=lambda r: -r["cost_usd"])
    with (out / "slice_ranking.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["slice", "cost_usd", "tokens", "turns",
                                           "raw_turns", "convs", "managers", "subagents",
                                           "wall_h", "active_h", "projects"])
        w.writeheader()
        for r in ranking:
            r2 = dict(r); r2["projects"] = json.dumps(r["projects"])
            w.writerow(r2)
    (out / "slice_roles.json").write_text(json.dumps(roles_json, indent=2))

    # ---- stdout ---------------------------------------------------------
    if args.slice:
        s = "%03d" % int(re.sub(r"\D", "", args.slice))
        print(f"\n=== slice {s} — conversations (by cost) ===")
        rows = sorted([c for c in convs if c._slice == s],  # type: ignore[attr-defined]
                      key=lambda c: -c.cost())
        print(f"{'role':28} {'agent/session':40} {'turns':>6} {'tokens':>12} {'cost':>9} {'dur':>7}")
        for c in rows:
            ident = c.path.stem[:8] if c.kind == "manager" else c.path.name[:22]
            print(f"{c.role:28} {ident:40} {c.turns:>6} {c.total_tokens():>12,} "
                  f"${c.cost():>8,.2f} {c.duration_s()/60:>6.0f}m")
        print(json.dumps(roles_json.get(s, {}), indent=2))
        return 0

    print(f"# {len(convs)} conversations across {len({c.project for c in convs})} projects")
    dupf = sum(c.raw_turns for c in convs) / max(1, sum(c.turns for c in convs))
    print(f"# dedup: {sum(c.turns for c in convs):,} billed msgs from "
          f"{sum(c.raw_turns for c in convs):,} raw records ({dupf:.2f}x dup)\n")
    print(f"{'slice':7} {'cost':>10} {'tokens':>14} {'turns':>7} {'convs':>6} "
          f"{'mgr':>4} {'sub':>4} {'wall_h':>7} {'active_h':>9}  projects")
    for r in ranking:
        if r["cost_usd"] < args.min_cost:
            continue
        print(f"{r['slice']:7} ${r['cost_usd']:>9,.2f} {r['tokens']:>14,} "
              f"{r['turns']:>7,} {r['convs']:>6} {r['managers']:>4} {r['subagents']:>4} "
              f"{r['wall_h']:>7} {r['active_h']:>9}  {r['projects']}")
    print(f"\nwrote: sessions.csv, slice_ranking.csv, slice_roles.json -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
