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
  non-phase sections use `##`; the driver ignores those entirely.
- **Ids are free-form labels; document order is authoritative.** `P3a` inserted between `P3`
  and `P4` runs between them because of *where it sits*, not its name. Ids must be unique.
- **`## Task shape` is the plan-writer's declaration** — `pre-settled`, `localized`, or
  `cross-cutting`, one line of justification anchored in slice.md facts. It binds the writer's
  investigation and the plan review checks it (semantics: [plan-loop.md](plan-loop.md)); the
  run loop's parser ignores it like every other `##` section.
- **`Target:` is the first line of every phase body** — a `kc project list` component name or
  a sibling repo path (`../SiblingRepo`). It roots the executor's cwd, the driver's git
  operations, and the gate. Markdown decoration is tolerated (`**Target:**` with a backticked
  value), but the
  line carries nothing else. A phase without a resolvable Target is a structure error.
- **`✅ DONE <date>` on the heading is the driver's stamp.** Only the driver writes it, after
  review passes and the merge lands. No agent ever stamps, and a done phase is skipped on every
  re-parse.
- **Done-records go under the phase's own heading** — appended below the phase text as plain
  paragraphs or lists, **never a new `###`**. Content: what landed, what settled beyond the
  plan's text, what changes for later phases — hard cap ~25 lines, settlements not narration.
  A find that affects a later phase is edited *into that phase*, where its reader will trip
  over it, not left in the done-record.
- **Phases are roughly PR-sized and independently reviewable** — one branch, one gate run, one
  reviewable diff. A phase outgrowing that splits; a phase *section* outgrowing ~a page
  overflows into `attachments/` (referenced, never inlined). No testing or doc phases — the
  loop owns those; a phase's own tests ride the phase.
- **The plan carries no doc-phase content.** The doc phase writes docs from the shipped diff
  and the requirements/rulings — the rulings, in the operator's words, are the only doc
  steering there is. A doc-deliverable section, drafted prose, or a doc-content attachment is
  a defect the plan review flags. (Exception: a slice whose task *is* doc changes — then the
  doc work is the phases.)
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
- `verdict`/`rationale`/`evidence` stay empty at planning time — the run loop's test phase
  checks items off (`pass`/`fail` with rationale and evidence).
