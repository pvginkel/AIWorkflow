# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how § 3.10 of
# docs/research/close-out-triage-plan-2026-09-29.md was computed — the loud/silent label
# against the operator's rulings, and the policy table with the label in it. Reads the
# committed labels and, through ruled_tables.py, the entries with their fates from
# /tmp/close-out-entries.json (the plan's § 10 says how to make it again). Owed to
# close_out_readout.py; this folder goes when that is done.
"""The loud/silent label (plan § 4.2 `signal`) against the rulings, and § 4.3 with it.

Run from the repository root:
    python3 docs/research/tools/close_out_discussion_2026_09_29/signal_score.py [--misses] [--list]
"""
import contextlib
import importlib.util
import io
import json
import statistics
import sys
from collections import Counter, defaultdict

HERE = 'docs/research/tools/close_out_discussion_2026_09_29/'
spec = importlib.util.spec_from_file_location('ruled_tables', HERE + 'ruled_tables.py')
rt = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(rt)
raw = json.load(open(rt.DATA + 'close-out-signal-labels-2026-09-29.json'))['labels']
signal = {tuple(k.split(' ')): v['signal'] for k, v in raw.items()}
basis = Counter(v['basis'] for v in raw.values())
VALUES = ('silent', 'loud', 'unknown')
FIX_OR_CARD = 'to the wrap-up: fix, or ask for a card'
RISK = 'to the operator: severe or major, in place of a close'


def pct(n, t):
    return f"{100 * n / t:.0f} %" if t else "-"


def row(name, es):
    c = Counter(e['fate'] for e in es)
    n = len(es)
    print(f"  {name:<48}{n:>4}  progressed {pct(n - c['close'], n):>5}  carded or folded "
          f"{pct(c['card'] + c['fold'], n):>5}  fixed {pct(c['fix'], n):>5}")


def rows(title, es):
    print(f"   {title}")
    for v in VALUES:
        row(v, [e for k, lab, e in es if signal[k] == v])


def easy(lab):
    return lab['fix'] in ('one-edit', 'known-several') and lab['sensitive'] != 'yes'


own = [(k, lab, e) for k, lab, e in rt.own if k in signal]
fixes = [x for x in own if x[0] not in rt.improvement]
print(f"labelled {len(signal)}: {dict(Counter(signal.values()))}; basis {dict(basis)}")
print(f"of the operator's own rulings {len(own)} carry the label\n")

print("A. the label against the operator's own rulings")
rows("every labelled entry", own)
rows("what should be fixed: a defect, a test gap, an event that describes a problem", fixes)
rows("… defects", [x for x in fixes if x[1]['kind'] == 'defect'])
rows("… test gaps, by what they would prevent", [x for x in fixes if x[1]['kind'] == 'test-gap'])
rows("potential improvements, by what they would prevent",
     [x for x in own if x[0] in rt.improvement])
rows("what should be fixed, an easy fix (the policy's first two bullets)",
     [x for x in fixes if easy(x[1])])
rows("what should be fixed, not an easy fix (its third bullet)",
     [x for x in fixes if not easy(x[1])])

print("\nB. rulings that are not the operator's own: a sheet's, a handed-over rest")
rest = [(k, lab, e) for k, lab, e in rt.handed
        if e['fate'] in rt.RULED and e['who'] in ('sheet', 'other') and k in signal]
rows("every labelled entry", rest)

print("\nC. the routes of the table as ruled (§ 3.9), split by the label — own rulings")
for r in rt.ORDER:
    for v in VALUES:
        es = [e for k, lab, e in own if rt.route(k, lab, e) == r and signal[k] == v]
        if es:
            row(f"{r[:38]} / {v}", es)

print("\nD. the row that fixes or asks for a card, by the label — every ruling, whoever ruled")
ruled = [(k, lab, e) for k, lab, e in rt.handed
         if e['fate'] in rt.RULED and k in signal and rt.route(k, lab, e) == FIX_OR_CARD]
for who in ('operator', 'advice', 'sheet', 'other'):
    for v in VALUES:
        es = [e for k, lab, e in ruled if e['who'] == who and signal[k] == v]
        if es:
            row(f"{who} / {v}", es)
