#!/usr/bin/env python3
"""Peak context size of every session the loops recorded, per project, since a cut-off.

Usage: collect.py <since YYYY-MM-DD> <project>=<spec-repo> ... > sessions.json
"""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "/work/AIWorkflow/plugins/dev/tools")
import slice_cost  # noqa: E402


def peak(path: Path) -> dict:
    seen, best, last, turns = set(), 0, 0, 0
    model = None
    for line in path.read_text(errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        u = msg.get("usage")
        mid = msg.get("id")
        if not u or (mid and mid in seen):
            continue
        if mid:
            seen.add(mid)
        if msg.get("model") == "<synthetic>":
            continue
        turns += 1
        model = msg.get("model") or model
        size = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                              "cache_creation_input_tokens", "output_tokens"))
        best = max(best, size)
        last = size
    return {"peak": best, "last": last, "turns": turns, "model": model}


since = datetime.fromisoformat(sys.argv[1]).replace(tzinfo=UTC)
rows, warns = [], []
for arg in sys.argv[2:]:
    project, repo = arg.split("=", 1)
    dirs = {p.parent for n in ("state.json", "plan_state.json")
            for p in Path(repo, "slices").rglob(n)}
    for d in sorted(dirs):
        try:
            convs, w = slice_cost.collect(d)
        except FileNotFoundError:
            continue
        warns += [f"{project} {d.name}: {x}" for x in w]
        for c in convs:
            if not c.start or c.start < since:
                continue
            rows.append({"project": project, "slice": d.name, "kind": c.kind,
                         "role": c.role, "phase": c.phase, "loop": c.loop,
                         "start": c.start.isoformat(), "session": c.session, "round": c.round,
                         "transcript": str(c.transcript), "slice_dir": str(d),
                         **peak(c.transcript)})
json.dump({"rows": rows, "warnings": warns}, sys.stdout, indent=0)
