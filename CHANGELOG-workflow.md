# `dev` plugin — changelog

Notable changes to the `dev` slice-workflow plugin, newest first. Entries below the plugin rework
are retained as history — they document the template-era workflow this plugin supersedes (when the
workflow was copy-and-fill templates rather than an installed plugin).

## 2026-08-20 — the anti-polling rule moves into the KubeCoder preamble; the plugin's three copies go (v0.7.4)

"Wait by notification, never by polling" was restated in four near-identical places — the
`run-slice` and `plan-slice` skills, `test-agent.md`'s rule 7, and KubeCoder's
`slice-test-plan.md` — and not one of them covered a dispatched sub-agent, the other kind of work
that reports back. It is now a single `## Waiting on work` section in the in-pod `CLAUDE.md`
preamble (KubeCoder `worker/internal/claudemd/templates/CLAUDE.md.tmpl`, after `## Sub-agents`),
which reaches every session in every KubeCoder pod — dispatching agent and sub-agent alike — and
names the legitimate hand-waits (`track_build.py`, `kill -0` on a captured pid) beside the ban, so
nobody improvises one. The three copies here are gone: the two skill sentences lose only the
"notifies you on exit" clause (the `log.txt` / `state.json` / `bailout.json` pointers stay, and
"do **not** read or tail" with them), and rule 7 goes entirely. The plugin now leans on a file in
another repo for a rule its agents need; KubeCoder's `TestWaitingOnWork`, asserted over the render
matrix, is what guards it — the goldens would let `-update` bless a deletion. Trello #656.

## 2026-08-19 — the writer-effort step-down is withdrawn: 0.7.0–0.7.2 reverted (v0.7.3)

A3 stage 1 is out, by operator decision after four slices (`docs/research/status.md` A3,
2026-08-19): the code-writer's round-1 step-down, `--writer-effort`, the fuse, the run loop's
`## Task shape` reader, `task_shape` / `writer_effort` / `effort_fuse` in `state.json`, `effort`
on history rows in both loops, the `shape … · writer …` segment of the close-out `Run:` header
with `round1_writer_tier`, the crash-re-dispatch `redo` flag on `spawn_executor`, and
`slice_cost.py`'s `tiers` line and effort column. Every Opus dispatch is `xhigh` again, as before
0.7.0. The read that ended it: the seven `high` round-1s on slices 160 and 161 all signed off on
round 1 — but every `high` round the trial ever ran sat in the small-phase band where `xhigh`
draws a blocking finding only 5–10 % of the time, so the trial could not gain power; and effort
moves output tokens, which are ≈ 20 % of a writer round's cost (context is the rest), so the
saving was ≤ 1 % of a slice against one witnessed ≈ 4 % rework strike (158 P2). The operator's
ruling: additional complexity, dead weight — whoever wants the knob in this loop can build it
for themselves. Kept from the three versions: `slice_cost.py`'s session table still names each
session's round (`P2 code-writer r2`). State files written under 0.7.0–0.7.2 keep their extra
keys; nothing reads them. The research record (`docs/research/a3-plan.md`, `status.md`,
`interventions.md`) stands as written.

## 2026-08-19 — the run header names the tier round 1 ran at, not the flag it was launched with (v0.7.2)

Slice 159's close-out read `shape cross-cutting · writer high` on a run whose every writer round
was `xhigh` — the header printed the persisted `writer_effort` flag, which a `cross-cutting` shape
makes inert. It now prints the tier the rule actually dispatched: the round-1 tier rule and
`STEP_DOWN_SHAPES` moved to `close_out.py` (`round1_writer_tier`), where the loop's dispatch, its
dry run and the report's `Run:` line all derive the same answer; a `null` task shape is said as
`shape undeclared` (it is why the writer ran `xhigh`), and `(fuse tripped)` is dropped where no
lower tier existed to leave. Behaviour of the dispatch is unchanged. `close-out-template.md`
states the header rule.

## 2026-08-18 — a crash re-dispatch is not a redo: it neither escalates nor trips the fuse (v0.7.1)

The first read of the step-down (slice 158) found the fuse counting P4, whose round 1 died `rc=1`
with no verdict and whose round 2 was only the re-dispatch after the operator resumed the loop.
`spawn_executor` now takes an explicit `redo` flag: gate-fix, review-fix and operator-ruled rounds
are redos — they run `xhigh` and count toward the fuse — while a re-dispatch after a crashed or
`blocked` session or a protocol bail-out is a fresh attempt at the same work: it runs at the
round-1 tier and counts for nothing. The round number still climbs (it names the verdict file and
the history row). Left as it was, a crash on the first two phases of a small-shape slice would trip
the fuse on noise and silently move a `high` phase into the `xhigh` arm of the trial.
`agent-dispatch.md`, `run-loop.md` and `runner-state.md` state the rule.

## 2026-08-18 — the code-writer's round 1 steps down to `high` on a small-shape plan (v0.7.0)

