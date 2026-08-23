#!/usr/bin/env python3
"""The T3/T4 readout — new slices against the 32-slice corpus (turns-plan.md § T4 Read).

Three views over the same replay (the plugin's turn_profile.py, imported the way
context_profile.py imports it, so the numbers are the ones state.json carries):

  writers     per writer session: orientation turns before the first edit, plan.md /
              verification.json / slice.md reads (whole session and before the first
              edit), ctx at the first edit, first-prompt size, turn classes — medians
              per group and quartiles, one line per new session, one line per corpus slice
  slices      per slice: $ and turns per phase, writer / reviewer $ per phase, the quality
              instruments (r1 blocking phases, refuted, gate-fix, gate-red, rework share,
              abstention hits, appended phases), pooled per group
  plan-reads  every plan.md touch in the new writer sessions (turn, tool, before/after the
              first edit), Edit/Read tool vs shell-edit counts, the Claude Code version

Research tooling, not plugin. Usage:

  python3 docs/research/tools/t4_readout.py all
  python3 docs/research/tools/t4_readout.py writers --role code-reviewer
  python3 docs/research/tools/t4_readout.py slices --new /work/KubeCoderSpecs/slices/completed/18*

`--new` defaults to the four 2026-08-23 slices (179 on 0.9.7, 173/174/175 on 0.9.8); the corpus
is the 32 slices of context-profile-2026-08-23.md. First run 2026-08-23, recorded in
t4-read-2026-08-23.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics as st
from collections import Counter, defaultdict
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
ANS = Path("/work/AnsibleSpecs/slices/completed")
CORPUS_RE = {KCS: re.compile(r"1(4[4-9]|5\d|6\d|70)_"), ANS: re.compile(r"0(06|07|08|09|13|15)_")}
DEFAULT_NEW = [
    KCS / "179_headless_claude_flags",
    KCS / "174_vscode_extension_surface",
    KCS / "175_worker_test_suite_reliability",
    KCS / "173_surface_2_delivery_and_coverage",
]
PLAN_RE = re.compile(r"plan\.md")
VER_RE = re.compile(r"verification\.json")
SLICE_RE = re.compile(r"slice\.md")
REVIEW_RE = re.compile(r"code_review_r\d+\.md")
READ_PROG_RE = re.compile(r"\b(cat|sed|head|tail|grep|rg|less)\b")
ABST_RE = re.compile(
    r"cannot determine|unable to verify|could not verify|cannot verify|not able to verify|"
    r"unable to determine|could not determine|did not attempt|not attempted", re.I)


def corpus_dirs() -> list[Path]:
    out: list[Path] = []
    for root, rx in CORPUS_RE.items():
        if root.is_dir():
            out += [p for p in sorted(root.iterdir()) if rx.match(p.name)]
    return out


def _state(d: Path) -> dict:
    try:
        return json.loads((d / "state.json").read_text())
    except OSError:
        return {}


def _group(d: Path) -> str:
    v = _state(d).get("plugin_version")
    return f"new-{v}" if v else "new"


def _first_prompt_chars(path: Path) -> int:
    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "user":
                continue
            c = (o.get("message") or {}).get("content")
            if isinstance(c, str):
                return len(c)
            for blk in c or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    return len(blk.get("text", ""))
    return 0


def _version(path: Path) -> str:
    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("version"):
                return o["version"]
    return "?"


def _reads_of(turns: list[dict], rx: re.Pattern, upto: int | None = None) -> int:
    n = 0
    for t in turns:
        if upto is not None and t["i"] >= upto:
            break
        for rec in t["tools"]:
            if rec["name"] in ("Read", "Grep") and rx.search(rec["key"]):
                n += 1
            elif rec["name"] == "Bash":
                cmd = rec.get("cmd") or ""
                if rx.search(cmd) and READ_PROG_RE.search(cmd):
                    n += 1
    return n


def _med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def _quart(xs) -> str:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "-"
    n = len(xs)

    def p(f):
        return xs[min(n - 1, int(f * (n - 1)))]

    return (f"min={xs[0]} p25={p(.25)} med={p(.5)} p75={p(.75)} p90={p(.9)} max={xs[-1]} "
            f"mean={st.mean(xs):.1f}")


# --------------------------------------------------------------------------- writers

def session_row(conv, slice_name: str, group: str) -> dict | None:
    rep = tp.replay(conv.transcript)
    an = tp.analyse(rep, sc.cost_for)
    if not an:
        return None
    turns = rep["turns"]
    m = an["metrics"]
    fw = tp.first_write_turn(turns)
    fe = tp.first_edit_turn(turns)
    cls = Counter(r["cls"] for r in an["classes"])
    return {
        "group": group, "slice": slice_name, "phase": conv.phase, "round": conv.round,
        "turns": m["turns"], "cost": m["cost"],
        "ctx1": m["ctx_first"], "ctx_fe": turns[fe - 1]["ctx"] if fe else None,
        "ctx_mean": m["ctx_mean"], "ctx_max": m["ctx_max"],
        "orient_w": (fw - 1) if fw else m["turns"],
        "orient_e": (fe - 1) if fe else m["turns"],
        "plan_reads": _reads_of(turns, PLAN_RE),
        "plan_reads_pre": _reads_of(turns, PLAN_RE, fe),
        "ver_reads": _reads_of(turns, VER_RE),
        "slice_reads": _reads_of(turns, SLICE_RE),
        "review_reads": _reads_of(turns, REVIEW_RE),
        "tools_pt": m["tools_per_turn"], "reads_pt": m["reads_per_turn"],
        "rf": cls["retry"] + cls["fumble"], "batch_strict": m.get("batchable_strict", 0),
        "orient_read": cls["orient-read"], "work_read": cls["work-read"], "edit": cls["edit"],
        "gate": cls["gate"], "think": cls["think"],
        "prompt_chars": _first_prompt_chars(conv.transcript),
        "out_tok": m["tok"]["output"], "think_tok": m["tok"]["thinking"],
    }


def collect_rows(role: str, new: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for group_dirs in (("corpus", corpus_dirs()), (None, new)):
        group, dirs = group_dirs
        for d in dirs:
            try:
                convs, _ = sc.collect(d)
            except FileNotFoundError:
                continue
            nph = len(_state(d).get("phases", {}))
            for c in convs:
                if c.role != role:
                    continue
                r = session_row(c, d.name, group or _group(d))
                if r:
                    r["nphases"] = nph
                    rows.append(r)
    return rows


def print_writers(role: str, new: list[Path]) -> None:
    rows = collect_rows(role, new)
    keys = ["turns", "cost", "ctx1", "ctx_fe", "ctx_mean", "orient_w", "orient_e", "plan_reads",
            "plan_reads_pre", "ver_reads", "slice_reads", "tools_pt", "reads_pt", "rf",
            "batch_strict", "orient_read", "work_read", "edit", "think", "prompt_chars"]

    def agg(label: str, rs: list[dict]) -> None:
        if not rs:
            return
        parts = []
        for k in keys:
            v = _med([r[k] for r in rs])
            parts.append(f"{k}={v:.1f}" if isinstance(v, float) else f"{k}={v}")
        print(f"{label:26s} n={len(rs):3d} " + " ".join(parts))
        z = sum(1 for r in rs if r["plan_reads"] == 0)
        zp = sum(1 for r in rs if r["plan_reads_pre"] == 0)
        print(f"{'':26s}   plan_reads==0: {z}/{len(rs)}  pre-edit==0: {zp}/{len(rs)}  "
              f"sum$={sum(r['cost'] for r in rs):.2f} sum turns={sum(r['turns'] for r in rs)}  "
              f"mean turns={st.mean([r['turns'] for r in rs]):.1f} "
              f"mean $={st.mean([r['cost'] for r in rs]):.2f} "
              f"$/turn={sum(r['cost'] for r in rs) / sum(r['turns'] for r in rs):.4f}")

    corpus = [r for r in rows if r["group"] == "corpus"]
    news = [r for r in rows if r["group"] != "corpus"]
    band = [r for r in corpus if r["nphases"] and 2 <= r["nphases"] <= 4]
    tail = [r for r in corpus if r["slice"][:2] == "16" or r["slice"][:3] == "170"]
    print(f"== role {role}: per-session medians")
    agg("corpus (all)", corpus)
    agg("corpus r1", [r for r in corpus if r["round"] == 1])
    agg("corpus 2-4 phases", band)
    agg("corpus 2-4ph r1", [r for r in band if r["round"] == 1])
    agg("corpus 5+ phases", [r for r in corpus if r["nphases"] and r["nphases"] >= 5])
    agg("corpus 16x-170 r1", [r for r in tail if r["round"] == 1])
    for g in sorted({r["group"] for r in news}):
        agg(g, [r for r in news if r["group"] == g])
        agg(f"{g} r1", [r for r in news if r["group"] == g and r["round"] == 1])
    agg("new all", news)

    print("\n== quartiles (r1 sessions)")
    for label, rs in (("corpus 2-4ph r1", [r for r in band if r["round"] == 1]),
                      ("corpus 16x-170 r1", [r for r in tail if r["round"] == 1]),
                      ("new r1", [r for r in news if r["round"] == 1])):
        print(f"-- {label} n={len(rs)}")
        for k in ("turns", "cost", "orient_e", "ctx_fe", "ctx_mean", "think_tok"):
            print(f"   {k:9s} {_quart([round(r[k], 2) if k == 'cost' else r[k] for r in rs])}")

    print("\n== new sessions, one line each")
    for r in news:
        print(f"{r['slice'][:22]:22s} P{r['phase']} r{r['round']} turns={r['turns']:3d} "
              f"${r['cost']:5.2f} ctx1={r['ctx1']:6d} ctx_fe={r['ctx_fe']} "
              f"orient_w={r['orient_w']:2d} orient_e={r['orient_e']:2d} "
              f"plan={r['plan_reads']} (pre {r['plan_reads_pre']}) ver={r['ver_reads']} "
              f"slice={r['slice_reads']} rev={r['review_reads']} "
              f"or={r['orient_read']} wr={r['work_read']} ed={r['edit']} th={r['think']} "
              f"rf={r['rf']} bs={r['batch_strict']} prompt={r['prompt_chars']}")

    print("\n== corpus by slice (median per session)")
    bys: dict[str, list[dict]] = defaultdict(list)
    for r in corpus:
        bys[r["slice"]].append(r)
    for s, rs in sorted(bys.items(), key=lambda kv: kv[1][0]["nphases"] or 0):
        print(f"{s[:40]:40s} ph={rs[0]['nphases']} n={len(rs):2d} "
              f"turns={_med([r['turns'] for r in rs]):.0f} "
              f"orient_e={_med([r['orient_e'] for r in rs]):.0f} "
              f"plan={_med([r['plan_reads'] for r in rs]):.0f} "
              f"ctx1={_med([r['ctx1'] for r in rs]):.0f} "
              f"ctx_fe={_med([r['ctx_fe'] for r in rs]) or 0:.0f} "
              f"$={_med([r['cost'] for r in rs]):.2f} sum$={sum(r['cost'] for r in rs):.2f}")


# --------------------------------------------------------------------------- slices

def slice_row(d: Path) -> dict:
    s = _state(d)
    phases = s.get("phases", {})
    nph = len(phases)
    appended = {str(p) for p in s.get("appended_phases") or []}
    hist = s.get("history", [])
    r1_block = r1_reviews = refuted = blocking = gate_red = 0
    for e in hist:
        if e.get("role") == "gate" and e.get("outcome") not in ("green", None):
            gate_red += 1
        if e.get("role") == "code-reviewer":
            fs = e.get("findings") or []
            blocking += sum(1 for f in fs if f.get("impact") == "blocking")
            refuted += sum(1 for f in fs if f.get("refuted"))
            if e.get("round") == 1:
                r1_reviews += 1
                r1_block += any(f.get("impact") == "blocking" for f in fs)
    abst = sum(len(ABST_RE.findall(f.read_text(errors="replace")))
               for f in d.glob("phases/P*/code_review_r*.md"))
    convs, _ = sc.collect(d)
    by_role: dict[str, float] = defaultdict(float)
    turns_role: dict[str, int] = defaultdict(int)
    for c in convs:
        by_role[c.role] += c.cost()
        turns_role[c.role] += c.turns
    cost = s.get("cost") or {}
    return {
        "slice": d.name, "version": s.get("plugin_version"), "nph": nph,
        "appended": len(appended),
        "total": sum(by_role.values()), "turns": sum(turns_role.values()),
        "cw": by_role.get("code-writer", 0), "cr": by_role.get("code-reviewer", 0),
        "cw_turns": turns_role.get("code-writer", 0),
        "cr_turns": turns_role.get("code-reviewer", 0),
        "doc": by_role.get("doc-writer", 0), "test": by_role.get("test-agent", 0),
        "explore": by_role.get("subagent:Explore", 0),
        "exec_rounds": sum(p.get("executor_rounds", 0) for p in phases.values()),
        "gate_fix": sum(p.get("gate_fix_rounds", 0) for p in phases.values()),
        "gate_red": gate_red, "r1_block": r1_block, "r1_reviews": r1_reviews,
        "blocking": blocking, "refuted": refuted,
        "rework_share": cost.get("rework_share"), "abst": abst,
        "test_rounds": s.get("test_rounds"), "consults": s.get("consult_seq"),
        "bailouts": len(s.get("bailouts") or []),
    }


def _fmt_slice(r: dict) -> str:
    ph = r["nph"] or 1
    return (f"{r['slice'][:34]:34s} v={r['version'] or '-':5s} ph={r['nph']:2d}(+{r['appended']}) "
            f"${r['total']:6.2f} turns={r['turns']:4d} $/ph={r['total'] / ph:5.2f} "
            f"cw$/ph={r['cw'] / ph:4.2f} cr$/ph={r['cr'] / ph:4.2f} "
            f"cw-t/ph={r['cw_turns'] / ph:4.1f} cr-t/ph={r['cr_turns'] / ph:4.1f} "
            f"exec/ph={r['exec_rounds'] / ph:.2f} r1blk={r['r1_block']}/{r['r1_reviews']} "
            f"ref={r['refuted']} gfix={r['gate_fix']} gred={r['gate_red']} "
            f"rework={r['rework_share']} abst={r['abst']} test_r={r['test_rounds']} "
            f"cons={r['consults']} bail={r['bailouts']} doc$={r['doc']:.2f} "
            f"test$={r['test']:.2f} expl$={r['explore']:.2f}")


def print_slices(new: list[Path]) -> None:
    rows = [slice_row(d) for d in corpus_dirs()]
    news = [slice_row(d) for d in new if (d / "state.json").is_file()]
    print("== corpus slices")
    for r in sorted(rows, key=lambda r: r["nph"]):
        print(_fmt_slice(r))
    print("== new slices")
    for r in news:
        print(_fmt_slice(r))

    def agg(label: str, rs: list[dict]) -> None:
        if not rs:
            return
        ph = sum(r["nph"] for r in rs) or 1
        tot = sum(r["total"] for r in rs)
        turns = sum(r["turns"] for r in rs) or 1
        print(f"{label:22s} n={len(rs):2d} phases={ph:3d} $/ph={tot / ph:5.2f} "
              f"cw$/ph={sum(r['cw'] for r in rs) / ph:4.2f} "
              f"cr$/ph={sum(r['cr'] for r in rs) / ph:4.2f} "
              f"cw-t/ph={sum(r['cw_turns'] for r in rs) / ph:4.1f} "
              f"cr-t/ph={sum(r['cr_turns'] for r in rs) / ph:4.1f} "
              f"$/turn={tot / turns:.4f} turns/ph={turns / ph:.0f} "
              f"exec/ph={sum(r['exec_rounds'] for r in rs) / ph:.2f} "
              f"r1blk={sum(r['r1_block'] for r in rs)}/{sum(r['r1_reviews'] for r in rs)} "
              f"refuted={sum(r['refuted'] for r in rs)} gfix={sum(r['gate_fix'] for r in rs)} "
              f"gred={sum(r['gate_red'] for r in rs)} "
              f"rework med={_med([r['rework_share'] for r in rs])} "
              f"abst={sum(r['abst'] for r in rs)} "
              f"doc$/slice={st.mean([r['doc'] for r in rs]):.2f} "
              f"test$/slice={st.mean([r['test'] for r in rs]):.2f} "
              f"expl$/slice={st.mean([r['explore'] for r in rs]):.2f}")

    print("== aggregates")
    agg("corpus all", rows)
    agg("corpus 2-4ph", [r for r in rows if 2 <= r["nph"] <= 4])
    agg("corpus 2-4ph KC", [r for r in rows if 2 <= r["nph"] <= 4 and r["slice"][0] == "1"])
    agg("corpus 16x-170", [r for r in rows if r["slice"][:2] == "16" or r["slice"][:3] == "170"])
    for v in sorted({r["version"] for r in news}, key=str):
        agg(f"new {v}", [r for r in news if r["version"] == v])
    agg("new all", news)


# --------------------------------------------------------------------------- plan-reads

def print_plan_reads(role: str, new: list[Path]) -> None:
    for d in new:
        try:
            convs, _ = sc.collect(d)
        except FileNotFoundError:
            continue
        for c in convs:
            if c.role != role:
                continue
            rep = tp.replay(c.transcript)
            turns = rep["turns"]
            fe = tp.first_edit_turn(turns) or 10**9
            n_edit = sum(1 for t in turns for r in t["tools"] if r["name"] in tp.WRITE_TOOLS)
            n_read = sum(1 for t in turns for r in t["tools"] if r["name"] == "Read")
            n_bash_edit = sum(1 for t in turns for r in t["tools"]
                              if r["name"] == "Bash" and "edit" in tp.bash_ops(r.get("cmd") or ""))
            print(f"-- {d.name[:24]} P{c.phase} r{c.round} v={_version(c.transcript)} "
                  f"turns={len(turns)} first_edit={fe if fe < 10**9 else None} "
                  f"Edit/Write={n_edit} Read={n_read} shell-edits={n_bash_edit}")
            for t in turns:
                for r in t["tools"]:
                    cmd = r.get("cmd") or ""
                    if "plan.md" not in r["key"] and "plan.md" not in cmd:
                        continue
                    kind = r["name"]
                    if r["name"] == "Bash" and not re.search(
                            r"\b(cat|sed|head|tail|grep|rg|less|wc|git)\b", cmd):
                        kind = "shell-edit"
                    where = "pre" if t["i"] < fe else "post"
                    print(f"     t{t['i']:3d} {where:4s} {kind:10s} res={r['result_chars']:6d} "
                          f"{r['key'][:110]!r}")
    vc: Counter = Counter()
    for d in corpus_dirs():
        convs, _ = sc.collect(d)
        vc.update(_version(c.transcript) for c in convs if c.role == role)
    print(f"corpus {role} Claude Code versions:", vc.most_common())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("view", choices=("writers", "slices", "plan-reads", "all"))
    ap.add_argument("--role", default="code-writer")
    ap.add_argument("--new", nargs="*", type=Path, default=DEFAULT_NEW,
                    help="slice directories run on the new plugin "
                         "(default: the four of 2026-08-23)")
    a = ap.parse_args(argv)
    if a.view in ("writers", "all"):
        print_writers(a.role, a.new)
    if a.view in ("slices", "all"):
        print()
        print_slices(a.new)
    if a.view in ("plan-reads", "all"):
        print()
        print_plan_reads(a.role, a.new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
