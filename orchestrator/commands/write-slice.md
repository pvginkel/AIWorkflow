# Write Slice

Author an implementation slice. Argument: a short description of what the slice should deliver (e.g., "session lock rework using User FK").

## What you produce

A complete slice directory under `{{ specs_repo_path }}/slices/<NUMBER>_<snake_case_name>/` with the following layout:

```
<NUMBER>_<snake_case_name>/
  overview.md                 — what the slice delivers, why, dependencies
  acceptance_criteria.json    — testable conditions confirming the slice is done
  api_contract.json           — structured API specification
  grounding_check.md          — per-brief record of verified file:line citations
                                (always required when any brief is produced)
  ux_design.md                — designer-driven UX exploration (optional)
  <subproject>/brief.md       — scoped brief for that subproject's dev agent
  (one folder per subproject the slice actually touches)
```

Only create the subproject folder for surfaces the slice actually touches — a backend-only slice has only a `backend/` folder. Orchestrator-owned files (everything listed above the subproject folders) stay at the slice root; the `<subproject>/` subfolders are the dev agent's own working directory and hold both the brief and the dev-agent artifacts (plan, change brief, code reviews, etc.) produced during `/run-slice`.

`ux_design.md` is optional — see Step 8 for when to produce one.

Add the slice to the **Pending** section of `{{ specs_repo_path }}/README.md`.

## Procedure

### Step 1: Understand the request

Read the user's description. If it's vague, ask clarifying questions before proceeding. You need to understand:

- **What problem** is being solved or what capability is being added.
- **Which surfaces** are affected (backend, frontend, portal, or a combination).
- **What the user expects** to see when the slice is done.

**Capture every explicit request.** If the user says "I want X," X must become an acceptance criterion — not a suggestion, not a nice-to-have, not something softened into a different approach because it seems easier. If you think X is problematic or infeasible, say so and discuss it. Do not silently substitute a different approach.

**Push back when needed.** If the user's request has issues — conflicts with existing architecture, technically infeasible, would create problems downstream — raise it now. A conversation about feasibility is always better than silently delivering something different.

Check the issue log (Planned list) for cards related to this work — they may contain context, constraints, or prior decisions.

### Step 2: Research the codebase

Before writing anything, understand the current state:

- Read relevant conventions and architecture decisions.
- Read the code areas that will be affected (models, services, API endpoints, components).
- Check recent slices in the same area for patterns and context.
- Identify dependencies on other slices.

Do not write briefs based on assumptions about what the code looks like. Read it.

**Adjust research to fit the request.** A feature adding a new API endpoint needs you to understand models, services, and existing patterns. A mechanical change like "normalize every version pin" does not — it needs a clear rule and broad scope. Match the depth of your research to what the user actually asked for, and carry that through to the briefs: if the request is rule-based, the brief should state the rule and let the agent apply it, not enumerate every individual change (which agents misread as a closed set).

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
6. **Scope** — what surfaces are affected; explicitly note what's out of scope.

### Step 5: Write acceptance criteria

**This is the most important file in the slice.** The acceptance criteria are the contract between the user and the implementation. Everything else — briefs, API contracts, overviews — serves the criteria. If a requirement isn't in the acceptance criteria, it won't be verified, and if it's not verified, it may not be delivered.

Write `acceptance_criteria.json` with specific, testable conditions. Each criterion should be verifiable by a test, code review, or spec inspection.

```json
{
  "criteria": [
    {
      "id": "BE-01",
      "area": "{{ subproject }}",
      "description": "One specific, testable outcome"
    }
  ]
}
```

**ID prefixes:** use subproject-specific prefixes for clarity (e.g., `BE-` backend, `FE-` frontend, `PO-` portal, `RE-` regression).

`acceptance_criteria.json` carries the criteria definition only. Verdicts live in `verification.json` (created and maintained by `/run-slice`) — do not add a `status` field here.

**Good criteria:** "Customer create endpoint returns 201 with id, name, description fields"
**Bad criteria:** "Customer creation works correctly"

