#!/usr/bin/env python3
"""Render a Claude Code transcript (.jsonl) as readable text.

usage: render.py <transcript.jsonl> [--full] [--max-text N] [--max-result N]
Prints each assistant turn: timestamp, thinking (trimmed), text, tool calls with key args; tool
results trimmed. Sub-agent transcripts are not followed."""
import json, sys, re
args = sys.argv[1:]
full = '--full' in args
def opt(name, default):
    if name in args:
        return int(args[args.index(name)+1])
    return default
MAX_TEXT = opt('--max-text', 100000 if full else 1500)
MAX_RES = opt('--max-result', 100000 if full else 400)
MAX_THINK = opt('--max-think', 100000 if full else 600)
path = [a for a in args if a.endswith('.jsonl')][0]
def trim(s, n):
    s = s or ''
    return s if len(s) <= n else s[:n] + f' …[{len(s)-n} more chars]'
def ts(o):
    return (o.get('timestamp') or '')[11:19]
turn = 0
last_id = None
with open(path) as f:
    for line in f:
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get('type')
        m = o.get('message') or {}
        c = m.get('content')
        if t == 'user':
            if isinstance(c, str):
                print(f'\n=== USER {ts(o)} ===\n{trim(c, MAX_TEXT)}')
            elif isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get('type') == 'text':
                        print(f'\n=== USER {ts(o)} ===\n{trim(b["text"], MAX_TEXT)}')
                    elif b.get('type') == 'tool_result':
                        rc = b.get('content')
                        if isinstance(rc, list):
                            rc = '\n'.join(x.get('text', '') for x in rc if isinstance(x, dict))
                        err = ' [ERROR]' if b.get('is_error') else ''
                        print(f'  -> result{err}: {trim(str(rc), MAX_RES)}')
        elif t == 'assistant':
            if m.get('model') == '<synthetic>':
                continue
            if isinstance(c, list):
                mid = m.get('id')
                new_turn = mid != last_id
                last_id = mid
                if new_turn:
                    turn += 1
                usage = m.get('usage') or {}
                hdr = f'\n--- ASSISTANT turn {turn} {ts(o)} out={usage.get("output_tokens","?")} ---'
                printed_hdr = not new_turn
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get('type')
                    if bt == 'thinking':
                        if not printed_hdr:
                            print(hdr); printed_hdr = True
                        print(f'  [thinking] {trim(b.get("thinking",""), MAX_THINK)}')
                    elif bt == 'text':
                        if not printed_hdr:
                            print(hdr); printed_hdr = True
                        print(f'  [text] {trim(b["text"], MAX_TEXT)}')
                    elif bt == 'tool_use':
                        if not printed_hdr:
                            print(hdr); printed_hdr = True
                        inp = b.get('input') or {}
                        name = b.get('name')
                        if name == 'Bash':
                            arg = inp.get('command', '')
                        elif name in ('Read', 'Write', 'Edit', 'MultiEdit'):
                            arg = inp.get('file_path', '')
                            if name == 'Write':
                                arg += '\n' + trim(inp.get('content', ''), MAX_RES)
                            if name == 'Edit':
                                arg += '\n    old: ' + trim(inp.get('old_string', ''), 200) + '\n    new: ' + trim(inp.get('new_string', ''), 300)
                        elif name in ('Grep', 'Glob'):
                            arg = json.dumps({k: v for k, v in inp.items() if k in ('pattern', 'path', 'glob')})
                        elif name in ('Agent', 'Task'):
                            arg = f"[{inp.get('subagent_type','')}] {trim(inp.get('prompt',''), MAX_RES)}"
                        else:
                            arg = trim(json.dumps(inp), MAX_RES)
                        print(f'  [tool {name}] {trim(arg, MAX_RES)}')
