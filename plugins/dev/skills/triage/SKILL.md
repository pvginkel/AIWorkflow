---
name: triage
description: File a batch of findings, bugs, or requests with a filtering pass — mechanically categorize every item (nit pick → major) for the operator to adjudicate and persist each verdict on its tracker card, so cruft dies before planning spends on it; then record the survivors' asks verbatim as slice folders (slice.md under slices/backlog/NNN_slug/), the required input to /dev:plan-slice. Runs whole or as either half — adjudicate now, dispose later from the labelled board — over the intake queue or a selection of it. Comprehension, categorization, and routing only; grounding, design, and planning happen in /dev:plan-slice.
argument-hint: "[findings-document] [card ids to scope the run]"
---

# Triage

Turn a batch of raw asks — tracker intake cards, a findings document, chat discussion — into
adjudicated work: the cruft closed by the operator *before* planning can spend on it, the rest
filed as change requests — one slice folder per subject under `<spec-repo>/slices/backlog/NNN_slug/`,
the required input to `/dev:plan-slice`. Argument (optional): path to a findings document (e.g.,
`tmp/uat_testing.md`).

The work has two halves with a durable seam between them. **Adjudicate** (steps 1–5): what is
each item, and does it deserve to live — one item at a time, blind to the rest, ending with every
verdict on its card as a tracker label. **Dispose** (steps 6–9): what becomes a slice and what
dies — the batch as a set. The operator chooses per run: both halves in one sitting, adjudicate
now and dispose in a later session from the labelled board, or dispose cards an earlier session
prepared — and any run may be scoped to a selection of cards. The seam holds because nothing of
the record lives only in a session: the verdict is on the card, the reasons are in a committed
working document.

**You are the intake clerk, not the analyst.** The job is to understand each ask *as the operator
wrote it*, label it so the operator can decide what progresses, and file what survives where it
belongs. Reading the code, judging feasibility, and designing the solution belong to
`/dev:plan-slice` — the refinement session that grounds each requirement and bottoms the ask out
with the operator. This session never opens application code: when a label genuinely can't be
settled from the text (step 4), a dispatched read-only sub-agent fetches the one fact it turns on —
the judgment still happens here. Two rules carry the design: **no item is ever closed by machine
judgment alone** — you recommend, the operator closes — and your product is a faithful record:
there is no planning without a `slice.md`.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage`; relay
its message verbatim on a non-zero exit. `<spec-repo>` is the path in your `CLAUDE.md`'s
`Spec repo:` line. Boards, lists, owner tags, and notification wiring come from your host
convention (`~/.claude/CLAUDE.md`).

Steps that don't apply are skipped silently: no questions and clean labels → present and move on;
nothing flagged for research → no research round and no second pass; the document is re-presented
only when it changed; a run over already-labelled cards begins at step 6.

## Procedure

### 1. Collect — everything on disk first

Gather the inputs: the findings document if one was passed, the relevant chat discussion, and the
outstanding intake-queue cards carrying **this project's owner tag** — all of them, or the
selection the operator scoped the run to (ids, a list; the rest stay untouched, and the close-out
says so). Other projects' and untagged cards stay: if pointed at an untagged card, say so instead
of adopting it, and a card under another project's tag whose substance is this project's is
flagged by id — mine, mis-tagged? — never adopted; retagging is the operator's. A
`[NNN] close-out: …` card is not an ask but the marker that a slice's `close-out.md` is waiting
(`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`): read the report it names, take as items its live
entries whose `Disposition:` line is blank or says `defer` — one per entry, the entry verbatim as
the source — and never itemize the card itself.

A card already carrying a rubric label is adjudicated — by an earlier session or by the operator's
own hand — and its verdict is not re-derived; where a working document under `handovers/` holds
the item, its rulings and research are read from there. Such cards wait for step 6.

Before anything else, the raw material lands verbatim in
`<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md` — full card contents, the chat passages being
triaged, a pointer to the findings document. When triage starts mid-session out of an interactive
discussion, this dump is the first act: the session is ephemeral, the file is not. The card fetch
is delegated — one read-only sub-agent per list or source, in parallel, each writing its part of
the dump, so no card passes through this session's context on its way to disk. Each brief says:
whole and verbatim — title, labels, reporter, description, comments, URL, in the source's order —
the title is part of the ask (dead routing hides in a title as readily as in a body); the
tracker's fetch caveats from the host convention (a narrowed query silently drops the field that
tells an operator's ask from a session-authored card); and that broken markup in a source (a
literal `&gt;`, a stray entity) is reproduced as found — it renders wrong at the source too, and
"fixing" it is a transcription error.

Both working files — this dump and the status document below — live in the spec repo, are
committed at every pass boundary (staged by name), and are the record between sessions until
step 9 deletes them.

### 2. Itemize and categorize

**Itemize mechanically** from the dump, no research: one item per distinct ask. A card is
generally one item; a card that is itself a list of independent asks (a residuals card) becomes
several. When it is unclear whether something is one task or many, keep it as one — the planner
splits cheaply. Ids are assigned once and never change — the card number, suffixed `a`, `b`… when
a card yields several items (`#472b`), the findings-document section, a running number for chat
passages — so an item that changes group keeps its handle. Open the **status document**,
`<spec-repo>/handovers/triage_YYYY-MM-DD.md`, one block per item:

```
### <id> — <short title> — <card URL>
- Source: <card id and/or findings-document section>
- Ask: "<the ask, quoted verbatim — the stated symptom and the stated consequence>"
- Question: <only when one exists — see below>
- Category: <label> — "<justifying quote>"
- Note: <only when the label hides stakes the operator should see — rule 2>
- Research: <only when flagged — the one named question that settles the label>
- Ruling: —

**Card text:** <the source, whole and verbatim from the dump>
```

The document is grouped by verdict — one section per category, most severe first,
`undetermined` last — because a verdict group is the view the operator acts on: the nit picks
together *are* the cull list. An item whose label changes moves to its new group and nothing else
moves. Never write a count into the document — counts go stale as items re-home; derive them at
the notify line. `**Card text:**` inlines the source whole, so the operator reads without looking
anything up — length is not the enemy, lookups are — with headings inside it demoted (depth only,
said once at the head of the document) so a source's own `##` doesn't collide with the outline.
The document opens with that note and the ruling vocabulary (step 3).

You judge from the `Ask` extract; the dump stays the archive. A source's diagnosis, cause, or
line reference is an attributed claim ("the card claims…") — you can't verify it here and don't
try.

At scale — dozens of items — composition is delegated too: once every item is labelled, one
sub-agent per verdict group writes that group's section (blocks plus card text) to its own
fragment, no two agents on one file, and the session assembles them. Each brief says **never
alter a verdict line**, and the check is mechanical, not an eyeball: every `Ask:` / `Category:` /
`Question:` / `Note:` / `Research:` / `Ruling:` line in the assembled document is extracted and
diffed against the labelled source before the document is presented. That check is all that
stands between a sub-agent and a silently rewritten judgement.

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
   When the source's own framing and its described consequence disagree — an outage-shaped
   consequence under a card that calls itself accepted behaviour, not a regression, a decision to
   make — the explicit framing wins, being the more specific claim, and the stakes go on the
   `Note:` line so the operator sees what they are ruling on.
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

- **Nit pick** (`user-visible` or `internal` — the sub-split is recorded in the block, not as a
  second label; it matters at step 6) — a remark on wording: a code comment, a log line, screen
  text. Impactful wording still counts. *"the failure toast says 'unexpected error' even when the
  server names the cause"* → Nit pick, user-visible; *"the retry log line prints the attempt
  number twice"* → Nit pick, internal.
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
- **Test gap** — a guarantee no test pins, with no observed failure: not a defect and no user
  impact, but not wording either. *"nothing covers the exporter's empty-list branch"* → Test gap.
  A *failing* test is a defect and takes its consequence's rung.
