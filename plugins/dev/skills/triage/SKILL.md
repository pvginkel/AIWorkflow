---
name: triage
description: File a batch of findings, bugs, or requests — read every ask as the operator wrote it, check it against the project's standing decisions, and put the batch to the operator in one chat message (every item on a line under its proposed fate, the questions only they can answer, the proposed slices); then record the survivors' asks verbatim as slice folders (slice.md under slices/backlog/NNN_slug/), the required input to /dev:plan-slice. Runs over the project's pre-filtered batch — or its whole intake queue, or a selection, when the operator names it — in one sitting. Comprehension, questions, and routing only; grounding, design, and planning happen in /dev:plan-slice.
argument-hint: "[findings-document] [card ids to scope the run]"
---

# Triage

Turn a batch of raw asks — tracker intake cards, a findings document, chat discussion — into
filed work: what should not be built closed by the operator *before* planning can spend on it,
the rest filed as change requests — one slice folder per subject under
`<spec-repo>/slices/backlog/NNN_slug/`, the required input to `/dev:plan-slice`. Argument
(optional): path to a findings document (e.g., `tmp/uat_testing.md`).

The run is one sitting: collect, sort, one message to the operator, their answers, file. The
operator reads nothing but that message — every item on one line under the fate you propose for
it, the questions only they can answer, the slices you propose — and answers in chat, in their
own words. Those words are the record: they ride into `slice.md` verbatim, and nothing on the
tracker or under `slices/` moves until they are given.

**You are the intake clerk, not the analyst.** The job is to understand each ask *as the operator
wrote it*, put it to the operator so they can decide what progresses, and file what survives
where it belongs. Reading the code, judging feasibility, and designing the solution belong to
`/dev:plan-slice` — the refinement session that grounds each requirement and bottoms the ask out
with the operator. This session never opens application code: when a fate genuinely can't be
proposed from the text (step 4), a dispatched read-only sub-agent fetches the one fact it turns
on — the judgment still happens here. Two rules carry the design: **no item is ever closed by
machine judgment alone** — you recommend, the operator closes — and your product is a faithful
record: there is no planning without a `slice.md`.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage`; relay
its message verbatim on a non-zero exit. `<spec-repo>` is the path in your
`.aiworkflowrc`'s `spec_repo`. The tracker — which cards are this project's, and how each state and
disposition named here is written — and the notification wiring come from your host convention
(`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, section 3). **Load that convention before the
first tracker call** — where the host ships it as a skill, invoke the skill: nothing in the
pipeline loads it for you, and a convention that is not in context gets guessed at.

Steps that don't apply are skipped silently: no questions → the message is the scheme alone;
nothing to check → no research round; a card whose ruling an open dump under `handovers/`
already holds is not asked about twice.

## Procedure

### 1. Collect — everything on disk first

