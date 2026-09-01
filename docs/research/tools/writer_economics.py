#!/usr/bin/env python3
"""The writer-economics views behind readout-2026-09-01.md — the T4 judgement.

Three views over the same replay t4_readout.py uses (the plugin's turn_profile.py, so the
figures are the ones state.json carries), each against the 32-slice corpus of
context-profile-2026-08-23.md:

  bands   r1 code-writer sessions by plan size (2–4, 5–8, 9+ phases) and group — turns, $,
          orientation, ctx at the first edit, thinking and output per session, $/turn
  eras    the writer's dollar split by token class (output / cache read / cache write / input)
          and its edit turns — output per edit turn, shell-edit command length, Edit-tool vs
          shell edits — by Claude Code era (≤ 2.1.233 Edit-tool era, ≥ 2.1.234, new)
  subs    sub-agent $ per slice by the role that dispatched it and the sub-agent's type

Research tooling, not plugin. Usage:

  python3 docs/research/tools/writer_economics.py all
  python3 docs/research/tools/writer_economics.py bands --new <slice dirs>

`--new` defaults to the fifteen slices of the 2026-09-01 readout (180–193 and Ansible 016);
181 is its own group everywhere (the $294 desktop-extension slice the operator flagged).
"""
from __future__ import annotations

import argparse
import importlib.util
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("t4_readout", HERE / "t4_readout.py")
t4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t4)
sc, tp = t4.sc, t4.tp

KCS, ANS = t4.KCS, t4.ANS
DEFAULT_NEW = sorted(KCS.glob("18*")) + sorted(KCS.glob("19*")) + sorted(ANS.glob("016_*"))
RATES = {"input": 5.0, "out": 25.0, "cw": 6.25, "cr": 0.5}  # $/M, Opus 5 (slice_cost.PRICES)
GROUPS = ("corpus", "0.9.8", "181", "0.9.12+")


def group_of(d: Path, corpus: bool) -> str:
    if corpus:
        return "corpus"
    if d.name.startswith("181"):
        return "181"
    v = t4._state(d).get("plugin_version") or ""
    return "0.9.8" if v == "0.9.8" else "0.9.12+"


def band_of(nph: int) -> str:
    return "2-4" if nph <= 4 else ("5-8" if nph <= 8 else "9+")


def era_of(d: Path, corpus: bool, version: str) -> str:
    if corpus:
        return "corpus<=233" if version <= "2.1.233" else "corpus>=234"
    return "181" if d.name.startswith("181") else "new"


def quart(xs: list[float]) -> str:
    xs = sorted(xs)
    if not xs:
        return "-"
    n = len(xs)

    def p(f: float) -> float:
        return xs[min(n - 1, int(f * (n - 1)))]

    return (f"n={n:3d} med={p(.5):7.2f} p75={p(.75):7.2f} p90={p(.9):7.2f} "
            f"mean={st.mean(xs):7.2f}")


def writer_sessions(new: list[Path]):
    """Every r1 code-writer session with its replay analysis, tagged by group/band/era."""
    for corpus, dirs in ((True, t4.corpus_dirs()), (False, new)):
        for d in dirs:
            try:
                convs, _ = sc.collect(d)
            except FileNotFoundError:
                continue
            nph = len(t4._state(d).get("phases", {}))
            for c in convs:
                if c.role != "code-writer" or c.round != 1:
                    continue
                rep = tp.replay(c.transcript)
                an = tp.analyse(rep, sc.cost_for)
                if not an:
                    continue
                yield {
                    "group": group_of(d, corpus), "band": band_of(nph),
                    "era": era_of(d, corpus, t4._version(c.transcript)),
                    "turns": rep["turns"], "an": an,
                }


# --------------------------------------------------------------------------- bands

