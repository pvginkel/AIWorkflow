---
name: triage
description: File a batch of findings, bugs, or requests as slice folders recording the operator's asks verbatim (slice.md under slices/backlog/NNN_slug/) — the required input to /plan-slice. Comprehension and routing only; grounding, design, and planning happen in /plan-slice.
argument-hint: "[findings-document]"
---

# Triage

Turn a batch of raw asks — Triage-board cards, a findings document, chat discussion — into filed
change requests: one slice folder per subject under `<spec-repo>/slices/backlog/NNN_slug/`, the
required input to `/plan-slice`. Argument (optional): path to a findings document (e.g.,
`tmp/uat_testing.md`).

**You are the intake clerk, not the analyst.** The job is to understand each ask *as the operator
wrote it*, record it in their words, and file it where it belongs. Reading the code, judging
feasibility, and designing the solution belong to `/plan-slice` — the refinement session that
grounds each requirement and bottoms the ask out with the operator. Triage is doable, by design,
without the repo: you never open application code, and you don't need to know whether anything an
item names exists yet. A question only the code can answer is the planner's question — leave it
open for them. Your product is a faithful record, and every change starts with one: there is no
planning without a `slice.md`.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage`; relay
its message verbatim on a non-zero exit. `<spec-repo>` is the path in your `CLAUDE.md`'s
`Spec repo:` line. Boards, lists, owner tags, and notification wiring come from your host
convention (`~/.claude/CLAUDE.md`).

## Procedure

### 1. Collect

Gather the inputs: the findings document if one was passed, the relevant chat discussion, and the
outstanding Inbox cards on the Triage board carrying **this project's owner tag** (other projects'
and untagged cards stay; if pointed at an untagged card, say so instead of adopting it).

Write a working document at `<spec-repo>/handovers/triage_YYYY-MM-DD.md` — scratch, deleted at the
end — with one numbered entry per item: the ask, **quoted**, and its source (findings-document
section, card id, or both).

### 2. Interview

For every item that is vague or incomplete *as a request*, add a **QUESTION** marker; present the
document to the operator and iterate until each item can be stated as a one-or-two-sentence
requirement. A triage question is one **the operator can answer from memory** — "you want a Cancel
button: on which screen?" qualifies; where that screen lives in the code does not. Don't guess,
and don't research your way past an ambiguity the operator can resolve in a sentence.

One caution while you talk: a proposed default is only settled by an explicit answer. If the
operator doesn't answer, the point stays open for the planner — don't record your proposal as
their decision.

### 3. Sort

Separate what shouldn't become a slice, and confirm the separation with the operator:

- **Duplicates** — within this triage set, or of a card a plain board-list query surfaces →
  archive with a short comment. (Whether something is already *implemented* is a code question;
  the planner discovers that cheaply.)
- **Pure discussion**, nothing actionable → flag for the operator.
- **Infrastructure or tooling outside the dev-agent slice workflow** → note for the operator; it
  is handled outside slices.

Group the rest **by subject, on the asks as written**. Favor larger groups — a slice plans into
3–6 (max 10) project-local, independently testable, PR-sized tasks, and a group that would
clearly blow past that is split with the operator now — but don't count API surfaces or
applications touched: delivering a feature
end-to-end beats limiting development complexity. Bundling mistakes are fine; the planner splits,
merges, and kicks items back cheaply during refinement. When in doubt, group together.

### 4. File

For each group, allocate a number and create the folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # flock-guarded; a burned number is a harmless gap
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

Follow-up work to an existing slice takes a letter suffix (`087b`), not a fresh number.

**`slice.md`** is the record. The planner works from it alone, in a fresh session that never saw
this conversation. It holds:

- A one-line summary, then what is being requested and why, as the sources give it.
- **The numbered requirements list** — every input item, in the operator's words. Quote: a
  paraphrase can silently invert an ask; a quote cannot. Your own phrasing appears only where no
  operator wording exists, marked as yours. The planner seeds acceptance criteria from this list
  1:1, so an ask that isn't on it is lost.
- The relevant source material, quoted in (not just linked). A source's diagnosis, cause, or line
  reference stays attributed — "the card claims…" — you have no way to verify it and don't try.
- **Operator-provided API/spec definitions, carried over as given** — signature-level fidelity:
  named operations, parameters and defaults, return shapes, enums. Don't restate a definition as
  high-level intent; the definition itself is the record. If the conversation evolved it, carry
  the final agreed version and let the Q&A show the evolution.
- The interview **Q&A**, and the ids of the cards this slice subsumes.

Requirements, not solutions: no fixes, no task shapes, no acceptance criteria, no feasibility
verdicts. **Attachments** that arrive with the work (a debugging write-up, a prior design or
proposal — including anything already in `handovers/`) move into the slice folder as input,
unvalidated; you author none of your own.

Add each slice to the **Pending** section of `<spec-repo>/README.md` — one line matching the
existing entries, `- **NNN** — <short title>: <one-clause summary> (#refs)` — and commit the
slice folders to the specs repo, staging files by name.

### 5. Close out

- **Kanban:** one **To Do** card per slice — title `[NNN] <slice title>`, this project's owner
  tag and no other, a short highlights summary, a pointer to the slice folder, and the subsumed
  card ids.
- **Triage board:** archive the cards the slices subsume and the duplicates from step 3, each
  with a short comment. Items the operator parks go to **Later**; rejections to **Won't Do**.
- **Delete the working document** — if deleting it would lose a fact, it isn't absorbed yet.
- **Notify the operator** per the host convention — "N items triaged into M slices under
  `<spec-repo>/slices/backlog/`. Run /plan-slice on a slice when ready." — and stop.

Stop means stop: planning is the operator's next move, in their own time. The one exception — the
operator explicitly asks to carry straight on into `/plan-slice` *and* you agree the change is
genuinely minimal — still produces the `slice.md`, still runs the full planning process, and
never happens from a sub-agent. If you don't agree it's minimal, say so.
