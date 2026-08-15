---
name: triage
description: File a batch of findings, bugs, or requests with a filtering pass — mechanically categorize every item (nit pick → major) for the operator to adjudicate, so cruft dies before planning spends on it, then record the survivors' asks verbatim as slice folders (slice.md under slices/backlog/NNN_slug/), the required input to /dev:plan-slice. Comprehension, categorization, and routing only; grounding, design, and planning happen in /dev:plan-slice.
argument-hint: "[findings-document]"
---

# Triage

Turn a batch of raw asks — tracker intake cards, a findings document, chat discussion — into
adjudicated work: the cruft closed by the operator *before* planning can spend on it, the rest
filed as change requests — one slice folder per subject under `<spec-repo>/slices/backlog/NNN_slug/`,
the required input to `/dev:plan-slice`. Argument (optional): path to a findings document (e.g.,
`tmp/uat_testing.md`).

**You are the intake clerk, not the analyst.** The job is to understand each ask *as the operator
wrote it*, label it so the operator can decide what progresses, and file what survives where it
belongs. Reading the code, judging feasibility, and designing the solution belong to
`/dev:plan-slice` — the refinement session that grounds each requirement and bottoms the ask out
with the operator. This session never opens application code: when a label genuinely can't be
settled from the text (step 5), a dispatched read-only sub-agent fetches the one fact it turns on —
the judgment still happens here. Two rules carry the design: **no item is ever closed by machine
judgment alone** — you recommend, the operator closes — and your product is a faithful record:
there is no planning without a `slice.md`.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage`; relay
its message verbatim on a non-zero exit. `<spec-repo>` is the path in your `CLAUDE.md`'s
`Spec repo:` line. Boards, lists, owner tags, and notification wiring come from your host
convention (`~/.claude/CLAUDE.md`).

Steps that don't apply are skipped silently: no questions and clean labels → present and move on;
nothing flagged for research → no research round and no second pass; the document is re-presented
only when it changed.

## Procedure

### 1. Collect — everything on disk first

Gather the inputs: the findings document if one was passed, the relevant chat discussion, and the
outstanding intake-queue cards carrying **this project's owner tag** (other projects' and untagged
cards stay; if pointed at an untagged card, say so instead of adopting it). A slice's
`close-out.md` (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`) is a findings document too: its
entries whose `Disposition:` line is blank or says `defer` are the items — one per entry, the
entry verbatim as the source.

Before anything else, write the raw material verbatim to
`<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md` — full card contents, the chat passages being
triaged, a pointer to the findings document. When triage starts mid-session out of an interactive
discussion, this dump is the first act: the session is ephemeral, the file is not. Both working
files (this and the status document below) are scratch, deleted at close-out.

### 2. Itemize and categorize

**Itemize mechanically** from the dump, no research: one item per distinct ask. A card is
generally one item; a card that is itself a list of independent asks (a residuals card) becomes
several. When it is unclear whether something is one task or many, keep it as one — the planner
splits cheaply. Open the **status document**, `<spec-repo>/handovers/triage_YYYY-MM-DD.md`, one
block per item:

```
### <n>. <short title>
- Source: <card id and/or findings-document section>
- Ask: "<the ask, quoted verbatim — the stated symptom and the stated consequence>"
- Question: <only when one exists — see below>
- Category: <label> — "<justifying quote>"
- Research: <only when flagged — the one named question that settles the label>
- Ruling: —
```

You judge from the `Ask` extract; the dump stays the archive. A source's diagnosis, cause, or
line reference is an attributed claim ("the card claims…") — you can't verify it here and don't
try.

**Label each item independently** — one item, one verdict against the rubric, blind to the rest
of the batch. The justification is **a verbatim quote from the source and nothing else** — no
reasoning sentence, no restated evidence. If no quote supports the label, the label isn't
supported. Rules, in order:

1. **Determinability first.** Before reasoning toward a category, decide whether the text
   supports one. Too vague for a decent determination → `undetermined` (parenthesize a suspected
   label if it helps the operator) plus the `Research:` line.
2. **The stated consequence decides** — not the claimed cause, and not the tone. A calmly-written
   card describing data corruption is Major; an alarmed card about log wording is a nit pick. If
   the source claims a severity, take the claim: a card stating a major issue *is* Major until
   the operator or a research verdict says otherwise. Your own severity instinct is not an input.
3. **Severity dominance.** When two categories *genuinely both apply*, the more severe wins — a
   corner case with data-corruption potential is Major. This is not a tie-break for uncertainty:
   uncertain is the source's claim standing, or `undetermined`.
4. **Borderline is a legal label.** `Minor/Corner case — borderline` routes the call to the
   operator; don't force a resolution the text doesn't support.
5. **Invalid and Corner case are guarded.** They are the two labels reachable by pure assumption,
   so neither may rest on your belief about the system — only on the source saying so (quote it),
   an operator ruling, or a research verdict naming what was checked. Absent all three:
   `undetermined` with the `Research:` line.

The rubric — the examples are part of the definition:

