# Write Slice

Author an implementation slice. Argument: a short description of what the slice should deliver (e.g., "session lock rework using User FK").

## What you produce

A complete slice directory under `{{ specs_repo_path }}/slices/<NUMBER>_<snake_case_name>/` containing:

- `overview.md` — what the slice delivers, why, and dependencies
- `<subproject>_brief.md` — per-subproject briefs for each area that has work
- `api_contract.json` — structured API specification (if there are API changes)
- `acceptance_criteria.json` — testable conditions confirming the slice is done
- `ux_design.md` (optional) — UX guidance for slices with non-trivial UI work

Also add the slice to the **Pending** section of `{{ specs_repo_path }}/README.md`.

## Procedure

### Step 1: Understand the request

Read the user's description. If it's vague, ask clarifying questions before proceeding. You need to understand:
- **What problem** is being solved or what capability is being added.
- **Which subprojects** are affected.
- **What the user expects** to see when the slice is done.

**Capture every explicit request.** If the user says "I want X," X must become an acceptance criterion — not a suggestion, not a nice-to-have, not something that gets softened into a different approach because it seems easier. If you think X is problematic or infeasible, say so and discuss it. Do not silently substitute a different approach in the brief.

**Push back when needed.** If the user's request has issues — conflicts with existing architecture, is technically infeasible, would create problems downstream — raise it now. A conversation about feasibility is always better than silently delivering something different.

### Step 2: Research the codebase

Before writing anything, understand the current state:
- Read relevant conventions and architecture decisions.
- Read the code areas that will be affected (models, services, endpoints, components).
- Check recent slices in the same area for patterns and context.
- Identify dependencies on other slices.

Do not write briefs based on assumptions about what the code looks like. Read it.

**Adjust research depth to match the request.** A feature adding a new API endpoint needs you to understand models, services, and existing patterns. A mechanical change like "normalize every version pin" does not — it needs a clear rule and broad scope. Match the depth of your research to what the user asked for, and carry it through to the briefs: if the request is rule-based, the brief should state the rule and let the agent apply it, not enumerate every individual change (which agents misread as a closed set).

### Step 3: Assign a slice number

Check `{{ specs_repo_path }}/README.md` for the next available number. Use a letter suffix (e.g., `087b`) if this is follow-up work to an existing slice.

### Step 4: Write the overview

The overview is for the orchestrator and reviewers. It explains **what** and **why** — not implementation details.

Structure:
1. **What this slice delivers** — 1–3 sentences describing the outcome.
2. **Why** — the problem being solved or capability being added.
3. **Requirements** — numbered list of concrete requirements (R1, R2, ...).
4. **Current state** — what exists today (if relevant).
5. **Dependencies** — which prior slices must be complete.
6. **Scope** — what subprojects are affected; explicitly note what's out of scope.

### Step 5: Write acceptance criteria

**This is the most important file in the slice.** The acceptance criteria are the contract between the user and the implementation. Everything else — briefs, API contracts, overviews — serves the criteria. If a requirement isn't in the acceptance criteria, it won't be verified, and if it's not verified, it may not be delivered.

Write `acceptance_criteria.json` with specific, testable conditions. Each criterion should be verifiable by a test, code review, or spec inspection.

```json
{
  "criteria": [
    {
      "id": "BE-01",
      "area": "{{ subproject }}",
      "description": "One specific, testable outcome",
      "status": "pending"
    }
  ]
}
```

**ID prefixes:** use subproject-specific prefixes for clarity (e.g., `BE-` backend, `FE-` frontend, `PO-` portal, `RE-` regression).

**Good criteria:** "Customer create endpoint returns 201 with id, name, description fields"
**Bad criteria:** "Customer creation works correctly"

**The completeness rule:** Go back through the user's request and the overview requirements. For every explicit ask, there must be a matching acceptance criterion. If the user said "send an event when bindings are complete," there must be a criterion that says exactly that — not a criterion about a polling endpoint that achieves something similar. If you can't write a criterion that matches the request, that's a signal to discuss feasibility with the user, not to quietly substitute.

### Step 6: Write the API contract

Write `api_contract.json` for any API changes. For non-API slices, use:

```json
{
  "changes": [],
  "notes": "No API changes. <context>."
}
```

For slices with API changes:

```json
{
  "endpoints": [
    {
      "id": "EP-01",
      "method": "POST",
      "path": "/api/resource",
      "description": "What this endpoint does",
      "status_codes": [201, 422],
      "key_request_fields": ["name", "description"],
      "key_response_fields": ["id", "name", "created_at"],
      "verified": null
    }
  ],
  "schema_changes": [],
  "removals": []
}
```

### Step 7: Write the briefs

Write one brief per subproject that will work on the slice. Briefs are the most important part — they're what the dev agent reads to understand its task.

#### The cardinal rule: describe outcomes, not implementations

Briefs describe **what** needs to change and **why**. They do NOT prescribe **how** to implement it. No code snippets, no pseudocode, no "use this pattern" or "create a class named X."

