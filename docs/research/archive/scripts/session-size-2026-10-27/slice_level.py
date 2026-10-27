import json, re, subprocess, statistics as st
rows=[r for r in json.load(open('sessions.json'))['rows'] if r['kind']=='session']
xs=sorted(r['peak'] for r in rows); p95=xs[int(len(xs)*.95)]
ROOT={'/work/KubeCoder':'/work/scratch/KubeCoder','/work/PilotApp':'/work/scratch/pilotapp','/work/Ansible':'/work/scratch/Ansible'}
def slice_stats(sd):
    try: s=json.load(open(sd+'/state.json'))
    except OSError: s={}
    phases=s.get('phases') or {}
    tot=0; unknown=0
    for p in phases.values():
        l=p.get('landed') or {}; repo=ROOT.get(l.get('root'))
        if not repo or not l.get('base'): unknown+=1; continue
        out=subprocess.run(['git','-C',repo,'diff','--shortstat',l['base'],l['head']],capture_output=True,text=True).stdout
        m=re.search(r"(?:(\d+) insertions?)?\D*(?:(\d+) deletions?)?$",out.strip())
        nums=re.findall(r"(\d+) (?:insertion|deletion)",out); tot+=sum(map(int,nums))
    plan=open(sd+'/plan.md',errors='replace').read() if __import__('os').path.exists(sd+'/plan.md') else ''
    nph=len(re.findall(r"^### P\S+ — ",plan,re.M))
    return nph, tot, unknown, len(plan)
for role in ('doc-writer','plan-writer'):
    sel=[r for r in rows if r['role']==role]
    for r in sel: r['nph'],r['sdiff'],r['unk'],r['plan_chars']=slice_stats(r['slice_dir'])
    print(role)
    for lo,hi in ((0,4),(4,7),(7,10),(10,14),(14,99)):
        b=[r for r in sel if lo<=r['nph']<hi]
        if not b: continue
        pk=[r['peak'] for r in b]
        print(f"  phases {lo:>2}-{hi:<2} n={len(b):3} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk):3} ({sum(p>=p95 for p in pk)/len(b):4.0%})")
    if role=='doc-writer':
        meas=[r for r in sel if r['unk']==0 and r['sdiff']]
        for lo,hi in ((0,1000),(1000,3000),(3000,6000),(6000,10**9)):
            b=[r for r in meas if lo<=r['sdiff']<hi]
            if not b: continue
            pk=[r['peak'] for r in b]
            print(f"  slice diff {lo:>5}-{hi if hi<10**9 else '':<5} n={len(b):3} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk)} ({sum(p>=p95 for p in pk)/len(b):4.0%})")
    else:
        for lo,hi in ((0,20000),(20000,40000),(40000,60000),(60000,10**9)):
            b=[r for r in sel if lo<=r['plan_chars']<hi]
            if not b: continue
            pk=[r['peak'] for r in b]
            print(f"  final plan.md chars {lo:>5}-{hi if hi<10**9 else '':<6} n={len(b):3} median peak {st.median(pk)/1e3:4.0f}k  in top5% {sum(p>=p95 for p in pk)}")
