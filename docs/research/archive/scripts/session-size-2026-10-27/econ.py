import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import slice_cost as sc
cw=json.load(open('cw_diff.json'))
xs=sorted(r['peak'] for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session'); p95=xs[int(len(xs)*.95)]
ph=defaultdict(lambda: {'cost':0,'diff':None,'sessions':0,'rounds':0,'peak':0})
for r in cw:
    if not r['diff']: continue
    c=sc.Conv(r['session'],r['role'],r['phase'],'session',Path(r['transcript'])); sc.scan_transcript(Path(r['transcript']),c)
    k=(r['slice_dir'],r['phase']); p=ph[k]; p['cost']+=c.cost(); p['diff']=r['diff'][0]; p['sessions']+=1
    if r['role']=='code-writer': p['rounds']=max(p['rounds'], r['round'] or 1); p['peak']=max(p['peak'], r['peak'])
print("per phase (writer+reviewer sessions, all rounds), measurable phases only")
print(f"{'diff band':12}{'n':>5}{'$ med':>8}{'$/100 lines':>13}{'rounds>1':>10}{'writer peak':>13}")
for lo,hi in ((0,100),(100,300),(300,600),(600,1000),(1000,2000),(2000,10**6)):
    b=[p for p in ph.values() if lo<=p['diff']<hi]
    if not b: continue
    per=sum(p['cost'] for p in b)/sum(p['diff'] for p in b)*100
    print(f"{lo:>5}-{hi if hi<10**6 else '':<6}{len(b):>5}{st.median(p['cost'] for p in b):>8.2f}{per:>13.2f}{sum(p['rounds']>1 for p in b)/len(b):>10.0%}{st.median(p['peak'] for p in b)/1e3:>12.0f}k")
