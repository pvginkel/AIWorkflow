---
name: triage
description: Group a batch of findings, bugs, or requests into grounded slice folders (slice.md under slices/backlog/NNN_slug/) — the required input to /plan-slice. Does not plan slices.
argument-hint: "[findings-document]"
---

# Triage

Turn a batch of findings, requests, and issue-tracker items into grounded **slice folders** —
self-contained change requests under `<spec-repo>/slices/backlog/NNN_slug/`, the input to
`/plan-slice` (which plans them and promotes them up into `slices/`). Argument (optional): path to a findings document (e.g., `tmp/uat_testing.md`).

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line. **Preflight (step 0):** run
`python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage` and relay its message verbatim on a
non-zero exit — it bails when the `Spec repo:` entry is missing (there is nowhere to write a slice).
The issue-tracker and notification wiring this skill references generically (boards, lists, the
project's owner tag, how to notify) is defined by your host convention (`~/.claude/CLAUDE.md`).

The input can be a UAT run, a list of bugs, a change-request dump, chat discussion, or any
unstructured collection of issues. Triage understands it, groups it by subject, and writes one
slice per group. **Triage does not plan slices** — the task breakdown is `/plan-slice`'s job, in a
separate, deliberate act.

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

- A clear description of the issue.
- Its source (findings-document reference, issue-tracker id, or both).

This document is scratch — it exists to drive the clarification loop and is **deleted at the end
of triage** (Phase 7), once all information has been absorbed into the slices.

**1c. Clarify until you fully understand every item.** For every item that is vague, missing
information, or that simply needs research before it can be understood, add a **QUESTION** marker.
Present the document to the operator and iterate until every item is understood. Understanding the
request fully is the whole point of this phase — do not guess.

When an item hands you an **API or interface definition** — tool signatures, endpoint shapes, a
schema, a wire contract, anything with named operations, parameters, and return shapes — **ask
whether it is a rough sketch for inspiration or a considered surface.** The two look alike on the
page but demand opposite treatment: a sketch you may reshape freely; a considered surface you carry
through as a spec (Phase 5). Don't assume — ask.

**Do not group items into slices yet.** Phase 1 is about understanding individual items, not
deciding how they cluster.

### Phase 2: Ground enough to understand

Research items only to the depth needed to *understand* them — not to design or implement them.
The deep, file:line grounding that task plans depend on is the **planner's** job, not triage's.

- For an item whose meaning or feasibility is unclear, read the relevant code (use `Explore`
  sub-agents in parallel for groups of related items) until you understand what is actually being
  asked and whether it is coherent.
- Record findings back into the triage working document, and raise follow-up **QUESTION** markers
  where the code contradicts the reported behaviour or the request is ambiguous.
- If an item genuinely required research to understand, capture that research as a separate
  document — it becomes an attachment in the item's slice folder (Phase 5).

A concrete goal of this phase is to gather enough information that you can group the items **with
confidence** in Phase 4 — you have to understand what each item really is before you can judge what
it belongs with. If you cannot yet tell where an item clusters, you do not understand it well enough.

Iterate follow-up questions with the operator until resolved or explicitly deferred.

### Phase 3: Separate non-actionable items

Identify items that should not become slice work:

- **Already implemented, or a duplicate** → **archive the card** (leave a short comment saying why).
  It never reaches a slice.
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
- **Sanity-check against under-grouping.** Before finalizing, glance at the areas/files each item
  touches (from Phase 2's grounding): items that hit the same area or the same file almost certainly
  belong together. Over-grouping is cheap to split; *scattering* related work across separate
  slices is the expensive miss — that is the one to catch here.

### Phase 5: Write the slices

For each group, allocate a slice number and create the slice folder:

```bash
N=$(<spec-repo>/scripts/allocate-next-slice.sh)   # prints e.g. 074
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

(The allocator is flock-guarded so concurrent sessions never collide; a burned number is a harmless
gap. Follow-up work to an existing slice takes a letter suffix — `087b` — not a fresh number.)
Slices persist in `slices/backlog/` until the operator plans them (do not assume immediate action);
a slice sitting in `backlog/` is awaiting `/plan-slice`, which plans it and promotes it into `slices/`.

Each slice folder contains:

- **`slice.md`** — a self-contained write-up of the change request. It must absorb **all**
  the relevant material so the planner can work from the slice alone:
  - A one-line summary, then the detail of what is being requested and why.
  - **Abstracts of every referenced artifact** — the relevant content of findings-document
    sections, issue-tracker cards, and chat discussion, pulled in (not just linked).
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
  - The **Q&A** you did with the operator during clarification, captured so the planner
    inherits that understanding.
  - **References to the issue-tracker items** that belong to this change request (by id).
- **Attachments (optional)** — any research document you produced in Phase 2, and any pre-existing
  prior work that informs the request. If a relevant document already lives in `handovers/` (a
  prior design or proposal), **move it into the slice folder** so the planner has it in one place.

Finally, add the slice to the **Pending** section of `<spec-repo>/README.md` as a single
line matching the existing entries — `- **NNN** — <short title>: <one-clause summary> (#refs)` —
and commit the slice folder to the specs repo (stage files by name).

Your job here is to *absorb existing material* into a form the planner can focus on — not to
invent design, write acceptance criteria, or propose an implementation.

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

- **Ground only to understand.** Read enough code to understand and de-risk each item. Leave the
  deep file:line grounding to the planner — doing it twice wastes effort and goes stale.
- **Don't plan, don't design.** Triage's output is grouped, absorbed change requests. No task
  breakdowns, no acceptance criteria, no *new* API contracts, no implementation proposals.
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
