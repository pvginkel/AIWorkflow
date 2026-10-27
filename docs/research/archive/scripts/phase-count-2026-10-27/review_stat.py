"""Phase size from the round-1 code-reviewer's first `--stat` summary line."""
import glob, json, re
from pathlib import Path
STAT = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
import sys
F_IN = sys.argv[1] if len(sys.argv) > 1 else "slices.json"
S = {s["slice"]: s for s in json.load(open(F_IN))}


def first_stat(path):
    try:
        fh = open(path, errors="replace")
    except OSError:
        return None
    for line in fh:
        if '"tool_result"' not in line or "changed" not in line:
            continue
        o = json.loads(line)
        if o.get("type") != "user":
            continue
        for b in (o.get("message") or {}).get("content") or []:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            c = b.get("content")
            txt = c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
            m = STAT.search(txt)
            if m:
                return int(m.group(1)), int(m.group(2) or 0) + int(m.group(3) or 0)
    return None


for sp in glob.glob("/work/scratch/**/slices/**/state.json", recursive=True):
    sd = Path(sp).parent
    if sd.name not in S or "phase-count" in sp:
        continue
    st = json.loads(Path(sp).read_text())
    if (st.get("created_at") or "")[:10] != S[sd.name]["created"]:
        continue
    per = {}
    for h in st.get("history", []):
        if h.get("role") == "code-reviewer" and h.get("round") == 1 and h.get("transcript") and h.get("phase") not in per:
            per[h["phase"]] = first_stat(h["transcript"])
    phases = list((st.get("phases") or {}).keys())
    got = [per.get(p) for p in phases]
    S[sd.name]["review_lines"] = sum(g[1] for g in got if g)
    S[sd.name]["review_files"] = sum(g[0] for g in got if g)
    S[sd.name]["review_cov"] = [sum(1 for g in got if g), len(phases)]
json.dump(list(S.values()), open(F_IN, "w"), indent=1)
cov = [s.get("review_cov", [0, 1]) for s in S.values()]
print("fully covered", sum(a == b for a, b in cov), "of", len(cov), "| >=80%", sum(a >= .8 * b for a, b in cov))