- **Nit pick** (`user-visible` or `internal`) — a remark on wording: a code comment, a log line,
  screen text. Impactful wording still counts. *"the failure toast says 'unexpected error' even
  when the server names the cause"* → Nit pick, user-visible; *"the retry log line prints the
  attempt number twice"* → Nit pick, internal.
- **Corner case** — can't happen in practice, or takes the user doing something that makes no
  sense; hand-editing a URL's query parameters counts. *"pasting a step-5 wizard URL before
  completing step 1 renders a blank panel"* → Corner case. The same ask with corruption
  potential is Major (rule 3).
- **Minor** — a real defect with debatable user impact, including quirks the user immediately
  understands. *"the list shows the stale name until you switch tabs and back"* → Minor.
- **Major** — data corruption, data loss, outage, security. *"saving from two tabs silently
  drops the first tab's edit"* → Major.
- **Improvement** — an optional betterment, not a defect. *"remember the last-used filter across
  sessions"*.
- **Feature** — new capability. *"add CSV export to the report screen"*.
- **Invalid** (guarded — rule 5) — no longer applies, or doesn't reproduce. *"the card targets
  the legacy import screen"* where the source itself notes that screen was removed.

**Questions** ride the same document. The `Question:` line takes both kinds — one the source
itself states ("the card asks whether…") and one you need because the item is vague *as a
request* — but only questions **the operator can answer from memory**: "you want a Cancel
button: on which screen?" qualifies; where that screen lives in the code does not. A question
only the code can answer either waits for the planner or, when the *label* turns on it, becomes
the item's `Research:` line.

### 3. The operator pass

Present the status document — one consolidated pass: questions, labels, and research flags
together. The operator rules per item on the `Ruling:` line, in four forms, each with fixed
behaviour:

- **close** — binding. The item dies with a tracker disposition (step 8); no re-derivation, no
  argument.
- **answer: …** — a new fact. Re-derive the label from source-plus-fact; the updated `Category:`
  line quotes what changed the call.
- **override: \<category\>** — the operator's label, recorded as theirs. Not re-derived.
- **remark: …** — recorded verbatim, and it moves nothing unless it contains a fact (then it's
  an answer). A label never shifts because the operator sounded unconvinced — an honest override
  beats a re-judged label.

The operator may also add or strike `Research:` lines directly. One caution while you talk: a
proposed default is only settled by an explicit answer. If the operator doesn't answer, the point
stays open for the planner — don't record your proposal as their decision. One machine pass per
operator pass, and edits are item-local: action the rulings, don't re-polish the document.

### 4. Research — only what's still open

For each item that still carries a `Research:` line after the rulings, dispatch one **read-only
sub-agent**, in parallel across items. The brief is the item's one named question — the fact the
label turns on, quoting the source: "does *'\<claim\>'* reproduce on \<the named screen/path\>?",
"is \<the path the card calls impossible\> actually reachable?" — and nothing else: never "assess
this item", never "how would we fix it". The sub-agent may read across the repo and take the
turns it needs; **"cannot determine" is an allowed verdict** and leaves the source's claim
standing.

The sub-agent reports the fact; the label call stays here. Fold each verdict in — `Category:`
updated, the verdict kept to one line ("research: reproduces on \<path\>") — and nothing else
survives: this research settles labels, it is not planning groundwork, and none of it carries
into the slice. If any label changed, present the changed items for one more operator pass.

### 5. Sort

Separate what shouldn't become a slice, and confirm the separation with the operator:

- **Duplicates** — within this triage set, or of a card a plain tracker query surfaces →
  archive with a short comment. (Whether something is already *implemented* is a code question;
  the planner discovers that cheaply.)
- **Pure discussion**, nothing actionable → flag for the operator.
- **Operator-owned work** — infrastructure or tooling outside the dev-agent slice workflow, or an
  action only the operator can take → move the card to the **operator's action queue**, with a
  one-line comment saying what is theirs to do.
- **Solution Known** — a senior dev could deliver quality work from the card alone, and it
  passes the litmus in step 7 → write the acceptance criteria into the card, per step 7. These
  skip filing (step 6) and planning both: step 7 batches them straight into a run-ready slice.
  A surviving **user-visible nit pick** is the archetypal candidate — decided change, plain
  impact — check those against the litmus first.

Group the rest **by subject, on the asks as written**. Favor larger groups — a slice plans into
3–6 (max 10) project-local, independently testable, PR-sized tasks, and a group that would
clearly blow past that is split with the operator now — but don't count API surfaces or
applications touched: delivering a feature end-to-end beats limiting development complexity.
Bundling mistakes are fine; the planner splits, merges, and kicks items back cheaply during
refinement. When in doubt, group together.

### 6. File

For each group, allocate a number and create the folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # flock-guarded; a burned number is a harmless gap
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

Follow-up work to an existing slice takes a letter suffix (`087b`), not a fresh number.

**`slice.md`** is the record. The planner works from it alone, in a fresh session that never saw
this conversation. It holds:

- A one-line summary carrying the slice's **headline category** — the most severe among its
  items — then what is being requested and why, as the sources give it.
