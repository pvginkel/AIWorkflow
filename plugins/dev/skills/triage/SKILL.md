---
name: triage
description: File a batch of findings, bugs, or requests — read every ask as the operator wrote it, check it against the project's standing decisions, and put the batch to the operator in one chat message (the questions only they can answer first, each with its recommendation; then one line per proposed slice with the cards it files and the slices it must follow; then any other fate, only where an item has one); then record the survivors' asks verbatim as slice folders (slice.md under slices/backlog/NNN_slug/), the required input to /dev:plan-slice. Runs over the project's pre-filtered batch — or its whole intake queue, or a selection, when the operator names it — in one sitting. Comprehension, questions, and routing only; grounding, design, and planning happen in /dev:plan-slice.
argument-hint: "[findings-document] [card ids to scope the run]"
---

# Triage

Turn a batch of raw asks — tracker intake cards, a findings document, chat discussion — into
filed work: what should not be built closed by the operator *before* planning can spend on it,
the rest filed as change requests — one slice folder per subject under
`<spec-repo>/slices/backlog/NNN_slug/`, the required input to `/dev:plan-slice`. Argument
(optional): path to a findings document (e.g., `tmp/uat_testing.md`).

The run is one sitting: collect, sort, one message to the operator, their answers, file. The
operator reads nothing but that message — the questions only they can answer first, then the
slices and the other fates your recommendations lead to — and answers in chat, in their own
words. Those words are the record: they ride into `slice.md` verbatim, and nothing on the tracker
or under `slices/` moves until they are given.

**You are the intake clerk, not the analyst.** The job is to understand each ask *as the operator
wrote it*, put it to the operator so they can decide what progresses, and file what survives
where it belongs. Reading the code, judging feasibility, and designing the solution belong to
planning, `/dev:plan-slice`, which grounds each requirement and puts what is still open to the
operator. This session never opens application code: when a fate genuinely can't be proposed
from the text (step 4), a dispatched read-only sub-agent fetches the one fact it turns on — the
judgment still happens here. Two rules carry the design: **no item is ever closed by machine
judgment alone** — you recommend, the operator closes — and your product is a faithful record:
there is no planning without a `slice.md`.

**Preflight (step 0):** run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage`; relay
its message verbatim on a non-zero exit. `<spec-repo>` is the path in your
`.aiworkflowrc`'s `spec_repo`. The tracker — which cards are this project's, and how each state and
disposition named here is written — and the notification wiring come from your host convention
(`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, section 3). **Load that convention before the
first tracker call** — where the host ships it as a skill, invoke the skill: nothing in the
pipeline loads it for you, and a convention that is not in context gets guessed at.

**What the operator reads is written under `/dev:writing`**: the message, and every card text and
comment the run leaves on the tracker. Load it before you write the message. A sub-agent briefed
to write a card or a comment is told to read `${CLAUDE_PLUGIN_ROOT}/skills/writing/SKILL.md`
first.

Steps that don't apply are skipped silently: no questions → the message opens with the slices;
nothing to check → no research round.

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
operator's. Every card is read afresh — the tracker carries no verdict, and reading a card twice
costs little.

Before anything else, the raw material lands verbatim in
`<spec-repo>/handovers/triage_YYYY-MM-DD_raw.md` — full card contents, the chat passages being
triaged, a pointer to the findings document. When triage starts mid-session out of an interactive
discussion, this dump is the first act: the session is ephemeral, the file is not. The card fetch
is delegated — one read-only sub-agent per list or source, in parallel, each writing its part of
the dump, so no card passes through this session's context on its way to disk. Each brief says:

- whole and verbatim — id, title, marks, reporter, description, comments, in the source's order;
  the title is part of the ask, and dead routing hides in a title as readily as in a body;
- the tracker's fetch caveats from the host convention: a narrowed query silently drops the field
  that tells an operator's ask from a session-authored card;
- broken markup in a source (a literal `&gt;`, a stray entity) is reproduced as found: it renders
  wrong at the source too, and "fixing" it is a transcription error.

The dump lives in the spec repo, committed when written (staged by name,
`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`), and is the archive `slice.md` quotes from until step 8
deletes it. The operator never reads it.

### 2. Itemize, and check the standing decisions

