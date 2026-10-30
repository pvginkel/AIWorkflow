# The `dev` plugin re-envisioned for Pilot running it — the plan (P-111)

**Status:** the plan, written 2026-10-30 at the operator's ask, to be worked through in ad hoc
sessions on the branch `pilot-redesign` of this repo. Nothing on `main` changes until the cutover,
and the installed plugin stays at 0.9.x until then: the branch is published as **0.10.0** when the
rest of M1's prep is done, and the first slice through Pilot is its first run
(PilotAppSpecs `design/implementation-plan.md` steps 14 and 17). §1 holds the decisions the
operator rules before the first build session; §8 the items, in order.

**Inputs read:** P-111 and the eight AIWF cards it sweeps up; PilotAppSpecs
`design/aiworkflow-redesign.md` (the operator's eighteen points), `design/feed-model.md` §4 and
§7, `design/the-brain.md` §5 and §6.4, `design/aiworkflow-structured-data.md` (0.9.93, stale in
places); PilotApp `docs/round-trip.md`, `docs/mcp.md`, `docs/work.md`; PilotProjects
`rules/stages.md`, `rules/work-items.md`; this plugin at 0.9.147, surveyed subsystem by subsystem;
and the 91 changes from 0.9.57 to 0.9.147, read as a whole (§2). Added 2026-10-30, at the
operator's review of the first version: the reads of the operator's own reading and answering —
`close-out-read-2026-09-28.md`, `close-out-triage-plan-2026-09-29.md`, `triage-read-2026-09-29.md`,
`refinement-read-2026-09-03.md`, `plan-interview-2026-09-01.md` and its rubric, `interventions.md`,
`doc-phase-read-2026-09-04.md` — synthesised into `operator-reading-synthesis-2026-10-30.md`, the
evidence base of §5.7; the operator's remarks on the first version, recorded in §9; and the read
of their answers to `/dev:triage` since 0.9.60 (§5.4).

**Working the plan.** A session starts in `/work/PilotApp` (the project whose memory points here),
checks out `pilot-redesign` in `/work/AIWorkflow`, reads §1 and §9, and takes the first unticked
item of §8; a decision an item needs that §9 does not rule is built as recommended. Every commit
bumps the plugin's version and adds a changelog entry, as this repo's `CLAUDE.md` says, and the
item's box is ticked in the same commit; a ruling the operator gives is written into §9, dated,
naming its decision. The branch is pushed only on the operator's word. The surveys this plan was
written from are not kept: an item's session reads the code it changes.

## 0. In short

A stage of the workflow — planning, a run with its close-out — becomes **a Pilot work item**:
Pilot starts a headless session with a brief whose first line is the stage's command, the skill
does its work, writes its asks as **a block document**, registers it with Pilot, attaches what
backs it, and ends its turn; Pilot's pass pre-rules, the operator answers in the app, the answers
come back in the file, and the session is resumed with a message naming the file. Triage is not
a stage: in Pilot it is the definition chat's work, and `/dev:triage` stays the operator's own
chat skill (§5.4, ruled 2026-10-30). Nothing is put to a person in chat, nothing is edited by
hand in a rendered file, no card is a pointer a person follows, nobody checks on a loop every 55
minutes.

Three things make it one design rather than four reworks:

1. **Every ask a program acts on is data, and one module renders it.** `close_out.py` already is a
   store rendered to Markdown and read back; the refinement's decisions, the plan-writer's
   questions, the plan-reviewer's findings, the run loop's bail-outs and the triage's fates get
   the same treatment: the agent that judges writes structured entries, a new stdlib module
   `asks.py` renders them in the format skill's grammar (front matter, shared context, one ask
   per heading section, the block last) and reads `answer`/`by`/`note`/`to`/`done` back. An
   agent writes prose under `/dev:document-format` only where nothing programmatic consumes the
   answer (an arch design, a free report).
2. **The close-out is the run's continuation.** The driver renders the close-out document at the
   run's end, the run-slice session registers it, and the answers come back to the same session,
   which executes them. `/dev:close-out`, the close-out card and the Disposition lines go.
3. **Pilot owns waiting, routing and deferral; the workflow owns the ask's shape.** What waits on
   an operator act is an `action` block with a `check`; what belongs to a later slice is a block
   Pilot defers; what is another project's, Pilot routes. The workflow defers nothing
   (`aiworkflow-redesign.md`'s boundary) and keeps no marks, states or dumps of its own for it.

What is untouched: the plan as the queue, the phase round (writer → gate → review → merge →
stamp), the gate as it is computed today, the tail (sweep, consult, test phase, doc phase,
wrap-up), the roles and their verdicts, detach and resume, the label vocabulary and the route
table, worktrees for shared repos, uniform Opus at xhigh, the phase target, the cost tooling.

**Leading throughout: the research.** What an entry tracks, what a document shows and how its
prose is written is cut to what the reads of the operator's own answers show they use, and a
cut that went too far is put back when a read shows it — never on taste (the operator,
2026-10-30: "What's important is that the research shows. That needs to be leading always").
The reads are listed under *Inputs read*; §5.7 turns them into the writing skill.

**Parked for later, not in this rework:** PilotApp managing the loop's process itself — the
plan or run loop handed to PilotApp to run and supervise, instead of hosted under a session's
backgrounded wait (the operator, 2026-10-30).

## 1. Decisions for the operator

Each with the recommendation first. A decision not overruled before the item that needs it is
built as recommended; the rulings are recorded in this page's §9 and, where they bind Pilot's
record, as rows in PilotAppSpecs `decisions.md` at the cutover.

1. **The dividing line between coded and written documents** (§0 point 1). *Recommend:* an ask a
   program acts on is data rendered by `asks.py`; prose under the format skill only where no
   program reads the answer. The alternative — every stage's agent writes its document under the
   format skill and a parser reads the answers — keeps the prose in the agent's hands at the cost
   of a Markdown parser in every loop and a mapping from blocks to cards, rulings and entries that
   is guessed rather than known. This reads the operator's "rework the run system (so the
   requirements, or an evolution of this) to something close to the close-out system"
   (2026-10-30) as the planning stage's requirements document and the loops' questions; if
   another part was meant, this decision is where it changes.
2. **The close-out as the run's continuation** (§0 point 2; §5.3). *Recommend:* yes. The
   alternative is a close-out stage of its own that Pilot starts after the run, which costs a
   second work item and environment for what the run's session already holds.
3. **The close-out store's write model** (§2 bucket 1; §5.1). *Recommend:* an entry is open to
   its appender and to the wrap-up, the reviewers and the consult until the document is rendered
   at the run's end, and frozen after; the rendering happens once; the six take-back verbs, the
   Disposition read-back, the hash guard and `--overwrite` go. The alternative is porting the
   append-only, author-owned, commit-gated model that took eleven verbs in four weeks.
4. **The question verdict of code-writer and doc-writer gains optional `options` and
   `recommend`** (§5.2). A touch on roles FM §7 called untouched, additive: a question without
   options renders as a `question` block, one with them as a `decision`. *Recommend:* yes.
