#!/usr/bin/env python3
"""Trello #782 — the round-1 blocking rate before and after dev 0.9.6–0.9.8, read per phase.

Reads every completed KubeCoder slice from 144 on (149–153 excluded: they predate the
anchored-findings fields of 0.4.3, so their reviewer rows carry no `impact`), splits the
phases into `pre` (no `plugin_version` in state.json — run before 0.9.6 landed on
2026-08-23) and `post`, and prints:

  - the per-slice table the card carries (phases, phases blocked at review round 1,
    blocking findings by anchor, advisory Majors);
  - the blocking rate by target class and by phase size, with a direct standardization
    (pooled per-size-bin rates applied to each era's size mix) — phase size is the added
    lines of the round-1 diff, `git diff --numstat <merge-base> <r1 commit>` with both
    SHAs read out of the reviewer's dispatch prompt, so it exists only where the r1
    commit survived the slice-end rebase (~55 % of code phases);
  - reviewer round-1 practice from the transcripts: turns, sessions that edited a
    non-record file *and* ran a test (the mutation proxy; edit-target detection is
    coarse — most shell edits resolve to `?` — so read it as a floor on both sides),
    words about mutation, sub-agent dispatches;
  - writer round-1 practice: turns, edits to test files vs other source, whether
    verification.json or the whole plan was opened, output tokens (a size proxy that
    every phase has), test-line share of the diff where it exists;
  - the coverage-gap anchor's impact split, the model / effort / CLI version per era.

`--per-slice` prints the card's table only; `--dump` appends one line per reviewer
session. Transcript facts are cached in `--cache` (default /tmp/r1_blocking_facts.json).
Research tooling, not plugin: imports the plugin's turn_profile.py for its shell-op
classifier and run_loop.py for parse_plan. The write-up is
docs/research/r1-blocking-2026-09-01.md.
"""

import argparse
import glob
import importlib.util
import json
import os
import re
import statistics as st
import subprocess
from collections import Counter, defaultdict

PLUGIN_TOOLS = "/work/AIWorkflow/plugins/dev/tools"
SPECS = "/work/KubeCoderSpecs/slices"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, f"{PLUGIN_TOOLS}/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load("turn_profile")

TEST_RE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.go|[^/]*\.(test|spec)\.[jt]sx?|tests?/"
                     r"|__tests__/|conftest\.py|testing/)")
RECORD_RE = re.compile(r"code_review_r|review_result_r|executor_result_r|close-out\.md"
                       r"|close_out\.py|plan\.md|/slices/")
MUT_RE = re.compile(r"mutat", re.I)
REVERT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(checkout\s+(--|\S+\s+--|HEAD)|restore|stash)\b")
MB_RE = re.compile(r"git diff ([0-9a-f]{40})\.\.HEAD")
R1_RE = re.compile(r"exact commit \(([0-9a-f]{6,})\)")
CODE_TARGETS = ("root", "worker", "vscode(ts)")
SIZE_BINS = [(0, 100), (100, 300), (300, 600), (600, 1200), (1200, 10**9)]


def slice_states():
    paths = sorted(glob.glob(f"{SPECS}/completed/*/state.json"))
    paths += sorted(glob.glob(f"{SPECS}/[0-9]*/state.json"))  # in-progress slices
    for p in paths:
        n = os.path.basename(os.path.dirname(p)).split("_")[0]
        try:
            num = int(n.rstrip("b"))
        except ValueError:
            continue
        if num < 144 or 149 <= num <= 153:
            continue
        yield n, os.path.dirname(p), json.load(open(p))


