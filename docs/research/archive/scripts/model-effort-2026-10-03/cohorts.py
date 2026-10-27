#!/usr/bin/env python3
"""Run-phase numbers per slice and per cohort (model × effort), from state.json + transcripts."""
import json, glob, os, sys, collections, statistics as st
sys.path.insert(0, '/work/AIWorkflow/plugins/dev/tools')
import slice_cost
SPECS = ['/work/scratch/AnsibleSpecs', '/work/scratch/KubeCoderSpecs', '/work/scratch/FieldnotesAppSpecs', '/home/ubuntu/model-read-240/240_timer_overflow_slots']
USAGE = slice_cost.USAGE_KEYS

def scan(path):
    """turns, cost, model, effort, out tokens, first/last ts, tool calls, edits"""
    seen=set(); tok=collections.defaultdict(lambda: collections.Counter()); turns=0; effort=None; model=None
    tools=collections.Counter(); out=0
    try: f=open(path)
    except OSError: return None
    with f:
        for line in f:
            try:o=json.loads(line)
            except: continue
            if o.get('type')!='assistant': continue
            m=o.get('message') or {}
            if m.get('model')=='<synthetic>': continue
            effort = o.get('effort') or effort
            model = m.get('model') or model
            for b in m.get('content') or []:
                if isinstance(b,dict) and b.get('type')=='tool_use': tools[b.get('name')]+=1
            mid=m.get('id'); u=m.get('usage')
            if not u or (mid and mid in seen): continue
            seen.add(mid); turns+=1
            for k,uk in USAGE.items(): tok[m.get('model')][k]+=u.get(uk,0) or 0
            out+=u.get('output_tokens',0) or 0
    cost=sum(slice_cost.cost_for(mm,t) for mm,t in tok.items())
    return dict(turns=turns,cost=cost,model=model,effort=effort,out=out,tools=sum(tools.values()),edits=tools['Edit']+tools['Write']+tools['MultiEdit'],bash=tools['Bash'],agents=tools['Agent']+tools['Task'])

rows=[]
for spec in SPECS:
    for d in sorted(glob.glob(f'{spec}/slices/completed/*/'))+([spec+'/'] if spec.endswith('slots') and os.path.exists(spec+'/state.json') else []):
        sp=os.path.join(d,'state.json')
        if not os.path.exists(sp): continue
        s=json.load(open(sp))
        if not s.get('plugin_version'): continue
        h=s.get('history',[])
        if not h: continue
        name=os.path.basename(d.rstrip('/'))
        # per phase
        byphase=collections.defaultdict(list)
        for r in h:
            if r.get('role') in ('code-writer','code-reviewer'): byphase[r['phase']].append(r)
        if not byphase: continue
        rec=dict(spec=os.path.basename(spec.rstrip('/'))[:4], slice=name[:26], ver=s['plugin_version'], date=h[0]['ts'][:10], phases=[])
        for ph,rs in byphase.items():
            w1=[r for r in rs if r['role']=='code-writer' and r.get('round')==1]
            v1=[r for r in rs if r['role']=='code-reviewer' and r.get('round')==1]
            if not w1 or not v1: continue
            ws=scan(w1[0].get('transcript') or ''); vs=scan(v1[0].get('transcript') or '')
            if not ws or not vs: continue
            rr=os.path.join(d,'phases',f'P{ph}','review_result_r1.json')
            blocking=advisory=None
            if os.path.exists(rr):
                try:
                    j=json.load(open(rr)); fs=j.get('findings') or []
                    blocking=sum(1 for x in fs if x.get('impact')=='blocking'); advisory=len(fs)-blocking
                except Exception: pass
            nrounds=max(r.get('round',1) for r in rs if r['role']=='code-writer')
            fix_cost=sum((scan(r.get('transcript') or '') or {}).get('cost',0) for r in rs if r['role']=='code-writer' and r.get('round',1)>1)
            rec['phases'].append(dict(ph=ph, w_dur=w1[0].get('duration_s'), w_turns=ws['turns'], w_cost=ws['cost'], w_out=ws['out'], w_edits=ws['edits'], w_agents=ws['agents'],
                                      v_dur=v1[0].get('duration_s'), v_turns=vs['turns'], v_cost=vs['cost'], v_out=vs['out'], v_outcome=v1[0].get('outcome'),
                                      blocking=blocking, advisory=advisory, rounds=nrounds, fix_cost=fix_cost, model=ws['model'], effort=ws['effort']))
        if rec['phases']:
            rec['model']=rec['phases'][0]['model']; rec['effort']=rec['phases'][0]['effort']
            rows.append(rec)