Gather the inputs: the findings document if one was passed, the relevant chat discussion, and
**this project's** cards: by default its **pre-filtered batch**, the cards the operator moved to
the pre-filtered state — by hand, or with `/dev:inbox`, which sorts every project's inbox at once
and moves what is slice-shaped there — with the dated inbox ruling a card carries shown on its
line like any ruling (step 5). The whole intake queue is the batch only when the operator says
so, and a selection they scope the run to (ids, a list) replaces either: the rest stay untouched,
and the close-out says so. Other projects' cards stay: a card filed under another project whose
substance is this project's is flagged by id — mine, misfiled? — never adopted; moving it is the
operator's. A `[NNN] close-out: …` card is not an ask but the marker that a slice's close-out
report is waiting (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`): render the report it names
(`python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_out.py render <slice_dir>`) and take as items what
the report brings the operator — the entries under **Comes to you** and **Card requests** whose
`Disposition:` line is blank, and every entry whose line says `defer` — one per entry, the entry
verbatim as the source. What the report closed, what waits for the wrap-up and the record are
not items, and the card itself is never itemized.

A card that an open dump under `handovers/` holds ruled — a sitting that stopped before filing
wrote its rulings there (step 6) — brings its ruling along: it is read from the dump, not asked
again. Every other card is read afresh, one pulled back from a deferral included — the tracker
carries no verdict, and reading a card twice costs little.

Before anything else, the raw material lands verbatim in
`<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md` — full card contents, the chat passages being
triaged, a pointer to the findings document. When triage starts mid-session out of an interactive
discussion, this dump is the first act: the session is ephemeral, the file is not. The card fetch
is delegated — one read-only sub-agent per list or source, in parallel, each writing its part of
the dump, so no card passes through this session's context on its way to disk. Each brief says:
whole and verbatim — id, title, marks, reporter, description, comments, in the source's order —
the title is part of the ask (dead routing hides in a title as readily as in a body); the
tracker's fetch caveats from the host convention (a narrowed query silently drops the field that
tells an operator's ask from a session-authored card); and that broken markup in a source (a
literal `&gt;`, a stray entity) is reproduced as found — it renders wrong at the source too, and
"fixing" it is a transcription error.

The dump lives in the spec repo, committed when written (staged by name), and is the archive
`slice.md` quotes from until step 9 deletes it. The operator never reads it.

### 2. Itemize, and check the standing decisions

**Itemize mechanically** from the dump, no research: one item per distinct ask. A card is
generally one item; a card that is itself a list of independent asks (a residuals card) becomes
several. When it is unclear whether something is one task or many, keep it as one — the planner
splits cheaply. Ids are assigned once and never change — the card's id as the tracker writes it,
suffixed `a`, `b`… when a card yields several items (`KC-472b`), the findings-document section, a
running number for chat passages — so an item that changes fate keeps its handle. For each item
hold its id, its ask — the title and the stated symptom and consequence, and a close-out
entry's proposal, in the source's words —
its question when one exists (below), and what the decisions check finds. None of this is
written anywhere but the message (step 5) and, for what survives, `slice.md` (step 7).

You judge from the ask; the dump stays the archive. A source's diagnosis, cause, or line
reference is an attributed claim ("the card claims…") — you can't verify it here and don't try.
A source's own severity claim stands as it is: a card stating a major issue *is* major until
the operator or a research verdict says otherwise, and your own instinct about how bad or how
likely something is is not an input.

**Check every ask against the standing decisions before proposing anything.** A project's
decision record lives in its spec repo, where it keeps one — an index of `DNNN` rows, a log, a
set of design docs; the spec repo's own `README` or `CLAUDE.md` says where, and a project without
one skips the check. One read-only sub-agent per batch reads it with every item's ask and
reports, per item, each current decision the ask's stated shape contradicts — the id and the
ruling quoted, nothing on whether the ask is a good idea. This is not the code reading the
clerk is barred from: the record is the operator's own rulings, and an ask that contradicts one
is not decided, however settled its card reads. A hit becomes one of the message's questions
(step 5) — the record's id and ruling quoted, and the choice the operator answers from memory:
overrule the record, or close the card on it. The collision travels: unresolved, it bars the
item from every route that takes a card as decided (steps 3 and 8); an overrule rides into the
slice as a ruling, with the record's id (step 7).

**Questions** are only ones **the operator can answer from memory**: "you want a Cancel button:
on which screen?" qualifies; where that screen lives in the code does not. A source may state
one itself ("the card asks whether…"); you need one when the item is vague *as a request*. A
question only the code can answer waits for the planner — unless the item's fate turns on it,
which is step 4.

### 3. Sort — a fate for every item

Give every item one fate. Outside the slices:

- **Duplicates** — within this batch, or of a card a plain tracker query surfaces → close as
  rejected, naming the card it duplicates. (Whether something is already *implemented* is a code
  question; the planner discovers that cheaply.)
- **Pure discussion**, nothing actionable → say so.
- **Decisions** — nothing is broken; the source asks the operator to rule. The answer closes the
  card, or rides as a ruling into the slice it bears on; nothing is filed for it alone. It is a
  question in the message, and the cheapest kind: a minute of thought, not a planning session.
- **Operator-owned work** — infrastructure or tooling outside the dev-agent slice workflow, an
  operator chore (*"full-sync these three environments"* — a task addressed to the operator, not
  an ask about the system), or an action only the operator can take → the **operator's action
  queue**, with a one-line comment saying what is theirs to do.
- **Findings against the workflow itself** — the driver, a skill, an agent definition, the
  plugin's docs — never become a slice: a run-slice session editing the driver edits the process
  executing it (the running loop holds the old code while the phase gate runs the new tests).
  They go to the operator's action queue too, marked as the host convention marks work for the
  orchestrating session, and are worked from there; a slice that reaches `/dev:plan-slice` for
  one is cancelled.
- **No longer applies, or doesn't reproduce** → close. **Guarded:** a proposed close rests on the
  source saying so (quote it), an operator ruling, or a research verdict naming what was
  checked — never on your belief about the system. Absent all three, check (step 4) or ask.
- **Solution Known** — a senior dev could deliver quality work from the card alone, and it
  passes the litmus in step 8 → write the acceptance criteria into the card, per step 8. These
  skip filing (step 7) and planning both: step 8 batches them straight into a run-ready slice.
  **Every surviving card is run through the litmus here**, and the message shows the verdict by
  where the card's line sits — under **Solution Known** when it qualifies; in its slice, with
  its one open point as a question, when it is a near miss; in its slice with nothing said when
  it goes the normal route. The verdict turns on the card's text alone: a card without an
  `## Acceptance criteria` section is not thereby disqualified — the criteria are what this
  step writes, and a card that is already fully specified qualifies without them. A surviving
  ask for a wording change with plain impact — screen text, a message, a name — is the
  archetypal candidate; a card that arrives already marked from an earlier session is re-checked
  here too. A **near miss** — a card that fails on one open point the operator can settle from
  memory: which of two names, whether the old flag stays, the exact message — is put to them
  with the point named: rule it and the card passes. The answer goes on the card as a ruling (a
  comment, and into the criteria) and the card takes the mark; unanswered, it goes the normal
  route. A point only the code can settle is not a near miss. An item with an unresolved
  collision (step 2) is on no decided route — not this one, not a slice — until the operator
  has ruled on the record.

Group the rest **by subject, on the asks as written**. Favor larger groups — a slice plans into
project-local, independently testable, PR-sized phases, and **about seven is the sweet spot**,
measured on overhead: every slice pays its planning session, its consult and its test and doc
phases once, whatever its size, so a two- or three-phase slice pays all of that on little work
and a slice near seven spreads it thin. Aim there where the subject allows it — a group well
short of seven looks for a neighbouring subject before it is filed alone; unrelated asks are
never bundled to reach a number. Ten is the ceiling: a group that would clearly blow past it is
split with the operator now. Don't count API surfaces or applications touched: delivering a
feature end-to-end beats limiting development complexity. Bundling mistakes are fine; the
planner splits, merges, and kicks items back cheaply during refinement. When in doubt, group
together.

### 4. Research — only what a fate turns on

For an item whose proposed fate turns on a fact the repo can show — whether *"\<claim\>"* still
reproduces on the named screen or path, whether the path the card calls impossible is reachable,
whether the work is already done — dispatch one **read-only sub-agent**, in parallel across
items, before the message. The brief is the item's one named question, quoting the source, and
nothing else: never "assess this item", never "how would we fix it". The sub-agent may read
across the repo and take the turns it needs; **"cannot determine" is an allowed verdict** and
leaves the source's claim standing — the item then goes to the operator as a question, since
they may know from memory what the repo cannot show, rather than being stranded.

The sub-agent reports the fact; the call stays here. Fold each verdict into the item's line
("close — checked: …") and record it on the card as a comment, dated and marked as triage
research: durable, visible to the next session, and source material a slice quotes attributed
like any other card claim (step 7). None of it becomes this session's own design: this research
settles fates and rulings, it is not planning groundwork.

The operator's answers raise checks of their own ("is this something you can check yourself?",
a `conditional:` ruling), and each is a round of this step: the verdict goes back to them with
the line that moved, and the round repeats until nothing is open.

