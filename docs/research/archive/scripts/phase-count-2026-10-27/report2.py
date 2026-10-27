import json, statistics as st
import sys
F_IN = sys.argv[1] if len(sys.argv) > 1 else "slices.json"
S = [s for s in json.load(open(F_IN)) if s["planned"] > 0 and (s["old_model_share"] <= .05 if F_IN == "slices.json" else s["old_model_share"] >= .8) and not s["missing"]]
print(F_IN, "kept", len(S))
# validation against git where fully measured
v = [(s["lines"][0], s["review_lines"]) for s in S if s["lines"][1] == s["lines"][2] and s["lines"][0]]
print("validation, slices measured both ways:", len(v), " median ratio review/git", round(st.median(b / a for a, b in v), 2))
B = ((1, 4), (5, 7), (8, 10), (11, 14), (15, 99))
F = ("plan", "consult", "test", "doc", "wrap-up", "run-orch", "other")
print(f"\n{'phases':7}{'n':>3}{'lines/slice':>12}{'lines/phase':>12}{'$ slice':>8}{'$/100 lines':>12}{'pooled':>8}{'fixed $/100':>12}{'phase-work $/100':>17}")
for lo, hi in B:
    b = [s for s in S if lo <= s["planned"] <= hi and s["review_lines"]]
    if not b: continue
    L = sum(s["review_lines"] for s in b)
    fx = sum(sum(s["cost"].get(k, 0) for k in F) for s in b); pw = sum(s["cost"].get("phase", 0) + s["cost"].get("appended", 0) for s in b)
    print(f"{lo:>2}-{hi if hi < 99 else '+':<4}{len(b):>3}{st.median(s['review_lines'] for s in b):>12.0f}{st.median(s['review_lines'] / s['planned'] for s in b):>12.0f}"
          f"{st.median(s['total'] for s in b):>8.0f}{st.median(s['total'] / s['review_lines'] * 100 for s in b):>12.2f}{sum(s['total'] for s in b) / L * 100:>8.2f}"
          f"{fx / L * 100:>12.2f}{pw / L * 100:>17.2f}")
# OLS: total = a + b*phases + c*(lines/1000)
def ols(X, y):
    n, k = len(X), len(X[0])
    XtX = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    Xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    A = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i])); A[i], A[p] = A[p], A[i]
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]; A[r] = [a - f * c for a, c in zip(A[r], A[i])]
    beta = [A[i][k] / A[i][i] for i in range(k)]
    res = [y[r] - sum(beta[i] * X[r][i] for i in range(k)) for r in range(n)]
    ss = sum(e * e for e in res); sy = sum((t - sum(y) / n) ** 2 for t in y)
    return beta, 1 - ss / sy
b = [s for s in S if s["review_lines"]]
X = [[1, s["planned"], s["review_lines"] / 1000] for s in b]
for label, key in (("total", None), ("fixed (plan+consult+test+doc+wrap-up+orch)", "fixed"), ("phase work", "phase")):
    y = [s["total"] if key is None else (sum(s["cost"].get(k, 0) for k in F) if key == "fixed" else s["cost"].get("phase", 0) + s["cost"].get("appended", 0)) for s in b]
    beta, r2 = ols(X, y)
    print(f"\nOLS {label}: ${beta[0]:.1f} per slice + ${beta[1]:.2f} per phase + ${beta[2]:.2f} per 1,000 lines  (R² {r2:.2f}, n={len(b)})")
