"""For every driver phase gate: would the writer's own last full run of the same command,
on the same tree, have answered it?  HIT = same command, ended green, and nothing in the
target repo changed from that run's start to the writer's hand-back."""
import collections, json, re, sys
from datetime import datetime
def T(t): return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
OPS = r"(?:\s*(?:$|[>|;&)'\"\n]|2>&1|<))"
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\b", re.S)
SHELL_W = [r"\bsed\s+-i", r"(?<![0-9&<>])>>?\s*(?!&)(?!/dev/null)(?!/tmp)\S", r"\btee\s+(?!/tmp)",
           r"\bgit (checkout|stash|apply|restore|reset|am|cherry-pick|mv|rm)\b",
           r"(^|[;&|(]\s*)(rm|mv|cp|touch)\s+(?!/tmp)", r"ruff format(?![^\n]*--check)",
           r"ruff check[^\n]*--fix", r"prettier[^\n]*--write", r"eslint[^\n]*--fix",
           r"pnpm (generate|format|install|add|run gen|exec openapi)", r"\buv (add|lock|sync|remove)\b"]
BODY_W = [r"open\([^)]*,\s*['\"][wa]", r"write_text\(", r"\.write\("]
def in_spec(p): return 'Specs' in p or p.startswith('/tmp')
def resolve(p, d):
    p = p.strip('\'"')
    if p.startswith('~'): return '/home/ubuntu' + p[1:]
    return p if p.startswith('/') else d.rstrip('/') + '/' + p
QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
def mods_of(b, repo, cwd):
    n, inp = b['name'], b['input']
    if n in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        p = inp.get('file_path') or inp.get('notebook_path') or ''
        return None if (in_spec(p) or not p.startswith(repo + '/')) else f"{n} {p}"
    if n != 'Bash': return None
    cmd = inp.get('command', '')
    bodies = [m.group(0) for m in HEREDOC.finditer(cmd)]
    shell = QUOTED.sub("''", HEREDOC.sub(' __HEREDOC__ ', cmd))
    d = cwd or repo; hits = []
    for seg in re.split(r"&&|\|\||;|\||\n", shell):
        seg = seg.strip()
        m = re.match(r"cd\s+(\S+)", seg)
        if m: d = resolve(m.group(1), d); continue
        m = re.match(r"git\s+-C\s+(\S+)\s+(\w+)", seg)
        gd, gverb = (resolve(m.group(1), d), m.group(2)) if m else (d, (re.match(r"git\s+(\w+)", seg) or [None, None])[1])
        targets = []
        for m in re.finditer(r"(?<![0-9&<>])>>?\s*(?!&)(\S+)", seg): targets.append(resolve(m.group(1), d))
        if re.match(r"sed\s+(-\w+\s+)*-i", seg): targets.append(resolve(seg.split()[-1], d))
        m = re.match(r"tee\s+(?:-a\s+)?(\S+)", seg)
        if m: targets.append(resolve(m.group(1), d))
        m = re.match(r"(rm|mv|cp|touch)\s+(.*)", seg)
        if m: targets += [resolve(a, d) for a in m.group(2).split() if not a.startswith('-')]
        if gverb in ('checkout', 'restore', 'stash', 'reset', 'apply', 'am', 'cherry-pick', 'mv', 'rm'): targets.append(gd + '/')
        if re.search(r"ruff format(?!.*--check)|ruff check.*--fix|prettier.*--write|eslint.*--fix|pnpm (generate|format|install|add)|\buv (add|lock|sync|remove)\b", seg):
            targets.append(d + '/')
        if '__HEREDOC__' in seg and re.match(r"(python3?|node|uv run python)\b", seg):
            body = bodies.pop(0) if bodies else ''
            if any(re.search(r, body) for r in BODY_W):
                ab = re.findall(r"(/work/[\w./-]+)", body)
                targets += ab if ab else [d + '/']
        elif '__HEREDOC__' in seg and bodies: bodies.pop(0)
        hits += [t for t in targets if t.startswith(repo + '/') and not in_spec(t) and '/dev/null' not in t]
    return ('Bash: ' + cmd.replace('\n', ' ')[:150]) if hits else None
