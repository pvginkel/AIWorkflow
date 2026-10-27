import json, sys, statistics as st
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import turn_profile as tp
d=json.load(open('causes.json'))
def scan(path):
    """identical read repeated with no edit of that path in between (Read: path+offset+limit; Bash: same command)."""
    uses={}; seq=[]
    for line in open(path, errors='replace'):
        try: o=json.loads(line)
        except: continue
        if o.get('type') not in ('assistant','user'): continue
        m=o.get('message') or {}; c=m.get('content')
        if not isinstance(c,list): continue
        for b in c:
            if not isinstance(b,dict): continue
            if b.get('type')=='tool_use' and b.get('id') not in uses:
                uses[b['id']]=(b.get('name'), b.get('input') or {})
            elif b.get('type')=='tool_result' and b.get('tool_use_id') in uses:
                name,inp=uses.pop(b['tool_use_id'])
                cc=b.get('content'); n=len(cc) if isinstance(cc,str) else sum(len(x.get('text','')) for x in cc or [] if isinstance(x,dict))
                seq.append((name,inp,n))
    last_read={}; edited_since=set(); red=0; reads=0
    for name,inp,n in seq:
        if name in ('Edit','Write','MultiEdit'):
            edited_since.add(str(Path(inp.get('file_path','')).name)); continue
        if name=='Bash':
            cmd=inp.get('command') or ''
            for p in tp._bash_edit_targets(cmd): edited_since.add(Path(p).name)
            if tp.tool_class('Bash',cmd)!='cat/sed(read)': continue
            key=('B',cmd); paths=[Path(p).name for p in tp.bash_read_paths(cmd)]
        elif name=='Read':
            key=('R',inp.get('file_path'),inp.get('offset'),inp.get('limit')); paths=[Path(inp.get('file_path','')).name]
        else: continue
        reads+=n
        if key in last_read and not any(p in edited_since for p in paths):
            red+=n
        last_read[key]=1
        for p in paths: edited_since.discard(p)
    return red/3.6, reads/3.6
for role in ('code-writer','doc-writer','plan-writer'):
    for grp in ('top','ref'):
        sel=[s for s in d[grp] if s['role']==role]
        r=[scan(s['transcript']) for s in sel]
        print(f"{grp} {role:12} redundant identical re-reads median {st.median(x[0] for x in r)/1e3:.1f}k, mean {st.mean(x[0] for x in r)/1e3:.1f}k of {st.mean(x[1] for x in r)/1e3:.0f}k read; sessions with >10k: {sum(x[0]>10000 for x in r)}/{len(r)}")

def detail(path):
    uses={}; seq=[]
    for line in open(path, errors='replace'):
        try: o=json.loads(line)
        except: continue
        if o.get('type') not in ('assistant','user'): continue
        m=o.get('message') or {}; c=m.get('content')
        if not isinstance(c,list): continue
        for b in c:
            if b.get('type')=='tool_use' and b.get('id') not in uses: uses[b['id']]=(b.get('name'), b.get('input') or {}, o.get('timestamp'))
            elif b.get('type')=='tool_result' and b.get('tool_use_id') in uses:
                name,inp,ts=uses.pop(b['tool_use_id']); cc=b.get('content'); n=len(cc) if isinstance(cc,str) else sum(len(x.get('text','')) for x in cc or [] if isinstance(x,dict))
                seq.append((name,inp,n,ts))
    first={}; out=[]
    for i,(name,inp,n,ts) in enumerate(seq):
        if name=='Bash' and tp.tool_class('Bash',inp.get('command') or '')=='cat/sed(read)': key=inp['command']
        elif name=='Read': key=(inp.get('file_path'),inp.get('offset'),inp.get('limit'))
        else: continue
        if key in first and n>3000: out.append((first[key], i, n, str(key)[:120]))
        first.setdefault(key, i)
    return out, len(seq)
if __name__=='__main__' and len(sys.argv)>1:
    sel=[s for s in d['top'] if s['role']=='code-writer']
    sel=sorted(sel, key=lambda s:-scan(s['transcript'])[0])[:6]
    for s in sel:
        out,n=detail(s['transcript'])
        print(s['slice'], 'P'+str(s['phase']), s['transcript'].split('/')[-1], f"{n} tool calls")
        for a,b,c,k in out[:6]: print(f"   call {a:3} -> again at {b:3}: {c//1000}k chars  {k}")