A3, stage 1 (`docs/research/a3-plan.md` §3, §8a) — the trial the catalogue prices as the cheap
knob with honest uncertainty. Every dispatch has run Opus at `xhigh` since the graded lane was
retired; the effort documentation says `high` *is* the default and `xhigh` the premium for
demanding work, and Cuadron et al. found less effort matched more at 57 % of cost — with the
counter-evidence, stated in the catalogue, that o1-*low* over-thought *more* than o1-high in
agentic settings. So the change is one rule at one site, self-gating and reversible by a flag:
**the code-writer's executor round 1 of each phase runs at the run's `writer_effort` (new
`run_loop.py run --writer-effort {xhigh,high,medium}`, default `high`, persisted in
`state.json`) iff the plan's `## Task shape` is `pre-settled` or `localized`; `cross-cutting`, an
undeclared or unparseable shape (every plan predating A1), or a tripped fuse keeps round 1 at
`xhigh`; every executor round ≥ 2 runs `xhigh`** — each exists only because a signal fired (a
red gate, a blocking finding, an operator ruling), so "round ≥ 2" is the escalation with no
bookkeeping. The **fuse**: once two phases in a run have needed an executor round beyond round 1
(`state.json`'s `effort_fuse`), every later phase's round 1 runs `xhigh` — the self-protective
answer to the graded lane's failure mode, a slice on which the cheap tier keeps triggering redos
stops paying the redo tax mid-run rather than at the retrospective. Unchanged at `xhigh`:
code-reviewer, every consult, doc-writer (no reviewer covers the doc phase, so no signal would
catch a cheap-tier failure there), plan-writer and plan-reviewer (the plan half is a conditional
second stage, built only if this one holds); the Sonnet roles are untouched; the writer is not
told its tier. A crash-reattached session resumes at the tier it was created with (effort is
fixed within a session). Telemetry rides I1/I2: every session history row in both loops now
carries `effort` (the value actually dispatched), `state.json` gains `task_shape`,
`writer_effort` and `effort_fuse`, the close-out `Run:` header names the shape and tier,
`slice_cost.py` prints a `tiers` line and each session's round and effort, and `run_loop.py
status` / `--dry-run` show the shape and the round-1 tier. Kill criteria are pre-committed in the
plan (§5): if `high` sessions run longer or spend more than `xhigh` ones, or the redo tax eats the
discount, the flag goes back to `xhigh` — one launch-flag change, no revert.

## 2026-08-17 — the report is tool-written and rendered: append, note, strike, list, render (v0.6.0)

The same reports read once more, from the writer's side. Every entry was typed by hand off the
head comment, and it showed: the shape drifted wherever the comment was read loosely (the 0.5.1
read — unshaped headings, dropped labels), each author read the whole file — 42 KB by the doc
phase of a long slice — to add one entry, the completion consult reconciled by editing other
agents' text in place, and struck entries stayed where they arrived: in 154, 10 of the 16 Bugs
were struck in-run and sat, full-bodied, ahead of the six the operator had to decide on. Scripts
drive, agents judge — the shape is mechanical, the content is judgment. **Now `close_out.py` is
the only pen.** `append` mints the entry (as it did for the driver's own since 0.5.0); `note <id>`
adds the dated paragraph (`<who>, <date> — <text>`) above the Consequence line — above the
Provenance line on an entry from before that label existed; `strike <id> --reason … --by …`
rewrites the heading to the struck form and touches nothing else; `list` shows the sections' ids,
headlines and Consequence lines without the bodies; and `render` puts each entry section in
reading order, in place and idempotently — live entries first, Bugs by severity (major → minor
→ nit → cosmetic, then ungraded), headings not in the entry shape as they were, struck entries
last with their bodies folded once into a `<details>` block. Every dispatch of both loops, consults
included, names the report and the installed tool's absolute path once, with the ban on hand
edits; the completion consult's reconcile sentence names `strike` with a reason that carries the
phase, the commit and what was re-run, and `note` for anything else; the driver renders
immediately before it dispatches the doc phase — the doc-writer ranks its Focus lines over the
order the operator will read — and again at completion, before the stamp. The six registers point
at the tool instead of the file's shape; the close-out skill presents through `list`, executes
`close` through `strike`, renders before it commits, and archives the card when no *live* entry
has a blank Disposition (a struck entry needs none — its fate is its heading). Deliberately
unchanged: no validation beyond the smoke counts, no dedup (`render` orders, never merges), no
disposition parsing.

## 2026-08-17 — every claim in the report carries its evidence class (v0.5.4)

The reader-side half of the six-report read, from the S5–S7 papers. The overcorrection study's
false-rejection mass is claims with no falsifiable counterexample (87 %); symptom claims hold
(93–100 % match), cause attributions are the half that does not (44–75 %); and Sifting the Noise
found reading with perfect context no better than reading blind — only running things reaches
precision. The reports showed the same: the entries later refuted or overtaken (156 B4's first
bullet, 157 B1) and the one the operator called "very dense" (155 B2) were read, not witnessed,
and said so only in prose. **Now `**Provenance:**` opens with `witnessed` or `read`, the body
leads with the symptom and states a cause only where shown, and a strike is a claim like any
other — resolved / refuted / does-not-reproduce names the commit and what was re-run** (the
consult is the one in-run judge of other agents' entries; Huang et al.: self-correction without
external feedback degrades). The doc-writer's Focus lines rank on the Consequence lines and
evidence class, never on length, and say how many entries are witnessed (Gema: concrete anchors
correct spurious drift; Saito/Wataoka: same-model ranking favours long, fluent text). The
close-out skill answers a disposition that asks about a claim from the entry's own body and
Provenance — quoting what supports or fails the operator's reading, saying when it does not
settle it — instead of agreeing (Sharma: a challenge flips 32–86 % of correct answers). The
driver's own entries are stamped `witnessed`. Set as a constraint for the end game, not built:
an automated triage pass over the report ranks and never closes — the report is mostly the
judgment/policy class where an agentic filter suppresses 50–85 % of true findings.

## 2026-08-17 — the consequence is a line of its own, and the labels are bold (v0.5.3)

Read off six finished close-out reports across two projects (Ansible 008/015, KubeCoder 154–157:
76 entries, 22 struck in-run by the consult or the doc phase, 14 progressed by the operator, 7
tracker cards — against ten cards for one slice under per-finding carding). The report does what
it was built for; what it did unevenly was say **what an entry costs**. The template put the
consequence inside the body's placeholder prose ("Why it matters: the consequence, or 'none'
said plainly"), so authors treated it as prose: 154 and 155 wrote a `Consequence:` paragraph on
most entries, 157 wrote the template's own phrase "Why it matters:", 156 labelled nothing, and
the one entry the operator called "very dense" (155 B2) had a consequence line that said what
the code did rather than what a real environment risks. **Now `**Consequence:**` is one of three
bold labels closing every entry — Consequence, Provenance, Disposition, in that order** — its
charter written for triage (what an operator or user actually experiences if the entry stays as
it is, in the deployed shape, in plain words, or `none`; not "better than before", not "none to
behaviour" when a human would notice something), because it is the stated consequence
`/dev:triage` rules on and the line the operator scans for. `close_out.py append` mints the three
labels and requires a consequence (the driver's two stock entries — a refuted finding, a
funding-consult merge — carry one each), and `counts` names, beside the unshaped-heading count,
how many live entries lack a `Consequence:` or a `Provenance:` line, bold or bare — the smoke
check now reaches the line that was dropped most. **One entry per thing, not per turn:** a later
observation about an existing entry (its premise moved, it was re-tested, a reviewer refuted it —
157's N1→N2 thread about B1, 156's B6 refuting B4) is a dated paragraph at the end of that
entry's body, never a new entry. The close-out skill presents each live entry with its
Consequence line under the headline, treats a blanket ruling ("close the rest") as a `close` on
every blank entry, strikes a closed entry as `— closed by the operator, <date>` with the reason
staying on the operator's line, and records what it did after the operator's words on that
same line — three sessions had invented three places for it.

## 2026-08-16 — triage gets a durable seam: verdicts on the board, dispositions in a vocabulary (v0.5.2)

Read off the reworked skill's first real run — 86 in-scope cards over two days, findings in
KubeCoderSpecs `handovers/triage_2026-08-14_skill_findings.md`. The skill assumed one session
start-to-finish and one product (slice folders); the run needed to adjudicate now and dispose
later, and everything awkward traced back to that: the rubric verdict, the skill's main product,
was the one thing it never persisted, and step 8 deleted the only document holding it. **Now the
work has two named halves — adjudicate (steps 1–5) and dispose (steps 6–9) — with a durable
seam:** every final category is written to its card as a tracker label, `close`/`later` are
actioned at the seam, the working documents are committed at every pass boundary and deleted only
when nothing in them is still open, and a later session starts at Sort from the labelled board
without re-deriving a verdict. The operator chooses per run — either half, both, or a selection
of cards. **The status document holds at scale:** grouped by verdict (a verdict group is the view
the operator acts on — the nit picks together are the cull list), each item's source inlined
whole under `**Card text:**` with headings demoted, stable ids, URLs on headings, no typed
counts; collection and composition are delegated to parallel sub-agents under two stated
guardrails — never alter a verdict line, and the merge is verified mechanically, not by eye.
**The operator pass has a vocabulary,** stated in the document header instead of invented per
run: label rulings (`answer` / `override` / `remark`) and dispositions (`close` / `later` /
`agreed` / `apply the suggested edit` as a scope ceiling / `conditional: … if …` /
`split` / `superseded by`); a conditional ruling is not an approval — the fact becomes a
`Research:` line and the item comes back for a final ruling; split and superseded carry their
card mechanics. **Research is a loop, not a terminus** — rulings ask their own questions, the
round repeats until no `Research:` line is open, "cannot determine" routes to the `Question:`
line instead of stranding the item, and each verdict is recorded on the card as a dated triage
comment: durable, and source material a slice quotes attributed like any other card claim
(triage still authors no design). Rubric: `Test gap` (the run loop's most common shape had no
rung) and `Decision` (nothing broken; rule on this — the ruling is the disposition) join it;
operator chores sit outside it; rule 2 states its tie-break (a source's explicit framing beats an
inferred consequence, stakes on a `Note:` line); the nit-pick sub-split stays a note, not a
second label. Sweep: a Solution Known mark from an earlier session is re-checked against the
litmus as it stands, and `sweep_slice.py` gains a ceiling to match its floor — more than ten
phases refused without `--force`, larger sets split by target. Kept verbatim, on the run's
evidence: the verbatim-quote rule, rule 5's guard (it caught four already-done cards queued to
be built twice), the recommend/close split, the SK litmus with its adds-behaviour exclusion, and
the from-memory constraint on questions. Not adopted, deliberately: execution "lanes" for
bundles of literal edits — a one-off board clear-out, not workflow.

## 2026-08-15 — the entry shape is in the file; the gen-1 bar prices a phase against one word (v0.5.1)

Read off the first slice run end to end on 0.5.0 (KubeCoder 146). **The close-out report's
entries landed without ids, `Provenance:` or `Disposition:` lines** — every register says "the
shape is in the file", and the file `close_out.py init` wrote carried only the section charters,
so the first author wrote freehand and every later one copied the precedent; `counts` read zero
for a six-entry report and the consult deleted where it should have struck (Trello #630). Now the
template's head comment carries the entry shape and the struck form, so `init` writes them into
every report; `close_out.py` reads headings outside HTML comments as well as outside fences;
`counts` (and the driver's completion line and the close-out card that carry it) says how many
`###` headings in the entry sections are not in the entry shape, so a drifted report announces
itself instead of counting zero; the Notable-events charter names workflow deviations (a tool
missing from the sidecar, a wait that hit a cap) beside product ones. **The first-generation bar
was still priced against a card**: "absorbed beats reported" was written when the alternative to
appending a phase was a tracker card the operator had to open and relate to nine others; under
the report the alternative is one word under an entry, and 146's consult appended a phase for a
test nit ($4.02 with the consult it forced) reasoning "cheaper to fix than to card". The bar now
appends only work the plan owes and no phase delivered — a requirement or ruling nothing carried
out, an acceptance criterion with no implementing work to point at — and prices it plainly: a
phase costs an executor round, a review round and the consult the generation forces; a close-out
entry costs the operator one word. **`slice_cost.py`'s rework share now sees appended phases**:
every round of a phase in `state.json`'s `appended_phases` counts as spend past first delivery
(their round 1 sat outside the share, which is exactly the quantity the report's H2 hypothesis
moves; pre-0.5.0 records carry no such field and are unaffected). One reviewer-register clause:
the `coverage-gap` anchor names vacuous coverage — a mutation the criterion's test survives —
explicitly, so the class 146 and 145 each produced once stops arriving as evidence-free
advisory. Catalogued, not built: I5 (a `witnessed` field on the review verdict) and C8
(mutation-witnessed signoff for test-only phases) in `docs/research/interventions.md`.

## 2026-08-15 — the close-out report replaces per-finding cards (v0.5.0)

Everything a plan or run agent notices but the loops will not act on — a bug it will not fix, a
keystroke only the operator can make, an event that deviated from an uneventful run, a question
the run did not need answered, an idea — now goes into **one document per slice**,
`close-out.md`, in one fixed shape, as it happens (`docs/close-out.md` is the contract,
`docs/close-out-template.md` the shape; design and decisions in
`docs/research/close-out-report.md`, C7 on the status board). Nothing from a run is carded per
finding any more: the run's only tracker output is one `[NNN] close-out: …` card pointing at
the report. The operator reads the report in one sitting, writes a disposition under each entry
(`card` · `fix now` · `fold into <slice>` · `close` · `defer`, free form), and the new
`/dev:close-out` skill executes them; what remains is `/dev:triage`'s input.

What moved: the plan loop creates the report from the template before its first dispatch (the run
loop does if planning predates it); every agent register lost its verdict `cards` field and
gained the report — the code-reviewer enters its advisories there itself, the completion consult
is the one pass that reconciles (strike what it absorbed, merge duplicates, mark what a phase
resolved), the doc-writer writes the Summary and Focus lines as its last act; the driver's own
entries — refuted findings, funding-consult merges — go in as Notable events through the new
stdlib `tools/close_out.py` (init / append / stamp / counts), and the driver stamps the run header
from `state.json` at completion (`/dev:run-slice` re-stamps once the cost block has landed).
`state.json` lost `cards` and gained `bailouts` and `appended_phases`, which the header reads.
Gates whose purpose was to limit reporting came out — "worth a card", "no fix proposals", "a card
must never cost the operator more to triage than the fix costs to make", the consult carry-over
list; the gates that govern what funds work (fix rounds blocking-only, the generation bars, the
mechanical-residue rider) are unchanged. A pre-0.5.0 register still emitting `cards` is logged
and ignored, never a protocol failure. Hypotheses and how they are read: design note §7.

## 2026-08-14 — comments must be witnessable, prose findings must show wrongness (v0.4.5)

The comment-economy pair from `docs/research/interventions.md` (B1+B4), one rule each side of the
review boundary. Coder side (B1): the "invariants only" comment rule gains its missing criterion —
verifiability. A comment must state a condition code, a test, or a gate can witness; predictions
and strength-graded claims ("will/may/should …" about future or external behavior) are deleted,
not hedged, while load-bearing warnings ("must run before X") are invariants and stay. Reviewer
side (B4): a prose finding must show the text is *wrong* — contradicted by the code or the spec —
not that different words would be better; meaning-preserving wording drift is not a finding.
Together they remove the substrate the will→may findings grow on and the reviewer's license to
prefer its own phrasing. Effect is read off I1's comment-category finding rate and comment density
per diff (`docs/research/status.md` tracks both entries).

## 2026-08-14 — triage filters the cruft before planning spends on it (v0.4.4)

The triage skill, reworked ground-up around a filtering layer — the plan phase was where items
that should never progress got expensive. Raw material lands on disk verbatim before anything
else (also when triage starts mid-session); items are split mechanically and labelled against a
worked-example rubric — nit pick (user-visible/internal), corner case, minor, major, improvement,
feature, invalid — with every label justified by a verbatim source quote, never a generated
rationale, judged per-item in isolation, keyed on the stated consequence (a claimed severity
stands until the operator or a research verdict says otherwise). One consolidated operator pass
adjudicates via typed rulings — close / answer / override / remark — where a bare remark never
moves a label. Items whose label neither the source nor the operator settles get one read-only
sub-agent answering one named question ("cannot determine" allowed); the verdict settles the
label and none of it carries into the slice. Invalid and corner case are guarded — never
assignable from belief — and no item is ever closed by machine judgment alone. The final
category is stamped on each slice.md requirement and the README Pending line. Steps that don't
apply are skipped. Design honed against the docs/research corpus (judge-mode bias, sycophancy,
fact-vs-impact reliability split, premature disengagement); scope note added to interventions.md
A4 — an operator-adjudicated label is not the rejected automatic-routing grade.

## 2026-08-14 — the intervention catalogue's first batch ships (v0.4.3)

Six entries from `docs/research/interventions.md`, actioned together: the instrumented review/fix
contract (I1, C1, C2), the cost readout (I2), and the shape-bound plan contract (A1, A2). Per-entry
state and success criteria are tracked in `docs/research/status.md`.

- **Findings telemetry (I1).** The code-reviewer's verdict reports every finding
  machine-readably — id, severity, impact, category, anchor — and the driver persists the list
  into `state.json`'s history rows, alongside a fix round's `refuted` list. Problems B and C
  become measurable per run; slices 143+ against the ≤153 baseline is the 0.4.2 before/after.
- **Anchoring taxonomy (C1).** A `blocking` impact tag now requires one of five recorded
  anchors — failing test/command, repro trace, analyzer output, requirement-to-code
  contradiction, coverage gap against a named AC. No anchor is advisory by construction, and
  readability/taste/hypothetical-performance/unspecified-edge-case findings can never anchor.
  Replaces the looser "failing-input logic or a test sketch" severity bar.
- **Demonstrate-failure-first fix rounds (C2).** A fix round witnesses each executable-anchor
  blocking finding before changing code — the failing test rides the fix as its regression
  test. A finding that cannot be made to fail is **refuted**: no code change, carded with the
  refutation evidence, the record appended to the round's review file, never relitigated; a fix
  round that refutes every blocking finding with no code change settles the review outright.
  Inspection anchors (contradiction, coverage gap) keep their current handling.
- **Cost readout (I2).** `slice_cost.py` derives the close-out ratios — planner share,
  research-subagent share, rework share (rounds ≥2 + consults) — and `--write-state` appends
  them to `state.json` as `cost`; `/dev:run-slice` runs it at close-out, so cost trends read
  off committed run records instead of transcript archaeology.
- **Task shape + question-gated research (A1+A2).** The plan-writer declares
  `pre-settled` / `localized` / `cross-cutting` in plan.md before investigating, justified in
  one line from slice.md facts; `pre-settled` forbids research sub-agents and repo sweeps, and
  at any shape a research dispatch must name the open question it settles — a settled question
  is never re-dispatched. The plan-reviewer checks the declaration against slice.md. Grounding:
  slice 153 spent $27.72 before any code existed on a slice whose slice.md said "you are not
  designing anything".

## 2026-08-13 — fix rounds stop relitigating comments (v0.4.2)

Ansible slice 013 ($45, 3h wall for a small slice) spent the second rounds of two of its three
phases on comment wording. The chain: the reviewer reported advisory prose findings with forensic
evidence (Jenkins build-history archaeology to falsify one comment sentence, a git dig to date a
dead doc anchor); the fix round's "resolve every finding" pulled every advisory in alongside the
one blocking finding; the comment fixes became the delta review's subject and bred new comment
findings; the completion consult mopped up what was left. Three prompt-level bounds close it:

- **Fix rounds resolve blocking findings only.** `EXECUTOR_REVIEW_FIX_PROMPT` scopes the round to
  findings tagged blocking; advisories are the loop's (cards at close-out, the residue rider's
  in-place mop-up for mechanical comment fixes at loop tail — the cheap path that already
  existed). An advisory fixed mid-loop widens the next re-review to everything the fix touched.
