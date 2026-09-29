# ruff: noqa
# Ad-hoc, kept as it was run on 2026-09-29: the record of how a table of
# docs/research/close-out-triage-plan-2026-09-29.md § 3 was computed. Reads scratch data under
# /tmp (the plan's § 10 says how to make it again). Owed to close_out_readout.py; this folder
# goes when that is done.
"""Ad-hoc: how right is the Focus line, against the operator's rulings?"""
import json
import re
from collections import Counter, defaultdict

d = json.load(open('/tmp/close-out-entries.json'))
modes = json.load(open('/work/AIWorkflow/docs/research/data/close-out-read-2026-09-28.json'))['report_mode']
RULED = ("card", "fix", "fold", "close")
SEV = {"major": 0, "minor": 1, "": 2, "nit": 3, "cosmetic": 4}


def pct(n, t):
    return f"{100*n/t:.0f} %" if t else "-"


def key(r):
    return f"{r['project']}-{r['slice'][:3]}"


rows = []  # one per ruled entry in B, S with focus position
sections = []  # per (report, section)
for r in d:
    mode = modes.get(key(r), "uncoded")
    own = mode in ("direct", "mixed")
    for sec in ("B", "S", "Q", "N"):
        es = [e for e in r["entries"] if e["section"] == sec and e["fate"] != "in-run"
              and re.fullmatch(r"[ANBQS]\d+", e["id"])]
        if not es:
            continue
        f = r["focus"].get(sec, "")
        ids = {e["id"] for e in es}
        order = []
        for m in re.finditer(r"\b([ANBQS]\d+)\b", f):
            if m.group(1) in ids and m.group(1) not in order:
                order.append(m.group(1))
        for e in es:
            e["_pos"] = order.index(e["id"]) if e["id"] in order else None
            e["_own"] = own
            e["_mode"] = mode
            e["_sec"] = sec
            e["_nlive"] = len(es)
        sections.append({"report": key(r), "sec": sec, "entries": es, "order": order,
                         "own": own, "mode": mode, "focus": f})
        rows.extend(e for e in es if e["fate"] in RULED)


def prog(es):
    return sum(e["progressed"] for e in es), len(es)


def line(label, es):
    n, t = prog(es)
    c = Counter(e["fate"] for e in es)
    print(f"  {label:<46} {t:>4}  progressed {pct(n,t):>5}   card/fold {pct(c['card']+c['fold'],t):>5}"
          f"   fix {pct(c['fix'],t):>5}   close {pct(c['close'],t):>5}")


print("A. Bugs + Suggestions, ruled entries, by place in the Focus line")
bs = [e for e in rows if e["_sec"] in "BS"]
line("all", bs)
line("named first", [e for e in bs if e["_pos"] == 0])
line("named second", [e for e in bs if e["_pos"] == 1])
line("named third or later", [e for e in bs if e["_pos"] is not None and e["_pos"] >= 2])
line("not named", [e for e in bs if e["_pos"] is None])

print("\nB. The same, split by how the report was ruled")
for label, sel in (("own reading (direct, mixed)", lambda e: e["_own"]),
                   ("from a sheet (handed-over, auto)", lambda e: e["_mode"] in ("handed-over", "auto")),
                   ("uncoded", lambda e: e["_mode"] == "uncoded")):
    print(f" {label}")
    sub = [e for e in bs if sel(e)]
    line("all", sub)
    line("named first", [e for e in sub if e["_pos"] == 0])
    line("named later", [e for e in sub if e["_pos"] not in (None, 0)])
    line("not named", [e for e in sub if e["_pos"] is None])

print("\nC. Holding the grade still (Bugs + Suggestions)")
for sev in ("major", "minor", "", "nit", "cosmetic"):
    sub = [e for e in bs if e["severity"] == sev]
    print(f" grade: {sev or 'ungraded'}")
    line("named first", [e for e in sub if e["_pos"] == 0])
    line("named later", [e for e in sub if e["_pos"] not in (None, 0)])
    line("not named", [e for e in sub if e["_pos"] is None])

print("\nD. Sections where the first pick had a choice: >=2 ruled entries, a first-named one,")
print("   and the operator progressed some but not all")
for label, sel in (("all reports", lambda s: True), ("own reading", lambda s: s["own"]),
                   ("from a sheet", lambda s: s["mode"] in ("handed-over", "auto"))):
    n = hit = 0
    chance = 0.0
    sev_hit = 0
    sev_n = 0
    for s in sections:
        if s["sec"] not in "BS" or not sel(s):
            continue
        es = [e for e in s["entries"] if e["fate"] in RULED]
        if len(es) < 2 or not s["order"]:
            continue
        first = next((e for e in es if e["_pos"] == 0), None)
        if first is None:
            continue
        p = sum(e["progressed"] for e in es)
        if p == 0 or p == len(es):
            continue
        n += 1
        hit += first["progressed"]
        chance += p / len(es)
        top = min(SEV[e["severity"]] for e in es)
        tops = [e for e in es if SEV[e["severity"]] == top]
        if len(tops) < len(es):  # the grade makes a choice too
            sev_n += 1
            sev_hit += sum(e["progressed"] for e in tops) / len(tops)
    print(f"  {label:<14} sections {n:>3}   first pick progressed {pct(hit,n):>5}"
          f"   a random entry {pct(chance,n):>5}   the top grade ({sev_n} sections) {pct(sev_hit,sev_n):>5}")

print("\nE. Sections with at least one entry progressed: where was the operator's pick?")
for label, sel in (("all reports", lambda s: True), ("own reading", lambda s: s["own"])):
    secs = picks = first = later = unnamed = 0
    first_closed_other_progressed = 0
    for s in sections:
        if s["sec"] not in "BS" or not sel(s):
            continue
        es = [e for e in s["entries"] if e["fate"] in RULED]
        pr = [e for e in es if e["progressed"]]
        if not pr or not s["order"]:
            continue
        secs += 1
        picks += len(pr)
        first += sum(e["_pos"] == 0 for e in pr)
        later += sum(e["_pos"] not in (None, 0) for e in pr)
        unnamed += sum(e["_pos"] is None for e in pr)
        f = next((e for e in es if e["_pos"] == 0), None)
        if f is not None and not f["progressed"]:
            first_closed_other_progressed += 1
    print(f"  {label:<12} sections {secs}, picks {picks}: named first {pct(first,picks)},"
          f" named later {pct(later,picks)}, not named {pct(unnamed,picks)};"
          f" first pick closed while another was progressed: {first_closed_other_progressed} sections"
          f" ({pct(first_closed_other_progressed,secs)})")

print("\nF. How much the line names")
live = [e for s in sections if s["sec"] in "BS" for e in s["entries"]]
named = [e for e in live if e["_pos"] is not None]
print(f"  B+S live entries {len(live)}, named {len(named)} ({pct(len(named),len(live))})")
per = [len(s['order'])/len(s['entries']) for s in sections if s['sec'] in 'BS' and len(s['entries']) >= 3]
full = sum(1 for p in per if p >= 0.99)
print(f"  sections with >=3 live entries: {len(per)}; the line names every entry in {full} ({pct(full,len(per))})")
words = [len(s['focus'].split()) for s in sections if s['sec'] in 'BS']
words.sort()
print(f"  words per B/S Focus line over a non-empty section: median {words[len(words)//2]}, p90 {words[int(len(words)*.9)]}")