**The completeness rule:** Go back through the user's request, the issue-log cards, and the overview requirements. For every explicit ask, there must be a matching acceptance criterion. If the user said "send an event when bindings are complete," there must be a criterion that says exactly that — not a criterion about a polling endpoint that achieves something similar. If you can't write a criterion that matches the request, that's a signal to discuss feasibility, not to quietly substitute.

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

Write one brief per agent that will work on the slice, placed at `{{ specs_repo_path }}/slices/<SLICE_DIR>/<subproject>/brief.md` (e.g., `backend/brief.md`). Briefs are the most important part — they're what the dev agent reads to understand its task.

#### The cardinal rule: describe outcomes, not implementations

Briefs describe **what** needs to change and **why**. They do NOT prescribe **how**. The dev agent reads the code and writes the implementation; it knows the context the orchestrator doesn't. A prescriptive brief is the most expensive failure mode on record — the agent follows the brief down a wrong path even when a better one is obvious from the code, and the minor workflow has no plan-review safety net to catch it.

**Good:** "The undo endpoint must detect when an edit has already been undone and return 409."
**Bad:** "Add a query `select(ContentEdit).where(ContentEdit.original_edit_id == edit_id)` and if it returns a result, raise `InvalidOperationException`."

**Good:** "Editor users should see the lock screen when another user holds the session, just like portal users."
**Bad:** "Modify `verify_session_lock()` to remove the early return when `contact_id is None`."

#### Forbidden patterns

If a draft line matches any of these, rewrite it — don't soften, don't caveat.

1. **Code or pseudocode**, even one-liners or "shape" hints. No `select(...)`, no `if x: return 409`, no JSX fragments.

2. **Algorithm or step lists.** "First check Y, then do W" is procedure; describe the outcome and let the agent derive it. This includes task decompositions like "Task 1: add field. Task 2: backfill. Task 3: update endpoint" — that's an algorithm wearing a task list. A task is a unit of outcome, not an implementation step.

3. **Named symbols to create.** Don't name methods, classes, helpers, hooks, or files the agent should produce.
   - **Bad:** "Add a method `_check_lock_owner` and a helper class `LockGuard`."
   - **Good:** "The system must determine whether the requesting user owns the lock and reject the action otherwise."

4. **Target-state `file:line` citations.** Citations describe what the code is today, never what it should become. "Today, X happens in `file:142`" is fine; "Modify `file:142` to do Z" or "Add a function near `file:142`" is not — the agent picks the location.
   - **Bad:** "Modify `app/services/lock.py:142` by hoisting the owner check."
   - **Good:** "The lock owner check today lives in `app/services/lock.py:142`. It must be reachable from both the portal and the editor session paths."

5. **Exact CSS / Tailwind / class strings.** Visual prescription is still prescription. Describe the layout intent in prose and say "match the styling of the surrounding detail view."

6. **Forbiddances without a stated requirement.** If you have to forbid a path, you've imagined the implementation. State the positive requirement instead.
   - **Bad:** "Do not place the `key` prop on the wrapper element."
   - **Good:** "List items must remount when their underlying entity id changes." (The agent figures out where the key goes.)

Precedent references are the one allowed form of pointing at code: "follow the pattern in `<file>`" — no line numbers, no symbol names.

#### Final pass: classify every line

Before freezing, re-read the brief. Every non-trivial line is one of:

- **(a)** Fact about current state with a `file:line` citation — keep.
- **(b)** Outcome, requirement, constraint, or behavioral rule about target behavior — keep.
- **(c)** Prescription about how to get from (a) to (b) — move it: into `acceptance_criteria.json` if it's a requirement in disguise, into the overview's Constraints section if the user explicitly demanded the implementation choice, otherwise delete it.

If you find yourself defending a (c) line ("but the agent needs to know this"), you don't trust the agent — and the data says you should.

#### Length ceilings

Past the ceiling, the brief is doing a plan's job and the work belongs in the major workflow:

- **Routine maintenance** (rule-based, dep bumps, sweeps): ≤ 400 words.
- **Pattern-following / bug fix with reproduction**: ≤ 600 words.
- **Any minor brief**: ≤ 1,000 words hard ceiling.
- **Major-workflow briefs**: no ceiling — they go through plan-writer + plan-reviewer.

Outcome-focused minor briefs cluster at 300–500 words; plan-shaped minor briefs run 1,000–2,000 and produce the most expensive minor sessions on record.

#### Rule-based briefs (routine maintenance)

When the user's request is a rule applied broadly (dependency updates, bulk renames, config normalization, lint sweeps, dead-code removal, doc fixes), the brief should describe the **rule** and its scope, not enumerate every individual change. Include:

1. The rule (e.g., "normalize every version pin to `^N` based on the latest available version").
2. How to determine inputs (e.g., "run `poetry show --latest` to find the latest version").
3. A few illustrative examples.
4. Explicit scope — "every dependency in the file" vs. "only these specific packages."

Exhaustive tables get misread as a closed set.

**Routine briefs go to the minor workflow regardless of file count.** Each touch is mechanical and the dev coordinator does not need a written plan. Note this in the overview's Scope section ("Routine maintenance — minor workflow expected") so `/run-slice`'s brief-shape check exempts it from the plan-shaped-brief warning. Major-workflow plans on routine slices burn ~5M tokens of plan-writer + plan-reviewer overhead the agent did not need.

If a routine brief grows past 400 words, the work is probably no longer routine — design decisions are hidden inside the rule. Surface them to the user before freezing.

#### Brief structure

Each brief should include:

1. **Context** — 1–2 sentences on what the agent is building (point to the overview for background).
2. **Tasks** — numbered, scoped units of work. Each task describes:
   - What needs to change (a new endpoint, a schema modification, a UI screen).
   - Why it needs to change (the problem or requirement it addresses).
   - Constraints and edge cases (validation rules, error conditions, behavioral rules).
   - Which acceptance criteria it covers (reference the IDs).
3. **Testing requirements** — what must be tested.
4. **Code quality** — pointer to the subproject's `CLAUDE.md` for how to verify lint/type/format compliance.

#### Allowed content

The forbidden patterns say what to leave out. Positively, briefs carry:

- **Schema details** — field names, types, constraints (required/optional, nullable, enums, length limits). Facts about the contract, not implementation.
- **Behavioral rules** — "if X, the system must Y." Business logic as requirements.
- **Error conditions** — what can go wrong, status codes, user-facing messages.
- **Constraints** — "must work for both portal and editor users," "must handle concurrent access," "events must use explicit targets."
- **Precedent references** — "follow the pattern in the customers list." Point at the file; no line numbers, no symbol names.
- **Acceptance criterion IDs** — every task references the criteria it satisfies.

#### Doc-first slices — require a checkpoint between Task 1 and Task 2

When a slice is structured as "Task 1: write a contract/architecture document; Task 2: implement the fix whose direction depends on Task 1's contract" (e.g. an architecture doc that determines which subproject owns a follow-up fix), the brief must explicitly require the agent to stop after Task 1, commit the doc, and wait for user review before starting Task 2.

**Why:** The doc itself is the architectural decision the user wants to vet before code lands. If Task 2 starts immediately based on the agent's reading of the doc it just wrote, the user loses the chance to challenge the contract before implementation.

**How to apply:**
- In the brief's Task 1, include a terminal instruction: *"After committing Task 1, stop and wait for the orchestrator to resume you. Do not start Task 2."*
- In Task 2, note that the task is gated on user review of Task 1.
- Flag the checkpoint in the overview so `/run-slice` knows to pause and hand off to the user between tasks.

This applies to any slice where a planning artifact drives a downstream implementation choice — not just architecture docs (API contracts, schema docs, state-machine specs).

### Step 7b: Grounding pass

**Mandatory — do not skip, do not soften to "consider".** Before any brief in this slice is considered frozen, you must re-ground every codebase claim it contains against the current code. Briefs written from your short-term mental model rather than from a fresh read of the files are the leading cause of Round 1 Q&A corrections. This step exists to catch those misses before the brief is handed to a dev agent.