- **Delta reviews verify blocking resolutions and stop re-deriving the world.** Unfixed
  advisories are the protocol working, not a gap to re-report; premises the prior round proved
  (live registry state, sibling-repo behavior) are re-derived only where a fix commit touches
  them.
- **Comment and prose findings are advisory by default and earn one sentence, not research.**
  Reviewer rule: harm from following the words is what promotes one to blocking; a comment claim
  that takes live-system or history archaeology to falsify was not worth the archaeology; one
  report is the finding's whole lifecycle. Verdicts now hinge on the impact tag — `signoff` =
  nothing blocking — matching what the better reviews already did in practice.

## 2026-08-11 — the phased-plan rebuild comes home (v0.4.0)

KubeCoder vendored 0.3.1 back onto its `main` on 2026-07-31 and rebuilt the pipeline there
(`KubeCoderSpecs/ai-workflow-redesign/`), against a design that replaces the task-folder model with
a **phased plan**. Four pilot slices ran it end to end — 114, 125, and the parallel pair 104/107 —
at $56–164 each, with the pathologies the redesign targeted staying dead all four times. This
release is that rebuild ported home, and KubeCoder's copy is deleted in the same change: the
workflow has one home again.

**The plan is the queue.** `task_runner.py` becomes **`run_loop.py`**, driving one `plan.md` of
`### P<id>` phases instead of `tasks/NN_slug/` folders. Each phase opens with a `Target:` line (a
`kc project list` component *or a sibling repo* — cross-repo phases are first-class now), document
order is authoritative, and only the driver stamps `✅ DONE`. Every agent in the loop may edit the
plan; appending a phase is how work grows, bounded by a **generation bar** that folds small in-scope
touch-ups in early and cards the rest at close-out.

