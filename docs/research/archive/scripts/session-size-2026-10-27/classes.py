import json, sys, statistics as st
from collections import Counter
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp, slice_cost as sc
d=json.load(open('causes.json'))
def prof(path):
    rep=tp.replay(Path(path)); turns=[t for t in rep['turns'] if t['model']!='<synthetic>']
    cl=tp.classify_turns(turns, tp.first_edit_turn(turns))
    c=Counter(x['cls'] for x in cl)
    # growth by phase of session: before first edit vs after
    fe=tp.first_edit_turn(turns) or len(turns)
    ctx_at_fe=turns[min(fe,len(turns))-1]['ctx']
    return c, len(turns), fe, ctx_at_fe, turns[-1]['ctx']
for role in ('code-writer','doc-writer','plan-writer','test-agent'):
    for grp in ('top','ref'):
        sel=[s for s in d[grp] if s['role']==role]
        C=Counter(); fes=[]; fctx=[]; lctx=[]
        for s in sel:
            c,n,fe,cf,cl=prof(s['transcript']); C.update(c); fes.append(fe); fctx.append(cf); lctx.append(cl)
        n=len(sel); T=sum(C.values())
        print(f"{grp} {role:12} n={n} turns/session {T/n:.0f}; first edit at turn {st.median(fes):.0f}, ctx there {st.median(fctx)/1e3:.0f}k -> end {st.median(lctx)/1e3:.0f}k")
        print("     "+", ".join(f"{k} {v/n:.1f}" for k,v in C.most_common(10)))
