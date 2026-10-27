import json, sys, collections
from datetime import datetime
def P(t): return datetime.fromisoformat(t)
for d in sys.argv[1:]:
    s = json.load(open(d + '/state.json'))
    h = s['history']
    start = P(s['driver']['started']) if s.get('driver') else P(s['created_at'])
    end = max(P(r['ts']) for r in h)
    if s.get('in_flight') and s['in_flight'].get('started_at'):
        end = max(end, P(s['in_flight']['started_at']))
    wall = (end - start).total_seconds()
    by = collections.Counter(); n = collections.Counter()
    for r in h:
        by[r['role']] += r.get('duration_s') or 0; n[r['role']] += 1
    busy = sum(by.values())
    ph = [k for k, p in s['phases'].items() if p['status'] == 'merged']
    rounds = sum(p['review_rounds'] for p in s['phases'].values())
    # biggest gaps between consecutive rows (end of prev -> start of next)
    rows = sorted(h, key=lambda r: r['ts'])
    gaps = []
    prev_end = start
    for r in rows:
        st = P(r['ts']).timestamp() - (r.get('duration_s') or 0)
        g = st - prev_end.timestamp()
        if g > 300: gaps.append((round(g/60), r['phase'], r['role'], r['ts'][:16]))
        prev_end = P(r['ts'])
    print(f"{s['slice']}  v{s['plugin_version']}  phases={len(ph)} rounds={rounds}  run-wall={wall/3600:.1f}h  busy={busy/3600:.1f}h  per-phase={wall/60/max(len(ph),1):.0f}m")
    print('   ' + '  '.join(f"{k}:{v/60:.0f}m/{n[k]}" for k, v in by.most_common()))
    if gaps: print('   gaps>5m:', gaps[:8])
