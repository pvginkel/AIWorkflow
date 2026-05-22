#!/usr/bin/env python3
"""Verify a slice's api_contract.json against the generated OpenAPI spec.

Run at run-slice Step 3, after the OpenAPI cache is regenerated. Loads
the generated spec and the slice's api_contract.json, checks every
endpoint and endpoint-removal mechanically, sets each entry's `verified`
flag, writes api_contract.json back, and prints a compact report.

What it verifies, deterministically:

- **endpoints** — method + path exist in the spec (path params normalised,
  `/api` prefix tried); declared 2xx status codes are documented;
  `key_request_fields` / `key_response_fields` appear in the request /
  response schemas, resolving `$ref` / `allOf` / `anyOf` / `oneOf` chains.
  `verified` = endpoint found AND 2xx codes documented AND key fields
  present. Missing 4xx/5xx codes are reported as a note only — error
  responses are routinely served by framework error handlers and not
  annotated in the spec — they do not flip `verified`.
- **removals** with a method + path — the method/path is confirmed absent.

What it cannot verify, and reports under "Manual review" without a
verdict: `schema_changes` and prose `removals` (no method/path). Those
are free-text claims; the orchestrator inspects them. The script never
decides whether a `verified: false` is a significant gap — that call,
and the stop, stay with the orchestrator.

## Customize for your project

- `SPECS_ROOT` — the specs repo holding the slices/ tree.
- `DEFAULT_SPECS` — where the generated OpenAPI cache(s) live.
- The `/api` prefix tried in `find_op` assumes API paths are mounted
  under `/api`; adjust if your routes are mounted elsewhere.
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

# OpenAPI cache locations, in preference order, when --spec is not given.
# Customize for your project's generated-client cache paths.
DEFAULT_SPECS = [
    REPO_ROOT / "frontend" / "openapi-cache" / "openapi.json",
    REPO_ROOT / "portal" / "openapi-cache" / "openapi.json",
]

_PARAM_RE = re.compile(r"[<{][^<>{}]*[>}]")


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


def normalise_path(path: str) -> str:
    """Canonicalise a path so `<id>`-style and `{id}`-style params match."""
    return _PARAM_RE.sub("{}", path.strip()).rstrip("/") or "/"


def load_json(path: Path, label: str) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        sys.exit(f"error: {label} not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"error: {label} is not valid JSON ({path}): {e}")


def resolve_ref(spec: dict, ref: str) -> dict | None:
    if not ref.startswith("#/"):
        return None
    node: object = spec
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def collect_fields(node: object, spec: dict, seen: set[str]) -> set[str]:
    """All property names reachable in a schema node, resolving refs/combiners."""
    fields: set[str] = set()
    if not isinstance(node, dict):
        return fields
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return fields
        seen.add(ref)
        target = resolve_ref(spec, ref)
        if target is not None:
            fields |= collect_fields(target, spec, seen)
        return fields
    for combiner in ("allOf", "anyOf", "oneOf"):
        for sub in node.get(combiner, []) or []:
            fields |= collect_fields(sub, spec, seen)
    props = node.get("properties")
    if isinstance(props, dict):
        for pname, pschema in props.items():
            fields.add(pname)
            fields |= collect_fields(pschema, spec, seen)
    for nested in ("items", "additionalProperties"):
        if isinstance(node.get(nested), dict):
            fields |= collect_fields(node[nested], spec, seen)
    return fields


def request_schema(op: dict) -> dict | None:
    content = (op.get("requestBody") or {}).get("content") or {}
    for c in content.values():
        if isinstance(c, dict) and "schema" in c:
            return c["schema"]
    return None


def response_schemas(op: dict, codes: list[str]) -> list[dict]:
    responses = op.get("responses") or {}
    out: list[dict] = []
    for code in codes:
        r = responses.get(code)
        if not isinstance(r, dict):
            continue
        for c in (r.get("content") or {}).values():
            if isinstance(c, dict) and "schema" in c:
                out.append(c["schema"])
    return out


def build_path_index(spec: dict) -> dict[str, tuple[str, dict]]:
    index: dict[str, tuple[str, dict]] = {}
    for raw, methods in (spec.get("paths") or {}).items():
        if isinstance(methods, dict):
            index[normalise_path(raw)] = (raw, methods)
    return index


def find_op(index: dict, path: str, method: str) -> tuple[str, dict] | None:
    """Locate (raw_path, operation) for a contract path, trying the /api prefix."""
    candidates = [normalise_path(path)]
    if not path.startswith("/api"):
        candidates.append(normalise_path("/api" + ("" if path.startswith("/") else "/") + path))
    for norm in candidates:
        if norm in index:
            raw, methods = index[norm]
            op = methods.get(method.lower())
            if isinstance(op, dict):
                return raw, op
            return raw, {}  # path matched, method did not
    return None


def check_endpoint(ep: dict, index: dict, spec: dict) -> dict:
    method = str(ep.get("method", "")).upper()
    path = str(ep.get("path", ""))
    status_codes = [str(c) for c in ep.get("status_codes", []) or []]
    req_fields = list(ep.get("key_request_fields", []) or [])
    resp_fields = list(ep.get("key_response_fields", []) or [])
    notes: list[str] = []

    located = find_op(index, path, method)
    if located is None:
        return {"verified": False, "notes": ["path not found in spec"]}
    raw, op = located
    if not op:
        return {"verified": False, "notes": [f"path '{raw}' found but method {method} is not defined"]}

    responses = op.get("responses") or {}
    documented = set(responses.keys())
    success = [c for c in status_codes if c.isdigit() and 200 <= int(c) < 300]
    errors = [c for c in status_codes if c not in success]
    missing_success = [c for c in success if c not in documented]
    missing_errors = [c for c in errors if c not in documented]
    if not responses:
        notes.append("endpoint has no responses documented in the spec")
    if missing_success:
        notes.append(f"2xx status codes absent from spec: {', '.join(missing_success)}")
    if missing_errors:
        notes.append(
            f"4xx/5xx status codes absent (informational — often framework "
            f"error handlers): {', '.join(missing_errors)}"
        )

    missing_req: list[str] = []
    if req_fields:
        rschema = request_schema(op)
        if rschema is None:
            notes.append("key_request_fields declared but spec has no request body schema")
            missing_req = req_fields
        else:
            present = collect_fields(rschema, spec, set())
            missing_req = [f for f in req_fields if f not in present]
            if missing_req:
                notes.append(f"key_request_fields absent from request schema: {', '.join(missing_req)}")

    missing_resp: list[str] = []
    if resp_fields:
        codes = success or [c for c in documented if c.isdigit() and 200 <= int(c) < 300]
        codes = codes or sorted(documented)
        schemas = response_schemas(op, codes)
        if not schemas:
            notes.append("key_response_fields declared but spec has no response schema for it")
            missing_resp = resp_fields
        else:
            present = set()
            for s in schemas:
                present |= collect_fields(s, spec, set())
            missing_resp = [f for f in resp_fields if f not in present]
            if missing_resp:
                notes.append(f"key_response_fields absent from response schema: {', '.join(missing_resp)}")

    verified = not missing_success and not missing_req and not missing_resp and bool(responses)
    return {"verified": verified, "notes": notes, "raw_path": raw}


def check_removal(rm: dict, index: dict) -> dict | None:
    """Verify an endpoint removal; return None if it is a prose-only entry."""
    method = rm.get("method")
    path = rm.get("path")
    if not method or not path:
        return None
    located = find_op(index, str(path), str(method))
    if located is None:
        return {"verified": True, "notes": ["confirmed absent from spec"]}
    raw, op = located
    if not op:
        return {"verified": True, "notes": [f"path '{raw}' exists but method {method} is absent"]}
    return {"verified": False, "notes": [f"still present in spec as {method} {raw} — not removed"]}


def schema_present(spec: dict, name: str) -> bool:
    schemas = (spec.get("components") or {}).get("schemas") or {}
    return any(k == name or k.startswith(name + ".") for k in schemas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slice", help="Slice number/prefix (e.g. 182) or directory path")
    parser.add_argument("--spec", help="Path to the OpenAPI spec JSON (default: frontend then portal cache)")
    args = parser.parse_args()

    slice_dir = resolve_slice(args.slice)
    contract_path = slice_dir / "api_contract.json"
    contract = load_json(contract_path, "api_contract.json")

    endpoints = contract.get("endpoints")
    if not endpoints and "changes" in contract:
        print(f"API contract check — {slice_dir.name}")
        print("No API changes (non-API contract). Nothing to verify.")
        return 0

    if args.spec:
        spec_path = Path(args.spec)
    else:
        spec_path = next((p for p in DEFAULT_SPECS if p.exists()), DEFAULT_SPECS[0])
    spec = load_json(spec_path, "OpenAPI spec")
    index = build_path_index(spec)

    print(f"API contract check — {slice_dir.name}")
    print(f"Spec: {spec_path} ({len(index)} paths, "
          f"{len((spec.get('components') or {}).get('schemas') or {})} schemas)")

    endpoints = endpoints or []
    removals = contract.get("removals") or []
    schema_changes = contract.get("schema_changes") or []

    ep_verified = 0
    print(f"\nEndpoints — {len(endpoints)}")
    for ep in endpoints:
        result = check_endpoint(ep, index, spec)
        ep["verified"] = result["verified"]
        if result["verified"]:
            ep_verified += 1
        mark = "[ok]  " if result["verified"] else "[FAIL]"
        print(f"  {mark} {ep.get('id', '?'):<7} {str(ep.get('method', '')).upper():<6} {ep.get('path', '')}")
        for note in result["notes"]:
            print(f"           - {note}")

    endpoint_removals = []
    prose_removals = []
    for rm in removals:
        result = check_removal(rm, index)
        if result is None:
            prose_removals.append(rm)
        else:
            rm["verified"] = result["verified"]
            endpoint_removals.append((rm, result))

    rm_verified = sum(1 for _, r in endpoint_removals if r["verified"])
    if endpoint_removals:
        print(f"\nEndpoint removals — {len(endpoint_removals)}")
        for rm, result in endpoint_removals:
            mark = "[ok]  " if result["verified"] else "[FAIL]"
            print(f"  {mark} {rm.get('id', '?'):<7} {str(rm.get('method', '')).upper():<6} {rm.get('path', '')}")
            for note in result["notes"]:
                print(f"           - {note}")

    manual = [("schema_change", sc) for sc in schema_changes] + [("removal", rm) for rm in prose_removals]
    if manual:
        print(f"\nManual review — {len(manual)} entries not mechanically verifiable")
        for kind, entry in manual:
            tag = ""
            if kind == "schema_change" and entry.get("schema"):
                name = entry["schema"]
                tag = f" [schema {name} {'present' if schema_present(spec, name) else 'ABSENT'} in spec]"
            desc = entry.get("description") or entry.get("change") or ""
            print(f"  {entry.get('id', '?'):<7} {kind}{tag}")
            if desc:
                print(f"           {desc}")

    contract_path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n")
    print(
        f"\nSummary: endpoints {ep_verified}/{len(endpoints)} verified; "
        f"endpoint removals {rm_verified}/{len(endpoint_removals)} verified; "
        f"{len(manual)} entries need manual review."
    )
    print(f"Wrote {contract_path} with updated `verified` flags.")
    print("Assess every [FAIL] — significant gaps stop the slice; minor differences are fine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
