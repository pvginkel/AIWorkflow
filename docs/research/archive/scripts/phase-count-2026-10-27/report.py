import json, statistics as st
from collections import Counter
S = json.load(open("slices.json"))
print("projects:", Counter(s["project"] for s in S), " plan_created<09-22:", sum(s["plan_created"] < "2026-09-22" for s in S),
      " old-model share>5%:", sum(s["old_model_share"] > .05 for s in S), " missing transcripts:", sum(s["missing"] > 0 for s in S))
S = [s for s in S if s["old_model_share"] <= .05 and s["planned"] > 0]
print("kept", len(S), "| planned phases:", sorted(s["planned"] for s in S))
B = ((1, 4), (5, 7), (8, 10), (11, 14), (15, 99))
K = ("plan", "phase", "appended", "consult", "test", "doc", "wrap-up", "run-orch", "other")
def band(lo, hi): return [s for s in S if lo <= s["planned"] <= hi]
print(f"\n{'phases':8}{'n':>3}{'med $':>8}{'$/phase':>9}{'pooled':>8} | per phase, pooled: " + " ".join(f"{k:>8}" for k in K))
for lo, hi in B:
    b = band(lo, hi)
    if not b: continue
    ph = sum(s["planned"] for s in b)
    print(f"{lo:>2}-{hi if hi < 99 else '+':<5}{len(b):>3}{st.median(s['total'] for s in b):>8.0f}"
          f"{st.median(s['total'] / s['planned'] for s in b):>9.2f}{sum(s['total'] for s in b) / ph:>8.2f} | "
          + " ".join(f"{sum(s['cost'].get(k, 0) for s in b) / ph:>8.2f}" for k in K))
print("\nfixed per slice (plan + consult + test + doc + wrap-up + run-orch + other), median $ by band:")
F = ("plan", "consult", "test", "doc", "wrap-up", "run-orch", "other")
for lo, hi in B:
    b = band(lo, hi)
    if not b: continue
    print(f"  {lo:>2}-{hi if hi < 99 else '+':<3} fixed/slice {st.median(sum(s['cost'].get(k,0) for k in F) for s in b):6.2f}  "
          + "  ".join(f"{k} {st.median(s['cost'].get(k, 0) for s in b):5.2f}" for k in F)
          + f"   phase-work/phase {st.median((s['cost'].get('phase',0)+s['cost'].get('appended',0)) / s['planned'] for s in b):5.2f}")
print("\nwhere diff lines are measurable: $ per 100 lines")
for lo, hi in B:
    b = [s for s in band(lo, hi) if s["lines"]]
    if not b: continue
    print(f"  {lo:>2}-{hi if hi < 99 else '+':<3} n={len(b):2}  lines/phase {st.median(s['lines'] / s['planned'] for s in b):5.0f}  "
          f"$/100 lines median {st.median(s['total'] / s['lines'] * 100 for s in b):5.2f} pooled {sum(s['total'] for s in b) / sum(s['lines'] for s in b) * 100:5.2f}")
