#!/usr/bin/env python3
"""Doc-writer sessions: where the dollars sit by stage, and what a k-unit split would cost.

Model (context_profile.what_if_cut generalised to k cuts): the session's turns after the first
edit are split into k contiguous chunks; each chunk runs in a fresh context whose prefix is
`unit_prefix` (a sub-agent's first-turn context) + a hand-off of `handoff` tokens + `reorient`
tokens of re-read files, written once and then dragged, and adds exactly what the original added
over those turns (same growth). The coordinator keeps the orientation turns as they were and
pays one result turn per unit at its end-of-orientation context plus the k briefs as output.
Ignores quality, prefix breaks, and any reads a unit needs beyond `reorient`.

Research tooling, not plugin (doc-phase-plan.md § 2). Usage:

  python3 docs/research/tools/doc_split_whatif.py            # the table + pooled savings
  python3 docs/research/tools/doc_split_whatif.py --grid     # sensitivity to the unit's fixed cost
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "plugins" / "dev" / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load("turn_profile")
sc = _load("slice_cost")

KCS = Path("/work/KubeCoderSpecs/slices/completed")
PROJ = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", "/work/KubeCoder")
NEW = re.compile(r"^(17[345]|179|18[2456])")
CORPUS = re.compile(r"^1(4[4-9]|5\d|6\d|70)_")
KS = (2, 3, 4, 6, 8, 12)


def cost(t: dict, ctx: int | None = None) -> float:
    cr = t["cr"] if ctx is None else ctx
    return sc.cost_for(t["model"], {"cache_read": cr, "cache_write": t["cw"],
                                    "input": t["input"], "output": t["out"]})


def session(d: Path) -> tuple[list[dict], int] | None:
    s = json.loads((d / "state.json").read_text())
    sid = (s.get("doc_phase") or {}).get("session")
    p = PROJ / f"{sid}.jsonl" if sid else None
    if not p or not p.exists():
        return None
    turns = tp.replay(p)["turns"]
    fe = tp.first_edit_turn(turns) if turns else None
    return (turns, fe) if fe else None


def split_cost(turns: list[dict], fe: int, k: int, unit_prefix: int = 21_000,
               handoff: int = 3_000, reorient: int = 30_000) -> float:
    model = turns[0]["model"]
    base_in, base_out = sc.PRICES[model]["input"], sc.PRICES[model]["output"]
    pre, post = turns[:fe], turns[fe:]
    coord = sum(cost(t) for t in pre)
    ctx_end = pre[-1]["ctx"] if pre else turns[0]["ctx"]
    coord += k * sc.cost_for(model, {"cache_read": ctx_end, "cache_write": 2_000, "output": 300})
    coord += k * handoff / 1e6 * base_out
    fresh = unit_prefix + handoff + reorient
    units = 0.0
    n = len(post)
    bounds = [round(i * n / k) for i in range(k + 1)]
    for u in range(k):
        chunk = post[bounds[u]:bounds[u + 1]]
        if not chunk:
            continue
        c0 = chunk[0]["ctx"]
        units += fresh / 1e6 * base_in * sc.CACHE_WRITE_MULT
        units += sum(cost(t, fresh + t["ctx"] - c0) for t in chunk)
    return coord + units


def collect() -> list[dict]:
    rows = []
    for d in sorted(KCS.iterdir()):
        if not (NEW.match(d.name) or CORPUS.match(d.name)):
            continue
        r = session(d)
        if not r:
            continue
        turns, fe = r
        rows.append({
            "slice": d.name[:26], "group": "new" if NEW.match(d.name) else "corpus",
            "turns": turns, "fe": fe, "ctx_fe": turns[fe]["ctx"],
            "ctx_max": max(t["ctx"] for t in turns),
            "total": sum(cost(t) for t in turns), "pre": sum(cost(t) for t in turns[:fe]),
        })
    return rows


def table(rows: list[dict]) -> None:
    print(f"{'slice':26} {'grp':6} {'turns':>5} {'fe':>3} {'ctx_fe':>7} {'ctx_max':>7} "
          f"{'$tot':>6} {'$pre':>6} {'pre%':>5} " + " ".join(f"{'k' + str(k):>6}" for k in KS))
    for r in rows:
        splits = " ".join(
            f"{(split_cost(r['turns'], r['fe'], k) / r['total'] - 1) * 100:+5.0f}%" for k in KS)
        print(f"{r['slice']:26} {r['group']:6} {len(r['turns']):5} {r['fe']:3} {r['ctx_fe']:7} "
              f"{r['ctx_max']:7} {r['total']:6.2f} {r['pre']:6.2f} "
              f"{r['pre'] / r['total'] * 100:4.0f}% {splits}")
    for g in ("new", "corpus"):
        rs = [r for r in rows if r["group"] == g]
        if not rs:
            continue
        tot, pre = sum(r["total"] for r in rs), sum(r["pre"] for r in rs)
        pooled = " ".join(
            f"k{k}={(sum(split_cost(r['turns'], r['fe'], k) for r in rs) / tot - 1) * 100:+.0f}%"
            for k in KS)
        print(f"-- {g}: n={len(rs)} $={tot:.2f} pre-edit share={pre / tot * 100:.0f}% {pooled}")


def _pooled(rs: list[dict], k: int, up: int, ho: int, ro: int) -> float:
    return sum(split_cost(r["turns"], r["fe"], k, up, ho, ro) for r in rs)


def grid(rows: list[dict]) -> None:
    print("saving vs actual, pooled, by (unit prefix, hand-off, re-reads):")
    for g in ("new", "corpus"):
        rs = [r for r in rows if r["group"] == g]
        tot = sum(r["total"] for r in rs)
        for up, ho, ro in ((21_000, 3_000, 30_000), (21_000, 2_000, 15_000),
                           (12_000, 2_000, 15_000), (21_000, 3_000, 50_000)):
            line = " ".join(
                f"k{k}={(_pooled(rs, k, up, ho, ro) / tot - 1) * 100:+.0f}%" for k in KS)
            print(f"  {g:6} {up // 1000}k/{ho // 1000}k/{ro // 1000}k: {line}")
    print("fixed cost per Opus unit (written once + dragged per turn):")
    for up, ho, ro in ((21_000, 3_000, 30_000), (21_000, 2_000, 15_000), (12_000, 2_000, 15_000)):
        fresh = up + ho + ro
        write, drag = fresh / 1e6 * 5 * sc.CACHE_WRITE_MULT, fresh / 1e6 * 5 * sc.CACHE_READ_MULT
        print(f"  {up // 1000}k/{ho // 1000}k/{ro // 1000}k: ${write:.2f} + ${drag:.3f}/turn "
              f"-> 10-turn unit ≈ ${write + 10 * drag:.2f}")


if __name__ == "__main__":
    rows = collect()
    table(rows)
    if "--grid" in sys.argv:
        print()
        grid(rows)
