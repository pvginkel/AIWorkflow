# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how § 3.9 and § 3.5 of
# docs/research/close-out-triage-plan-2026-09-29.md were computed — the two policy tables as the
# operator ruled them, over the committed label data. Reads the entries with their fates from
# /tmp/close-out-entries.json (the plan's § 10 says how to make it again). Owed to
# close_out_readout.py; this folder goes when that is done.
"""The policy tables as ruled (plan § 4.3, § 4.4) against the operator's own rulings.

Run from the repository root:  python3 docs/research/tools/close_out_discussion_2026_09_29/ruled_tables.py
"""
import json
import re
import statistics
from collections import Counter, defaultdict

DATA = 'docs/research/data/'
entries = json.load(open('/tmp/close-out-entries.json'))
read = json.load(open(DATA + 'close-out-read-2026-09-28.json'))
first = json.load(open(DATA + 'close-out-labels-2026-09-29.json'))['labels']
second = json.load(open(DATA + 'close-out-improvement-labels-2026-09-29.json'))['labels']
RULED = ('card', 'fix', 'fold', 'close')


def pct(n, t):
    return f"{100 * n / t:.0f} %" if t else "-"


# every entry by report key ("KubeCoder-163") and id; two reports share a key and are one here,
# as in the read's own tool
ent = {}
for r in entries:
    k3 = f"{r['project']}-{r['slice'][:3]}"
    for e in r['entries']:
        if re.fullmatch(r"[ANBQS]\d+", e['id']):
            ent[(k3, e['id'])] = e

# whose ruling: the operator's own, advice, a sheet's, the rest
mode_of = defaultdict(set)
on_sheet, named, advised = set(), set(), set()
for s in read['sessions']:
    if s['mode'] == 'other':
        continue
    for sl in s['slices']:
        mode_of[f"{s['project']}-{sl}"].add(s['mode'])
    on_sheet |= {(f"{s['project']}-{sl}", i) for sl, i, _ in s['sheet']}
    named |= {(f"{s['project']}-{row[0]}", row[1]) for row in s['named_rulings'] + s['overrides']}
    advised |= {(f"{s['project']}-{a[0]}", a[1]) for a in s['advice']}
for k, e in ent.items():
    modes = mode_of.get(k[0], set())
    if e['fate'] not in RULED:
        e['who'] = None
    elif k in advised:
        e['who'] = 'advice'
    elif k in named:
        e['who'] = 'operator'
    elif k in on_sheet:
        e['who'] = 'sheet'
    elif modes and modes <= {'direct', 'blanket-close'}:
        e['who'] = 'operator'
    else:
        e['who'] = 'other'

labels = {}
for name, data in first.items():
    k3 = name[:name.index('-') + 4]
    for i, lab in data.items():
        labels[(k3, i)] = lab
improvement = {tuple(k.split(' ')): v for k, v in second.items()}
handed = [(k, lab, ent[k]) for k, lab in labels.items() if k in ent and ent[k]['fate'] != 'in-run']

HYPOTHETICAL = ('after-a-change', 'after-an-incident', 'not-observable')


def route_improvement(lab, major):
    """Plan § 4.4."""
    severe = lab['prevents'] == 'severe' or major
    if lab['benefit'] == 'workflow':
        return 'to Fieldnotes'
    if (lab['change'] in ('adjust', 'remove') and lab['size'] in ('one-edit', 'several-places')
            and lab['product_call'] == 'no'):
        return 'to the wrap-up: a potential improvement'
    if lab['change'] == 'add' and lab['felt'] in HYPOTHETICAL:
        return 'to the operator: severe or major, in place of a close' if severe else 'closed'
    return 'to the operator: a potential improvement'


def route_fix(lab, e):
    """Plan § 4.3, without rows 4 and 5's labels (the replay had neither `repo` nor `for`;
    the first pass's kind `slice-input` stands in for row 4)."""
    kind = lab['kind']
    severe = (lab['impact'] == 'wrong-or-lost' and lab['trigger'] != 'none') or e['severity'] == 'major'
    if kind == 'action':
        return 'to the operator: an action'
    if kind == 'question':
        return 'to the operator: a decision'
    problem = lab['impact'] != 'none-observable' and lab['trigger'] != 'none'
    if kind == 'event' and not problem:
        return 'the record'
    if kind == 'slice-input':
        return 'input for a later slice'
    if kind == 'prose':
        return 'to the wrap-up: fix'
    if lab['fix'] in ('one-edit', 'known-several') and lab['sensitive'] != 'yes':
        return 'to the wrap-up: fix'
    if 'unknown' in (lab['trigger'], lab['impact']):
        return 'to the wrap-up: look'
    if lab['trigger'] in ('normal-use', 'ordinary-condition') and lab['impact'] != 'none-observable':
        return 'to the wrap-up: fix, or ask for a card'
    return 'to the operator: severe or major, in place of a close' if severe else 'closed'


