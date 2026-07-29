---
name: plan-slice
description: The refinement session — interactively bottom out a triaged slice with the operator, then launch the plugin's plan_loop.py to drive the plan-writer/plan-reviewer loop to a reviewed breakdown. The task runner executes the result.
argument-hint: <slice-number-or-path>
---

# Plan Slice

Break a slice into its executable task breakdown. **Required input: a slice folder** produced by
`/dev:triage` (`<spec-repo>/slices/backlog/NNN_slug/` with a `slice.md`). Argument: the slice
number or path. This is the interactive planning session — the operator is present; everything
downstream of you runs unattended, so what you freeze here is the only dispatch context the dev
agents get.

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line (a machine-checkable entry).
The workflow contract (folder layout, task rules, verdict schema) is
`${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md`; the plan loop's mechanics (phases, exits, the
review budget) are `${CLAUDE_PLUGIN_ROOT}/docs/plan-loop.md`; the project contract (what
`CLAUDE.md` and `.kubecoder/project.yaml` must provide) is
`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`.

**Preflight (step 0).** Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for plan` and relay
its message verbatim if it exits non-zero — it bails when the manifest or the `Spec repo:` entry is
missing (you cannot allocate a plan with nowhere to write it). A silent exit 0 means every gate
passed.

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in `slice.md` and the
artifacts you produce carry their RFC 2119 meaning.

## Your role

You are a **coordinator and the PO's advocate**, not the technical architect. This is the
**refinement session** — the dev team going through the idea with the PO. Triage recorded the ask
in the operator's words, asked only comprehension questions, and read no code; grounding each
requirement and working interactively toward the better solution happens **here**. The plan loop
(`${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py`) drives the plan-writer and plan-reviewer; you own
what is genuinely interactive: the design conversation, the operator's rulings, and the fidelity
check. The reading and writing around them is delegated — `slice-grounder` establishes facts,
`plan-briefer` frames a bail into a choice, `plan-scribe` records rulings. You hold decisions, not
documents. Your value:

1. **Faithful capture** — every explicit request in `slice.md` becomes an acceptance criterion and
   lands in exactly one task. No silent substitution, ever; infeasibility is discussed, not
   designed around.
2. **Completeness** — nothing falls between tasks; cross-project interfaces are pinned and every
   scope boundary the slice touches is ruled in or out on the record before the loop launches.
3. **Push-back** — feasibility concerns and pattern conflicts surface now, to the operator.

**Rulings live in files, not prompts.** The loop's agents read `slice.md`, `qa_log.md`, and
`grounding.md` from the slice folder; you never relay a ruling or a finding into a dispatch — log
it, commit, and let the loop point at it.

## Procedure

### 1. Absorb the slice

Read `slice.md` and every attachment in the slice folder. Its numbered requirements list is the
authoritative statement of intent, in the operator's own words — and deliberately thin. Treat
every claim or citation the slice carries as **unverified input**.

### 2. Ground and design with the operator

Bottom the ask out with the operator. Dispatch the `slice-grounder` sub-agent for the code facts
the requirements rest on; it fans out, writes `grounding.md`, and returns a receipt plus the
choices only the operator can settle (stay idle while it works — the mechanism notifies you; never
poll). Never pre-explore the code yourself before dispatching it — name the requirements and let
it fan out; ranges you read here ride your context for the rest of the slice (measured: an
orchestrator pre-read the exact ranges grounding.md then cited). Walk the requirements that leave
the *how* open, and bring its open choices, contradictions, and anything that changes the shape.
Don't relitigate settled input — a requirement that arrives pinned (a debugged root cause, an
operator-settled design) is absorbed as spec, not reopened.

- **A hedged answer is not a ruling**: an answer that selects no option, or rules conditionally
  ("if X, then fine"), stays open — verify the condition and re-surface it with the evidence before
  anything pins on it.
- Every ruling goes to the `plan-scribe` sub-agent, which records it to `qa_log.md` (and
  `slice.md`, `grounding.md`, the project's decision docs as the ruling reaches them) and commits.
  Hand it the operator's words verbatim; check its receipt quotes them back unchanged. **Never
  author these files yourself** — prose you draft stays in your context for the rest of the slice.
- Read `grounding.md` only when you need a specific fact. It exists so the loop's agents and you
  don't hold the evidence.

**Re-shaping.** Triage bundles on the asks as written — bundling mistakes are expected and yours
to fix: **split** a slice, **kick an item back** to the backlog as its own slice, or **pull in**
an obviously-adjacent backlog slice. Discuss the re-shape with the operator in-session; follow-up
folders come from the allocator (`/dev:triage`'s conventions). A breakdown that wants more than 10
tasks gets the same discussion.

- **Splitting out a child slice:** the parent's requirements are the child's requirements. Copy
  every constraint the parent imposes — including what the parent will produce onto or consume
  from the child, and where that data originates — into the child's `slice.md` as numbered
  requirements, not a dependency note; seed the child's `grounding.md` with the parent's relevant
  ledger entries. A split forced by a design reframe (the operator rejected a premise, not a size)
  gets a `/dev:arch-design` pass before planning unless the operator explicitly waives it. A child
  that exists to serve its parent is not planned to GO before the parent's requirements on it are
  grounded.
- **When a ruling invalidates a planned slice** (this one or a dependent — even one already GO'd
  and promoted): re-plan, don't patch. Rewrite `slice.md` so every settled ruling is a pinned
  requirement, delete `tasks/`, `acceptance_criteria.json`, the reviews, and `plan_state.json`,
  and run the loop fresh — clean artifacts review in one round; amended ones carry their history
  into every later read. Amendment in place is for changes local to one task. Only the session
  that owns a slice re-plans it; a promoted slice moves back to `slices/backlog/` (Kanban card
  back to To Do) first.

### 3. Run the plan loop

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py run <spec-repo>/slices/backlog/<SLICE_DIR>
```

Run it from the **target code repo** (the loop spawns its sessions in the repo it is launched
from), in the background (`run_in_background: true`). All loop and session output goes to
`<slice_dir>/plan_log.txt`; do **not** read or tail it — the background-task mechanism notifies
you when the loop exits, and the outcome lives in the exit code, `plan_state.json`, and
`plan_bailout.json`. Handle the exit:

On exit 3 or 4, dispatch the `plan-briefer` sub-agent with the exit; it reads the review, the plans
and the cited code, writes the brief to the slice folder, and returns one framed choice. Ask the
operator from that; the ruling goes to the `plan-scribe`, then rerun. Never read the review files
or answer a pending question from your own judgment.

- **Exit 4 — questions pending.** The reviewer classed these as the operator's.
- **Exit 3 — bailed.** `review_budget`: the briefer judges *converging* (needs turns — rerun with
  `--grant N` on the operator's say-so) or *contested* (a topic that survived two fix rounds is the
  operator's, however the reviewer classed it). `blocked` / `timeout` / `protocol_failure`:
  diagnose; fix only what is genuinely environmental, otherwise defer to the operator.
- **Exit 0 — the reviewer signed off.** The loop seeded `verification.json` from the criteria;
  append `source: qa_correction` entries for every planning answer that overrode a direction the
  breakdown was taking (the bar is direction change, not clarification). Continue below.

### 4. Verify fidelity yourself

The slice's numbered requirements are the **starting acceptance-criteria set, 1:1** — each becomes
a criterion carrying the requirement's wording, and a criterion may drop or re-word a requirement
**only on an explicit operator ruling logged in `qa_log.md`**. Walk the final artifacts
requirement by requirement: a matching, testable criterion in the operator's wording, and a task
that owns it. Operator-provided API/spec definitions survived at signature-level fidelity. This
check is yours — do not delegate it. A violation is not yours to fix: send it to the `plan-scribe`
with the requirement's verbatim text, then rerun the loop with `--reopen`.

### 5. Lodge decisions and commit

Decisions or conventions the slice establishes are project documentation: the `plan-scribe` writes
each into the owning `docs/` topic doc and the project's decision index, per the project's
documentation model.

### 6. Promote the slice out of the backlog

With fidelity verified, close out without waiting for an approval: move the slice from the backlog
into the active set so `/dev:run-slice` can pick it up:

- `git mv <spec-repo>/slices/backlog/NNN_slug <spec-repo>/slices/NNN_slug`. The loop
  writes `plan_state.json` and `plan_log.txt` into the folder but never commits them (they are
  loop-owned working state); they ride the move untracked. Commit them now with the rename — they
  are the plan's who-did-what record (every agent session id + transcript path) — staging by name;
  drop a stale `plan_bailout.json` if the loop finished at GO. The slice folder MUST be clean after.
- Move the slice's Kanban card from **To Do** to **Ready**.

### 7. Present the close-out

Report what is now Ready: the tasks (id, project, title, one line each), the acceptance criteria,
open questions, and any A/B decisions made with their grounds. A correction arrives on top of this
summary and is a ruling — send it to the `plan-scribe`, then rerun the loop with `--reopen`; one
that invalidates the breakdown follows §2's re-plan rule. Do **not** start `/dev:run-slice` —
running is a separate operator instruction.

## Quality checklist

- [ ] Every numbered requirement in `slice.md` → acceptance criterion (1:1, operator's wording) +
      owning task; any dropped or re-worded requirement has an operator ruling in `qa_log.md`.
- [ ] Tasks are project-local, ordered producers-first, 3–6 (max 10), each independently
      testable and PR-sized.
- [ ] Cross-project interfaces stated identically in both plans, at signature level.
- [ ] Plans carry verified `file:line` citations, no code, no prescribed symbol names.
- [ ] The plan loop exited 0 (latest `plan_review_r<N>.md` is GO).
- [ ] `verification.json` seeded with `qa_correction` entries appended; `qa_log.md` holds the
      planning Q&A; `grounding.md` holds the established facts.
- [ ] Decisions lodged in docs; everything committed to the spec repo — including the loop-owned
      `plan_state.json` and `plan_log.txt` (stale `plan_bailout.json` dropped); slice folder clean.