def iter_msgs(path):
    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def session_facts(path):
    f = {"turns": 0, "tools": 0, "bash": 0, "edits": 0, "src_edits": 0, "test_edits": 0,
         "nontest_edits": 0, "gates": 0, "reverts": 0, "mut_words": 0, "dispatch": 0,
         "verif_reads": 0, "plan_cat": 0, "ac_words": 0, "edit_targets": [], "first_prompt": "",
         "out_tok": 0, "ctx_max": 0, "model": "", "effort": "", "version": ""}
    seen = set()
    for o in iter_msgs(path):
        t = o.get("type")
        msg = o.get("message") or {}
        if t == "user" and not f["first_prompt"]:
            c = msg.get("content")
            if isinstance(c, str):
                f["first_prompt"] = c
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        f["first_prompt"] = b["text"]
                        break
        if t != "assistant":
            continue
        if not f["model"]:
            f["model"] = msg.get("model", "")
            f["effort"] = o.get("effort") or ""
            f["version"] = o.get("version", "")
        mid = msg.get("id")
        if mid and mid not in seen and msg.get("usage"):
            seen.add(mid)
            u = msg["usage"]
            f["turns"] += 1
            f["out_tok"] += u.get("output_tokens", 0) or 0
            f["ctx_max"] = max(f["ctx_max"], sum((u.get(k, 0) or 0) for k in (
                "cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens")))
        for b in msg.get("content") or []:
            if b.get("type") == "text":
                f["mut_words"] += len(MUT_RE.findall(b["text"]))
                f["ac_words"] += len(re.findall(r"acceptance criteri|\bV\d\d\b", b["text"]))
            if b.get("type") != "tool_use":
                continue
            f["tools"] += 1
            name = b["name"]
            inp = b.get("input") or {}
            targets = []
            if name in ("Agent", "Task"):
                f["dispatch"] += 1
            if name in tp.WRITE_TOOLS:
                f["edits"] += 1
                targets = [inp.get("file_path") or inp.get("path") or ""]
            elif name == "Read":
                p = inp.get("file_path", "")
                f["verif_reads"] += "verification.json" in p
                f["plan_cat"] += p.endswith("plan.md")
            elif name == "Bash":
                cmd = inp.get("command", "") or ""
                f["bash"] += 1
                ops = tp.bash_ops(cmd)
                f["gates"] += ops.count("gate")
                if "edit" in ops:
                    f["edits"] += 1
                    targets = tp._bash_edit_targets(cmd) or ["?"]
                f["reverts"] += bool(REVERT_RE.search(cmd))
                if "verification.json" in cmd and re.search(r"\b(cat|sed|head|jq|python)", cmd):
                    f["verif_reads"] += 1
                f["plan_cat"] += bool(re.search(r"\bcat\b[^|;&]*plan\.md", cmd))
            for tg in targets:
                if RECORD_RE.search(tg):
                    continue
                f["src_edits"] += 1
                f["edit_targets"].append(tg)
                if TEST_RE.search(tg):
                    f["test_edits"] += 1
                else:
                    f["nontest_edits"] += 1
    return f


def tclass(t):
    if not t:
        return "?"
    if "Specs" in t:
        return "specs"
    if "vscode" in t:
        return "vscode(ts)"
    return t


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 2) if xs else None


def load_rows():
    rows = []
    for n, sd, d in slice_states():
        era = "pre" if not d.get("plugin_version") else "post"
        for r in d["history"]:
            if r.get("round") != 1 or r.get("role") not in ("code-writer", "code-reviewer"):
                continue
            ph = d["phases"].get(r["phase"], {})
            rows.append({"slice": n, "era": era, "pv": d.get("plugin_version") or "pre",
                         "phase": r["phase"], "target": ph.get("target"), "role": r["role"],
                         "transcript": r.get("transcript"), "duration": r.get("duration_s"),
                         "findings": r.get("findings", []), "sd": sd})
    blk = {}
    for r in rows:
        if r["role"] == "code-reviewer":
            b = [x for x in r["findings"] if x.get("impact") == "blocking"]
            adv = [x for x in r["findings"]
                   if x.get("impact") != "blocking" and x.get("severity") == "Major"]
            blk[(r["slice"], r["phase"])] = (bool(b), Counter(x.get("anchor") for x in b),
                                             len(adv))
    for r in rows:
        r["blocked"], r["anchors"], r["adv_major"] = blk.get(
            (r["slice"], r["phase"]), (False, Counter(), 0))
    return rows


def per_slice(rows):
    print("## Per slice: phases reviewed, blocked at r1, blocking findings by anchor")
    by = defaultdict(list)
    for r in rows:
        if r["role"] == "code-reviewer":
            by[(r["slice"], r["pv"])].append(r)
    tot = defaultdict(lambda: [0, 0, Counter()])
    for (n, pv), R in sorted(by.items()):
        a = Counter()
        for r in R:
            a.update(r["anchors"])
        blk = sum(r["blocked"] for r in R)
        era = "pre" if pv == "pre" else "post"
        tot[era][0] += len(R)
        tot[era][1] += blk
        tot[era][2] += a
        print(f"  {n:>4} {pv:>7} ph={len(R):>2} blk-ph={blk:>2} blk={sum(a.values()):>2} "
              f"advMaj={sum(r['adv_major'] for r in R):>2}  {dict(a)}")
    for era in ("pre", "post"):
        n, b, a = tot[era]
        print(f"  {era:>4}: {n} phases, {b} blocked at r1 ({100*b/n:.0f}%); {dict(a)}")


