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

`<spec-repo>` is the path in your `.aiworkflowrc`'s `spec_repo`. The plan-doc format and loop
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

Bottom the ask out with the operator — through a document and a conversation, never a dialog:
you MUST NOT use the AskUserQuestion tool, here or anywhere in this skill. The two forms, the
material, and the doc's shape are `${CLAUDE_PLUGIN_ROOT}/docs/refinement.md`. Walk the
requirements that leave the *how* open; bring open choices, contradictions, and anything that
changes the shape. Don't relitigate settled input — a requirement that arrives pinned is
absorbed as spec, not reopened.

1. **Ground, then collect.** For each decision: the premises it rests on, verified —
   **targeted exploration only, for load-bearing uncertainty** (e.g. "who reads the session
   title"), one focused sub-agent per question, never a fan-out, and never pre-read code ranges
   yourself that the planner will read again: what you read rides your context for the rest of
   the slice — then your recommendation and its trade-off, the alternatives you consider live,
   and the impact if you are wrong. What only the operator knows is an open fact. The size in
   phases goes in the material too.
2. **Dispatch `dev:refinement-writer`** with the material and end the turn — its receipt is the
   walkthrough; post it as it came back. The doc is `refinement.md` in the slice folder.
3. **Take the rulings.** The operator comments in the file or in chat. A single decent choice
   with impact is put to them in chat as agree-or-comment; a reframe or "walk me through this"
   is answered in prose, and the decision is not re-posed until they have said what they think.
   **A hedged answer is not a ruling**: an answer that rules conditionally ("if X, then fine")
   stays open — verify the condition and re-surface it with the evidence.
4. A slice whose shape is wrong is re-shaped here with the operator: split it, kick an item back
   to the backlog, or pull in an obviously-adjacent backlog slice (follow-up folders come from the
   allocator, `/dev:triage`'s conventions). A design reframe worth a design document gets
   `/dev:arch-design` before planning.

### 3. Seed plan.md and run the loop

Write the plan's header yourself — this is the one artifact you author: the one-liner; a
**requirements/rulings** section carrying every requirement and every ruling from §2 **in the
operator's words**; any ordering constraints already known; not-in-scope. A ruling that forbids
pushing a repo also gets its machine-readable half — a `## Push holds` bullet, shaped as the
plan template above says; prose alone is invisible to the driver, which then nudges the test
agent for that push and bails. No phases — the plan-writer designs those, and **`###` is theirs
alone**: sub-structure inside your sections is `####`, because every `###` the parser sees is a
phase heading and a stray one is a structure error. Commit it with `refinement.md` (stage by
name — shared working tree), then:

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
- **Exit 4 — writer questions.** The named questions file is second-round material: re-ground
  it (where the plan now stands, what the writer settled, what each question decides), dispatch
  `dev:refinement-writer` to append the decisions to `refinement.md`, post its receipt, take
  the rulings, and write each **into plan.md's requirements/rulings section** (operator's
  words), commit, rerun. Never answer a pending question from your own judgment.
- **Exit 4 — review pending adjudication.** Read the review and bring every blocking finding
  to the operator in one agree-or-comment message — each with its default disposition and what
  it changes in the plan; a premise the review overturned is stated first — and record the
  rulings in plan.md's rulings section — **editing a superseded ruling in place, never
  appending a correction-chain** (the round history lives in `plan_review_r*.md`). Commit,
  rerun: the rerun dispatches one writer fix pass, which applies
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
- [ ] `refinement.md` written by the refinement-writer, no dialog posed; every ruling it drew
      is in plan.md, in the operator's words.
- [ ] Every phase opens with a real `Target:`; phases are PR-sized, producers first.
- [ ] Attachments only where genuinely underivable, at the smart-dev altitude; no auto-doc
      content anywhere in the plan (a doc task is a phase); rulings edited in place, no
      correction-chains.
- [ ] The plan loop exited 0 (reviewer verdict on file; findings adjudicated).
- [ ] Slice folder committed clean; card advanced to planned.
