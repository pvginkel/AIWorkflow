import json, os, re, sys
from pathlib import Path
ROOT = Path.home() / ".claude/projects"
REM = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
pat = re.compile(r"triage", re.I)
pat2 = re.compile(r"format|template|too long|length|wall|verbose|shorter|read(ing)? it|useful|use(ful|less)|value|alternative|scheme|one-liner|one line|message|output|dislike|don't like|hate", re.I)
since = 1759190400  # 2026-09-30 UTC
for d in ROOT.iterdir():
    if d.name.startswith("-tmp") or d.name.startswith("-work-scratch"): continue
    for f in d.glob("*.jsonl"):
        if f.stat().st_mtime < since: continue
        with open(f, errors="replace") as fh:
            for line in fh:
                if '"type":"user"' not in line or 'triage' not in line.lower(): continue
                try: o = json.loads(line)
                except: continue
                if (o.get("origin") or {}).get("kind") != "human" or o.get("isMeta") or o.get("isSidechain") or o.get("timestamp","") < "2026-09-30": continue
                c = o["message"]["content"]
                if isinstance(c, list):
                    if any(b.get("type") == "tool_result" for b in c): continue
                    c = "\n".join(b.get("text", "") for b in c if b.get("type") == "text")
                t = REM.sub("", c).strip()
                if not t or t.startswith(("<command-", "<local-command", "<task-notification", "This session is being continued", "Caveat:")): continue
                if pat.search(t) and pat2.search(t):
                    print(f"=== {d.name} {f.name[:8]} {o['timestamp'][:16]} ({len(t)} ch)\n{t[:700]}\n")
