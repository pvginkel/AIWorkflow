# Major change workflow

Sequence for substantive changes — anything that introduces new patterns, crosses module boundaries, or involves design decisions worth capturing in a written plan.

For small, pattern-following changes, use `minor_change_workflow.md` instead.

The coordinator reading this document is the subproject's main Claude session. The coordinator dispatches the four dev agents (`plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`) in order and drives the verification and iteration loop.

## Step 0: Establish the slice subproject directory

Before invoking any subagents, confirm the slice subproject directory path:

```
{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/
```

This is the dev-agent working directory for the {{ subproject }} part of the slice. The orchestrator (`/run-slice`) creates the slice directory and supplies `<SLICE_DIR>`; your job is to add the artifacts below alongside the `brief.md` already in place.

**Do not create, edit, or delete files at the slice root** (`{{ specs_repo_path }}/slices/<SLICE_DIR>/*.md`, `*.json`) **or in any sibling subproject folder.** Those belong to the orchestrator and the other dev agents.

Document paths (pass these to every agent invocation):

- Change brief: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/change_brief.md`
- Plan: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/plan.md`
- Plan review: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/plan_review.md`
- Code review: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/code_review.md`

**Commit each document to the specs repo as soon as it's written** — don't wait until the end of the workflow. Multiple agents may work in the specs repo concurrently, so frequent small commits avoid conflicts and prevent work loss if a session crashes.

## Step 1: Write the change brief

Describe the work at a functional level based on the user's input. A brief can be a single sentence or several paragraphs if the change needs a reproduction or domain context.

Write the change brief to the slice subproject directory.

If confidence is low that the change brief describes the change clearly, respond back to the user and abort the session.

## Step 2: Dispatch the plan-writer

```
Launch the plan-writer agent. Pass the full path to the change brief and the
target plan location. Resolve all questions autonomously.
```

The plan-writer will produce `plan.md` plus the companion JSON files (`requirements.json`, `file_map.json`, `test_plan.json`). Its internal structure, sections, and method are documented in the plan-writer agent definition — do not restate them here.

## Step 3: Dispatch the plan-reviewer

```
Launch the plan-reviewer agent. Pass the full path to the plan.
```

The plan-reviewer will produce `plan_review.md` with a JSON decision block and prose findings. Read the review.

**Apply review feedback.** If the review has **Blocker** or **Major** findings, dispatch the plan-writer again with the review as input and ask it to update the plan. Then re-run the plan-reviewer. Repeat until the review comes back with no **Blocker** or **Major** findings.

If the review reports any open questions that only the user can answer, ask the user before proceeding.

## Step 4: Dispatch the code-writer

```
Launch the code-writer agent. Pass the full path to the plan.
```

The code-writer reads the plan and companion JSONs, implements the change, and runs the subproject's verification commands before reporting back.

If the agent does not complete the plan in full, provide assistance:

- **Encourage progress.** Prompt the agent to proceed to the next chunk.
- **Perform a partial review.** Spot-check direction, run tests, feed conclusions back, request continuation.
- **Request self-testing.** Ask the agent to test its own code before handing results back.

## Step 5: Verification checkpoint (after code-writer)

Before proceeding to code review, verify:

- [ ] Lint/type/format/test all pass. Run: `{{ check_command }}`
- [ ] Review `git diff` for unexpected changes.
- [ ] New test files were created as required by the plan.
- [ ] Any schema migrations and test-data updates were made.
- [ ] `requirements.json` (if present): spot-check that key requirements appear implemented.
- [ ] `test_plan.json` (if present): spot-check that planned test scenarios have corresponding test functions.

**Hard gate: tests must actually run.** If verification fails due to infrastructure issues (unreachable services, missing env vars, broken fixtures), **do not proceed** to code review and **do not commit** work. Report the infrastructure issue and stop.

**Fix trivial pre-existing issues inline.** If `{{ check_command }}` flags something unrelated to your slice and the fix is obvious and one-shot, fix it as part of your slice commit. Don't stop, don't file a card, don't ask. Anything bigger, leave it and escalate.

## Step 6: Dispatch the code-reviewer

```
Launch the code-reviewer agent. Pass the full path to the plan and instruct
it to review the unstaged changes. Delete any existing code_review.md first
so the review is independent.
```

The code-reviewer produces `code_review.md` with a JSON decision block and prose findings. Read the review.

**Apply review feedback.** Even on a GO decision, resolve ALL issues (BLOCKER, MAJOR, and MINOR). A GO decision means no BLOCKER or MAJOR issues, but MINOR issues should still be fixed. Dispatch the same code-reviewer agent to resolve the issues, providing clear context about which findings need resolution.

## Step 7: Verification checkpoint (after fixes)

Repeat Step 5 after resolving review findings. All checks must pass. If any fail, return to Step 6.

## Step 8: Iterate if needed

- If you lack confidence in the end result, request a new code review from a fresh code-reviewer instance. Place subsequent reviews at `code_review_2.md`, `code_review_3.md`, etc.
- Repeat the review-and-resolution cycle until quality standards are met.
- If not confident after 3 iterations, escalate to the user.

## Hard guardrails

- Use only the dev agents: `plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`. Do not implement the change yourself — the workflow exists to avoid that.
- Minor localized corrections by the coordinator are acceptable if you're confident. Everything substantive goes through the agents.

## Quality standards

The work is complete when:

- All plan requirements are implemented.
- Code review has been completed with decision GO or GO-WITH-CONDITIONS.
- ALL issues identified in code review are resolved.
- The subproject's verification command passes cleanly (see `CLAUDE.md`).
- Tests that fail as a side effect of the work are fixed.
- No outstanding questions remain (or are deferred to the user with clear context).