**The loop owns the whole slice, not just the merges.** After the last phase: a loop-tail
`lint`+`build`+`test` sweep across every touched repo, a completion consult, then a **test phase**
and a **doc phase**, each "read the project's doc and execute it". The driver holds the spec repo's
devlock across both, and under that hold pushing and rolling dev for verification is
pre-authorized — prd stays explicitly operator-gated. Two new agents serve them: **`doc-writer`**
(diff-based over the whole shipped slice) and **`rebase-agent`** (mechanical rebases onto a moved
base, on Sonnet). A fourth `CLAUDE.md` contract line, **`Slice doc plan:`**, is what the doc phase
resolves through.

**The plan loop is one structural round.** `plan_loop.py` no longer iterates: a writer pass, a
reviewer pass, and exit — findings go to the operator for adjudication, whose rulings land in
`plan.md` and drive exactly one fix pass. The review is not optional; exit 0 is refused without a
reviewer verdict on file.

**The grounding ledger is gone** — `grounding_check.py`, `grounding_dispatch.py`, the
`slice-grounder` agent and `grounding-ledger.md`. Grounding survives as evidence citations in
`verification.json`, whose acceptance criteria are outcome-level. Also retired: `plan-briefer`,
`plan-scribe`, `slice-verifier`, and the `write-task` skill (a plan phase is a heading, not a
folder to author).

