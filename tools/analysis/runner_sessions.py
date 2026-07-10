#!/usr/bin/env python3
"""Per-session inventory + token accounting for one task-runner slice.

Reads a slice folder's `state.json` (the runner's execution record) and prints
one row per agent session: task, role, round, outcome, session id, transcript
path, and — with --tokens — deduplicated token usage and sticker-price cost.

This is the drill-down companion to `slice_costs.py` (fleet-wide ranking):
point it at ONE slice when researching what its agents actually did. The
transcript path is what you hand to a sub-agent for a deep read; a session's
own sub-agents sit next to its transcript under `<session-id>/subagents/`.

Transcript resolution: newer runs record the path in each history entry
(`transcript`); for older runs the session id is globbed across
`~/.claude/projects/*/`.

Accounting detail (same as slice_costs.py): the stream-json transcript logs
one line per content block, repeating the SAME `message.id` + usage payload —
naive summation overcounts ~2-3x. We keep one usage record per message.id.

Usage:
  python3 runner_sessions.py <slice-dir>              # inventory only
  python3 runner_sessions.py <slice-dir> --tokens     # + tokens and cost
  python3 runner_sessions.py <slice-dir> --json       # machine-readable
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

# USD per 1,000,000 tokens (public sticker prices); cache multipliers per the
# published pricing model (write = 1.25x input for the 5m TTL, read = 0.10x).
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-fable-5": {"input": 10.0, "output": 50.0},
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def resolve_transcript(entry: dict) -> Path | None:
    """The transcript path recorded by the runner, or a glob fallback for
    state.json written before the runner recorded paths."""
    recorded = entry.get("transcript")
    if recorded and Path(recorded).exists():
        return Path(recorded)
    sid = entry.get("session")
    if not sid:
        return None
    hits = glob.glob(str(PROJECTS_DIR / "*" / f"{sid}.jsonl"))
    return Path(hits[0]) if hits else None


def usage_of(transcript: Path) -> dict:
    """Deduplicated usage sums for a transcript file plus its subagents dir.
    Returns {main: {...}, sidechain: {...}, model: str|None}."""
    buckets = {"main": defaultdict(int), "sidechain": defaultdict(int)}
    model: str | None = None

    def add(path: Path, bucket: str) -> None:
        nonlocal model
        seen: set[str] = set()
        try:
            with open(path) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message") or {}
                    usage = msg.get("usage")
                    mid = msg.get("id")
                    if not usage or not mid or mid in seen:
                        continue
                    seen.add(mid)
                    model = model or msg.get("model")
                    b = buckets[bucket]
                    b["input"] += usage.get("input_tokens", 0)
                    b["output"] += usage.get("output_tokens", 0)
                    b["cache_write"] += usage.get(
                        "cache_creation_input_tokens", 0)
                    b["cache_read"] += usage.get("cache_read_input_tokens", 0)
        except OSError:
            pass

    add(transcript, "main")
    for sub in sorted(transcript.parent.glob(
            f"{transcript.stem}/subagents/agent-*.jsonl")):
        add(sub, "sidechain")
    return {"main": dict(buckets["main"]),
            "sidechain": dict(buckets["sidechain"]), "model": model}


def cost_usd(usage: dict, model: str | None) -> float | None:
    price = PRICES.get(model or "")
    if not price:
        return None
    return (usage.get("input", 0) * price["input"]
            + usage.get("output", 0) * price["output"]
            + usage.get("cache_write", 0) * price["input"] * CACHE_WRITE_MULT
            + usage.get("cache_read", 0) * price["input"] * CACHE_READ_MULT
            ) / 1_000_000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slice_dir", help="path to slices/NNN_slug/")
    ap.add_argument("--tokens", action="store_true",
                    help="also sum token usage + cost per session (reads "
                         "every transcript — slower)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit JSON instead of a table")
    args = ap.parse_args()

    state_path = Path(args.slice_dir) / "state.json"
    state = None
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        sys.exit(f"error: cannot read {state_path}")

    rows = []
    totals: defaultdict[str, int] = defaultdict(int)
    total_cost = 0.0
    counted: set[str] = set()  # a resumed session spans several history rows —
    #                            count its transcript once, on first appearance
    for h in state.get("history", []):
        transcript = resolve_transcript(h)
        row = {
            "ts": h.get("ts", ""), "task": h.get("task") or "-",
            "role": h.get("role", "?"), "round": h.get("round", 0),
            "outcome": h.get("outcome", "?"), "session": h.get("session"),
            "transcript": str(transcript) if transcript else None,
            "duration_s": h.get("duration_s", 0),
        }
        if args.tokens and transcript and str(transcript) in counted:
            row["tokens"] = "counted-at-first-row"
        elif args.tokens and transcript:
            counted.add(str(transcript))
            u = usage_of(transcript)
            combined = defaultdict(int)
            for bucket in ("main", "sidechain"):
                for k, v in u[bucket].items():
                    combined[k] += v
                    totals[k] += v
            row["model"] = u["model"]
            row["tokens"] = dict(combined)
            c = cost_usd(combined, u["model"])
            row["cost_usd"] = round(c, 2) if c is not None else None
            total_cost += c or 0.0
        rows.append(row)

    if args.as_json:
        print(json.dumps({"slice": state.get("slice"), "sessions": rows},
                         indent=2))
        return

    print(f"slice {state.get('slice')} — {len(rows)} agent session(s)")
    for r in rows:
        line = (f"  {r['task']:<34} {r['role']:<13} r{r['round']} "
                f"→ {r['outcome']:<15} {r['duration_s']:>5}s")
        if args.tokens and r.get("tokens") == "counted-at-first-row":
            line += "  (resumed session — usage counted at its first row)"
        elif args.tokens and r.get("tokens") is not None:
            t = r["tokens"]
            cost = f"${r['cost_usd']:.2f}" if r.get("cost_usd") else "?"
            line += (f"  out={t.get('output', 0):>7,} "
                     f"cw={t.get('cache_write', 0):>9,} "
                     f"cr={t.get('cache_read', 0):>11,} {cost:>7}")
        print(line)
        print(f"    {r['transcript'] or '(transcript not found)'}")
    if args.tokens:
        print(f"\ntotal: out={totals['output']:,} "
              f"cache_write={totals['cache_write']:,} "
              f"cache_read={totals['cache_read']:,} input={totals['input']:,} "
              f"≈ ${total_cost:.2f} (sticker, per-model)")


if __name__ == "__main__":
    main()
