# The plan loop — one structural write→review round

`${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py` is `/dev:plan-slice`'s mechanical half. The interactive
session pins requirements with the operator and seeds `plan.md`'s header; the loop then runs a
fresh **plan-writer** pass to complete the plan and **one** fresh **plan-reviewer** pass to
judge it. The review is structural, not optional: **exit 0 is refused without a reviewer
verdict on file**, and it is the only place anything checks the plan against `slice.md` —
nobody downstream reads slice.md again. Session mechanics and models are
[agent-dispatch.md](agent-dispatch.md); the loop that executes the result is
[run-loop.md](run-loop.md).

**There is no review loop.** A `go` verdict completes the plan. Anything else — blocking
findings or questions — pauses with the review on file: the interactive session adjudicates
the findings with the operator and records the rulings in plan.md's rulings section, **edited
in place** (a ruling that corrects an earlier one replaces it; the round history lives in
`plan_review_r*.md`). The rerun then dispatches one writer fix pass that reads the review plus
the rulings — **unless the session applied the accepted fixes itself and says so with
`--fixes-applied`**. That declaration is the only thing that suppresses the pass: the loop
reads nothing off the plan to guess it. It cannot — recording the rulings is required either
way, and a reversed ruling routinely falsifies an ordering or not-in-scope bullet, so plan
maintenance and applied fixes look identical in the file. The default is therefore the pass:
a forgotten flag costs a no-op writer round, never a plan that ships unfixed. Nobody
re-reviews the result — the operator's read is the second look, and it is the cheapest review
pass there is. Post-GO corrections are the same move without the loop: edit the plan in place,
sanity-check with `run_loop.py run <slice-dir> --dry-run`.

Exits: **0** plan complete (a reviewer verdict is on file and the plan parses as a phase
queue) · **4** operator input needed (writer questions, or a review pending adjudication;
handle it, rerun — the loop resumes where it paused) · **3** bailed (`plan_bailout.json`:
`blocked`, `timeout`, `protocol_failure`).

Every pass is a fresh context reading its inputs from the slice folder; rulings reach agents
through plan.md only — dispatch prompts carry pointers, never relayed content. Agents must leave
the slice folder committed (stage by name — the spec repo is a shared working tree); the loop
nudges once, then bails. Round counts persist in `plan_state.json`; a plan that already parses
with phases (a reset re-plan) enters at review.

The loop is the first thing to run on a slice, so it creates the slice's **close-out report**
(`close-out.md`, from the plugin's template) and commits it before its first dispatch, and every
dispatch names the report and `close_out.py`, the only way to write to it; what the planning
agents write there is [close-out.md](close-out.md)'s.

## The plan doc

`plan.md` is **the one plan** — read by every executor, and by the operator (legibility is a
design goal; the operator's read is the cheapest review pass there is). The concrete skeleton —
heading levels, the `Target:` line, done-record shape, the `verification.json` schema — is
[plan-template.md](plan-template.md); its shape:

- **Header** (seeded by the interactive session): the one-liner; **requirements/rulings** — every
  requirement and operator ruling, in the operator's words; this section is authoritative on
  intent, is preserved verbatim by the writer, and is where `/dev:run-slice` records mid-run
  operator answers.
- **Task shape** — declared by the plan-writer *before* it investigates, checked by the review:
  `pre-settled` / `localized` / `cross-cutting`, with a one-line justification anchored in
  slice.md facts. The declaration binds the writer's investigation budget — its register
  carries the binding (`pre-settled` forbids research sub-agents and repo sweeps; research runs
  only against a named open question).
- **Ordering constraints** and **not-in-scope**.
- **Phases** — `### P<id> — <title>` sections (format details: [run-loop.md](run-loop.md)), each
  opening with its `Target:` line, **self-sufficient by reference**: outcome, the few constraints
  the executor can't figure out, pointers to attachments. Roughly PR-sized and independently
  reviewable; a phase outgrowing that splits, a section outgrowing ~a page overflows into an
  attachment. No testing or doc phases — the loop owns those — and **no doc-phase content
  anywhere in the plan**: the doc phase derives docs from the shipped diff and the
  requirements/rulings; the rulings are the only doc steering there is (exception: a slice
  whose task is doc changes).
- **Done-records** are appended under each phase's own heading (never a new `###`): what landed,
  what settled beyond the plan's text, what changes for later phases — hard cap ~25 lines,
  settlements not narration. Finds that affect later phases are edited into those phases, where
  their reader will trip over them.

**`attachments/`** — designs only where the executor genuinely cannot derive them, written at the
altitude a smart dev would want handed to them: a functional description of success, never class
names, pseudo-code, or a specced implementation. Read on demand, never inlined.

**`verification.json`** — outcome-level acceptance criteria, complete against slice.md's numbered
requirements 1:1 in the operator's wording, with `file:line` evidence citations where a criterion
rests on a code fact. Coverage-preservation criteria allowed; doc-truth universals banned.
Checked off in the run loop's test phase.

## The reviewer's charter

ACs outcome-level and complete against slice.md; the task shape declared and justified from
slice.md facts that hold; detailed designs correct (load-bearing citations
verified against the code); every phase's `Target:` present and real; phases independently
reviewable and roughly PR-sized; attachments at the altitude above; no doc-phase content (an
altitude finding — flagged, never fact-checked claim by claim); no correction-chained rulings;
nothing load-bearing silently uncertain. Findings describe problems, never corrections. One
round, ever — the findings go to the operator. Verdicts: `go` / `issues` / `questions`.