5. **The order of planning stays, and the preparation leaves the session** (§5.3). *Recommend:*
   the requirements asks first, the plan loop after, as today; each ask carries the approach in
   short, not a drafted plan. The alternative — a writer round before the asks so that each
   carries the draft — pays for a plan that the answers then rewrite. *Ruled 2026-10-30 with a
   change:* the session itself stays small. A sub-agent sets up the folder, absorbs the slice,
   grounds and writes the requirements entries and the grounding file; the session renders,
   registers and ends its turn; every later turn — a ruling to absorb, a question to answer —
   is worked by a sub-agent pointed at the folder, never from the session's own reading (the
   planner today ends over 250k, "forced to keep an eye on it").
6. **Arch-design stays the operator's own chat skill**, touched only by the blanket-accept scan;
   plan-slice puts "this slice needs an arch design first" as a decision block when it does.
   *Recommend:* yes (the operator runs designs of judgment themselves, 2026-10-25).
7. **`/dev:inbox` stays until v1.1's inbox sitting, `/dev:onboard` stays**, both trimmed of the
   blanket accept and the by-hand hints; neither is a stage Pilot runs. *Recommend:* yes.
8. **AIWF-82, stale `file:line` citations** — the operator said they would suggest the solution.
   *Proposed:* every artifact another session reads cites a path and a quoted line, never a line
   number; the writers' prompts and the format skill say so, and `close_out.py append` and the
   plan-reviewer flag a `:<digits>` citation. The alternative is to leave the card open past
   this rework.
9. **The AIWF sweep's fates** (§7). *Recommend:* AIWF-88 built as its design recommends,
   AIWF-84 answered by Pilot's deferral, AIWF-82 by decision 8, AIWF-113 already landed;
   AIWF-1, -35, -36 and -40 closed as not pursued, with a line each saying why (AIWF-36 was
   recommended built; the operator closed it, 2026-10-30).
10. **The rehearsal before the cutover** (§8 phase E). *Recommend:* the stages run end to end in
    ad hoc sessions with `--plugin-dir` on a throwaway slice, the fallback path showing the
    documents; then one rehearsal through pilot-dev with a free-form work item whose brief points
    at the branch's skill by path. The installed plugin is one for every environment (the shared
    home), so a branch cannot be installed for one environment; the plugin-version guard (0.9.49)
    is relaxed for a `--plugin-dir` run.
11. **The fallback without Pilot** — the operator's "if not, the documents are just shown/attached
    in chat" (2026-10-30). *Recommend:* when `mcp__pilot__register_document` is not among the
    session's tools, the skill prints the document's path and ends its turn; the operator edits
    the answer lines in the file by hand and says "continue"; nothing more is kept for it — no
    walkthrough, no agree-or-comment, no read-back of a prose line.
12. **The version:** 0.10.0 for the branch, every session bumping the patch as today.

## 2. Six weeks of changes, read as a whole

91 changes, 0.9.57 (2026-09-29) to 0.9.147 (2026-10-27). A third went into the close-out report
after its rebuild, a quarter into git, the pod and the process the loop runs in; none touched the
core loop. Buckets, each with the reading — converged and kept, a wrong tool the rework replaces,
or by-hand help Pilot makes moot:

| Bucket | n | Reading |
|---|---|---|
| `close_out.py`'s write model: take-back and correction verbs, the render read back, the staging of a JSON store in a shared tree (0.9.65, 84, 85, 91, 94, 99, 122, 124, 132, 142) | 10 | **Replace.** An event log rebuilt one verb at a time, under an append-only, author-owned rule that fits committed records and not uncommitted drafts; and two-way sync through a rendered file. → decision 3 |
| Routing and the operator's page (0.9.57, 63, 70, 73, 78, 105, 138, 144) | 8 | **Policy converged, mechanism moot.** The route table has not moved since 0.9.57; the ask's shape swung once (0.9.70 → 0.9.73) and settled at "the ask first, the evidence on the page", which `/dev:document-format` already carries. Keep the labels and the table; Pilot's documents replace the renderer |
| Wrap-up and consult scope: what must land before the test phase or the push, found by matching prose (0.9.58, 59, 90, 112, 126, 133, 140) | 7 | **Replace the text matches** (`owed_before_push`, `owed_before_test`) with a `due` field the author sets: before merge, test, push or close. Keep the wrap-up's bar and "no reviewer for its fixes" |
| Work meant for later: tracker marks (night shift, hand-back), `for` entries folded into a later `slice.md`, cards linked after triage (0.9.81, 82, 87, 89, 100, 128, 129, 131, 135) | 9 | **Replace with Pilot's deferral.** Three homes, each change a patch on a seam between them (a fold into a planned slice, a proposal naming a shipped one, a slice not yet created). `for` stays as the author's hint; the route is Pilot's `deferred`/`to` |
| Operator acts the run waits on: pre-run entries struck by hand, push holds, `push.enabled`, `owed_after`, promotion behind a ruling (0.9.66, 96, 97, 102, 118, 119, 123) | 7 | **One shape**: an `action` block with a `check` (AIWF-88's vocabulary), rendered where it arises — before the run, during it, after the deploy. `## Push holds` and `## Driver rulings` stay as the machine half |
| The phase gate: root, the manifest at gate time, touched components, the spec check, lint, the writer's own run reused (0.9.67, 115, 120, 125, 127, 134, 136, 137, 145) | 9 | **Converged, keep.** The scope is one function over the diff against a re-read merge base (`gate_projects`). The remaining churn rescues kc's output (0.9.120, 0.9.134): a kc gap, not the plugin's |
| Git: the spec tree branched in place, its lease, hook and `spec_commit.py`, then worktrees; bases that move (0.9.64, 79, 86, 88, 93, 103, 139) | 7 | **Replaced already** (0.9.93), now converged. Worktrees stay the shared repos' mode and nothing more: for a code repo they break `kc project setup`, and parallel work is the environment's to allow (the operator, 2026-10-30) |
| Environment readiness: eleven pre-checks inferring needs by scanning other repos' manifests (0.9.68, 74, 75, 77, 83, 106, 109, 111, 113, 117, 121) | 11 | **Kept as is.** The scans reverse-engineer the environment model, and a `needs:` declaration in KubeCoder would end them — but the way environments are managed is changing and `kc env reset` already ensures most of what the checks infer, so no KC card and no change to preflight; revisited later if at all (the operator, 2026-10-30). The stale-plugin check (0.9.75) is moot once Pilot launches the plugin |
| Loop hosting under a chat session: detach, 55-minute waits, locks across pods, resume after a kill, "you are a headless session" (0.9.69, 95, 101, 114, 143, 146) | 6 | **Moot**, with lessons kept: the exit recorded first, a stage's completion before its side effects, dead work set aside not reset, an interruption never an outcome |
| What a role is handed: review sets, the `Review:` ledger, diffs, secrets, skills, MCP servers (0.9.76, 80, 92, 98, 104, 108, 110) | 7 | Mixed. The hand-written `Review:` ledger was fixed three times: compute the review set from HEAD before and after in every repo the session committed to (optional, §8 C6). Redaction fails closed: keep |
| Planning and triage rules, two measured retargets (0.9.60, 62, 107, 130, 147) | 5 | **Converged**, prompt content that ports |
| Models and cost (0.9.61, 71, 72, 116, 141) | 5 | **Settled** |

**Reversals worth remembering:** five layers of spec-tree coping built and removed within days;
the effort step-down withdrawn the same day for the third time; the ask cut to three lines and
the evidence put back the next day; append-only entries worn away verb by verb; readiness checks
too strict, then loosened; operator documents nobody read (the triage status document, the
Summary, the Focus lines) removed. The pattern the operator suspected is real in four places —
the close-out's write model, the loop's hosting, the homes for later work, the operator acts a
run waits on — and the rework replaces those mechanisms rather than porting them. Stale after
0.9.145: `docs/rationale/principles.md` § Git and gates still states the test-only gate.

Two rulings on this read (2026-10-30). The operator has made or allowed changes to the prose
rules and the tracked fields that did not help them and were not all reverted, so the axe is
allowed there: the reads decide what stays (§0). And one reversal is settled the other way for
good — the evidence behind an ask stays available, below the ask on the page or attached, never
cut to the ask alone: the operator deep-dives a decision or a proposal now and then, and a fresh
session answering a question about one has nothing else to answer from.

## 3. The stage as a work item — the contract

This is what `plugins/dev/docs/pilot.md` states once written (§8 A0), the one home for the shape
every stage skill follows; `docs/AUTHORING.md` points at it.

**The brief.** Pilot's `add_item` for a stage carries a `brief` whose first line is the stage's
command — `/dev:plan-slice 031`, `/dev:run-slice 031` — so the skill
loads with what follows as its arguments (the-brain §5.4); then the brain's own text: the task in
a line, the project's ticket (`P-5`), and the grants text the switch selects; then the server's
`From Pilot:` lines — the plan task to write as `step`, the switch, the handbook verbatim
(PilotApp `docs/mcp.md`, PilotProjects `rules/work-items.md`). The skill reads the slice from its
arguments, `step` and the ticket from the brief, and the spec repo from the cwd's `.aiworkflowrc`
as today. A brief without a ticket files no parented card and says so in its document.

**The documents.** Every ask goes into a file under the slice's folder in the spec repo,
`slices/<NNN>/asks/<n>-<slug>.md`, numbered in the order written, except the close-out, which is
`close-out.md`. Each is rendered by `asks.py` from entries: the front matter (`title`,
`summary` on more than one ask, `step` from the brief, `for` only for a person's handle), the
shared context, one ask per heading section with its block last, ids unique in the document. The
session registers it with `register_document`, attaches what backs it with `attach_file` (the
material, the plan, the diffs, the record), and ends its turn with no tool call pending. A
registered file is never edited by the workflow again: the write-back is the one write it takes,
and a revised ask is a new document.

**The continuation.** The resumed session's first message is Pilot's, verbatim: "Your documents
were answered and written back in place: <path>, <path>. Read the answers and continue." The
skill reads the answers back through `asks.py` (`answer`, `by`, `at`, `note`, `to`, `done`,
`via`), acts on each — a ruling into `plan.md`, a card, a fold, a strike, a slice folder — and
goes on. Three readings are fixed: the operator's words travel **verbatim**, `answer` and `note`
quoted wherever the ruling is restated (`aiworkflow-redesign.md` point 3); an answer `by: agent`
is Pilot's choice on a delegated ruling and is **marked so** on anything it produces ("chosen by
Pilot: '<note>'; the operator did not decide this"); `answer: deferred` with `to` is **terminal**
for the workflow — the block's fate is Pilot's, the entry closes as deferred, nothing is kept to
bring it back (point 7, FM §7).

**The clarification turn.** A turn opening "Pilot asks about <path>:" is the pass's question to
the writer (F52.2, D059): the skill has a fresh sub-agent pointed at the slice folder answer
each, relays it under `## <local id>` in words, registers nothing, starts nothing, and ends its
turn — never answering from its own reading (§5.3).

**The nudge.** A turn that is neither the continuation's message nor a clarification — the nudge
after a halt or a pause (F135.3, F141.3) — resumes what the session was doing: a loop that exited
`halted` is resumed, a document still unanswered is left as it is and the turn ends.

**The halt file.** `/work/.quota-limit-halt-requested` present means stop at the next safe point
(§5.5); present at a loop's start means do not start.

**Cards.** Every card a stage files — a slice card, a card a close-out ruling asks for — is
parented to the project's ticket from the brief (F57.1), through the host convention
(`kubecoder:youtrack-usage`); the slice card's moves (triaged → planned → in progress → resolved)
stay the skills', Done the operator's. Resolved is new to the skills: today the operator moves
the card there after a review of their own; in Pilot the close-out's answers are that review, and
the run's continuation makes the move (ruled 2026-10-30).

**The fallback** (decision 11): no `mcp__pilot__register_document` among the tools → print the
path, end the turn; the continuation is the operator's "continue".

**What a skill never does:** present an ask in chat, offer a word that accepts everything, read a
ruling from prose, edit a rendered file by hand or ask anyone to, wait by polling, tell "the
operator" anything that is not in a document.

## 4. The shared module: `asks.py`

One store, one renderer and one read-back for every ask a stage puts to the operator or to
Pilot — the requirements, the plan loop's questions and findings, the triage's fates, the run's
bail-outs, and the close-out, which is the same store with its labels and route table on top
(the operator, 2026-10-30: requirements should work as `close-out.json` does, "in the end it's
just decisions and actions for the operator (or pilot)"). Stdlib, beside the other tools,
imported by `close_out.py`, `plan_loop.py` and `run_loop.py`, with a CLI for the skills and the
sub-agents. Three parts:

- **The store.** `asks/<n>-<slug>.json`, beside the document it renders to: `{title, summary?,
  step?, for?, context: [paragraphs], entries: [{id, kind, headline, body, options?: [{label,
  line?}], recommend?, proposal?, default?, check?, due?}]}`. `append` adds an entry and refuses
  one missing what its kind carries, as `close_out.py append` refuses today; `amend` and `note`
  change one before the render; `show` and `list` read. A body is Markdown — paragraphs, lists,
  run-in heads — passed through as written: the writing skill (§5.7) keeps it readable, not the
  tool.
- **Render.** `render` writes the document: the front matter, the context, then per entry
  `## <headline>`, the body, the block last, the kind's keys in the format skill's order, every
  value quoted where YAML would read it as something else (a colon-space, a leading `#`, `- `,
  `[`, a quote, a backtick), a multi-line value as a literal block. It refuses what Pilot would
  refuse (a duplicate id, `recommend` naming no option, `options` beside `proposal`, a heading
  inside an ask).
- **Read back.** `absorb` reads a written-back document into its store: the fences found by their
  info string, the answer lines (`answer`, `by`, `at`, `note`, `to`, `done`, `via`) read with a
  parser of the subset the record writes — `key: value` scalars, quoted or plain, a `|` literal
  block for a note — and nothing else of the body touched; each entry's ruling then stands in
  the store for the continuation to execute. The grammar whole is PilotApp `docs/block-dsl.md`;
  the format skill is the writer's view of it, and a test pins the module against the skill's
  own example.

`close-out.json` is an `asks.py` store whose entries also carry the labels and the grade;
`close_out.py` is the layer on top — the route table, the wrap-up's verbs, the record — and
takes the entries' shape, the render and the read-back from the module (§5.1).

Not used: the backend's `pilot-dsl` package (the operator, 2026-10-30: no use for the shared
library here; stdlib-only stands).

## 5. The stages, as they will be

### 5.1 The close-out store and document

`close-out.json` stays one store per slice, written by every role through `close_out.py` as the
run goes, with the labels and the route table of 0.9.57 (§2). What changes:

- **Fields.** A `decision` entry carries `options` and `recommend` (today prose in the body); an
  `action` may carry `check` (AIWF-88's vocabulary) and `due` (before merge, test, push, close),
  which replaces the prose matches `owed_before_push`/`owed_before_test`; an `improvement` whose
  headline ends in a question mark is appended as a `decision` (point 8). The `for` label keeps
  its name in the store and never renders as front matter.
- **The write model** (decision 3): `append`, `amend`, `note`, `strike`, `relabel`, `propose`,
  `fold`, `settle` for anyone who has the pen, until the render; the six take-backs, `unrule`,
  `request-word`, `request-card` (→ `propose --card`), `leave` (→ a mark), `held`, `import`,
  `rule --words/--append/--replace`, `close --words`, the Disposition read-back, `rendered`,
  `ReportEdited`, `--overwrite` and the `report_edited` bail go. The report is rendered once, at
  the run's end, after the wrap-up; no render on every write (0.9.85 reversed).
- **The document.** `close_out.py render` writes `close-out.md` through `asks.py`: `title`
  "Close-out of slice NNN — \<title>", `summary`, `step`; the context — the slice in two lines,
  what shipped, what the wrap-up fixed in a line, the record attached; then one section per entry
  the table routes to the operator or to a card request, or the wrap-up marked `card`/`word`:
  `A` → `action` (`check`, `due`, options where the entry gives what to report back); `D` →
  `decision` with `options`/`recommend`; every other kind → `decision` with the entry's
  `proposal` ("card it in KC", "fold into slice 031", "fix now", "close"); the body, the
  consequence, the evidence class and the provenance as prose above the block. `Route:`,
  `Latest`, the grade suffix and the section headings of the old page go. Everything else —
  closed, record, the wrap-up's fixes — is `close-out-record.md`, attached.
- **Read-back.** `close_out.py absorb` reads the written-back document: `answer`+`note` →
  `ruling.words` (with `by`, `at`); an action's `done`+`note` → the ruling and its `did`;
  `deferred`/`to` → the entry closed as Pilot's. Then the session executes — a card parented to
  the ticket, a fold, a fix now where the project's `CLAUDE.md` allows ad hoc fixes, a settle —
  and records `--did`; `close` strikes what is left; the final render writes the record under the
  answered asks; the session commits by name.
- **The wrap-up** keeps its bar and its fixes; its asks become proposals on the entries. It runs
  before the render whatever the run's exit, so no entry ever waits for a wrap-up nobody
  dispatched; an entry it did not reach comes to the operator said as what it is. And it checks
  **every proposal's vehicle**, as the close-out session does today: a vehicle exists when the
  document is read, which is after the run — never a phase of this run ("append to phase 4"
  reaches nobody, since nothing reads the report before the run is over; the operator,
  2026-10-30), never a slice already planned or running, never a slice that has shipped since.
  A proposal with no vehicle gets `fix now`, `card` or a slice still to run, with the reason.

**The close-out skill's rules, by home.** The skill goes as a chat entry point (there is no
chat); its rules do not all go with it (the operator, 2026-10-30: "there's stuff in there I'm not
convinced we should lose"). Each rule of `skills/close-out/SKILL.md` lands in one of four
places, and A2 and B1 move them:

- *To the run's end, in the driver:* the wrap-up before the render at every exit; the scratch
  clones the driver left for a `github:` Target removed when clean and level, said in the record.
- *To the wrap-up agent:* the ageing check — a claim a command or two settles is checked, an
  entry fixed since is presented as that with the commit, never whether the entry was right; a
  proposal for an entry whose author gave none; the vehicle check above.
- *To the continuation* (`docs/close-out.md`'s procedure, which run-slice follows): the operator's
  words verbatim, never paraphrased or completed; a word of assent is a ruling for the proposal;
  the executions — `card` (one per entry, the title the headline without its grade, the body the
  entry as `show` prints it; actions the operator cards go on one card in their action queue),
  `fix now` only where the project's `CLAUDE.md` classes the change as ad hoc work, `fold into`
  (the entry verbatim as an ask in that `slice.md`, refused for a slice planned or running),
  `close`, and `settle` for an owed-after action into `verification.json`; what cannot be
  executed as ruled — a `fix now` no rule allows, a fold into a running slice — is a new
  document with the alternatives as a `decision`, never a quiet substitution; neither
  `close-out.json` nor `verification.json` is edited by hand; the record rendered and committed
  by name.
- *To the clarification turn:* a question about an entry's claim is answered from its body and
  `Provenance:`, quoting what supports or fails the reading — never re-derived, and agreeing is
  not an answer.
- *Gone:* locating the card; the Disposition read-back and `--overwrite`; present-and-wait; the
  blanket ruling (every block is answered); `unrule`, `--append`, `--replace`; the offer to
  close; `defer` (Pilot's `deferred`/`to`); the close-out card and its closure.

What Pilot's brain needs of the workflow is none of these rules but what each stage's fates
mean when it pre-rules a document — card, fold, fix now, close; a slice, Solution Known, later —
and that is F2's `rules/stages.md`, written for the pass (§8).

### 5.2 The run

The run-slice skill becomes the stage's turns (§3), the driver untouched but for what it renders
and when it stops:

- **Start.** Parse the brief; preflight; an environment fact that stops the start — a tool
  container, a service, a Target not cloned, a dirty tree — is an `action` document with the
  exact fix and a `check` naming the fact, registered, the turn ended; Pilot's pass claims what
  the grants allow (a restart is a fleet call), the operator does the rest, and the continuation
  runs in the mended environment. Open pre-run actions are an `action` document the same way.
  Then `run_loop.py run <slice> --detach --step <tN>` and one backgrounded `wait` that re-invokes
  the session when the run ends or stops. The 55-minute check goes whole (the operator,
  2026-10-30: it never found an error): `wait` keeps the loop's own cap, a return of 5 is
  re-armed with no word said and no log read, 6 relaunches, 0 goes on to the exit; while the
  run runs, the session reports to nobody.
- **Exit 4.** The driver renders every operator question as a document in `asks/` before it
  exits — the role's question with its options where the verdict gives them (decision 4),
  `generation_exhausted` and `plan_doc` as decisions with the driver's proposal — and the session
  registers it, attaches the plan and the phase's review where they bear, and ends its turn. The
  continuation writes the ruling into `plan.md`'s rulings section verbatim, with the `## Driver
  rulings`/`## Push holds` bullet where the answer calls for one, commits, and runs `--resume
  --detach`.
- **Exit 3.** What is mechanical or environmental the session fixes and resumes, as today; what
  is not becomes a `decision` document — the diagnosis, the options (retry, stop here, change the
  plan) — and the turn ends.
- **Exit `halted`** (§5.5): the turn ends with its last line saying where; the nudge resumes.
- **Exit 0.** `slice_cost.py --write-state`, `close_slice.py`, the commit, as today; then the
  close-out document (§5.1) registered with the record attached, and the turn ended. The
  continuation absorbs and executes (§5.1), moves the slice card to resolved, and ends. The
  close-out card (0.9.51) and `/dev:close-out` go.
- **Roles** are dispatched as today: strict MCP config, the promoted servers; Pilot's server is
  not promoted to them, since the session registers on their behalf (FM §7). The `plugin_version`
  guard is relaxed for a `--plugin-dir` run (decision 10).

### 5.3 Planning

The plan-slice skill becomes the stage's turns, and the session a small coordinator that never
reads the slice itself (decision 5 as ruled 2026-10-30: the planner today ends over 250k, and the
operator watches its context for it). The refinement-writer and `docs/refinement.md` go (point 1).

**Start.** Parse the brief; preflight `--for plan`, an environment fact an `action` document as
in §5.2. Then one sub-agent, the **plan-preparer** (`agents/plan-preparer.md`, in the
refinement-writer's place, Opus at xhigh), does what the session did:

- sets up the plan folder and absorbs `slice.md`, the card and the cards linked after triage;
- grounds every claim with read-only sub-agents of its own, and checks a checkable premise
  before it is asked (point 13);
- writes `grounding.md` into the folder — what it read, what it checked and what it found, the
  settled items in a sentence each, the approach in short — so that any later agent pointed at
  the folder knows what it knows;
- appends the asks to `asks/1-requirements.json` through `asks.py`, under the writing skill: a
  decision the operator could plausibly rule the other way as a `decision` with options, the
  recommendation, what it optimises for and the card it serves named in the prose (the card-id
  ban lifted, FM §7); an open fact as a `question`; a new repository to create as a `decision`
  with a proposal; "this slice needs an arch design first" as a decision when it does
  (decision 6). The settled items and the approach in short are the shared context; the rest of
  the grounding stays in `grounding.md`;
- hands back one line.

The session renders `asks/1-requirements.md`, registers it, attaches `grounding.md` and
`slice.md`, commits, and ends its turn. A slice with nothing to ask skips the document and goes
straight to the loop.

**The continuation.** A sub-agent pointed at the folder absorbs the rulings into `plan.md`'s
rulings section verbatim (`by: agent` marked) and seeds the header; the session commits and
launches `plan_loop.py` with a backgrounded wait, as the run does (§5.2). The loop's writer and
reviewer are its own sub-agents, as today.

**The plan loop's exits.** The plan-writer writes its questions as `plan_questions_rN.json` and
the plan-reviewer its findings as `plan_review_rN.json` (the prose review kept beside it,
attached); the loop renders each exit-4 as a document in `asks/` — a question per block, a
blocking finding per `decision` with the reviewer's disposition recommended — and exits; the
session registers, attaches the draft plan, ends its turn. The continuation's sub-agent writes
the answers into `plan.md`, the session reruns the loop; the fix pass runs by default, there
being no operator sanity-read. This loops as often as the loop asks; most of these Pilot's pass
rules itself (`by: agent`).

**Questions about the slice.** A clarification turn ("Pilot asks about <path>:") or a nudge that
turns on a fact of the slice is answered by a fresh sub-agent pointed at the folder —
`grounding.md`, the asks, `slice.md`, the plan — never from the session's own reading (the
operator, 2026-10-30: "for questions we should never attempt to use the running session, but
instead use dedicated sessions"; the risk otherwise is a session that "figures it out itself,
blowing up its context"). The session relays the answer under `## <local id>` and ends its turn.
The folder carries enough for this; that is what `grounding.md` is for. The operator's own
practice, a new session pointed at the folder with the question, is the same move by hand and
stays theirs. An answer in the operator's chat whose referent is not in it ("yes, that's what I
want") is Pilot's to write into the document with its context, since it writes the answer line.
*Ruled 2026-10-30:* the simple option — Pilot's clarification turn to the writer's session
(D059) stays the mechanism, the sub-agent inside it, no change to Pilot. Every resume lands on a
session over an hour old, its cache cold; whether that costs real budget is reviewed once a few
slices have run through Pilot (P-128), the dedicated session per question the alternative then.

**Exit 0.** The dry run, the promotion to `slices/`, the commit, the card to planned, as today;
the turn ends with one line.

### 5.4 Triage

Rewritten 2026-10-30 from the read of the operator's answers since 0.9.60
(`triage-answers-read-2026-10-30.md`, 41 runs), at their ask: "take the axe to it".

**What the read says.** The scheme is never the ask. In 63 turns the operator proposed a
different bundling once, never named a slice by its letter, never commented on a phase estimate,
never disputed a Close or a Later; the three times the message offered "say merge A+B" or
"split", nobody said it. Their input is the numbered questions: 40 % of turns answer them, 33 %
agree to everything, and 26 of 29 typed turns are "Qn: …" lists. Of 121 questions, the
recommendation was taken 67 % of the time and overruled 21 % — the design content is where they
disagree. The fixed answer forms ("split:", "superseded by", "conditional:") were never used;
"Go" five times, always with no question open. What the message lacked they asked for after
filing: the order between slices, in 5 of 8 multi-slice runs ("Can you build me a DAG for
this?"), and once what a card was for (KC-165, disagreed with after filing because its one line
had not said). Empty fates were printed anyway ("Close: — / Later: —"); the headings were made
up per run. The median message was 392 words for 3 items and 3 questions; 22 of 41 runs restated
what the conversation had just agreed, and all four zero-question messages got "Go".

**The output, redesigned.** Whatever runs triage puts to the operator, under the writing skill:

- *the questions first*, numbered, each a `decision` with its recommendation and, where it is a
  collision, the standing decision quoted — the only part they answer;
- *then the scheme as the consequence*, one line per slice: the title, its cards each with what
  it is for in a few words (the KC-165 line), and its place among the others (`needs:`), which is
  what survives of the DAG; the estimate goes;
- *then the other fates only where an item has one*, a line each; nothing printed empty;
- no "go", no fixed answer forms, no invented headings, no agreed scheme restated to be agreed
  again: a run born of a conversation that already decided files, and says so in a line.

A multi-round run is a design discussion on one question, never on the scheme: a continuation
re-asks that question alone. The template in the skill and the handover dump's `## Rulings` go;
the raw dump stays as the attached archive.

**Where triage runs** — the operator's question of 2026-10-30 ("Triage I feel is mostly part of
the project definition, right?"), with the design read of the same day. Pilot's design never
places triage: a Pilot project is any body of work agreed in the definition chat, which produces
`project.md`, and `/dev:triage` as a stage Pilot drives appears only in the v1.1 inbox proposal
(`the-inbox-sitting-as-a-pilot-project.md`); `rules/stages.md` today says no stage is runnable
from Pilot, and v1 has no stated path from the intake queue to a project. What triage does for
one slice — read the cards, check them against the standing decisions, put the real questions
with a recommendation — is the definition chat's work in the design's own words ("what the
project is for, what result establishes it, its material constraints"). The one part the chat
does not do is the bundling of a batch into several slices, which the read shows the operator
never disputes and mostly does themselves by naming the cards (22 of 41 runs). *Ruled 2026-10-30:*
in Pilot, triage is the definition chat's, not a stage — the brain's definition skill carries
the standing-decisions check and the questions-first shape, and `slice.md` is written from
`project.md` by the setup or read by the plan-preparer in its place (F2, F3); `/dev:triage`
stays the operator's own chat skill (as `/dev:arch-design`, decision 6) for a batch sweep and
for projects outside Pilot, with the output above and trimmed of the blanket accept. The
alternative — the stage as this section first had it, each slice folder becoming a project
through `start_project` — was not taken.

**Sweep slices**, the other question: PilotAppSpecs has never had a `sweep_slice.py` slice; the
M1 "sweep slice" (plan row 030) is an ordinary triage over its named cards, "filed by a triage
and run on today's workflow". The Solution Known lane was used in 3 of the 41 runs, and in one
of those the operator moved the six marked cards to a manual sweep of their own. *Ruled
2026-10-30:* dropped, as unused — the lane, `sweep_slice.py` and `residual-sweep.md` go (§6, B3);
a mechanical card is the card pass's, or an ordinary slice's.

**The continuation**, where triage is a stage or a chat skill alike: the slice folders written
(`slice.md` quoting the answers' words as the operator's, its front matter carrying `issue:` and
`needs:`), the subsumed cards closed, `later` and `close` actioned, the slice cards filed and
parented, the README's Pending lines, the commit. A question the answer reopens re-enters
research and may put a second document.

### 5.5 The halt file, in both loops

`_halt_requested()` at the choke points: each iteration of the phase loop, the top of every
dispatch and consult, the devlock wait's poll, the session-limit sleep (which becomes a poll that
also watches the file), before each push. A running role's turn, a running gate and a push in
flight finish; then the loop records its stage, releases the devlock and exits with a new code,
`halted`, distinct from `wait`'s 5 and 6, `state.json` current and `--resume` continuing from
there. `plan_loop.py` gets the same check and a `stop` command. A file present at start refuses
the start. The driver's own sleep until the session limit resets stays as the fallback for a wall
Pilot's halt did not prevent, halt-aware.

### 5.6 Preflight and onboard

Preflight keeps every check as a program's fact and loses the person's text: a failure is
structured — the check, the fact, the fix — for the session to render into an `action` document;
the stale-plugin line goes. The checks themselves, the environment ones included, stay as they
are (§2). `/dev:onboard` stays an operator-driven skill with its by-hand steps
trimmed, its "pre-ruled headless" shape the template for a later Pilot-driven onboard.
`/dev:inbox` stays until v1.1 (decision 7), its "go approves the scheme" gone.

### 5.7 The writing skill

**What it is.** One skill, `dev:writing`, on how to write what the operator reads: a close-out
entry, a requirements ask, a triage line, a plan question, a proposal. Every role that writes
one loads it — the code-writer and the reviewer for their entries, the wrap-up, the plan-slice
preparation sub-agent, the plan-writer and plan-reviewer, the test agent, the triage's
sub-agents — and `/dev:document-format` points at it for the prose inside its grammar, as
`close-out.md`'s entry rules do. Its every rule cites a finding of
`operator-reading-synthesis-2026-10-30.md`; a rule with no finding behind it is not in it (§0,
the research leading). The operator's ask (2026-10-30): "All the findings need to lead to a
writer skill that helps write better close-out/requirement etc records."

**What the findings say it must carry**, each with its finding (synthesis §.n):

- *Write for the reader's path.* The operator reads the summary, then the headline and the
  proposal, judged for safety, then half the context on a doubt, the rest one time in twenty
  (1.1, 1.2). So the `summary` and each ask's headline and proposal are rulable alone, the context
  after them, the evidence after that — present, never cut (§2's ruling), never first.
- *Shape over density.* A paragraph carries one point; three or more of anything is a list; a
  number, a command, a quoted line stands on its own line; run-in heads inside an ask. No
  200-word paragraph (4.1, 4.2): "3 paragraphs and 2 bullet lists". Length is what the body
  needs — a cap produces more, not less (4.5) — but the body is structured, not dense.
- *Ask only what they could rule the other way.* Eight of twelve refinement decisions were
  implementation picks whose own alternatives said "loses" (4.11); the ones engaged with changed
  what a user sees or what the operator runs (5.3). An implementation pick is the writer's, said
  in a sentence of the context, not asked.
- *Every ask carries its recommendation; alternatives only when live.* 77 % took the
  recommendation, padded alternatives were rejected 0 of 13 (2.3, 6.2). The delegation phrases
  — "pick the simple option", "I want to follow your recommendations" (2.5) — are a reader
  asking for the recommendation to be there.
- *Self-contained for a cold reader.* Half the plan questions were not readable cold, and
  confused or delegated answers rose with every handle leaned on (1.11, 4.8). No bare id: a
  decision, a requirement, a card is named with what it says; a citation is a path and a quoted
  line (decision 8); nothing assumes the slice is fresh in the reader's mind.
- *A premise is a claim, checked, with its class.* Fifteen questions rested on a false premise
  written as background (4.9). A premise a command settles is checked before it is asked; one
  that is not is stated as what it is — read or witnessed — not folded into an option.
- *Price it.* What the operator asks back is what the entry says, whether it can happen and how
  bad, and what the fix costs (3.1, 3.2); advice that traced reach and priced the fix was followed
  35 of 41 times (5.6). An ask about a problem says whether it is reachable, what a user would
  meet, and what the fix takes, in a line each.
- *Severity first and visible.* "an agent trying to get my eyes on something that I then don't
  see" (4.12, 4.13; 2.8: "High severity needs to come to me, even if it's very unlikely"). What
  the author thinks the operator must not miss is the first line, said as such.
- *Reports are asks.* "just a dump of thoughts and ideas. They aren't questions" (4.4). An entry
  that reports and proposes nothing is not written; its author takes a position.
- *A card request is one line and a card.* Never read today (1.3); nobody has measured whether a
  card can be ruled from its text (4.15). The ask is a line — what the card would say, why it is
  more than a fix — and the body is the card's text, written for the card.
- *Settled items in a sentence each, or not at all.* "I should not have to see the details. The
  planner agent will have this already" (4.10; 6.3).
- *One line per item for a batch.* The one-line-per-item chat message was the triage format
  that worked, ruled by numbered reply (5.7); in a document, the headline is that line.
- *No restating.* A proposal that restates the headline, or a consequence that restates the
  mechanism, sends the reader into the body for what the line should have said (`close-out.md`
  entry rules; 4.4).

**What it replaces.** `close-out.md`'s "Entry rules", the prose guidance in the role prompts
(`code-writer.md`, `code-reviewer.md`, `wrap-up.md`, `plan-writer.md`), and whatever of
`refinement.md`'s writing rules survives its deletion; each keeps a pointer and loses its copy.

**How it is checked.** Nothing mechanical: E1's read of the rehearsal's documents against the
findings, and the next read of the operator's answers once Pilot has run a few slices (the
reads' method, `triage-read-2026-09-29.md` § Corpus and method).

## 6. What goes

- **Skills:** `close-out` (folded into run-slice), `slice-dag`; in `triage`, the Solution Known
  lane, the template, the fixed answer forms and "go".
- **Agents:** `refinement-writer` (the `plan-preparer` in its place).
- **Tools:** `sweep_slice.py` and its tests.
- **Docs:** `plugins/dev/docs/refinement.md`, `residual-sweep.md`; `close-out.md` and
  `close-out-template.md` rewritten; the DAG sentence in `spec-tree.md`;
  `docs/rationale/plan-refinement.md` and `reporting.md` rewritten or moved to `history.md`.
- **In `close_out.py`:** the verbs of §5.1; the rendering of the old page; `held`.
- **In `run_loop.py`:** the `report_edited` bail; `wait`'s prose for a person; the stale-plugin
  relaunch; the close-out card, the chat summary and the 55-minute status update in the skill.
- **In `plan_loop.py`:** nothing of the loop; the free-Markdown questions file as the surface.
- **In `preflight.py`:** the stale-plugin check; the person-directed fix text.
- **Everywhere:** every wording that offers or invites a one-word accept-all (point 11): the
  known sources in `skills/inbox/SKILL.md` and `skills/triage/SKILL.md`, and a full scan of
  skills, agents, contract docs and every string a tool prints.

## 7. The AIWF cards swept in

| Card | Fate | How |
|---|---|---|
| AIWF-113 phase target | landed as 0.9.147 | closes with P-111 |
| AIWF-88 pre-run checks as facts | built | `append --check` with the design's vocabulary (`env`, `file`, `origin … contains`, `slice … completed`, `manual`), a hash or an environment id refused; the driver evaluates at start and on resume, an unmet check the `action` document of §5.2; the design's D1–D5 as recommended unless overruled |
| AIWF-84 a card against code a backlog slice still writes | answered by the design | the entry's `for` renders as a proposal to hold for that slice; Pilot defers it to the task (`deferred`, `to`); no card, no `held` state |
| AIWF-82 stale `file:line` citations | decision 8 | the citation rule in the writers' prompts and the format skill; `append` and the plan-reviewer flag `:<digits>` |
| AIWF-36 risk level in the reviewer's dispatch | closed, not pursued | the operator's ruling, 2026-10-30, on the recommendation to build it; closed on the tracker the same day |
| AIWF-35 risk-based review (the skip) | closed, not pursued | the 2026-08-27 research: documentation is not low risk in this pipeline; AIWF-36 is the part that lowers exposure |
| AIWF-40 a project hook for a mid-run publish | closed, not pursued | 0.9.102's in-phase push ruling at seeding covers the case seen; the operator expected it to come up less |
| AIWF-1 `code_health` grading Go | closed, not pursued | the quality tool's rebuild is no part of this rework; `archive/quality/` stays the frozen record |

## 8. The items, in order

Each item is one ad hoc session or two, on the branch, committed as it goes with the version
bumped and a changelog entry; `kc project test` and `lint` green at every commit. About twelve
sessions in all.

**Phase A — the contract and the foundation**

- [x] **A0. The contract page.** `plugins/dev/docs/pilot.md` as §3 states it, and `docs/AUTHORING.md`'s
  rules for a stage skill (headless, ends its turn, the brief, the documents, the continuation,
  the clarification turn, the fallback). *Done when:* the page reads as the one home and the
  operator has read it — this is P-111's "Designed" box, with this plan.
- [x] **A1. `asks.py`** (§4): the store, its CLI, the render and the read-back, with its suite,
  pinned against the format skill's example and the quoting rules. *Done when:* a store of every
  kind renders to a document that round-trips through the read-back with Pilot's answer lines
  added.
- [x] **A2. `close_out.py`** (§5.1) on `asks.py`: the fields, the write model, `render` as the
  document plus the record, `absorb`, the verbs removed, the dispatch line, the vehicle rule, the
  rules of the close-out skill moved to their homes in `close-out.md`, `close-out-template.md`
  and `wrap-up.md`; the suite reworked (the render and read-back half of `test_close_out.py`).
  *Done when:* a store of the old fixtures renders as a document that `register_document` would
  take, and an answered copy absorbs into rulings. The largest item.
- [x] **A3. The halt file** (§5.5) in both loops, `plan_loop.py stop`, the exit `halted`, tests.
- [x] **A4. The run loop's asks** (§5.2): every exit-4 rendered as a document before the exit, `--step`,
  the question verdict's optional `options`/`recommend` in `code-writer.md` and `doc-writer.md`,
  the pre-run actions and the environment facts as `action` documents, AIWF-88's checks
  evaluated, `report_edited` removed, `wait` as a machine signal; tests.
- [x] **A5. The plan loop's asks** (§5.3): `plan_questions_rN.json`, `plan_review_rN.json`, the
  documents rendered at exit 4, the plan-writer's and plan-reviewer's hand-back sections, the fix
  pass by default; tests (the exit-4 tests of `test_plan_loop.py`).
- [ ] **A6. Preflight** (§5.6): structured failures, the stale-plugin check gone, the version guard
  relaxed for `--plugin-dir`; tests.
- [ ] **A7. The writing skill** (§5.7): `skills/writing/SKILL.md` from the synthesis, every rule
  with its finding; the role prompts and `document-format` pointed at it, their own prose rules
  removed; `close-out.md`'s entry rules moved. Before phase B: the stages' documents are written
  under it. *Done when:* every writer loads it and no prose rule stands twice.

**Phase B — the stages**

- [ ] **B1. Run-slice** (§5.2): the skill rewritten as the stage's turns with the close-out
  continuation; `/dev:close-out` deleted; the close-out card gone; the wrap-up's asks as
  proposals; `run-loop.md`, `runner-state.md`, `agent-dispatch.md` brought to it.
- [ ] **B2. Plan-slice** (§5.3): the skill rewritten as the small coordinator; `plan-preparer.md`
  written, `grounding.md`, the continuation and the clarification turn by sub-agent;
  `refinement-writer.md` and `refinement.md` deleted; `plan-template.md` and `plan-loop.md`
  brought to it.
- [ ] **B3. Triage** (§5.4): the chat skill's output rewritten from the read — the questions
  first, the scheme as one line per slice with `needs:`, nothing empty; the template, "go", the
  fixed answer forms and the Solution Known lane gone; `sweep_slice.py` with its tests,
  `residual-sweep.md` and `slice-dag` deleted; `needs:` in `slice.md`'s front matter read by
  preflight's "ready to plan". Not a stage: no document, no brief (ruled 2026-10-30).

**Phase C — the sweep and the gutting**

- ~~**C1. AIWF-36**, the risk table and the reviewer's dispatch line.~~ Closed by the operator,
  2026-10-30; nothing to build.
- [ ] **C2. AIWF-82's rule** (after decision 8): the prompts, the format skill, the checks.
- [ ] **C3. The blanket-accept scan** and the trims of `inbox`, `onboard`, `arch-design` (§6).
- [ ] **C4. Dead code and the research tools** that read gone artifacts: `close_out_readout.py`'s
  snapshot import left as research, noted in its header; nothing else.
- [ ] **C5. The AIWF cards** commented with their fate (§7); closed at the cutover.
- [ ] **C6. Optional, if it falls out of A4:** the review set computed from HEAD before and after in
  every repo a session committed to, in place of the `Review:` ledger (§2).

**Phase D — the docs**

- [ ] **D1.** `README.md`, this repo's `CLAUDE.md`, `docs/ADOPTING.md`, `project-contract.md`,
  `preflight.md`; `docs/rationale/`: `plan-refinement.md` and `reporting.md` rewritten or moved
  to `history.md`, `principles.md` § Git and gates corrected, `overview.md` the new flow; the
  0.10.0 changelog entry that tells the story once.

**Phase E — the rehearsal** (decision 10)

- [ ] **E1.** Plan-slice and run-slice end to end in ad hoc sessions with `--plugin-dir` on a
  throwaway slice of a test spec repo, the fallback path showing each document, the answer lines
  edited by hand; `/dev:triage` once in chat with its new output; the documents read against the
  synthesis (§5.7).
- [ ] **E2.** One rehearsal through pilot-dev: a test project, a free-form work item whose brief points
  at the branch's skill by path with `CLAUDE_PLUGIN_ROOT` named; the round trip watched —
  register, the pass, the operator's answer from the phone, the write-back, the continuation, a
  clarification turn.

**Phase F — the cutover** (with implementation-plan step 17)

- [ ] **F1.** Merge to `main`, publish 0.10.0, the marketplace updated in every environment.
- [ ] **F2.** PilotProjects: `rules/stages.md` rewritten — the two commands, the brief's arguments,
  what each stage registers, the ticket in the brief, what each fate means for the pass (§5.1);
  `rules/work-items.md`'s brief for a stage; the definition chat's skill given triage's substance
  — the standing-decisions check, the questions first with a recommendation, `slice.md` from
  `project.md` (§5.4).
- [ ] **F3.** PilotAppSpecs: `feed-model.md` §7 brought to what was built; `aiworkflow-redesign.md`
  reworked into the record of the points and their fates, or retired; `aiworkflow-structured-data.md`
  marked as the 0.9.93 survey it is; the ledger's F92 row ticked; the rulings of §1 and §9 as rows
  in `decisions.md` where they bind the record — triage as the definition chat's among them.
  PilotApp: `CLAUDE.md`'s dev-pipeline paragraph, `.aiworkflowrc` checked (unchanged).
  KubeCoderConfig: the `youtrack-usage` skill's "done is the operator's move" brought to the
  run's continuation moving the slice card to Resolved, its plugin version bumped; not before F1,
  since the 0.9.x plugin still leaves done to the operator.
- [ ] **F4.** The AIWF cards closed (AIWF-36 already is).
- [ ] **F5.** The first slice through Pilot, the phone's layout (031), on 0.10.0.

## 9. Rulings

Recorded here as the operator gives them, dated, each naming the decision of §1 it answers.

**2026-10-30, on the plan as written** (the operator's review, actioned the same day):

- Decisions 1, 3, 4, 6, 7, 10, 12: agreed as recommended.
- Decision 2: agreed, with the caveat that the continuation of the run session is a cache miss
  on a session over an hour old (small context, so cheap) and that the close-out skill's rules
  must not be lost with the skill — §5.1 lists them by home. The operator asked whether the
  store agent needs a running-the-workflow skill: no — it pre-rules, it does not run; what it
  needs is F2.
- Decision 5: agreed, with the preparation moved into a sub-agent and the session kept small
  (§1.5, §5.3); questions about the slice are answered by a sub-agent pointed at the folder,
  never from the session's own reading.
- Decision 8: agreed ("prose can change also", but quotes are easier to resolve, to detect and
  to read).
- Decision 9: as recommended, except AIWF-36, closed (§7).
- Decision 11: agreed, kept minimal.
- §2: worktrees stay the shared repos' mode only; the KubeCoder `needs:` declaration is not
  pursued and preflight's checks stay; the axe is allowed on prose rules and tracked fields, the
  research leading; the evidence behind an ask stays available (§2's tail).
- §4: requirements follow `close-out.json`'s mechanism, and one tool serves both — `asks.py`.
- §5.2: the 55-minute check goes whole.
- §5.4: the triage output is to be redesigned from a read of the operator's answers, not from
  the template; see §5.4.
- Rich prose — paragraphs, lists, formatting, no 200-word paragraph — is a must of the writing
  skill (§5.7).
- Parked for later: PilotApp managing the loop's process (§0).

**2026-10-30, second round** (on the six questions the first round left):

- Questions about a slice: the simple option — Pilot's clarification turn with the sub-agent
  inside it, the continuation on the aged session; whether the cache misses cost real budget is
  reviewed after some slices through Pilot, P-128 (§5.3).
- Triage is the definition chat's in Pilot, `/dev:triage` the operator's chat skill (§5.4, F2,
  F3).
- The run's continuation moves the slice card to Resolved (§3).
- The writing skill is its own, `dev:writing` (§5.7).
- The later-phase proposal bug is fixed on the branch only, no patch on `main`.
- The Solution Known lane and `sweep_slice.py` are dropped as unused (§5.4, §6, B3).
- The branch may be pushed (pushed 2026-10-30). §8 stands as written, the build may start.

**2026-10-30, at A0:**

- The contract page, `plugins/dev/docs/pilot.md`, is approved: A0 is done. With it, against
  §5.2's and §5.3's backgrounded wait: Pilot as built makes a work item done at any turn's end
  and refuses `register_document` between turns, so a stage waits on its own loop inside the
  turn, in the foreground, and Pilot is not changed for it. A4, B1 and B2 build to the page.
- The branch is pushed as needed, item by item, without asking.
- KubeCoderConfig's `youtrack-usage` skill, whose "done is the operator's move" the
  continuation's Resolved reverses, is brought to it at the cutover, in F3 (placed there on the
  operator's "no preference").
