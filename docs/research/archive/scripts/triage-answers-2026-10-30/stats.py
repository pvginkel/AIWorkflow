import json, re, statistics
runs = json.load(open("runs.json"))
EXCL = {1: "pre-0.9.60 (0.9.54): status-document format", 4: "preflight failed, no .aiworkflowrc: no message"}
ID = re.compile(r"^\s{0,6}(?:[-*]\s+)?\**\s*(?:[A-Z]{1,4}-\d+(?:\.\d+)?[a-z]?|C\d+|chat-\d+|R\d+[a-z]?|R020|§\s?\d[\d.]*|row \d+\w*|§3 row \d+|\d{3} [A-Z]\d|J\d+|T\d+[–-]T?\d+|Q\d+ |D\d+ |\d{1,2}\s{2,}|033 \w+|034 \w+|Stage generators|§2, §9)", re.M)
SL = re.compile(r"^\s*\**\s*Slice\s+[A-Z0-9]{1,4}\b|^\s*Slice:", re.M)
Q = re.compile(r"^\s*(?:\*\*)?Q(\d+)\b|^(\d)\. \*\*", re.M)
FATES = ["Solution Known", "Operator action", "Close", "Later", "Decision:", "Fold into", "This session", "night shift", "Straightforward change", "Done in the design session", "Rulings (", "Split, then Later", "Not an item", "Own slice", "Rulings carried", "Manual sweep"]
rows = []
for n, r in enumerate(runs, 1):
    if n in EXCL: continue
    evs = r["events"]
    first_op = next((i for i, e in enumerate(evs) if e["k"] == "op"), len(evs))
    # triage message: last long assistant text before first operator turn that has a slice/Q
    cands = [e for e in evs[:first_op] if e["k"] == "asst" and len(e["text"].split()) >= 100
             and (SL.search(e["text"]) or "Q1" in e["text"])]
    if not cands:
        rows.append((n, r, None, None)); continue
    m = cands[-1] if len(cands) > 1 and n != 23 else cands[0]
    t = m["text"]
    head = re.split(r"^\s*(?:\*\*)?(?:Q1\b|1\. \*\*)", t, maxsplit=1, flags=re.M)[0]
    items = len(ID.findall(head))
    sl = len(SL.findall(head))
    qs = sorted({int(a or b) for a, b in Q.findall(t)})
    fates = [f for f in FATES if f.lower() in head.lower()]
    op = evs[first_op] if first_op < len(evs) else None
    lat = None
    if op:
        from datetime import datetime
        f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
        lat = (f(op["ts"]) - f(m["ts"])).total_seconds() / 60
    rows.append((n, r, dict(w=len(t.split()), items=items, slices=sl, q=len(qs), fates=fates, code="```" in t, ts=m["ts"]), lat))
for n, r, s, lat in rows:
    if not s: print(n, r["via"], r["folder"], r["start"][:10], "NO MESSAGE"); continue
    print(f"{n:2} {r['via']:5} {r['folder'][6:18]:12} {r['start'][:10]} w={s['w']:5} items={s['items']:3} slices={s['slices']:2} q={s['q']:2} code={int(s['code'])} lat={lat if lat is None else round(lat,1)} fates={s['fates']}")
