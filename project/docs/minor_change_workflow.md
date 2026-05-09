# Minor change workflow

Lightweight sequence for pattern-following changes that don't need a written plan. The coordinator runs a short Q&A round with the user, dispatches the code-writer, then the code-reviewer, and drives the fix loop.

For substantive changes that introduce new patterns, cross module boundaries, or involve design decisions worth capturing, use `major_change_workflow.md` instead.

## When to use this workflow

- The change is pattern-following — there is an existing precedent in the codebase, or it is a verbatim-style mirror of a sibling change.
- No new architectural decisions are required.
- Diff surface is narrow (rough guide: ≤ ~200 lines, ≤ ~5 files).
- The change can be executed without a written plan once the brief and clarifications are in hand.

If any of these is false, stop and use the major change workflow.

## Hard guardrails

- The `code-writer` and `code-reviewer` subagents are mandatory. The coordinator must not implement the change directly, and must not skip code review.
- The Q&A round is mandatory (see Step 2). Do not skip it because the brief looks clear — an agent forbidden from asking questions will invent answers instead.

## Step 0: Establish the slice subproject directory

Your working directory for this slice is:

```
{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/
```

The orchestrator (`/run-slice`) creates the slice directory and supplies `<SLICE_DIR>`; `brief.md` is already there. **Do not create, edit, or delete files at the slice root or in any sibling subproject folder** — those belong to the orchestrator and the other dev agents.

Document paths:

- Change brief: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/change_brief.md`
- Code review: `{{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}/code_review.md`

**Commit each document to the specs repo as soon as it's written** — don't wait until the end of the workflow. Multiple agents may work in the specs repo concurrently, so frequent small commits avoid conflicts and prevent work loss if a session crashes.

## Step 1: Read or write the change brief

If the user supplied a brief, read it. Otherwise, write a short change brief based on the user's request — typically a few sentences or a short bulleted list. Write the brief to the slice subproject directory.

## Step 2: Q&A round with the user (mandatory)

Before dispatching the code-writer, read the brief and the surrounding code to understand the change in context, then ask the user the questions you have.

**Discipline boundary.** Q&A resolves **scope, ambiguity, and missing context** — not design. Questions that are valid:

- "Does X apply to all entities of type Y, or only the ones that are Z?"
- "Should the new field show on the detail view as well as the list view, or only the list view?"
- "The sibling precedent uses pattern A; is that what you want here, or should this version differ?"

Questions that are **not** valid in this workflow:

- "How should I structure the service method?"
- "Should I introduce a new base class for this?"
- "Which pattern is better — A or B?"

If the conversation tips into design questions, the change does not belong in this workflow. Stop and escalate to the major change workflow.

Keep the round short. If the brief and the code are clear, the round may be a single question or a confirmation. Do not pad it.

Record the answers in a **Clarifications** section appended to the change brief, so the code-writer sees them as part of its single input document.

## Step 3: Dispatch the code-writer

```
Launch the code-writer agent. Pass the full path to the change brief (which
now includes the Clarifications section). Apply only the change described —
no adjacent refactors or "while I'm here" improvements.
```

If the agent does not complete the change in full:

- **Encourage progress.** Prompt it to complete the remaining work.
- **Perform a partial review.** Spot-check, run tests, feed conclusions back.
- **Request self-testing.** Ask the agent to test its own code before handing results back.

## Step 4: Verification checkpoint (after code-writer)

Verify:

- [ ] Lint/type/format/test all pass. Run: `{{ check_command }}`
- [ ] Review `git diff` for unexpected changes or scope bleed.
- [ ] Tests were added or updated for the changed behavior.

**Hard gate: tests must actually run.** If verification fails due to infrastructure issues, **do not proceed** to code review and **do not commit**.

**Fix trivial pre-existing issues inline.** If `{{ check_command }}` flags something unrelated to your slice and the fix is obvious and one-shot, fix it as part of your slice commit. Don't stop, don't file a card, don't ask. Anything bigger, leave it and escalate.

## Step 5: Dispatch the code-reviewer

```
Launch the code-reviewer agent. Pass the full path to the change brief
(in lieu of a plan) and instruct it to review the unstaged changes.
Delete any existing code_review.md first.
```

Read the review. Resolve ALL issues identified (BLOCKER, MAJOR, and MINOR). A GO decision means no BLOCKER or MAJOR issues, but MINOR issues must still be fixed. Dispatch the same code-reviewer to resolve them, providing clear context about which findings need resolution.

## Step 6: Verification checkpoint (after fixes)

Repeat Step 4. If any checks fail, return to Step 5.

## Step 7: Iterate if needed

- If you lack confidence in the end result, request a new code review from a fresh code-reviewer instance. Place subsequent reviews at `code_review_2.md`, `code_review_3.md`, etc.
- If not confident after 2 iterations on a minor change, the change was mis-classified — stop and escalate to the major change workflow (or to the user).

## Quality standards

The work is complete when:

- All requirements from the brief (including Clarifications) are implemented.
- Code review has been completed with decision GO or GO-WITH-CONDITIONS.
- ALL review issues are resolved.
- The subproject's verification command passes cleanly.
- No scope bleed — the diff matches the brief with no adjacent refactors.