def numstat(r):
    """(test lines, other lines, [(added, path)]) of the r1 diff, or None."""
    m = MB_RE.search(r["f"]["first_prompt"])
    m1 = R1_RE.search(r["f"]["first_prompt"])
    if not m or not m1 or tclass(r["target"]) not in CODE_TARGETS:
        return None
    p = subprocess.run(["git", "-C", "/work/KubeCoder", "diff", "--numstat", m.group(1),
                        m1.group(1)], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    ta = na = 0
    files = []
    for line in p.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue
        a, path = int(parts[0]), parts[2]
        files.append((a, path))
        if path.endswith(".md") or "/docs/" in path:
            continue
        if TEST_RE.search(path):
            ta += a
        else:
            na += a
    return ta, na, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-slice", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--cache", default="/tmp/r1_blocking_facts.json")
    args = ap.parse_args()
    rows = load_rows()
    per_slice(rows)
    if args.per_slice:
        return

    cache = json.load(open(args.cache)) if os.path.exists(args.cache) else {}
    for r in rows:
        tpath = r["transcript"]
        if not tpath or not os.path.exists(tpath):
            r["f"] = None
            continue
        if tpath not in cache:
            cache[tpath] = session_facts(tpath)
        r["f"] = cache[tpath]
    json.dump(cache, open(args.cache, "w"))
    rev = [r for r in rows if r["role"] == "code-reviewer" and r["f"]]
    wr = [r for r in rows if r["role"] == "code-writer" and r["f"]]

    print("\n## Round-1 blocking rate by target class")
    tab = defaultdict(lambda: [0, 0, Counter()])
    for r in rev:
        k = (r["era"], tclass(r["target"]))
        tab[k][0] += 1
        tab[k][1] += r["blocked"]
        tab[k][2] += r["anchors"]
    for k in sorted(tab):
        n, b, a = tab[k]
        print(f"  {k[0]:>4} {k[1]:<15} phases={n:>3} blocked={b:>2} ({100*b/n:3.0f}%)  {dict(a)}")

    print("\n## coverage-gap anchors by (impact, severity)")
    for era in ("pre", "post"):
        c = Counter((f.get("impact"), f.get("severity")) for r in rev if r["era"] == era
                    for f in r["findings"] if f.get("anchor") == "coverage-gap")
        print(f"  {era}: {dict(c)}")

    print("\n## Model / effort / CLI version")
    for role, S0 in (("reviewer", rev), ("writer", wr)):
        for era in ("pre", "post"):
            S = [r for r in S0 if r["era"] == era]
            print(f"  {role:<8} {era:>4} models={dict(Counter(r['f']['model'] for r in S))} "
                  f"effort={dict(Counter(r['f']['effort'] for r in S))} "
                  f"cli={dict(Counter(r['f']['version'] for r in S))}")

    print("\n## Reviewer round-1 practice")
    for era in ("pre", "post"):
        R = [r for r in rev if r["era"] == era]
        F = [r["f"] for r in R]

        def mut(rs):
            return [r for r in rs if r["f"]["src_edits"] > 0 and r["f"]["gates"] > 0]
        pct = 100 * len(mut(R)) / len(R)
        print(f"  {era}: n={len(R)} turns med={med([f['turns'] for f in F])} "
              f"dur med={med([r['duration'] for r in R])}s | "
              f"mutation sessions={len(mut(R))} ({pct:.0f}%) | "
              f"gates/session={mean([f['gates'] for f in F])} "
              f"mutation-words/session={mean([f['mut_words'] for f in F])} "
              f"sub-agents={sum(f['dispatch'] for f in F)}")
        for blocked in (False, True):
            S = [r for r in R if r["blocked"] == blocked]
            pct = 100 * len(mut(S)) / max(1, len(S))
            print(f"      blocked={blocked!s:<5} n={len(S):>3} "
                  f"mutation sessions={len(mut(S)):>3} ({pct:.0f}%) "
                  f"turns med={med([r['f']['turns'] for r in S])}")
        cg = [r for r in R if r["anchors"].get("coverage-gap")]
        print(f"      coverage-gap-blocked phases={len(cg)} "
              f"of which mutation sessions={len(mut(cg))}")

    print("\n## Writer round-1 practice")
    for era in ("pre", "post"):
        W = [r for r in wr if r["era"] == era]
        F = [r["f"] for r in W]
        vr = sum(1 for f in F if f["verif_reads"])
        pc = sum(1 for f in F if f["plan_cat"])
        print(f"  {era}: n={len(W)} turns med={med([f['turns'] for f in F])} "
              f"dur med={med([r['duration'] for r in W])}s | verification.json opened={vr} "
              f"({100*vr/len(W):.0f}%) | plan read whole={pc} ({100*pc/len(W):.0f}%) | "
              f"AC mentions/session={mean([f['ac_words'] for f in F])} | "
              f"out_tok med={med([f['out_tok'] for f in F])} | "
              f"gates/session={mean([f['gates'] for f in F])}")
        for tc in CODE_TARGETS:
            S = [r for r in W if tclass(r["target"]) == tc]
            if not S:
                continue
            nt = sum(1 for r in S if r["f"]["src_edits"] and r["f"]["test_edits"] == 0)
            print(f"      {tc:<11} n={len(S):>3} out_tok med={med([r['f']['out_tok'] for r in S])} "
                  f"src edits med={med([r['f']['src_edits'] for r in S])} "
                  f"test-file edits med={med([r['f']['test_edits'] for r in S])} "
                  f"zero-test-edit phases={nt} blocked={sum(r['blocked'] for r in S)}")
        C = [r for r in W if tclass(r["target"]) in CODE_TARGETS]
        for flag in (True, False):
            S = [r for r in C if bool(r["f"]["verif_reads"]) == flag]
            if S:
                b = sum(r["blocked"] for r in S)
                print(f"      verification.json opened={flag!s:<5} n={len(S):>3} "
                      f"blocked={b} ({100*b/len(S):.0f}%) "
                      f"coverage-gap={sum(r['anchors'].get('coverage-gap', 0) for r in S)}")

    print("\n## Phase size: writer output-token terciles (every code phase)")
    C = [r for r in wr if tclass(r["target"]) in CODE_TARGETS]
    toks = sorted(r["f"]["out_tok"] for r in C)
    t1, t2 = toks[len(toks) // 3], toks[2 * len(toks) // 3]
    print(f"  bands: S<{t1} M<{t2} L>={t2} output tokens")
    tab = defaultdict(lambda: [0, 0, 0])
    for r in C:
        band = "S" if r["f"]["out_tok"] < t1 else ("M" if r["f"]["out_tok"] < t2 else "L")
        k = (r["era"], band)
        tab[k][0] += 1
        tab[k][1] += r["blocked"]
        tab[k][2] += r["anchors"].get("coverage-gap", 0)
    for k in sorted(tab, key=lambda k: (k[1], k[0])):
        n, b, cg = tab[k]
        print(f"  {k[0]:>4} band {k[1]} phases={n:>3} blocked={b:>2} ({100*b/n:3.0f}%) "
              f"coverage-gap={cg}")

    print("\n## Phase size: added lines of the r1 diff (where the r1 commit survives)")
    N = []
    for r in rev:
        ns = numstat(r)
        if ns:
            r["numstat"] = ns
            N.append(r)
    for era in ("pre", "post"):
        S = [r for r in N if r["era"] == era]
        tot = [r["numstat"][0] + r["numstat"][1] for r in S]
        share = [r["numstat"][0] / max(1, r["numstat"][0] + r["numstat"][1]) for r in S]
        code = sum(1 for r in rev if r["era"] == era and tclass(r["target"]) in CODE_TARGETS)
        blk = [t for t, r in zip(tot, S, strict=True) if r["blocked"]]
        unb = [t for t, r in zip(tot, S, strict=True) if not r["blocked"]]
        print(f"  {era}: phases={len(S)}/{code} added lines med={med(tot)} mean={mean(tot)} | "
              f"blocked med={med(blk)} unblocked med={med(unb)} | "
              f"test-line share med={med(share)}")
    print("  size bin        | pre blocked/phases  anchors | post blocked/phases  anchors")
    pooled = {}
    for lo, hi in SIZE_BINS:
        line = f"  {lo:>5}-{hi if hi < 10**9 else 'inf':<5}    "
        S_all = [r for r in N if lo <= sum(r["numstat"][:2]) < hi]
        pooled[(lo, hi)] = (sum(r["blocked"] for r in S_all), len(S_all))
        for era in ("pre", "post"):
            S = [r for r in S_all if r["era"] == era]
            a = Counter()
            for r in S:
                a.update(r["anchors"])
            line += f"| {era}: {sum(r['blocked'] for r in S):>2}/{len(S):<3} {dict(a)} "
        print(line)
    print("  direct standardization (pooled per-bin rate x each era's size mix):")
    for era in ("pre", "post"):
        S = [r for r in N if r["era"] == era]
        exp = sum(k * (b / n if n else 0) for (lo, hi), (b, n) in pooled.items()
                  for k in [sum(1 for r in S if lo <= sum(r["numstat"][:2]) < hi)])
        print(f"    {era}: observed {sum(r['blocked'] for r in S)}/{len(S)} = "
              f"{100*sum(r['blocked'] for r in S)/len(S):.0f}%  expected from size "
              f"{exp:.1f}/{len(S)} = {100*exp/len(S):.0f}%")

    if args.dump:
        print("\n## Reviewer sessions")
        for r in rev:
            print(r["era"], r["slice"], f"P{r['phase']}", tclass(r["target"]),
                  "BLK" if r["blocked"] else "   ", dict(r["anchors"]), "turns", r["f"]["turns"],
                  "src_edits", r["f"]["src_edits"], "gates", r["f"]["gates"],
                  "lines", sum(r["numstat"][:2]) if r.get("numstat") else "-")


if __name__ == "__main__":
    main()
