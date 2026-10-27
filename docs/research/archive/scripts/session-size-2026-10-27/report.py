import json, statistics as st
from collections import Counter, defaultdict
d = json.load(open("causes.json"))
print("p95", d["p95"])
def summ(sel, label):
    g = Counter(); base = []; last = []; turns = []; ups = []; rr = []
    for s in sel:
        g.update(s["grow"]); base.append(s["base"]); last.append(s["last"]); turns.append(s["turns"]); ups.append(s["user_prompts"]); rr.append(s["reread_tok"])
    n = len(sel); tot = sum(g.values())
    print(f"--- {label}: n={n} median peak {st.median(last)/1e3:.0f}k base {st.median(base)/1e3:.0f}k turns {st.median(turns):.0f} user-msgs {st.median(ups):.0f} reread≈{st.median(rr)/1e3:.0f}k")
    for k, v in g.most_common(14):
        print(f"   {k:42} {v/n/1e3:7.1f}k/session  {v/tot:5.1%}")
for role in ("code-writer", "doc-writer", "plan-writer", "test-agent"):
    summ([s for s in d["top"] if s["role"] == role], f"TOP {role}")
    summ([s for s in d["ref"] if s["role"] == role], f"REF {role}")
