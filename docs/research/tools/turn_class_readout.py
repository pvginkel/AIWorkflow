#!/usr/bin/env python3
"""Turn-class readout: replay a corpus of transcripts through the plugin's
turn_profile and show where its classes go wrong.

    turn_class_readout.py scan <paths-file|conversations.json> [--jobs N] [--out F]
    turn_class_readout.py report <scan.json> [--section S] [--top N]

`scan` replays every transcript (one per line in a paths file, or every
`path` of a cost-dashboard conversations.json) with the plugin's
`turn_profile` from this checkout, prices it with `slice_cost.cost_for`, and
writes one JSON of aggregates: cost and turns per class, why each `other`
turn is other (its op set, the programs and tools behind it, examples), the
targets a shell edit was read from, what a fumble's failure text was, the
tools by class, the user-text kinds counted as prompts. `report` prints them.

Research tooling (AIWF-156), not plugin: it imports turn_profile and
slice_cost from plugins/dev/tools.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "plugins" / "dev" / "tools"
sys.path.insert(0, str(TOOLS))
import slice_cost  # noqa: E402
import turn_profile as tp  # noqa: E402

EX = 4          # examples kept per key
CUT = 220       # chars of an example


def _ex(store: dict, key: str, val: str):
    lst = store.setdefault(key, [])
    if len(lst) < EX and val not in lst:
        lst.append(val[:CUT])


def _user_kinds(path: Path) -> Counter:
    """What the replay counts as a user prompt, by kind."""
    out = Counter()
    with path.open(errors="replace", newline="\n") as fh:
        for line in fh:
            if '"type":"user"' not in line and '"type": "user"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            c = (o.get("message") or {}).get("content")
            texts = [c] if isinstance(c, str) else [
                b.get("text", "") for b in (c or [])
                if isinstance(b, dict) and b.get("type") == "text"]
            for txt in texts:
                if not isinstance(c, str) and ("<system-reminder>" in txt
                                               or "<attachment" in txt):
                    continue
                s = txt.lstrip()
                m = re.match(r"<([\w-]+)", s)
                k = (f"<{m.group(1)}>" if m else
                     "[Request interrupted" if s.startswith("[Request interrupted") else
                     "meta" if o.get("isMeta") else
                     "compact-summary" if o.get("isCompactSummary") else
                     "sidechain" if o.get("isSidechain") else "text")
                out[k] += 1
    return out


def scan_one(path: str) -> dict:
    p = Path(path)
    agg = {"n": 0, "cls_turns": Counter(), "cls_cost": Counter(),
           "other_sig": Counter(), "other_sig_cost": Counter(), "other_ex": {},
           "seg_other_prog": Counter(), "seg_other_ex": {},
           "tool_cls": Counter(), "tool_cost": Counter(),
           "redir_only_edit": Counter(), "redir_ex": {}, "redir_edit_cost": 0.0,
           "fail_match": Counter(), "fail_ex": {}, "fail_cls": Counter(),
           "models": Counter(), "user_kinds": Counter(), "err": None,
           "mixed_record_edit": 0, "think_stop": Counter(), "wait_ex": {},
           "gate_ex": {}, "gate_seg": Counter()}
    try:
        rep = tp.replay(p)
        an = tp.analyse(rep, slice_cost.cost_for)
    except Exception as e:  # noqa: BLE001
        agg["err"] = f"{type(e).__name__}: {e}"[:200]
        return agg
    if not an:
        return agg
    agg["n"] = 1
    agg["user_kinds"] = _user_kinds(p)
    for t, c, cost in zip(an["turns"], an["classes"], an["turn_cost"], strict=True):
        cls = c["cls"]
        agg["cls_turns"][cls] += 1
        agg["cls_cost"][cls] += cost
        agg["models"][t["model"]] += 1
        if cls == "think":
            agg["think_stop"][str(t.get("stop"))] += 1
        ops, targets, _ = tp.turn_ops(t)
        opset = set(ops)
        if "edit" in opset and "record" in opset:
            agg["mixed_record_edit"] += 1
        for r in t["tools"]:
            nm = r["name"]
            key = nm if nm != "Bash" else "Bash"
            if nm.startswith("mcp__"):
                key = "mcp__" + nm.split("__")[1] + "__" + nm.split("__")[-1]
            agg["tool_cls"][f"{key} -> {cls}"] += 1
            if nm != "Bash":
                agg["tool_cost"][key] += cost / max(1, len(t["tools"]))
            if tp._failed(r) and cls in ("fumble", "retry"):
                m = tp.FAIL_RE.search(r.get("res_head", ""))
                mk = (m.group(0).strip()[:40] if m else "is_error")
                agg["fail_match"][mk] += 1
                agg["fail_cls"][f"{mk} -> {nm}"] += 1
                head = r.get("res_head", "")
                if m:
                    head = head[max(0, m.start() - 60):m.end() + 60]
                _ex(agg["fail_ex"], mk, f"{nm}: {(r.get('cmd') or r['key'])[:110]} ==> "
                    f"{head!r}")
        if cls == "wait":
            for r in t["tools"]:
                _ex(agg["wait_ex"], "wait", (r.get("cmd") or r["name"])[:CUT])
        if cls == "gate":
            for r in t["tools"]:
                for s in tp.bash_segments(r.get("cmd") or ""):
                    if tp._seg_op(s) == "gate":
                        m = tp.GATE_SEG_RE.search(s)
                        agg["gate_seg"][m.group(0) if m else tp._seg_prog(s)] += 1
        # shell edit read only from a redirection
        if cls == "edit":
            via = []
            for r in t["tools"]:
                if r["name"] in tp.WRITE_TOOLS:
                    via.append("tool")
                elif r["name"] == "Bash":
                    cmd = r.get("cmd") or ""
                    for s in tp.bash_segments(cmd):
                        if tp._seg_op(s) != "edit":
                            continue
                        if any(rx.search(s) for rx in tp.SHELL_EDIT_RES_BASE):
                            via.append("shell")
                        else:
                            via.append("redirect")
                            for m in tp.REDIRECT_RE.finditer(s):
                                tgt = m.group(1)
                                kind = ("/tmp" if tgt.startswith(("/tmp", "$TMP", "${TMP"))
                                        else "log" if tgt.endswith((".log", ".txt", ".out"))
                                        else "numeric" if re.fullmatch(r"[\d.]+", tgt)
                                        else "other")
                                agg["redir_only_edit"][kind] += 1
                                _ex(agg["redir_ex"], kind, s)
                    if any(rx.search(cmd) for rx in tp.BODY_EDIT_RES):
                        via.append("body")
            if via and set(via) == {"redirect"}:
                agg["redir_edit_cost"] += cost
        if cls != "other":
            continue
        parts = set()
        for r in t["tools"]:
            nm = r["name"]
            if nm == "Bash":
                for s in tp.bash_segments(r.get("cmd") or ""):
                    op = tp._seg_op(s)
                    if op == "other":
                        prog = tp._seg_prog(s) or "?"
                        if prog.startswith("python") or prog == "uv":
                            mm = re.search(r"([\w.-]+\.py)\b", s)
                            prog = f"{prog}:{mm.group(1) if mm else '-c/heredoc'}"
                        elif prog in ("kc", "cexec", "npx", "pnpm", "npm", "docker",
                                      "kubectl", "helm", "gh", "curl", "make"):
                            mm = re.match(r"\S+\s+(\S+)(?:\s+(\S+))?", tp.WRAPPER_RE.sub(
                                "", tp.ENV_PREFIX_RE.sub("", s)))
                            if mm:
                                prog = f"{prog} {mm.group(1)}" + (
                                    f" {mm.group(2)}" if prog in ("kc", "cexec") and mm.group(2)
                                    else "")
                        agg["seg_other_prog"][prog] += 1
                        _ex(agg["seg_other_ex"], prog, s)
                        parts.add(f"sh:{prog.split(':')[0].split(' ')[0]}")
                    elif op != "noop":
                        parts.add(op)
            elif nm.startswith("mcp__"):
                parts.add("mcp:" + nm.split("__")[1])
            else:
                parts.add(nm if nm not in tp.READ_TOOLS else "read")
        sig = " + ".join(sorted(parts)) or "(none)"
        agg["other_sig"][sig] += 1
        agg["other_sig_cost"][sig] += cost
        _ex(agg["other_ex"], sig, " ;; ".join((r.get("cmd") or r["name"] + ":" + r["key"])[:120]
                                              for r in t["tools"]))
    return agg


def merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if k == "err":
            if v:
                a.setdefault("errors", []).append(v)
            continue
        if isinstance(v, Counter):
            a.setdefault(k, Counter()).update(v)
        elif isinstance(v, dict):
            d = a.setdefault(k, {})
            for kk, lst in v.items():
                cur = d.setdefault(kk, [])
                for x in lst:
                    if len(cur) < EX and x not in cur:
                        cur.append(x)
        elif isinstance(v, (int, float)):
            a[k] = a.get(k, 0) + v
    return a


def load_paths(src: str) -> list[str]:
    p = Path(src)
    if p.suffix == ".json":
        recs = json.loads(p.read_text())["records"]
        return sorted({r["path"] for r in recs if r.get("path") and Path(r["path"]).exists()})
    return [x.strip() for x in p.read_text().splitlines() if x.strip()]


def cmd_scan(args):
    paths = load_paths(args.src)
    total: dict = {}
    with ProcessPoolExecutor(args.jobs) as ex:
        for i, agg in enumerate(ex.map(scan_one, paths, chunksize=16)):
            merge(total, agg)
            if i % 1000 == 0:
                print(f"{i}/{len(paths)}", file=sys.stderr)
    out = {k: (dict(v.most_common()) if isinstance(v, Counter) else v)
           for k, v in total.items()}
    Path(args.out).write_text(json.dumps(out, indent=1))
    print(f"{total.get('n', 0)} transcripts -> {args.out}", file=sys.stderr)


def cmd_report(args):
    d = json.loads(Path(args.scan).read_text())
    top = args.top
    want = set(args.section or [])

    def sec(name):
        return not want or name in want

    tot = sum(d["cls_cost"].values())
    if sec("classes"):
        print(f"== classes ({d['n']} transcripts, ${tot:,.0f})")
        for k, v in sorted(d["cls_cost"].items(), key=lambda x: -x[1]):
            print(f"  {k:12} {d['cls_turns'][k]:7}  ${v:9,.0f}  {v / tot:6.1%}")
    if sec("other"):
        print("\n== other: by signature (turns, $)")
        for k, v in sorted(d["other_sig_cost"].items(), key=lambda x: -x[1])[:top]:
            print(f"  ${v:8,.0f} {d['other_sig'][k]:6}  {k}")
            for e in d["other_ex"].get(k, [])[:2]:
                print(f"           e.g. {e}")
    if sec("progs"):
        print("\n== other: shell programs")
        for k, v in list(d["seg_other_prog"].items())[:top]:
            print(f"  {v:7}  {k}")
            for e in d["seg_other_ex"].get(k, [])[:2]:
                print(f"           e.g. {e}")
    if sec("tools"):
        print("\n== non-Bash tools -> class")
        for k, v in list(d["tool_cls"].items())[:top]:
            if not k.startswith("Bash"):
                print(f"  {v:7}  {k}")
    if sec("redirect"):
        print(f"\n== edits read only from a redirection: ${d.get('redir_edit_cost', 0):,.0f}")
        for k, v in d["redir_only_edit"].items():
            print(f"  {v:7}  {k}")
            for e in d["redir_ex"].get(k, []):
                print(f"           e.g. {e}")
    if sec("fail"):
        print("\n== fumble/retry failure markers")
        for k, v in list(d["fail_match"].items())[:top]:
            print(f"  {v:7}  {k!r}")
            for e in d["fail_ex"].get(k, [])[:3]:
                print(f"           e.g. {e}")
    if sec("misc"):
        print("\n== models", dict(list(d["models"].items())[:10]))
        print("== user kinds", d["user_kinds"])
        print("== think stop", d["think_stop"])
        print("== mixed record+edit turns", d.get("mixed_record_edit"))
        print("== gate segs", dict(list(d["gate_seg"].items())[:20]))
        print("== wait ex", d["wait_ex"])
        print("== errors", (d.get("errors") or [])[:5])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("src")
    s.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    s.add_argument("--out", default="/tmp/turn_class_scan.json")
    r = sub.add_parser("report")
    r.add_argument("scan")
    r.add_argument("--section", action="append")
    r.add_argument("--top", type=int, default=40)
    a = ap.parse_args()
    {"scan": cmd_scan, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
