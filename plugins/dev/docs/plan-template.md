# The plan template — plan.md and verification.json, mechanically

The concrete shape of a slice's `plan.md` and `verification.json`, settled so every author —
the interactive `/dev:plan-slice` session seeding the header, the plan-writer completing it, agents
appending phases mid-run, the operator editing at will — produces a doc `run_loop.py`'s parser
drives without nudges. Semantics (who writes which section, review charter, loop mechanics) are
[plan-loop.md](plan-loop.md) and [run-loop.md](run-loop.md); this doc is the shape. Sanity-check
a plan with `run_loop.py run <slice-dir> --dry-run` — it parses, resolves every `Target:`, and
prints the gates without touching anything.

## plan.md

```markdown
# Slice NNN — <one-liner: what ships when this slice is done>

## Requirements / rulings

<!-- Seeded by /dev:plan-slice, in the operator's words; authoritative on intent.
     /dev:run-slice appends mid-run operator answers here. A ruling that corrects
     an earlier one REPLACES it in place — no correction-chains; the round
     history lives in plan_review_r*.md. -->

- R1. …
- Ruling (YYYY-MM-DD): …

## Task shape

<!-- Declared by the plan-writer BEFORE it investigates; checked by the plan
     review against slice.md. One of pre-settled | localized | cross-cutting,
     justified in one line from slice.md facts. -->

pre-settled — slice.md's design section fixes the mechanism; planning is transcription.

## Ordering constraints

<!-- Only what is genuinely ordered beyond "producers before consumers". Often empty. -->

## Push holds

<!-- Optional; almost always absent — omit the heading unless a ruling holds a push. One
     bullet per held repo, `- ../SiblingRepo — <why this run must not push it>`, target
     written as a phase writes its `Target:`. The driver leaves it out of the push check
     and reports it held instead. -->

### P1 — <title>

Target: <component>

<The phase: outcome, the few constraints the executor cannot figure out from the repo,
pointers into attachments/. Self-sufficient by reference — no inlined designs.>

### P2 — <title>

Target: ../<SiblingRepo>

<…>

## Not in scope

- …
```

The mechanical rules the parser holds every author to:

- **Every `###` heading is a phase heading** — `### P<id> — <title>` (em dash), id
  `[A-Za-z0-9]+`. Any other `###` line is a structure error the driver nudges back. All
  non-phase sections use `##`, and the driver reads exactly one of them — `## Push holds`;
  the rest it ignores.
- **Ids are free-form labels; document order is authoritative.** `P3a` inserted between `P3`
  and `P4` runs between them because of *where it sits*, not its name. Ids must be unique.
- **`## Task shape` is the plan-writer's declaration** — `pre-settled`, `localized`, or
  `cross-cutting`, one line of justification anchored in slice.md facts. It binds the writer's
  investigation and the plan review checks it (semantics: [plan-loop.md](plan-loop.md)); the
  run loop's parser ignores it, as it does every `##` section but the next one.
- **`## Push holds` names the repos this run must not push** — one `- <target> — <why>`
  bullet each (em dash), target in the same vocabulary as `Target:`. The driver skips them in
  its push check, names them in the test phase's dispatch, and writes one Outstanding-actions
  entry per held repo; the doc landing merges locally and does not push a held primary repo. A
  bullet in that section the parser cannot read is a structure error, not a skip — a hold
  missed silently is a repo the driver pushes. The section is absent from almost every plan.
- **`Target:` is the first line of every phase body** — a `kc project list` component name or
  a sibling repo path (`../SiblingRepo`). It roots the executor's cwd, the driver's git
  operations, and the gate. Markdown decoration is tolerated (`**Target:**` with a backticked
  value), but the
  line carries nothing else. A phase without a resolvable Target is a structure error.
