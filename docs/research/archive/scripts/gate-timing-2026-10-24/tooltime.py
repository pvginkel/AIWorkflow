import json, sys, re, collections
from datetime import datetime
def T(t): return datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
TEST = re.compile(r'kc project test|pytest|playwright|pnpm (run )?test|vitest|uv run.*test')
LINT = re.compile(r'kc project lint|ruff|eslint|tsc|pnpm (run )?(lint|check|typecheck)')
def session(path):
    uses = {}; res = {}; first = last = None
    for l in open(path):
        try: r = json.loads(l)
        except Exception: continue
        ts = r.get('timestamp')
        if ts:
            t = T(ts); first = first or t; last = t
        m = r.get('message') or {}
        c = m.get('content')
        if not isinstance(c, list): continue
        for x in c:
            if x.get('type') == 'tool_use':
                cmd = x['input'].get('command', '') if x['name'] == 'Bash' else ''
                bg = x['input'].get('run_in_background')
                uses[x['id']] = (t, x['name'], cmd, bg)
            elif x.get('type') == 'tool_result':
                res[x['tool_use_id']] = t
    agg = collections.Counter(); cnt = collections.Counter()
    for i, (t0, name, cmd, bg) in uses.items():
        if i not in res: continue
        d = res[i] - t0
        k = 'test' if TEST.search(cmd) else 'lint' if LINT.search(cmd) else ('bash' if name == 'Bash' else 'agent' if name in ('Agent', 'Task') else 'other-tool')
        if bg: k += '(bg)'
        agg[k] += d; cnt[k] += 1
    return (last - first) if first else 0, agg, cnt
roles = collections.defaultdict(lambda: [0, collections.Counter(), collections.Counter(), 0])
for d in sys.argv[1:]:
    s = json.load(open(d + '/state.json'))
    roles.clear()
    for r in s['history']:
        if not r.get('transcript'): continue
        try: dur, agg, cnt = session(r['transcript'])
        except FileNotFoundError: continue
        R = roles[r['role']]; R[0] += dur; R[1].update(agg); R[2].update(cnt); R[3] += 1
    print(s['slice'])
    for role, (dur, agg, cnt, n) in sorted(roles.items(), key=lambda x: -x[1][0]):
        tools = sum(agg.values())
        print(f"  {role:15s} n={n:2d} wall={dur/60:6.0f}m  model≈{(dur-tools)/60:5.0f}m  " + ' '.join(f"{k}={v/60:.0f}m/{cnt[k]}" for k, v in agg.most_common(6)))
