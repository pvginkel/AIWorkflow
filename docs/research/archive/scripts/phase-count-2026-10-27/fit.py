import json, random, statistics as st, sys
exec(open("report2.py").read().split("b = [s for s in S if s[\"review_lines\"]]")[0].split("print(f\"\\n{'phases'")[0].replace('print(F_IN, "kept", len(S))', ''))
def ols(X, y):
    n, k = len(X), len(X[0])
    A = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] + [sum(X[r][i] * y[r] for r in range(n))] for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i])); A[i], A[p] = A[p], A[i]
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]; A[r] = [a - f * c for a, c in zip(A[r], A[i])]
    return [A[i][k] / A[i][i] for i in range(k)]
b = [s for s in S if s["review_lines"] and s["planned"] <= 14]
rows = [([1, s["planned"], s["planned"] ** 2, s["review_lines"] / 1000], s["total"]) for s in b]
beta = ols([r[0] for r in rows], [r[1] for r in rows])
random.seed(1); boots = []
for _ in range(400):
    smp = [random.choice(rows) for _ in rows]
    try: boots.append(ols([r[0] for r in smp], [r[1] for r in smp]))
    except ZeroDivisionError: pass
ci = lambda i: (sorted(x[i] for x in boots)[10], sorted(x[i] for x in boots)[-10])
print(f"{F_IN}: n={len(b)}  total = {beta[0]:.1f} + {beta[1]:.2f}·P + {beta[2]:.3f}·P² + {beta[3]:.2f}·kLOC")
print(f"   95% CI  slice {ci(0)[0]:.1f}..{ci(0)[1]:.1f}   P {ci(1)[0]:.2f}..{ci(1)[1]:.2f}   P² {ci(2)[0]:.3f}..{ci(2)[1]:.3f}")
# cost per phase for a fixed phase size (the era's median lines/phase), by P
lpp = st.median(s["review_lines"] / s["planned"] for s in b) / 1000
print("   modelled $/phase at the era's median phase size (%.0f lines):" % (lpp * 1000),
      "  ".join(f"P={P}: {(beta[0] + beta[1]*P + beta[2]*P*P + beta[3]*lpp*P) / P:.2f}" for P in (4, 7, 10, 12, 14)))
lin = ols([[1, s["planned"], s["review_lines"] / 1000] for s in b], [s["total"] for s in b])
print("   linear-only modelled $/phase:", "  ".join(f"P={P}: {(lin[0] + lin[1]*P + lin[2]*lpp*P) / P:.2f}" for P in (4, 7, 10, 12, 14)))
print(f"   spend {sum(s['total'] for s in b):.0f} over {len(b)} slices, {sum(s['planned'] for s in b)} phases")