def route(k, lab, e):
    if k in improvement:
        return route_improvement(improvement[k], e['severity'] == 'major')
    return route_fix(lab, e)


ORDER = ['to the operator: an action', 'to the operator: a decision',
         'to the operator: severe or major, in place of a close',
         'to the operator: a potential improvement', 'to the wrap-up: fix',
         'to the wrap-up: a potential improvement', 'to the wrap-up: fix, or ask for a card',
         'to the wrap-up: look', 'input for a later slice', 'to Fieldnotes', 'closed', 'the record']

own = [(k, lab, e) for k, lab, e in handed if e['fate'] in RULED and e['who'] == 'operator']
print(f"labelled and handed over {len(handed)}; the operator's own rulings {len(own)}\n")
print(f"{'route':<56}{'n':>4}{'':>6}{'closed':>8}{'fixed':>7}{'carded':>8}{'folded':>8}")
for rt in ORDER:
    es = [e for k, lab, e in own if route(k, lab, e) == rt]
    c = Counter(e['fate'] for e in es)
    print(f"{rt:<56}{len(es):>4}{pct(len(es), len(own)):>6}{c['close']:>8}{c['fix']:>7}{c['card']:>8}{c['fold']:>8}")

closed = [(k, lab, e) for k, lab, e in own if route(k, lab, e) in ('closed', 'the record')]
picks = [e for _, _, e in own if e['progressed']]
cards = [e for _, _, e in own if e['fate'] in ('card', 'fold')]
lost = [(k, lab, e) for k, lab, e in closed if e['progressed']]
lost_cards = [x for x in lost if x[2]['fate'] in ('card', 'fold')]
print(f"\npicks kept {len(picks) - len(lost)}/{len(picks)} ({pct(len(picks) - len(lost), len(picks))}); "
      f"cards and folds kept {len(cards) - len(lost_cards)}/{len(cards)} "
      f"({pct(len(cards) - len(lost_cards), len(cards))}); closed {pct(len(closed), len(own))}")
print("the misses (§ 3.5):")
for k, lab, e in lost:
    print(f"  {k[0]} {k[1]:<4} {e['fate']:<5} {e['severity'] or '-':<6} "
          f"{lab['kind']} / {lab['trigger']} / {lab['impact']} / {lab['fix']}")


def group(rt):
    if rt.startswith('to the operator'):
        return 'comes to the operator'
    if rt.startswith('to the wrap-up'):
        return 'goes to the wrap-up'
    return rt


per, total = defaultdict(Counter), Counter()
for k, lab, e in handed:
    g = group(route(k, lab, e))
    per[k[0]][g] += 1
    total[g] += 1
print(f"\nover everything handed over ({len(handed)} entries, {len(per)} reports)")
for g in ('comes to the operator', 'goes to the wrap-up', 'input for a later slice',
          'to Fieldnotes', 'closed', 'the record'):
    xs = [per[r][g] for r in per]
    print(f"  {g:<26}{total[g]:>4} {pct(total[g], len(handed)):>5}  a report: median "
          f"{statistics.median(xs)}, max {max(xs)}")

# D7: the closes whose impact breaks a flow
cl_own = [(k, lab, e) for k, lab, e in own if route(k, lab, e) == 'closed']
br_own = [x for x in cl_own if x[0] not in improvement and x[1]['impact'] == 'broken-or-stuck']
cl_all = [(k, lab, e) for k, lab, e in handed if route(k, lab, e) == 'closed']
br_all = [x for x in cl_all if x[0] not in improvement and x[1]['impact'] == 'broken-or-stuck']
print(f"\nD7: closes on own rulings {len(cl_own)}, breaking a flow {len(br_own)}, lost cards among "
      f"them {sum(1 for x in br_own if x[2]['fate'] in ('card', 'fold'))}; over all reports "
      f"{len(br_all)} of {len(cl_all)}, {len(br_all) / len(per):.1f} a report")
