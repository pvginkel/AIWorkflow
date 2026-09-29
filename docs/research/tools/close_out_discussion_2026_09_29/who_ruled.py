# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: whose ruling is each entry's fate — the operator's own, or a sheet's they accepted —
and how the sorts score against the operator's own rulings only."""
import json
import re
from collections import Counter, defaultdict

d = json.load(open('/tmp/close-out-entries.json'))
m = json.load(open('/work/AIWorkflow/docs/research/data/close-out-read-2026-09-28.json'))
RULED = ("card", "fix", "fold", "close")


def pct(n, t):
    return f"{100*n/t:.0f} %" if t else "-"


ent = {}
for r in d:
    k3 = f"{r['project']}-{r['slice'][:3]}"
    for e in r['entries']:
        if re.fullmatch(r"[ANBQS]\d+", e['id']):
            e['_rep'] = k3
            ent[(k3, e['id'])] = e

mode_of = defaultdict(set)
on_sheet, named, advised = {}, set(), set()
for s in m['sessions']:
    if s['mode'] == 'other':
        continue
    for sl in s['slices']:
        mode_of[f"{s['project']}-{sl}"].add(s['mode'])
    for sl, i, b in s['sheet']:
        on_sheet[(f"{s['project']}-{sl}", i)] = b
    for row in s['named_rulings']:
        named.add((f"{s['project']}-{row[0]}", row[1]))
    for row in s['overrides']:
        named.add((f"{s['project']}-{row[0]}", row[1]))
    for a in s['advice']:
        if isinstance(a, (list, tuple)) and len(a) >= 2:
            advised.add((f"{s['project']}-{a[0]}", a[1]))
        elif isinstance(a, dict):
            advised.add((f"{s['project']}-{a.get('slice')}", a.get('id')))
print("advice sample:", m['sessions'][1]['advice'][:2], [s['advice'][:1] for s in m['sessions'] if s['advice']][:2])

for k, e in ent.items():
    modes = mode_of.get(k[0], set())
    if e['fate'] not in RULED:
        e['_who'] = None
    elif k in advised:
        e['_who'] = 'advice'
    elif k in named:
        e['_who'] = 'operator'
    elif k in on_sheet:
        e['_who'] = 'sheet'
    elif modes and modes <= {'direct'}:
        e['_who'] = 'operator'
    elif modes and modes <= {'direct', 'blanket-close'}:
        e['_who'] = 'operator'
    elif not modes:
        e['_who'] = 'uncoded'
    else:
        e['_who'] = 'unclear'   # mixed/handed-over report, entry neither named nor on a coded sheet

print("\nA. Whose ruling (entries ruled, all kinds)")
for who in ('operator', 'advice', 'sheet', 'unclear', 'uncoded'):
    es = [e for e in ent.values() if e.get('_who') == who]
    c = Counter(e['fate'] for e in es)
    print(f"  {who:<9} {len(es):>4}  progressed {pct(c['card']+c['fix']+c['fold'],len(es)):>5}  "
          f"card {pct(c['card'],len(es)):>5} fix {pct(c['fix'],len(es)):>5} fold {pct(c['fold'],len(es)):>5} close {pct(c['close'],len(es)):>5}")
print("  by mode of the report, 'unclear':", Counter(tuple(sorted(mode_of[e['_rep']])) for e in ent.values() if e.get('_who') == 'unclear'))

MAP = {'card': 'card', 'fix now': 'fix', 'fold': 'fold', 'close': 'close', 'moot': 'close'}


def score(arm, whos, label):
    conf = defaultdict(Counter)
    for rep, items in m['sorts'][arm].items():
        k3 = rep[:rep.index('-') + 4]
        for i, b in items.items():
            e = ent.get((k3, i))
            if not e or e.get('_who') not in whos:
                continue
            conf[b][e['fate']] += 1
    n = sum(sum(c.values()) for c in conf.values())
    prog = sum(c['card'] + c['fix'] + c['fold'] for c in conf.values())
    closed_b = [b for b in conf if b in ('close', 'moot')]
    lost = sum(conf[b]['card'] + conf[b]['fix'] + conf[b]['fold'] for b in closed_b)
    nclose = sum(sum(conf[b].values()) for b in closed_b)
    tot = sum(sum(conf[b].values()) for b in MAP if b in conf)
    exact = sum(conf[b][MAP[b]] for b in MAP if b in conf)
    flagged = [b for b in conf if b in ('card', 'fix now', 'fold', 'test gaps')]
    nfl = sum(sum(conf[b].values()) for b in flagged)
    fl_prog = sum(conf[b]['card'] + conf[b]['fix'] + conf[b]['fold'] for b in flagged)
    print(f"\n  {arm} · {label}: entries {n}, progressed by the operator {prog} ({pct(prog,n)})")
    print(f"    the sort closes {nclose} ({pct(nclose,n)}); of those the operator progressed {lost} ({pct(lost,nclose)})")
    print(f"    picks kept {prog-lost}/{prog} ({pct(prog-lost,prog)});  exact disposition {exact}/{tot} ({pct(exact,tot)})")
    print(f"    proposes work (card, fix now, fold, test gaps) {nfl}; the operator closed {nfl-fl_prog} of them ({pct(nfl-fl_prog,nfl)})")
    print(f"    {'':<12}{'n':>4}{'close':>7}{'fix':>6}{'card':>6}{'fold':>6}")
    for b in ('card', 'fix now', 'fold', 'test gaps', 'needs-eyes', 'action', 'close', 'moot'):
        c = conf[b]
        if sum(c.values()):
            print(f"    {b:<12}{sum(c.values()):>4}{c['close']:>7}{c['fix']:>6}{c['card']:>6}{c['fold']:>6}")


