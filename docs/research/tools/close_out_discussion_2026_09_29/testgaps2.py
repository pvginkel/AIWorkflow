# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: test-gap entries corpus-wide (keyword class), their fates, and whether the code a
closed gap named shows up later in a Bug entry or in another gap entry."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

d = json.load(open('/tmp/close-out-entries.json'))
m = json.load(open('/work/AIWorkflow/docs/research/data/close-out-read-2026-09-28.json'))
arm = m['sorts']['heldout-v2']
RULED = ("card", "fix", "fold", "close")
GAP = re.compile(
    r"no test\b|test gap|unpinned|not pinned|pins? nothing|pinned only|pins only|survives? (a |the )?mutation|"
    r"vacuous|cannot fail|can never fail|no \S+( \S+)? test (pins|drives|covers|exercises|observes|renders)|"
    r"untested|uncovered|has no (\S+ )?test|nothing (pins|observes|exercises|holds|checks)|"
    r"no (\S+ )?gate (holds|on)|not (covered|exercised|reached|reachable) (by|from) (a |any )?test|"
    r"no (\S+ )?(drift )?(test|gate)\b|test witness|without a test|lacks? a test|is not tested|"
    r"(test|assertion)s? .{0,60}(cannot observe|never fails|passes either way|proves nothing)", re.I)


def pct(n, t):
    return f"{100*n/t:.0f} %" if t else "-"


def bodies(path):
    out = {}
    text = Path(path).read_text(errors="replace")
    cur = None
    fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        mm = None if fence else re.match(r"^### (?:~~)?([ANBQS]\d+) — (.*)", line)
        if mm:
            cur = mm.group(1)
            out[cur] = line + "\n"
        elif not fence and line.startswith("## "):
            cur = None
        elif cur:
            out[cur] += line + "\n"
    return out


truth = {}
for rep, items in arm.items():
    k3 = rep[:rep.index('-') + 4]
    for i, b in items.items():
        truth[(k3, i)] = b

allent = []
for r in d:
    k3 = f"{r['project']}-{r['slice'][:3]}"
    bd = bodies(r['path']) if Path(r['path']).exists() else {}
    for e in r['entries']:
        if not re.fullmatch(r"[ANBQS]\d+", e['id']):
            continue
        e['_rep'] = k3
        e['_num'] = int(r['slice'][:3])
        e['_proj'] = r['project']
        e['_body'] = bd.get(e['id'], '')
        e['_gap'] = e['section'] in 'BS' and bool(GAP.search(e['headline']))
        allent.append(e)

# classifier against the sorter's bucket on the held-out reports
tp = sum(1 for e in allent if (e['_rep'], e['id']) in truth and truth[(e['_rep'], e['id'])] == 'test gaps' and e['_gap'])
fn = sum(1 for e in allent if (e['_rep'], e['id']) in truth and truth[(e['_rep'], e['id'])] == 'test gaps' and not e['_gap'])
fp = sum(1 for e in allent if (e['_rep'], e['id']) in truth and truth[(e['_rep'], e['id'])] != 'test gaps' and e['_gap'])
print(f"keyword class vs the sorter's bucket (held-out): both {tp}, sorter only {fn}, keyword only {fp}")

gaps = [e for e in allent if e['_gap'] and e['fate'] != 'in-run']
ruled = [e for e in gaps if e['fate'] in RULED]
print(f"\ncorpus: test-gap entries handed over {len(gaps)}, ruled {len(ruled)}")
c = Counter(e['fate'] for e in ruled)
print(" fates:", dict(c), " progressed", pct(c['card'] + c['fix'] + c['fold'], len(ruled)))
for sev in ("major", "minor", "", "nit", "cosmetic"):
    s = [e for e in ruled if e['severity'] == sev]
    cc = Counter(e['fate'] for e in s)
    print(f"  {sev or 'ungraded':<9} {len(s):>3}  card/fold {pct(cc['card']+cc['fold'],len(s)):>5}  fix {pct(cc['fix'],len(s)):>5}  close {pct(cc['close'],len(s)):>5}")
for ev in ("witnessed", "read"):
    s = [e for e in ruled if e['evidence'] == ev]
    cc = Counter(e['fate'] for e in s)
    print(f"  {ev:<9} {len(s):>3}  card/fold {pct(cc['card']+cc['fold'],len(s)):>5}  fix {pct(cc['fix'],len(s)):>5}  close {pct(cc['close'],len(s)):>5}")
