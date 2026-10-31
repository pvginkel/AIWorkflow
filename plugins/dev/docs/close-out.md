# The close-out report — one record per slice for everything out of the loops' scope

Every plan and run agent puts what it notices but the loops will not act on in the slice's
close-out report: a bug it will not fix, a keystroke only the operator can make, an event that
deviated from an uneventful run, a choice that is the product owner's, an improvement. The
author of an entry says what it is, in labels the tool checks; a table in the tool routes the
entry from those labels — to the operator, to the wrap-up, closed, or to the record. At the
run's end the report is rendered once, as a document Pilot reads: the operator answers it in the
app, Pilot writes the answers back, and the run's continuation carries them out
([pilot.md](pilot.md)). Nothing from a run is carded per finding.

**The record is `<slice>/close-out.json`; at the run's end it is rendered into `close-out.md`,
the document Pilot reads, and `close-out-record.md`, the record attached to it**
([close-out-template.md](close-out-template.md) has the three shapes). An entry is data for its
whole life, from the plan loop's first append to the continuation's last ruling.
`${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` is the one pen: it writes every author's entries
(`append`), notes (`note`) and strikes (`strike`); the corrections of an entry (`amend`), of its
labels (`relabel`) and of its proposal (`propose`); the section the document shows for an entry
(`restate`); the wrap-up's marks (`propose --card`, `propose --word`, `note --left`); the fold of an entry into a later slice's `slice.md` (`fold`,
which stages that file and writes nothing else); the render (`render`); the answers Pilot wrote
back (`absorb`) and what was done on them (`rule`); the criterion an owed-after action settles
(`settle`, which writes `verification.json` too); and the close (`close`). It prints an entry in
full (`show`) and counts the report. Both loops import it, and every dispatch names it beside the
report's path — which the tool takes as its positional, the slice directory or the report
itself, so the first call works — with the labels each kind carries and how they pair, from the
tables `append` refuses by, and the arguments of `append`, `note` and `strike`, rendered from the
tool's own parser (`close_out.verb_usage`), so no `--help` turn or refused call is spent;
`amend`, whose flags are `append`'s, is named without them. No agent edits any of the three
files by hand.

**The write model.** Until the report is rendered at the run's end, the store is open to
everyone with the pen — an entry's appender, the reviewers, the consults, the wrap-up: `amend`
corrects any live entry, each field given replacing its own and checked as `append` checks it,
`relabel` its labels, `propose` its proposal, and nothing is taken back — what was written wrong
is written again. Nothing renders on a write. The loops render when they stop and at the run's
end, after the wrap-up; the last render is the one the run registers. After it, only the run's
continuation writes, through `absorb`, `rule`, `fold`, `settle` and `close`, and a
`close-out.md` that carries Pilot's answers is never rendered over: a render writes the record
alone.

## What it is — and is not

**Only for what is out of scope of the plan and run loops' own action.** Anything in scope
already has a home: the plan (phases, rulings, done-records), `verification.json`, the review
files, a `question` verdict that pauses the loop. The report is not a thinking scratchpad, not a
substitute for asking the operator when the run needs an answer (a `question` verdict pauses; a
report entry never does), and not a place to restate the plan. It is the release valve for
everything an agent would otherwise have to decide what to do with — the destination is fixed
(put it in the report), the shape is fixed (the entry and its labels), and the table routes.