**New: the residual-sweep lane** (`sweep_slice.py` + `residual-sweep.md`). Cards whose acceptance
criteria triage can write from the card text alone batch into a mechanically generated slice that
skips `/dev:plan-slice` entirely and runs on the ordinary loop.

**This repo gains a gate.** `kc project test|lint` now run the plugin's ~4,700 lines of suite here
(159 tests) — before, nothing in AIWorkflow could run them, which was survivable only while
KubeCoder held a copy. `tools/analysis/` retires with the move: `slice_cost.py` ships in the plugin
and prices a slice from the run's own state records, superseding `slice_costs.py`, which guessed a
session's slice by regex over raw transcripts and hardcoded a `-work-KubeCoder` project map;
`runner_sessions.py` read a `task` key `run_loop.py` no longer writes.

Not ported, deliberately: KubeCoder's `update-docs` skill and `track_build.py` stay project-owned —
the first because a project's documentation model is its own, the second because it is CI tooling
that never belonged to the pipeline.

## 2026-07-29 — `kc status` joins the preflight (v0.3.1)

Preflight's v1 note said "no daemon-reachability check — the first `kc session create-headless`
failure is the signal". `kc status` now exists (worker daemon over loopback `/healthz`, controller
reachable *and* authenticated), so the signal moves to step one: **`--for plan` and `--for run` gate
on it**, as an environment failure (**exit 2**, alongside the `kc`-on-PATH check) — a dead control
plane means every dispatch fails, but nothing in the project is wrong, so the project is not the one
asked to fix it. The check runs before the repo is resolved and relays `kc status`'s own report,
whichever stream it came out of.

**`--for triage` is deliberately exempt.** Triage dispatches nothing and touches no `kc` surface —
it is intake, doable without the repo. The cost of the check there is a false gate, not the 20ms.

`preflight.py` gains its first suite (7 tests) covering the check, its exit code, its position in
the sequence, and the profile split.

## 2026-07-29 — the last KubeCoder sync (v0.3.0)

KubeCoder — the repo the workflow was developed and validated in — now runs inside a KubeCoder
environment and installs this plugin like every other repo. This sync ports everything its vendored
copy learned since the 2026-07-16 baseline (KubeCoder `912da03`, 35 commits), after which the
vendored copy is deleted and **the plugin is the workflow's only home**: improvements land here
first from now on, there is no upstream left to sync from.

Five sub-syncs, each its own commit:

- **The grounding ledger** (`grounding_check.py` + `grounding_dispatch.py`, suites,
  `grounding-ledger.md`). Claim→source ledgers with mechanical drift checking: the checker
  re-greps every entry's anchor, `--repair` fixes `MOVED` lines with no model involved, and
  tiered handling routes real drift to a scoped re-grounding pass — only a falsified load-bearing
  claim reaches the operator. Both scripts derive the repo root from `git rev-parse
  --show-toplevel` at the caller's cwd (the vendored copies hardcoded their repo).
- **The runner.** The review loop's economics replace the cap-3-plus-2-grants scheme: round 1's
  fix is automatic, every later `issues` verdict goes to a funding consult that judges the
  findings against a bar that rises each round, and the old cap survives only as a backstop (5)
  at which funding is withheld. Rounds bank on a verdict, not on dispatch; rounds 2+ are
  delta-scoped to the fix range; every round is told the gate's verified state. D177 graded
  writer routing lands (`task.json`'s `grade` picks round 1's model — `mechanical` → Sonnet,
  `standard` → Opus, `gnarly` → Fable; every later round runs Opus, and a Sonnet round 1 licenses
  the fix round to redo rather than patch). Fix rounds are fresh sessions (a resumed round's
  accumulated context cost ~2.2× per turn). Account session-limit windows are waited out and the
  round redispatched — never nudged, consulted, or counted. Grounding freshness rides every
  initial writer dispatch, and the checkpoint consult gets a whole-ledger drift summary as
  deterministic input.
