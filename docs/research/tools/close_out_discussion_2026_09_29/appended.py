# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: appended phases across the completed slices."""
import glob
import json
import os
import re
import statistics
from collections import Counter, defaultdict

ROOTS = {'KubeCoder': '/work/scratch/KubeCoderSpecs/slices/completed',
         'Ansible': '/work/scratch/AnsibleSpecs/slices/completed'}


def pct(n, t):
    return f"{100*n/t:.0f} %" if t else "-"


slices = []
for proj, root in ROOTS.items():
    for d in sorted(glob.glob(root + '/*/')):
        sp = os.path.join(d, 'state.json')
        if not os.path.exists(sp):
            continue
        try:
            s = json.load(open(sp))
        except Exception:
            continue
        consults = []
        for cp in sorted(glob.glob(d + 'consult_*.json')):
            try:
                consults.append((os.path.basename(cp), json.load(open(cp))))
            except Exception:
                pass
        tests = []
        for tp in sorted(glob.glob(d + 'test_phase_result_r*.json')):
            try:
                tests.append((os.path.basename(tp), json.load(open(tp))))
            except Exception:
                pass
        slices.append({'proj': proj, 'dir': d, 'name': os.path.basename(d.rstrip('/')), 's': s,
                       'consults': consults, 'tests': tests})

print("slices with a state.json:", len(slices), Counter(x['proj'] for x in slices))
withapp = [x for x in slices if x['s'].get('appended_phases')]
napp = sum(len(x['s']['appended_phases']) for x in withapp)
nplanned = sum(len(x['s'].get('phases', {})) - len(x['s'].get('appended_phases') or []) for x in slices)
print(f"slices with an appended phase: {len(withapp)} ({pct(len(withapp), len(slices))}); appended phases {napp}; planned phases {nplanned}")
print(" appended per slice that has any:", Counter(len(x['s']['appended_phases']) for x in withapp))
print(" generations spent:", Counter(x['s'].get('generation') for x in slices))
print(" consult outcomes:", Counter(c.get('outcome') for x in slices for _, c in x['consults']))
print(" test phase outcomes:", Counter(t.get('outcome') for x in slices for _, t in x['tests']))
print(" plugin versions with appended:", Counter((x['s'].get('plugin_version') or '?') for x in withapp).most_common(8))

# time per phase from history rows (duration_s), appended against planned
def phase_time(x):
    t = defaultdict(float)
    rows = defaultdict(list)
    for h in x['s'].get('history', []):
        ph = str(h.get('phase'))
        t[ph] += h.get('duration_s') or 0
        rows[ph].append(h)
    return t, rows

app_t, plan_t, app_rounds, plan_rounds, app_rev, plan_rev = [], [], [], [], [], []
tot_time = 0
app_time = 0
for x in slices:
    t, rows = phase_time(x)
    tot_time += sum(t.values())
    ap = set(map(str, x['s'].get('appended_phases') or []))
    for pid, p in x['s'].get('phases', {}).items():
        if pid in ap:
            app_t.append(t.get(pid, 0)); app_rounds.append(p.get('executor_rounds') or 0); app_rev.append(p.get('review_rounds') or 0)
            app_time += t.get(pid, 0)
        else:
            plan_t.append(t.get(pid, 0)); plan_rounds.append(p.get('executor_rounds') or 0); plan_rev.append(p.get('review_rounds') or 0)
med = statistics.median
print(f"\nper phase, session time from history rows: appended median {med(app_t)/60:.0f} min (n={len(app_t)}), planned median {med(plan_t)/60:.0f} min (n={len(plan_t)})")
print(f" executor rounds: appended mean {statistics.mean(app_rounds):.2f}, planned mean {statistics.mean(plan_rounds):.2f}; review rounds: appended {statistics.mean(app_rev):.2f}, planned {statistics.mean(plan_rev):.2f}")
print(f" appended phases' share of all session time in history: {pct(app_time, tot_time)}")
wt = sum(sum(phase_time(x)[0].values()) for x in withapp)
print(f" in slices that have one: {pct(app_time, wt)} of that slice's session time")

# who appended: look at log.txt lines
who = Counter()
samples = []
for x in withapp:
    lp = os.path.join(x['dir'], 'log.txt')
    if not os.path.exists(lp):
        continue
    for line in open(lp, errors='replace'):
        if re.search(r"append", line, re.I) and re.search(r"phase|P\d", line):
            samples.append((x['name'], line.strip()[:220]))