**About the work, never about working.** The report holds what the operator needs to judge what
the slice hands over. What got in an agent's way while it worked — a tool the sidecar lacks, a
wait that hit a cap, a call the harness refused, an error that hid its cause, a plugin defect —
is the other channel's: the agent posts it to Fieldnotes with the `fieldnotes` MCP tool `post`,
which the host's `~/.claude/CLAUDE.md` describes and every dispatched role is spawned with
([agent-dispatch.md](agent-dispatch.md#spawning)). It reaches the operator curated and across
projects instead of once per slice, and it is what keeps a report at the length that gets read.
The line is the agent's to draw and is easy to draw: would the entry change what the operator
thinks of this slice's outcome? An event that did — a proof that could not be run because the
validator was down, so the criterion stays open — is the report's, as the event it was; the
outage itself is Fieldnotes'. An improvement of the workflow — the agents that build slices,
their suites and gates, CI, the tools they run — is Fieldnotes' too, posted as an `idea`: the
tool refuses it as an entry and says where it goes.

## The labels

An author says what it knows about the thing it reports, and is never asked where it goes: it
does not know the operator's bar, and a bar written into every role cannot be moved. What it
would do about it is a recommendation, its proposal (below), never a route.
The facts are the ones an entry states in prose already — what has to happen for the problem to
show, what is then experienced, whether it then says so itself, what is decided about the fix,
where the fix lives — given in a vocabulary the tool checks. `close_out.py labels` prints this
section.

**Where the author cannot tell, the label is `unknown`** — never a guess; the wrap-up then
looks. `trigger`, `impact`, `signal` and `fix` take it, as do `benefit`, `felt`, `change`,
`size` and `prevents`.

**The kind** says what sort of thing the entry is, and gives the entry its id: the kind's
letter and the next number in order of arrival. An id is given once; a kind corrected later
does not rename the entry.

| kind | id | |
|---|---|---|
| `action` | A | one thing only the operator can do, that something waits on — a criterion, a push, a run. It reads as an imperative ("Create the `IaC/ArgoCDTools` Jenkins job") |
| `decision` | D | the entry puts a choice that is the product owner's as a question: options to pick from, a convention to rule on |
| `event` | E | something happened to the run that an uneventful one would not have had: a bail-out, an appended phase, a blocked proof re-routed, a live run that exposed what the suite hid. A phase or a round that went right is not an event — the run header counts them |
| `defect` | B | the code, the configuration or the deployed system does something wrong today, however rarely |
| `prose` | P | text is wrong, stale or missing — a document, a comment, help text, a message — and the behaviour is not in question |
| `test-gap` | T | a test is missing, pins nothing or cannot fail, and the code it would guard is right today |
| `improvement` | I | nothing is wrong today: a guard against what does not occur with the code as it is, a cleanup, behaviour the product could have or have otherwise. Its headline is what it proposes, not the symptom |

**What is wrong, or could go wrong** — the labels of every kind but `improvement`:

| label | value | |
|---|---|---|
| `trigger` | `normal-use` | shows on a path ordinary use takes |
| | `ordinary-condition` | needs what ordinary operation produces now and then: a restart, a second environment, a slow dependency, an upgrade, a legitimate but particular input |
| | `fault` | needs a fault, a narrow timing window, a misconfiguration, a misuse, or several conditions together |
| | `future-change` | cannot show with the code as it is |
| | `none` | there is no problem that could show |
| `impact` | `severe` | data lost or corrupted, something exposed, or a failure that cannot be recovered without repair |
| | `broken` | a wrong result, or a flow that fails or stays stuck until somebody intervenes |
| | `degraded` | it works, and somebody is told something wrong or notices it is worse: a wrong message, status or document, a fault that corrects itself, a slowdown |
| | `none` | nobody would notice; what is cosmetic is here |
| `signal` | `loud` | when it happens it says so itself: an error, a crash, a refused request or deploy, a red gate, a flow that visibly stops — whoever meets it knows that something went wrong |
| | `silent` | nothing says so: a wrong result taken for a right one, a protection that does not protect, data lost or changed without a message, a step skipped and reported done, a status that states something false and reads as true |
| | `none` | the entry has no impact, so there is nothing to announce |
| `fix` | `one-edit` | the entry states the exact change, in one place |
| | `several-places` | known and mechanical, in more than one place |
| | `design` | a choice with consequences is open, or the change adds behaviour — a code path, a piece of state, a process, a gate |
| `area` | `plain` · `sensitive` | sensitive: the change touches concurrency or timing, the layout of stored data, a wire contract, or authentication and secrets |
| `repo` | a name | the repository the fix lives in, by its directory name |
| `for` | a slice, optional | the slice still to run that should take the entry, by its number — one a project's plan names that no folder holds yet among them; `relabel --for none` clears it |

**What could be better** — the labels of an `improvement`, which says what the change would
bring and what it would take:

| label | value | |
|---|---|---|
| `benefit` | `user` | somebody using the product is better off: what they see, can do, or have to do by hand |
| | `operations` | whoever deploys, runs, upgrades or recovers the system |
| | `workflow` | the agents that build slices, their suites and gates, CI, the tools they run. This is Fieldnotes', not an entry |
| | `code` | whoever maintains the code or the documentation |
| `felt` | `in-use` | as things are today, each time or on ordinary occasions |
| | `after-change` | only once somebody changes something, or something outside changes |
| | `after-incident` | only when something goes wrong first |
| | `not-observable` | nobody would notice the difference |
| `change` | `remove` | it takes something away: code, a duplicate, a step |
| | `adjust` | it changes what exists, in place |
| | `add` | it adds something: behaviour, a check, a gate, an alarm, state, a process, a document |
| `size` | `one-edit` · `several-places` · `design` | as `fix` above |
| | `investigate` | something is to be looked into before anything changes |
| `product-call` | `yes` · `no` | it changes what a user of the product sees or can do |
| `prevents` | `severe` · `broken` · `degraded` · `nothing` | the worst it would prevent, on the scale of `impact` |

`area`, `repo` and `for` are an improvement's as well.

**Which labels an entry carries:**

| kind | carries |
|---|---|
| `defect`, `test-gap` | `trigger`, `impact`, `signal`, `fix`, `area`, `repo` |
| `prose` | the same without `area`: prose has no sensitive area |
| `event` | `trigger`, `impact` and `signal`; with an impact other than `none` also `fix`, `area` and `repo` |
| `action`, `decision` | `trigger`, `impact` and `signal`; the others where the entry names a fix |
| `improvement` | `benefit`, `felt`, `change`, `size`, `product-call`, `prevents`, `area`, `repo` |

**The grade** is for an entry of any kind that has one: `major` (a wrong result or a broken
flow, unfixed) · `minor` (a real defect with a contained consequence) · `nit` (true, no
practical consequence today) · `cosmetic` (no behavioural or informational consequence — a
stale line pointer). The reviewer's own Blocker/Major/Minor never reaches the report: a Blocker
gets fixed.

**Where the line is drawn:**

- **Wrong today, or better tomorrow.** A defect, prose and a test gap say that something should
  be fixed; an improvement says that something could be better, safer or simpler. A hardening
  against what cannot occur with the code as it is, and a cleanup, are improvements.
- **A decision asks its question.** Its headline is the question; its body opens with what was
  chosen and whether it has shipped. Its options are fields, two or more (`--option`, the label
  and one line), the one in effect saying so, each line with what switching to it would cost — a
  revert, a migration, a changed contract, work redone — and the one its author would pick is
  `--recommend`, in place of a proposal. `Consequence:` is what is experienced while the choice
  in effect stands, as for every kind. An account of what the writer did, with the alternatives
  somewhere in a paragraph, is not a decision, and an entry that ends in "the operator's call"
  is what it was before that sentence. A ratification — a change already shipped, with no alternative but undoing it — says
  so in its first line, and its options are keep and revert.
- **An action is one thing to do, and nothing waits on a notice.** Its headline is the
  imperative, and its author can say who waits on it — a criterion, a push, the run. An "if"
  makes it a decision. A fact nobody has to act on — a surface that changed, a step that was
  taken, a convention the slice kept — is not an entry: what an owner might want to rule on is
  a decision put to them, the rest is nothing. An action whose `Consequence:` is none is a sign
  the kind is wrong.
- **An improvement says its change.** "Quiet the MCP SDK's INFO lines in the mcp log" is the
  headline; "the SDK's lines outnumber ours" is the body's first sentence. An improvement whose
  headline asks a question is a decision, with options: the tool refuses the question mark and
  says so.
- **A limit the plan chose is not a defect.** An entry that proposes to lift it is an
  improvement; one that only records it restates the plan and is not an entry.
- **Input for a later slice is `for`, beside the kind**: a defect that a later slice should
  take is still a defect.
- **An action, a decision or an event that describes a problem** carries that problem's
  trigger, impact and signal; one that does not carries `none` for each.
- **A test gap** carries the trigger, impact and signal of what it would prevent — as a rule
  `future-change`, and the signal of the fault as it would be met in use: a gate that stays
  green is what every test gap is.
- **Prose is labelled by what following the words does**: a procedure that fails when followed
  is `broken`, a stale pointer is `none`.
- **The signal is of the moment the problem happens**, not of how bad or how likely it is. A
  failure that destroys data under a stack trace is `loud`; a harmless wrong number that nobody
  questions is `silent`.
- **An error that follows by itself from the same act is `loud`**: a configuration that loads
  and then fails the pod's creation. What shows only through what follows from it — a disk that
  fills, a certificate that was never renewed — is `silent`.
- **A message that states something false is `silent`; an error whose cause is hidden or blamed
  on something else is `loud`.** Output that is visibly odd and no more is `loud`.
- **Of two outcomes, one of each, the signal is `silent`.**
- **What you fixed yourself is not an entry**; what is entered already and you fixed, you
  strike.

**The proposal.** Beside its labels an entry says what its author would do about it and why,
in a sentence or two (`append --proposal`), one line of at most 300 characters, which the CLI
refuses past: in Pilot it is the label of the one row that agrees, and the line the answered
block shows, so what it rests on goes into the body. An action and an improvement carry one from
their author, and a decision its options and the one it recommends in its place; the tool
refuses them without. A defect, a test gap or prose may carry one, and gets the wrap-up's where
the table brings it to the operator — a card request is a one-line proposal on the entry
restated as the card (`restate`, then `propose --card`); a risk gets one where its author gave
none or the code says otherwise (`propose`). A proposal is a recommendation, never a route: the
table decides who sees the entry, the operator what happens to it.

**What must land first.** An entry whose fix must not wait for the run's end says what it must
land before (`--due`): the phase's merge, the test phase, the push, or the report's close. The
run loop hands the completion consult every live entry due before the push or the test phase
([run-loop.md](run-loop.md) § After the last phase). An action whose being done shows in the
tree or the pod says so as a fact (`--check`, repeated for each): `env <NAME>` set in the pod
that runs the slice, `file <repo>:<path>` present, `origin <repo> <branch>:<path> contains
<text>` after a fetch, `slice <NNN> completed` — never a commit, which a push can rebase, nor an
environment, which may not be the one that runs the slice; `manual` where no check captures it.
An action owed before the run carries one, which the run loop evaluates before it starts
([run-loop.md](run-loop.md) § Protocol invariants). One that asks for an answer back names the
answers (`--option`).

**The tool refuses**, naming the flag, so that the author corrects in one turn:

- an action or an improvement without a proposal; a decision without two options or more and
  the one it recommends, or with a proposal; an improvement whose headline is a question;
- an option, a recommendation or a check on a kind that does not take it, a recommendation
  naming no option, a due that is no step of the run;
- a check outside the vocabulary, one naming a commit or an environment, `manual` beside another
  check; an action owed before the run without one;
- an entry without the labels its kind carries;
- an impact other than `none` over a `Consequence:` that opens with "none", and the reverse;
- a `for` that names the slice being run, or one whose folder has left `slices/` and
  `slices/backlog/` — it has run, or was cancelled; on a relabel, only a `for` the call gives;
- an improvement whose benefit is `workflow`.

## The routes

**The author labels, the tool routes.** The policy is the operator's and is one table in
`close_out.py`, the same for every project. A routing can always be explained from the labels
it rests on, and a readout can hold the labels against the rulings. The route is not stored:
`render` computes it, so a corrected label routes the entry again at the next render. Nothing
that comes to the operator is decided by anyone else.

What should be fixed — every kind but `improvement` — takes the first row that fits:

| | an entry that is | goes |
|--:|---|---|
| 1 | an action | to the operator |
| 2 | a decision | to the operator |
| 3 | an event that describes no problem | to the record |
| 4 | input for a slice that is still to run | to the wrap-up, to fold into that slice; to the operator, as an action, once that slice is planned or running; to the operator, to hold for it, while no folder holds it |
| 5 | fixable only in a repository the slice did not touch | to the operator as a card request when it shows and has an impact as row 8 says, or is `severe` or graded major; closed otherwise |
| 6 | prose; or fixed by one edit or in several known places, outside a sensitive area | to the wrap-up, to fix |
| 7 | anything else, with a trigger or an impact `unknown` | to the wrap-up, to look |
| 8 | anything else that has an impact and shows in normal use, or on an ordinary condition and is not `loud` | to the wrap-up, to fix within its bar or to ask for a card |
| 9 | anything else that is `severe`, or graded major | to the operator, as a risk |
| 10 | anything else: it needs a fault or a future change, it is `loud` on an ordinary condition, or it has no impact | closed |

An improvement takes the first of these that fits:

| | an improvement that | goes |
|--:|---|---|
| 1 | is input for a slice that is still to run | to the wrap-up, to fold into that slice; to the operator, as an action, once that slice is planned or running; to the operator, to hold for it, while no folder holds it |
| 2 | adjusts or removes, in one edit or in several known places, and is no product call | to the wrap-up, within its bar. In a repository the slice did not touch: to the operator as a card request when it prevents something `severe` or is graded major, closed otherwise |
| 3 | adds something, for a benefit that is not felt in use, and prevents something `severe` or is graded major | to the operator, as a risk |
| 4 | adds something, for a benefit that is not felt in use | closed |
| 5 | is anything else — a product call, a change that needs design or a look first, an addition felt in use | to the operator |

- **A `for` is read against the slice it names, at every render.** Unplanned, the entry folds
  into its `slice.md`. Planned or running — a `state.json`, or a `plan.md` with a phase
  heading, a seeded one in the backlog too — its run never reads `slice.md` again, so the
  entry comes to the operator as an action, to add a phase or rule on that run. No longer
  still to run — it has run since — the entry routes as if it had no `for`. **Not created yet**
  — a number no folder under `slices/` holds, at any stage: a slice the project's plan names
  that triage has not filed — the entry comes to the operator, proposed to be held for that
  slice, and Pilot defers it to that slice's task: the workflow keeps nothing for it.
- **Severity stands where the close would have been, and nowhere else** (row 9, and row 3 of
  the second table). What is severe is not closed for being unlikely; where the table would fix
  it or ask for a card, it does.
- **What is loud on an ordinary condition is closed**, as what is unlikely is closed: when it
  is hit, it will be very visible. Only `loud` closes — a signal that is `silent` or `unknown`
  leaves the entry in row 8; an easy fix is made whatever its signal (row 6); and what fails on
  a path ordinary use takes is met by everybody, loud or not, so it stays the wrap-up's.
- **An `unknown` is not taken for the value that closes.** A trigger or an impact that is
  `unknown` sends the entry to the wrap-up to look, and in row 5 counts as one that shows and
  has an impact; a benefit whose `felt` is `unknown` is not taken as unfelt.
- **Whether the slice touched a repository** is read from the run's record in `state.json`: the
  roots its phases landed in, and the repositories its unfinished phases' `Target:` lines
  resolve to (`target_roots`). A phase counts from the moment the plan names it, so an entry
  for the repository of a phase still in review, or still to run, routes as the slice's own.
  Without a run record every repository is taken as the slice's own.
- **An entry without labels** — a report written before the labels existed — has no route. It
  waits, in a section of its own, until it is labelled.

**A card request** is an entry that comes to the operator with a card asked for: by the table
where the fix lives elsewhere (row 5), by the wrap-up where a likely problem is more than it
can fix responsibly (row 8, `propose --card`). Its section is the card — the heading what the
card would say, the body the card's text — and its proposal the line Agree files it on; the
continuation files the section. Nothing is filed before the operator's word. **A request for the
operator's word** is the wrap-up's for an edit it would make but a rule of the project reserves
for them (`propose --word`): it comes to them whatever the table's route, the entry restated as
the exact edit and the rule, its proposal the line their assent makes it on, so that their
assent is the ruling and the continuation makes the edit.

## The document and the record

`close_out.py render` writes two files from the store, both computed, neither ever edited.

**`close-out.md` is the document Pilot reads**, in `/dev:document-format`'s grammar, rendered
through `${CLAUDE_PLUGIN_ROOT}/tools/asks.py` — the format, the quoting and the refusals are
that module's. It holds one ask per entry the table brings to the operator, per card request,
and per entry no wrap-up reached or nobody labelled, which comes to the operator said as what
it is: in that order, each place by grade, kind and id. An entry's ask is its section, the
current story told once — its headline as the section's heading, its body, an action's
proposal, its `Consequence:` and its `Provenance:` as prose, each the restatement's where the
entry has one (`restate`), else its author's — and its block last, the block's id the entry's.
No note stands in a section: every note is the record's, and what a note changed, the wrap-up,
which vets every entry that comes to the operator, says by restating the entry. An action is an
`action` block with its options and its check; a decision with options a `decision` block with
them and the one recommended; every other entry a `decision` on its proposal — or, where the
table brought it for a reason of its own, the one that reason makes: a card for the repository
the fix lives in, a phase for a planned slice, holding it for a slice not created yet — and a
`question` where nobody proposed anything. The front matter carries the title, a summary over
more than one ask and the brief's `step`; the shared context, the run in a line, what shipped,
what the wrap-up settled, and the record attached. The labels, the route, the grade, the run
header and the old page's sections are not on it. A report with no ask renders no document.

**`close-out-record.md` is the record**, attached to the document: the run header, what was
ruled and what was done on it, the operator's words verbatim and an answer Pilot chose said as
Pilot's; what is asked and open, under the heading it is asked by, with the trail its section
leaves out — the author's own text where a restatement took its place, every note and the
wrap-up's mark; what the table closed, with its consequence, its
labels in words, its evidence and the ground of the close, so that a close can be questioned
from one line; and the record — the run's events, then every entry struck, with its reason.

`close_out.py show <id>` prints an entry in full — its restatement, its author's body, every
note, its fields, labels, marks and ruling — and is how the wrap-up, the continuation and a
clarification read one; `show <id> --card` prints the card an agreed card request files.
`close_out.py list` is the view an agent takes before it appends: ids, headlines and
Consequence lines, without the bodies.

## Who writes what, when

Both loops create the store if it does not exist — the plan loop first, so planning can already
write to it. All agents may append, through `close_out.py append` (`list` first shows what is
already there); an agent commits the store with its own commit, staged by name like every other
slice-folder artifact ([spec-tree.md](spec-tree.md)). The store is one JSON file and cannot be
staged in part, so the run loop commits it before every dispatch that finds it changed: the
driver's own entries, and whatever an earlier session left uncommitted, are in the loop's commit,
and a role's commit holds only what the role wrote ([run-loop.md](run-loop.md) § Protocol
invariants).

- **plan-writer / plan-reviewer** — out-of-scope observations about the spec or the estate;
  events during planning. Their in-scope findings and questions keep their existing routes (the
  review's and the questions' hand-backs, which the loop renders as documents). An action only the operator can
  take that the run needs *before* it starts — a push the plan's tools wait on, a pod restart —
  is an action whose headline begins `Before /dev:run-slice:`, with the check that shows it
  done; the run loop strikes it when its checks hold and does not start while one is open
  ([run-loop.md](run-loop.md) § Protocol invariants).
- **the plan loop** — at its exit 0, one action per repo the plan's `## Push holds` holds,
  listing the criteria `verification.json` marks `owed_after` that push, and one per criterion
  owed after anything else ([plan-template.md](plan-template.md)). Each is entered once: the
  push check notes the seeded hold entry instead of writing its own.
- **code-writer** — anything out of the phase's scope it noticed; events in its session.
- **code-reviewer** — its advisory findings, each as an entry of the kind it is; the review file
  keeps the full finding and stays the evidence trail. An entry may state its fix — the fix
  label asks for it; "describe the problem, never the fix" governs review files, not the report.
- **consults** — sub-bar findings. The **completion consult reconciles the report**,
  and only through `close_out.py strike` and `note`: it strikes an entry it absorbed into an
  appended phase (the reason names the phase and commit), duplicates it is sure of, and what a
  later phase resolved (the reason names the commit and what was re-run); anything else it has
  to say about an entry is a `note`. It edits nobody's text. It is the one reader of the report
  before the slice's push, and is handed what is due before it ([run-loop.md](run-loop.md)
  § After the last phase).
