# Improvements — the case-study catalogue

The specific changes the workflow made, each written as a case: what went wrong, what showed it,
what the plugin does now, and what a later read found. It is the evidence behind the rules in
[`principles.md`](principles.md) and the eras in [`history.md`](history.md); the mechanics live in
the contract docs under [`plugins/dev/docs/`](../../plugins/dev/docs/) and are linked, not restated.
The close-out report has its own doc, [`reporting.md`](reporting.md); the measurement tooling and
the research method are in [`measurement.md`](measurement.md); the papers behind several cases are in
[`literature.md`](literature.md). Every version cited has an entry in
[`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md); every slice is KubeCoderSpecs unless marked
Ansible. Labels: **measured** is a number from the record, **ruled** an operator decision,
**untested** something built or proposed and not yet read.

Each case has four parts — **Incident**, **Evidence**, **Change**, **Readout** — and "not yet read"
is a legitimate fourth part: most 0.9.x cases are younger than the slices that would read them.

## 1. Review economics

### The runner runs the gate; the tester becomes a fixer (2026-07-16)

**Incident.** The original task runner spawned a Sonnet `code-tester` session every round to learn
whether the suite was green, and the review loop's cap of 2 let a finding raised in the final round
have its fix written and merged without anyone re-reading it.

**Evidence.** Slice 082: 4 of 11 tasks merged with a real defect from exactly that unseen last fix
(the entry's review-budget bullet). The gate bullet itself names no slice: detecting green is
deterministic, so a session spawned to learn the gate's colour was a model doing a script's job.

**Change.** Detecting green is deterministic and needs no model: the driver runs `kc project test`
itself, spawns a `test-fixer` only on red, and confirms the fixer's `clean` by re-running the gate,
never by trusting it. A red gate cannot merge (`gate_red`), and a gate-fix round is capped at 3
(`GATE_FIX_CAP` in `run_loop.py`; [`run-loop.md`](../../plugins/dev/docs/run-loop.md) § The per-phase
round). The same sync made the review cap a budget — 2 → 3, extendable by two grants to 5 — so
`another_round` could buy the confirming review instead of merging a last-round fix unseen.

**Readout.** The shape held through every later version; the `code-tester` never came back. The
gate stays test-only by a later ruling (v0.7.5, Triage #399): the writer lints once itself, the
loop-tail sweep runs lint + build + test per component, so a per-phase lint would tax every phase to
save the one that fixes it.

### The funding consult with a rising bar (v0.3.0, v0.4.0)

**Incident.** The 07-16 sync had made the review cap a budget — 3 rounds, extendable by two grants
to 5 — and v0.3.0 replaced it thirteen days later; the changelog records the replacement without
naming an incident.

**Evidence.** The 2026-07-29 sync records the replacement without a fresh number; the shape it was
built against is `workflow-improvements/ANALYSIS.md`'s slice 052 (6 plan-writer, 6 plan-reviewer,
9 code-writer and 8 code-reviewer rounds on one slice). What the bar produced is **measured** later:
over slices 155–170, round-1 `issues` was 17 % (12/71) against a 24 % baseline, 15 blocking findings
were raised and 0 refuted, and rework sat at 2–19 % of a slice (median ≈ 7 %)
([`interventions.md`](../research/interventions.md) § 12).

**Change.** Round 1's fix is automatic; from round 2 every `issues` verdict goes to a fresh bare
consult that judges the findings against a bar that rises per round — blocking-only, then
Blocker-only, then critical-only — and a fix range that touched no production code applies the next
round's bar a step early (`_review_bar` in `run_loop.py`). The old cap survives only as a backstop
(`REVIEW_ROUND_CAP = 5`) at which funding is withheld. Fix rounds are fresh sessions: a resumed
round's accumulated context cost ≈ 2.2× per turn (v0.3.0).

**Readout.** Catalogue entry C3 recorded the rising bar as "in place → keep" when it was catalogued
on 2026-08-14 (`docs/research/status.md` § C3) — a decision record, not a measured result. No phase in
the 149–153 grounding sample went past review round 2 (`interventions.md` § 1).

### Fix rounds stop relitigating comments (v0.4.2)

**Incident.** Ansible slice 013 — $45 and 3 h wall for a small slice — spent the second rounds of two
of its three phases on comment wording: the reviewer reported advisory prose findings with forensic
evidence (Jenkins build-history archaeology to falsify one sentence, a git dig to date a dead doc
anchor), the fix round's "resolve every finding" pulled every advisory in beside the one blocking
finding, and the comment fixes became the delta review's subject and bred new comment findings.

**Evidence.** The cost breakdown of slice 013 (Ansible) in the v0.4.2 entry; the pre-0.4.2 baseline
had comment and prose findings at ≈ 49 % of all findings (28 of 57 across slices 149–153,
`interventions.md` § 1) — **measured**.

**Change.** Three prompt-level bounds: fix rounds resolve blocking findings only; delta reviews
verify blocking resolutions and stop re-deriving premises the prior round proved; comment and prose
findings are advisory by default and earn one sentence, not research — "harm from following the
words is what promotes one to blocking". Verdicts hinge on the impact tag: `signoff` means nothing
blocking.

**Readout.** $0 prose rework for 27 consecutive slices since 0.4.2 (143–170), every comment-prose
finding advisory, one sentence, no relitigation (`status.md` § B2, 2026-08-22) — **measured**.

### Anchored blocking findings, and the fix round demonstrates failure first (v0.4.3, C1 + C2)

**Incident.** A `blocking` tag had a loose severity bar ("failing-input logic or a test sketch"), so
a reviewer could block on a hypothetical, and a fix round changed code before anyone had shown the
finding was real.

**Evidence.** The research corpus, not a slice: in the overcorrection study's false-rejection
taxonomy, 48.2 % of wrong rejections were unfalsifiable "logic error" claims, 14.1 % hallucinated
requirements and 13.2 % asserted boundary errors — 87 % of the false positives would fail an anchor
bar — and condition-anchored verification cut wrongly-overturned correct answers from 9.1 % to 2.5 %
in ProCo (`interventions.md` § 6 C1; [`literature.md`](literature.md) has the papers). The
instrument that would show the plugin's own rate did not exist until the same release (I1, below).

**Change.** A `blocking` impact tag requires one of five recorded anchors — failing test or command,
repro trace, analyzer output, requirement-to-code contradiction, coverage gap against a named
acceptance criterion; no anchor is advisory by construction. A fix round witnesses each
executable-anchor finding before changing code, the failing test rides the fix as its regression
test, and a finding that cannot be made to fail is **refuted** with evidence, never relitigated
([`code-reviewer.md`](../../plugins/dev/agents/code-reviewer.md); `run-loop.md` § The per-phase
round).

**Readout.** 15 blocking findings on 155–170, every one anchored (contradiction, repro-trace,
failing-test), 0 refuted, every one re-verified by the round-2 reviewer — blocking precision 15/15 by
the evidence gate, which met I3's ≥ 80 % bar without a sampled audit (`status.md` § I3, § C1, § C2,
2026-08-22) — **measured**. The refute path has never fired; it stays because it is the instrument
the precision claim rests on.

### Findings telemetry (v0.4.3, I1)

**Incident.** Problems B (comment churn) and C (work amplification) in the first research briefing
could only be measured by hand: the grounding sample of five slices took "38 tool calls of grep +
manual classification" (`interventions.md` § I1).

**Evidence.** Same section; no per-finding record existed in `state.json`.

**Change.** The reviewer's verdict reports every finding machine-readably — id, severity, impact,
category, anchor — and the driver persists the list on the history row, beside a fix round's
`refuted` list ([`runner-state.md`](../../plugins/dev/docs/runner-state.md)).

**Readout.** The 155–170 closure read (sixteen slices) was one script over the I1/I2 fields, "no
transcript archaeology" (`status.md` § I1, 2026-08-22). Anchors are recorded only for blocking
findings, a stated limit.

## 2. Comments and prose findings

### Comments state what a gate can witness (v0.4.5, B1)

**Incident.** The coder's "invariants only" comment rule had no verifiability criterion, so comments
predicted ("will", "may", "should") and reviewers graded the strength of the prediction — the
substrate the will→may findings of research run 1's problem B grew on (`research.md`).

**Evidence.** The ≈ 49 % comment-prose share above; the Huang et al. finding that models cannot
reliably judge unverifiable claims, so verdicts on them are noise (`interventions.md` § 5 B1).

**Change.** A comment must state a condition code, a test or a gate can witness; predictions and
strength-graded claims are deleted, not hedged; load-bearing warnings ("must run before X") are
invariants and stay ([`code-writer.md`](../../plugins/dev/agents/code-writer.md) rule 6).

**Readout.** Comment-prose findings 43/114 (38 %) on 155–170 against ≈ 49 % before, all advisory
(`status.md` § B1) — **measured**. On slice 146, the first on the rule, 1 of 4 findings (25 %).

### A prose finding must show the text is wrong (v0.4.5, B4)

**Incident.** Reviewers reported meaning-preserving wording drift as findings — different words,
not wrong ones.

**Evidence.** Wataoka et al. on self-preference being a familiarity effect rather than
self-recognition: same-model separation does not neutralise a stylistic preference, so the rule has
to be a semantic bar, not a different reviewer (`interventions.md` § 7 D1, § 5 B4).

**Change.** A prose finding must show the text is contradicted by the code or the spec; wording
that preserves meaning is not a finding
([`code-reviewer.md`](../../plugins/dev/agents/code-reviewer.md)).

**Readout.** Held across 155–170: the prose findings seen were wrongness findings (`status.md` § B4,
2026-08-22) — **measured**, by reading, not by an instrument.

## 3. Planning

### The plan loop stops iterating (v0.4.0)

**Incident.** The v0.3.0 plan loop ran fresh writer/reviewer rounds against a stored budget of 4,
`--grant` to extend, `--reopen` to re-enter — a loop that could spend its budget on the same
disagreement.

**Evidence.** `ANALYSIS.md`'s slice 052 (6 + 6 planning rounds) is the shape; the v0.4.0 entry gives
no fresh count for the plan loop specifically.

**Change.** A writer pass, one reviewer pass, exit: findings go to the operator, whose rulings land
in `plan.md` and drive exactly one fix pass; exit 0 is refused without a reviewer verdict on file
([`plan-loop.md`](../../plugins/dev/docs/plan-loop.md)).

**Readout.** Only 3 of 30 plan reviews in the close-out era signed off clean; the rest returned
`issues` or questions (`docs/research/risk-review-2026-08-27.md` § 6) — the single round is doing
work, which is why plan review was ruled out as a risk-skip candidate.

### Task shape and the question-gated research budget (v0.4.3, A1 + A2)

**Incident.** The planner deep-dived regardless of task size: slice 153 spent $27.72 — $16.17 on the
planner core (the interactive session, plan-writer and plan-reviewer), $11.55 on research
sub-agents, 34 % of the slice — before any code existed, on a slice
whose `slice.md` said "you are not designing anything" (`interventions.md` § 1; v0.4.3).

**Evidence.** Planner share 18.6 % / 26.9 % on slices 144/145 (I2 in `a3-plan.md`); the earlier
attempt to grade tasks by complexity upfront had "produced poor results" (`research.md` problem A),
so routing was ruled out (`interventions.md` § A4, a decision record).

**Change.** The plan-writer declares `pre-settled` / `localized` / `cross-cutting` in `plan.md`
before investigating, justified in one line from `slice.md` facts; `pre-settled` forbids research
sub-agents and repo sweeps; at any shape a research dispatch must name the open question it settles
([`plan-template.md`](../../plugins/dev/docs/plan-template.md) § Task shape;
[`plan-writer.md`](../../plugins/dev/agents/plan-writer.md)). The plan-reviewer checks the
declaration.

**Readout.** Plan-writer research $0 on every pre-settled slice in 155–170 and four question-named
surveys ($6.76) on slice 170's honestly declared `cross-cutting` plan; planner absolute $14–27 across
155–170, the share a floor effect on small slices (`status.md` § A1, § A2, 2026-08-22) — **measured**.
The 3–13 % research shares still in the cost readout are the interactive refinement session's
Explore agents, outside the gate — see [`plan-refinement.md`](plan-refinement.md).

### Planning dispatches carry the change-discipline pointer (v0.9.10)

**Incident.** The `design_philosophy` pointer rode every run-loop dispatch but never a planning one —
the plan-writer and plan-reviewer, the two roles that must catch what the discipline demands of a
plan, were never told the doc exists.

**Evidence.** Triage #738, measured three times in one lineage: KubeCoder's change-discipline doc
requires a wire-contract (`api/*.md`) correction in the same change as the code, so a plan must
carry it in the implementing phase — and slices 142, 179 and 184 each rediscovered that by hand
(184's plan missed it; the plan reviewer caught it).

**Change.** All three plan-loop prompt templates carry the same `PHILOSOPHY_LINE` the run loop
formats, resolved from `.aiworkflowrc`; a config without the pointer degrades to no line
(`plan_loop.py`). The project-side half: the standing rule moved into the doc the pointer names, and
the doc phase's procedure gained a verify-never-own bullet so a contract claim the diff falsified
becomes a finding instead of shipping silently (the v0.9.10 entry names the KubeCoder commit; it is
not in this pod's KubeCoder checkout).

**Readout.** Not yet read.

### `Creates:` declares a new component (v0.9.12)

**Incident.** Slice 181 stood up a second Node project and could not target it: `run_loop.py`
snapshotted `kc project list` once at run start, so a component a phase registers stayed invalid for
the whole run. The plan faked every desktop phase onto an existing component with hand-run
`kc project test --project vscode-desktop` Gate paragraphs, and the driver's own gate never ran the
new suite (#746, that run's close-out S1).

**Evidence.** The plan and the gate logs of slice 181; the $293.03, 14-phase, 70-session run is the
most expensive in the costed corpus (its `state.json` cost block).

**Change.** The driver re-reads the component set at every plan load — after every merge — and the
loop-tail sweep reads every root's manifest fresh. A phase that registers a component says so with
a `Creates: <component>` line under `Target:`; the declaring phase targets its own creation
optimistically, later phases pass validation on the declaration's word, and a declarer stamped DONE
whose component never appeared is a structure error naming both phases
([`plan-template.md`](../../plugins/dev/docs/plan-template.md)).

**Readout.** Not yet read; no slice since has created a component.

### The seeded plan header keeps `###` for phases (v0.9.4)

**Incident.** Slice 167's seeded plan carried two `###` sub-headings inside its requirements
section, because the seeding step named the sections to write and never the heading levels, while
"every `###` is a phase" lived one link away in `plan-template.md`.

**Evidence.** Nothing shipped broken: the strict parser caught it at writing, the plan-writer demoted
both to `####`, and `_verify_plan_parses` gates exit 0 against exactly this — but the writer paid for
a correction it should not have had to make.

**Change.** The seeding step in `/dev:plan-slice` says `###` is the plan-writer's alone and
sub-structure is `####`.

**Readout.** No recurrence recorded.

## 4. Reporting

The four cases here are summaries; [`reporting.md`](reporting.md) has the design, the counts and the
open readouts.

### One close-out report replaces per-finding cards (v0.5.0)

**Incident.** Every plan or run agent that noticed something out of scope filed a tracker card, from
five uncoordinated write paths; Ansible slice 007's run produced eleven `state.json["cards"]`
entries that the operator merged into ten cards, of which one was a must-act and one a real
cross-project bug (`docs/research/close-out-report.md` § 1.1). Counts on KubeCoderSpecs runs reached
24 entries on one slice (§ 1.2).

**Evidence.** Same design note; the finding-suppression gates that existed to limit carding
("worth a card", "no fix proposals") were the visible symptom.

**Change.** Everything the loops will not act on goes into one `close-out.md` per slice in one
fixed shape, as it happens; the run's only tracker output is one card pointing at the report; the
operator dispositions entries in one sitting and `/dev:close-out` executes
([`close-out.md`](../../plugins/dev/docs/close-out.md)).

**Readout.** Six finished reports across two projects: 76 entries, 22 struck in-run, 14 progressed by
the operator, 7 tracker cards — against ten cards for one slice under carding (v0.5.3) — **measured**.

### The generation bar is priced against one word (v0.5.1)

**Incident.** Slice 146's completion consult appended a phase for a test nit — $4.02 with the consult
it forced — reasoning "cheaper to fix than to card", a bar written when the alternative to a phase was
a tracker card the operator had to open and relate to nine others.

**Change.** The first generation appends only work the plan owes and no phase delivered, priced
plainly: a phase costs an executor round, a review round and the consult the generation forces; a
close-out entry costs the operator one word (`GENERATION_BARS` in `run_loop.py`; `run-loop.md`
§ The generation bar). The second generation appends blocking work only; a third pending generation
bails to the operator (`GENERATION_CAP = 2`).

**Readout.** 0 appended phases on 155–170 (`interventions.md` § 12); across the 44 costed slices
144–196, 2 slices appended a phase (their `state.json`) — **measured**.

### The tool is the only pen (v0.6.0)

**Incident.** Entries typed by hand off a head comment drifted from the shape; each author read the
whole file — 42 KB by the doc phase of a long slice — to add one entry; and in slice 154, 10 of the
16 Bugs were struck in-run and sat, full-bodied, ahead of the six the operator had to decide on.

**Change.** `close_out.py` mints every entry, note and strike, lists without bodies and renders
reading order idempotently — live entries first, struck ones folded last. No dedup and no
disposition parsing, deliberately.

**Readout.** The head comment could then shrink to seven lines (v0.9.3); a later friction — every
session's first `list` call failing on the report path — was measured at 225 of 1,248 fumble turns
and fixed in v0.9.6 (§ 5 below).

### Every claim carries its evidence class (v0.5.4)

**Incident.** The entries later refuted or overtaken (156 B4, 157 B1) and the one the operator called
"very dense" (155 B2) were read, not witnessed, and said so only in prose.

**Evidence.** The overcorrection study: false rejections are claims with no falsifiable counterexample
(87 %); symptom claims hold (93–100 %), cause attributions are the half that does not (44–75 %)
([`literature.md`](literature.md)).

**Change.** `**Provenance:**` opens with `witnessed` or `read`; the body leads with the symptom and
states a cause only where shown; a strike names the commit and what was re-run
(`close-out.md` § Entry rules).

**Readout.** Not read as an instrument; the close-out skill's behaviour on a challenged claim (quote
the entry's own evidence rather than agree) is the untested half.

## 5. Cost and context

### The cost readout (v0.4.3, I2)

**Incident.** Cost trends were read by transcript archaeology; the template-era analysis had needed
a regex over raw transcripts to guess which slice a session belonged to (`slice_costs.py`, retired
in v0.4.0).

**Change.** `slice_cost.py` (in the plugin since v0.4.0, superseding `slice_costs.py`) prices a slice
from its own `state.json` history rows and the transcripts they name; v0.4.3's I2 added the derived
ratios — planner share, research share and rework share (rounds ≥ 2 + consults) — and
`--write-state`, which appends them as `cost`; `/dev:run-slice` runs it at close-out, so the close-out
header carries the run's own numbers.

**Readout.** The block is on every run from 155 on; a round whose session returns no verdict leaves
no history row and is unpriced — slice 170's test r1 was ≈ $8.27 by hand (`status.md` § I2). Over the
44 costed slices 144–196 the median slice is $61.91 (p25 $44.37, p75 $99.81) with a median of 5
phases; see [`measurement.md`](measurement.md) for the table.

### Every run says what its turns did (v0.9.5, T2)

**Incident.** The bill is charged per model invocation, and every role sits at 50–145 k tokens of
context re-read at the cache rate, so a turn costs nearly the same whatever the role — yet a run
recorded what it cost, not what those turns did.

**Evidence.** The research profiler's replay of 809 sessions across 32 slices put `orient-read` —
reading to find one's bearings — at 36.6 % of headless turns and 32.9 % of their cost
(`docs/research/context-profile-2026-08-23.md` § 13) — **measured**.

**Change.** `turn_profile.py` ships in the plugin: it puts each turn in exactly one of thirteen
classes by what its calls did, counts the reads chained inside one Bash command, and marks the read
turns a perfect batcher would have folded; `slice_cost.py` prints the per-role turn table and
`--write-state` stores it as `cost.turns`. Research's `context_profile.py` imports the plugin module
and regenerates the 32-slice profile byte-identical.

**Readout.** Avoidable turns (`retry + fumble + batchable(strict)`) run 9–18 % of a slice's turns
(median 12 %) on the 22 slices carrying the block (their `state.json`, 2026-09-02) — a floor, not a
target.

### Auto-memory and bundled skills leave the prefix (v0.9.6, T3a)

**Incident.** Every dispatched session started at 31–34 k tokens of context, paid again on every
turn, and part of it was listings no headless role ever used.

**Evidence.** In 809 corpus sessions no dispatched role read or wrote a memory file, and none invoked
a bundled skill (v0.9.6) — **measured**.

**Change.** `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1` in the
`SPAWN_ENV` every `create-headless` carries
([`agent-dispatch.md`](../../plugins/dev/docs/agent-dispatch.md) § Spawning).

**Readout.** `ctx1` — context on the first turn — dropped 3.3–4.0 k tokens for every role
(code-writer 32,172 → 28,825), ≈ 10 % of the prefix on every turn (v0.9.6) — **measured** on one
trivial dispatch per role.

### `close_out.py` takes the report's path (v0.9.6, T3b)

**Incident.** Every dispatch named the report's *path*, so that is what an agent had in hand — and the
tool took the slice directory. The first call was `list <report>`, which failed, then `--help`,
then the retry.

**Evidence.** 225 of the 1,248 fumble-and-retry turns the turn taxonomy counted were on this one
interface (v0.9.6) — **measured**.

**Change.** Any `.md` positional resolves to its directory, and the dispatch line shows the whole
invocation.

**Readout.** Slice 190's `cost.turns` shows 28 retry/fumble turns in 944 (3 %) across all roles;
the corpus's all-role figure was ≈ 4.9 % (1,393 of 28,176 turns; `context-profile-2026-08-23.md`
§ 13). Not isolated to this fix.

### The writer's dispatch carries the plan, digested for its phase (v0.9.7, T4)

**Incident.** Every code-writer session opened with "read the whole plan" — 15–74 KB, the top
orientation read in the corpus — and spent a median 14 turns before its first edit re-deriving
what the driver already held: which phase is its own, what earlier ones settled, what the criteria
say.

**Evidence.** `orient-read` was 28 % of the writer's turns and the largest class in the loop, and
182 of 184 corpus writer sessions read `plan.md` before editing (`turns-plan.md` § T4;
`t4-read-2026-08-23.md`); context at first edit median 79,655 tokens
(`context-profile-2026-08-22.md`) — **measured**.

**Change.** The driver renders a phase digest into every executor round's prompt, rebuilt per round:
the slice's intent paragraph, `## Requirements / rulings` and `## Not in scope` verbatim, this
phase's section whole, earlier phases' done-records read from their `**Done (P<id>).**` opener (not
their phase text, the near-miss distractor), later phases' headings and targets, every acceptance
criterion, and `git diff --stat` of what earlier phases changed (`build_phase_digest` in
`run_loop.py`; `run-loop.md` § The per-phase round). The done-record opener became a rule: it was
universal already, 296 of 296 done phases.

**Readout (preliminary, still validating).** Over 296 plan phases the digest is 30 KB ≈ 7.7 k
tokens at the median (p90 57 KB) against a 45 KB median plan; done-records run 31 lines against
their ~25-line cap, 77 % over it. On the first four slices (173/174/175 on 0.9.8, 179 on 0.9.7):
whole-plan reads before the first edit 0 of 16 writer sessions; writer $/phase $2.82 against $4.83
in the corpus's 2–4-phase band, −40 % pooled — but the median round-1 writer session only −8 %
($2.35 vs $2.56), the pooled gain being the absent long tail (max 50 turns vs 150); the digest
measures ≈ 9–10 k tokens on the real dispatch (≈ 3 chars/token, not 3.9); quality instruments all
inside baseline (refuted 0, gate-red 0, abstentions 0)
([`t4-read-2026-08-23.md`](../research/t4-read-2026-08-23.md); `status.md` § T4). Confound: Claude
Code 2.1.241's writers made zero Read/Edit/Write tool calls in 16 of 16 sessions. On the 22 costed
slices since (0.9.7+), the per-slice median of code-writer turns before the first edit has a median
of 10.5 (p25 7, p75 14; `cost.turns.by_role.code-writer.orient_turns`, computed 2026-09-02) against
the corpus's per-session median of 14 — a median of medians, so indicative rather than a
like-for-like before/after ([`measurement.md`](measurement.md) § The corpus today).

### The prefix trim finishes: no skills, no MCP servers but the test-agent's (v0.9.8, T3a)

**Incident.** v0.9.6 left ≈ 3.6 k tokens it could not reach — the plugins' skill descriptions and the
operator's MCP servers' tool names — pending a KubeCoder change to pass claude flags through
`kc session create-headless`.

**Evidence.** The test-agent drives CI through Jenkins (118 calls in 21 of 64 sessions); every other
headless role reached an MCP server in a handful of ~1,100 sessions and invoked a skill twice in 809
(v0.9.8) — **measured**.

**Change.** Every dispatch adds `--disable-slash-commands`; every one but the test-agent's adds
`--strict-mcp-config` with no `--mcp-config` (`SPAWN_FLAGS` / `spawn_flags()` in `run_loop.py`).
The plugin keeps the test-agent's servers whole rather than by name, because the servers are the
operator's and the plugin names no project's tooling.

**Readout.** `ctx1` 24,488 (code-writer), 25,040 (reviewer), 25,553 (test-agent), 23,966
(doc-writer), 25,494 (consult) — another 2.8–4.4 k off v0.9.6, 7–8 k off the corpus's 31–34 k, on
every turn (v0.9.8) — **measured**.

### The doc-writer's dispatch: diff on disk, plan digested whole, then yield (v0.9.9)

**Incident.** Three doc-writer sessions read turn by turn (186: 65 turns / $7.65; 184: 78 / $8.40;
170: 192 / $33.28) showed three defects in the fixed stages. The survey sub-agents were a pure loss:
every Explore report arrived 18–49 turns after dispatch, past the writer's first edit, because the
writer never ended its turn to wait — it re-derived the survey by hand (46–66 % of the paths it read
after dispatching were its sub-agent's) and then carried a report it no longer needed, 15–21 % of
each session. The diff round-tripped through disk — one 26 k-char diff sliced three times. And the
tail's mechanics were discovered, not given: `close_out.py --help` fumbles, a previous slice's report
read for the Summary's style, the plan read whole at intake and carried on every later turn
([`doc-phase-plan.md`](../research/doc-phase-plan.md) § 1) — **measured**.

**Change.** The doc-writer dispatches the survey and ends its turn with nothing else in flight;
`agent-dispatch.md` § Nested delegation carries the rule. The dispatch carries the slice's diff on
disk, one file per touched repo, over the repo's slice base to its base branch; the plan digested
whole from every phase's done-record; and the close-out verbs with argument shapes rendered from
`close_out.py`'s own parser so the block cannot drift from the CLI.

**Readout.** The plan estimated 15–25 % off the doc-writer; the read is `t4_readout.py writers
--role doc-writer` on the first two slices this reaches — not yet read in this checkout. Phase 2 of
the plan, a coordinator with per-scope units, shipped as 0.9.14 and was read on nine slices against
the round-1 code-writer's spend: about 2x per phase of shipped work at matched size, ≈ 1.5x per
file, 22 % of its spend lost to waiting gone wrong. Reverted as 0.9.29; the reconcile pass, the
unverified-claims self-report and a two-agent survey cap survive in the single writer
(`doc-phase-read-2026-09-04.md` § 5–6) — **measured**.

### Two-part done-records (0.9.17 — not in this checkout)

**Incident.** Done-records averaged 31 lines against a ~25-line cap (v0.9.7), and the digest carried
every earlier record whole; on slice 181's 14 phases the writer's dispatch grew from 34 k to 65 k
characters between P1–P3 and P10–P14. The operator's words on reading 181's P8 record: "we're
polluting the start of the context".

**Change (unconfirmed here — from the operator's session notes; 0.9.14–0.9.20 live in another
environment's checkout).** A done-record is a `**Done (P<id>).**` summary paragraph plus a `Later
phases:` list, then the record; the phase digest carries the summary, the doc phase's slice digest
the whole; a record without the list rides whole and is logged.

**Readout.** Untested — to be read on the next slice with seven or more phases: dispatch size by
phase index, pre-edit plan reads on large plans, and the log's "carried whole" count.

## 6. Git and safety incidents

### One driver per slice, and a branch reconciled against its record (v0.9.1)

**Incident.** Slice 148's P2 gated green on commit `6373316`, and round 2 started from a tree with
none of that work while `state.json` still pointed at the dead sha (Triage #610).

**Evidence.** The forensics: two drivers were running slice 148 at once, in two environments. The
slice folder is on the spec repo, the mount every KubeCoder environment shares; `/work/KubeCoder`
is not. Both drivers wrote one `log.txt`, one `state.json` and one `phases/**` while branching two
different checkouts; the second, resuming a record that said P2 was mid-review, found no
`phase/148-P2` in its own repo, treated it as a fresh phase and cut the branch from `main` in
silence.

**Change.** `run.lock`, a `flock` on the slice folder held from start to exit — a second driver exits
2 naming the holder — and the branch reconciled against its record before every reset and after
every executor round: every commit the driver recorded must still be on the branch; missing and
carried by the base means the merge landed and the run died before the record caught up, so the
resume stamps the phase; carried nowhere is the new `lost_work` bail
([`runner-state.md`](../../plugins/dev/docs/runner-state.md) § Resume and crash recovery).

**Readout.** One `lost_work` bail in the 44 costed slices: slice 194's P9 (2026-09-01, its
`state.json`) — the guard fired instead of rebuilding the branch from base; what lost the commits is
not in the state file.

### A plan can hold a repo's push (v0.8.0)

**Incident.** Slice 135 held `../HelmCharts` by operator ruling (a push there deploys dev and prd
together). The test agent honoured it, was nudged twice by the blanket push check, the driver bailed
`unpushed` — whose message read as an instruction to push — and the run session pushed 38 seconds
later: `IaC/HelmCharts` #5668 deployed both stages and `kubecoder@prd` crash-looped (Triage #445).

**Evidence.** The build number and the bail message in the entry; the ruling existed only as prose
in `plan.md`, invisible to the driver.

**Change.** `plan.md` gains `## Push holds`, the one `##` section the run loop reads; held repos are
left out of the push check, named in the test phase's dispatch as a deterministic fact, and reported
as one Outstanding-actions entry each instead of nudged and bailed. A hold bullet the parser cannot
read is a plan structure error, because a hold missed silently is a repo the driver pushes
(`plan-template.md` § Push holds).

**Readout.** No recurrence recorded. `/dev:plan-slice` and `/dev:run-slice` both say a ruling
forbidding a push needs its machine-readable half.

### The loop-tail gate sweep, and the rider that overclaimed it (slice 152; v0.7.5)

**Incident.** Slice 152 reached the completion consult with a manual known-red ("owed to the doc
phase"); the consult answered `complete`, the test phase pushed to confirm, and CI failed a build the
tree could never pass (the comment above `_sweep_targets` in `run_loop.py`).

**Change.** After the last phase the driver runs lint + build + test per component across every repo
in the run's `bases`, so the tree's whole gate state is a driver-run fact before any loop-tail
dispatch and the fix-or-bail decision is made at the consult, where it costs nothing, never at push
time (`run-loop.md` § After the last phase). The sweep is reused only while every swept HEAD matches.

**Readout.** The generation rider then told the consult and the test agent that "the driver's later
full-sweep gate covers" the mechanical residue they fix on the spot — false in one direction, since
the test phase pushes before anything re-sweeps. v0.7.5 corrected it to what is true: the sweep
re-runs on any commit it has not seen, never before a push the agent's own procedure doc orders.
Prompt and doc wording only.

### Preflight owns the pull (v0.9.13)

**Incident.** Before every plan and run the operator ran a pull-every-repo script by hand and
resolved by hand whatever it turned up — the one standing pre-step the pipeline did not own.

**Change.** `preflight.py`'s `synced` check fetches every checkout's upstream (the target repo, every
sibling, the spec repo), fast-forwards a clean checkout that is behind, rebases one with local
commits on top, leaves ahead-only alone, and refuses a dirty tree that is behind; a refused pull is
exit 1 and the operator's to resolve — the relaying skill session does not resolve it either
([`preflight.md`](../../plugins/dev/docs/preflight.md) § Notes on the sync).

**Readout.** Untested on a refused pull as of this checkout; the message shape is the pending read.

### `kc status` joins the preflight (v0.3.1)

**Incident.** Preflight's first version said "no daemon-reachability check — the first `kc session
create-headless` failure is the signal", so a dead control plane failed at the first dispatch, inside
a run.

**Change.** `--for plan` and `--for run` gate on `kc status` as an environment failure (exit 2) before
the repo is resolved; `--for triage` is exempt because triage dispatches nothing (`preflight.md`
§ Exit codes, § Notes on the control-plane check).

**Readout.** The exit-code split (2 = environment, 1 = project) has held through every later profile
change.

### Account session limits are not an agent outcome (v0.3.0; `agent-dispatch.md`)

**Incident.** A session killed by the API's "You've hit your session limit · resets …" notice surfaces
the notice as its whole output; counted as a round, it would escalate the bar or trip a cap on noise.

**Change.** The driver detects the notice only when the verdict is invalid, records a
`session_limit` history row, sleeps until the stated reset plus five minutes — half an hour when the
reset does not parse, never more than twelve hours in one wait (`SESSION_LIMIT_MAX_SLEEP`) — and
redispatches the same round; nothing is nudged, consulted or counted
(`agent-dispatch.md` § Account session limits are not an agent outcome).

**Readout.** Not measured as a rate; the rows exist to be counted.

## 7. Portability and the project contract

### The project contract moves to `.aiworkflowrc` (v0.9.0)

**Incident.** Onboarding Ansible (Triage #579): the dev lock, the test phase and the doc phase had to
be optional, because none of them, or only part, apply to an Ansible repo. Two switches half-existed
as `CLAUDE.md` lines; the devlock was inferred from a `scripts/` directory happening to exist in the
spec repo — a hardcoded convention in a plugin whose first constraint is portability.

**Evidence.** The ruling in the entry: three booleans beside four machine-read lines would have made
`CLAUDE.md` a config file in the one file every agent loads every turn; a second file beside them
would have left two places a project says how its pipeline behaves, "and the first bug is a repo
whose two answers disagree".

**Change.** All of it in one TOML file read by stdlib `tomllib` (`project_config.py`); unknown keys
refused rather than ignored; defaults are the pipeline's full behaviour, so a repo naming only its
pointers runs every phase; `[devlock] lease` alone defaults off; `Design philosophy:` becomes
instance data in every writer and reviewer dispatch instead of an ambient line
([`project-contract.md`](../../plugins/dev/docs/project-contract.md)). No fallback to the old lines.

**Readout.** Two repos onboarded on it, KubeCoder and Ansible. A project running no test phase
leaves `verification.json` unverified, and `run-loop.md` says so rather than leaving it to be
discovered.

### Switching off the test phase leaves nobody pushing (v0.9.0)

**Incident.** Nothing in the driver pushed a code phase — `_run_phase` ff-merges locally — and the
test phase's procedure doc was what pushed. The card that asked for an optional test phase did not
ask about this, and the loop could not survive it.

**Change.** With the phase off, the driver pushes where the push check would have run, honouring
`## Push holds` as the test agent does; `[push] enabled = false` switches the concern off entirely and
rebases the doc branch onto the local base rather than an `origin/<base>` behind by everything the
slice did.

**Readout.** Not yet exercised on a slice in this corpus (every costed KubeCoder slice ran the test
phase).

### The doc phase is auto docs; a doc task is a phase (v0.9.2)

**Incident.** Ansible slice 015 planned a requirement — close a decision, record a hook URL, correct a
phases doc — as "the run loop's own doc phase … not a phase here", so its criterion reached the test
phase before anything could have earned it (Triage #650).

**Evidence.** KubeCoderSpecs showed the same reading sanctioned by plan rulings since slice 114:
fourteen `owed_to_doc_phase` verdicts (plus `pending — doc phase`, `deferred` and one half-and-half)
still sitting unverified in `slices/completed/` — **measured**.

**Change.** The doc phase is auto docs — the surfaces that already describe the changed behaviour,
brought up to date from the shipped diff — and carries no slice task; a requirement that is a doc
change is a phase with its own `Target:` (the spec repo resolves as a sibling), and every criterion
in `verification.json` must be earnable by a phase. Prose only: `plan-template.md`, both plan
agents, `test-agent` rule 1 (an unearned criterion is `fail`, never deferred).

**Readout.** Slice 190's P3 targets `../KubeCoderSpecs` to state a contract refusal — a doc task as a
phase, reviewed and merged like any other (its `plan.md`).

### Whole-number slice ids (v0.9.11)

**Incident.** Closing `182b_per_client_operator_tokens` moved slice 182's Pending bullet — `^(\d+)`
read the folder as slice 182 (Triage #584, #718, #763). Separately, AnsibleSpecs' README was
unparseable to the tool, so Ansible slice 013 was closed by hand.

**Change.** **Ruled:** slice ids are whole numbers only; every follow-up and split-out takes a fresh
number from `allocate-next-slice.sh`, whose header had prescribed the letter suffix. `close_slice.py`
exits 2 on a suffixed folder having changed nothing, and reads both README shapes.

**Readout.** No suffixed folder since; 182b's Completed entry was added by hand (KubeCoderSpecs
b0e3f60a).

### The anti-polling rule has one home, in another repo (v0.7.4)

**Incident.** "Wait by notification, never by polling" was restated in four near-identical places —
two skills, `test-agent.md` rule 7, KubeCoder's `slice-test-plan.md` — and not one covered a
dispatched sub-agent, the other kind of work that reports back (Trello #656).

**Change.** One `## Waiting on work` section in the in-pod `CLAUDE.md` preamble KubeCoder renders
into every session in every pod; the plugin's three copies deleted. The plugin now leans on a file
in another repo for a rule its agents need, guarded by KubeCoder's `TestWaitingOnWork` over the
render matrix.

**Readout.** The same section later gained the outer-`timeout` rule after the 0.9.16 reversal
(§ 8) — the rule's home proved to be where the fix landed.

## 8. Withdrawn

The longer narrative of every reversal is in [`history.md`](history.md); these two are the cases
with a measured or witnessed reason.

### The code-writer's round 1 steps down to `high` (v0.7.0 → withdrawn v0.7.3)

**Incident.** Every dispatch ran Opus at `xhigh`; the effort documentation says `high` is the
default and `xhigh` the premium; Cuadron et al. found less effort matched more at 57 % of cost —
with the stated counter-evidence that o1-*low* over-thought *more* than o1-high in agentic
settings. Catalogue entry A3 (`docs/research/a3-plan.md`).

**Change (v0.7.0).** Round 1 of each phase ran at `--writer-effort` (default `high`) iff the plan's
task shape was `pre-settled` or `localized`; every round ≥ 2 ran `xhigh`; a fuse tripped to `xhigh`
for the rest of the run once two phases needed a round beyond round 1; kill criteria pre-committed.
v0.7.1 fixed the fuse counting a crashed session's re-dispatch as a redo (slice 158 P4, round 1
died `rc=1` with no verdict); v0.7.2 fixed the close-out header printing the launch flag rather than
the tier dispatched (slice 159).

**Evidence for withdrawal.** The seven `high` round-1s on slices 160 and 161 all signed off on
round 1 — but every `high` round the trial ran sat in the small-phase band where `xhigh` draws a
blocking finding only 5–10 % of the time, so the trial could not gain power (one-sided Fisher
p ≈ 0.14–0.22, `status.md` § A3). Effort moves output tokens, ≈ 20 % of a writer round's cost —
context is the rest — so the saving was ≤ 1 % of a slice against one witnessed ≈ 4 % rework strike
(158 P2) — **measured**. The recommendation was to drop "not on the kill rule, which has not fired".

**Ruled.** "My preference is we revert, really … For me it's additional complexity, dead weight."
v0.7.3 removed everything the three versions added except the round names in `slice_cost.py`'s
session table; `medium` and a Sonnet writer were weighed and set
aside in the same ruling. The lesson without a catalogue entry at the time: the spend is in what a
role *reads* per turn, not how hard it thinks — context is 67–84 % of every Opus role's cost — which
became the second research run ([`measurement.md`](measurement.md)).

### The yield boundary half of 0.9.16 (not in this checkout)

**Incident (unconfirmed here — from the operator's session notes).** Slice 192's P3 was read as a
"dead wait": a headless session that backgrounded a command and was never resumed when it completed.
0.9.16 shipped a rule against it alongside its other half (the shipped diff is the slice's own landed
ranges).

**Evidence.** The diagnosis was wrong: a headless session *is* resumed when a backgrounded command
completes — 71 corpus cases, every one resumed. 192 P3's mutation run hung, and a backgrounded
command has no deadline.

**Change.** The rule was reversed the same evening; the fix lives in KubeCoder's managed `CLAUDE.md`
§ Waiting on work, which asks for an outer `timeout(1)` on anything that can hang. The plugin's
registers say nothing about it.

**Readout.** Untested; the first hung command under the new rule is the read.
