import json, sys
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp
exec(open('touched.py').read().split("cw=[r for r")[0])
d=json.load(open('causes.json'))
by={s['session']:s for s in d['top']}
for r in rows:
    if r['role']!='code-writer' or r['peak']<p95: continue
    n=touched(r['transcript'])
    if n>=6: continue
    s=by[r['session']]; g=sorted(s['grow'].items(), key=lambda kv:-kv[1])[:3]
    rep=tp.replay(Path(r['transcript'])); T=[t for t in rep['turns'] if t['model']!='<synthetic>']
    gates=sum(1 for t in T for x in t['tools'] if tp.tool_class(x['name'],x['cmd'])=='gate')
    print(f"{r['project']:9} {r['slice'][:34]:34} P{r['phase']:<4} r{r['round']} files {n:2} peak {r['peak']//1000}k turns {s['turns']:3} gates {gates:2} | "+", ".join(f"{k[:18]} {v/1e3:.0f}k" for k,v in g))
