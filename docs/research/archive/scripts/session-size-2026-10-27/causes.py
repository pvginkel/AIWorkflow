#!/usr/bin/env python3
"""Where a session's context came from: base prompt, own output, tool results by class."""
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp  # noqa: E402

CHARS_PER_TOK = 3.6


def tool_cls(rec):
    c = tp.tool_class(rec["name"], rec["cmd"])
    if c == "Read":
        k = rec["key"]
        if "/slices/" in k or "Specs/" in k:
            return "Read:spec-repo"
        return "Read:code/docs"
    return c


def decompose(path):
    rep = tp.replay(Path(path))
    turns = [t for t in rep["turns"] if t["model"] != "<synthetic>"]
    if not turns:
        return None
    base = turns[0]["ctx"]
    grow = Counter()
    big = []
    reads = Counter()
    read_chars = Counter()
    for a, b in zip(turns, turns[1:], strict=False):
        d = b["ctx"] - a["ctx"]
        if d <= 0:
            continue
        own = min(a["out"], d)
        grow["own output (thinking+text+tool input)"] += own
        rest = d - own
        tot = sum(r["result_chars"] for r in a["tools"])
        if not tot:
            grow["user msg / reminder (no tool result)"] += rest
            continue
        for r in a["tools"]:
            share = rest * r["result_chars"] / tot
            grow[tool_cls(r)] += share
            if r["result_chars"] > 40_000:
                big.append((r["result_chars"], tool_cls(r), r["key"][:110]))
            if r["name"] == "Read":
                reads[r["key"]] += 1
                read_chars[r["key"]] += r["result_chars"]
    last = turns[-1]["ctx"] + turns[-1]["out"]
    rereads = sum(read_chars[k] * (n - 1) / n for k, n in reads.items() if n > 1)
    return {"base": base, "last": last, "turns": len(turns), "grow": grow,
            "user_prompts": rep["user_prompts"], "big": sorted(big, reverse=True)[:6],
            "reread_tok": rereads / CHARS_PER_TOK,
            "reads": reads, "read_chars": read_chars}


if __name__ == "__main__":
    rows = [r for r in json.load(open("sessions.json"))["rows"] if r["kind"] == "session"]
    xs = sorted(r["peak"] for r in rows)
    p95 = xs[int(len(xs) * .95)]
    top = [r for r in rows if r["peak"] >= p95]
    # reference: same role, 40-60th percentile of that role
    by_role = defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)
    ref = []
    for role, rs in by_role.items():
        rs = sorted(rs, key=lambda r: r["peak"])
        n = len(rs)
        ref += rs[int(n * .4):int(n * .6)]
    out = {"p95": p95, "top": [], "ref": []}
    for name, sel in (("top", top), ("ref", ref)):
        for r in sel:
            d = decompose(r["transcript"])
            if not d:
                continue
            d["grow"] = dict(d["grow"])
            d["reads"] = dict(d["reads"].most_common(15))
            d["read_chars"] = dict(d["read_chars"].most_common(15))
            out[name].append({**{k: r[k] for k in ("project", "slice", "role", "phase",
                                                    "round", "session", "transcript",
                                                    "slice_dir", "peak", "model")}, **d})
    json.dump(out, open("causes.json", "w"), indent=0)