- **test-agent** — below-bar findings; live-check events — what its pass met that an uneventful
  one would not have, never the record of a round that passed.
- **doc-writer** — doc debt, every claim it could not verify among it; a strike on an entry its
  own commit resolved whole (the reason names the commit), a `note` on one it resolved in part,
  which stays live — the doc phase runs after the last consult, and what it fixed would
  otherwise reach the operator as open work.
- **the driver and the plan loop** — deterministic entries only, and no labels of their own
  choosing: the tool labels what a loop enters, an action as an action and an event as one that
  describes no problem, unless its `Consequence:` says otherwise — then its trigger and impact are
  `unknown`. A refuted finding, a funding-consult merge and every stop of the run (entered by the
  resume that follows it) each become an event, as does each `## Driver rulings` bullet, once, the
  first time it takes effect ([run-loop.md](run-loop.md)), and a scratch clone the driver left for a
  `github:` Target. **Each loop renders when it stops, for whatever reason, and when it
  completes**, and the driver once more before it dispatches the doc phase, so that a run that
  stalls there leaves a report that can be read, and once after the wrap-up. The run header is
  written by `render` from `state.json` (run window, phases planned/appended, bail-outs, test
  rounds, doc phase outcome); `/dev:run-slice` renders again once `slice_cost.py --write-state`
  has added the `cost` block, with the brief's `step` (`render --step`).
