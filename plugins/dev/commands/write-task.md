---
description: Author one task folder in an in-flight slice from a findings or missing-task write-up, so the task runner can execute it on resume. Usually run in a sub-agent from /run-slice.
---

# Write Task

Author **one task folder** in an in-flight slice, from a write-up — a `test_findings.md`, a
writer's `missing-task` report, or an operator instruction. Arguments: the slice folder and the
source write-up. Used by `/run-slice` (usually in a sub-agent) to feed work back into the task
runner; the contract is [`docs/conventions/task-workflow.md`](../../docs/conventions/task-workflow.md).

## Procedure

1. **Read the write-up and the slice.** The findings/report say *what is wrong or missing*; the
   slice's `slice.md`, `acceptance_criteria.json`, and merged work (git log) say what the world
   looks like now. Ground every claim you carry over — read the code the write-up points at.
2. **Scope one task per project.** Group findings by owning project; one new task folder per
   project that has work. A task must be executable in isolation against the current merged state.
3. **Create `tasks/NN_slug/`** — next free number, or a letter suffix when the task must run at a
   specific insertion point (`04a_slug` runs between `04` and `05`; the runner picks it up on
   resume). Never renumber an existing folder.
4. **Write `task.json` and `plan.md`** exactly as the plan-writer would (see its agent definition
   for the shape): outcome-focused requirements quoting the findings' evidence, current state with
   verified citations, what must be tested, a minimal reading list. Findings are requirements —
   "the reported symptom no longer occurs" style — not fix prescriptions.
5. **Commit** the task folder to the specs repo, staged by name, and report the created task
   id(s) back.

Do not modify merged tasks, `state.json` (runner-owned), or application code.