**Itemize mechanically** from the dump, no research: one item per distinct ask. A card is
generally one item; a card that is itself a list of independent asks (a residuals card) becomes
several. When it is unclear whether something is one task or many, keep it as one — the planner
splits cheaply. Ids are assigned once and never change — the card's id as the tracker writes it,
suffixed `a`, `b`… when a card yields several items (`KC-472b`), the findings-document section, a
running number for chat passages — so an item that changes fate keeps its handle. For each item
hold its id, its ask — the title and the stated symptom and consequence, in the source's words —
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
is not decided, however settled its card reads.

A hit becomes one of the message's questions (step 5): the record's id and ruling quoted, and the
choice the operator answers from memory, overrule the record or close the card on it. The
collision travels: unresolved, it bars the item from filing (step 7); an overrule rides into the
slice as a ruling, with the record's id.

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
- **Later** — the ask stands but is not for now, on the source's word or the operator's → the
  deferred disposition.

Group the rest **by subject, on the asks as written**. Favor larger groups — a slice plans into
project-local, independently testable, PR-sized phases, and **about ten to twelve is the
target**, measured on cost: every slice pays its planning session, its consult and its test and
doc phases once, whatever its size. A two- or three-phase slice pays all of that on little work,
and the cost per line shipped keeps falling as a slice grows, as far as fourteen phases. Aim
there where the subject allows it. A group well short of ten looks for a neighbouring subject
before it is filed alone, and unrelated asks are never bundled to reach a number. Fourteen is the
ceiling, the largest size the cost has been measured at: a group that would clearly blow past
it is split with the operator now. Don't count API surfaces or applications touched: delivering a
feature end-to-end beats limiting development complexity. Bundling mistakes are fine; the
planner splits, merges, and kicks items back cheaply during planning. When in doubt, group
together.

**Then the order between the slices.** For each slice, name the slices that must be done before
it is planned: another slice of this batch, or a pending slice already filed — the spec repo's
`README.md` lists them under **Pending**. Judge it from the asks: one builds on what another
adds, or changes what another is about to change. Related is not enough, and most slices need
none. This is the slice's `needs:` (step 7).

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

The operator's answers raise checks of their own — "is this something you can check yourself?",
a ruling that holds only if some fact does — and each is a round of this step: the verdict goes
back to them with the line that moved, and the round repeats until nothing is open.

### 5. The message

Present the batch in one chat message, however long the queue — never a dialog, never a
document. The operator answers the questions; the rest of the message is what your
recommendations lead to, there for them to redirect. It runs in this order, and nothing is
printed empty:

1. **The questions, numbered.** Each is a decision, written as `/dev:writing` has an ask: what
   the card asks, the standing decision quoted with its id where the item collides with one, the
   question, the options where more than one is live, and your recommendation. They come first
   because they are the only part the operator answers.
2. **The slices, one line each.** The line is the slice's title; each card it files, with what
   the card is for in a few words; the slices it must follow (step 3), a slice of this batch by
   its title and one already filed by its number; and the questions its shape turns on. No phase
   estimate: the planner sets the size.
3. **Every other fate, only where an item has one** — a duplicate, a close, a later, an operator
   action, a workflow finding, a decision a question settles, a misfiled card — a line per item:
   its id, the ask, the fate and its reason. A close quotes the source's words or the research
   verdict; an operator action says why it is theirs.

Every item appears exactly once, on a line written as `/dev:writing` has a batch's line. A ruling
the card already carries is on its line ("— you ruled yes on 2026-09-25"). The message offers no
word that approves the lot, no answer forms to type, no alternative grouping, and no heading
beyond the three parts: a regrouping is the operator's to propose, and they say it in their own
words.

**A run born of a conversation that already decided** — every item's fate and every slice agreed
there, and no question open — puts no message. It files (steps 6 to 8), and says so in one line
naming what it filed; the agreed scheme is not put again to be agreed again.

The operator answers in chat, in their own words, and their reply settles the message:

- **An answer rules its question,** and their words are the ruling that rides into `slice.md`.
- **A word on an item moves that item** — out of the batch, into another slice, to a close — and
  what they leave untouched stands as the message showed it.
- **A question they leave unanswered stays open** for the planner. A proposed default is settled
  only by an explicit answer, so don't record your recommendation as their decision.
- **A question back is answered before anything is asked again,** in prose, as `/dev:writing`
  has it. A continuation is about that one question: the answer, then the question again if it is
  still open, then only the lines that moved. The rest of the message is not put again.

One pass per operator message: action the words, don't re-polish the scheme.