**Why:** The dev agent reads the codebase, writes a plan, and designs the implementation. It knows the code better than the orchestrator. Prescribing implementation constrains the agent to a potentially wrong solution.

**Good:** "The undo endpoint must detect when an edit has already been undone and return 409."
**Bad:** "Add a query `select(ContentEdit).where(ContentEdit.original_edit_id == edit_id)` and if it returns a result, raise `InvalidOperationException`."

**Good:** "Editor users should see the lock screen when another user holds the session, just like portal users."
**Bad:** "Modify `verify_session_lock()` to remove the early return when `contact_id is None` and instead fall through to the comparison."

#### Rule-based briefs

When the user's request is a rule applied broadly (dependency updates, bulk renames, config normalization), the brief should describe the **rule** and its scope, not enumerate every individual change. Include:

1. The rule (e.g., "normalize every version pin to `^N` based on the latest available version").
2. How to determine inputs (e.g., "run `poetry show --latest` to find the latest version").
3. A few illustrative examples.
4. Explicit scope — "every dependency in the file" vs. "only these specific packages."

Exhaustive tables of every item and its target value get misread as a closed set — agents only touch listed items and skip the rest.

#### Brief structure

Each brief should include:

1. **Context** — 1–2 sentences on what the agent is building (pointer to the overview for full background).
2. **Tasks** — numbered, scoped units of work. Each task describes:
   - What needs to change (a new endpoint, a schema modification, a UI screen).
   - Why it needs to change (the problem or requirement it addresses).
   - Constraints and edge cases (validation rules, error conditions, behavioral rules).
   - Which acceptance criteria it covers (reference the IDs).
3. **Testing requirements** — what must be tested.
4. **Code quality** — how to verify lint/type/format compliance (use the subproject's `CLAUDE.md` conventions).

#### What to include in briefs

- **Schema details** — field names, types, constraints (required/optional, nullable, enums, length limits). These are facts about the contract, not implementation.
- **Behavioral rules** — "if X happens, the system must Y." Business logic as requirements.
- **Error conditions** — what can go wrong and what the user should see.
- **Constraints** — "must work for both editor and portal users," "must handle concurrent access," etc.
- **References** — point to conventions or existing patterns. Say "follow the existing pattern in the customers list" rather than pasting the pattern.

#### What NOT to include in briefs

- **Code** — no snippets, no pseudocode, no implementation details.
- **Class/function names** — let the agent follow project conventions.
- **Algorithm steps** — describe the outcome, not the procedure.
- **Internal architecture** — the agent reads the code.
- **Defensive caveats** — if you find yourself writing "be careful to..." or "make sure you don't...", you're prescribing implementation. State the requirement instead.

### Step 8: Consider UX design

Assess whether the slice needs a dedicated UX design. A UX design is needed for:

- New screens or views.
- Novel interaction patterns not covered by existing archetypes.
- Complex state management (multi-step flows, real-time updates, conditional visibility).
- Customer-facing UI with non-trivial interaction.
- Ambiguous or underspecified UI behavior.

A UX design is **not** needed for:

- Backend-only slices.
- Simple CRUD additions following existing patterns.
- Adding columns, fields, or badges to existing screens.
- Pure bugfix or refactoring slices.

If needed, note it in the overview. The UX design is generated by `/run-slice` (via Codex) after the overview and acceptance criteria are in place, but before the frontend/portal agent work. The briefs then reference the UX design.

### Step 9: Present to the user

Show the user a summary of what you've written:

- Which agents will run.
- Key requirements and acceptance criteria.
- Any design decisions or trade-offs you made.
- Questions or ambiguities that need resolution.

Wait for the user to review and approve before considering the slice complete.

## Your role

You are a **work coordinator and validator**, not a technical architect. Your value is in:

1. **Faithfully capturing requirements** — every user request becomes a tracked criterion.
2. **Ensuring completeness** — nothing falls through the cracks between overview, criteria, and briefs.
3. **Pushing back** — raising feasibility concerns before work starts, not silently substituting.
4. **Validating delivery** — verifying at the end that what was asked for is what was built.

You are NOT responsible for designing the implementation. The dev agents read the code, write plans, and make technical decisions. When you spend your attention on implementation details, you take it away from coordination and validation — which is where requirements get dropped.

## Quality checklist

Before presenting the slice to the user, verify:

- [ ] Overview explains *what* and *why*, not *how*.
- [ ] **Every explicit user request** has a matching acceptance criterion.
- [ ] No user request was silently substituted with a different approach.
- [ ] Every acceptance criterion is specific and testable (not "works correctly").
- [ ] Briefs contain zero code snippets or pseudocode.
- [ ] Briefs describe outcomes and constraints, not implementation steps.
- [ ] API contract lists all new/changed/removed endpoints and fields.
- [ ] Error conditions and edge cases are documented as requirements.
- [ ] Dependencies on other slices are listed.
- [ ] Scope is clear — "out of scope" is stated where relevant.
- [ ] Each brief references which acceptance criteria IDs it covers.
- [ ] Slice is added to the **Pending** section of `{{ specs_repo_path }}/README.md`.