- **The numbered requirements list** — every input item, in the operator's words, each tagged
  with its final category. Quote: a paraphrase can silently invert an ask; a quote cannot. Your
  own phrasing appears only where no operator wording exists, marked as yours. The planner seeds
  acceptance criteria from this list 1:1, so an ask that isn't on it is lost.
- The relevant source material, quoted in (not just linked). A source's diagnosis, cause, or line
  reference stays attributed — "the card claims…" — you have no way to verify it and don't try.
- **Operator-provided API/spec definitions, carried over as given** — signature-level fidelity:
  named operations, parameters and defaults, return shapes, enums. Don't restate a definition as
  high-level intent; the definition itself is the record. If the conversation evolved it, carry
  the final agreed version and let the Q&A show the evolution.
- The **Q&A and operator rulings** from the passes, and the ids of the cards this slice subsumes.

Requirements, not solutions: no fixes, no task shapes, no acceptance criteria, no feasibility
verdicts. **Attachments** that arrive with the work (a debugging write-up, a prior design or
proposal — including anything already in `handovers/`) move into the slice folder as input,
unvalidated; you author none of your own.

Add each slice to the **Pending** section of `<spec-repo>/README.md` — one line matching the
existing entries, `- **NNN** — <short title>: <one-clause summary> (<headline category>; #refs)` —
and commit the slice folders to the specs repo, staging files by name.

### 7. Sweep the Solution Known cards

**The litmus (and the risk filter):** the label means *a senior dev could take the card, as
written, and deliver quality work with no preparation*. That takes two things, both legible in
the card text: **what to change** is fully decided — no choice with consequences left to the
implementer — and **the impact** is plain — what the change touches and what breaks if it goes
wrong. Moderate size is fine; an open decision is not. Operationally: you can write the card's
acceptance criteria — outcome-level, one or a few — from its text alone. You never open code
here, so if the criteria would need grounding, the card goes the normal route.

Never label: concurrency or timing behaviour; storage-layout or wire-contract changes; a card
that leaves anything open ("investigate", "decide", "confirm"); or a fix that **adds
behaviour** — a new code path, process, or piece of state — rather than correcting what exists
in place. Added behaviour carries design surface (failure policy, bounds, collisions with
documented rulings) that a card cannot prove is settled, however completely it argues its
diagnosis — a root-caused bug with an empirically verified fix mechanism still leaves the
*change* undecided. Mechanism-verified is not change-decided. When in doubt, the normal route:
an over-careful card merely costs a planning session; a mislabelled one ships unadjudicated
design.

When a card qualifies, append its criteria to the card description under an
`## Acceptance criteria` heading — that section is the only mark a qualifying card carries, and
it persists, so a later session sweeps cards this one only qualified. The Solution Known set is
part of step 5's confirmation with the operator.

When the intake queue holds **five or more** qualifying cards with this project's owner tag (fewer
simply accumulate — say so in the close-out), assemble the payload — one item per card: a short
imperative title, `target` (a `kc project list` component name or a sibling-repo path, read off
the paths the card itself cites — routing, not code reading), the card description verbatim as
`body`, and the criteria; a multi-item card whose bullets need different targets becomes several
items citing the same card (the script's docstring holds the schema) — and run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/sweep_slice.py <payload.json>
```

It allocates the number, writes `slice.md` / `plan.md` / `verification.json` under
`<spec-repo>/slices/NNN_<slug>/` — born planned, skipping `/dev:plan-slice` — validates the plan with
the run loop's `--dry-run`, adds the README **Pending** line, and stages by name. Relay its
errors verbatim; on success, fold the results into step 8: commit the staged spec-repo files, one
slice card `[NNN] Residual sweep` (triaged, as in step 8), and archive each swept card with a
comment naming the slice folder. Running the slice stays the operator's move (`/dev:run-slice`), like any other.
Rules and rationale: `${CLAUDE_PLUGIN_ROOT}/docs/residual-sweep.md`.

### 8. Close out

- **Slice cards:** one per slice, in its **triaged** state — title `[NNN] <slice title>`, this
  project's owner tag and no other, a short highlights summary, a pointer to the slice folder,
  and the subsumed card ids.
- **Intake queue:** archive the cards the slices subsume, the duplicates from step 5, and the
  items the operator closed at the filter — each with a one-line comment carrying the ruling
  ("closed at triage: corner case"). Items the operator parks take the tracker's **deferred**
  disposition; rejections its **rejected** one.
- **Delete both working documents** — if deleting them would lose a fact, it isn't absorbed yet.
- **Notify the operator** per the host convention — "N items triaged: K closed at the filter,
  M slices under `<spec-repo>/slices/backlog/`. Run /dev:plan-slice on a slice when ready." —
  plus, when step 7 ran, "J cards swept into slice NNN — run /dev:run-slice on it when ready"
  (or how many qualifying cards are still accumulating) — and stop.

Stop means stop: planning is the operator's next move, in their own time. The one exception — the
operator explicitly asks to carry straight on into `/dev:plan-slice` *and* you agree the change is
genuinely minimal — still produces the `slice.md`, still runs the full planning process, and
never happens from a sub-agent. If you don't agree it's minimal, say so.
