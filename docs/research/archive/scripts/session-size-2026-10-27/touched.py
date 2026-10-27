import json, sys, statistics as st
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp, slice_cost as sc
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session']
xs=sorted(r['peak'] for r in rows); p95=xs[int(len(xs)*.95)]
def touched(path):
    rep=tp.replay(Path(path)); files=set()
    for t in rep['turns']:
        for r in t['tools']:
            if r['name'] in tp.WRITE_TOOLS: files.add(r['key'])
            elif r['name']=='Bash':
                for p in tp._bash_edit_targets(r['cmd']): files.add(p)
    return len({f for f in files if '/slices/' not in f and '/tmp/' not in f})
cw=[r for r in rows if r['role']=='code-writer']
for r in cw: r['touched']=touched(r['transcript'])
print("code-writer, all repos: peak by files the session edited (spec repo excluded)")
for lo,hi in ((0,3),(3,6),(6,10),(10,15),(15,25),(25,999)):
    b=[r for r in cw if lo<=r['touched']<hi]
    pk=[r['peak'] for r in b]
    print(f"  files {lo:>2}-{hi:<3} n={len(b):4} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk):3} ({sum(p>=p95 for p in pk)/len(b):4.0%})")
# cost share
tot=0; top=0
for r in rows:
    c=sc.Conv(r['session'],r['role'],None,'session',Path(r['transcript'])); sc.scan_transcript(Path(r['transcript']),c)
    tot+=c.cost(); top+=c.cost() if r['peak']>=p95 else 0
print(f"top-5% sessions: {top/tot:.1%} of headless-session spend (${top:,.0f} of ${tot:,.0f})")
