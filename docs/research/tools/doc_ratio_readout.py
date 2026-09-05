#!/usr/bin/env python3
"""The doc phase as a share of the slice's round-1 code-writer spend (the #716 re-read).

`doc-phase-read-2026-09-04.md` measured the reworked doc phase in absolute dollars and as a
share of the whole slice, and both moved with slice size. This readout divides instead by the
work the doc phase documents: the sum of every phase's **round-1 code-writer session** (its
sub-agents included) — one first delivery per phase, no gate-fix or review-fix rounds, no
reviewer, no consult. A slice with two writer rounds of 100 k and 200 k tokens and a doc phase of
150 k reads 50 %. Both eras are priced by the same `slice_cost.py`, so the ratio is free of slice
size and of the writer's own drift only to the extent the denominator column beside it says.

Groups (KubeCoderSpecs only; AnsibleSpecs is not cloned here):
  corpus   144–170 — the 26 single-stage doc phases the 09-04 read compared against
  late     171–196 — single-stage doc phases on 0.9.7–0.9.13 (the T3/T4 writer, the digest)
  new      0.9.20+ — the two-stage doc phase (coordinator + surveys + units)

Columns per slice: phases (state.json's `phases`, appended ones counted), the base in $ and
tokens, the doc phase in $ and tokens, the doc phase's surviving round only (a round the engine
race killed is `dead`), and the ratios. `--first-delivery` widens the base to a round ≥2 that
resumes its own role's question/blocked round (slice_cost's `continuation`).

Usage:
    doc_ratio_readout.py [--first-delivery] [--json]
"""

import argparse
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "plugins" / "dev" / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load("slice_cost")

KCS = Path("/work/KubeCoderSpecs/slices/completed")
GROUPS = {
    "corpus": re.compile(r"1(4[4-9]|5\d|6\d|70)_"),
    "late": re.compile(r"1(7[1-9]|8\d|9[0-6])_"),
}


def _state(d: Path) -> dict:
    try:
        return json.loads((d / "state.json").read_text())
    except OSError:
        return {}


def _group(d: Path, state: dict) -> str | None:
    for name, rx in GROUPS.items():
        if rx.match(d.name):
            return name
    v = state.get("plugin_version") or ""
    parts = tuple(int(x) for x in v.split(".")) if v else ()
    return "new" if parts >= (0, 9, 20) else None


def _dispatcher(c) -> object:
    """The recorded session a Conv bills to: itself, or its parent for a sub-agent."""
    return c.parent if c.kind == "subagent" else c


def slice_row(d: Path, first_delivery: bool) -> dict | None:
    state = _state(d)
    if not state or not any(e.get("role") == "doc-writer" for e in state.get("history", [])):
        return None
    convs, warnings = sc.collect(d)
    base_cost = base_tok = 0.0
    doc_cost = doc_tok = 0.0
    doc_live_cost = doc_live_tok = 0.0
    doc_rounds: list[tuple[object, bool]] = []
    # The surviving doc round = the last doc-writer session in history order (the one the
    # doc-gate followed); every earlier one is a round the engine race killed and the driver
    # re-dispatched. Outcome is no guide: 202's only round is recorded `blocked` and landed.
    doc_sessions = [c for c in convs if c.kind == "session" and c.role == "doc-writer"]
    order = [e.get("session") for e in state.get("history", [])
             if e.get("role") == "doc-writer" and e.get("session")]
    live = {order[-1]} if order else set()
    for c in convs:
        disp = _dispatcher(c)
        if disp.loop != "run" or disp.kind != "session":
            continue
        if disp.role == "code-writer" and (
                disp.round == 1 or (first_delivery and disp.continuation)):
            base_cost += c.cost()
            base_tok += c.total_tokens()
        elif disp.role == "doc-writer":
            doc_cost += c.cost()
            doc_tok += c.total_tokens()
            if disp.session in live:
                doc_live_cost += c.cost()
                doc_live_tok += c.total_tokens()
    for c in doc_sessions:
        doc_rounds.append((c, c.session in live))
    nph = len(state.get("phases", {}))
    return {
        "slice": d.name, "group": _group(d, state),
        "version": state.get("plugin_version") or "<0.9.6",
        "nph": nph, "appended": len(state.get("appended_phases") or []),
        "base_cost": base_cost, "base_tok": base_tok,
        "doc_cost": doc_cost, "doc_tok": doc_tok,
        "doc_live_cost": doc_live_cost, "doc_live_tok": doc_live_tok,
        "dead_rounds": sum(1 for _, ok in doc_rounds if not ok),
        "ratio_cost": doc_cost / base_cost if base_cost else None,
        "ratio_tok": doc_tok / base_tok if base_tok else None,
        "ratio_live_cost": doc_live_cost / base_cost if base_cost else None,
        "ratio_live_tok": doc_live_tok / base_tok if base_tok else None,
        "warnings": warnings,
    }


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:5.0f} %"