### 5. The message

Present the batch in one chat message, however long the queue — never a dialog, never a
document:

```
Slice A: <title> (~N phases)
  <id>  <the ask, on one line>                                    (Q1)
  <id>  <the ask, on one line>
Slice B: <title> (~N phases)
  …
Solution Known: <id>  <the ask> — criteria written to the card; swept now / waits for the floor
Operator actions: <id>  <the ask> — <why it is theirs>
Close: <id>  <the ask> — <the reason: the source's words, or a research verdict>
Later: <id>  <the ask> — <why>

Q1 (<id>). <What the card asks.> <What it collides with, the ruling quoted.> <The question?>
I'd <recommendation>.
Q2 …
```

- **Every item appears exactly once**, on one line: its id and the ask in the card's words,
  shortened to a line — the title is part of the ask. No card text, no label, no note: the
  operator opens a card when they want it. A ruling the card already carries is on its line
  ("— you ruled yes on 2026-09-25").
- **The slices carry a phase estimate**, a guess from the cards alone — say so once in the
  message; the planner sets the number.
- **The questions are numbered**, each with the fact it turns on and your recommendation,
  answerable from memory. An item's line cites its question.
- **Nothing is asked twice.** An answer folded in, only what moved is re-presented — the lines
  that changed fate, the questions still open.

