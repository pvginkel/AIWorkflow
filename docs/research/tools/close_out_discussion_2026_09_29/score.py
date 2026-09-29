# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: the labelled entries through the operator's policy table, against their rulings."""
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

d = json.load(open('/tmp/close-out-entries.json'))
m = json.load(open('/work/AIWorkflow/docs/research/data/close-out-read-2026-09-28.json'))
RULED = ("card", "fix", "fold", "close")
VOCAB = {
    'kind': {'action', 'event', 'question', 'idea', 'prose', 'test-gap', 'defect', 'hardening', 'cleanup', 'slice-input'},
    'trigger': {'normal-use', 'ordinary-condition', 'fault-or-coincidence', 'future-change', 'none', 'unknown'},
    'impact': {'wrong-or-lost', 'broken-or-stuck', 'misleading', 'none-observable', 'unknown'},
    'fix': {'one-edit', 'known-several', 'design', 'unknown', 'na'},
    'sensitive': {'yes', 'no', 'na'},
    'basis': {'stated', 'partly', 'inferred'},
}


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
    for row in s['named_rulings'] + s['overrides']:
        named.add((f"{s['project']}-{row[0]}", row[1]))
    for a in s['advice']:
        advised.add((f"{s['project']}-{a[0]}", a[1]))
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
    elif modes and modes <= {'direct', 'blanket-close'}:
        e['_who'] = 'operator'
    else:
        e['_who'] = 'other'

moot = set()
for rep, items in m['sorts']['heldout-v2'].items():
    k3 = rep[:rep.index('-') + 4]
    for i, b in items.items():
        if b == 'moot':
            moot.add((k3, i))

labels = {}
bad = Counter()
files = sorted(glob.glob('/tmp/co/labels/out/*.json'))
for f in files:
    name = os.path.basename(f)[:-5]
    k3 = name[:name.index('-') + 4]
    try:
        data = json.load(open(f))
    except Exception as ex:
        bad[f'unparsable {name}'] += 1
        continue
    for i, lab in data.items():
        for a, vs in VOCAB.items():
            if lab.get(a) not in vs:
                bad[f'{a}={lab.get(a)}'] += 1
        labels[(k3, i)] = lab
print(f"label files {len(files)}, entries labelled {len(labels)}, matched to the corpus {sum(k in ent for k in labels)}; off-vocabulary: {dict(bad)}")


def route(lab):
    k = lab['kind']
    if k == 'action':
        return 'yours: action'
    if k == 'event':
        return 'record'
    if k in ('question', 'idea'):
        return 'yours: decide'
    if k == 'slice-input':
        return 'fold'
    if k == 'prose':
        return 'sweep: fix'
    easy = lab['fix'] in ('one-edit', 'known-several') and lab['sensitive'] != 'yes'
    if easy:
        return 'sweep: fix'
    if lab['trigger'] == 'unknown' or lab['impact'] == 'unknown':
        return 'sweep: investigate'
    if lab['trigger'] in ('normal-use', 'ordinary-condition') and lab['impact'] != 'none-observable':
        return 'sweep: fix or card'
    return 'close'


ROUTES = ['yours: action', 'yours: decide', 'sweep: fix', 'sweep: fix or card', 'sweep: investigate', 'fold', 'close', 'record']
rows = [(k, lab, ent[k]) for k, lab in labels.items() if k in ent]
handed = [(k, lab, e) for k, lab, e in rows if e['fate'] != 'in-run']
print(f"handed over {len(handed)}")


def matrix(title, sel):
    sub = [(k, lab, e) for k, lab, e in handed if e['fate'] in RULED and sel(k, e)]
    print(f"\n{title}: entries ruled {len(sub)}, progressed {pct(sum(e['progressed'] for _, _, e in sub), len(sub))}")
    print(f"  {'route':<20}{'n':>4}{'share':>7}{'closed':>8}{'fixed':>7}{'carded':>8}{'folded':>8}")
    for rt in ROUTES:
        s = [e for k, lab, e in sub if route(lab) == rt]
        c = Counter(e['fate'] for e in s)
        if s:
            print(f"  {rt:<20}{len(s):>4}{pct(len(s), len(sub)):>7}{c['close']:>8}{c['fix']:>7}{c['card']:>8}{c['fold']:>8}")
    closed = [e for k, lab, e in sub if route(lab) in ('close', 'record')]
    lost = [e for e in closed if e['progressed']]
    lost_card = [e for e in closed if e['fate'] in ('card', 'fold')]
    picks = [e for _, _, e in sub if e['progressed']]
    cards = [e for _, _, e in sub if e['fate'] in ('card', 'fold')]
    print(f"  the table closes {len(closed)} ({pct(len(closed), len(sub))}); of those the operator progressed {len(lost)} ({pct(len(lost), len(closed))}), carded or folded {len(lost_card)}")
    print(f"  picks kept {len(picks)-len(lost)}/{len(picks)} ({pct(len(picks)-len(lost), len(picks))}); cards and folds kept {len(cards)-len(lost_card)}/{len(cards)} ({pct(len(cards)-len(lost_card), len(cards))})")
    return sub


own = matrix("A. The operator's own rulings", lambda k, e: e['_who'] == 'operator')
matrix("A2. … without entries already fixed in the run (where known)", lambda k, e: e['_who'] == 'operator' and k not in moot)
matrix("B. Entries the operator asked advice on", lambda k, e: e['_who'] == 'advice')
matrix("C. Rulings taken from a sheet or handed over", lambda k, e: e['_who'] in ('sheet', 'other'))

print("\nD. Each label against the operator's own rulings")
for a in ('kind', 'trigger', 'impact', 'fix', 'sensitive', 'basis'):
    print(f"  {a}")
    for v in sorted(VOCAB[a]):
        s = [e for k, lab, e in own if lab.get(a) == v]
        c = Counter(e['fate'] for e in s)
        if s:
            print(f"    {v:<22}{len(s):>4}  progressed {pct(c['card']+c['fix']+c['fold'], len(s)):>5}   carded/folded {pct(c['card']+c['fold'], len(s)):>5}   fixed {pct(c['fix'], len(s)):>5}")

print("\nE. What reaches the operator, per report (all handed-over entries of the labelled reports)")
per = defaultdict(Counter)
for k, lab, e in handed:
    rt = route(lab)
    grp = 'yours' if rt.startswith('yours') else ('sweep' if rt.startswith('sweep') or rt == 'fold' else 'closed or record')
    per[k[0]][grp] += 1
for grp in ('yours', 'sweep', 'closed or record'):
    xs = [per[r][grp] for r in per]
    print(f"  {grp:<18} total {sum(xs):>4} ({pct(sum(xs), len(handed))}), per report median {statistics.median(xs)}, max {max(xs)}")
unk = sum(1 for k, lab, e in handed if lab['trigger'] == 'unknown' or lab['impact'] == 'unknown')
print(f"  trigger or impact unknown: {unk} ({pct(unk, len(handed))}); basis: {dict(Counter(lab['basis'] for _, lab, _ in handed))}")

if '--misses' in sys.argv:
    print("\nF. The operator's own cards and folds that the table closes")
    for k, lab, e in own:
        if route(lab) in ('close', 'record') and e['fate'] in ('card', 'fold'):
            print(f"  {k[0]} {k[1]:<4} [{e['fate']}] {e['severity'] or '-':<6} {lab['kind']}/{lab['trigger']}/{lab['impact']}/{lab['fix']}/{lab['sensitive']}  {e['headline'][:90]}")
