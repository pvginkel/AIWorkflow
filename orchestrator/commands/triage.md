# Triage

Turn a batch of findings into grounded, sliced implementation work. Argument: path to a findings document (e.g., `tmp/uat_testing.md`).

The findings document can be a UAT run, a list of bugs, a change-request dump, or any unstructured collection of issues. This skill converts it into fully documented implementation slices ready to run.

## What this skill does

You are the orchestrator. You do not write application code — you produce slice documentation that dev agents will execute.

## Procedure

### Phase 1: Collect and consolidate

**1a. Read the findings document** passed as the argument.

**1b. Read the issue tracker.** Fetch the outstanding items in your issue tracker's intake queue. These should be considered alongside the findings.

**1c. Write a consolidated test-results document** at `{{ specs_repo_path }}/test_results_YYYY-MM-DD.md`. Every item gets a numbered entry with:

- Clear description of the issue.
- Source (findings document reference, issue-tracker id, or both).

Group related items. For every item that isn't clear, add a **QUESTION** marker. Present the document to the user and iterate on questions until all items are understood.

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

- Infrastructure or tooling quality issues that bypass the dev-agent workflow → extract to a dedicated notes file.
- Already-fixed items → mark as resolved and remove.
- Discussion points without actionable work → flag for user.

**3b. Present the separation to the user** for confirmation before proceeding to slicing.

### Phase 4: Create slices

**4a. Design the slice grouping.** Group items into slices following these principles:

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
   - `acceptance_criteria.json` — structured criteria with IDs (BE-01, FE-01, PO-01, RE-01).
   - `api_contract.json` — endpoints and schema changes (or empty if no API changes).

2. **Second pass — UX designs (where needed).** For slices that need UX design, generate them using Codex after the overview and acceptance criteria exist. Write a prompt file and run:

   ```bash
   python3 {{ project_root }}/tools/ai_workflow/codex_exec.py --prompt-file <file> --response-file <file>
   ```

   The prompt must start with `$frontend-ux-designer` and follow the documented structure (what you're designing, what to read, current state, problems, what the design must cover, constraints, deliverable).

   **UX design is needed when:**
   - New screens or views
   - Novel interaction patterns
   - Complex state management or conditional UI
   - Multiple visual options that need a decision
   - Ambiguous or underspecified UI behavior

3. **Third pass — briefs.** Write per-subproject briefs that reference the acceptance criteria and (where applicable) the UX design. Delegate to subagents in parallel.

**Track progress:** Update `slice_backlog.json` status as each slice completes its documentation. Use `docs_complete` when all files are written.

### Phase 6: Update slice index and issue tracker

**6a. Update `{{ specs_repo_path }}/README.md`** — add all new slices to the **Pending** section.

**6b. Update the issue tracker.** For each tracker entry that was assigned to a slice:

- Add a slice label (e.g., "Slice 048") — create the label if it doesn't exist.
- Add type labels (Bug, Enhancement, Tech Debt) and area labels.
- Rewrite the entry description with structured markdown (summary, details, action, origin).
- Move the entry from the intake queue to "planned."

### Phase 7: Write summary and DAG

**7a. Create a summary document** at `{{ specs_repo_path }}/<triage_name>_summary.md` covering:

- What was done (item count, slice count).
- What the user needs to review (UX designs, technical designs).
- Slice overview table (number, title, areas, dependencies, items).
- Removed/deferred items.
- Files created/modified.

**7b. Create a run DAG** at `{{ specs_repo_path }}/<triage_name>_dag.md`. The user keeps this open in a notepad next to the execution run to pick the next slice to dispatch — optimise for clarity, copy-paste friendliness, and "can I glance at this and know what's runnable right now."

The DAG must show:

- **Every active slice** with a one- or two-line description. Each slice appears exactly once. Every active slice gets a `[ ]` checkbox prefix so the user can tick slices off as they dispatch and complete them. Deferred slices use `[-]` instead.
- **Soft ordering edges** between slices, annotated with the *reason* (e.g., "shares {{ subproject }}/src/hooks/use-foo.ts", "doc should reflect the new prompt framing"). Soft edges are ordering hints that minimize merge churn and rework — not hard gates.
- **Free roots** — slices with no predecessors, dispatchable any time — grouped separately from the ordered chain so the user can grab one at a glance.
- **An ASCII visual** of the DAG. Keep it monospace-clean, no heavy Unicode that renders badly in a plain notepad. Nodes appear once, each with a `[ ]` checkbox. Draw the arrows.
- **Deferred slices** in a separate section so they don't clutter the runnable set but are still visible. Use `[-]` prefix.
- **A cheat sheet** at the bottom: max parallel width, longest path, pure sinks, pure sources. This is what the user scans when deciding how many slices to dispatch at once.

**How to discover the edges:**

1. **File overlap.** For each pair of slices touching the same subproject, list the files each slice will write. Same file → soft edge. Adjacent files in the same area (same directory, same test file, same hook) → soft edge. Read the briefs you just wrote — the grounded file paths are the source of truth.
2. **Logical sequencing.** A slice that produces a fact another slice consumes (a new convention, a new doc, a new disablement) gets an edge. Example: a disablement slice should land before a documentation slice that describes "this is disabled."
3. **Contract changes.** A slice that changes a shared contract (API response shape, error taxonomy, event shape) should land before slices that consume the new contract.

Do NOT invent hard dependencies. Slices are intentionally independent where possible — edges are hints, not gates. If you can't find a good reason for an edge, don't draw one.

**Do NOT include execution waves.** The user's parallel capacity varies run-to-run. A DAG is more flexible than a wave plan — the user picks from free nodes based on current capacity.

**7c. Notify the user:**

```bash
python3 {{ notification_script }} --title "Triage complete" "N items triaged into M slices. Summary at {{ specs_repo_path }}/..._summary.md. Run DAG at {{ specs_repo_path }}/..._dag.md. UX designs ready for review."
```

## Key principles

- **Ground everything in code.** Don't propose solutions without reading the relevant source files. File paths and line numbers make briefs actionable.
- **UX design before briefs.** The frontend brief must reference the UX design, not the other way around. Write the overview first, then the UX design, then the brief.
- **Don't write application code.** Your output is documentation that dev agents execute. If the user asks for an ad hoc code change, push back and suggest creating a slice.
- **Iterate with the user.** Ambiguous items need clarification. Ask questions early — don't guess and create a slice based on assumptions.
- **Use subagents for parallel work.** Research, slice documentation creation, and UX design prompts can all be parallelized. Batch work to keep throughput high.
- **All information must have a home.** When triage is done, the user should be able to delete the test-results document and slice backlog — all information lives in the slice documentation and the summary.
