# Triage

Turn a batch of findings into grounded, sliced implementation work. Argument: path to a findings document (e.g., `tmp/uat_testing.md`).

The findings document can be a UAT run, a list of bugs, a change-request dump, or any unstructured collection of issues. This skill converts it into fully documented implementation slices ready for `/run-slice`.

## What this skill does

You are the orchestrator. You do not write application code — you produce slice documentation that dev agents will execute.

## Procedure

### Phase 1: Collect and consolidate

**1a. Read the findings document** passed as the argument.

**1b. Read your issue tracker's intake queue.** Fetch outstanding items that should be considered alongside the findings.

**1c. Write a consolidated test-results document** at `{{ specs_repo_path }}/test_results_YYYY-MM-DD.md`. Every item gets a numbered entry with:

- Clear description of the issue.
- Source (findings document reference, issue tracker ID, or both).

Group related items. For every item that isn't clear, add a **QUESTION** marker. Present the document to the user and iterate on questions until all items are understood. This may take multiple rounds.

### Phase 2: Ground in code

**2a. Research every item.** For each item, find the relevant code. Use `Explore` subagents in parallel batches to investigate groups of related items. For each item, record:

- Exact file paths and line numbers.
- Current implementation state.
- Root cause (for bugs).
- Proposed solution with specific code-level changes.

**2b. Update the test-results document** with grounded analysis. Add file references, solution proposals, and follow-up questions where the code doesn't match the reported behavior.

**2c. Present follow-up questions to the user.** Some items will have ambiguities that only live debugging or user clarification can resolve. Iterate until resolved or explicitly deferred to slice implementation.

### Phase 3: Separate non-slice items

**3a. Identify items that don't belong in slices:**

- Infrastructure or tooling issues that bypass the dev-agent workflow.
- Already-fixed items → mark as resolved and remove.
- Discussion points without actionable work → flag for user.

**3b. Present the separation to the user** for confirmation before proceeding to slicing.

### Phase 4: Create slices

**4a. Design the slice grouping.** Follow these principles:

- Each slice should be independently runnable.
- Minimize dependencies between slices (a few are fine).
- Don't make slices too big — 3–6 items per slice is typical.
- Group by area (same screen, same backend service, same subsystem).
- Keep backend-only work separate from frontend-only work where it makes sense.

**4b. Write `{{ specs_repo_path }}/slice_backlog.json`** with the slice plan:

```json
{
  "created": "YYYY-MM-DD",
  "source": "path/to/findings",
  "slices": [
    {
      "id": "NNN",
      "name": "snake_case_name",
      "title": "Human readable title",
      "items": ["1a", "2b", "3c"],
      "areas": ["{{ subproject }}"],
      "ux_design": false,
      "dependencies": [],
      "status": "pending"
    }
  ]
}
```

**4c. Present the slice plan to the user** for review. Adjust groupings based on feedback.

**4d. Create slice directories** under `{{ specs_repo_path }}/slices/NNN_name/`. Continue the existing numbering sequence.

### Phase 5: Write slice documentation

For each slice, create the full documentation set. Work through slices in parallel batches using background agents.

**Authoring order matters:**

1. **First pass — overview, acceptance criteria, API contract.** These define what the slice does, what must be true when done, and what API changes are needed. Delegate to subagents in parallel. Each agent creates:
   - `overview.md` — requirements (R1, R2, …), background, dependencies, scope.
   - `acceptance_criteria.json` — structured criteria with IDs.
   - `api_contract.json` — endpoints and schema changes (or empty if no API changes).

2. **Second pass — UX designs (where needed).** For slices that need UX design, generate them using Codex after the overview and acceptance criteria exist:

   ```bash
   python3 {{ project_root }}/tools/ai_workflow/codex_exec.py --prompt-file <file> --response-file <file>
   ```

   The first line of the prompt must be `$frontend-ux-designer`. See `/write-slice` for when a UX design is needed.

3. **Third pass — briefs.** Write per-subproject briefs that reference the acceptance criteria and (where applicable) the UX design. Delegate to subagents in parallel.

**Track progress:** Update `slice_backlog.json` status as each slice completes its documentation. Use `docs_complete` when all files are written.

### Phase 6: Update slice index and issue tracker

**6a. Update `{{ specs_repo_path }}/README.md`** — add all new slices to the **Pending** section.

**6b. Update the issue tracker.** For each tracker entry that was assigned to a slice: add a slice label, add type/area labels, rewrite the description with structured markdown, move the item from the intake queue to "planned."

### Phase 7: Write summary

**7a. Create a summary document** at `{{ specs_repo_path }}/<triage_name>_summary.md` covering:

- What was done (item count, slice count).
- What the user needs to review (UX designs, technical designs).
- Slice overview table (number, title, areas, dependencies, items).
- Suggested execution order (waves of slices that can run in parallel).
- Removed/deferred items.
- Files created/modified.

**7b. Notify the user** that triage is complete:

```bash
python3 {{ notification_script }} --title "Triage complete" "N items triaged into M slices. Summary at {{ specs_repo_path }}/..._summary.md."
```

## Key principles

- **Ground everything in code.** Don't propose solutions without reading the relevant source files. File paths and line numbers make briefs actionable.
- **UX design before briefs.** The frontend brief must reference the UX design, not the other way around. Write the overview first, then the UX design, then the brief.
- **Don't write application code.** Your output is documentation that dev agents execute. If the user asks for an ad hoc code change, push back and suggest creating a slice.
- **Iterate with the user.** Ambiguous items need clarification. Ask questions early — don't guess and create a slice based on assumptions.
- **Use subagents for parallel work.** Research, slice documentation creation, and UX design prompts can all be parallelized. Batch work to keep throughput high.
- **All information must have a home.** When triage is done, the user should be able to delete the test-results document and slice backlog — all information lives in the slice documentation and the summary.
