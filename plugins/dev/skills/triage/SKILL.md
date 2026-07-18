---
name: triage
description: Sort a batch of findings, bugs, or requests into slice folders that record the operator's requirements verbatim (slice.md under slices/backlog/NNN_slug/) — the required input to /plan-slice. Does not ground, design, or plan slices.
argument-hint: "[findings-document]"
---

# Triage

Sort a batch of findings, requests, and issue-tracker items — a UAT run, a bug list, a
change-request dump, chat discussion — into **slice folders**: recorded change requests under
`<spec-repo>/slices/backlog/NNN_slug/`, the required input to `/plan-slice`. Argument (optional):
path to a findings document (e.g., `tmp/uat_testing.md`).

Triage is the **first line**: it makes sure each ask is understood *as written*, records it in
the operator's words, and routes it. `/plan-slice` is the second line — the refinement session
that reads the code, grounds each requirement, and bottoms the ask out with the operator. **Every
change goes through triage** — there is no planning without a `slice.md` — and triage stops when
the slices are written.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage` and
relay its message verbatim on a non-zero exit. `<spec-repo>` is the path in your `CLAUDE.md`'s
`Spec repo:` line. Boards, lists, owner tags, and notification wiring are defined by your host
convention (`~/.claude/CLAUDE.md`).

## Rules

Triage is source-faithful and code-blind:

- **Never open application code** — no grep, no sub-agents into the repo, and no verifying that a
  thing an item names exists (it may be unbuilt in another pending slice). Your sources are the
  cards, the documents they cite, and the chat. A question only the code can answer is the
  planner's question.
- **Quote, don't restate.** A paraphrase can invert an ask (slice 087 turned "put an empty line
  above the shortcuts line" into its opposite); a quote cannot. Your own phrasing appears only
  where no operator wording exists, and is marked as yours.
- **Every input becomes a numbered requirement.** The planner seeds acceptance criteria from the
  list, 1:1 — nothing gets bundled away or summarized out of existence, however small the ask.
- **Claims stay claims.** A source's diagnosis, cause, or line reference is carried attributed
  ("the card claims…") and unverified — never endorsed.
- **No design — and a feasibility verdict *is* design.** No fixes, task shapes, acceptance
  criteria, test enumerations, or "settled / do not re-open". A design doc that arrives as input
  is attached and pointed at, not validated.
- **Only explicit answers are operator decisions.** Silence on a default you proposed is not
  approval; leave the open point to the planner.
- **Stop at the slice.** Don't start `/plan-slice`, and don't make ad hoc code changes — route
  them through a slice. One exception: the **operator explicitly asks** to carry straight on *and*
  you agree the change is genuinely minimal (a clear bug fix, a cosmetic fix); if you don't agree,
  say so. Even then `slice.md` is produced, the full planning process applies, and never from a
  sub-agent.

## Procedure

### 1. Collect

Gather every input: the findings document if one was passed, the relevant chat discussion, and the
outstanding cards carrying **this project's owner tag** in the Triage board's **Inbox**. Leave
other projects' cards alone; untagged cards are not-yet-claimed — if asked to consider one, say so
rather than adopting it silently.

Write a working document at `<spec-repo>/handovers/triage_YYYY-MM-DD.md` — scratch, deleted in
step 5 — with one numbered entry per item: the ask, quoted, and its source (findings-document
reference, card id, or both).

### 2. The comprehension interview

Mark every item that is vague or incomplete *as a request* with **QUESTION**; present the document
to the operator and iterate until every item is understood. The test for a triage question is that
**the operator can answer it from memory**: "you want a Cancel button — on which screen?"
qualifies; where the screen lives, or whether a reported cause is right, is the planner's. Don't
guess, and don't research your way past an ambiguity the operator can resolve in a sentence — an
item that still can't be stated as a one-or-two-sentence requirement is not ready to route; take
it back to the operator.

When an item hands you an **API or interface definition** (named operations, parameters, return
shapes), ask whether it is a rough sketch or a considered surface. The two look alike on the page
and demand opposite treatment: a sketch the planner may reshape freely; a considered surface is
carried as a spec (step 4). Don't assume — ask.

### 3. Sort

Separate the non-actionable and confirm the separation with the operator:

- **Duplicate** within this triage set, or of a card a plain board-list query surfaces → archive
  with a short comment. Don't hunt further, and never check the code for "already implemented" —
  the planner discovers that cheaply and closes the slice.
- **Pure discussion, no actionable work** → flag for the operator.
- **Infrastructure or tooling that bypasses the dev-agent slice workflow** → note it for the
  operator; it is handled outside slices.

Group the rest into slices **by subject, on the asks as written**:

- Favor larger groups, sized with the task model in mind: a slice executes as 2–4 (max 5)
  independently testable, project-local tasks. A group that would clearly plan bigger gets raised
  with the operator and split now.
- Don't use the number of API surfaces or applications touched as a grouping metric — delivering
  a feature end-to-end matters more than limiting development complexity.
- Bundling mistakes are expected and cheap — the planner re-shapes during refinement (split, kick
  an item back, pull an adjacent slice in). When in doubt, group together.

### 4. Write the slices

For each group, allocate a number and create the folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # flock-guarded; a burned number is a harmless gap
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

Follow-up work to an existing slice takes a letter suffix (`087b`), not a fresh number.

**`slice.md`** is the recorded change request. The planner works from it alone, in a fresh session
that never saw this conversation — anything that lives only in the chat is lost to them. It holds:

- A one-line summary, then what is being requested and why, as the sources give it.
- The **numbered requirements list** — the spine, written per the rules above.
- The relevant source material, quoted in (not just linked): findings sections, card text, chat.
- **Operator-provided API/spec definitions at signature-level fidelity** — named operations,
  parameters and defaults, return shapes, enums. Fold in simplifications the operator agreed to,
  and mark the deltas — but the planner must not end up building a substantially different
  surface than the one the operator specified.
- The interview **Q&A**.
- The ids of the source cards this slice subsumes.

**Attachments:** pre-existing material that informs the request (a debugging write-up, a prior
design or proposal) moves into the slice folder — including anything already in `handovers/`. You
author no research documents of your own.

Add each slice to the **Pending** section of `<spec-repo>/README.md` — one line matching the
existing entries, `- **NNN** — <short title>: <one-clause summary> (#refs)` — and commit the slice
folders to the specs repo, staging files by name.

### 5. Close out

- **Kanban:** one **To Do** card per slice — title `[NNN] <slice title>`, this project's owner
  tag and no other, a short highlights summary, a pointer to the slice folder, and the subsumed
  card ids.
- **Triage board:** archive the source cards each slice subsumes and the ones separated in
  step 3, each with a short comment saying why. Items the operator parks go to **Later**;
  rejections to **Won't Do**.
- **Delete the working document.** Every fact must now live in a slice or its attachments; if
  deleting would lose something, absorb that first.
- **Notify the operator** per the host convention — "N items triaged into M slices under
  `<spec-repo>/slices/backlog/`. Run /plan-slice on a slice when ready." — and stop.