For every brief produced in this slice, you must:

- **(a) Open every `file:line` citation** in the brief and confirm the cited code matches the claim the brief is making about it. A stale line number, a renamed symbol, a moved block — any mismatch gets corrected in the brief before the brief is frozen.
- **(b) Re-grep or re-read the code behind every "the system does X today" / "the current behavior is Y" / "there is no Z today" assertion.** Do not assert current behavior from memory. If the claim is "feature F does not exist yet," grep for it; if it is "endpoint E returns 201 on success today," open the handler.
- **(c) Check every "add Y" / "introduce Y" / "create Y" task against the current codebase** to confirm Y is not already present. Partial implementations count — if a half-built version of Y exists, record what is present so the brief directs the agent to complete rather than duplicate.

You must write a sibling grounding self-check artifact at `{{ specs_repo_path }}/slices/<SLICE_DIR>/grounding_check.md`. This file is a dedicated artifact, not inlined into each brief. Its minimum contents:

- One section per brief (`## <subproject>/brief.md` for each subproject the slice touches).
- Under each section, a bulleted list of every claim you checked, each with a `file_path:line_number` citation where relevant and a verdict of **confirmed**, **corrected** (with a short note on what was changed in the brief), or **not applicable** (with a reason).
- A final "Summary" bullet per section stating "all file:line citations verified" — or, if any corrections were applied, listing them.

The artifact lets the orchestrator and reviewers see the grounding pass actually happened. A brief without a matching `grounding_check.md` section is not frozen.

### Step 8: Consider UX design

If the slice involves new screens, novel interactions, complex state management, or ambiguous UI behavior, note in the overview that a UX design is needed. The user can generate one via the `/ux-design` skill before the frontend/portal briefs are written. The briefs then reference the UX design.

### Step 8b: Consider architecture design

Most slices follow an existing pattern and do not need a separate `/arch-design` run. The dev agent's own planning phase during `/run-slice` surfaces the same implementation subtleties (timing, callback threading, field population, dispatch wiring) that an upfront arch-design would — running both is redundant and the arch-design output tends to re-discover what the dev agent would find anyway.

**Reserve `/arch-design` for slices where:**
- The decision spans multiple agents and affects how they coordinate.
- The decision changes the slice structure (splitting into sub-slices, introducing blocking dependencies).
- There are genuinely competing approaches and the user needs to choose before implementation starts.
- A new cross-cutting pattern is being introduced that future slices will follow.

For "follow the existing pattern" slices, the brief plus the dev agent's own planning is sufficient. Do not default to running arch-design as a safety net.

### Step 9: Present to user

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

You are NOT responsible for designing the implementation. The dev agents read the code, write plans, and make technical decisions. When you spend attention on implementation details, you take it away from coordination and validation — which is where requirements get dropped.

## Quality checklist

Before presenting the slice to the user, verify:

- [ ] Overview explains *what* and *why*, not *how*.
- [ ] **Every explicit user request** has a matching acceptance criterion.
- [ ] **Every issue-log card** scoped into this slice has matching acceptance criteria.
- [ ] No user request was silently substituted with a different approach.
- [ ] Every acceptance criterion is specific and testable.
- [ ] Briefs contain zero code snippets or pseudocode.
- [ ] Briefs describe outcomes and constraints, not implementation steps.
- [ ] API contract lists all new/changed/removed endpoints and fields.
- [ ] Error conditions and edge cases are documented as requirements.
- [ ] Dependencies on other slices are listed.
- [ ] Scope is clear — "out of scope" is stated where relevant.
- [ ] Each brief references which acceptance criteria IDs it covers.
- [ ] Briefs live under `<SLICE_DIR>/<subproject>/brief.md`, not at the slice root.
- [ ] Grounding pass has been run and `grounding_check.md` exists in the slice directory with every `file:line` citation verified and zero unchecked claims.
- [ ] Slice is added to the **Pending** section of `{{ specs_repo_path }}/README.md`.