def cohort(r):
    m=(r['model'] or '').replace('claude-',''); return f"{m}/{r['effort']}"
mode=sys.argv[1] if len(sys.argv)>1 else 'slices'
if mode=='slices':
    print(f"{'spec':4} {'slice':26} {'ver':6} {'date':10} {'cohort':16} {'ph':>2} {'r1blk':>5} {'rnds>1':>6} {'w_turn':>6} {'w_min':>5} {'w_$':>5} {'v_turn':>6} {'v_min':>5} {'v_$':>5} {'fix$':>5}")
    for r in rows:
        ps=r['phases']; n=len(ps)
        blk=sum(1 for p in ps if p['blocking']); rn=sum(1 for p in ps if p['rounds']>1)
        print(f"{r['spec']:4} {r['slice']:26} {r['ver']:6} {r['date']:10} {cohort(r):16} {n:>2} {blk:>5} {rn:>6} {st.median([p['w_turns'] for p in ps]):>6.0f} {st.median([p['w_dur'] or 0 for p in ps])/60:>5.1f} {st.median([p['w_cost'] for p in ps]):>5.2f} {st.median([p['v_turns'] for p in ps]):>6.0f} {st.median([p['v_dur'] or 0 for p in ps])/60:>5.1f} {st.median([p['v_cost'] for p in ps]):>5.2f} {sum(p['fix_cost'] for p in ps):>5.2f}")
else:
    groups=collections.defaultdict(list)
    for r in rows:
        if r['date']<'2026-09-01': continue   # 0.9.12+ only: the plugin confound is smaller
        for p in r['phases']: groups[cohort(r)].append(p)
    print(f"{'cohort':16} {'phases':>6} {'r1blk%':>6} {'rnds>1%':>7} {'w_turn':>6} {'w_min':>5} {'w_$':>5} {'w_out':>6} {'w_edit':>6} {'v_turn':>6} {'v_min':>5} {'v_$':>5} {'v_out':>6} {'adv':>4} {'fix$/ph':>7}")
    for c,ps in groups.items():
        n=len(ps); known=[p for p in ps if p['blocking'] is not None]
        print(f"{c:16} {n:>6} {100*sum(1 for p in known if p['blocking'])/max(1,len(known)):>6.0f} {100*sum(1 for p in ps if p['rounds']>1)/n:>7.0f} "
              f"{st.median([p['w_turns'] for p in ps]):>6.0f} {st.median([p['w_dur'] or 0 for p in ps])/60:>5.1f} {st.median([p['w_cost'] for p in ps]):>5.2f} {st.median([p['w_out'] for p in ps]):>6.0f} {st.median([p['w_edits'] for p in ps]):>6.0f} "
              f"{st.median([p['v_turns'] for p in ps]):>6.0f} {st.median([p['v_dur'] or 0 for p in ps])/60:>5.1f} {st.median([p['v_cost'] for p in ps]):>5.2f} {st.median([p['v_out'] for p in ps]):>6.0f} {st.mean([p['advisory'] for p in known]) if known else 0:>4.1f} {sum(p['fix_cost'] for p in ps)/n:>7.2f}")
    print()
    for c,ps in groups.items():
        print(c, 'writer turns p25/p50/p75/p90:', [round(x) for x in st.quantiles([p['w_turns'] for p in ps], n=20)[4::5]][:4], ' writer $ p25/50/75/90:', [round(x,2) for x in st.quantiles([p['w_cost'] for p in ps], n=20)[4::5]][:4], ' reviewer out p50:', st.median([p['v_out'] for p in ps]))