The operator answers in chat, in their own words. "Go" approves the scheme as it stands. These
forms have fixed behaviour when they use them: **close** and **later** are binding — the item
dies with a tracker disposition (rejected; deferred), no re-derivation, no argument; **agreed**
takes the card as written and any recommendation on it, to the normal route; **apply the
suggested edit** is a ceiling — the literal change the card names and nothing beyond it,
recorded verbatim, bounding the slice or sweep that carries it; **conditional: \<ruling\> if
\<fact\>** is not an approval — the fact goes to step 4 and the item comes back; **split: …**
makes the named part its own item (and its own card, step 9), the remainder taking its own
ruling; **superseded by …** closes the card naming what supersedes it — work already done, a
broader change, an answer that made the card moot — or, when the ruling *rewrites* the ask, has
it retitled and rewritten in the operator's words (step 9). A question the operator does not
answer stays open for the planner: a proposed default is settled only by an explicit answer, so
don't record your proposal as their decision. One pass per operator message: action the words,
don't re-polish the scheme.

### 6. Action the rulings

When nothing is open, every item's fate is the operator's, given in the chat and carried into
`slice.md` from there — the tracker holds no fate beyond the dispositions themselves. Action
`close` and `later`: `close` closes the card as rejected, with a one-line comment carrying the
ruling ("closed at triage: duplicate of KC-12"), and `later` takes the deferred disposition.

Delegated tracker work runs on **disjoint card sets** — each brief names the cards that are its
and the cards it must not touch — and is verified on the tracker itself, by spot check, never from
the agent's report.

A run that has to stop before filing appends the rulings given so far to the dump, under a
`## Rulings` heading — one line per item id, the operator's words, dated — commits it, and says
so in the notify line; the dump is the record between sittings, and the next run reads them
from it (step 1). The tracker carries none of it.

### 7. File

For each group, allocate a number and create the folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # flock-guarded; a burned number is a harmless gap
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

Follow-up work to an existing slice also takes a fresh number from the same helper — letter-suffixed
slice ids (`087b`) are not supported; `close_slice.py` rejects them.

**`slice.md`** is the record. The planner works from it alone, in a fresh session that never saw
this conversation. Step 9 puts the slice card's id above its title as frontmatter; the body
holds:

- A one-line summary of what is being requested and why, as the sources give it.
- **The numbered requirements list** — every input item, in the operator's words. Quote: a
  paraphrase can silently invert an ask; a quote cannot. Your own phrasing appears only where no
  operator wording exists, marked as yours. The planner seeds acceptance criteria from this list
  1:1, so an ask that isn't on it is lost.
- The relevant source material, quoted in (not just linked) — triage's dated research comments on
  the cards included, attributed as such. A source's diagnosis, cause, or line reference stays
  attributed — "the card claims…" — you have no way to verify it and don't try.
- **Operator-provided API/spec definitions, carried over as given** — signature-level fidelity:
  named operations, parameters and defaults, return shapes, enums. Don't restate a definition as
  high-level intent; the definition itself is the record. If the conversation evolved it, carry
  the final agreed version and let the Q&A show the evolution.
- The **Q&A and operator rulings** from the chat — a ceiling (`apply the suggested edit`)
  verbatim, it bounds the planner too; an overrule of a standing decision with the record's id,
  so the plan moves the record as the project's decision discipline says — and the ids of the
  cards this slice subsumes.

Requirements, not solutions: no fixes, no task shapes, no acceptance criteria, no feasibility
verdicts. **Attachments** that arrive with the work (a debugging write-up, a prior design or
proposal — including anything already in `handovers/`) move into the slice folder as input,
unvalidated; you author none of your own.

Add each slice to the **Pending** section of `<spec-repo>/README.md` — one line matching the
existing entries, `- **NNN** — <short title>: <one-clause summary>`, placed inside that section,
above the heading that ends it. The line names no card: a README outlives its cards as handles,
and `slice.md` holds the ids. The file's end is `## Completed`, whose bullets have the same
shape, and an entry landed there is one the close-out refuses. Verify before you commit:
`python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_slice.py --check <slice-dir>...` runs the close-out's
preconditions over each new folder and moves nothing. Then commit the slice folders to the specs
repo, staging files by name.

### 8. Sweep the Solution Known cards

**The litmus (and the risk filter):** the label means *a senior dev could take the card, as
written, and deliver quality work with no preparation*. That takes two things, both legible in
the card text: **what to change** is fully decided — no choice with consequences left to the
implementer — and **the impact** is plain — what the change touches and what breaks if it goes
wrong. Moderate size is fine; an open decision is not. Operationally: you can write the card's
acceptance criteria — outcome-level, one or a few — from its text alone; that the card does not
yet carry them is the normal state of a qualifying card, never a failure of the litmus. You
never open code here, so if the criteria would need grounding, the card goes the normal route.

