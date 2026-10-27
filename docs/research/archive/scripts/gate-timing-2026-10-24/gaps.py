import json, sys, re, collections
from datetime import datetime
def T(t): return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
TEST = re.compile(r'kc project test|pytest|playwright|pnpm (run )?test|vitest')
def session(path):
    recs = []
    for l in open(path):
        try: r = json.loads(l)
        except Exception: continue
        if r.get('timestamp') and r.get('type') in ('assistant', 'user', 'queue-operation', 'system'): recs.append(r)
    cmds = {}
    out = collections.Counter()
    prev = None
    for r in recs:
        t = T(r['timestamp'])
        m = r.get('message') or {}
        c = m.get('content') if isinstance(m.get('content'), list) else []
        if r['type'] == 'assistant':
            for x in c:
                if x.get('type') == 'tool_use':
                    cmds[x['id']] = (x['name'], x['input'].get('command', '') if x['name'] == 'Bash' else '', x['input'].get('run_in_background'))
        if prev is not None:
            g = t - prev
            if r['type'] == 'assistant': k = 'model'
            elif r['type'] == 'user' and any(x.get('type') == 'tool_result' for x in c):
                tid = next(x['tool_use_id'] for x in c if x.get('type') == 'tool_result')
                name, cmd, bg = cmds.get(tid, ('?', '', None))
                k = 'tool:test' if TEST.search(cmd) and not bg else 'tool:agent' if name in ('Agent', 'Task') else 'tool:other'
            else: k = 'wait/other'
            out[k] += g
        prev = t
    return out
for d in sys.argv[1:]:
    s = json.load(open(d + '/state.json'))
    roles = collections.defaultdict(collections.Counter); n = collections.Counter()
    for r in s['history']:
        if not r.get('transcript'): continue
        try: roles[r['role']].update(session(r['transcript'])); n[r['role']] += 1
        except FileNotFoundError: pass
    print(s['slice'])
    for role, c in sorted(roles.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(c.values())
        print(f"  {role:14s} n={n[role]:2d} {tot/60:5.0f}m  " + ' '.join(f"{k}={v/60:.0f}m({v/tot*100:.0f}%)" for k, v in c.most_common()))