def print_bands(new: list[Path]) -> None:
    rows = list(writer_sessions(new))
    print("== r1 code-writer sessions by plan size and group (per-session quartiles)")
    for band in ("2-4", "5-8", "9+"):
        for g in GROUPS:
            rs = [r for r in rows if r["band"] == band and r["group"] == g]
            if not rs:
                continue
            m = [r["an"]["metrics"] for r in rs]
            fe = [tp.first_edit_turn(r["turns"]) for r in rs]
            ctx_fe = [r["turns"][f - 1]["ctx"] / 1000
                      for r, f in zip(rs, fe, strict=True) if f]
            tot = sum(x["cost"] for x in m)
            turns = sum(x["turns"] for x in m)
            print(f"{band:4s} {g:8s} turns  {quart([x['turns'] for x in m])}")
            print(f"{'':13s} $      {quart([x['cost'] for x in m])}")
            orient = [(f - 1) if f else x["turns"] for f, x in zip(fe, m, strict=True)]
            think = [x["tok"]["thinking"] / 1000 for x in m]
            print(f"{'':13s} orient {quart(orient)}")
            print(f"{'':13s} ctx_fe {quart(ctx_fe)} (k)")
            print(f"{'':13s} think  {quart(think)} (k/session)")
            print(f"{'':13s} $/turn {tot / turns:.4f}  think/turn "
                  f"{sum(x['tok']['thinking'] for x in m) / turns:.0f}  out/turn "
                  f"{sum(x['tok']['output'] for x in m) / turns:.0f}")


# --------------------------------------------------------------------------- eras

def print_eras(new: list[Path]) -> None:
    agg: dict[str, Counter] = defaultdict(Counter)
    for r in writer_sessions(new):
        a = agg[r["era"]]
        cls = {c["i"]: c["cls"] for c in r["an"]["classes"]}
        a["n"] += 1
        for t in r["turns"]:
            a["turns"] += 1
            for k in RATES:
                a[k] += t.get(k, 0)
            a["think"] += t.get("think", 0)
            if cls.get(t["i"]) != "edit":
                continue
            a["edit_turns"] += 1
            a["edit_out"] += t.get("out", 0)
            for rec in t["tools"]:
                if rec["name"] == "Bash":
                    a["edit_bash"] += 1
                    a["edit_cmd_chars"] += len(rec.get("cmd") or "")
                elif rec["name"] in tp.WRITE_TOOLS:
                    a["edit_tool"] += 1
    print("== r1 code-writer $ by token class and edit turns, by Claude Code era")
    for era in ("corpus<=233", "corpus>=234", "new", "181"):
        a = agg[era]
        if not a["turns"]:
            continue
        dollars = {k: a[k] / 1e6 * RATES[k] for k in RATES}
        tot = sum(dollars.values())
        share = " ".join(f"{k}={dollars[k] / tot:.0%}" for k in ("out", "cr", "cw", "input"))
        print(f"{era:12s} n={a['n']:3d} turns={a['turns']:5d} $/turn={tot / a['turns']:.4f} | "
              f"$ share {share} | out/turn={a['out'] / a['turns']:.0f} "
              f"think/turn={a['think'] / a['turns']:.0f} | edit turns={a['edit_turns']} "
              f"out/edit-turn={a['edit_out'] / max(a['edit_turns'], 1):.0f} "
              f"shell-edit cmd chars={a['edit_cmd_chars'] / max(a['edit_bash'], 1):.0f} "
              f"(shell {a['edit_bash']}, Edit/Write tool {a['edit_tool']})")


# --------------------------------------------------------------------------- subs

def print_subs(new: list[Path]) -> None:
    agg: dict[str, Counter] = defaultdict(Counter)
    nsl: Counter = Counter()
    for corpus, dirs in ((True, t4.corpus_dirs()), (False, new)):
        for d in dirs:
            try:
                convs, _ = sc.collect(d)
            except FileNotFoundError:
                continue
            g = group_of(d, corpus)
            nsl[g] += 1
            for c in convs:
                if c.role.startswith("subagent") and c.parent is not None:
                    agg[g][(c.parent.role, c.role.split(":", 1)[1])] += c.cost()
    print("== sub-agent $ per slice by dispatching role -> sub-agent type")
    for g in GROUPS:
        if not nsl[g]:
            continue
        print(f"-- {g}: slices={nsl[g]} sub-agent $/slice={sum(agg[g].values()) / nsl[g]:.2f}")
        for (role, kind), v in sorted(agg[g].items(), key=lambda kv: -kv[1])[:8]:
            print(f"   {role:22s} -> {kind:18s} ${v / nsl[g]:5.2f}/slice")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("view", choices=("bands", "eras", "subs", "all"))
    ap.add_argument("--new", nargs="*", type=Path, default=DEFAULT_NEW,
                    help="slice dirs run on the new plugin versions")
    args = ap.parse_args(argv)
    new = [d for d in args.new if (d / "state.json").is_file()]
    print("new slices:", " ".join(d.name for d in new))
    if args.view in ("bands", "all"):
        print_bands(new)
    if args.view in ("eras", "all"):
        print()
        print_eras(new)
    if args.view in ("subs", "all"):
        print()
        print_subs(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