- **`Creates: <component>` declares that a phase registers a new component** — an optional
  line under `Target:` for a phase that adds a `kc project list` entry to the manifest. The
  driver re-reads the component set at every plan parse, so the component is a valid `Target:`
  from the moment the creating phase merges; the declaration is what lets a *later* phase — or
  the creating phase itself — target the name before that: validation and `--dry-run` accept it
  on the declaration's word instead of failing against a manifest that does not hold it yet. A
  declarer stamped done whose component never appeared in the manifest is a structure error.
- **`✅ DONE <date>` on the heading is the driver's stamp.** Only the driver writes it, after
  review passes and the merge lands. No agent ever stamps, and a done phase is skipped on every
  re-parse.
- **Done-records go under the phase's own heading** — appended below the phase text as plain
  paragraphs or lists, **never a new `###`** — in two parts, the summary first:
  1. a bold `**Done (P<id>).**` paragraph — what landed (the files and names that now exist)
     and the gate's result — then a `Later phases:` line and **one contiguous list** of what a
     later phase must know: what is settled beyond the plan's text, the seams and harness it can
     use, what is owed or unexercised. About ten lines together.
  2. the record — the narrative, the witnessed reds, the fix rounds, the gate lines — hard cap
     ~25 lines, settlements not narration.
  The run loop's phase digest hands later phases part 1 only; the doc phase's digest and the
  reviewer read the whole record. A record without the `Later phases:` list rides in later
  dispatches whole (the driver's log names it), and a phase without the opener hands over its
  whole section.
  A find that affects a later phase is edited *into that phase*, where its reader will trip
  over it, not left in the done-record.
- **Phases are roughly PR-sized and independently reviewable** — one branch, one gate run, one
  reviewable diff. A phase outgrowing that splits; a phase *section* outgrowing ~a page
  overflows into `attachments/` (referenced, never inlined). No end-to-end testing phase and
  no auto-doc phase — the loop owns those; a phase's own tests ride the phase.
- **A doc task is a phase.** The loop's doc phase is auto docs only — the doc surfaces that
  already describe the changed behavior, brought up to date from the shipped diff — and it
  carries no slice task. So a requirement that *is* a doc change — a decision to close, a
  design fact to record, a page to correct — is a phase like any other work, with its own
  `Target:` (the spec repo resolves as a sibling, `../<SpecRepo>`), reviewed and merged by the
  loop. A plan that hands such work to the doc phase is a defect the plan review flags.
- **The plan carries no auto-doc content.** The doc phase writes from the shipped diff and the
  requirements/rulings — the rulings, in the operator's words, are the only steering it gets.
  A doc-deliverable section, drafted prose, or a doc-content attachment for it is a defect the
  plan review flags.
- **Rulings are living text.** A ruling that corrects an earlier one replaces it in place —
  never a correction appended after superseded wording. The same no-tombstone rule the code
  follows; git and `plan_review_r*.md` hold the history.

## verification.json

```json
{
  "items": [
    {
      "id": "V01",
      "area": "<subsystem or requirement cluster>",
      "description": "<outcome-level criterion, in the operator's wording>",
      "verdict": null,
      "rationale": "",
      "evidence": []
    }
  ]
}
```

- **Outcome-level, complete against slice.md's numbered requirements 1:1**, in the operator's
  wording. Add criteria freely; never drop or re-word a requirement without a ruling recorded
  in plan.md's rulings section.
- **`file:line` evidence citations** where a criterion rests on a code fact the author verified
  this pass — the surviving anti-hallucination discipline.
- **Coverage-preservation criteria are allowed** ("no coverage is lost; every deleted test has
  a named successor" — phrased as an outcome, never an inventory of paths). **Doc-truth
  universals are banned** (a criterion asserting prose claims hold everywhere).
- **Every criterion is earned by the plan's phases.** One whose work no phase delivers — a doc
  change assigned to the loop's doc phase, which carries no slice task — is a planning defect
  the plan review flags, not a verdict the test phase can write.
- `verdict`/`rationale`/`evidence` stay empty at planning time — the run loop's test phase
  checks items off (`pass`/`fail` with rationale and evidence).