- **The plan loop** (`plan_loop.py` + suite, `plan-loop.md`) — `/dev:plan-slice`'s mechanical
  half, which previously had none: fresh plan-writer/plan-reviewer rounds against a stored review
  budget (4, `--grant` extends, `--reopen` re-enters a done loop), `questions` verdicts that pause
  the loop for operator rulings, delta-scoped re-reviews, grounding `--repair` before every
  dispatch and `--prune` at GO, then hygiene, cross-reference lint, and deterministic
  `verification.json` seeding. Three new agents — `plan-briefer`, `plan-scribe`,
  `slice-grounder` — and the `plan-slice` skill rewritten around the loop: the coordinator holds
  decisions, not documents.
- **Close-out and the remaining prose** (`close_slice.py` + suite): the mechanical half of
  `/dev:run-slice`'s close-out — README entry Pending → Completed, folder to `slices/completed/`,
  staged by name, commit left to the session. Run-slice gains a grounding preflight
  (whole-ledger `--repair`; tier 2 dispatches a scoped re-grounding, tier 3 stops before the
  runner starts). The nested-delegation house rule lands — delegate the reading, keep the
  judgment — and `slice-verifier` / `arch-design` fan their per-item reads out under it.
- **The contract docs** reconcile into topic docs, one home per claim: `task-workflow.md` keeps
  the shared contract; `task-runner.md`, `runner-state.md`, and `agent-dispatch.md` (re-authored
  around the `kc session` seam) take the mechanics. `/dev:onboard`'s delete-list now names
  everything the plugin supersedes — eleven agents, five scripts, six contract docs.

Not ported, deliberately: `PROJECT_DIRS` and its `mcp-server` fix (the manifest is the component
source here, so the bug cannot exist); KubeCoder-specific prose — the hardcoded project list in
`plan-writer`, the `cross-repo-tasks.md` required-reading pointer, the `../KubeCoderSpecs`
decision-index path, and `task-workflow.md`'s board-states section (tracker wiring is
host/project business); `update-docs`'s fan-out half (it belongs to the unbuilt `upkeep` plugin);
and `track_build.py`, which is CI-wait tooling, not workflow, and stays with its project.

## 2026-07-16 — the merge runbook becomes `/dev:merge-repos`

`runbooks/MERGING.md` → `plugins/dev/skills/merge-repos/SKILL.md`. Not a move: the runbook was
written against the template era and three of its load-bearing claims had rotted.

- **Phase 3 pointed at a source of truth that no longer exists** — "execute `AIWorkflow/ADOPTING.md`,
  apply its Step 1 copy-map and Step 2 variable substitution", at an absolute path predating `/work`.
  The plugin rework deleted the copy-map, the Jinja vars, and all of `scripts/`. Phase 3 is now two
  halves: project scaffolding sourced from `../DesignAssistant` (which still has it), then
  `/plugin install` + `/dev:onboard`. `build-all.py` and `run-suite` stop being copied scripts and
  become the manifest's `build:`/`test:` statements — the runner gates on `kc project test`, so that
  is where they belong.
- **One baked-in decision inverted.** The runbook said the four per-stack dev agents "stay
  per-subproject in `backend/.claude/agents/` + `frontend/.claude/agents/`". `/dev:onboard` deletes
  exactly those now. The skill says to leave them for onboard to sweep rather than hand-delete.
- **Learning #4 (the `orchestrator/pyproject.toml` Jinja vars) is gone** with the templates it
  described. The other eight survive; their sources re-point from the dead template to
  DesignAssistant.