def _k(x) -> str:
    return f"{x / 1000:7.0f} k"


def print_rows(rows: list[dict]) -> None:
    hdr = (f"{'slice':<44} {'ver':<7} {'ph':>3} {'base $':>7} {'base tok':>9} {'/ph $':>6} "
           f"{'doc $':>7} {'doc tok':>9} {'/ph $':>6} {'dead':>4} "
           f"{'$ %':>6} {'tok %':>6} {'live $ %':>8} {'live tok %':>10}")
    for group in ("corpus", "late", "new"):
        rs = [r for r in rows if r["group"] == group]
        if not rs:
            continue
        print(f"\n== {group} ({len(rs)} slices)")
        print(hdr)
        for r in rs:
            ph = r["nph"] or 1
            print(f"{r['slice']:<44} {r['version']:<7} {r['nph']:>3} {r['base_cost']:>7.2f} "
                  f"{_k(r['base_tok']):>9} {r['base_cost'] / ph:>6.2f} {r['doc_cost']:>7.2f} "
                  f"{_k(r['doc_tok']):>9} {r['doc_cost'] / ph:>6.2f} {r['dead_rounds']:>4} "
                  f"{_pct(r['ratio_cost']):>6} {_pct(r['ratio_tok']):>6} "
                  f"{_pct(r['ratio_live_cost']):>8} {_pct(r['ratio_live_tok']):>10}")
        for w in (w for r in rs for w in r["warnings"]):
            print(f"   ! {w}")


def print_summary(rows: list[dict]) -> None:
    print("\n== medians")
    print(f"{'group':<22} {'n':>3} {'ph':>4} {'base $/ph':>9} {'doc $/ph':>8} "
          f"{'$ %':>6} {'tok %':>6} {'live $ %':>8} {'live tok %':>10} {'quartiles $ %':>22}")

    def agg(label: str, rs: list[dict]) -> None:
        if not rs:
            return
        q = sorted(r["ratio_cost"] for r in rs if r["ratio_cost"] is not None)
        if len(q) >= 4:
            qs = statistics.quantiles(q, n=4)
            quart = f"{qs[0] * 100:.0f} / {qs[1] * 100:.0f} / {qs[2] * 100:.0f}"
        else:
            quart = " ".join(f"{x * 100:.0f}" for x in q)
        print(f"{label:<22} {len(rs):>3} {_med([r['nph'] for r in rs]):>4.0f} "
              f"{_med([r['base_cost'] / (r['nph'] or 1) for r in rs]):>9.2f} "
              f"{_med([r['doc_cost'] / (r['nph'] or 1) for r in rs]):>8.2f} "
              f"{_pct(_med([r['ratio_cost'] for r in rs])):>6} "
              f"{_pct(_med([r['ratio_tok'] for r in rs])):>6} "
              f"{_pct(_med([r['ratio_live_cost'] for r in rs])):>8} "
              f"{_pct(_med([r['ratio_live_tok'] for r in rs])):>10} {quart:>22}")

    for group in ("corpus", "late", "new"):
        rs = [r for r in rows if r["group"] == group]
        agg(group, rs)
        agg(f"  {group} 2-4 ph", [r for r in rs if 2 <= r["nph"] <= 4])
        agg(f"  {group} 5+ ph", [r for r in rs if r["nph"] >= 5])
    before = [r for r in rows if r["group"] in ("corpus", "late")]
    agg("before (both)", before)
    # Pooled: the ratio of sums, so big slices weigh what they cost.
    print("\n== pooled (sum doc / sum base)")
    for group in ("corpus", "late", "new"):
        rs = [r for r in rows if r["group"] == group]
        if not rs:
            continue
        b = sum(r["base_cost"] for r in rs)
        print(f"{group:<10} $ {sum(r['doc_cost'] for r in rs) / b * 100:5.0f} %   "
              f"live $ {sum(r['doc_live_cost'] for r in rs) / b * 100:5.0f} %   "
              f"tok {sum(r['doc_tok'] for r in rs) / sum(r['base_tok'] for r in rs) * 100:5.0f} %")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--first-delivery", action="store_true",
                    help="count a continuation round (question/blocked resumed) in the base")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rows = []
    for d in sorted(KCS.iterdir()):
        if not d.is_dir():
            continue
        state = _state(d)
        if _group(d, state) is None:
            continue
        r = slice_row(d, args.first_delivery)
        if r:
            rows.append(r)
    if args.json:
        json.dump(rows, sys.stdout, indent=1)
        return 0
    print_rows(rows)
    print_summary(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
