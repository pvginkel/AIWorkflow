import json, sys, subprocess
from datetime import datetime
repo = '/work/scratch/pilotapp'
def stat(b, h, *paths):
    out = subprocess.run(['git', '-C', repo, 'diff', '--shortstat', f'{b}..{h}', '--', *paths], capture_output=True, text=True).stdout
    import re
    ins = int((re.search(r'(\d+) insertion', out) or [0, 0])[1]); dele = int((re.search(r'(\d+) deletion', out) or [0, 0])[1])
    return ins + dele
for d in sys.argv[1:]:
    s = json.load(open(d + '/state.json'))
    h = s['history']
    tot_lines = tot_t = 0; rows = []
    for k, p in s['phases'].items():
        l = p.get('landed') or {}
        if not l or 'PilotApp' not in l.get('root', ''): 
            if p['status'] == 'merged': rows.append((k, p['target'], None, None))
            continue
        lines = stat(l['base'], l['head'])
        test = stat(l['base'], l['head'], ':(glob)**/tests/**', ':(glob)**/*.spec.ts', ':(glob)**/test_*.py')
        t = sum(r.get('duration_s') or 0 for r in h if r['phase'] == k)
        rows.append((k, p['target'], lines, t)); tot_lines += lines; tot_t += t
    print(s['slice'], f"lines={tot_lines} phase-time={tot_t/3600:.1f}h  min/100 lines={tot_t/60/max(tot_lines,1)*100:.1f}")
    print('   ', ' '.join(f"P{k}:{lines}l/{(t or 0)//60}m" for k, tg, lines, t in rows))
