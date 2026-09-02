# From per-finding cards to the close-out report

Why the loops stopped filing a tracker card per finding and started writing one document per
slice, what that document's shape is for, and what the first forty-one reports show. The
report's contract — who writes what, the entry rules, the lifecycle — is
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

The six sections and what each is for are the template's; two choices are worth the why. **Notable
events** exists so that workflow deviations — a bail-out, a blocked proof re-routed, a tool
missing from the sidecar — surface in the report rather than only in `log.txt` (H4 below).
**Outstanding actions** was the operator's addition on 2026-08-15: "a runbook for the operator to
complete" (§ 8).

The entry closes with three bold labels, each added when a read showed the gap:

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
  in words rather than through the tool.

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
game, not now) and, in its header, where the build departed from the plan the same day.

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
*deleted* the two entries it absorbed instead of striking them (Trello #630). The fix put the
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
smoke checks. Only the completion consult strikes, and only through the tool.

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

The operator reads the rendered report and writes one line under each live entry; the suggested
vocabulary is `card [board]` · `fix now` · `fold into <slice>` · `close` · `defer`, free form. The
`/dev:close-out` skill ([`SKILL.md`](../../plugins/dev/skills/close-out/SKILL.md)) presents the
report through `list` and asks nothing, then executes: `card` files one tracker card with the
entry verbatim as its body, `fix now` does the small thing only if the project's own conventions
class it as ad hoc work, `fold into` appends the entry to a backlog slice's `slice.md`, `close`
strikes with `— closed by the operator, <date>`, `defer` leaves it for `/dev:triage`. A blanket
ruling ("close the rest") is a `close` on every blank entry. Two bounds carry the design's
intent: the session never edits the operator's words (what it did goes after them on the same
line — a card id, a commit), and when a disposition asks about a claim it answers from the
entry's own body and Provenance rather than agreeing (v0.5.4: a challenge flips 32–86 % of
correct answers in Sharma et al.).

The run's only tracker output is one card, `[NNN] close-out: <title>`, whose body is the Summary,
the Focus lines, the entry counts and the report's path; it is archived when no live entry has a
blank `Disposition:`.

Triage got the same durable seam one stage earlier and one day later (v0.5.2, 2026-08-16): after
a run of 86 in-scope cards over two days, the rubric verdict — the skill's main product — turned
out to be the one thing it never persisted. Verdicts became tracker labels on the cards,
dispositions a stated vocabulary (`close` / `later` / `agreed` / `apply the suggested edit` /
`conditional: … if …` / `split` / `superseded by`), and the work two named halves a later session
can resume from the labelled board. Same idea: the operator's decision, recorded where the next
session finds it, in the operator's words.

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
  departure and renders a false, permanent "Deleted" — carded as Triage #778; S9, the same shape at
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

## Deliberately absent

From the contract's own closing section (`plugins/dev/docs/close-out.md`), each a decision of
2026-08-15 or 2026-08-17: no validation beyond "the section heading exists" and the smoke counts
(the operator: don't go overboard); no dedup tooling — `render` orders, it never merges, and every
agent runs `list` before it writes; no disposition parsing — the line is the operator's, free
form; and no automated triage pass over the report, with one constraint set in advance for when
it comes: it ranks and pre-fills, never closes, because the report is mostly the judgment class
where an agentic filter suppresses 50–85 % of true findings (v0.5.4, from Sifting the Noise). The
shape is meant not to change when that step arrives.