Never label: concurrency or timing behaviour; storage-layout or wire-contract changes; a card
that leaves anything open ("investigate", "decide", "confirm"); an ask that collides with a
standing decision (step 2) until the operator's overrule is on the card; or
a fix that **adds behaviour** — a new code path, process, or piece of state — rather than
correcting what exists in place. Added behaviour carries design surface (failure policy,
bounds, collisions with documented rulings) that a card cannot prove is settled, however
completely it argues its diagnosis — a root-caused bug with an empirically verified fix
mechanism still leaves the *change* undecided. Mechanism-verified is not change-decided. When in doubt, the normal route:
an over-careful card merely costs a planning session; a mislabelled one ships unadjudicated
design.

When a card qualifies, append its criteria to the card description under an
`## Acceptance criteria` heading — that section is the only mark a qualifying card carries, and
it persists, so a later session sweeps cards this one only qualified. The mark persists; so does
the litmus's right to move: a card carrying the section from an earlier session is re-checked
against the litmus as it stands before it is swept — an earlier revision's mark vouches for
nothing — and one that fails loses the section, with a comment saying why, and is filed as its
own backlog slice now (step 7): its grounding is already written and would only rot, and the
survivors keep their marks. The Solution Known set is part of the message (step 5), like every
other fate. A criterion for a prose nit says the duplicate or false clause is gone — culled,
not reworded — so the writer does not negotiate with it.

The floor is **five or more** qualifying cards of this project. Fewer accumulate —
say so in the close-out: waiting cards cost nothing, and a sweep amortises the loop's fixed
consult, test and doc overhead across the batch, so forcing it at three pays full overhead for
three one-line fixes. `--force` is never the proposal. When the operator wants a short batch
moved, the move is **widening**: re-run the litmus over the project's other open intake cards —
cards routed the normal route in an earlier pass are fair game, and the litmus reads a card's
text alone; the usual qualifiers are renames, test-only fixes and other
in-place corrections — and report the verdict for every card, the failures included, so the
widened batch is auditable. Widening is owed to a batch the operator
wants moved, not to one that merely shrank by a withdrawal; still short after it, the cards
accumulate.

At the floor, assemble the payload — one item per card: a short
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
slice card `[NNN] Residual sweep` (triaged, its id into `slice.md`, as in step 9), and close each
swept card as absorbed into it, with a comment naming the slice folder. Running the slice stays the operator's move (`/dev:run-slice`), like any other.
Rules and rationale: `${CLAUDE_PLUGIN_ROOT}/docs/residual-sweep.md`.

### 9. Close out

- **Slice cards:** one per slice, in this project, in its **triaged** state — title
  `[NNN] <slice title>`, a short highlights summary and the slice folder's name — `NNN_slug`,
  never a path: the folder moves from `slices/backlog/` to `slices/` to `slices/completed/` as
  the slice advances, and a path is stale after the first move. The card's
  id then goes into the slice's `slice.md` as frontmatter above the title — `issue: <id>` between
  two `---` lines — and is committed (staged by name): `/dev:plan-slice` and `/dev:run-slice` move
  the card by that id, never by looking for its title.
- **The batch's cards:** close the cards the slices subsume as **absorbed**, each under its slice's
  card, and the duplicates from step 3 as rejected, each with a short comment (`close` and `later`
  were actioned in step 6). A **split** ruling makes one new card per split-off part, in the
  operator's words — their ruling as the body, the parent cited — and the parent is closed or
  trimmed as the ruling says. A **superseded** card closes
  with a comment naming what supersedes it; when the ruling rewrites the ask, the card is retitled
  and rewritten in the operator's words with its original text kept below a rule, so its history
  stays legible.
- **The dump is deleted when nothing in it is still open** — every item filed, swept, closed, or
  parked. A partial disposition (a selection of the cards, a run that stopped) leaves it in
  place, committed, with the rulings given so far under its `## Rulings` heading (step 6). If
  deleting it would lose a fact, it isn't absorbed yet.
- **Notify the operator** per the host convention — "N items triaged: K closed at the filter,
  M slices under `<spec-repo>/slices/backlog/`. Run /dev:plan-slice on a slice when ready." —
  plus, when step 8 ran, "J cards swept into slice NNN — run /dev:run-slice on it when ready"
  (or how many qualifying cards are still accumulating) — and stop.

Stop means stop: planning is the operator's next move, in their own time. The one exception — the
operator explicitly asks to carry straight on into `/dev:plan-slice` *and* you agree the change is
genuinely minimal — still produces the `slice.md`, still runs the full planning process, and
never happens from a sub-agent. If you don't agree it's minimal, say so.
