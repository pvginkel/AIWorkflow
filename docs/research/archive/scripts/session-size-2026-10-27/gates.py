import json, sys, statistics as st, re
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session']
xs=sorted(r['peak'] for r in rows); p95=xs[int(len(xs)*.95)]
cw=[r for r in rows if r['role']=='code-writer']
for r in cw:
    rep=tp.replay(Path(r['transcript'])); T=[t for t in rep['turns'] if t['model']!='<synthetic>']
    cmds=[x['cmd'] for t in T for x in t['tools'] if tp.tool_class(x['name'],x['cmd'])=='gate']
    r['gates']=len(cmds)
    r['narrow']=sum(1 for c in cmds if re.search(r"-k |::|playwright|vitest|--project \S+ -- |test_\w+\.py", c))
print("code-writer: peak by gate/test runs in the session")
for lo,hi in ((0,3),(3,6),(6,10),(10,15),(15,25),(25,999)):
    b=[r for r in cw if lo<=r['gates']<hi]
    pk=[r['peak'] for r in b]
    print(f"  runs {lo:>2}-{hi:<3} n={len(b):4} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk):3} ({sum(p>=p95 for p in pk)/len(b):4.0%})  by project {dict(Counter(r['project'] for r in b))}")
top=[r for r in cw if r['peak']>=p95]
print("top-5% code-writers: median runs", st.median(r['gates'] for r in top), " >=12 runs:", sum(r['gates']>=12 for r in top), "of", len(top))
import collections
exec(open('touched.py').read().split("cw=[r for r")[0].split("rows=")[0])
def touched(path):
    rep=tp.replay(Path(path)); files=set()
    for t in rep['turns']:
        for x in t['tools']:
            if x['name'] in tp.WRITE_TOOLS: files.add(x['key'])
            elif x['name']=='Bash':
                for p in tp._bash_edit_targets(x['cmd']): files.add(p)
    return len({f for f in files if '/slices/' not in f and '/tmp/' not in f})
for r in cw: r['touched']=touched(r['transcript'])
print("\ntop-5% rate, files edited (rows) x test runs (cols)")
fb=((0,6),(6,15),(15,999)); gb=((0,6),(6,12),(12,999))
print(" "*12+"".join(f"{f'runs {a}-{b if b<999 else chr(43)}':>18}" for a,b in gb))
for fa,fz in fb:
    line=f"files {fa}-{fz if fz<999 else '+':<4}"
    for ga,gz in gb:
        b=[r for r in cw if fa<=r['touched']<fz and ga<=r['gates']<gz]
        line+=f"{(f'{sum(r[chr(112)+chr(101)+chr(97)+chr(107)]>=p95 for r in b)}/{len(b)}'):>18}"
    print(line)
# red share of runs in heavy-gate sessions
red=re.compile(r"\bfailed\b|FAILED|\berror\b|Error:|✘|\bfail\b", re.I)
heavy=[r for r in cw if r['gates']>=12]
reds=[];fulls=[]
for r in heavy:
    rep=tp.replay(Path(r['transcript']))
    runs=[x for t in rep['turns'] for x in t['tools'] if tp.tool_class(x['name'],x['cmd'])=='gate']
    reds.append(sum(bool(red.search(x['res_head'])) for x in runs)/len(runs))
    fulls.append(sum(bool(re.search(r"kc project test", x['cmd'])) for x in runs)/len(runs))
print(f"\nsessions with >=12 runs: n={len(heavy)}; median share of runs whose output head looks red {st.median(reds):.0%}; share that are full 'kc project test' {st.median(fulls):.0%}")
