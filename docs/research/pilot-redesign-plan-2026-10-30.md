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
and the 91 changes from 0.9.57 to 0.9.147, read as a whole (§2).

**Working the plan.** A session starts in `/work/PilotApp` (the project whose memory points here),
checks out `pilot-redesign` in `/work/AIWorkflow`, reads §1 and §9, and takes the first unticked
item of §8; a decision an item needs that §9 does not rule is built as recommended. Every commit
bumps the plugin's version and adds a changelog entry, as this repo's `CLAUDE.md` says, and the
item's box is ticked in the same commit; a ruling the operator gives is written into §9, dated,
naming its decision. The branch is pushed only on the operator's word. The surveys this plan was
written from are not kept: an item's session reads the code it changes.

## 0. In short

A stage of the workflow — triage, planning, a run with its close-out — becomes **a Pilot work
item**: Pilot starts a headless session with a brief whose first line is the stage's command, the
skill does its work, writes its asks as **a block document**, registers it with Pilot, attaches
what backs it, and ends its turn; Pilot's pass pre-rules, the operator answers in the app, the
answers come back in the file, and the session is resumed with a message naming the file. Nothing
is put to a person in chat, nothing is edited by hand in a rendered file, no card is a pointer a
person follows, nobody checks on a loop every 55 minutes.

Three things make it one design rather than four reworks:

1. **Every ask a program acts on is data, and one module renders it.** `close_out.py` already is a
   store rendered to Markdown and read back; the refinement's decisions, the plan-writer's
   questions, the plan-reviewer's findings, the run loop's bail-outs and the triage's fates get
   the same treatment: the agent that judges writes structured entries, a new stdlib module
   `blocks.py` renders them in the format skill's grammar (front matter, shared context, one ask
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

## 1. Decisions for the operator

Each with the recommendation first. A decision not overruled before the item that needs it is
built as recommended; the rulings are recorded in this page's §9 and, where they bind Pilot's
record, as rows in PilotAppSpecs `decisions.md` at the cutover.

1. **The dividing line between coded and written documents** (§0 point 1). *Recommend:* an ask a
   program acts on is data rendered by `blocks.py`; prose under the format skill only where no
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
5. **The order of planning stays** (§5.4). *Recommend:* the requirements asks first, the plan
   loop after, as today; each ask carries the approach in short, not a drafted plan. The
   alternative — a writer round before the asks so that each carries the draft — pays for a
   plan that the answers then rewrite.
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
9. **The AIWF sweep's fates** (§7). *Recommend:* AIWF-36 built, AIWF-88 built as its design
   recommends, AIWF-84 answered by Pilot's deferral, AIWF-82 by decision 8, AIWF-113 already
   landed; AIWF-1, -35 and -40 closed as not pursued, with a line each saying why.
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
| Git: the spec tree branched in place, its lease, hook and `spec_commit.py`, then worktrees; bases that move (0.9.64, 79, 86, 88, 93, 103, 139) | 7 | **Replaced already** (0.9.93), now converged. Consider worktrees as the one mode for code repos too, so there is one path; not in this rework unless it falls out |
| Environment readiness: eleven pre-checks inferring needs by scanning other repos' manifests (0.9.68, 74, 75, 77, 83, 106, 109, 111, 113, 117, 121) | 11 | **A wrong tool that belongs to KubeCoder.** The plugin reverse-engineers the environment model; a `needs:` declaration per component and one readiness answer from `kc` would end the scans. Kept as is here; a KC card at the cutover. The stale-plugin check (0.9.75) is moot once Pilot launches the plugin |
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

## 3. The stage as a work item — the contract

This is what `plugins/dev/docs/pilot.md` states once written (§8 A0), the one home for the shape
every stage skill follows; `docs/AUTHORING.md` points at it.

**The brief.** Pilot's `add_item` for a stage carries a `brief` whose first line is the stage's
command — `/dev:triage P-106 P-107`, `/dev:plan-slice 031`, `/dev:run-slice 031` — so the skill
loads with what follows as its arguments (the-brain §5.4); then the brain's own text: the task in
a line, the project's ticket (`P-5`), and the grants text the switch selects; then the server's
`From Pilot:` lines — the plan task to write as `step`, the switch, the handbook verbatim
(PilotApp `docs/mcp.md`, PilotProjects `rules/work-items.md`). The skill reads the slice from its
arguments, `step` and the ticket from the brief, and the spec repo from the cwd's `.aiworkflowrc`
as today. A brief without a ticket files no parented card and says so in its document.

