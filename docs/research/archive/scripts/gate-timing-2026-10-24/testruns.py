import json, sys, re, collections
from datetime import datetime
def T(t): return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
TEST = re.compile(r'kc project test|pytest|playwright|pnpm (run )?test|vitest')
d = sys.argv[1]
s = json.load(open(d + '/state.json'))
for r in s['history']:
    if r['role'] not in ('code-writer', 'code-reviewer') or not r.get('transcript'): continue
    uses = {}; rows = []
    recs = [json.loads(l) for l in open(r['transcript'])]
    for i, x in enumerate(recs):
        if not x.get('timestamp'): continue
        m = x.get('message') or {}
        c = m.get('content') if isinstance(m.get('content'), list) else []
        for b in c:
            if b.get('type') == 'tool_use' and b['name'] == 'Bash' and TEST.search(b['input'].get('command', '')):
                uses[b['id']] = (T(x['timestamp']), b['input']['command'], b['input'].get('run_in_background'))
            if b.get('type') == 'tool_result' and b.get('tool_use_id') in uses:
                t0, cmd, bg = uses.pop(b['tool_use_id'])
                full = bool(re.search(r'kc project test --project \w+\s*(2>&1|\||;|&&|$|>)', cmd)) and '-k' not in cmd
                rows.append(('F' if full else 't') + ('bg' if bg else '') + f"{(T(x['timestamp'])-t0)/60:.1f}")
    print(f"P{r['phase']:>2} {r['role'][5:]:8s} r{r['round']} {r['duration_s']/60:4.0f}m  runs={len(rows)}  " + ' '.join(rows))
