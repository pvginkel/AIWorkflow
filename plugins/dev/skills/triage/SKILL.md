---
name: triage
description: Sort a batch of findings, bugs, or requests into slice folders that record the operator's requirements verbatim (slice.md under slices/backlog/NNN_slug/) — the required input to /plan-slice. Does not ground, design, or plan slices.
argument-hint: "[findings-document]"
---

# Triage

Sort a batch of findings, requests, and issue-tracker items into **slice folders** — recorded
change requests under `<spec-repo>/slices/backlog/NNN_slug/`, the input to `/plan-slice`
(which refines and plans them and promotes them up into `slices/`). Argument (optional): path to a findings document (e.g., `tmp/uat_testing.md`).

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line. **Preflight (step 0):** run
`python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage` and relay its message verbatim on a
non-zero exit — it bails when the `Spec repo:` entry is missing (there is nowhere to write a slice).
The issue-tracker and notification wiring this skill references generically (boards, lists, the
project's owner tag, how to notify) is defined by your host convention (`~/.claude/CLAUDE.md`).

The input can be a UAT run, a list of bugs, a change-request dump, chat discussion, or any
unstructured collection of issues. Triage understands it, groups it by subject, and writes one
slice per group. **Triage does not plan slices** — the task breakdown is `/plan-slice`'s job, in a
separate, deliberate act. Triage is the **first line**: it makes sure each ask is understood *as
written*, records it in the operator's words, and routes it. `/plan-slice` is the second line —
the refinement session that grounds the ask in code and bottoms it out with the operator.

## Triage is mandatory — and it stops at the slice request

- **Every change goes through triage first.** This is a hard rule. The slice folder's `slice.md`
  is the required input to `/plan-slice`; there is no planning without one.
- **Triage does not start `/plan-slice` itself.** When the slices are written, stop. The operator
  picks a slice up later — usually in a fresh session — and runs `/plan-slice` then. Do not assume
  the operator will action every slice immediately.
- **The one exception is operator-initiated — never your own judgement.** Only when the **operator
  explicitly asks** you to carry straight on into `/plan-slice` in the same session may you do so,
  and only if you also agree the request is a single isolated, genuinely minimal change (a clear bug
  fix, a cosmetic fix, an impactful-but-honestly-straightforward change). You never decide this on
  your own: absent an explicit operator request, you stop at the slice, full stop. If the operator
  asks but you judge the change is not minimal, say so. Even when you do proceed, `slice.md` is
  still produced, the full planning process still applies, and you **never** do this from a
  sub-agent.

## Hard rules

- **Never open application code.** Not even a quick grep, not via a sub-agent. Triage's sources
  are the cards, the documents they cite, and the chat — never the repo. If an item can't be
  understood without reading code, it's a planning question, not a triage question.
- **Requirements are recorded in the operator's words.** Quote, don't restate: a paraphrase can
  invert an ask (slice 087 turned "put an empty line above the shortcuts line" into an acceptance
  criterion asserting the opposite); a quote cannot.
- **Every input becomes a numbered requirement** — the planner's starting acceptance criteria,
  1:1. Nothing gets lost, bundled away, or summarized out of existence.
- **Claims stay claims.** A card's diagnosis, cause, or line reference is carried attributed and
  unverified — never endorsed, never checked against the code.
- **Nothing is "operator-approved" without an explicit answer.** Silence on a default you proposed
  is not approval; don't record assumptions — leave the open point to the planner.
- **No design — and a feasibility verdict *is* design.** No fixes, no task shapes, no acceptance
  criteria, no test enumerations, no "settled / do not re-open". A design doc that arrives as
  input is attached and pointed at, not validated.

## What this skill does

You are the orchestrator. You do not write application code, and you do not design the
implementation — you produce work packages that the planner (and, downstream, the dev agents)
execute.

## Procedure

### Phase 1: Collect and consolidate

**1a. Gather every input.** Read the findings document if one was passed. Pull in the relevant
chat discussion. Fetch the outstanding cards carrying **this project's owner tag** in the Triage
board's **Inbox** list — the project's intake queue. Leave cards tagged for other projects alone,
and treat untagged cards as not-yet-claimed; if asked to consider a card without the project's tag,
say so rather than adopting it. All three are inputs and are considered together.

**1b. Write a transient triage working document** at `<spec-repo>/handovers/triage_YYYY-MM-DD.md`
(transient docs live in `handovers/`, never at the specs root). Give every item a numbered entry
with:

- The ask, in the operator's words (quote it — the phrasing carries the requirement).
- Its source (findings-document reference, issue-tracker id, or both).

This document is scratch — it exists to drive the clarification loop and is **deleted at the end
of triage** (Phase 7), once all information has been absorbed into the slices.

**1c. The comprehension interview.** For every item that is vague or incomplete *as a request*,
add a **QUESTION** marker; present the document to the operator and iterate until every item is
understood. The scope is "do I understand what you wrote?" — the test for a triage question is
that **the operator can answer it from memory**. "You want a Cancel button — on which screen?"
qualifies. Anything that would require someone to open a file — where the screen lives, whether it
exists yet, whether a reported cause is right — is the planner's question, not yours. Do not
guess, and do not research your way past an ambiguity the operator can resolve in a sentence.

When an item hands you an **API or interface definition** — tool signatures, endpoint shapes, a
schema, a wire contract, anything with named operations, parameters, and return shapes — **ask
whether it is a rough sketch for inspiration or a considered surface.** The two look alike on the
page but demand opposite treatment: a sketch you may reshape freely; a considered surface you carry
through as a spec (Phase 5). Don't assume — ask.

**Do not group items into slices yet.** Phase 1 is about understanding individual items, not
deciding how they cluster.

### Phase 2: Understand the ask — never the code

There is no grounding phase. Understanding the *ask* is a conversation with the operator
(Phase 1c); understanding the *code* is the planner's refinement session. Do not read application
code, do not dispatch sub-agents into the repo, and do not verify that the things an item names
exist — a screen the operator mentions may be unbuilt in another pending slice, and "add a Cancel
button to screen X", noted down, is a complete triage result.

What you do read: the sources the items cite — cards, findings documents, handover docs, chat.
An item that arrives with depth (a debugging session's write-up, an operator-settled design) is
absorbed as **input**, with provenance; you carry it, you don't check it.

If an item still cannot be stated as a one-or-two-sentence requirement after the interview, it is
not ready to route — take it back to the operator; research on your side cannot fix that.

### Phase 3: Separate non-actionable items

Identify items that should not become slice work:

- **A duplicate within this triage set** (or of a card a plain board-list query surfaces) →
  **archive the card** (leave a short comment saying why). Do not hunt beyond that, and never
  check the code for "already implemented" — if a slice turns out to be already done, the planner
  discovers that cheaply and closes it.
- **Pure discussion / no actionable work** → flag for the operator.
- **Infrastructure or tooling work that bypasses the dev-agent slice workflow** (e.g. orchestrator
  tooling, chart-only ops) → note it for the operator; it is handled outside slices.

Present the separation to the operator for confirmation before grouping.

### Phase 4: Group into logical categories

Group the remaining items into **slices**. Follow these rules:

- **Group by related subject.** You are deciding what work is *about the same thing*; the planner
  decides the task breakdown later.
- **Do not use the number of API surfaces or applications touched as a grouping metric.**
  Delivering a feature end-to-end and correct matters more than limiting development complexity.
- **Favor larger groups, sized with the task model in mind.** A slice executes as 2–4 (max 5)
  independently testable, project-local tasks. A group that would plan to more than that is fine —
  raise it with the operator and split it into two slices here. It is easier to split now than to
  notice adjacent work scattered across separate slices later; when in doubt, group together.
- **Group on the asks as written — and accept bundling mistakes.** You have no code knowledge in
  this session, by design. If the subjects say the items belong together, group them; the planner
  re-shapes cheaply during refinement (split, kick an item back to the backlog, pull in an
  adjacent slice). When in doubt, group together.

### Phase 5: Write the slices

For each group, allocate a slice number and create the slice folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # prints e.g. 074
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

(The allocator is flock-guarded so concurrent sessions never collide; a burned number is a harmless
gap. Follow-up work to an existing slice takes a letter suffix — `087b` — not a fresh number.)
Slices persist in `slices/backlog/` until the operator plans them (do not assume immediate action);
a slice sitting in `backlog/` is awaiting `/plan-slice`, which plans it and promotes it into `slices/`.

Each slice folder contains:

- **`slice.md`** — the recorded change request. Its spine is a **numbered requirements list,
  each requirement in the operator's words** — quote the card, the findings doc, the chat; your
  own phrasing only where no operator wording exists, and marked as yours. The list is the
  planner's **starting acceptance-criteria set, 1:1** — input to triage never gets lost, however
  small the ask. Around the list, absorb the relevant material so the planner can work from the
  slice alone:
  - A one-line summary, then what is being requested and why, as the sources give it.
  - **The relevant source material, pulled in** (quoted, not just linked): findings-document
    sections, issue-tracker cards, chat discussion. A source's diagnosis, cause, or line
    reference is carried **attributed and unverified** — "the card claims…" — never restated
    as fact.
  - **Operator-provided API/spec definitions are carried through as specs.** When the operator hands
    you an API or interface definition (tool signatures, endpoint shapes, schemas, wire contracts),
    preserve it **in `slice.md`** at signature-level fidelity — named operations, parameters and
    defaults, return shapes, enums. The planner usually works from the slice alone, in a fresh
    session that never saw the chat, so a surface that lives only in the conversation is lost to
    them. You **may evolve or improve it** during triage — a cleaner version in the slice is welcome,
    and you should fold in any simplifications the operator agreed while clarifying — but the guardrail
    is that the planner must not end up building a **substantially different** API than the one
    the operator specified. Mark the **deltas** from the operator's original for provenance. (This is
    absorbing the operator's own spec, not authoring a new contract — see "Don't design" below.)
  - The **Q&A** from the comprehension interview, captured so the planner inherits that
    understanding.
  - **References to the issue-tracker items** that belong to this change request (by id).
- **Attachments (optional)** — pre-existing material that informs the request (a debugging
  write-up, a prior design or proposal). If it already lives in `handovers/`, **move it into the
  slice folder** so the planner has it in one place. You author no research documents of your own.

Finally, add the slice to the **Pending** section of `<spec-repo>/README.md` as a single
line matching the existing entries — `- **NNN** — <short title>: <one-clause summary> (#refs)` —
and commit the slice folder to the specs repo (stage files by name).

Your job here is to *absorb existing material* into a form the planner can focus on — not to
invent design, write acceptance criteria, issue feasibility verdicts, or propose an implementation.

### Phase 6: Update the issue tracker

The Triage cards are just collected thoughts and ideas — they have no standalone value once a slice
exists. For each of this project's cards that was folded into a slice:

- **Create one card on the Kanban board (To Do) per slice you wrote** — title `[NNN] <slice
  title>`, this project's owner tag and no other, a short highlights summary (not a restatement), a
  pointer to the slice folder, and the source-card ids it subsumes. That card flows **To Do → In
  Progress → Done** through `/run-slice`.
- **Archive the source cards** the slice subsumes — their content now lives in `slice.md`. Also
  archive the already-implemented / duplicate ones separated out in Phase 3 (with a short comment
  saying why). Items the operator wants parked rather than sliced go to **Later**; ones rejected
  outright go to **Won't Do**.

### Phase 7: Finish

**7a. Delete the transient triage working document.** All information must by now live in the
slices — the operator should be able to delete the triage scratch doc with nothing lost. If
anything would be lost, it has not been absorbed yet; fix that before deleting.

**7b. Notify the operator** per the host's notification convention — "N items triaged into M slices
under `<spec-repo>/slices/`. Run /plan-slice on a slice when ready."

Then stop. Do not start `/plan-slice` (except under the narrow interactive minimal-change
exception at the top of this skill).

## Key principles

- **Understand the ask, not the code.** The interview asks what the operator meant — it never
  sends you into the repo. All grounding, however shallow, is the planner's.
- **The operator's words are the record.** Requirements are quoted and numbered, and arrive at
  the planner as the starting acceptance criteria, 1:1. What the operator asks is what happens.
- **Don't plan, don't design.** Triage's output is grouped, absorbed change requests. No task
  breakdowns, no acceptance criteria, no feasibility verdicts, no *new* API contracts, no
  implementation proposals.
  (Preserving an API the operator *hands* you is not designing — see the next principle.)
- **Treat operator-provided specs as specs.** An API or interface the operator gives you (tool
  signatures, endpoint shapes, schemas — any API service) is source material, not a prompt to
  redesign. Preserve it in `slice.md` at signature-level fidelity; evolving or simplifying it is fine
  and expected (record the deltas), but substituting a substantially different surface is not. If you
  can't tell whether it's a sketch or a considered surface, ask (Phase 1c).
- **Favor larger groups.** Splitting later is cheap; missing adjacent work is expensive.
- **Iterate with the operator.** Ambiguous items get a QUESTION and a conversation, not a guess.
- **All information must have a home in the slice.** When triage is done, the triage working
  document is deleted and every fact lives in a `slice.md` or its attachments.
- **Don't write application code.** If the operator asks for an ad hoc code change, push back and
  route it through a slice (or, if it truly qualifies, the interactive minimal-change exception).