inrun = [e for e in allent if e['_gap'] and e['fate'] == 'in-run']
print(f" struck in the run (fixed, refuted, superseded): {len(inrun)}")
rest = [e for e in allent if e['section'] in 'BS' and not e['_gap'] and e['fate'] in RULED]
cc = Counter(e['fate'] for e in rest)
print(f" for comparison, other Bugs+Suggestions ruled {len(rest)}: card/fold {pct(cc['card']+cc['fold'],len(rest))}  fix {pct(cc['fix'],len(rest))}  close {pct(cc['close'],len(rest))}")

per = Counter(e['_rep'] for e in gaps)
reports = len({e['_rep'] for e in allent})
print(f" reports with a test-gap entry: {len(per)} of {reports}; per report with any: median {sorted(per.values())[len(per)//2]}, max {max(per.values())}")

# by era of slice number (KubeCoder only): does the rate of gap entries rise?
print("\nKubeCoder, test-gap entries per report by slice range")
for lo, hi in ((146, 170), (171, 195), (196, 215), (216, 240)):
    reps = {e['_rep'] for e in allent if e['_proj'] == 'KubeCoder' and lo <= e['_num'] <= hi}
    g = [e for e in gaps if e['_proj'] == 'KubeCoder' and lo <= e['_num'] <= hi]
    print(f"  {lo}-{hi}: reports {len(reps)}, gap entries {len(g)}, per report {len(g)/max(1,len(reps)):.1f}")

# identifiers a closed gap names, met again later
IDENT = re.compile(r"`([A-Za-z_][\w./:-]{7,}(?:\(\))?)`")
common = Counter()
for e in allent:
    for t in set(IDENT.findall(e['headline'] + e['_body'])):
        common[t] += 1
closed = [e for e in gaps if e['fate'] == 'close']
hits = []
for g in closed:
    toks = {t for t in IDENT.findall(g['headline'] + g['_body']) if common[t] <= 6}
    if not toks:
        continue
    for e in allent:
        if e['_proj'] != g['_proj'] or e['_num'] <= g['_num'] or e['section'] != 'B' or e['_gap']:
            continue
        shared = toks & set(IDENT.findall(e['headline'] + e['_body']))
        if shared:
            hits.append((g, e, shared))
print(f"\nclosed gap entries: {len(closed)}; with a later non-gap Bug entry sharing a rare identifier: "
      f"{len({(g['_rep'], g['id']) for g, _, _ in hits})} gaps, {len(hits)} pairs")
for g, e, shared in hits[:60]:
    print(f"  {g['_rep']} {g['id']} [{g['severity'] or '-'}] {g['headline'][:80]}")
    print(f"     -> {e['_rep']} {e['id']} [{e['fate']}] {e['headline'][:90]}   shared: {sorted(shared)[:4]}")

# ---- the gap list for the defect check, and the themes
allgap = [e for e in allent if e['section'] in 'BS' and e['fate'] == 'close'
          and (e['_gap'] or truth.get((e['_rep'], e['id'])) == 'test gaps')]
runs = {f"{r['project']}-{r['slice'][:3]}": (r['slice'], r['run'][:10]) for r in d}
THEMES = {
    "wiring / composition root / call site unpinned": r"wiring|composition root|call site|field-injected|main\.py",
    "cross-component or cross-repo contract without a gate": r"hand-mirror|hand-maintain|cross-repo|cross-compo|drift|contract .{0,40}no gate|against each other",
    "boundary or threshold value": r"boundary|threshold|exact-fit|default val|only from below",
    "a test that cannot fail as written": r"vacuous|catches its own|try/catch|cannot observe|never writes|50 ms sleep|survives",
}
print(f"\nclosed gap entries, keyword class or sorter's bucket: {len(allgap)}")
for name, rx in THEMES.items():
    s = [e for e in allgap if re.search(rx, e['headline'], re.I)]
    print(f"  {name}: {len(s)} in {len({e['_rep'] for e in s})} reports")
with open('/tmp/co/focus/closed-gaps.md', 'w') as f:
    for e in sorted(allgap, key=lambda e: (e['_proj'], e['_num'], e['id'])):
        slug, date = runs[e['_rep']]
        body = re.sub(r"\s+", " ", e['_body'])[:900]
        f.write(f"## {e['_proj']} slice {slug} — {e['id']} — closed; run of {date}; grade {e['severity'] or 'none'}; {e['evidence'] or 'evidence unstated'}\n\n{body}\n\n")
print("written", len(allgap))
