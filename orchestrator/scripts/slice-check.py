#!/usr/bin/env python3
"""Structural lint and citation check for a slice authored by /write-slice.

Two subcommands:

  lint <slice>   Structural lint of the slice's documents — JSON validity,
                 AC id prefixes, the forbidden `status` field, brief
                 locations, grounding_check.md sections, README Pending
                 entry, brief word-count ceilings. Silent on success;
                 prints findings (FAIL / WARN) otherwise.

  cite <slice>   Parse every `file:line` citation out of the briefs, hard-
                 fail any pointing at a missing file or an out-of-range
                 line (stale line numbers — the failure mode write-slice
                 Step 7b exists to catch), and dump `citation → line
                 content` so the semantic grounding check reads one block
                 instead of opening every file.

The slice argument is a number/prefix (e.g. "182") or a directory path.
`lint` covers the mechanical half of the write-slice quality checklist;
the semantic items (every request → an AC, outcomes-not-implementation)
still need a human read.

## Customize for your project

- `SPECS_ROOT` — the specs repo holding the slices/ tree.
- `BRIEF_SUBPROJECTS` / `CODE_SUBPROJECTS` — your project's subprojects.
- `AC_ID_PREFIXES` — the acceptance-criteria id prefixes you use.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Path to the specs repo holding the slices/ tree — customize for your project.
SPECS_ROOT = REPO_ROOT.parent / "ProjectSpecs"
SLICES_DIR = SPECS_ROOT / "slices"
LIFECYCLE_SUBDIRS = ["completed", "deferred", "cancelled"]

# Subprojects that may carry a brief, and the recognised AC id prefixes.
# An id starts with one of these (e.g. BE-01) — a compound form such as
# RE-ROOT-01 is fine as long as the first segment is a known prefix.
BRIEF_SUBPROJECTS = ["root", "backend", "frontend", "portal"]
AC_ID_PREFIXES = ("BE", "FE", "PO", "RE")

# Code subprojects searched when resolving a bare-filename citation.
CODE_SUBPROJECTS = ["backend", "frontend", "portal"]
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv",
             "coverage", ".pytest_cache", ".turbo"}

# A citation is a path with one of these extensions, then :line or :line-line.
CITATION_RE = re.compile(
    r"(?<![\w/])([\w./-]+\.(?:py|ts|tsx|js|jsx|mjs|cjs|json|md|sh|ya?ml|toml|"
    r"css|scss|html|sql|txt|cfg|ini|lock)):(\d+)(?:-(\d+))?\b"
)

# Brief word-count hard ceiling for minor-workflow briefs (write-slice).
MINOR_BRIEF_CEILING = 1000


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


def slice_briefs(slice_dir: Path) -> list[tuple[str, Path]]:
    """(subproject, brief path) for every brief in the slice."""
    return [
        (s, slice_dir / s / "brief.md")
        for s in BRIEF_SUBPROJECTS
        if (slice_dir / s / "brief.md").is_file()
    ]


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

def lint(slice_dir: Path) -> int:
    fails: list[str] = []
    warns: list[str] = []

    # acceptance_criteria.json
    ac_path = slice_dir / "acceptance_criteria.json"
    ac_ids: set[str] = set()
    if not ac_path.is_file():
        fails.append("acceptance_criteria.json is missing")
    else:
        try:
            ac = json.loads(ac_path.read_text())
        except json.JSONDecodeError as e:
            fails.append(f"acceptance_criteria.json is not valid JSON: {e}")
            ac = None
        if ac is not None:
            criteria = ac.get("criteria")
            if not isinstance(criteria, list) or not criteria:
                fails.append("acceptance_criteria.json has no non-empty 'criteria' array")
            else:
                for i, c in enumerate(criteria, start=1):
                    if not isinstance(c, dict):
                        fails.append(f"criterion #{i} is not an object")
                        continue
                    for field in ("id", "area", "description"):
                        if field not in c:
                            fails.append(f"criterion #{i} is missing '{field}'")
                    cid = c.get("id", "")
                    if cid:
                        ac_ids.add(cid)
                        prefix = cid.split("-", 1)[0]
                        if prefix not in AC_ID_PREFIXES or not any(ch.isdigit() for ch in cid):
                            warns.append(
                                f"criterion '{cid}' id uses an unrecognised prefix — "
                                f"write-slice documents {'-/'.join(AC_ID_PREFIXES)}-"
                            )
                    if "status" in c:
                        fails.append(
                            f"criterion '{cid or i}' has a forbidden 'status' field "
                            f"— verdicts live in verification.json"
                        )

    # api_contract.json
    contract_path = slice_dir / "api_contract.json"
    if not contract_path.is_file():
        fails.append("api_contract.json is missing")
    else:
        try:
            json.loads(contract_path.read_text())
        except json.JSONDecodeError as e:
            fails.append(f"api_contract.json is not valid JSON: {e}")

    # Brief locations
    if (slice_dir / "brief.md").exists():
        fails.append("a brief.md exists at the slice root — briefs belong in <project>/brief.md")
    briefs = slice_briefs(slice_dir)
    if not briefs:
        fails.append("no <project>/brief.md found (expected at least one)")

    # grounding_check.md — exists, with a section per brief
    grounding_path = slice_dir / "grounding_check.md"
    if briefs and not grounding_path.is_file():
        fails.append("grounding_check.md is missing (required when any brief exists)")
    elif briefs:
        grounding_text = grounding_path.read_text()
        for project, _ in briefs:
            heading = re.compile(rf"^##\s+{re.escape(project)}/brief\.md\s*$", re.MULTILINE)
            if not heading.search(grounding_text):
                fails.append(f"grounding_check.md has no '## {project}/brief.md' section")

    # Each brief references at least one real AC id, and word count
    ac_id_re = (
        re.compile(r"\b(?:" + "|".join(re.escape(i) for i in sorted(ac_ids)) + r")\b")
        if ac_ids
        else None
    )
    for project, brief_path in briefs:
        text = brief_path.read_text()
        if ac_id_re and not ac_id_re.search(text):
            fails.append(f"{project}/brief.md references no acceptance-criteria id")
        words = len(text.split())
        if words > MINOR_BRIEF_CEILING:
            warns.append(
                f"{project}/brief.md is {words} words — over the {MINOR_BRIEF_CEILING}-word "
                f"minor-brief ceiling (fine for a major-workflow brief; trim otherwise)"
            )

    # README Pending entry
    number = slice_dir.name.split("_", 1)[0]
    readme_path = SPECS_ROOT / "README.md"
    if not readme_path.is_file():
        warns.append(f"README.md not found at {readme_path} — skipped Pending check")
    else:
        readme = readme_path.read_text()
        m = re.search(r"^##\s+Pending\s*$(.*?)(?=^##\s)", readme, re.MULTILINE | re.DOTALL)
        pending = m.group(1) if m else ""
        if not m:
            warns.append("README.md has no '## Pending' section — skipped Pending check")
        elif f"**{number}**" not in pending:
            fails.append(f"slice {number} is not listed in the README '## Pending' section")

    # Report
    for w in warns:
        print(f"WARN  {w}")
    for f in fails:
        print(f"FAIL  {f}")
    if fails:
        print(f"\nslice-check lint: {len(fails)} failure(s), {len(warns)} warning(s) — {slice_dir.name}")
        return 1
    return 0


# --------------------------------------------------------------------------
# cite
# --------------------------------------------------------------------------

_basename_index: dict[str, list[Path]] | None = None


def basename_index() -> dict[str, list[Path]]:
    """Lazily index code-subproject files by basename for bare-filename citations."""
    global _basename_index
    if _basename_index is not None:
        return _basename_index
    index: dict[str, list[Path]] = {}
    for sp in CODE_SUBPROJECTS:
        root = REPO_ROOT / sp
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            index.setdefault(path.name, []).append(path)
    _basename_index = index
    return index


def resolve_citation(cited: str, project: str) -> tuple[Path | None, str]:
    """Resolve a cited path. Returns (path, status); status in
    {found, missing, ambiguous}."""
    if "/" in cited:
        candidates = [REPO_ROOT / cited]
        if project:
            candidates.append(REPO_ROOT / project / cited)
        for sp in CODE_SUBPROJECTS:
            candidates.append(REPO_ROOT / sp / cited)
        for c in candidates:
            if c.is_file():
                return c, "found"
        return None, "missing"
    # Bare filename — resolve by unique basename within the code subprojects.
    matches = basename_index().get(cited, [])
    if len(matches) == 1:
        return matches[0], "found"
    if not matches:
        return None, "missing"
    return None, "ambiguous"


def cite(slice_dir: Path) -> int:
    briefs = slice_briefs(slice_dir)
    if not briefs:
        print(f"slice-check cite: no briefs in {slice_dir.name} — nothing to check")
        return 0

    broken: list[str] = []
    dump: list[str] = []
    total = 0

    for project, brief_path in briefs:
        lines = brief_path.read_text().splitlines()
        seen: set[tuple[str, int, int]] = set()
        brief_dump: list[str] = []
        for ln in lines:
            for m in CITATION_RE.finditer(ln):
                cited, start_s, end_s = m.group(1), m.group(2), m.group(3)
                start = int(start_s)
                end = int(end_s) if end_s else start
                key = (cited, start, end)
                if key in seen:
                    continue
                seen.add(key)
                total += 1
                label = f"{cited}:{start}" + (f"-{end}" if end != start else "")
                path, status = resolve_citation(cited, project)
                if status == "missing":
                    broken.append(f"{project}/brief.md: {label} — file not found")
                    brief_dump.append(f"  {label}  ✗ file not found")
                    continue
                if status == "ambiguous":
                    n = len(basename_index().get(cited, []))
                    broken.append(
                        f"{project}/brief.md: {label} — bare filename matches "
                        f"{n} files, cite a path"
                    )
                    brief_dump.append(f"  {label}  ✗ ambiguous ({n} matches)")
                    continue
                assert path is not None
                file_lines = path.read_text(errors="replace").splitlines()
                if start < 1 or end > len(file_lines) or start > end:
                    broken.append(
                        f"{project}/brief.md: {label} — line out of range "
                        f"({path.relative_to(REPO_ROOT)} has {len(file_lines)} lines)"
                    )
                    brief_dump.append(f"  {label}  ✗ out of range (file has {len(file_lines)} lines)")
                    continue
                rel = path.relative_to(REPO_ROOT)
                shown = file_lines[start - 1:end]
                capped = shown[:15]
                for offset, content in enumerate(capped):
                    text = content if len(content) <= 200 else content[:197] + "..."
                    brief_dump.append(f"  {rel}:{start + offset}  │ {text}")
                if len(shown) > len(capped):
                    brief_dump.append(f"  {rel}:{end}  │ ... ({len(shown) - len(capped)} more lines in range)")
        if brief_dump:
            dump.append(f"## {project}/brief.md")
            dump.extend(brief_dump)
            dump.append("")

    print(f"slice-check cite — {slice_dir.name}: {total} citation(s) across {len(briefs)} brief(s)")
    print()
    print("\n".join(dump).rstrip())
    if broken:
        print()
        print(f"BROKEN CITATIONS — {len(broken)}:")
        for b in broken:
            print(f"  {b}")
        return 1
    print()
    print("All citations resolve to an existing file and an in-range line.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_lint = sub.add_parser("lint", help="Structural lint of the slice documents")
    p_lint.add_argument("slice", help="Slice number/prefix (e.g. 182) or directory path")
    p_cite = sub.add_parser("cite", help="Extract and check file:line citations in the briefs")
    p_cite.add_argument("slice", help="Slice number/prefix (e.g. 182) or directory path")
    args = parser.parse_args()

    slice_dir = resolve_slice(args.slice)
    if args.command == "lint":
        return lint(slice_dir)
    if args.command == "cite":
        return cite(slice_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