**The documents.** Every ask goes into a file under the slice's folder in the spec repo,
`slices/<NNN>/asks/<n>-<slug>.md`, numbered in the order written, except the close-out, which is
`close-out.md`. Each is rendered by `blocks.py` from entries: the front matter (`title`,
`summary` on more than one ask, `step` from the brief, `for` only for a person's handle), the
shared context, one ask per heading section with its block last, ids unique in the document. The
session registers it with `register_document`, attaches what backs it with `attach_file` (the
material, the plan, the diffs, the record), and ends its turn with no tool call pending. A
registered file is never edited by the workflow again: the write-back is the one write it takes,
and a revised ask is a new document.

**The continuation.** The resumed session's first message is Pilot's, verbatim: "Your documents
were answered and written back in place: <path>, <path>. Read the answers and continue." The
skill reads the answers back through `blocks.py` (`answer`, `by`, `at`, `note`, `to`, `done`,
`via`), acts on each — a ruling into `plan.md`, a card, a fold, a strike, a slice folder — and
goes on. Three readings are fixed: the operator's words travel **verbatim**, `answer` and `note`
quoted wherever the ruling is restated (`aiworkflow-redesign.md` point 3); an answer `by: agent`
is Pilot's choice on a delegated ruling and is **marked so** on anything it produces ("chosen by
Pilot: '<note>'; the operator did not decide this"); `answer: deferred` with `to` is **terminal**
for the workflow — the block's fate is Pilot's, the entry closes as deferred, nothing is kept to
bring it back (point 7, FM §7).

**The clarification turn.** A turn opening "Pilot asks about <path>:" is the pass's question to
the writer (F52.2, D059): the skill answers each under `## <local id>` in words, registers
nothing, starts nothing, and ends its turn.

**The nudge.** A turn that is neither the continuation's message nor a clarification — the nudge
after a halt or a pause (F135.3, F141.3) — resumes what the session was doing: a loop that exited
`halted` is resumed, a document still unanswered is left as it is and the turn ends.

**The halt file.** `/work/.quota-limit-halt-requested` present means stop at the next safe point
(§5.5); present at a loop's start means do not start.

**Cards.** Every card a stage files — a slice card, a card a close-out ruling asks for — is
parented to the project's ticket from the brief (F57.1), through the host convention
(`kubecoder:youtrack-usage`); the slice card's moves (triaged → planned → in progress → resolved)
stay the skills', Done the operator's.

**The fallback** (decision 11): no `mcp__pilot__register_document` among the tools → print the
path, end the turn; the continuation is the operator's "continue".

**What a skill never does:** present an ask in chat, offer a word that accepts everything, read a
ruling from prose, edit a rendered file by hand or ask anyone to, wait by polling, tell "the
operator" anything that is not in a document.

## 4. The shared module: `blocks.py`

Stdlib, beside the other tools, imported by `close_out.py`, `plan_loop.py`, `run_loop.py` and
called by the triage skill through a small CLI. Two halves:

- **Render.** `render(document) -> str` from `{title, summary?, step?, for?, context: [lines],
  entries: [{id, kind, headline, body: [lines], options?: [{label, line?}], recommend?,
  proposal?, default?, check?}]}`: the front matter, the context, then per entry `## <headline>`,
  the body, the block last, the kind's keys in the format skill's order, every value quoted where
  YAML would read it as something else (a colon-space, a leading `#`, `- `, `[`, a quote, a
  backtick), a multi-line value as a literal block. It refuses what Pilot would refuse (a duplicate
  id, `recommend` naming no option, `options` beside `proposal`, a heading inside an ask).
- **Read back.** `answers(text) -> {id: {answer, by, at, note, to, done, via}}` over a
  written-back file: the fences found by their info string, the answer lines read with a parser of
  the subset the record writes — `key: value` scalars, quoted or plain, a `|` literal block for a
  note — and nothing else of the body touched. The grammar whole is PilotApp `docs/block-dsl.md`;
  the format skill is the writer's view of it, and a test pins the module against the skill's own
  example.

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
- **The document.** `close_out.py render` writes `close-out.md` through `blocks.py`: `title`
  "Close-out of slice NNN — <title>", `summary`, `step`; the context — the slice in two lines,
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
- **The wrap-up** keeps its bar and its fixes; its asks become proposals on the entries.

### 5.2 The run

The run-slice skill becomes the stage's turns (§3), the driver untouched but for what it renders
and when it stops:

- **Start.** Parse the brief; preflight; an environment fact that stops the start — a tool
  container, a service, a Target not cloned, a dirty tree — is an `action` document with the
  exact fix and a `check` naming the fact, registered, the turn ended; Pilot's pass claims what
  the grants allow (a restart is a fleet call), the operator does the rest, and the continuation
  runs in the mended environment. Open pre-run actions are an `action` document the same way.
  Then `run_loop.py run <slice> --detach --step <tN>` and one backgrounded `wait` that re-invokes
  the session when the run ends or stops; no status posts, no re-arm for a person.
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

The plan-slice skill becomes the stage's turns; the refinement-writer and `docs/refinement.md`
go (point 1):

- **The requirements document.** The session reads `slice.md`, the card and the cards linked
  after triage, grounds every claim with read-only sub-agents and checks a checkable premise
  before it asks (point 13), then writes its asks as entries: a decision the operator could
  plausibly rule the other way as a `decision` with options, the recommendation, what it
  optimises for and the card it serves named in the prose (the card-id ban lifted, FM §7); an
  open fact as a `question`; a new repository to create as a `decision` with a proposal; "this
  slice needs an arch design first" as a decision when it does (decision 6). The settled items
  and the approach in short are the shared context (decision 5). `blocks.py` renders
  `asks/1-requirements.md`; the grounding, the sub-agents' findings and `slice.md` are attached;
  the turn ends. A slice with nothing to ask skips the document.
- **The continuation** writes the rulings into `plan.md`'s rulings section verbatim (`by: agent`
  marked), seeds the header, commits, and launches `plan_loop.py` with a backgrounded wait.