- **Decision** — nothing is broken; the source asks the operator to rule. *"nothing to build —
  confirm the deviation is acceptable"* → Decision. The cheapest class on the board: a minute of
  thought, not a planning session — the ruling is the disposition (step 6).
- **Invalid** (guarded — rule 5) — no longer applies, or doesn't reproduce. *"the card targets
  the legacy import screen"* where the source itself notes that screen was removed.

Outside the rubric: an **operator chore** — a maintenance task addressed to the operator, not an
ask about the system (*"full-sync these three environments"*) — takes no rubric label. It is
operator-owned work (step 6), marked the way the host convention marks chores.

**Questions** ride the same document. The `Question:` line takes both kinds — one the source
itself states ("the card asks whether…") and one you need because the item is vague *as a
request* — but only questions **the operator can answer from memory**: "you want a Cancel
button: on which screen?" qualifies; where that screen lives in the code does not. A question
only the code can answer either waits for the planner or, when the *label* turns on it, becomes
the item's `Research:` line.

### 3. The operator pass

Present the status document — one consolidated pass: questions, labels, and research flags
together. Its header states the ruling vocabulary, so the operator needn't invent one and this
session needn't guess at one; the operator rules per item on the `Ruling:` line, in their own
words, and these forms have fixed behaviour.

Label rulings — the verdict:

- **answer: …** — a new fact. Re-derive the label from source-plus-fact; the updated `Category:`
  line quotes what changed the call.
- **override: \<category\>** — the operator's label, recorded as theirs. Not re-derived.
- **remark: …** — recorded verbatim, and it moves nothing unless it contains a fact (then it's
  an answer). A label never shifts because the operator sounded unconvinced — an honest override
  beats a re-judged label.

Dispositions — the item's fate, actioned at the seam and in steps 6–9:

- **close** — binding. The item dies with a tracker disposition (step 5); no re-derivation, no
  argument. **later** parks it (the tracker's deferred disposition).
- **agreed** — the card as written *and* any recommendation this document made on it, to the
  normal route.
- **apply the suggested edit** — a ceiling: the literal change the card names and nothing beyond
  it. Recorded verbatim as a ruling the slice or sweep carries; work past the words is out of
  scope.
- **conditional: \<ruling\> if \<fact\>** — a ruling contingent on something the operator doesn't
  have. Not an approval: the fact becomes the item's `Research:` line, and the item comes back
  with the verdict for a final ruling.
- **split: …** — the named part becomes its own item (and its own card, step 9); the remainder
  takes its own ruling.
- **superseded by …** — the ruling replaces the ask: work already done, a broader change, an
  answer that made the card moot. The card closes naming what supersedes it — or, when the ruling
  *rewrites* the ask, is retitled and rewritten in the operator's words (step 9).

The operator may also add or strike `Research:` lines directly — a ruling round asks questions of
its own, and each becomes one. One caution while you talk: a proposed default is only settled by
an explicit answer. If the operator doesn't answer, the point stays open for the planner — don't
record your proposal as their decision. One machine pass per operator pass, and edits are
item-local: action the rulings, don't re-polish the document — a re-format the operator asks for
is not polishing.

### 4. Research — only what's still open, until nothing is

For each item that carries a `Research:` line after the rulings — flagged at labelling, added by
the operator, or produced by a conditional ruling — dispatch one **read-only sub-agent**, in
parallel across items. The brief is the item's one named question — the fact the label or the
ruling turns on, quoting the source: "does *'\<claim\>'* reproduce on \<the named screen/path\>?",
"is \<the path the card calls impossible\> actually reachable?" — and nothing else: never "assess
this item", never "how would we fix it". The sub-agent may read across the repo and take the
turns it needs; **"cannot determine" is an allowed verdict** and leaves the source's claim
standing — it goes onto the item's `Question:` line, since the operator may know from memory what
the repo cannot show, rather than stranding the item.

The sub-agent reports the fact; the label call stays here. Fold each verdict in — `Category:`
updated, the verdict kept to one line in the document ("research: reproduces on \<path\>") — and
record it on the card as a comment, dated and marked as triage research: durable, visible to the
next session, and source material a slice quotes attributed like any other card claim (step 7).
None of it becomes this session's own design: this research settles labels and rulings, it is
not planning groundwork.

Rulings raise questions of their own, so this is a loop, not a terminus: changed items and
answered questions go back for one more operator pass, and the round repeats until no
`Research:` line is open — one machine pass per operator pass throughout.

### 5. Persist the verdicts — the seam

When the round settles, write every item's final category onto its card as the tracker's label —
the operator-ruled category, from the host convention's label set, one rubric label per card. The
owner tag and any status marker stay: labels are written additively, and a tracker whose label
write replaces the card's whole set is sent the full set. Every ruled card is labelled, the ones
about to close included — the archive stays auditable that way. Then action `close` and `later`,
adjudication's own outcomes: `close` archives the card with a one-line comment carrying the ruling
("closed at triage: corner case") — or takes the tracker's rejected disposition when the ruling
rejects the ask itself — and `later` takes its deferred one.

Delegated board work runs on **disjoint card sets** — each brief names the cards that are its
and the cards it must not touch — and is verified on the board itself, by spot check, never from
the agent's report.

Commit both working documents (staged by name). This is the seam: the board carries the verdicts
and the documents carry the reasons, so a session may stop here — notify "N items adjudicated, K
closed at the filter; labels on the board, record under `handovers/`; run /dev:triage again to
dispose" — and a later session starts at step 6 from the labelled cards. Or carry on.

### 6. Sort

Separate what shouldn't become a slice, and confirm the separation with the operator:

- **Duplicates** — within this triage set, or of a card a plain tracker query surfaces →
  archive with a short comment. (Whether something is already *implemented* is a code question;
  the planner discovers that cheaply.)
- **Pure discussion**, nothing actionable → flag for the operator.
- **Decisions** — a `Decision` item ends at its ruling: the answer closes the card, or rides as a
  ruling into the slice it bears on. Nothing is filed for it alone.
- **Operator-owned work** — infrastructure or tooling outside the dev-agent slice workflow, an
  operator chore, or an action only the operator can take → move the card to the **operator's
  action queue**, with a one-line comment saying what is theirs to do.
- **Solution Known** — a senior dev could deliver quality work from the card alone, and it
  passes the litmus in step 8 → write the acceptance criteria into the card, per step 8. These
  skip filing (step 7) and planning both: step 8 batches them straight into a run-ready slice.
  A surviving **user-visible nit pick** is the archetypal candidate — decided change, plain
  impact — check those against the litmus first; a card that arrives already marked from an
  earlier session is re-checked there too.

Group the rest **by subject, on the asks as written**. Favor larger groups — a slice plans into
3–6 (max 10) project-local, independently testable, PR-sized tasks, and a group that would
clearly blow past that is split with the operator now — but don't count API surfaces or
applications touched: delivering a feature end-to-end beats limiting development complexity.
Bundling mistakes are fine; the planner splits, merges, and kicks items back cheaply during
refinement. When in doubt, group together.

### 7. File

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
- The relevant source material, quoted in (not just linked) — triage's dated research comments on
  the cards included, attributed as such. A source's diagnosis, cause, or line reference stays
  attributed — "the card claims…" — you have no way to verify it and don't try.
- **Operator-provided API/spec definitions, carried over as given** — signature-level fidelity:
  named operations, parameters and defaults, return shapes, enums. Don't restate a definition as
  high-level intent; the definition itself is the record. If the conversation evolved it, carry
  the final agreed version and let the Q&A show the evolution.
- The **Q&A and operator rulings** from the passes — a ceiling (`apply the suggested edit`)
  verbatim, it bounds the planner too — and the ids of the cards this slice subsumes.

Requirements, not solutions: no fixes, no task shapes, no acceptance criteria, no feasibility
verdicts. **Attachments** that arrive with the work (a debugging write-up, a prior design or
proposal — including anything already in `handovers/`) move into the slice folder as input,
unvalidated; you author none of your own.

Add each slice to the **Pending** section of `<spec-repo>/README.md` — one line matching the
existing entries, `- **NNN** — <short title>: <one-clause summary> (<headline category>; #refs)` —
and commit the slice folders to the specs repo, staging files by name.

### 8. Sweep the Solution Known cards

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
it persists, so a later session sweeps cards this one only qualified. The mark persists; so does
the litmus's right to move: a card carrying the section from an earlier session is re-checked
against the litmus as it stands before it is swept — an earlier revision's mark vouches for
nothing — and one that fails loses the section, with a comment saying why, and takes the normal
route. The Solution Known set is part of step 6's confirmation with the operator.

When the intake queue holds **five or more** qualifying cards with this project's owner tag (fewer
simply accumulate — say so in the close-out), assemble the payload — one item per card: a short
imperative title, `target` (a `kc project list` component name or a sibling-repo path, read off
the paths the card itself cites — routing, not code reading), the card description verbatim as
`body`, and the criteria; a multi-item card whose bullets need different targets becomes several
items citing the same card (the script's docstring holds the schema). A sweep is a slice and
sized like one — the generator refuses more than ten phases; a larger set splits by target into
several payloads of five to ten, each its own sweep, filed one after another — and run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/sweep_slice.py <payload.json>
```

It allocates the number, writes `slice.md` / `plan.md` / `verification.json` under
`<spec-repo>/slices/NNN_<slug>/` — born planned, skipping `/dev:plan-slice` — validates the plan with
the run loop's `--dry-run`, adds the README **Pending** line, and stages by name. Relay its
errors verbatim; on success, fold the results into step 9: commit the staged spec-repo files, one
slice card `[NNN] Residual sweep` (triaged, as in step 9), and archive each swept card with a
comment naming the slice folder. Running the slice stays the operator's move (`/dev:run-slice`), like any other.
Rules and rationale: `${CLAUDE_PLUGIN_ROOT}/docs/residual-sweep.md`.

### 9. Close out

- **Slice cards:** one per slice, in its **triaged** state — title `[NNN] <slice title>`, this
  project's owner tag and no other, a short highlights summary, a pointer to the slice folder,
  and the subsumed card ids.
- **Intake queue:** archive the cards the slices subsume and the duplicates from step 6, each
  with a short comment (`close` and `later` were actioned at the seam). A **split** ruling makes
  one new card per split-off part, in the operator's words — their ruling as the body, the parent
  cited — and the parent is archived or trimmed as the ruling says. A **superseded** card closes
  with a comment naming what supersedes it; when the ruling rewrites the ask, the card is retitled
  and rewritten in the operator's words with its original text kept below a rule, so its history
  stays legible.
- **The working documents are deleted when nothing in them is still open** — every item filed,
  swept, closed, or parked. A partial disposition (a selection of the cards) leaves them in place,
  committed, each disposed item's `Ruling:` line saying where it went (`→ slice NNN`,
  `archived`). If deleting them would lose a fact, it isn't absorbed yet.
- **Notify the operator** per the host convention — "N items triaged: K closed at the filter,
  M slices under `<spec-repo>/slices/backlog/`. Run /dev:plan-slice on a slice when ready." —
  plus, when step 8 ran, "J cards swept into slice NNN — run /dev:run-slice on it when ready"
  (or how many qualifying cards are still accumulating) — and stop.

Stop means stop: planning is the operator's next move, in their own time. The one exception — the
operator explicitly asks to carry straight on into `/dev:plan-slice` *and* you agree the change is
genuinely minimal — still produces the `slice.md`, still runs the full planning process, and
never happens from a sub-agent. If you don't agree it's minimal, say so.
