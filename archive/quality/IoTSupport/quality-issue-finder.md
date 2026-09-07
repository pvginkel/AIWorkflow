# Quality Issue Finder

Scan this subproject for duplicated patterns and reinvented utilities. Produce a ranked JSON backlog and a human-readable markdown summary.

Invoked by `/quality-improver` in a dispatched sub-session. Runs inside one subproject with `cwd=<subproject>`. The specs repo path is supplied absolute by the dispatching prompt — relative paths resolve differently from the subproject CWD.

## Inputs

The dispatching prompt provides:

- **Scope**: `full` | `incremental since <git-ref>` | `incremental last <N>`.
- **JSON output path** (absolute).
- **Markdown output path** (absolute).

## Procedure

### Phase 1: Inventory existing utilities

Build a map of what's already shared in this subproject. For each utility, record `{ name, path, purpose }`. This is the reference set for Phase 2's "reinvented utility" detection.

Scope per subproject:

- **backend** (`cwd=backend`): scan the application package under `app/` — `app/utils/` (home of shared helpers such as `text_utils.py`, `url_utils.py`, `sse_utils.py`, `request_parsing.py`), shared service modules, mixins, and base classes across `app/services/`, plus the layered code in `app/api/`, `app/models/`, and `app/schemas/`. Do not inventory Alembic migrations under `alembic/`.
- **frontend** (`cwd=frontend`): scan `src/` — especially `src/lib/` (notably `src/lib/utils/` and `src/lib/ui/`) and `src/hooks/`, which hold the shared TypeScript/React utilities and hooks. Do not inventory the generated OpenAPI client under `src/lib/api/generated/` or the cached spec under `openapi-cache/`.

Load `.codehealthignore` from the repository root. Files listed there **are still valid inventory entries** — if a callsite duplicates a utility that lives in an ignored file, the fix is to use the utility (not to move the utility). What changes is Phase 2's handling of extraction candidates below.

### Phase 2: Scan for findings

**If scope is `full`:**

Walk source files in the subproject. Skip:

- tests and fixtures (`tests/`, `test/`, `__tests__/`, `*.test.*`, `*.spec.*`, `conftest.py`, `playwright/`)
- generated code and caches (`openapi-cache/`, `src/lib/api/generated/`, `alembic/versions/`, `migrations/`)
- build outputs and dependencies (`node_modules/`, `dist/`, `build/`, `.next/`, `coverage/`)

For each candidate code region, classify:

- **Category A — reinvented utility**: duplicates (in shape or purpose) a Phase-1 inventory entry. Record the callsite and name the existing utility.
- **Category B — extraction candidate**: a pattern that recurs in ≥2 files and is not in the inventory. Record all callsites.

**If scope is `incremental`:**

Identify changed hunks via `git log` and `git diff` over the range. For each new pattern introduced in the diff:

- Check against the inventory (Category A).
- `grep` the rest of the codebase for other occurrences (Category B). If the pattern now exists in ≥2 places counting the new one, it's a finding.

Incremental mode catches drift from recent work only — pre-existing duplication is invisible.

### Phase 3: Apply the template-ownership rule

IoTSupport does not consume a copier/cookiecutter template that duplicates scaffolding across sibling subprojects — `backend` and `frontend` do not share owned files. What this phase covers instead is **generated and scaffolding code**, which is generated or boilerplate by design and must never be reported as a quality issue:

- The generated OpenAPI client and types under `frontend/src/lib/api/generated/` (regenerated from `frontend/openapi-cache/openapi.json` by `pnpm generate:api`).
- Alembic migrations under `backend/alembic/`.
- Non-application orchestration code under `tools/` and `scripts/` (both at the monorepo root and within each subproject).

These paths are reflected in the repository `.codehealthignore` (`scripts/`, `docs/`, `tools/`, `backend/alembic/`); the generated client is a build output and is never hand-edited in place.

Apply to findings:

- **Category A findings are fine as-is.** Using an existing utility is always correct — even if that utility lives in scaffolding or generated code.
- **Category B findings whose callsites fall under any generated or scaffolding path above are invalid and must be dropped.** If any listed callsite is in a file matched by `.codehealthignore`, drop the finding.

`.codehealthignore` is authoritative.

### Phase 4: Rank, filter, cap

- Discard trivial findings: single-line repetitions, formatting, obvious idioms (`log = logging.getLogger(__name__)`, `const nav = useNavigate()`, etc.).
- Assign severity:
  - `high` — clear win, multiple callsites, small risk.
  - `medium` — worth doing, moderate scope or some risk.
  - `low` — nice to have.
- Sort by estimated impact (occurrences × size × severity weight).
- **Cap at 15 findings total.** If you have more candidates, keep the top 15.

### Phase 5: Write outputs

Create the `quality-audits/` directory in the specs repo if it doesn't exist.

Write JSON to the specified path:

```json
{
  "audit_date": "YYYY-MM-DD",
  "project": "<subproject>",
  "scope": {
    "mode": "full",
    "since": null,
    "last_n": null
  },
  "inventory_size": 42,
  "findings": [
    {
      "id": "Q-001",
      "category": "reinvented-utility",
      "severity": "high",
      "title": "Short descriptive title",
      "evidence": [
        { "file": "app/services/foo.py", "lines": "45-52", "snippet": "first ~80 chars of the block" }
      ],
      "existing_utility": "app/utils/text.py::slugify",
      "proposed_fix": "Replace the inline slug logic with `slugify(...)`.",
      "rationale": "Three call paths are computing slugs inline while `slugify` already exists."
    }
  ]
}
```

Field notes:

- `category` is `reinvented-utility` or `extraction-candidate`.
- `severity` is `high`, `medium`, or `low`.
- `existing_utility` is the target utility ref (e.g., `path::symbol`) for Category A findings; `null` for Category B.
- `proposed_fix` describes **what** to change, not **how**. Don't write code.
- `scope.mode` is `full` or `incremental`; `since` and `last_n` are populated only for `incremental`.

Write markdown to the specified path:

```markdown
# Quality audit — <subproject> — YYYY-MM-DD

Scope: <full / incremental since <ref> / incremental last <N>>
Inventory: <N> utilities indexed
Findings: <N>

## Q-001 — <title>    [<category> / <severity>]

- **Evidence**:
  - `path/to/file.ext:45-52`
  - `path/to/other.ext:120-127`
- **Existing utility**: `app/utils/foo.py::bar` *(Category A only)*
- **Proposed fix**: <what to change>
- **Rationale**: <why this is a real finding>

## Q-002 — ...
```

Keep markdown findings ordered the same way as JSON.

### Phase 6: Commit to the specs repo

```bash
cd /home/pvginkel/source/IoTSupportSpecs
mkdir -p quality-audits
git add quality-audits/<date>-<subproject>.json quality-audits/<date>-<subproject>.md
git commit -m "Quality audit: <subproject> <date>"
```

### Phase 7: Signal completion

Print as the **final line** of your response:

```
AUDIT_COMPLETE: N findings
```

where N is the finding count. The orchestrator parses this line — do not omit it, do not add anything after it.

## Key principles

- **Inventory first, scan second.** Every Category A finding must point at a real inventory entry. Every Category B finding must show ≥2 real callsites.
- **Respect generated and scaffolding ownership.** Generated code (the OpenAPI client under `frontend/src/lib/api/generated/`), Alembic migrations, and orchestration code under `tools/`/`scripts/` are not quality targets — they are generated or boilerplate by design. Category B findings that touch those callsites are dropped. `.codehealthignore` is the source of truth.
- **Ground everything.** Every finding carries `file:line` citations. No claims without evidence.
- **What, not how.** `proposed_fix` describes the change in prose — never code, never pseudocode, never a class/function name that doesn't already exist.
- **Cap at 15.** A tight, high-quality backlog is more useful than a flood of marginal items.
- **No cross-subproject moves.** Do not propose extracting anything to a shared package. That's a separate mode handled with explicit template awareness.
