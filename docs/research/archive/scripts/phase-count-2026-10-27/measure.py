#!/usr/bin/env python3
"""Per-slice cost split into plan loop / phase work / per-slice fixed run overhead, 5.5-era slices."""
import glob, json, re, subprocess, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import slice_cost as sc

REPOS = {"KubeCoder": "/work/scratch/KubeCoderSpecs", "Ansible": "/work/scratch/AnsibleSpecs",
         "PilotApp": "/work/scratch/pilotappspecs", "FieldnotesApp": "/work/scratch/FieldnotesAppSpecs"}
for d in glob.glob("/work/scratch/specs-extra/*"):
    REPOS[Path(d).name.removesuffix("Specs")] = d
ROOT = {"/work/KubeCoder": "/work/scratch/KubeCoder", "/work/PilotApp": "/work/scratch/pilotapp",
        "/work/Ansible": "/work/scratch/Ansible"}
SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-22"
UNTIL = sys.argv[2] if len(sys.argv) > 2 else "9999"
OUT = sys.argv[3] if len(sys.argv) > 3 else "/work/scratch/phase-count/slices.json"


ALIAS = {"PilotAppSpecs": "pilotappspecs", "PilotApp": "pilotapp"}


def repo_for(root):
    name = Path(root).name
    for cand in (Path("/work/scratch") / ALIAS.get(name, name), Path("/work/scratch/phase-count/repos") / name):
        if (cand / ".git").exists():
            return str(cand)
    return None


def diff_lines(state):
    """(lines changed by the slice's landed phases, phases measured, phases total)."""
    tot = measured = n = 0
    for p in (state.get("phases") or {}).values():
        n += 1
        l = p.get("landed") or {}
        repo = repo_for(l["root"]) if l.get("root") else None
        if not repo or not l.get("base") or not l.get("head"):
            continue
        r = subprocess.run(["git", "-C", repo, "diff", "--shortstat", l["base"], l["head"]],
                           capture_output=True, text=True)
        if r.returncode:
            continue
        measured += 1
        tot += sum(map(int, re.findall(r"(\d+) (?:insertion|deletion)", r.stdout)))
    return tot, measured, n


def bucket(c):
    top = c
    while top.parent is not None:
        top = top.parent
    if top.loop == "plan":
        return "plan"
    if top.role == "orchestrator:run":
        return "run-orch"
    if top.appended:
        return "appended"
    if top.role in ("code-writer", "code-reviewer") and top.phase is not None:
        return "phase"
    return {"consult": "consult", "test-agent": "test", "doc-writer": "doc",
            "wrap-up": "wrap-up"}.get(top.role, "other")


out = []
for proj, repo in REPOS.items():
    for sp in glob.glob(f"{repo}/slices/**/state.json", recursive=True):
        sd = Path(sp).parent
        s = json.loads(Path(sp).read_text())
        if not (SINCE <= (s.get("created_at") or "") < UNTIL) or (s.get("doc_phase") or {}).get("stage") != "done":
            continue
        try:
            ps = json.loads((sd / "plan_state.json").read_text())
        except (OSError, json.JSONDecodeError):
            ps = {}
        convs, warns = sc.collect(sd)
        cost = defaultdict(float)
        old_model = 0.0
        for c in convs:
            cost[bucket(c)] += c.cost()
            for m, tok in c.tok_by_model.items():
                if m == "claude-opus-5":
                    old_model += sc.cost_for(m, tok)
        appended = {str(p) for p in s.get("appended_phases") or []}
        planned = [k for k in (s.get("phases") or {}) if str(k) not in appended]
        total = sum(cost.values())
        out.append({"project": proj, "slice": sd.name, "created": s["created_at"][:10],
                    "plan_created": (ps.get("created_at") or "")[:10], "plugin": s.get("plugin_version"),
                    "planned": len(planned), "appended": len(appended), "cost": dict(cost),
                    "total": total, "old_model_share": old_model / total if total else 0,
                    "lines": diff_lines(s), "missing": len(warns),
                    "has_wrap_up": cost.get("wrap-up", 0) > 0})
json.dump(out, open(OUT, "w"), indent=1)
print(len(out), "slices")