print("\nB. The sorts against the operator's own rulings only, and against sheet rulings")
for arm in ('heldout-v1', 'heldout-v2'):
    score(arm, ('operator',), "operator's own rulings")
for arm in ('heldout-v1', 'heldout-v2'):
    score(arm, ('sheet',), "rulings taken from a sheet")
score('heldout-v2', ('advice',), "entries the operator asked advice on")
score('sample-v1', ('operator',), "operator's own rulings")

print("\nC. What the rules were derived from: the picks the current rules lost on the 55 sample reports")
lost = Counter()
for rep, items in m['sorts']['sample-v1'].items():
    k3 = rep[:rep.index('-') + 4]
    for i, b in items.items():
        e = ent.get((k3, i))
        if e and e['fate'] in ('card', 'fix', 'fold') and b in ('close', 'moot'):
            lost[e.get('_who')] += 1
print("  ", dict(lost))
held = Counter()
for rep in m['sorts']['heldout-v2']:
    k3 = rep[:rep.index('-') + 4]
    held[tuple(sorted(mode_of.get(k3, {'uncoded'})))] += 1
print("  held-out reports by mode:", dict(held))

print("\nD. Direct-mode reports only (every ruling the operator's, blanket closes included)")
direct = {k for k, v in mode_of.items() if v <= {'direct'}}
es = [e for e in ent.values() if e['_rep'] in direct and e['fate'] in RULED]
c = Counter(e['fate'] for e in es)
print(f"  reports {len(direct)}, entries ruled {len(es)}: progressed {pct(c['card']+c['fix']+c['fold'],len(es))}, "
      f"card {pct(c['card'],len(es))}, fix {pct(c['fix'],len(es))}, fold {pct(c['fold'],len(es))}, close {pct(c['close'],len(es))}")
bs = [e for e in es if e['section'] in 'BS']
c = Counter(e['fate'] for e in bs)
print(f"  Bugs+Suggestions {len(bs)}: progressed {pct(c['card']+c['fix']+c['fold'],len(bs))}")
op = [e for e in ent.values() if e.get('_who') == 'operator']
print(f"  the 'operator' set: {sum(e['_rep'] in direct for e in op)} in direct reports, "
      f"{sum(e['_rep'] not in direct for e in op)} named in mixed or handed-over reports")
for e in ent.values():
    e['_direct'] = e['_rep'] in direct and e['fate'] in RULED


def score2(arm):
    conf = defaultdict(Counter)
    reps = set()
    for rep, items in m['sorts'][arm].items():
        k3 = rep[:rep.index('-') + 4]
        for i, b in items.items():
            e = ent.get((k3, i))
            if e and e['_direct']:
                conf[b][e['fate']] += 1
                reps.add(k3)
    n = sum(sum(c.values()) for c in conf.values())
    prog = sum(c['card'] + c['fix'] + c['fold'] for c in conf.values())
    cb = [b for b in conf if b in ('close', 'moot')]
    lost = sum(conf[b]['card'] + conf[b]['fix'] + conf[b]['fold'] for b in cb)
    nclose = sum(sum(conf[b].values()) for b in cb)
    fb = [b for b in conf if b in ('card', 'fix now', 'fold', 'test gaps')]
    nfl = sum(sum(conf[b].values()) for b in fb)
    flp = sum(conf[b]['card'] + conf[b]['fix'] + conf[b]['fold'] for b in fb)
    print(f"  {arm}: reports {len(reps)}, entries {n}, picks {prog}; closes {nclose} ({pct(nclose,n)}), "
          f"wrongly {lost} ({pct(lost,nclose)}); kept {prog-lost}/{prog} ({pct(prog-lost,prog)}); "
          f"proposes work {nfl}, operator closed {nfl-flp} ({pct(nfl-flp,nfl)})")


for arm in ('sample-v1', 'heldout-v1', 'heldout-v2'):
    score2(arm)

print("\nE. Entries the operator asked advice on, corpus-wide: what the sheets and the sorts made of them")
adv = [e for e in ent.values() if e.get('_who') == 'advice']
print("  fates:", dict(Counter(e['fate'] for e in adv)), " grades:", dict(Counter(e['severity'] or 'ungraded' for e in adv)),
      " kinds:", dict(Counter(e['section'] for e in adv)))
b = Counter()
for arm in ('sample-v1', 'heldout-v2'):
    for rep, items in m['sorts'][arm].items():
        k3 = rep[:rep.index('-') + 4]
        for i, bk in items.items():
            e = ent.get((k3, i))
            if e and e.get('_who') == 'advice':
                b[(arm, bk)] += 1
print("  sorted as:", dict(b))
