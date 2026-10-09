# The close-out report — one record per slice for everything out of the loops' scope

Every plan and run agent puts what it notices but the loops will not act on in the slice's
close-out report: a bug it will not fix, a keystroke only the operator can make, an event that
deviated from an uneventful run, a choice that is the product owner's, an improvement. The
author of an entry says what it is, in labels the tool checks; a table in the tool routes the
entry from those labels — to the operator, to the wrap-up, closed, or to the record; the
operator reads what comes to them and rules on it; the `close-out` skill executes the rulings.
Nothing from a run is carded per finding — the loops' only tracker output is one card per slice
pointing at the report.

**The record is `<slice>/close-out.json`; `<slice>/close-out.md` is rendered from it**
([close-out-template.md](close-out-template.md) has both shapes). An entry is data for its
whole life, from the plan loop's first append to the operator's last ruling, and the report is
what the operator is shown of it: each entry's ask — its headline, its proposal and its
consequence — with the body, the newest note and the evidence they need to rule on it.
`${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` is the one pen:
it writes every author's entries (`append`), notes (`note`) and strikes (`strike`), the
corrections of a label (`relabel`) and of a proposal (`propose`), what the wrap-up asked for and
left (`request-card`, `leave`), the operator's rulings (`rule`), prints an entry in full
(`show`), renders the report and counts it. Both
loops import it, and every dispatch names it beside the report's path — which the tool takes as
its positional, the slice directory or the report itself, so the first call works — with
the labels each kind carries and how they pair, from the tables `append` refuses by, and the
arguments of `append`, `note` and `strike`, rendered from the tool's own parser
(`close_out.verb_usage`), so no `--help` turn or refused call is spent. No agent edits either
file by hand. The `Disposition:` lines of `close-out.md` are the operator's, and the one thing
in that file that is read back; everything else in it is overwritten by the next render.

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
| `for` | a slice, optional | the slice still to run that should take the entry, by its number |

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

**Where the line is drawn:**

- **Wrong today, or better tomorrow.** A defect, prose and a test gap say that something should
  be fixed; an improvement says that something could be better, safer or simpler. A hardening
  against what cannot occur with the code as it is, and a cleanup, are improvements.
- **A decision asks its question.** Its headline is the question; its body opens with what was
  chosen and whether it has shipped, then lists the options, one line each, the one in effect
  marked, each with what switching to it would cost — a revert, a migration, a changed contract,
  work redone. `Consequence:` is what is experienced while the choice in effect stands, as for
  every kind; the costs of the other options are on their lines. An account of what the writer
  did, with the alternatives somewhere in a paragraph, is not a decision — the operator reads
  it and has to ask "what's the decision?" — and an entry that ends in "the operator's call" is
  what it was before that sentence. A ratification — a change already shipped, with no
  alternative but undoing it — says so in its first line, and its options are keep and revert.
- **An action is one thing to do, and nothing waits on a notice.** Its headline is the
  imperative, and its author can say who waits on it — a criterion, a push, the run. An "if"
  makes it a decision. A fact nobody has to act on — a surface that changed, a step that was
  taken, a convention the slice kept — is not an entry: what an owner might want to rule on is
  a decision put to them, the rest is nothing. An action whose `Consequence:` is none is a sign
  the kind is wrong.
- **An improvement asks for its change.** "Quiet the MCP SDK's INFO lines in the mcp log?" is
  the headline; "the SDK's lines outnumber ours" is the body's first sentence.
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
in a sentence or two, in a ruling's words — card · fix now · fold into <slice> · close · do it
(`append --proposal`). The operator reads it with the headline and the `Consequence:` line and
nothing else, so that one word back is a complete ruling: it is the reasoning they would
otherwise redo. An action, a decision and an improvement carry one from their author, and the
tool refuses them without. A defect, a test gap or prose may carry one, and gets the wrap-up's
where the table brings it to the operator — a card request is the proposal (`request-card`); a
risk gets one where its author gave none or the code says otherwise (`propose`). A proposal is
a recommendation, never a route: the table decides who sees the entry, the operator what
happens to it.

**The tool refuses**, naming the flag, so that the author corrects in one turn:

- an action, a decision or an improvement without a proposal;
- an entry without the labels its kind carries;
- an impact other than `none` over a `Consequence:` that opens with "none", and the reverse;
- a `for` that names no slice that is still to run;
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
| 4 | input for a slice that is still to run | to the wrap-up, to fold into that slice |
| 5 | fixable only in a repository the slice did not touch | to the operator as a card request when it shows and has an impact as row 8 says, or is `severe` or graded major; closed otherwise |
| 6 | prose; or fixed by one edit or in several known places, outside a sensitive area | to the wrap-up, to fix |
| 7 | anything else, with a trigger or an impact `unknown` | to the wrap-up, to look |
| 8 | anything else that has an impact and shows in normal use, or on an ordinary condition and is not `loud` | to the wrap-up, to fix within its bar or to ask for a card |
| 9 | anything else that is `severe`, or graded major | to the operator, as a risk |
| 10 | anything else: it needs a fault or a future change, it is `loud` on an ordinary condition, or it has no impact | closed |

An improvement takes the first of these that fits:

| | an improvement that | goes |
|--:|---|---|
| 1 | is input for a slice that is still to run | to the wrap-up, to fold into that slice |
| 2 | adjusts or removes, in one edit or in several known places, and is no product call | to the wrap-up, within its bar. In a repository the slice did not touch: to the operator as a card request when it prevents something `severe` or is graded major, closed otherwise |
| 3 | adds something, for a benefit that is not felt in use, and prevents something `severe` or is graded major | to the operator, as a risk |
| 4 | adds something, for a benefit that is not felt in use | closed |
| 5 | is anything else — a product call, a change that needs design or a look first, an addition felt in use | to the operator |

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
- **Whether the slice touched a repository** is read from the run's record — the roots of the
  phases in `state.json`. Without a run record every repository is taken as the slice's own.
- **An entry without labels** — a report written before the labels existed — has no route. It
  waits, in a section of its own, until it is labelled.

**A card request** is an entry that comes to the operator with a card asked for: by the table
where the fix lives elsewhere (row 5), by the wrap-up where a likely problem is more than it
can fix responsibly (row 8). Nothing is filed before the operator's word.

## The report