### 6. Action the rulings

When nothing is open, every item's fate is the operator's, given in the chat and carried into
`slice.md` from there — the tracker holds no fate beyond the dispositions themselves. Read each
ruling for what it does:

- **A close or a later is binding**: no re-derivation, no argument. A close closes the card as
  rejected, with a one-line comment carrying the ruling ("closed at triage: duplicate of
  KC-12"); a later takes the deferred disposition.
- **A ruling that limits a card to the literal change it names is a ceiling.** It is recorded
  verbatim and bounds the slice that carries it, the planner included.
- **A ruling that splits a card** makes the named part its own item, filed or fated as the ruling
  says, and its own card at the close-out (step 8); the remainder takes its own ruling.
- **A ruling that a card is superseded** — by work already done, a broader change, an answer that
  made it moot — closes it naming what supersedes it. One that rewrites the ask has the card
  retitled and rewritten in the operator's words (step 8).
- **A ruling that holds only if a fact does** is not yet a ruling: the fact goes to step 4, and
  the item comes back.

Delegated tracker work runs on **disjoint card sets** — each brief names the cards that are its
and the cards it must not touch — and is verified on the tracker itself, by spot check, never from
the agent's report.

A run that stops before filing files nothing. The dump stays committed as the archive, and the
next run reads every card afresh and asks again what is still open.

### 7. File

Allocate every group's number first, so that a slice's `needs:` can name another of the batch,
then create each folder:

```bash
N=$(${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>)   # flock-guarded; a burned number is a harmless gap
mkdir <spec-repo>/slices/backlog/${N}_<snake_case_slug>
```

Follow-up work to an existing slice also takes a fresh number from the same helper — letter-suffixed
slice ids (`087b`) are not supported; `close_slice.py` rejects them.

**`slice.md`** is the record. The planner works from it alone, in a fresh session that never saw
this conversation. It opens with a front matter block between two `---` lines: `issue: <id>`,
which step 8 writes, and, for a slice that must follow others, `needs:` with their numbers —
`needs: 028, 031`. A `needs:` is a slice that must be done before this one is planned, not merely
a related one: preflight's plan profile refuses to plan the slice until each slice it names has
completed (`${CLAUDE_PLUGIN_ROOT}/docs/preflight.md`). The body holds:

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
- The **Q&A and operator rulings** from the chat — a ceiling verbatim, since it bounds the planner
  too; an overrule of a standing decision with the record's id, so the plan moves the record as
  the project's decision discipline says — and the ids of the cards this slice subsumes.

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
preconditions over each new folder and moves nothing. Then commit the slice folders and the
README to the specs repo, staging files by name (`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`).

### 8. Close out

- **Slice cards:** one per slice, in this project, in its **triaged** state — title
  `[NNN] <slice title>`, a short highlights summary and the slice folder's name — `NNN_slug`,
  never a path: the folder moves from `slices/backlog/` to `slices/` to `slices/completed/` as
  the slice advances, and a path is stale after the first move. The card's id then goes into the
  slice's `slice.md` front matter as `issue: <id>`, and is committed (staged by name):
  `/dev:plan-slice` and `/dev:run-slice` move the card by that id, never by looking for its title.
- **The batch's cards:** close the cards the slices subsume as **absorbed**, each under its slice's
  card, and the duplicates from step 3 as rejected, each with a short comment (closes and laters
  were actioned in step 6). A split makes one new card per split-off part, in the operator's
  words — their ruling as the body, the parent cited — and the parent is closed or trimmed as the
  ruling says. A superseded card closes with a comment naming what supersedes it; when the ruling
  rewrites the ask, the card is retitled and rewritten in the operator's words with its original
  text kept below a rule, so its history stays legible.
- **The dump is deleted when nothing in it is still open** — every item filed, closed, or
  parked. A partial disposition (a selection of the cards, a run that stopped) leaves it in
  place, committed. If deleting it would lose a fact, it isn't absorbed yet.
- **Notify the operator** per the host convention — "N items triaged: K closed at the filter,
  M slices under `<spec-repo>/slices/backlog/`." — and stop.

Stop means stop: planning is the operator's next move, in their own time. The one exception — the
operator explicitly asks to carry straight on into `/dev:plan-slice` *and* you agree the change is
genuinely minimal — still produces the `slice.md`, still runs the full planning process, and
never happens from a sub-agent. If you don't agree it's minimal, say so.