- **The plan loop's exits.** The plan-writer writes its questions as `plan_questions_rN.json`
  and the plan-reviewer its findings as `plan_review_rN.json` (the prose review kept beside it,
  attached); the loop renders each exit-4 as a document in `asks/` — a question per block, a
  blocking finding per `decision` with the reviewer's disposition recommended — and exits; the
  session registers, attaches the draft plan, ends its turn; the continuation writes the answers
  into `plan.md` and reruns; the fix pass runs by default, there being no operator sanity-read.
- **Exit 0.** The dry run, the promotion to `slices/`, the commit, the card to planned, as today;
  the turn ends with one line.

### 5.4 Triage

The triage skill becomes the stage's turns; the chat message, "Go", `agreed`, the handover dump's
`## Rulings` and `/dev:slice-dag` go (points 11, 17):

- **The triage document.** Collect, itemize, the standing-decisions check and the research run as
  today, by sub-agents; the scheme is written as entries — one `decision` per item, its options
  the fates (`Slice A: <title> (~N phases)`, `Solution Known`, `Operator action`, `Close: duplicate
  of X`, `Later`, `Decision`), the proposed fate recommended, the ask in the card's words as the
  body; a standing-decision collision a `decision` (overrule / close on it); a question the
  operator can answer from memory a `question`. The raw dump is attached as the archive.
  `blocks.py` renders `asks/1-triage.md`; the turn ends.
- **The continuation** reads the fates: the slice folders written (`slice.md` quoting the answers'
  words as the operator's, its front matter carrying `issue:` and `needs:` — the slices it must
  follow, structured, which is what survives of the DAG), the subsumed cards closed, `later` and
  `close` actioned, the Solution Known lane to `sweep_slice.py` at its floor, the slice cards
  filed and parented, the README's Pending lines, the commit. A `conditional:` answer re-enters
  research and may register a second document.

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
the stale-plugin line goes. `/dev:onboard` stays an operator-driven skill with its by-hand steps
trimmed, its "pre-ruled headless" shape the template for a later Pilot-driven onboard.
`/dev:inbox` stays until v1.1 (decision 7), its "go approves the scheme" gone.

## 6. What goes

- **Skills:** `close-out` (folded into run-slice), `slice-dag`.
- **Agents:** `refinement-writer`.
- **Docs:** `plugins/dev/docs/refinement.md`; `close-out.md` and `close-out-template.md`
  rewritten; the DAG sentence in `spec-tree.md`; `docs/rationale/plan-refinement.md` and
  `reporting.md` rewritten or moved to `history.md`.
- **In `close_out.py`:** the verbs of §5.1; the rendering of the old page; `held`.
- **In `run_loop.py`:** the `report_edited` bail; `wait`'s prose for a person; the stale-plugin
  relaunch; the close-out card and the chat summary in the skill.
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
| AIWF-36 risk level in the reviewer's dispatch | built | `[risk]` in `.aiworkflowrc` (`base`, `paths`, dotfiles high), the driver classifies the phase's diff after each writer round, records it in `state.json`, and the reviewer's dispatch carries the sentence; no skip |
| AIWF-35 risk-based review (the skip) | closed, not pursued | the 2026-08-27 research: documentation is not low risk in this pipeline; AIWF-36 is the part that lowers exposure |
| AIWF-40 a project hook for a mid-run publish | closed, not pursued | 0.9.102's in-phase push ruling at seeding covers the case seen; the operator expected it to come up less |
| AIWF-1 `code_health` grading Go | closed, not pursued | the quality tool's rebuild is no part of this rework; `archive/quality/` stays the frozen record |

## 8. The items, in order