def events(path):
    ev = []
    for l in open(path):
        try: x = json.loads(l)
        except Exception: continue
        ts = x.get('timestamp')
        if not ts: continue
        c = (x.get('message') or {}).get('content')
        if isinstance(c, str): ev.append(('text', T(ts), None, c)); continue
        if not isinstance(c, list): continue
        for b in c:
            if b.get('type') == 'tool_use': b['_cwd'] = x.get('cwd'); ev.append(('use', T(ts), b['id'], b))
            elif b.get('type') == 'tool_result':
                t = b['content'] if isinstance(b['content'], str) else ' '.join(
                    y.get('text', '') for y in b['content'] if isinstance(y, dict))
                ev.append(('res', T(ts), b['tool_use_id'], t))
            elif b.get('type') == 'text': ev.append(('text', T(ts), None, b.get('text', '')))
    return ev
def is_full(cmd, gate):
    return bool(gate) and bool(re.search(re.escape(gate) + OPS, cmd))
def green_text(t):
    if re.search(r"exit (code )?[1-9]|\b[1-9]\d* (failed|errors?)\b|did not complete", t): return False
    if re.search(r"\b\d+ passed\b|exit (code )?0\b|GREEN", t): return True
    return None
def analyse(sd):
    s = json.load(open(sd + '/state.json')); h = s['history']; rows = []
    for i, g in enumerate(h):
        if g['role'] != 'gate': continue
        k = g['phase']; ps = s['phases'][k]; comp = ps.get('target')
        repo = (ps.get('landed') or {}).get('root') or ps.get('worktree') or '/work/PilotApp'
        w = [r for r in h[:i] if r['role'] == 'code-writer' and r['phase'] == k]
        base = (s['slice'], k, g['round'], g['outcome'], g.get('duration_s') or 0)
        if not w or not w[-1].get('transcript'): rows.append(base + ('NO-WRITER', '')); continue
        try: ev = events(w[-1]['transcript'])
        except FileNotFoundError: rows.append(base + ('NO-TRANSCRIPT', '')); continue
        runs = [j for j, e in enumerate(ev) if e[0] == 'use' and e[3]['name'] == 'Bash'
                and is_full(e[3]['input'].get('command', ''), ps.get('gate_cmd'))]
        if not runs:
            other = [e[3]['input']['command'][:90] for e in ev if e[0] == 'use' and e[3]['name'] == 'Bash'
                     and 'kc project test' in e[3]['input'].get('command', '')]
            rows.append(base + ('MISS:no-full-run', ' | '.join(other[-2:]))); continue
        j = runs[-1]; gr = None
        cmd0 = ev[j][3]['input']['command']; uid = ev[j][2]
        keys = re.findall(r">>?\s*(/tmp/\S+\.(?:log|txt|out))", cmd0)
        cmdtext = {e[2]: e[3]['input'].get('command', '') for e in ev if e[0] == 'use' and e[3]['name'] == 'Bash'}
        cands = []
        for e in ev[j + 1:]:
            if e[0] == 'res' and e[2] == uid:
                m = re.search(r"background with ID: (\w+)", e[3])
                if m: keys.append(m.group(1))
                else: cands.append(e[3])
            elif e[0] == 'res' and any(k in cmdtext.get(e[2], '') for k in keys): cands.append(e[3])
            elif e[0] == 'text' and any(k in e[3] for k in keys) and 'task-notification' in e[3]: cands.append(e[3])
        for t in reversed(cands):
            v = green_text(t)
            if v is not None: gr = v; break
        mods = [m for e in ev[j + 1:] if e[0] == 'use' for m in [mods_of(e[3], repo, e[3].get('_cwd'))] if m]
        v = 'MISS:edited-after' if mods else 'HIT' if gr else 'MISS:not-green' if gr is False else '?:green-unknown'
        rows.append(base + (v, ' || '.join(mods[:3])))
    return rows
if __name__ == '__main__':
    allrows = [r for sd in sys.argv[1:] for r in analyse(sd)]
    c = collections.Counter(); secs = collections.Counter()
    for r in allrows:
        c[r[5]] += 1; secs[r[5]] += r[4]
        if '-v' in sys.argv[0:1] or True:
            print(f"{r[0][:24]:24s} P{r[1]:>2} r{r[2]} {r[3]:5s} {r[4]/60:4.1f}m  {r[5]:18s} {r[6][:260]}")
    print({k: (n, f"{secs[k]/60:.0f}m") for k, n in c.most_common()})