- **the wrap-up** — strikes for what it fixed, corrected labels, card requests, the proposal
  of a risk that has none, and what it left ([below](#the-wrap-up)).
- **the run's continuation** — what Pilot's answers say (`absorb`), what it did on them (`rule`),
  and the close ([below](#the-continuation)).

**Reading the report is never a license to act on it.** Phase agents append only — otherwise
the report becomes a new source of scope bleed, a writer "fixing while here" what an earlier
phase reported. Reconcile is the completion consult's; render is the loops'; fixing what the
table sends it is the wrap-up's, and only that; ruling is the operator's. A strike is for
whoever resolved the entry — the consult for what a phase resolved, the doc-writer for what its
own commit did — and records work that was the striker's to do anyway; it never licenses the
work.

## The wrap-up

What the table gives the wrap-up is worked on by one agent, `dev:wrap-up` — called the wrap-up,
never a sweep: the run loop has its gate sweep. It does what
the operator used to ask for by hand, "fix inline please": it fixes what is decided and safe,
asks for a card where a likely problem is more than it can fix responsibly, and the rest stays
closed. [Its definition](../agents/wrap-up.md) holds its bar and what it does entry by entry.

**It is the one exception to "append only".** For the entries the table sends it, and for
fixing alone, the report is a license to act, before the operator has ruled. Nothing else is:
what the table closed stays live until the report is closed, what comes to the operator is
theirs, and no card is filed without their word.

| it finds | it writes |
|---|---|
| a dated note says the run fixed the entry, and the commit is there | a strike naming that commit |
| the change is within its bar | the edit, the gate, one commit for the entry, a strike naming it |
| the label said one edit and the code says otherwise | the label corrected, with a note of what it found (`relabel`) |
| a likely problem it cannot fix within its bar | a card request: the entry restated as the card — what it would say, how the problem is reached, what the fix takes (`restate`) — and the line Agree files it on (`propose --card`) |
| an edit within its bar that a rule of the project makes only on the operator's word — a decision record, its `CLAUDE.md` | a request for their word: the entry restated as the exact edit and the rule (`restate`), and the line Agree makes it on (`propose --word`) — the entry comes to the operator; the edit is not made |
| a trigger or an impact the author could not tell | the label, from the code |
| an entry without labels | its labels, from its text |
| input for a slice still unplanned | the entry appended to that slice's `slice.md` (`fold`), and a strike naming the slice |
| a close that rests on one label, on an entry that breaks a flow | that label checked in the code — its trigger, or its signal — and corrected where the code says otherwise |
| a closed entry that someone other than the wrap-up noted after the table closed it | its labels checked against the note, and corrected where the note shows them wrong (`relabel`), else that it left it, and why (`note --left`) |
| a risk that comes to the operator | a proposal, where its author gave none or the code says otherwise (`propose`); what the code shows — how it is reached, what a fix takes — in its section (`restate`); what it checked as its mark (`note --left`); the entry stays theirs |
| an entry that comes to the operator, and what it found changes its story — a claim fixed since, a reach wider than its author saw | the entry restated as it now stands (`restate`), and what it ran as its mark (`note --left`) |
| a gate that goes red on its fix | the fix taken back, and a card request or a note that says so |
| anything else it looked at and does not change | that it left it, and why (`note --left`) |

**The wrap-up changes facts, never routes.** What it finds in the code it writes as a fix, a
corrected label or a card request, and the table routes again. Every entry it was given ends
with one mark — a strike, a card request, a request for the operator's word, or that it was
left; on an entry it was given for a
look or a recheck, a corrected label that routes the entry away from the wrap-up is its mark, with no note
after it. `close_out.py worklist` names what still waits. An entry the operator has ruled on is theirs, whatever its route, and does
not wait for the wrap-up.

**No reviewer reads what it fixes.** A review of its diff would write advisory findings, those
are entries, and entries go to a wrap-up: the loop has no end, and fix rounds resolve blocking
findings only ([run-loop.md](run-loop.md)). Its assurance is its bar, the gate, and one commit
per entry — each can be read and taken back on its own.

**One caller, at the run's end.** The driver dispatches it after the doc-writer's session and
lands what it committed with the doc phase; it never fails a run ([run-loop.md](run-loop.md)
§ After the last phase). It runs before the run's last render, so no entry waits for a wrap-up
nobody dispatches: an entry it did not reach comes to the operator in the document, said as what
it is — an entry nobody looked at.

## Writing an entry

An entry's words are written under `/dev:writing`
(`${CLAUDE_PLUGIN_ROOT}/skills/writing/SKILL.md`): its headline, its proposal or its options and
its `Consequence:` are the lines the operator rules from, and the body is what a question about
the entry, the wrap-up and the card an entry may become work from. Those have only the store, so
the body quotes what they will need: the sentence that is wrong, the command and its output, the
file and the quoted line, never its number ([spec-tree.md](spec-tree.md) § Citing a line, which
the CLI enforces). Three rules are the store's own:

- **`Provenance:` opens with the claim's class** — `witnessed`, the author ran, measured,
  reproduced or mutated it and the command, the output or the probe is in the body, or `read`,
  inferred from code or text — then the author, phase and round. A strike's reason names the
  commit and what was re-run the same way.
- **One entry per thing, not per turn.** A later observation about an entry that already exists —
  its premise moved, its symptom was re-tested, a phase resolved it, a reviewer refuted it — is
  `close_out.py note <close-out.md> <id>`: a dated paragraph under that entry, never a new
  entry. Everything about B1 is under B1, in the record; what the operator reads in B1's section
  is the wrap-up's to bring up to date (`restate`).
- **In doubt, add it.** Nobody pre-dedups: every agent runs `list` before it writes, the
  completion consult strikes duplicates it is sure of, the operator merges the rest by reading.

## The continuation

The run's continuation is the run-slice session resumed once Pilot has written the document's
answers back ([pilot.md](pilot.md) § The continuation). It reads them into the store
(`close_out.py absorb`): each block's answer lines become its entry's ruling, verbatim. An
answer `deferred` closes its entry as Pilot's, its `to` named, and nothing is kept to bring it
back; an action's `done` is what was done on it, which closes it. Then the session carries out
every other ruling, records what it did (`close_out.py rule <id> --did "…"`, `--commit` where
there is one), which closes the entry, and closes the report.

- **The operator's words travel verbatim**, quoted wherever the ruling is restated, never
  paraphrased or completed; a ruling Pilot chose (`by: agent`) is marked so on everything it
  produces.
- **A word of assent is a ruling for the proposal** — "agreed", "ok", "do it": carry out the
  proposal as it stands, and what you record as done names it.
- **`card [project]`** — one tracker card per entry, parented to the brief's ticket, in the
  named project, else this one: the card is the section the operator agreed to, as
  `close_out.py show <id> --card` prints it — its first line the title, the rest the body —
  then the report's path. Entries that are one
  fix are one card. Actions the operator wants carded go together, on one card in their action
  queue: a list they work from, not a card each.
- **`fix now`** — made here only where the project's `CLAUDE.md` classes the change as ad hoc
  work.
- **`fold into <slice>`** — `close_out.py fold <id> --into <slice>` appends the entry verbatim as
  an ask to that slice's `slice.md` and stages it; commit it, then record it. It refuses a slice
  planned or running, whose run never reads `slice.md` again.
- **`close`** — nothing to do but record it; the operator's reason is part of their words.
- **An owed-after action, done** — `close_out.py settle <Vnn> --verdict pass|fail --evidence
  "<their words, or what you observed>"` per criterion, which writes it into
  `verification.json`; a hold's action lists every criterion its push owes.
- **What cannot be carried out as ruled** — a `fix now` no rule allows, a fold into a running
  slice — is a new document with the alternatives as a decision, never a quiet substitute.
- **Neither `close-out.json` nor `verification.json` is edited by hand.** At the end,
  `close_out.py close` closes every entry still live, but one whose ruling nobody carried out;
  `render` writes the record under the answered asks; the session commits the store and the
  record by name.

**A question about an entry** — Pilot's clarification turn, or the operator's in chat — is
answered from the entry's body and `Provenance:` (`close_out.py show`), as `/dev:writing` has a
question back answered.

## Lifecycle

1. The plan loop creates the store at its first dispatch; planning agents append; the loop
   seeds the actions the plan already owes at its exit 0, and renders.
2. The run loop creates it if planning did not, appends throughout; the completion consult
   reconciles; the wrap-up works on what the table gave it, after the doc-writer and before the
   render the run completes with — in a project with no doc phase the ladder starts at it — so
   the close-out a run registers always comes after it, and an entry it did not reach, its
   session left out, renders as that. The driver renders before the doc phase, after the
   wrap-up, at every stop — the record of a run not over, which nobody registers — and when the
   run completes, and `/dev:run-slice` once more after the cost block lands. At the run's end
   the driver removes a scratch clone it left for a `github:` Target when its tree is clean,
   it holds no stash and every commit on its branches is on a remote, and says so under the
   clone's event; otherwise it says what it found and leaves it.
3. `/dev:run-slice` registers `close-out.md` with Pilot, attaches the record and the rest of
   the slice's evidence, and ends its turn. With no ask, there is nothing to register, and the
   continuation's end runs at once: the report closed, the record rendered and committed, the
   slice's card done.
4. Pilot's pass pre-rules what it can, the operator answers the rest, Pilot writes the answers
   back, and the continuation carries them out ([above](#the-continuation)); it moves the
   slice's card to done ([pilot.md](pilot.md) § Cards). Git in the spec repo holds the history.

Deliberately absent: dedup tooling (`render` orders, it never merges); a table of a project's
own, or a switch on any part of the routing or on the wrap-up — the policy is one and the
operator's; a reviewer for what the wrap-up fixes; a list, a summary or a ranking written over
the entries by anyone; a take-back of a write; and a deferral of the workflow's own — Pilot
defers.
