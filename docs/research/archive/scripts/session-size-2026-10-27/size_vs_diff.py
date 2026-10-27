import json, re, subprocess, statistics as st
from collections import Counter
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session']
xs=sorted(r['peak'] for r in rows); p95=xs[int(len(xs)*.95)]
ROOT={'/work/KubeCoder':'/work/scratch/KubeCoder','/work/PilotApp':'/work/scratch/pilotapp','/work/Ansible':'/work/scratch/Ansible'}
cache={}
def phase_diff(sd, ph):
    s=cache.setdefault(sd, json.load(open(sd+'/state.json')))
    p=(s.get('phases') or {}).get(str(ph)) or {}
    l=p.get('landed') or {}
    repo=ROOT.get(l.get('root'))
    if not repo or not l.get('base') or not l.get('head'): return None
    out=subprocess.run(['git','-C',repo,'diff','--shortstat',l['base'],l['head']],capture_output=True,text=True).stdout
    m=re.search(r"(\d+) files? changed(?:, (\d+) insertions?)?(?:, (\d+) deletions?)?",out)
    if not m: return None
    return int(m.group(2) or 0)+int(m.group(3) or 0), int(m.group(1))
cw=[r for r in rows if r['role'] in ('code-writer','code-reviewer')]
for r in cw:
    r['diff']=phase_diff(r['slice_dir'], r['phase'])
json.dump(cw, open('cw_diff.json','w'))
for role in ('code-writer','code-reviewer'):
    b0=[r for r in cw if r['role']==role and r['diff']]
    print(f"{role}: {len(b0)} sessions with a measurable phase diff")
    for lo,hi in ((0,100),(100,300),(300,600),(600,1000),(1000,2000),(2000,4000),(4000,10**9)):
        b=[r for r in b0 if lo<=r['diff'][0]<hi]
        if not b: continue
        pk=[r['peak'] for r in b]
        print(f"  diff {lo:>5}-{hi if hi<10**9 else '':<5} n={len(b):4} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk):3} ({sum(p>=p95 for p in pk)/len(b):5.1%})")
    top=[r for r in b0 if r['peak']>=p95]
    if top: print("  top5% median diff", st.median(r['diff'][0] for r in top), "files", st.median(r['diff'][1] for r in top), "| rest", st.median(r['diff'][0] for r in b0 if r['peak']<p95), st.median(r['diff'][1] for r in b0 if r['peak']<p95))