for n, l in samples[:25]:
    print("  ", n[:30], "|", l)
print(len(samples))

# ---- second pass: appended = a phase whose first executor row comes after the first completion consult row
print("\n\n==== second pass")
roles = Counter(h.get('role') for x in slices for h in x['s'].get('history', []))
print("history roles:", dict(roles))
events = []
tot_cost = 0.0
app_cost = 0.0
n_with = 0
allslices_cost = 0.0
per_slice = []
for x in slices:
    hist = x['s'].get('history', [])
    first_consult = next((i for i, h in enumerate(hist) if 'consult' in str(h.get('role')) and str(h.get('phase')) in ('None', 'completion', '', 'null') ), None)
    # fall back: a row whose role mentions completion
    if first_consult is None:
        first_consult = next((i for i, h in enumerate(hist) if 'completion' in json.dumps(h)[:200]), None)
    t, rows = phase_time(x)
    cost = (x['s'].get('cost') or {}).get('cost_usd') or 0
    allslices_cost += cost
    total_t = sum((h.get('duration_s') or 0) for h in hist)
    ap = []
    if first_consult is not None:
        seen_before = {str(h.get('phase')) for h in hist[:first_consult] if h.get('role') == 'code-writer'}
        for h in hist[first_consult:]:
            pid = str(h.get('phase'))
            if h.get('role') == 'code-writer' and pid not in seen_before and pid not in ap and pid in x['s'].get('phases', {}):
                ap.append(pid)
    x['_ap'] = ap
    if ap:
        n_with += 1
        at = sum(t[p] for p in ap)
        est = cost * at / total_t if total_t else 0
        app_cost += est
        tot_cost += cost
        per_slice.append((x['name'], x['s'].get('plugin_version'), ap, at / 60, est, cost))
print(f"slices with appended phases (by history order): {n_with} of {len(slices)} ({pct(n_with, len(slices))}); appended phases {sum(len(x['_ap']) for x in slices)}")
print(f"their session time as a share of the slice, priced at the slice's cost: ${app_cost:.0f} of ${tot_cost:.0f} ({pct(app_cost, tot_cost)}) in those slices; of all slices' ${allslices_cost:.0f}: {pct(app_cost, allslices_cost)}")
for row in per_slice:
    print(f"  {row[0][:44]:<44} v{row[1]}  phases {row[2]}  {row[3]:.0f} min  ~${row[4]:.1f} of ${row[5]:.0f}")

# the reasons
print("\n==== why: consult and test-phase summaries that appended")
for x in slices:
    if not x['_ap'] and not any(c.get('outcome') in ('appended', 'fix_tasks') for _, c in x['consults']):
        continue
    for n, c in x['consults']:
        if c.get('outcome') in ('appended', 'fix_tasks'):
            print(f"\n--- {x['proj']} {x['name']} · {n} · {c.get('outcome')} · v{x['s'].get('plugin_version')}")
            print(re.sub(r"\s+", " ", c.get('summary', ''))[:1100])
    for n, tres in x['tests']:
        if tres.get('outcome') == 'findings':
            print(f"\n--- {x['proj']} {x['name']} · {n} · findings · v{x['s'].get('plugin_version')}")
            print(re.sub(r"\s+", " ", tres.get('summary', ''))[:1100])

print("\n==== third pass: before and since 2026-08-16 (the 0.5.1 bar)")
for label, sel in (("created before 2026-08-16", lambda x: (x['s'].get('created_at') or '')[:10] < '2026-08-16'),
                   ("created since", lambda x: (x['s'].get('created_at') or '')[:10] >= '2026-08-16')):
    sub = [x for x in slices if sel(x)]
    w = [x for x in sub if x['_ap']]
    n = sum(len(x['_ap']) for x in w)
    ts = [phase_time(x)[0][p] / 60 for x in w for p in x['_ap']]
    print(f"  {label}: slices {len(sub)}, with an appended phase {len(w)} ({pct(len(w), len(sub))}), appended phases {n}, "
          f"median minutes {statistics.median(ts) if ts else 0:.0f}; names {[x['name'][:3] for x in w]}")
nodate = [x['name'] for x in slices if not x['s'].get('created_at')]
print("  without a date:", len(nodate))