- **Per-repo status moved to the issue tracker** (cards #234–236, one per remaining repo). Work
  state does not belong in a procedure that rewrites itself after every run. IoTSupport's run
  history is dropped — it is done, and git has it.
- `code_health` is not copied into new merges; the runbook was seeding the fork the archive is
  removing.

The skill is **finite**: DHCPApp, ElectronicsInventory, ZigbeeControl, then delete it. Its own
frontmatter and card #236 both say so.

## 2026-07-16 — `/dev:onboard`, and the allocator moves into the plugin

A seventh skill: `/dev:onboard` brings a repo onto the pipeline. In the template era onboarding was
mostly copying — skills, agents, scripts. The plugin ships all of that, so what is left is the parts
a plugin *cannot* provide: the project describing itself, and the cleanup of whatever it used before.

- **Retiring the old in-repo workflow** is by name, not by folder, and sweeps **every** `.claude`
  found recursively (older layouts put agents per-subproject). It deletes only what `dev`
  supersedes — including a `docs/**/task-workflow.md`, which the plugin now owns and which would
  otherwise sit there as a second, drifting contract. The four `upkeep`-era commands (`update-docs`,
  `refactor-audit`, `quality-*`) are explicitly **left**: `upkeep` is not built, so deleting them
  removes capability nothing restores.
- **The manifest's `test:` statements are the onboarding decision**, now that the runner gates on
  `kc project test`. A component that declares none is green by definition — right for a docs-only
  component, and the skill says so rather than inventing a gate.
- **The spec repo is scaffolded or reshaped, not assumed.** Preflight only checks the path is a
  directory, so a repo can pass preflight and still die at `/dev:triage` on a missing allocator or
  `slices/backlog/`. The bar is **shape, not contents**: the tree and its lifecycle folders, the
  `.gitignore`, the README `## Pending` list — plus whole superseded eras archived wholesale.
  Old-format slice *bodies* are explicitly left alone: `/dev:plan-slice` reads one and deals with it
  when it plans it, and reworking a slice nobody is planning is speculative effort spent without the
  context the planner will have. Numbers are never recycled or renumbered.
- **Done is machine-checkable:** `preflight.py --for run` exits 0.

**`allocate-next-slice.sh` moves into `plugins/dev/tools/`** and takes the spec repo as an argument
instead of deriving it from its own location. `/dev:triage` calls the plugin's copy, so a spec repo
carries none: N copies across N spec repos were N chances to drift, and the numbering space is the
project's while the algorithm is the workflow's. The repo's template-era `specs/` reference tree
(the last of the Jinja placeholders — `{{ project_short }}`, `{{ specs_repo_path }}`) is deleted
with it.

## 2026-07-16 — the six commands become skills

`plugins/dev/commands/<name>.md` → `plugins/dev/skills/<name>/SKILL.md`, one directory per skill,
each with a mandatory `name:` matching its directory. **Nothing about invocation changes:**
`/dev:triage`, `/dev:run-slice`, … resolve exactly as before, and every `${CLAUDE_PLUGIN_ROOT}`
reference, `argument-hint`, and `write-task`'s `allowed-tools` carry over untouched. Claude Code
loads skills and commands into one registry — the move is a layout change, not a behavior change.

The motivation is that `commands/` is the legacy path: Claude Code 2.1.211 tags it
`loadedFrom: "commands_DEPRECATED"` internally while skills load as `"skills"`. Skills also unlock
per-skill supporting files and `context: fork` if the pipeline ever wants them.

Verified against the running build rather than the docs (the network here resolves them to a
captive redirect): the binary's own strings confirm plugin-sourced skills are both user- and
model-invocable, `name`/`description` are the only required frontmatter, and `version:` is **not**
required. A widely-cited GitHub issue (#41842) claiming plugin `skills/` never register as slash
commands does **not** hold for this build — Anthropic's own `example-plugin` ships a skill whose
body states the two formats are "functionally identical … only the file layout differs."

## 2026-07-16 — the runner runs the gate; the tester becomes a fixer

Syncs the workflow changes KubeCoder validated after the plugin rework (its commits `ca1d5c1`,
`2d7c320`, `6f8a9c2`, `8b1d6b6`, `c88c3d8`, `d08d5ea`). The rework of 2026-07-12 migrated from
KubeCoder's `.claude/` + `tools/`, so that is this sync's baseline; everything KubeCoder changed
since is either here, or recorded below as deliberately not ported.

- **The runner runs the gate.** The `code-tester` agent is gone. Detecting green is deterministic —
  no session is spawned to learn the gate's color — and only fixing red needs a model, so a
  `test-fixer` spawns on red and its `clean` is confirmed by a gate re-run, never trusted. **A red
  gate cannot merge** (new bail reason: `gate_red`); red can stall a task, never ship it.
- **The gate is `kc project test --project <name>`, not a script path.** KubeCoder's
  `<project>/tools/run_tests.py` is a stopgap for exactly this by its own docstring, and
  `project-contract.md` already declared the seam — so the contract ported, not the path. It runs
  from the repo root: `kc` resolves `.kubecoder/project.yaml` against its own cwd with no upward
  walk. What "test" means for a component is the operator's call, declared in the manifest; a
  component that declares no statements is green by definition, and that is a valid answer, not a
  gap for the runner to second-guess. `kc` rejecting the component *name* is different — that is
  `protocol_failure`, since the name came from `kc project list`.
- **`grounding.md` replaces `focus_notes.md`.** The writer keeps a claim→source ledger for
  behavior-describing prose; the reviewer verifies citations instead of re-deriving every claim
  (slice 084: each fix round minted new false claims — a vague sentence sharpened into a precisely
  false one).
- **The review cap becomes a budget** (2 → 3, extendable by 2 grants to 5). A finding raised in the
  final round had its fix written but never re-reviewed; `another_round` buys the confirming round
  instead of merging it unseen (slice 082: 4 of 11 tasks, every one a real defect).
- **The plugin has tests.** KubeCoder's runner suite ports (23 tests), with the `kc` seams stubbed.
  It caught a real port defect immediately: `_task_state` must back-fill keys missing from states
  written before those keys existed, or any resume across this change dies on `KeyError gate_runs`.

Not ported, deliberately: `af72dfc` (adds `RETEST_PROMPT`, which `d08d5ea` then deletes — the
plugin never carried it); KubeCoder's `CLAUDE.md` changes (project facts with no plugin
destination — the plugin cannot ship a `CLAUDE.md` by design); and KubeCoder's `slice-dag.md`, where
the plugin is the fresher copy. `run-slice.md`'s `gate_red` route was authored here — KubeCoder's
own copy never grew one.

## 2026-07-12 — the workflow becomes the `dev` plugin (v0.1.0)

The slice workflow stops being templates you copy into a repo and becomes an installable Claude Code
plugin, `dev`, hosted in this repo's marketplace (`.claude-plugin/marketplace.json`). Instead of
copy-and-fill, a repo describes itself: everything that was a Jinja blank or a hardcoded per-repo
constant is now either a `kc` call or a short `CLAUDE.md` entry.

- **kc-native runner.** `task_runner.py`'s three project-specific seams collapse into `kc`:
  `PROJECT_DIRS` → `kc project list --output=json`; the `claude_session.py` wrapper (retired) →
  `kc session create-headless|send|status|end`; `FORCE_PROMPT_CACHING_5M=1` → `-e` on
  create-headless. `REPO_ROOT` now comes from `git rev-parse --show-toplevel` (the runner no longer
  lives in the target repo). Agents spawn namespaced as `dev:<role>`; consults spawn bare. Verified
  against the actual kc surface (KubeCoderSpecs slice 079): the flag is `--output=json`, and the
  status snapshot carries `sessionId` (empty until the first turn).
- **Plugin surface.** 6 commands (`triage`, `plan-slice`, `run-slice`, `write-task`, `slice-dag`,
  `arch-design`) → `/dev:*`; 8 agents; `task_runner.py` + a new stdlib-only `preflight.py`; contract
  docs (`task-workflow.md`, `project-contract.md`, `preflight.md`). All plugin-internal paths use
  `${CLAUDE_PLUGIN_ROOT}`.
- **Project contract.** `.kubecoder/project.yaml` + three machine-checkable `CLAUDE.md` lines
  (`Spec repo:`, `Slice testing strategy:`, `Design philosophy:`), enforced by preflight (profiles
  `--for triage|plan|run`). Issue-tracker + notification wiring is referenced generically; the
  concrete form lives in the host `~/.claude/CLAUDE.md`.
- **Repo rework.** `orchestrator/`, `project/`, `EXAMPLE.md`, and the retired `tools/ai_workflow`
  scripts are deleted; `MERGING.md` moved to `runbooks/`; `README`/`ADOPTING`/`AUTHORING` rewritten;
  the auxiliary commands + `documentation-model.md` parked under `plugins/upkeep/` as backlog for a
  planned second plugin.

Not yet live-tested against `kc` (no `kc` in the authoring env) — the operator validates on a real
slice. See `plugin-plan.md` for the full plan and open items.

## 2026-07-10 — #175: the task-runner workflow (developed in KubeCoder, not yet synced here)

The workflow's execution core moved from LLM-driven skills into a script. Developed and validated
in `../KubeCoder` first; this repo's templates (`orchestrator/`, `project/`, `tools/`) sync after
the validation slices. An adopting repo replays:

**New pipeline.** `/triage` → `/plan-slice` → `/run-slice` + `tools/ai_workflow/task_runner.py`.
Canonical contract: the target repo's `docs/conventions/task-workflow.md` (folder layout, verdict
schema, bounded loops, escalation ladder, session mechanics).

