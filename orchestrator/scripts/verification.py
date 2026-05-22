#!/usr/bin/env python3
"""Seed and tally a slice's verification log.

`verification.json` is the single source of truth for the slice's
independent verifier (run-slice Step 8c). This script owns the two
mechanical operations on it:

  seed <slice>    Generate verification.json from acceptance_criteria.json
                  — one item per AC, in entry order, ids V01.., source "ac".
  tally <slice>   Count source:"ac" items by verdict.

The slice argument is a number or prefix (e.g. "182", "182b") resolved to
the slice directory under <specs>/slices/, or an explicit directory path.

`qa_correction` items are appended to verification.json by hand during
run-slice Steps 1/4/5 (judgment — they record direction changes). `seed`
never invents them; `tally` reports only `source:"ac"` items, which is
what the Step 10 acceptance-criteria check counts.

## Customize for your project

- `SPECS_ROOT` — the specs repo holding the slices/ tree.
- `AGENT_AREAS` / `BRIEF_SUBPROJECTS` — your project's subproject names.
  A verification item's `area` must name a subproject the verifier can
  route a failure back to.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Path to the specs repo holding the slices/ tree — customize for your
# project (typically a sibling checkout next to the monorepo).
SPECS_ROOT = REPO_ROOT.parent / "ProjectSpecs"
SLICES_DIR = SPECS_ROOT / "slices"

# Lifecycle subfolders a slice may live under, besides the pending top level.
LIFECYCLE_SUBDIRS = ["completed", "deferred", "cancelled"]

# Verdict values the verifier writes, in report order.
VERDICTS = ["passed", "failed", "uncertain"]

# A verification item's `area` must name an agent the verifier can route a
# failure back to (run-slice Step 8c). Regression criteria carry area
# "regression" in acceptance_criteria.json — not an agent — so they are
# remapped to the owning subproject; see cmd_seed.
AGENT_AREAS = {"root", "backend", "frontend", "portal"}
BRIEF_SUBPROJECTS = ["root", "backend", "frontend", "portal"]


def slice_subprojects(slice_dir: Path) -> list[str]:
    """Subprojects with a brief in this slice — the agents that will run."""
    return [s for s in BRIEF_SUBPROJECTS if (slice_dir / s / "brief.md").exists()]


def resolve_slice(arg: str) -> Path:
    """Resolve a slice number/prefix (or explicit path) to its directory."""
    arg = arg.strip().rstrip("/")
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate.resolve()
    search_roots = [SLICES_DIR, *(SLICES_DIR / s for s in LIFECYCLE_SUBDIRS)]
    matches: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child.name == arg or child.name.startswith(arg + "_")):
                matches.append(child)
    if not matches:
        sys.exit(f"error: no slice directory matching '{arg}' under {SLICES_DIR}")
    if len(matches) > 1:
        listing = "\n  ".join(str(m) for m in matches)
        sys.exit(f"error: '{arg}' matches multiple slices:\n  {listing}")
    return matches[0].resolve()


def cmd_seed(slice_dir: Path, force: bool) -> int:
    ac_path = slice_dir / "acceptance_criteria.json"
    out_path = slice_dir / "verification.json"
    if not ac_path.exists():
        sys.exit(f"error: {ac_path} not found")
    if out_path.exists() and not force:
        sys.exit(
            f"error: {out_path} already exists — pass --force to overwrite "
            f"(this discards any verdicts already recorded in it)"
        )
    try:
        ac = json.loads(ac_path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"error: {ac_path} is not valid JSON: {e}")
    criteria = ac.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        sys.exit(f"error: {ac_path} has no non-empty 'criteria' array")

    subprojects = slice_subprojects(slice_dir)
    items: list[dict] = []
    unrouted: list[str] = []
    for i, c in enumerate(criteria, start=1):
        if not isinstance(c, dict) or not {"id", "area", "description"} <= c.keys():
            sys.exit(f"error: criterion #{i} is missing id/area/description")
        # The verification `area` must name an agent. AC areas that already
        # do (backend/frontend/portal/root) pass through. A non-agent area
        # (regression criteria) routes to the slice's sole subproject when
        # there is exactly one; otherwise it is left verbatim and flagged.
        ac_area = c["area"]
        if ac_area in AGENT_AREAS:
            area = ac_area
        elif len(subprojects) == 1:
            area = subprojects[0]
        else:
            area = ac_area
            unrouted.append(f"V{i:02d} ({c['id']}, area={ac_area!r})")
        items.append(
            {
                "id": f"V{i:02d}",
                "source": "ac",
                "area": area,
                "description": f"{c['id']}: {c['description']}",
                "verdict": None,
                "rationale": "",
                "evidence": [],
            }
        )

    out_path.write_text(json.dumps({"items": items}, indent=2, ensure_ascii=False) + "\n")
    print(
        f"Seeded {out_path}: {len(items)} items "
        f"(V01–V{len(items):02d}) from {len(criteria)} acceptance criteria"
    )
    if unrouted:
        print(
            "\nACTION REQUIRED: the slice has multiple subprojects, so these "
            "items\nkept a non-routable area — assign each to an owning agent "
            "before Step 1:\n  " + "\n  ".join(unrouted)
        )
    return 0


def cmd_tally(slice_dir: Path) -> int:
    v_path = slice_dir / "verification.json"
    if not v_path.exists():
        sys.exit(f"error: {v_path} not found — run 'seed' first")
    try:
        data = json.loads(v_path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"error: {v_path} is not valid JSON: {e}")
    items = data.get("items", [])
    ac_items = [it for it in items if it.get("source") == "ac"]

    counts: dict[str, int] = {}
    for it in ac_items:
        key = it.get("verdict") or "(unverified)"
        counts[key] = counts.get(key, 0) + 1

    print(f"AC verification tally — {slice_dir.name}")
    print(f"  source:ac items: {len(ac_items)}")
    for verdict in VERDICTS:
        print(f"  {verdict + ':':<14}{counts.get(verdict, 0)}")
    known = {*VERDICTS, "(unverified)"}
    extra = sorted(k for k in counts if k not in known)
    for key in ["(unverified)", *extra]:
        if counts.get(key):
            print(f"  {key + ':':<14}{counts[key]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="Generate verification.json from acceptance_criteria.json")
    p_seed.add_argument("slice", help="Slice number/prefix (e.g. 182) or directory path")
    p_seed.add_argument(
        "--force", action="store_true", help="Overwrite an existing verification.json"
    )

    p_tally = sub.add_parser("tally", help="Count source:ac items by verdict")
    p_tally.add_argument("slice", help="Slice number/prefix (e.g. 182) or directory path")

    args = parser.parse_args()
    slice_dir = resolve_slice(args.slice)
    if args.command == "seed":
        return cmd_seed(slice_dir, args.force)
    if args.command == "tally":
        return cmd_tally(slice_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
