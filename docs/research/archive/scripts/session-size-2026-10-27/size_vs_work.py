import json, re, statistics as st
from collections import Counter, defaultdict
from pathlib import Path
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session']
xs=sorted(r['peak'] for r in rows); p95=xs[int(len(xs)*.95)]
STAT=re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
def committed(path):
    tot=0; files=0; seen=set()
    for line in open(path, errors='replace'):
        if '"tool_result"' not in line or 'changed' not in line: continue
        o=json.loads(line)
        for b in (o.get('message') or {}).get('content') or []:
            if not isinstance(b,dict) or b.get('type')!='tool_result': continue
            c=b.get('content'); txt=c if isinstance(c,str) else ''.join(x.get('text','') for x in c or [] if isinstance(x,dict))
            if '] ' not in txt: continue   # a git commit's "[branch sha] subject" line
            for m in STAT.finditer(txt):
                key=(b.get('tool_use_id'),m.group(0))
                if key in seen: continue
                seen.add(key)
                files+=int(m.group(1)); tot+=int(m.group(2) or 0)+int(m.group(3) or 0)
    return tot, files
cw=[r for r in rows if r['role']=='code-writer']
for r in cw:
    r['lines'], r['files']=committed(r['transcript'])
json.dump(cw, open('cw_work.json','w'))
def band(lo,hi):
    return [r for r in cw if lo<=r['lines']<hi]
print("code-writer: peak by committed lines (insertions+deletions) of the session")
for lo,hi in ((0,1),(1,100),(100,300),(300,600),(600,1000),(1000,2000),(2000,10**9)):
    b=band(lo,hi)
    if not b: continue
    pk=[r['peak'] for r in b]
    print(f"  {lo:>5}-{hi if hi<10**9 else '':<5} n={len(b):4} median peak {st.median(pk)/1e3:4.0f}k  share in top5% {sum(p>=p95 for p in pk)/len(b):5.1%}")
top=[r for r in cw if r['peak']>=p95]; rest=[r for r in cw if r['peak']<p95]
print("top5% writers: median lines", st.median(r['lines'] for r in top), "files", st.median(r['files'] for r in top), " rest:", st.median(r['lines'] for r in rest), st.median(r['files'] for r in rest))
print("round of top writers", Counter(r['round'] for r in top), " all:", Counter(r['round'] for r in cw))
print("top writers by project", Counter(r['project'] for r in top), "all", Counter(r['project'] for r in cw))
# per project: peak per 100 committed lines
for p in ('KubeCoder','Ansible','PilotApp'):
    b=[r for r in cw if r['project']==p and r['lines']>=50]
    print(p, 'median lines', st.median(r['lines'] for r in b), 'median peak', st.median(r['peak'] for r in b)//1000, 'k')