`close-out.md` is written for the operator and for nobody else, in the order of what is asked
of them ([the template](close-out-template.md#the-report) has the sections). An entry that
comes to them — the actions, the decisions, the risks, the improvements that are theirs to
weigh, the card requests — is shown as its ask and what they need to rule on it without the
store: the heading, the body as its author wrote it, what is proposed (`**Proposal:**`), what
it costs (`**Consequence:**`), the newest note (`**Latest**`), the labels in words
(`**Triage:**`), who found it on what evidence (`**Provenance:**`), where the table sent it and
why (`**Route:**`, where it says more than the kind), and the line they write on
(`**Disposition:**`). The older notes are the store's. What the table closed follows as its
heading, its consequence where it says more than none, its labels, its evidence and the ground
of the close, so a close they do not agree with can be pulled back from one line; the record
is headings, a struck entry's with its reason up to the first `; `. An id on
every entry lets a ruling name it in one line ("card B1, close B6, fold I1 into 009"), and the
run's shape is stamped at the top.

There is no list at the head of the report and none in the body of the close-out card: the
report is its entries. The operator reads an entry and rules, or sends a session to dig; an
entry has to stand without the store behind it, and the page carries what that takes,
never a summary written over it.

`close_out.py show <id>` prints an entry in full — body, every note, labels, marks — and is how
the wrap-up, the close-out session and a card filing read one. `close_out.py list` is the view
an agent takes before it appends: ids, headlines and Consequence lines, without the bodies.

## Who writes what, when

Both loops create the store if it does not exist — the plan loop first, so planning can already
write to it. All agents may append, through `close_out.py append` (`list` first shows what is
already there); an agent commits the store with its own commit, staged by name like every other
slice-folder artifact. The rendered report is committed by whoever rendered it, the store with
it.

- **plan-writer / plan-reviewer** — out-of-scope observations about the spec or the estate;
  events during planning. Their in-scope findings and questions keep their existing routes (the
  review file, the `questions` verdict, the interactive session). An action only the operator can
  take that the run needs *before* it starts — a push the plan's tools wait on, a pod restart —
  is an action whose headline begins `Before /dev:run-slice:`; the run loop refuses to start or
  resume while one is live ([run-loop.md](run-loop.md) § Protocol invariants).
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
  to say about an entry is a `note`. It edits nobody's text.
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
  `github:` Target — the close-out session removes it, nobody is asked; on a phase that targets the
  spec repo, an agent's append left uncommitted is committed onto the phase branch before the driver
  leaves it. **Each loop renders when it stops, for whatever reason, and when it completes**, and
  the driver once more before it dispatches the doc phase, so that a run that stalls there leaves a
  report that can be read, and once after the wrap-up. The run header is written by `render` from
  `state.json` (run window, phases planned/appended, bail-outs, test rounds, doc phase outcome);
  `/dev:run-slice` renders again once `slice_cost.py --write-state` has added the `cost` block.
- **the wrap-up** — strikes for what it fixed, corrected labels, card requests, the proposal
  of a risk that has none, and what it left ([below](#the-wrap-up)).
- **the close-out session** — the proposal of an entry that comes to the operator with none,
  the operator's rulings, in their words (`rule`), what it did on them, and the closing of the
  report ([the lifecycle](#lifecycle)).

**Reading the report is never a license to act on it.** Phase agents append only — otherwise
the report becomes a new source of scope bleed, a writer "fixing while here" what an earlier
phase reported. Reconcile is the completion consult's; render is the loops'; fixing what the
table sends it is the wrap-up's, and only that; ruling is the operator's. A strike is for whoever resolved the entry — the consult for what a phase resolved,
the doc-writer for what its own commit did — and records work that was the striker's to do
anyway; it never licenses the work.

## The wrap-up

What the table gives the wrap-up is worked on by one agent, `dev:wrap-up` — called the wrap-up,
never a sweep: the run loop has its gate sweep and the plugin the residual sweep. It does what
the operator used to ask for by hand, "fix inline please": it fixes what is decided and safe,
asks for a card where a likely problem is more than it can fix responsibly, and the rest stays
closed. [Its definition](../agents/wrap-up.md) holds its bar and what it does entry by entry.

**It is the one exception to "append only".** For the entries the table sends it, and for
fixing alone, the report is a license to act, before the operator has ruled. Nothing else is:
what the table closed stays live until the operator closes the report, what comes to the
operator is theirs, and no card is filed without their word.

| it finds | it writes |
|---|---|
| a dated note says the run fixed the entry, and the commit is there | a strike naming that commit |
| the change is within its bar | the edit, the gate, one commit for the entry, a strike naming it |
| the label said one edit and the code says otherwise | the label corrected, with a note of what it found (`relabel`) |
| a likely problem it cannot fix within its bar | a card request: how it is reached, what the fix takes (`request-card`) — it becomes the entry's proposal |
| a trigger or an impact the author could not tell | the label, from the code |
| an entry without labels | its labels, from its text |
| input for a slice that is still to run | the entry appended to that slice's `slice.md`, and a strike naming the slice |
| a close that rests on one label, on an entry that breaks a flow | that label checked in the code — its trigger, or its signal — and corrected where the code says otherwise |
| a risk that comes to the operator | a proposal, where its author gave none or the code says otherwise (`propose`), and what the code shows under it (`leave`); the entry stays theirs |
| a gate that goes red on its fix | the fix taken back, and a card request or a note that says so |
| anything else it looked at and does not change | that it left it, and why (`leave`) |

**The wrap-up changes facts, never routes.** What it finds in the code it writes as a fix, a
corrected label or a card request, and the table routes again. Every entry it was given ends
with one mark — a strike, a card request, or that it was left; `close_out.py worklist` names
what still waits. An entry the operator has ruled on is theirs, whatever its route, and does
not wait for the wrap-up.

**No reviewer reads what it fixes.** A review of its diff would write advisory findings, those
are entries, and entries go to a wrap-up: the loop has no end, and fix rounds resolve blocking
findings only ([run-loop.md](run-loop.md)). Its assurance is its bar, the gate, and one commit
per entry — each can be read and taken back on its own.

**Two callers.** The driver dispatches it at the end of the run, after the doc-writer's
session, and lands what it committed with the doc phase; it never fails a run
([run-loop.md](run-loop.md) § After the last phase). The close-out session dispatches it for a
report whose entries still wait — a run that stopped before its end, a wrap-up the driver left
out, a report an older plugin wrote — presents what comes to the operator meanwhile, and the
card requests when it has returned. There its commits land as a `fix now` of the session
lands.

## Entry rules

- **The ask leads the entry and stands alone.** The headline, the proposal and the
  `Consequence:` line are what the operator rules on — write the three so that one word back is
  a complete ruling, and so that none of them needs the body to be understood. The body is on
  the page with them, and it is what the session they send to dig, the wrap-up and the card
  an entry may become work from; those have only the store, so quote liberally there: the
  sentence that is wrong, the command and its output, the file and lines. Provenance ids
  (`P3 r1 F3`, `V10`) belong on the `Provenance:` line, not in the body as load-bearing
  references.
- **`Consequence:` is a line of its own, written for triage.** What an operator or user actually
  experiences if the entry stays as it is — unfixed, undone, unanswered; for a decision, while
  the choice in effect stands — in the deployed shape,
  in plain words, with what has to happen for it to be reached; or `none`, said plainly. It is the
  stated consequence `/dev:triage` puts to the operator, who reads it the same way, so it is not
  "better than before", not "none to behaviour" when a human would notice something, and not a
  restatement of the mechanism the body already gave. A body that leaves the reader asking "what
  is the risk in a real environment?" has an entry without a consequence, however long it is.
  The labels say the same in the tool's words, and the tool holds the two against each other.
- **Every claim carries its evidence class.** `**Provenance:**` opens with `witnessed` (the author
  ran, measured, reproduced or mutated it — the command, the output, the probe are in the body)
  or `read` (inferred from reading code or text). The body leads with the symptom and states a
  cause only where it was shown: symptom claims hold up, cause attributions are the half that does
  not, and a reader deciding what to trust needs the class before the body. The same holds for
  a strike — resolved, refuted, does-not-reproduce names the commit and what was re-run.
- **No limit on prose, no limit on count — and no filler.** Long sections are fine; a cap produces
  more, not less. Length is what the body needs, and the page shows it whole beside the ask. A
  proposal that restates the headline, or a consequence that restates the mechanism, leaves the
  ask nothing to rule from and sends the operator into the body for what that line should have
  said.
- **One entry per thing, not per turn.** A later observation about an entry that already exists —
  its premise moved, its symptom was re-tested, a phase resolved it, a reviewer refuted it — is
  `close_out.py note <close-out.md> <id>`: a dated paragraph at the end of that entry's body,
  never a new entry.
  The reader who decides on B1 finds everything about B1 under B1.
- **In doubt, add it.** Nobody pre-dedups: every agent runs `list` before it writes, the
  completion consult strikes duplicates it is sure of, the operator merges the rest by reading.
- **The grade** is for an entry of any kind that has one: `major` (a wrong result or a broken
  flow, unfixed) · `minor` (a real defect with a contained consequence) · `nit` (true, no
  practical consequence today) · `cosmetic` (no behavioural or informational consequence — a
  stale line pointer). The reviewer's own Blocker/Major/Minor never reaches the report: a
  Blocker gets fixed.
- **`Disposition:` is the operator's line.** Free form; a suggested vocabulary is `card [project]`
  · `fix now` · `fold into <slice>` · `close` · `defer`. They rule there or in the close-out
  session, as it suits them: the session records what they say with `close_out.py rule`, in
  their words and never edited, and reads what they wrote in the file back by the entry's id
  before it executes anything. What it then did — a card id, a commit, the slice folded into —
  is recorded after their words. A struck entry needs no disposition: its fate is the reason on
  its heading.

## Lifecycle

1. The plan loop creates the store at its first dispatch; planning agents append; the loop
   seeds the actions the plan already owes at its exit 0, and renders.
2. The run loop creates it if planning did not, appends throughout; the completion consult
   reconciles; the wrap-up works on what the table gave it, after the doc-writer; the driver
   renders before the doc phase, after the wrap-up, at every stop and when the run completes,
   and `/dev:run-slice` once more after the cost block lands.
3. `/dev:run-slice` files **one** tracker card — `[NNN] close-out: <slice title>`, in the intake
   queue, carrying the **close-out** mark, related to the slice's card — whose body is the
   report's path and its entry counts. That card is the "a report is waiting" marker, never an
   ask (`/dev:triage` reads the report it names, not the card); nothing else from the run is
   carded.
4. The close-out session dispatches the wrap-up when entries still wait for it. The operator reads
   what comes to them and rules. The `close-out` skill (or an ad hoc session following it) executes:
   `card` files a tracker card with the entry in full (`show`) as its body, `fix now` does the small
   thing and strikes the entry with the commit, or bails to a slice, `fold into` appends the entry
   to that slice's `slice.md`, `close` strikes, `defer` leaves it — then renders. Git in the spec
   repo holds the history. **The card's closure is the report's.** The operator does not treat a
   blank `Disposition:` as pending work, and a report is never a queue they work from: when they are
   done with it the report is closed (`close_out.py close`), the close-out card with it, and every
   entry still live is closed by that act — what the table closed among it, which stays live until
   then. `defer` is the one word that keeps the card open.
5. While the card is open, `/dev:triage` reads the report it names — the `defer` entries and
   what came to the operator and is not ruled — one item per entry. A finding that deserves a
   life of its own gets there by a `card` disposition, never by the report sitting unread.

**A report written before the store existed** is imported by the first call of the tool that
finds a `close-out.md` and no store beside it (`close_out.py import` does only that): its
entries keep their ids and have no labels.

Deliberately absent: dedup tooling (`render` orders, it never merges); a table of a project's
own, or a switch on any part of the routing or on the wrap-up — the policy is one and the
operator's; a reviewer for what the wrap-up fixes; and a list, a summary or a ranking written
over the entries by anyone.
