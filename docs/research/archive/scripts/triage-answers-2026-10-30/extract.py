#!/usr/bin/env python3
"""Extract /dev:triage runs (2026-09-30 on) from Claude Code transcripts.

Writes runs.json (all runs, every event in the run window) and one timeline per run under runs/.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
OUT = Path(__file__).resolve().parent
SINCE = "2026-09-30"
CMD_RE = re.compile(r"<command-name>([^<]*)</command-name>")
ARGS_RE = re.compile(r"<command-args>([^<]*)</command-args>", re.S)
REM_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
VER_RE = re.compile(r"/dev/(\d+\.\d+\.\d+)/skills/triage")
NOT_OPERATOR = ("<local-command", "<task-notification", "<persisted", "Caveat:", "<bash-",
                "<user-memory-input>")
BENIGN_CMDS = {"/context", "/cost", "/usage", "/model", "/status", "/compact", "/config",
               "/statusline", "/memory", "/help", "/doctor", "/mcp", "/effort"}


def text_of(content):
    if isinstance(content, str):
        return content, []
    texts, results = [], []
    for b in content:
        t = b.get("type")
        if t == "text":
            texts.append(b.get("text", ""))
        elif t == "tool_result":
            results.append(b)
    return "\n".join(texts), results


def events(path):
    """Yield normalised events from one transcript, in order."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = o.get("type")
            if typ not in ("user", "assistant") or o.get("isSidechain"):
                continue
            ts = o.get("timestamp", "")
            msg = o.get("message") or {}
            content = msg.get("content")
            if typ == "user":
                txt, results = text_of(content)
                for r in results:
                    rc = r.get("content")
                    if isinstance(rc, list):
                        rc = "\n".join(x.get("text", "") for x in rc if isinstance(x, dict))
                    yield {"k": "result", "ts": ts, "id": r.get("tool_use_id"), "text": rc or ""}
                if not txt.strip():
                    continue
                if o.get("isMeta"):
                    m = VER_RE.search(txt)
                    yield {"k": "meta", "ts": ts, "ver": m.group(1) if m else None,
                           "head": txt[:120]}
                    continue
                m = CMD_RE.search(txt)
                if m:
                    a = ARGS_RE.search(txt)
                    yield {"k": "cmd", "ts": ts, "name": m.group(1).strip(),
                           "args": (a.group(1).strip() if a else "")}
                    continue
                clean = REM_RE.sub("", txt).strip()
                if not clean:
                    continue
                if clean.startswith(NOT_OPERATOR):
                    yield {"k": "sys", "ts": ts, "text": clean[:200]}
                    continue
                if clean.startswith("[Request interrupted"):
                    yield {"k": "interrupt", "ts": ts, "text": clean}
                    continue
                yield {"k": "op", "ts": ts, "text": clean}
            else:
                if not isinstance(content, list):
                    continue
                for b in content:
                    t = b.get("type")
                    if t == "text" and b.get("text", "").strip():
                        yield {"k": "asst", "ts": ts, "text": b["text"], "mid": msg.get("id")}
                    elif t == "tool_use":
                        inp = b.get("input") or {}
                        name = b.get("name")
                        ev = {"k": "tool", "ts": ts, "name": name, "id": b.get("id")}
                        if name == "Bash":
                            ev["cmd"] = inp.get("command", "")
                        elif name == "AskUserQuestion":
                            ev["input"] = inp
                        elif name == "Skill":
                            ev["skill"] = inp.get("skill")
                            ev["args"] = inp.get("args") or ""
                        elif name in ("Agent", "Task"):
                            ev["desc"] = inp.get("description", "")
                        yield ev


def main():
    files = sorted({Path(l.strip()) for f in ("files.txt", "skillfiles.txt")
                    for l in open(OUT / f) if l.strip()})
    runs = []
    for rel in files:
        if "/subagents/" in str(rel):
            continue
        path = ROOT / rel
        folder = rel.parts[1] if rel.parts[0] == "." else rel.parts[0]
        evs = list(events(path))
        starts = [i for i, e in enumerate(evs)
                  if e["ts"][:10] >= SINCE and (
                      (e["k"] == "cmd" and e["name"] == "/dev:triage")
                      or (e["k"] == "tool" and e["name"] == "Skill" and e.get("skill") == "dev:triage"))]
        for si in starts:
            # end: next non-benign slash command, or end of session
            end = len(evs)
            ender = "session end"
            for j in range(si + 1, len(evs)):
                e = evs[j]
                if e["k"] == "cmd" and e["name"] not in BENIGN_CMDS:
                    end = j
                    ender = f"{e['name']} {e['args'][:80]}"
                    break
                if e["k"] == "tool" and e["name"] == "Skill" and (e.get("skill") or "").startswith("dev:"):
                    end = j
                    ender = f"Skill {e.get('skill')} {e.get('args','')[:60]}"
                    break
            win = evs[si:end]
            ver = next((e["ver"] for e in win[1:4] if e["k"] == "meta" and e.get("ver")), None)
            runs.append({"folder": folder, "file": rel.name, "start": evs[si]["ts"],
                         "via": "cmd" if evs[si]["k"] == "cmd" else "skill",
                         "args": evs[si]["args"], "ver": ver, "ender": ender, "events": win})
    runs.sort(key=lambda r: r["start"])
    (OUT / "runs.json").write_text(json.dumps(runs, indent=1))
    rd = OUT / "runs"
    rd.mkdir(exist_ok=True)
    for n, r in enumerate(runs, 1):
        r["n"] = n
        lines = [f"# run {n}: {r['folder']} {r['start']} via={r['via']} ver={r['ver']} file={r['file']}",
                 f"# args: {r['args']}", f"# ended by: {r['ender']}", ""]
        asked = {}
        for e in r["events"]:
            k = e["k"]
            if k == "op":
                lines.append(f"\n>>> OPERATOR {e['ts']}\n{e['text']}\n<<<")
            elif k == "asst":
                lines.append(f"\n--- ASSISTANT {e['ts']} ({len(e['text'].split())} w)\n{e['text']}")
            elif k == "tool":
                if e["name"] == "Bash" and "git" in e.get("cmd", "") and "commit" in e.get("cmd", ""):
                    lines.append(f"[COMMIT {e['ts']}] {e['cmd'][:300]!r}")
                elif e["name"] == "AskUserQuestion":
                    asked[e["id"]] = True
                    lines.append(f"[ASK {e['ts']}] {json.dumps(e['input'])[:1500]}")
                elif e["name"] in ("Agent", "Task"):
                    lines.append(f"[AGENT {e['ts']}] {e.get('desc')}")
            elif k == "result" and e["id"] in asked:
                lines.append(f"[ASK-ANSWER {e['ts']}] {str(e['text'])[:1500]}")
            elif k == "tool" and e["name"] == "Skill":
                lines.append(f"[SKILL {e['ts']}] {e.get('skill')} {e.get('args','')[:400]}")
            elif k == "cmd":
                lines.append(f"[CMD {e['ts']}] {e['name']} {e['args'][:200]}")
            elif k == "interrupt":
                lines.append(f"[INTERRUPT {e['ts']}]")
        (rd / f"{n:02d}_{r['via']}_{r['folder']}_{r['start'][:10]}.txt").write_text("\n".join(lines))
        nop = sum(1 for e in r["events"] if e["k"] == "op")
        print(n, r["via"], r["folder"], r["start"], r["ver"], "ops", nop, "|", r["args"][:60], "| end:",
              r["ender"][:50])


if __name__ == "__main__":
    main()
