#!/usr/bin/env python3
"""Compact, readable digest of ONE Claude Code transcript (top-level or sub-agent).

Reads a multi-MB stream-json transcript and prints a human-scannable narrative:
  * header    — role/model, deduped turns, token breakdown, cost, wall-clock
  * tool use  — histogram by tool, and Bash sub-histogram by intent (test/build/
                git/lint/kubectl/deploy/read/...) so "what did it spend turns on"
                is obvious at a glance
  * timeline  — one line per assistant turn: elapsed, output toks, context size
                (cache_read), thinking?, text preview + tool calls
  * big I/O   — the largest tool RESULTS (test logs, file dumps) by size

Dedups by message.id (the transcript logs each assistant message ~2.5x).

Usage:
  python3 digest.py <transcript.jsonl>                 # full timeline
  python3 digest.py <transcript.jsonl> --tail 60       # last 60 turns
  python3 digest.py <transcript.jsonl> --grep pytest   # only turns touching pytest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import PurePosixPath

PRICES = {
    "claude-opus-4-8": (5.0, 25.0), "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0), "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
}
BASH_CATS = [
    ("test", re.compile(r"pytest|\btest\b|vitest|jest|npm test|uv run.*test|-m pytest", re.I)),
    ("lint/format", re.compile(r"ruff|black|eslint|prettier|mypy|lint|format|code.?health", re.I)),
    ("build", re.compile(r"\bbuild\b|docker|kaniko|compile|tsc|regenerate|codegen|openapi", re.I)),
    ("deploy/k8s", re.compile(r"kubectl|helm|deploy|track_build|jenkins|kube|pod|rollout", re.I)),
    ("git", re.compile(r"\bgit \b|git$|commit|branch|diff|merge|checkout|stash", re.I)),
    ("session/agent", re.compile(r"claude_session|kc session|send_message|start-headless", re.I)),
    ("read/inspect", re.compile(r"\bcat\b|\bls\b|head|tail|grep|find|wc|jq|echo|which", re.I)),
]


def price(model, tok):
    r = PRICES.get(model)
    if not r:
        return 0.0
    inp, out = r
    return (tok["input"] / 1e6 * inp + tok["output"] / 1e6 * out
            + tok["cw"] / 1e6 * inp * 1.25 + tok["cr"] / 1e6 * inp * 0.10)


def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def tool_desc(name, inp):
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        return inp.get("description") or (inp.get("command", "")[:100])
    if name in ("Read", "Edit", "Write"):
        return PurePosixPath(inp.get("file_path", "")).name
    if name == "Grep":
        return repr(inp.get("pattern", ""))[:40]
    if name in ("Task", "Agent"):
        return f"[{inp.get('subagent_type', inp.get('description',''))}] {inp.get('description','')}"[:90]
    if name == "TodoWrite":
        return f"{len(inp.get('todos', []))} todos"
    return json.dumps(inp)[:80]


def clip(s, n=140):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--tail", type=int, default=0)
    ap.add_argument("--head", type=int, default=0)
    ap.add_argument("--grep", default="")
    ap.add_argument("--big", type=int, default=12, help="show N biggest tool results")
    args = ap.parse_args()

    lines = open(args.path, errors="replace").read().splitlines()
    seen = set()
    tok = dict.fromkeys(["input", "output", "cw", "cr"], 0)
    models = Counter()
    tools = Counter()
    bash_cats = Counter()
    turns = []          # (elapsed_s, out, cr, think, text, [toolstrs])
    big = []            # (size, tool_name, preview)
    t0 = None
    raw = 0
    pend = {}           # tool_use_id -> name

    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        typ = o.get("type")
        t = ts(o.get("timestamp", ""))
        if t and t0 is None:
            t0 = t
        if typ == "user":
            for b in (o.get("message", {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content", "")
                    txt = c if isinstance(c, str) else " ".join(
                        x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c)
                    nm = pend.get(b.get("tool_use_id"), "?")
                    big.append((len(txt), nm + ("!err" if b.get("is_error") else ""), clip(txt, 160)))
            continue
        if typ != "assistant":
            continue
        msg = o.get("message", {})
        u = msg.get("usage")
        if not u:
            continue
        raw += 1
        mid = msg.get("id")
        if mid in seen:
            continue
        seen.add(mid)
        models[msg.get("model", "?")] += 1
        tok["input"] += u.get("input_tokens", 0) or 0
        tok["output"] += u.get("output_tokens", 0) or 0
        tok["cw"] += u.get("cache_creation_input_tokens", 0) or 0
        tok["cr"] += u.get("cache_read_input_tokens", 0) or 0
        think = any(isinstance(b, dict) and b.get("type") == "thinking"
                    for b in msg.get("content", []))
        text, tcalls = "", []
        for b in msg.get("content", []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                text += b["text"] + " "
            elif b.get("type") == "tool_use":
                nm = b.get("name", "?")
                tools[nm] += 1
                pend[b.get("id")] = nm
                d = tool_desc(nm, b.get("input", {}))
                if nm == "Bash":
                    cmd = (b.get("input", {}).get("command", "") + " " + d)
                    cat = next((c for c, rx in BASH_CATS if rx.search(cmd)), "other")
                    bash_cats[cat] += 1
                    tcalls.append(f"Bash/{cat}:{clip(d,60)}")
                else:
                    tcalls.append(f"{nm}:{clip(d,60)}")
        el = (t - t0).total_seconds() if t and t0 else 0
        turns.append((el, u.get("output_tokens", 0) or 0,
                      (u.get("cache_read_input_tokens", 0) or 0), think, clip(text), tcalls))

    dur = turns[-1][0] if turns else 0
    print(f"# {args.path}")
    print(f"# models={dict(models)}  turns={len(seen)} (raw {raw}, {raw/max(1,len(seen)):.1f}x dup)")
    print(f"# tokens in={tok['input']:,} out={tok['output']:,} "
          f"cache_write={tok['cw']:,} cache_read={tok['cr']:,}  "
          f"total={sum(tok.values()):,}")
    mc = models.most_common(1)[0][0] if models else "?"
    print(f"# cost≈${price(mc, tok):,.2f}  wall={dur/3600:.2f}h ({dur/60:.0f}m)")
    print(f"# TOOLS: {dict(tools.most_common())}")
    if bash_cats:
        print(f"# BASH by intent: {dict(bash_cats.most_common())}")
    print()

    rx = re.compile(args.grep, re.I) if args.grep else None
    rows = turns
    if args.grep:
        rows = [r for r in rows if rx.search(r[4]) or any(rx.search(t) for t in r[5])]
    if args.tail:
        rows = rows[-args.tail:]
    elif args.head:
        rows = rows[: args.head]
    for el, out, cr, think, text, tcalls in rows:
        m = int(el // 60)
        head = f"[{m:>4}m] out={out:>4} cr={cr//1000:>5}k {'T' if think else ' '}"
        if text:
            print(f"{head} · {text}")
        for tc in tcalls:
            print(f"{head} · → {tc}")
        if not text and not tcalls:
            print(f"{head} · (no text/tools)")
    if args.big and not args.grep:
        print(f"\n# {args.big} BIGGEST tool results (chars):")
        for size, nm, prev in sorted(big, reverse=True)[: args.big]:
            print(f"  {size:>9,}  {nm:20} {prev}")


if __name__ == "__main__":
    main()