Each item is one ad hoc session or two, on the branch, committed as it goes with the version
bumped and a changelog entry; `kc project test` and `lint` green at every commit. About twelve
sessions in all.

**Phase A — the contract and the foundation**

- [ ] **A0. The contract page.** `plugins/dev/docs/pilot.md` as §3 states it, and `docs/AUTHORING.md`'s
  rules for a stage skill (headless, ends its turn, the brief, the documents, the continuation,
  the clarification turn, the fallback). *Done when:* the page reads as the one home and the
  operator has read it — this is P-111's "Designed" box, with this plan.
- [ ] **A1. `blocks.py`** (§4) with its suite, pinned against the format skill's example and the
  quoting rules. *Done when:* a rendered document of every kind round-trips through the read-back
  with Pilot's answer lines added.
- [ ] **A2. `close_out.py`** (§5.1): the fields, the write model, `render` as the document plus the
  record, `absorb`, the verbs removed, the dispatch line, `close-out.md` and
  `close-out-template.md` rewritten; the suite reworked (the render and read-back half of
  `test_close_out.py`). *Done when:* a store of the old fixtures renders as a document that
  `register_document` would take, and an answered copy absorbs into rulings. The largest item.
- [ ] **A3. The halt file** (§5.5) in both loops, `plan_loop.py stop`, the exit `halted`, tests.
- [ ] **A4. The run loop's asks** (§5.2): every exit-4 rendered as a document before the exit, `--step`,
  the question verdict's optional `options`/`recommend` in `code-writer.md` and `doc-writer.md`,
  the pre-run actions and the environment facts as `action` documents, AIWF-88's checks
  evaluated, `report_edited` removed, `wait` as a machine signal; tests.
- [ ] **A5. The plan loop's asks** (§5.3): `plan_questions_rN.json`, `plan_review_rN.json`, the
  documents rendered at exit 4, the plan-writer's and plan-reviewer's hand-back sections, the fix
  pass by default; tests (the exit-4 tests of `test_plan_loop.py`).
- [ ] **A6. Preflight** (§5.6): structured failures, the stale-plugin check gone, the version guard
  relaxed for `--plugin-dir`; tests.

**Phase B — the stages**

- [ ] **B1. Run-slice** (§5.2): the skill rewritten as the stage's turns with the close-out
  continuation; `/dev:close-out` deleted; the close-out card gone; the wrap-up's asks as
  proposals; `run-loop.md`, `runner-state.md`, `agent-dispatch.md` brought to it.
- [ ] **B2. Plan-slice** (§5.3): the skill rewritten; `refinement-writer.md` and `refinement.md`
  deleted; `plan-template.md` and `plan-loop.md` brought to it.
- [ ] **B3. Triage** (§5.4): the skill rewritten; `slice-dag` deleted; `needs:` in `slice.md`'s front
  matter read by preflight's "ready to plan"; `residual-sweep.md` brought to it.

**Phase C — the sweep and the gutting**

- [ ] **C1. AIWF-36**, the risk table and the reviewer's dispatch line.
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

- [ ] **E1.** The four stages end to end in ad hoc sessions with `--plugin-dir` on a throwaway slice
  of a test spec repo, the fallback path showing each document, the answer lines edited by hand.
- [ ] **E2.** One rehearsal through pilot-dev: a test project, a free-form work item whose brief points
  at the branch's skill by path with `CLAUDE_PLUGIN_ROOT` named; the round trip watched —
  register, the pass, the operator's answer from the phone, the write-back, the continuation, a
  clarification turn.

**Phase F — the cutover** (with implementation-plan step 17)

- [ ] **F1.** Merge to `main`, publish 0.10.0, the marketplace updated in every environment.
- [ ] **F2.** PilotProjects: `rules/stages.md` rewritten — the three commands, the brief's arguments,
  what each stage registers, the ticket in the brief; `rules/work-items.md`'s brief for a stage.
- [ ] **F3.** PilotAppSpecs: `feed-model.md` §7 brought to what was built; `aiworkflow-redesign.md`
  reworked into the record of the points and their fates, or retired; `aiworkflow-structured-data.md`
  marked as the 0.9.93 survey it is; the ledger's F92 row ticked; the rulings of §1 as rows in
  `decisions.md` where they bind the record. PilotApp: `CLAUDE.md`'s dev-pipeline paragraph,
  `.aiworkflowrc` checked (unchanged unless `[risk]` is added).
- [ ] **F4.** The AIWF cards closed; a KC card for the environment-readiness declaration (§2).
- [ ] **F5.** The first slice through Pilot, the phone's layout (031), on 0.10.0.

## 9. Rulings

Recorded here as the operator gives them, dated, each naming the decision of §1 it answers.

*(none yet)*