for v in VALUES:
    row(f"all / {v}", [e for k, lab, e in ruled if signal[k] == v])
for v in VALUES:
    row(f"all, on an ordinary condition / {v}",
        [e for k, lab, e in ruled if signal[k] == v and lab['trigger'] == 'ordinary-condition'])


# the table of § 4.3 with the label in it; three rules were tried
def variant(name, k, lab, e):
    base = rt.route(k, lab, e)
    s = signal.get(k)
    if name in ('silent is not closed', 'both') and base == 'closed' and s == 'silent':
        return FIX_OR_CARD
    if (name in ('loud is closed', 'both') and base == FIX_OR_CARD and s == 'loud'
            and lab['trigger'] == 'ordinary-condition'):
        severe = lab['impact'] == 'wrong-or-lost' or e['severity'] == 'major'
        return RISK if severe else 'closed'
    return base


def score(name, detail=False):
    routes = [(k, lab, e, variant(name, k, lab, e)) for k, lab, e in rt.own]
    closed = [x for x in routes if x[3] in ('closed', 'the record')]
    picks = [x for x in routes if x[2]['progressed']]
    cards = [x for x in routes if x[2]['fate'] in ('card', 'fold')]
    lost = [x for x in closed if x[2]['progressed']]
    lost_cards = [x for x in lost if x[2]['fate'] in ('card', 'fold')]
    per, total = defaultdict(Counter), Counter()
    for k, lab, e in rt.handed:
        g = rt.group(variant(name, k, lab, e))
        per[k[0]][g] += 1
        total[g] += 1
    n = len(rt.handed)
    print(f"\n  {name}: picks kept {len(picks) - len(lost)}/{len(picks)} "
          f"({pct(len(picks) - len(lost), len(picks))}), cards and folds kept "
          f"{len(cards) - len(lost_cards)}/{len(cards)} "
          f"({pct(len(cards) - len(lost_cards), len(cards))}), closed or the record "
          f"{pct(len(closed), len(routes))}")
    if detail:
        print(f"  {'route':<56}{'n':>4}{'':>6}{'closed':>8}{'fixed':>7}{'carded':>8}{'folded':>8}")
        for r in rt.ORDER:
            c = Counter(x[2]['fate'] for x in routes if x[3] == r)
            m = sum(c.values())
            print(f"  {r:<56}{m:>4}{pct(m, len(routes)):>6}{c['close']:>8}{c['fix']:>7}"
                  f"{c['card']:>8}{c['fold']:>8}")
    for g in ('comes to the operator', 'goes to the wrap-up', 'input for a later slice',
              'to Fieldnotes', 'closed', 'the record'):
        xs = [per[r][g] for r in per]
        print(f"    {g:<26}{total[g]:>4} {pct(total[g], n):>5}  a report: median "
              f"{statistics.median(xs)}, max {max(xs)}")
    if '--misses' in sys.argv:
        for k, lab, e, r in lost:
            print(f"    lost: {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<6} "
                  f"{lab['kind']} / {lab['trigger']} / {lab['impact']} / {lab['fix']} / "
                  f"{signal.get(k, '-')}")


print("\nE. the table with the label in it, against the 234 rulings of § 3.9")
score('as ruled')
score('silent is not closed')
score('loud is closed', detail=True)
score('both')

# D7's closes are those that rest on the trigger: the label adds none to them
cl = [(k, lab, e) for k, lab, e in rt.handed if variant('loud is closed', k, lab, e) == 'closed']
new = [x for x in cl if rt.route(*x) != 'closed']
print(f"\nF. closes over all reports {len(cl)}, of which on the label {len(new)} "
      f"({len(new) / len({k[0] for k, _, _ in rt.handed}):.1f} a report); breaking a flow among "
      f"those {sum(1 for x in new if x[1]['impact'] == 'broken-or-stuck')}")

if '--list' in sys.argv:
    print("\nG. the entries of the row, own rulings")
    for k, lab, e in rt.own:
        if rt.route(k, lab, e) == FIX_OR_CARD:
            print(f"  {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<8} "
                  f"{signal.get(k, '-'):<8} {lab['kind']} / {lab['trigger']} / {lab['impact']} / "
                  f"{lab['fix']} -> {variant('loud is closed', k, lab, e)}")
