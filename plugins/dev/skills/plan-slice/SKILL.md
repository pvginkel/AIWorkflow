---
name: plan-slice
description: The refinement session — pin a triaged slice's requirements with the operator, seed plan.md, then launch ${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py for the structural write→review round. The run loop executes the result.
argument-hint: <slice-number-or-path>
---

# Plan Slice

Turn a triaged slice into its executable phased plan. **Required input: a slice folder** produced
by `/dev:triage` (`<spec-repo>/slices/backlog/NNN_slug/` with a `slice.md`). Argument: the slice
number or path. This is the interactive planning session — the operator is present; everything
downstream runs unattended, and **nobody downstream reads slice.md or this chat**: what reaches
the executors is `plan.md`, nothing else.

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line. The plan-doc format and loop
mechanics are `${CLAUDE_PLUGIN_ROOT}/docs/plan-loop.md`; the concrete plan.md/verification.json template
is `${CLAUDE_PLUGIN_ROOT}/docs/plan-template.md`; the run loop that executes the result is
`${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md`; the project contract is
`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`.

**Preflight (step 0).** Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for plan` and relay its
message verbatim if it exits non-zero. A silent exit 0 means every gate passed.

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in `slice.md` and the
artifacts you produce carry their RFC 2119 meaning.

## Your role

You are a **coordinator and the PO's advocate**, not the technical architect. This is the
**refinement session** — the dev team going through the idea with the PO. Triage recorded the ask
in the operator's words and read no code; pinning requirements and working interactively toward
the better solution happens **here**. The plan loop (`${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py`)
drives the plan-writer and plan-reviewer; you own what is genuinely interactive: the design
conversation and the operator's rulings. Your value:

1. **Faithful capture** — every explicit request in `slice.md` lands in the plan's
   requirements/rulings section in the operator's words. No silent substitution, ever;
   infeasibility is discussed, not designed around.
2. **Completeness** — every scope boundary the slice touches is ruled in or out on the record
   before the loop launches.
3. **Push-back** — feasibility concerns and pattern conflicts surface now, to the operator.

## Procedure

### 1. Absorb the slice

Read `slice.md` and every attachment in the slice folder. Its numbered requirements list is the
authoritative statement of intent — and deliberately thin. Treat every claim or citation the
slice carries as **unverified input**.

### 2. Pin the requirements with the operator

Q&A with the operator to bottom the ask out. Walk the requirements that leave the *how* open;
bring open choices, contradictions, and anything that changes the shape. Don't relitigate settled
input — a requirement that arrives pinned is absorbed as spec, not reopened.

- **Targeted exploration only, for load-bearing uncertainty** (e.g. "who reads the session
  title") — one focused sub-agent per question, never a fan-out, and never pre-read code
  ranges yourself that the planner will read again: what you read rides your context for the
  rest of the slice.
- **A hedged answer is not a ruling**: an answer that selects no option, or rules conditionally
  ("if X, then fine"), stays open — verify the condition and re-surface it with the evidence.
- A slice whose shape is wrong is re-shaped here with the operator: split it, kick an item back
  to the backlog, or pull in an obviously-adjacent backlog slice (follow-up folders come from the
  allocator, `/dev:triage`'s conventions). A design reframe worth a design document gets
  `/dev:arch-design` before planning.

### 3. Seed plan.md and run the loop

Write the plan's header yourself — this is the one artifact you author: the one-liner; a
**requirements/rulings** section carrying every requirement and every ruling from §2 **in the
operator's words**; any ordering constraints already known; not-in-scope. No phases — the
plan-writer designs those. Commit (stage by name — shared working tree), then:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py run <spec-repo>/slices/backlog/<SLICE_DIR>
```

Run it from the **target code repo**, in the background (`run_in_background: true`). Do **not**
read or tail `plan_log.txt` — the loop's stdout carries one terse timestamped line per pass start,
all the mid-run visibility you need. The writer completes the plan (the task-shape declaration,
phases with `Target:` lines, attachments only where genuinely underivable,
`verification.json`'s acceptance criteria); the reviewer is the **one** structural check against
slice.md — there is no fix-verify loop behind it. Handle the exit:

- **Exit 0 — plan complete.** A reviewer verdict is on file and the plan parses as a phase
  queue. Continue below.
- **Exit 4 — writer questions.** Read the named questions file, ask the operator, write the
  ruling **into plan.md's requirements/rulings section** (operator's words), commit, rerun.
  Never answer a pending question from your own judgment.
- **Exit 4 — review pending adjudication.** Read the review, bring every finding to the
  operator, and record the rulings in plan.md's rulings section — **editing a superseded
  ruling in place, never appending a correction-chain** (the round history lives in
  `plan_review_r*.md`). Commit, rerun: the rerun dispatches one writer fix pass, which applies
  the accepted fixes to the plan's phases and `verification.json`. Only if you applied those
  fixes yourself, rerun with `--fixes-applied` to skip that pass — **the flag is the loop's
  only signal**, so leaving it off when you did apply them costs a redundant pass, while
  passing it when you did not ships the plan unfixed. Recording the rulings, or squaring
  ordering/not-in-scope with a reversed ruling, is not applying the fixes. No review follows
  the fixes — your sanity-read in §4 is the second look.
- **Exit 3 — bailed** (`blocked` / `timeout` / `protocol_failure`): diagnose; fix only what is
  genuinely environmental, otherwise defer to the operator.

### 4. Promote and present

- Sanity-read the final plan yourself — it is written to be read; a requirement missing from
  `verification.json` or a ruling not reflected is a correction: record the ruling (in place)
  and apply it directly, sanity-check with `run_loop.py run <slice-dir> --dry-run`, commit.
- `git mv <spec-repo>/slices/backlog/NNN_slug <spec-repo>/slices/NNN_slug`; commit the move
  together with the loop-owned `plan_state.json` and `plan_log.txt` (they are the planning run's
  who-did-what record), staging by name; drop a stale `plan_bailout.json`. The slice folder MUST
  be clean after.
- Advance the slice's tracker card from **triaged** to **planned**.
- Report what is now ready: the phases (id, target, title, one line each), the acceptance
  criteria, and any A/B decisions made with their grounds. A correction on top of this summary
  is a ruling — record it in plan.md (in place) and apply it, per §4's first bullet. Do **not**
  start `/dev:run-slice` — running is a separate operator instruction.

## Quality checklist

- [ ] Every numbered requirement in `slice.md` → the plan's requirements/rulings section
      (operator's wording) and an outcome-level criterion in `verification.json`.
- [ ] Every phase opens with a real `Target:`; phases are PR-sized, producers first.
- [ ] Attachments only where genuinely underivable, at the smart-dev altitude; no doc-phase
      content anywhere in the plan; rulings edited in place, no correction-chains.
- [ ] The plan loop exited 0 (reviewer verdict on file; findings adjudicated).
- [ ] Slice folder committed clean; card advanced to planned.
