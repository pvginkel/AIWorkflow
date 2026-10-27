import json, re, sys, statistics as st
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp
d = json.load(open("causes.json"))

def detail(path):
    """per session: reads per path via Bash cat/sed and Read, written chars, thinking."""
    rep = tp.replay(Path(path))
    turns = [t for t in rep["turns"] if t["model"] != "<synthetic>"]
    per_path = defaultdict(lambda: [0, 0])  # path -> [times, chars]
    for t in turns:
        for r in t["tools"]:
            if r["name"] == "Read":
                ps = [r["key"]]
            elif r["name"] == "Bash" and tp.tool_class("Bash", r["cmd"]) == "cat/sed(read)":
                ps = tp.bash_read_paths(r["cmd"]) or ["<unparsed>"]
            else:
                continue
            for p in ps:
                per_path[p][0] += 1
                per_path[p][1] += r["result_chars"] / len(ps)
    think = sum(t["think"] for t in turns); out = sum(t["out"] for t in turns)
    return per_path, think, out, len(turns)

def kind(p):
    if p == "<unparsed>": return "unparsed"
    if re.search(r"/slices/|Specs/", p):
        if p.endswith("plan.md"): return "spec:plan.md"
        if "/phases/" in p: return "spec:phase files"
        if "/docs/" in p: return "spec:docs"
        return "spec:other"
    if p.endswith(".md"): return "repo:.md"
    if re.search(r"test", p): return "repo:tests"
    return "repo:code"

for role in ("code-writer", "doc-writer", "plan-writer"):
    for grp in ("top", "ref"):
        sel = [s for s in d[grp] if s["role"] == role]
        kinds = Counter(); times = Counter(); multi = 0; distinct = []; thinks = []; outs = []
        multi_chars = 0; tot_chars = 0
        for s in sel:
            pp, th, ou, n = detail(s["transcript"])
            thinks.append(th); outs.append(ou); distinct.append(len(pp))
            for p, (k, c) in pp.items():
                kinds[kind(p)] += c; tot_chars += c
                if k > 1: multi_chars += c * (k - 1) / k
        n = len(sel)
        print(f"{grp} {role} n={n}: distinct paths read median {st.median(distinct)}, "
              f"output {st.median(outs)/1e3:.0f}k of which thinking {st.median(thinks)/1e3:.0f}k; "
              f"re-read share of read chars {multi_chars/tot_chars:.0%}")
        print("   ", ", ".join(f"{k} {v/n/3.6/1e3:.1f}k" for k, v in kinds.most_common()))
