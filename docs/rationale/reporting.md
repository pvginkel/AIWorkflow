# From per-finding cards to the close-out report

Why the loops stopped filing a tracker card per finding and started writing one document per
slice, what that document's shape is for, what the first forty-one reports show, and why the
entries are since 0.9.57 labelled by their authors and routed by a table. The
report's contract — the labels and the routes, who writes what, the entry rules, the lifecycle — is
[`plugins/dev/docs/close-out.md`](../../plugins/dev/docs/close-out.md) and its shape
[`close-out-template.md`](../../plugins/dev/docs/close-out-template.md); this doc does not
restate them. The papers behind the design are in [`literature.md`](literature.md), the
generation bar's place in the run loop in [`overview.md`](overview.md), and the report's
entries in the improvement catalogue in [`improvements.md`](improvements.md).

## What carding looked like, and why it broke

Until plugin 0.4.5 the loop's reporting surface was the issue tracker: every agent that noticed
something out of its scope put it in its verdict's `cards` list, the driver funnelled those into
`state.json["cards"]`, and the launching session filed a tracker card per item at close-out. The
rule set existed to *limit* that stream — the code-writer's verdict asked for findings "worth an
issue-tracker card", the test-agent had a "no fix proposals" rule, the run loop said "a card must
never cost the operator more to triage than the fix costs to make", and the completion consult
carried an "already carded this run — settled, do not re-report" list
(`../research/close-out-report.md` § 6; the v0.5.0 entry in
[`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md)).

The exhibit is Ansible slice 007 (2026-08-14), read card by card with the operator the next day
(`close-out-report.md` § 1.1; **measured**). The run collected eleven entries from five sources —
code-writer P2, P3 twice, P7 twice, four consults, the test-agent, the doc-writer — and filed ten
cards (615–624). The tally: one must-act (an operator runbook whose body said "full detail in the
slice's `attachments/credential-inventory.md`", so it did not stand alone), one real
cross-project bug, one ruling request, one card **already fixed inside the same run** (consult 1
had absorbed it into an appended phase that landed as AnsibleSpecs `97b5313`, and nothing struck
the entry — stale on arrival), and six minor, nit or doc items. The card texts were competent;
the cost was ten board items to open, order and relate to each other, with no severity and no
whole-run context. It was not a 007 thing: KubeCoderSpecs runs had produced 24 (slice 117), 17
(135), 16 (107), 15 (109) and 13 (125) card entries each, the completion consult the largest
producer everywhere (§ 1.2).

Two structural defects sat under the counts (§ 1.3–1.4). Cards were decided in five places, each
with its own phrasing of the rule and blind to the others, and the one agent with the whole-slice
view — the completion consult — made absorb/strike/merge decisions that never fed back into the
list. And nothing recorded *what happened* in a run except `log.txt` (169 KB for 007): the run's
bail-out on a commitless sibling repo (a plugin bug), a proof venue moved by operator ruling, a
live check that exposed what the test double hid — none of it was on any card.

The operator's own reading, 2026-08-15 (**ruled**): "I feel like I've been trying to suppress
this and I'm frustrated it doesn't work" (§ 2).

## The report's design

The design note (`../research/close-out-report.md`, written 2026-08-15 at plugin 0.4.5,
catalogue entry C7 in `../research/interventions.md`) separates two decisions the old rule set
had asked every agent to make, and removes both.

**Routing.** An agent that noticed something out of scope had to choose: card it, append a phase,
fix it in place, leave it to the consult, mention it in the summary. Now there is one
destination — the slice's `close-out.md`, created at planning and written by every agent as it
goes — and the operator routes.

**Completion.** An open-ended instruction ("card things worth carding") has no closure
criterion. The fixed entry shape turns "what do I do with this?" into a fill-in-the-blank whose
completion is visible: writing the entry *is* the licensed act. The mechanism comes from three
papers — Fan et al. on models that detect a problem and then keep re-visiting it instead of
abstaining, Wu et al. (ProCo) on verification against a specific slot converging where open-ended
critique regresses, and Han et al. (TALE) on numeric caps producing *more* output rather than
less, which is why the report has no limit on prose or count (§ 2; the readings are in
[`literature.md`](literature.md)).

Until 0.9.57 the report had six sections, one per kind of entry, and two of them are worth the
why; both live on as kinds. **Notable events** existed so that workflow deviations — a bail-out,
a blocked proof re-routed, a tool missing from the sidecar — surface in the report rather than
only in `log.txt` (H4 below). **Outstanding actions** was the operator's addition on 2026-08-15:
"a runbook for the operator to complete" (§ 8).

The entry closed with three bold labels, each added when a read showed the gap; 0.9.57 put two
lines of the tool's between them, `**Triage:**` and `**Route:**`
([below](#triage-at-the-source)):

- `**Consequence:**` (v0.5.3, 2026-08-17). The template had put the consequence inside the
  body's placeholder prose, and six finished reports showed authors treating it as prose: two
  slices wrote a `Consequence:` paragraph on most entries, one wrote the template's own phrase
  "Why it matters:", one labelled nothing, and the entry the operator called "very dense" (155 B2)
  had a consequence line that said what the code did rather than what a real environment risks.
  The label is chartered for triage — what an operator or user actually experiences if the entry
  stays as it is — because it is the line the operator scans for and the line `/dev:triage`
  rules on.
- `**Provenance:**` opening `witnessed` or `read` (v0.5.4, same day). The entries later refuted
  or overtaken (156 B4's first bullet, 157 B1) and the dense one (155 B2) were all read rather
  than witnessed, and said so only in prose. The papers gave the shape: in the overcorrection
  study 87 % of the false-rejection mass is claims with no falsifiable counterexample, symptom
  claims hold at 93–100 %, cause attributions at 44–75 %. So the body leads with the symptom,
  states a cause only where shown, and a strike is a claim like any other — it names the commit
  and what was re-run.
- `**Disposition:**` — blank, the operator's line, free form. The only thing written into the file
  in words rather than through the tool, and since 0.9.57 the only thing read back from it.

The design note stated its hypotheses in advance (§ 7): **H1** cards per slice created by the run
10 → 1, trivially true by construction, the real number being cards the operator files at
disposition; **H2** fewer generation-1 appended phases and a lower rework share, because agents
stop resolving "what do I do with this?" by doing it (baselines: 007 appended 3 phases at 13.8 %
rework; KubeCoder 149–153 at 9.3–15.7 %); **H3** the operator processes a report in one sitting
without opening other files; **H4** workflow defects surface as entries. The kill signal: reports
that are long *and* the operator stops reading them — answered by a better Focus line or a
section split, never by a cap.

`../research/close-out-plan.md` records the fourteen operator decisions of 2026-08-15 so a fresh
session does not relitigate them (no JSON, no YAML, no tables; no pre-dedup; no validation beyond
the section headings; the doc-writer writes Summary and Focus lines; automated triage is the end
game, not now) and, in its header, where the build departed from the plan the same day. The
operator reversed three of them on 2026-09-29, with 99 reports read: the record is JSON, the
Summary and the Focus lines are gone, and the triage is automated — at the source.

## The generation bar, re-priced

The report changed the economics of the loop's one other outlet for leftover work: appending a
phase. Under carding, the completion consult's first-generation bar read "absorbed beats carded",
written when the alternative to a phase was a tracker card the operator had to open and relate to
nine others. The first slice run end to end on 0.5.0 (KubeCoder 146) showed the bar was now
mispriced: consult 1 appended a phase for a test-durability nit — $4.02 with the consult it
forced, 8.7 % of the slice — reasoning "cheaper to fix than to card", a comparison 0.5.0 had
deleted (`../research/status.md` C7, 2026-08-15 log line; **measured**).

v0.5.1 re-priced it in the consult's own prompt: a phase costs an executor round, a review round
and the consult the generation forces; a close-out entry costs the operator one word. Generation 1
appends only work the plan *owes* and no phase delivered; generation 2 blocking work only; a third
pending generation bails to the operator (`GENERATION_BARS` in `plugins/dev/tools/run_loop.py`;
the rule in [`run-loop.md`](../../plugins/dev/docs/run-loop.md) § The generation bar). The
six-report read of 2026-08-17 counted zero generation-1 appended phases in six runs
(`status.md` C7).

## The tool is the only pen

0.5.0 shipped `close_out.py` for the driver's own entries and left every agent to type its entries
off the shape in the file. Two reads showed why that could not stand.

On 146 the shape did not hold at all (v0.5.1): no entry carried an id, `Provenance:` or
`Disposition:`, because every register said "the shape is in the file" and `init` had written a
file holding section charters only — the first author wrote freehand and every later one read the
file and copied the precedent. `counts` read zero for a six-entry report, and the consult
*deleted* the two entries it absorbed instead of striking them. The fix put the
entry shape into the template's head comment.

On the six reports of 2026-08-17 (v0.6.0) the shape held but the authoring did not: the shape
drifted wherever the head comment was read loosely, each author read the whole file — 42 KB by
the doc phase of a long slice — to add one entry, the completion consult reconciled by editing
other agents' text in place, and struck entries stayed where they arrived. In slice 154, 10 of the
16 Bugs were struck in-run and sat, full-bodied, ahead of the six the operator had to decide on.
"Scripts drive, agents judge — the shape is mechanical, the content is judgment": `close_out.py`
became the only pen. `append` mints the entry with its three labels (and requires a consequence),
`note <id>` adds a dated paragraph to an existing entry so a later observation never becomes a
second entry, `strike <id>` rewrites the heading to the struck form and touches nothing else,
`list` is the triage view without bodies, `render` puts each section in reading order — live
entries first, Bugs by severity, struck entries last with their bodies folded into a `<details>`
block — idempotently, `stamp` writes the run header from `state.json`, and `counts` reports the
smoke checks. Only the completion consult strikes, and only through the tool — until v0.9.56,
which lets the doc-writer strike what its own commit resolved whole: the doc phase runs after
the last consult, and 58 live entries in 25 reports had reached the operator already fixed
(`../research/close-out-read-2026-09-28.md`, finding 9). 0.9.57 kept the pen and changed what
it writes on: a store, from which the report is rendered ([below](#triage-at-the-source)).

Two later versions closed what the tool's own interface cost. The template's head comment still
spelled out the whole entry shape as if an author typed it, and had drifted from what the tool
minted — a `· <repo or component>` tail after the severity that `append` never wrote; v0.9.3
(2026-08-22) cut it to seven lines, the shape stated once in `close-out-template.md`. And the
turn taxonomy of the 32-slice corpus found the tool's positional was the single most fumbled
interface in the pipeline: every dispatch names the report's *path*, agents passed exactly that,
`close_out.py` wanted the slice directory, and the result was `list <report>` → failure →
`--help` → retry — 225 of the 1,248 fumble-and-retry turns counted, 188 of them on `list`
(`../research/context-profile-2026-08-23.md` § 13 "What is fumbled and retried"; **measured**).
v0.9.6 made any `.md` argument resolve to its directory; v0.9.9 went further for the doc-writer,
whose dispatch now carries the verbs it uses with their argument shapes rendered from the tool's
own parser (`verb_usage`), so no `--help` turn is spent and the block cannot drift from the CLI.

## Dispositions and the close-out skill

The operator rules on an entry in a line; the suggested vocabulary is `card [board]` · `fix now`
· `fold into <slice>` · `close` · `defer`, free form. The `/dev:close-out` skill
([`SKILL.md`](../../plugins/dev/skills/close-out/SKILL.md)) presents what the report brings
them and asks nothing, then executes: `card` files one tracker card with the entry verbatim as
its body, `fix now` does the small thing only if the project's own conventions class it as ad
hoc work, `fold into` appends the entry to a backlog slice's `slice.md`, `close` strikes,
`defer` leaves it for `/dev:triage`. A blanket ruling ("close the rest") is a `close` on every
entry that came to them and is not ruled. Two bounds carry the design's intent: the session
never edits the operator's words (what it did is recorded after them — a card id, a commit),
and when a ruling asks about a claim it answers from the entry's own body and Provenance rather
than agreeing (v0.5.4: a challenge flips 32–86 % of correct answers in Sharma et al.).

They rule where it suits them, in the session or on the `Disposition:` lines of the rendered
file: "In the beginning I sent most responses in session, but I do feel it's kind of nice to add
them on the disposition lines. It's in-context for me" (2026-09-29).

From v0.9.38 to v0.9.56 the skill carried a second way to process a report: the operator handed
over the triage and ruled once, on a sheet the session had sorted into buckets. The reports
read below show it was the habit before it was the skill's — "Please apply your suggestions",
"Apply your suggestions for the rest" — and what the session suggested came from rules the
operator had stated once, on slice 181's report (2026-08-30). The sheet went with 0.9.57. The
operator's own account of those rulings is that they were not their pattern: a third of the
time they had seen that there was little to progress, two thirds they were "doing the third or
fourth close out report in a sitting and I'm fed up with them". A sort learned from such
rulings learns the sheet.

The run's only tracker output is one card, `[NNN] close-out: <title>`, whose body is the report's
path and its entry counts; it is closed when the report is.

Triage got the same durable seam one stage earlier and one day later (v0.5.2, 2026-08-16): after
a run of 86 in-scope cards over two days, the rubric verdict — the skill's main product — turned
out to be the one thing it never persisted. Verdicts became tracker labels on the cards,
dispositions a stated vocabulary (`close` / `later` / `agreed` / `apply the suggested edit` /
`conditional: … if …` / `split` / `superseded by`), and the work two named halves a later session
can resume from the labelled board. Same idea: the operator's decision, recorded where the next
session finds it, in the operator's words.

The label half of that was withdrawn a month later (2026-09-17). The committed status document,
added in the same release, already held every verdict with its reasons, and nothing downstream
ever read the label: planning, the lane plan and the run loop work from `slice.md`, slice cards
never carried one, and intake cards are closed at dispose. The operator's ruling was that a
verdict is cheap to give twice, so the tracker carries none, and a later session resumes from the
committed document alone.

The document went the same way on 2026-09-30 (0.9.60). Read across the last twenty runs
([`../research/triage-read-2026-09-29.md`](../research/triage-read-2026-09-29.md)), it decided
almost nothing: of 181 items the operator wrote a bare "Agree" or nothing on 89 of the 109 that
carried no question, every substantive ruling answered a question or moved an item between fates,
the label predicted nothing about what was culled, and the slice scheme — the one thing the
operator steered in half the runs — was never in the document at all. The operator's own read:
"I hardly read them." What the document held is now one chat message: every item on one line
under its proposed fate, the questions numbered, the proposed slices with a phase estimate.
The rubric, the justification quotes, the `Note:` lines, the ruling vocabulary for labels and
`triage_verbatim.py` (which repaired what the operator's editor did to the document) went with
it; the collection, the standing-decisions check, the routes, the grouping rule, the sweep and
the filing are unchanged. The verbatim dump stays, as the archive `slice.md` quotes from.

## A report, read

Slice 190 (`/work/KubeCoderSpecs/slices/completed/190_fleet_state_under_faults/close-out.md`,
run on plugin 0.9.12, 2026-09-01) is a median-sized report. The driver's header:

```
Run: 2026-09-01 11:11 → 13:39 · 5 phases · 0 bail-outs · 1 test round · doc phase done · $71.56
(planner 22 %, research 3 %, rework 9 %)
```

The doc-writer's Summary is four paragraphs: one line of shape ("Four independent fault-handling
defects, one slice, five phases, each done in one round") and one paragraph per fix, each naming
the decision record it landed as. Its Focus lines do the ranking the operator would otherwise do:
Outstanding actions "nothing is owed", Notable events "nothing deviated", Bugs "**B2 first** — …
the only entry here with no self-repair", Suggestions "S1 and S9 are the two that would change a
decision".

Fourteen entries arrived: three Bugs (B1 minor, B2 major, B3 nit), one Question, ten Suggestions.
Twelve carry `read` provenance, two `witnessed` (S5, and S10 by mutation). Their sources show who
writes here: the code-reviewer (seven, its advisory findings from rounds that signed off), the
plan-writer (three, out-of-scope observations from planning), the plan-reviewer (one, from
grounding P2's citations), the code-writer (one, noticed while adding a method), and one the
consult resolved.

After the operator's pass the report reads, in rendered order:

- **Two live entries.** B2 — the bot's reconnect reseed reads a one-shot read fault as a
  departure and renders a false, permanent "Deleted" — carded; S9, the same shape at
  the other consumer of the same `None`, folded into B2's card.
- **Two fixed on the spot**, struck as `fixed by the operator's ruling` with the commit: S3
  (KubeCoder `d2b1b38c`) and S7 (KubeCoderSpecs `69ba4ed8`).
- **One struck in-run**: S6, a comment that credited a recovery the code cannot give, resolved by
  consult 1 as mechanical residue — the heading names the commit (`a034a55d`), that lint was
  re-run green and that the driver's sweep covers the new commit; its `Disposition:` is blank,
  because a struck entry needs none.
- **Nine closed by the operator**, each heading `— closed by the operator, 2026-09-01`, the reason
  staying on the `Disposition:` line: B1 (settled by CI — Build-Main #424 carried the tests and
  passed), B3, Q1, S1, S2, S4, S5, S8, S10.

Every `Disposition:` line begins "Please apply your suggestions — suggested <close | card | fix
now>": the session proposed a disposition per entry and the operator accepted the set in one
sentence, with the session's suggestion and its execution recorded after the operator's words.

Two contrasts. Slice 181 (14 phases, $293.03) is the largest report so far: 67 entries (43 of
them Suggestions), 33 closed in one blanket ruling on 2026-08-30 ("Apply your suggestions for the
rest"), the eight live entries every one carded (#746–#749 among them, two cards covering two
entries each), one struck as `superseded` by its own author during planning after a miscount.
Slice 195 (6 phases, $65.79, run finished 2026-09-01 22:38) is a report before the operator's
pass: thirteen live entries, nothing struck, every `Disposition:` blank — three Outstanding
actions that are the operator's sequence for bringing OIDC live on prd, nine Bugs of which eight
are nits, and one Suggestion that the plan contract and the project's doc plan disagree about
who writes a decision record.

## What the numbers say so far

The six-report read of 2026-08-17 (Ansible 008/015, KubeCoder 154–157; `status.md` C7;
**measured**): 76 entries (A 2 · N 6 · B 43 · Q 0 · S 25), 22 struck in-run by the consult or the
doc phase, 14 progressed by the operator, 7 tracker cards — against ten cards for one slice under
carding. Every report was dispositioned in one sitting. H1 held across projects; H2 held (zero
generation-1 appended phases in six runs, rework 8–16 % inside the 149–153 band with appended
phases now counted); H3 held on 146 (a bug accepted at disposition with its claim and line numbers
verified from the report's text alone); H4 held in part (015's `$JENKINS_TOKEN` unset and a
loop-ordering defect surfaced as entries, while two bail-outs appeared only in the header). The
kill signal was not seen: 154's 42 KB, 25-entry report was read whole. The operator's words that
day: "we struck gold … 1 or 2 things out of anywhere between 10 and 30 … solved the biggest
frustration I was having with the system."

Slice 170 (2026-08-22), the largest report at the time — 30 entries — was dispositioned in three
buckets, 6 cards, 7 fix-now, 15 closed, and B14 (an expired host certificate reads as certified)
was carded from the text alone. Its read also logged two defects that became catalogue entries
W3 and W4: the Summary and a Focus line said "no bail-out" under a 2-bail header (as 161's had),
and seven of the fix-nows were rider-grade comment nits the consult should have fixed itself.
No formal H1–H4 read has been logged since 170 (`status.md`'s C7 chapter ends there;
**untested** beyond that date).

Counted mechanically over the corpus on 2026-09-02 — every `close-out.md` under
`KubeCoderSpecs/slices/completed/`, live entries as `^### ` headings without `~~`, struck as with,
strike reasons classified by the words they contain (**measured**, method stated, first pass):

| | |
|---|---|
| Reports (slices 146–196) | 41 |
| Entries | 566 — median 12 per report, min 1, max 67 (slice 181) |
| Struck in-run (reason names a consult or the doc phase) | 112 |
| Struck at the operator's pass (reason names the operator) | 297, plus 35 worded as fixed or resolved at close-out |
| Live after dispositions | 122, of which 39 still blank — 14 of those in the two reports not yet processed (195, 196) |
| `Disposition:` lines naming a card or tracker URL | 59 (struck entries' lines included) |

Against H1's real number, that is roughly one and a half cards filed per slice at disposition
plus the one close-out card, against ten for slice 007. Two things from the record are still
open. The redundancy watch the first slice raised — two of 146's three Notable events narrated
things going right — was noted against the kill signal and not acted on from one slice
(`status.md` C7, 2026-08-15); the 41-report corpus has not been read for it. And one item is
"recommended, not built" since the six-report read: collapsing consult-struck bodies, which in
154 were most of the Bugs section — v0.6.0's `render` folds them into a `<details>` block rather
than removing them.

## Triage at the source

0.9.57 to 0.9.59 (2026-09-29) rebuilt the report around one observation of the operator's and
one read. The read is `../research/close-out-read-2026-09-28.md`: 99 reports, 1,429 entries,
every entry followed to what the operator did with it. The discussion of it, the design and
every number below are in `../research/close-out-triage-plan-2026-09-29.md`; the rules
themselves are the contract's.

**What was wrong.** A report hands over a median 11 entries and the operator progresses one in
three. The aids written over the entries did not help them choose: the Focus lines, the
Summary, the head of the report and the body of the close-out card were not read — "I judge the
items at their merit" — and a Focus line named 76 % of the entries, so it could not select. The
operator's diagnosis was of the entries themselves (**ruled**): "right now the close out report
is just a dump of thoughts and ideas. They aren't questions … the agent isn't really taking
responsibility for what it's reporting. 'I saw this; not sure what you want to do with it.'"
And what they guard is not a lost entry — "there will always be bugs" — but "an agent trying to
get my eyes on something that I then don't see".

**The author states facts, the tool applies the policy.** An author knows what it found and
does not know the operator's bar; a bar written into eight role definitions cannot be moved.
So the author labels — what kind of thing, what has to happen for it to show, what is then
experienced, whether it then says so itself, what is decided about the fix, where the fix
lives — and one table in `close_out.py` routes. The facts were there already: read from the
text alone, 87 % of the entries state what has to happen and what is then experienced, and the
labellers answered `unknown` for 4 % (**measured**, 561 entries of 47 reports).

**The table is the operator's policy**, as they stated it: prose and nits with a simple fix are
always progressed; a bug with an obvious fix is always progressed; "everything that's more
complicated is decided on how likely it is to cause problems". Two rulings followed from the
replay. Severity: the first table closed a defect graded major because it needed a fault, and
the operator ruled that what is severe comes to them in place of the close — and only there: "I
have no problem never knowing of an issue". And the signal: they progress what fails silently
twice as often as what fails loudly, 51 % against 24 % on their own rulings, because "when we
hit this, it will be very visible" — so what is loud on an ordinary condition is closed.

**Replayed on the rulings that are the operator's own** (234 entries, labels given by a reader;
**measured**), the tables keep 95 % of what they progressed, close 22 % of the entries, bring
them a median 2 entries of the 11 a report hands over and give 46 % to the wrap-up. The
text-only sorter this design replaced — one agent after the run, guessing the ruling from the
report's text — kept 83 %. The rule for improvements was chosen on the 48 rulings it is scored
on, so its part of that number is an upper bound.

**An improvement has labels of its own**, because the operator's two categories are different
questions: what should be fixed is asked how likely and how bad, what could be better is asked
who is better off and when that is felt. What adds something for a benefit nobody feels today
— a gate, an alarm, a check for an event that may never come — is what they close: 13 of 48,
none progressed. An improvement of the workflow was never the report's; the tool now refuses
it and names Fieldnotes.

**The constraint of v0.5.4 — a triage pass "ranks and pre-fills, never closes" — was set for an
agent that filters by judgment**, the class where an agentic filter suppresses 50–85 % of true
findings. What closes here is a rule of the operator's applied to facts the author stated, and it
closes in view: a closed entry keeps its heading and the ground of the close on the page (its
Consequence and its labels too, until 0.9.70), stays live until the operator closes the report, and
is pulled back by a ruling that names it. Where a close rests on a label and the entry breaks a
flow, the wrap-up checks that label in the code first.

**The store.** With labels an entry is a record of a dozen fields, the route is computed from
them, and the wrap-up corrects them. Kept in Markdown, each of those is a line the tool writes
and then has to find and parse again — about half of the tool was the parser of its own
output. The operator's suggestion: "I would very much consider storing close out information
in a structured format (JSON or YAML) until at the very end". JSON, because plugin code is
stdlib-only. It also makes a ruling data: the read needed a pattern classifier to tell an
entry's fate from the words on it, at 88 % agreement.

**The wrap-up** automates what the operator did by hand — "fix inline please": it fixes what is
decided and safe, asks for a card where a likely problem is more than it can fix responsibly,
and the rest stays closed. Its bar is the residual sweep's litmus, calibrated on the same class
of work. No reviewer reads its fixes: a review writes advisory findings, those are entries, and
entries go to a wrap-up — the loop has no end, and fix rounds on advisory findings are a
settled no. Its assurance is the bar, the gate, and one commit per entry.

**What it costs and what nobody has measured** (plan § 8): a session per slice that re-orients
on the repositories, which the doc-phase measurement of 2026-09-05 priced at about twice the
work; more inline fixes than the operator asked for, in code no reviewer reads; six labels
more per entry. Every number above rests on labels a reader gave — an author knows more than
its entry says, and has a stake a reader has not — and the wrap-up was never simulated. The
first live slice is looked at before the second runs, and the readout comes after five.

**The three lines (0.9.70, 2026-10-02).** The first eight reports under the tables showed the
entry itself in the way. Of the 23 actions that reached the operator, 11 ended with nothing
for them to do (**measured**): four "delete the scratch clone" entries the driver seeded — the
close-out session removes a clean, level clone itself — six restarts of environments that were
not running, and one notice of a changed surface, written as an action because a project's doc
plan asked for the surface to be named. An improvement reached them with its question in none
of its lines and four paragraphs under the headline — the body, a consult's note, the wrap-up's
relabel with a 250-line log count, the session's "still holds" — each one the contract asked
for; another came with six notes. The operator's direction (AIWF-34, **ruled**): "drop the
evidence and the prose from the report and get to the point … I trust the requests a session
makes. Evidence stays in close-out.json, where a session the operator asks to dig into an
entry finds it" — modelled on the Fieldnotes triage card, which opens each item with the ask
and the recommendation and is read past them "maybe one item in twenty". So an entry that
comes to them is three lines: the headline, which is the ask (0.9.63 had made a decision's
headline its question; an improvement's is now what it proposes, and an action is one
imperative that something waits on — an "if" is a decision, a fact nobody acts on is not an
entry); a `Proposal:` its author gives in a ruling's words, required of an action, a decision
and an improvement, the wrap-up's card request on the rest; and the `Consequence:`. The body,
the notes, the labels in words and the provenance left the page for the store, where `show`
prints them; a closed entry is its heading and the ground of the close, the record is
headings. Nine of the fourteen decisions that reached them were ratifications of a shipped
choice with no consequence either way; asked whether those should go to the record instead,
the operator kept them (**ruled**): "Bring them to me. I'll come back if it bothers me." Two
of the design's own words moved with it. The session that "asks nothing yet" now presents a
proposal on every entry — the rulings showed that is how the operator ruled anyway: "Perform
the rest of your suggested actions please", "I'll follow your recommendation", "Agreed on the
actions" — and "write for a reader who has only this document" is now said of the body and
the store, not of the page.

## Deliberately absent

From the contract's own closing section (`plugins/dev/docs/close-out.md`): no dedup tooling —
`render` orders, it never merges, and every agent runs `list` before it writes; no table of a
project's own and no switch on the routing or on the wrap-up — the operator's word on the
switch was "I don't need the switch"; and nothing written over the entries by anyone, no list,
no summary, no ranking: the report is its entries.
