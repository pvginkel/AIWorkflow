# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: the improvement labels against the operator's rulings."""
import contextlib
import io
import json
import sys
from collections import Counter

src = open(__file__.replace("improve_score.py", "score.py")).read()
head = src[:src.index('own = matrix(')]
with contextlib.redirect_stdout(io.StringIO()):
    exec(head, globals())

L = json.load(open('/tmp/co/improve/labels.json'))
rows = []
for key, lab in L.items():
    rep, i = key.split(' ')
    e = ent.get((rep, i))
    if e:
        rows.append(((rep, i), lab, e, labels.get((rep, i), {})))
ruled = [r for r in rows if r[2]['fate'] in RULED]
own = [r for r in ruled if r[2]['_who'] in ('operator', 'advice')]
print(f"labelled {len(L)}, matched {len(rows)}, ruled {len(ruled)}, the operator's own rulings (advice included) {len(own)}")


def row(label, es, indent=2):
    c = Counter(r[2]['fate'] for r in es)
    n = len(es)
    if n:
        print(f"{' '*indent}{label:<40}{n:>4}  progressed {pct(c['card']+c['fix']+c['fold'], n):>5}  carded {pct(c['card']+c['fold'], n):>5}  fixed {pct(c['fix'], n):>5}  closed {pct(c['close'], n):>5}")


for title, es in (("A. the operator's own rulings", own), ("B. all rulings", ruled)):
    print(f"\n{title}")
    row("all", es)
    for a in ('benefit', 'felt', 'ground', 'change', 'size', 'product_call', 'prevents'):
        print(f"  {a}")
        for v, _ in Counter(r[1][a] for r in es).most_common():
            row(f"{v}", [r for r in es if r[1][a] == v], 4)


def route(lab, first):
    if lab['prevents'] == 'severe':
        return 'to the operator: severe'
    if lab['benefit'] == 'workflow':
        return 'fieldnotes'
    felt_now = lab['felt'] in ('every-use', 'some-uses')
    grounded = lab['ground'] in ('met-in-run', 'left-by-slice')
    known = lab['size'] in ('one-edit', 'several-places')
    if lab['ground'] == 'left-by-slice' and lab['change'] in ('remove', 'adjust') and known and lab['product_call'] == 'no':
        return 'wrap-up: does it'
    if felt_now and (grounded or lab['product_call'] == 'yes'):
        return 'to the operator'
    return 'closed'


print("\nC. the proposed treatment, against the operator's own rulings")
for rt in ('to the operator: severe', 'to the operator', 'wrap-up: does it', 'fieldnotes', 'closed'):
    row(rt, [r for r in own if route(r[1], r[3]) == rt])
closed = [r for r in own if route(r[1], r[3]) == 'closed']
picks = [r for r in own if r[2]['progressed']]
lost = [r for r in closed if r[2]['progressed']]
print(f"  closes {len(closed)} of {len(own)} ({pct(len(closed), len(own))}); of those progressed {len(lost)}; picks kept {len(picks)-len(lost)}/{len(picks)} ({pct(len(picks)-len(lost), len(picks))})")
print("  over all 89 handed over:", dict(Counter(route(r[1], r[3]) for r in rows)))

# simpler variants
def v_felt(lab):
    return 'keep' if lab['felt'] in ('every-use', 'some-uses') or lab['prevents'] == 'severe' else 'closed'
def v_felt_or_ground(lab):
    return 'keep' if lab['felt'] in ('every-use', 'some-uses') or lab['ground'] in ('met-in-run', 'left-by-slice') or lab['prevents'] == 'severe' else 'closed'
def v_no_add_hyp(lab):
    hyp = lab['felt'] in ('after-a-change', 'after-an-incident', 'not-observable')
    return 'closed' if hyp and lab['change'] == 'add' and lab['prevents'] != 'severe' else 'keep'
print("\nD. simpler rules (keep = not closed by the rule)")
for name, fn in (("felt in use, or prevents severe", v_felt), ("felt in use, or grounded, or severe", v_felt_or_ground),
                 ("close only what is hypothetical and adds", v_no_add_hyp)):
    cl = [r for r in own if fn(r[1]) == 'closed']
    lo = [r for r in cl if r[2]['progressed']]
    print(f"  {name:<44} closes {len(cl):>3} ({pct(len(cl), len(own))}), of which progressed {len(lo)} ({pct(len(lo), len(cl))}); picks kept {pct(len(picks)-len(lo), len(picks))}")

if '--misses' in sys.argv:
    print("\nE. picks the proposed treatment closes")
    for r in lost:
        print(f"  {r[0][0]} {r[0][1]:<4} [{r[2]['fate']}] {r[1]['benefit']}/{r[1]['felt']}/{r[1]['ground']}/{r[1]['change']}/{r[1]['size']}/pc={r[1]['product_call']}/{r[1]['prevents']}  {r[2]['headline'][:70]}")
