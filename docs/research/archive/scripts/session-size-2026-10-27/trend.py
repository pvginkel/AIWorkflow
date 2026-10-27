import json, sys, statistics as st, re
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session' and r['role']=='code-writer']
def period(s):
    m=s[5:7]; d=int(s[8:10]); return f"{m}-{'a' if d<16 else 'b'}"
for r in rows:
    rep=tp.replay(Path(r['transcript'])); T=[t for t in rep['turns'] if t['model']!='<synthetic>']
    files=set()
    for t in T:
        for x in t['tools']:
            if x['name'] in tp.WRITE_TOOLS: files.add(x['key'])
            elif x['name']=='Bash': files.update(tp._bash_edit_targets(x['cmd']))
    r['files']=len({f for f in files if '/slices/' not in f and '/tmp/' not in f})
    r['gates']=sum(1 for t in T for x in t['tools'] if tp.tool_class(x['name'],x['cmd'])=='gate')
    r['base']=T[0]['ctx'] if T else 0; r['nturns']=len(T); r['think']=sum(t['think'] for t in T); r['out']=sum(t['out'] for t in T)
    fe=tp.first_edit_turn(T); r['ctx_fe']=T[(fe or len(T))-1]['ctx'] if T else 0
json.dump(rows, open('cw_trend.json','w'))
g=defaultdict(list)
for r in rows: g[period(r['start'])].append(r)
print(f"{'period':7}{'n':>5}{'peak':>7}{'base':>7}{'ctx@1st edit':>13}{'turns':>7}{'files':>6}{'tests':>6}{'out':>7}{'peak/file':>10}  models")
for p in sorted(g):
    b=g[p]; m=lambda k: st.median(r[k] for r in b)
    ppf=st.median(r['peak']/max(r['files'],1) for r in b if r['files']>=3)
    mods=defaultdict(int)
    for r in b: mods[r['model']]+=1
    print(f"{p:7}{len(b):>5}{m('peak')/1e3:>6.0f}k{m('base')/1e3:>6.0f}k{m('ctx_fe')/1e3:>12.0f}k{m('nturns'):>7.0f}{m('files'):>6.0f}{m('gates'):>6.0f}{m('out')/1e3:>6.0f}k{ppf/1e3:>9.0f}k  {dict(mods)}")
# same-size comparison: files 6-15
print("\nfiles 6-15 only:")
for p in sorted(g):
    b=[r for r in g[p] if 6<=r['files']<15]
    if len(b)<5: continue
    print(f"  {p} n={len(b):3} median peak {st.median(r['peak'] for r in b)/1e3:.0f}k base {st.median(r['base'] for r in b)/1e3:.0f}k turns {st.median(r['nturns'] for r in b):.0f} tests {st.median(r['gates'] for r in b):.0f} out {st.median(r['out'] for r in b)/1e3:.0f}k")