**Skills.**
- `/write-slice`, `/major-change`, `/minor-change` — **deleted.** Triage's output folder *is* the
  slice (`slices/NNN_slug/slice.md`; triage allocates the number, opens the Kanban card, archives
  source cards, adds the README Pending line). The major/minor distinction no longer exists —
  planning is slice-level, execution is uniform per task.
- `/plan-slice` — **new**: interactive session that dispatches plan-writer/plan-reviewer to break a
  slice into 3–6 ordered, project-local tasks (10 the hard limit — the cap is per slice, not per
  project as pre-#175); verifies requirement fidelity itself; seeds `verification.json`. Task
  folders are `tasks/NN_slug/` — two-digit ids, visually distinct from three-digit slice numbers;
  a letter suffix (`04a`) inserts a task between existing ones mid-run.
- `/run-slice` — **rewritten thin**: preflight → launch the runner as a background shell → handle
  bail-outs (`bailout.json` reasons → `/write-task` + `--resume`, or defer to operator) →
  close-out. It never drives the dev loop.
- `/write-task` — **new**: author one task folder from a findings / missing-task write-up.
- Every skill carries a self-sufficient `description:` frontmatter (the root CLAUDE.md skill list
  is gone).

**Agents.** All dev agents rewritten to the thin shape (identity + output contract + bounds); the
output contract is literally the verdict-file schema. `code-tester` (Sonnet, fresh per round,
fixes-and-closes trivial issues) and `test-agent` (Sonnet, verification handovers) are new;
code-writer loses testing (keeps lint); reviewers describe problems and never prescribe fixes;
tester and code-reviewer receive `slice.md` and the task's `plan.md` as requirements — framed, not
raw: the tester mines the plan for coverage but never treats it as verified truth, the reviewer
judges outcomes rather than approach (plan deviation that meets requirements is not a finding;
missed planned edge behavior, broken pinned interfaces, and silent substitutions against
`slice.md` are), and both are scope-guarded (the slice spans tasks; only this task is under
test/review). The plan-writer's companion JSONs
(`requirements.json`, `file_map.json`, `test_plan.json`) are gone. The external-surface-probe /
substitution-test blocks are deleted in favor of a one-line grounded-claims rule. "Never work
around environmental problems — report `blocked` and stop" is now a bound in every agent.
`slice-verifier` (the `/run-slice` close-out check, on probation) keeps its evidence discipline
unchanged but is reframed for the new pipeline: the log is seeded by `/plan-slice`, not maintained
by an orchestrator, and its artifact blindness now names the current slice-folder files — it
deliberately does NOT read `slice.md`/`plan.md` (unlike the dev-loop tester/reviewer), staying the
one check with no shared framing.

**Tools.** `claude_session.py` gains `--cwd`, `--agent`, `--model`, quiet-by-default stderr
(`-v` restores) and a `run_claude()` library entry; `task_runner.py` is new (spawns fresh
`claude --agent` sessions with `FORCE_PROMPT_CACHING_5M=1`, cwd = the task's project);
`track_build.py` gains `--diagnose`. A session that ends without its verdict file or with
uncommitted changes gets **one resume-nudge** to finish its protocol; after that a missing verdict
is `blocked` and a dirty tree bails — the runner never `git add -A`s an agent's leftovers.
Runner output goes to `<slice>/log.txt`, never stdout (`-v` echoes it) — the orchestrator reads
exit code + `state.json`/`bailout.json`, so no progress stream ever floods its context. A crashed
run (host restart, quota stop, Ctrl-C) reattaches on `--resume`: `state.json` tracks the in-flight
session id and the worktree is preserved for it (consults and timed-out sessions never reattach).
The post-task checkpoint consult is unconditional (`--no-checkpoint` removed), and preflight fails
hard (exit 2, both in the runner and `scripts/preflight.py`) on a dirty working tree.

**CLAUDE.md set.**
- Root: stripped to a generic project brief (orchestrator guidance, skill list, agent management,
  deploy/cexec mechanics, Trello/notification detail all removed). Keep: slice-workflow pointer,
  specs layout, commit discipline + the push-green-light hard rule, design philosophy summary,
  conventions, issue-tracking pointer.
- Deploy happy path → `docs/operations/deploy-operations.md`; cexec was already in worker docs.
- Two-board Trello model + MCP ids + card conventions + push-notification rule →
  `~/.claude/CLAUDE.md` (host-global; cross-project by design). **Deferred:** the same content
  into the env-pod CLAUDE.md template (worker `internal/claudemd` — application code, needs a
  task).
- Subproject CLAUDE.mds: Design-philosophy → `docs/conventions/change-discipline.md` (now with the
  internal-vs-external boundary), Decision-making sections deleted, testing policy notes → each
  project's `docs/testing.md`, worker's VS-Code packaging → `worker/docs/vscode-extension.md`.
- "Never dismiss failures as flaky" lives in code-tester/test-agent definitions + a run-slice
  note, not CLAUDE.md.

**Docs.** `documentation-model.md`: diet rule ("state every fact exactly once; no recap
sentences; 100 lines is big") + primary doc keeper is `/plan-slice`.

**Deploy verification → a project slice test plan.** `/run-slice`'s close-out no longer hardcodes
the push/CI/live-test dance. The skill is repo-agnostic (this repo owns it; targets hold a copy), so
its deploy-verification section is now a **bare pointer**: run the project's slice test plan once the
tasks are merged. All testing-strategy detail — whether it pushes, what it checks, how findings
resolve — lives in the **project-owned** `docs/operations/slice-test-plan.md`. An adopting repo
**authors its own** such doc and repoints the deploy-verification line in
`docs/conventions/task-workflow.md`. KubeCoder's plan (the worked example, because it has no isolated
per-slice test environment): one operator gate → fetch/rebase/push/CI → live tests on prd, findings
fixed in-slice only on significant breakage (minor/cosmetic defer to a related slice; doubt to the
operator), so each in-slice fix means another push-and-test gate.

**Known open items.** Skill-vs-agent-type naming collisions (`arch-design`, `update-docs` vs
`update-architecture`) unresolved; Trello **Accepted** list is vestigial (triage now archives
source cards directly); docs-diet splitting of oversized topic docs (`config-model.md` etc.) not
yet done; env-template CLAUDE.md addition deferred (above).
