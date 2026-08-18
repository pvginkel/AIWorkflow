# Intervention Status Board

Tracks the state of every entry in [interventions.md](interventions.md). That document stays
authoritative for evidence, expected effect, cost and risks; this one records only **where each
entry stands and what happened to it**. One chapter per entry, in catalogue order (I, A, B, C, D).

Started 2026-08-14, at plugin version 0.4.2.

## How to use this document

**Statuses** — an entry moves through them in this order:

- **new** — catalogued candidate. Nothing shipped, whether or not we intend to.
- **validating** — implemented and running; its effect is being measured but not yet judged.
- **accepted** — measured (or argued) and kept for good.
- **rejected** — decided against, or tried and withdrawn. The log says why, so it isn't retried.

**Entry template** — every chapter below uses exactly these fields:

```markdown
## <id> — <title>

**Status:** new | validating | accepted | rejected
**Cost:** S | M | L · **Rank:** <§9 rank or —> · **Depends on:** <ids or —>

**Summary.** One to three sentences: what the change actually does.

**Decides it.** The observation that moves this to accepted or rejected.

**Log**

- YYYY-MM-DD — what happened.
```

Rules: append log lines, never rewrite them; a status change always gets a log line naming what
caused it; `(pre-catalogue)` marks history that predates 2026-08-14.

---

## I1 — Findings telemetry in the review contract

**Status:** validating
**Cost:** S · **Rank:** 1 (with I2) · **Depends on:** — (shares a schema change with C1)

**Summary.** Reviewer verdicts gain machine-readable per-finding fields — severity, impact tag,
category (functional / comment-prose / style / other) and anchor type — persisted into `state.json`
history.

**Decides it.** Whether the fields, once collected, actually answer the B and C questions without
hand archaeology; self-proving, so acceptance is essentially "it shipped and the numbers read".

**Log**

- 2026-08-14 — catalogued (interventions.md §3). Ranked first: prerequisite for every other
  measurement, and it gives the 0.4.2 before/after for free.
- 2026-08-14 — operator direction: run-phase changes get tested on a new slice. Open decision
  whether the run batch is I1 alone or I1+C1+C2.
- 2026-08-14 — implemented (plugin 0.4.3): reviewer verdicts carry per-finding id/severity/
  impact/category/anchor, persisted into `state.json` history with the fix rounds' `refuted`
  lists. Operator resolved the run batch to I1+C1+C2. Reaches runs after push + marketplace
  update → validating.
- 2026-08-14 — first validation data (slices 144+145, the first runs on 0.4.3): all 12 findings
  across both runs carry the fields in `review_result_r*.json` and `state.json` history. The B/C
  readouts logged under B2, C1 and C2 below were produced from the fields alone — no transcript
  archaeology.
- 2026-08-15 — slice 146 (first run on 0.5.0, third on 0.4.3): all four findings carry the
  fields in `review_result_r1.json` and `state.json` history; every number in the 146 assessment
  came from them plus `slice_cost.py`. Distribution: Minor · advisory · `anchor: none` ×4;
  category functional 2, comment-prose 1, other 1.

## I2 — Standard cost readout per run

**Status:** validating
**Cost:** S · **Rank:** 1 (with I1) · **Depends on:** —

**Summary.** `slice_cost.py` gains derived close-out ratios appended to `state.json`: planner share,
research-subagent share, rework share, cost per merged slice.

**Decides it.** Trend lines exist per slice instead of one-off archaeology.

**Log**

- 2026-08-14 — catalogued (interventions.md §3). Noted as behaviour-neutral and
  phase-independent — implementing it commits us to nothing else.
- 2026-08-14 — implemented (plugin 0.4.3): `slice_cost.py` derives planner/research/rework
  shares and `--write-state` appends them to `state.json` as `cost`; `/dev:run-slice` runs it
  at close-out. → validating.
- 2026-08-14 — first validation data (144+145): both close-outs wrote the `cost` block
  (144: $55.02, planner 18.6%, research 3.1%, rework 15.4%; 145: $47.65, planner 26.9%, research
  4.1%, rework 4.9%; no warnings). Known limitation: the readout undercounts ~2–3% — re-pricing
  later gives $56.02/$49.02 — because the run orchestrator's own close-out tail lands after the
  readout is computed.
- 2026-08-15 — slice 146: the `cost` block wrote clean ($45.06 — planner 26.7 %, research 0.7 %,
  rework 9.9 %); the undercount reproduced (re-priced $46.21, 2.5 %). A limitation found and
  fixed (plugin 0.5.1): an appended phase runs as round 1, so its whole cost sat outside
  `is_rework` — exactly the quantity C7's H2 moves between "appended phase" and "close-out
  entry". `slice_cost.py` now marks every round of a phase in `state.json`'s `appended_phases`
  as rework. A definition change, but a contained one: states without the field (every run
  before 0.5.0) are unaffected, so 144/145 stand; 146 re-priced under it is rework $6.75 =
  14.6 % — the high end of the 9.3–15.7 % band, not the low — the honest number for a run that
  spent 8.7 % of itself pinning a test assertion. 146's committed record was re-stamped.

## I3 — Sampled blocking-finding precision audit

**Status:** new
**Cost:** S–M · **Rank:** — (gate for the C entries) · **Depends on:** I1, C1 (anchor taxonomy)

**Summary.** Periodically sample N blocking findings across recent slices and adjudicate them
valid/invalid; the metric is blocking precision, target ≥80%.

**Decides it.** Its own value: precision sustained ≥80–90% is the sunset criterion for C2/C5, and a
low number is the only justification for building them.

**Log**

- 2026-08-14 — catalogued (interventions.md §3). Needs C1's anchor taxonomy to anchor adjudication,
  so it follows rather than leads.

## I4 — Cards ledger

**Status:** new
**Cost:** S · **Rank:** 8 (with C6) · **Depends on:** —

**Summary.** Aggregate advisory-card flow from `state.json` — created vs closed per slice, net
backlog — to test whether problem C's unbounded half lives across slices.

**Decides it.** A flat or shrinking net backlog says cross-slice accumulation is not a problem and
C6 can stay unbuilt; a growing one says it is.

**Log**

- 2026-08-14 — catalogued (interventions.md §3). Grounding sample found within-run amplification
  bounded but the cross-slice path unmeasured (slice 153 deferred a finding to 143).
- 2026-08-14 — evidence ahead of implementation: slices 144+145 minted 8 advisory cards in one
  afternoon (2+6), plus three cut-requirement Trello cards that 145's own consult carded as
  "needing a disposition; no phase covers it". The cross-slice queue the entry would measure is
  visibly the active pressure point.
- 2026-08-15 — reframed by C7: once the run stops carding per finding, the ledger's unit is the
  close-out report — entries by section, dispositions by kind, cards the operator files at
  disposition. Same question (does the queue clear?), new place to count; the plan's
  `entry_counts` and the close-out skill's tally are the instrument.
- 2026-08-15 — C7 shipped (plugin 0.5.0): `state.json["cards"]` no longer exists for new runs,
  so the ledger's original data source ends at 0.4.5. From here the count is `close_out.py
  counts` per report plus the close-out skill's disposition tally at step 5; the pre-0.5.0
  `cards` lists stay readable as the baseline.
- 2026-08-15 — slice 146, the instrument's first reading, void: `counts` read `A 0 · N 0 · B 0 ·
  Q 0 · S 0` for a six-entry report because no entry carried an id (Trello #630; cause under
  C7). By hand: 3 Notable events, 3 Bugs, A/Q/S empty; dispositions so far: 1 card (#632). From
  0.5.1 `counts` also says how many `###` headings are not in the entry shape, so a void reading
  announces itself instead of reading zero.

## I5 — Witnessed-signoff field in the review verdict

**Status:** new
**Cost:** S · **Rank:** — · **Depends on:** I1 (same schema path); feeds I3

**Summary.** The reviewer verdict gains `witnessed: mutation | targeted-run | none` — what the
review rests on beyond reading — persisted into `state.json` history beside the findings.

**Decides it.** Whether I3's audit, given the field, separates witnessed signoffs from read ones
without archaeology; and whether the field's presence moves review cost.

**Log**

- 2026-08-15 — catalogued (interventions.md §3) from the slice 146 assessment: 4/4 reviews
  mutation-verified, the evidence in prose only. Not implemented — a register field, so D2's
  batch-and-A/B discipline applies; the operator picks batches.

---

## A1 — Task-shape declaration in the plan contract

**Status:** validating
**Cost:** M · **Rank:** 4 · **Depends on:** — (enables A3)

**Summary.** The plan-writer declares a task shape (`pre-settled` / `localized` / `cross-cutting`)
justified from slice.md facts, and the register binds investigation to it — `pre-settled` forbids
research subagents and repo sweeps. The plan-reviewer checks the declaration.

**Decides it.** Planner+research share on declared-small shapes drops toward the $11–13 floor with
no rise in downstream gate_red or appended phases.

**Log**

- 2026-08-14 — catalogued (interventions.md §4). Grounded by slice 153: $27.72 pre-code spend on a
  slice whose slice.md said "you are not designing anything".
- 2026-08-14 — operator direction: a planning session is imminent, so plan-phase changes can be
  implemented now and exercised by it. Not yet implemented.
- 2026-08-14 — implemented (plugin 0.4.3): `## Task shape` in the plan template, declared by
  the plan-writer before it investigates and checked by the plan-reviewer; `pre-settled`
  forbids research sub-agents and repo sweeps. → validating.
- 2026-08-14 — first validation data (144+145): both plans declared `pre-settled` with
  slice.md-anchored justifications, honestly both times. Planner+research $11.94/$14.76 against
  slice 153's $27.72 analog; no gate_red, no appended phases, generation 0 in both runs — and the
  plan-reviewer still did real work in each (144: caught P2 falsifying the wire contract; 145:
  three structural findings that fed the R2/R5/R6 cut). Only `pre-settled` exercised so far; the
  discrimination test — a cross-cutting slice declaring itself honestly — is still open.
- 2026-08-15 — slice 146: `pre-settled` declared from slice.md's 2026-08-14 grounding pass,
  checked by the plan-reviewer, no attachments taken. Planner $12.03 (26.7 %) + research $0.33 =
  $12.36 (27 %) against slice 153's $27.72 (34 %). The planner *share* looks unchanged from
  baseline; that is a floor effect on a $45 slice — the absolute figure sits at the bottom of the
  $11–19 band on a four-phase slice. Still only `pre-settled` exercised.

## A2 — Question-gated research budget

**Status:** validating
**Cost:** S · **Rank:** 5 · **Depends on:** A1 (complement)

**Summary.** Research subagents may only be dispatched against a named open question the plan must
settle; the dispatch names it, and a settled question cannot be re-dispatched. Structural, with no
numeric token cap.

**Decides it.** Research share falls (I2) without questions being manufactured to pass the gate —
visible in plan output.

**Log**

- 2026-08-14 — catalogued (interventions.md §4). Deliberately structural: TALE's token elasticity
  says tight numeric budgets backfire.
- 2026-08-14 — operator direction: rides with A1 in the plan-phase batch.
- 2026-08-14 — implemented (plugin 0.4.3), in the plan-writer register with A1: a research
  dispatch names the open question it settles; a settled question is never re-dispatched.
  → validating.
- 2026-08-14 — first validation data (144+145): plan-writers dispatched zero research subagents
  ("no attachments were needed"); the 3–4% research share in I2's readout is the interactive
  refinement session's Explore agents, outside this gate's scope. Unexercised on a shape that
  permits research.
- 2026-08-15 — slice 146: research $0.33 (0.7 %), the lowest recorded — one two-minute Explore
  in the plan loop, nothing from the plan-writer.

## A3 — Effort step-down for the plan registers

**Status:** validating
**Cost:** S–M · **Rank:** 7 · **Depends on:** A1 (trial gate)

**Summary.** Run the producer roles — plan-writer and code-writer — at `high` instead of `xhigh`
on declared-small shapes, escalating to `xhigh` on real signals: writer `questions`/`escalate`,
reviewer `issues`, red gates, blocking findings. Judgment roles (reviewers, consults) stay
`xhigh` unconditionally.

**Decides it.** An A/B on declared-small shapes: plan-reviewer verdict rate, gate-red rate,
blocking-finding rate and downstream appended-phase rate hold while producer cost per tier drops.

**Log**

- 2026-08-14 — catalogued (interventions.md §4) with counter-evidence stated: o1-low scored 35%
  *higher* on overthinking than o1-high in agentic settings. Trial-gated for that reason.
- 2026-08-14 — scope widened at operator direction: the run side is the large majority of slice
  spend, so the code-writer's rounds join the step-down (executor r1 shape-gated cheap, every
  signal-triggered round `xhigh`). Implementation plan written: [a3-plan.md](a3-plan.md).
  Scheduled after B1+B4.
- 2026-08-14 — staged run-loop-first (a3-plan.md §8a): the simpler build for the larger effect,
  with failures contained in-loop by the gate and the `xhigh` reviewer; the plan half's
  `escalate` machinery is now conditional on the run trial's read.
- 2026-08-18 — stage 1 implemented (plugin 0.7.0): the code-writer's executor round 1 runs at
  `high` (`run_loop.py run --writer-effort`, default `high` — §9's recommendation taken: an
  opt-in flag produces no trial data, and the mechanism self-gates) when plan.md's `## Task
  shape` is `pre-settled`/`localized`; `cross-cutting`, undeclared, or a tripped fuse (two
  phases needing a round beyond r1) keeps r1 at `xhigh`; every round ≥ 2, the reviewer, every
  consult, the doc-writer and both plan roles stay `xhigh`. Telemetry: `effort` on every session
  history row in both loops, `task_shape`/`writer_effort`/`effort_fuse` in state.json, the
  close-out `Run:` header and `slice_cost.py`'s `tiers` line name the arm. Prerequisites checked:
  A1 in place since 0.4.3 (three `pre-settled` declarations on file, all honest); B1+B4 have
  their `xhigh` slices (146 onward). Reaches runs after push + marketplace update. → validating.
  Read at the first `pre-settled`/`localized` slice under 0.7.0: r1 `duration_s`/cost per tier
  first (the Cuadron counter-evidence — a longer or dearer `high` r1 self-refutes early), then
  gate-red-on-r1, blocking-finding rate, executor-round-≥2 rate, fuse trips, and net slice cost
  against 144/145/146. Kill: flag back to `xhigh` per a3-plan.md §5; stage 2 stays unbuilt.

## A4 — Upfront complexity grading

**Status:** rejected
**Cost:** — · **Rank:** — · **Depends on:** —

**Summary.** Routing models by a predicted difficulty grade assigned before the work starts. Stays
rejected; A3 escalates on outcomes instead, which is strictly more information.

**Decides it.** Nothing pending — this chapter exists so the lane isn't retried on a hunch.

**Log**

- (pre-catalogue) — a graded complexity lane was built and retired: it "produced Opus redos whenever
  mechanical turned out to mean judgment".
- 2026-08-14 — recorded as a decision record (interventions.md §4). The reading explains the failure:
  difficulty is not a stable property of a request, models misjudge it from surface framing, and
  judges are least reliable exactly at near-ties — where an upfront grader lives entirely.

## A5 — Best-of-k cheap plans with bias-controlled selection

**Status:** new
**Cost:** M–L · **Rank:** 13 (last) · **Depends on:** D3 (judge controls); only if A1–A3 underdeliver

**Summary.** Generate k=2 plans at low effort and have a bare comparative judge pick one, with order
swap and a third vote on near-ties.

**Decides it.** Only becomes live if A1–A3 leave planner share high; the ceiling is bounded because
the planner is 11–29% of slice cost and this doubles plan latency.

**Log**

- 2026-08-14 — catalogued (interventions.md §4) and ranked last by the catalogue's own proposal.

---

## B1 — Coder comment policy: verifiable invariants only

**Status:** validating
**Cost:** S · **Rank:** 6 (with B4) · **Depends on:** — (interacts with B3)

**Summary.** Adds the missing criterion to the existing "invariants only" rule: a comment must state
a condition code, a test or a gate can witness. Predictions and strength-graded claims are deleted,
not hedged.

**Decides it.** Comment-category finding rate and comment density per diff fall (I1) without losing
load-bearing warnings.

**Log**

- 2026-08-14 — catalogued (interventions.md §5) as partial → tighten: the register already prefers
  trimming; verifiability is the missing half.
- 2026-08-14 — sequencing noted: cheap and compatible either way, but B's baseline (49% comment
  share) predates 0.4.2, so measurement comes first.
- 2026-08-14 — implemented (plugin 0.4.5), after B2's first measurement landed (comment cost at
  zero on 144+145, count barely moved — B1 attacks the count): the code-writer's comment rule
  gains the verifiability criterion — a condition code, a test, or a gate can witness;
  predictions and strength-graded claims deleted, not hedged; load-bearing warnings stay.
  Reaches runs after push + marketplace update. → validating.
- 2026-08-15 — first data point (146, the first run with B1 in the writer register): the writer
  still shipped one unwitnessable claim — P3's `"A reset that fails leaves the root as it found
  it"`, a post-condition the daemon cannot observe, precisely the claim B1 says to delete rather
  than hedge. B1 did not prevent it; B4 caught it at review; the consult fixed it in place as
  mechanical residue (`6de4795`). Comment findings 1 of 4 (25 %) against ≈49 % baseline — one
  finding, not a trend on its own.

## B2 — Reviewer comment scope

**Status:** validating
**Cost:** S · **Rank:** — · **Depends on:** I1 (to measure)

**Summary.** Shipped in 0.4.2: comment/prose findings are advisory by default, get one plain
sentence, and are never relitigated across rounds. The pending extension — narrowing the blocking
carve-out to factual contradiction with the code as it stands — is held until the measurement lands.

**Decides it.** Comment-category findings and their blocking share on slices 143+ versus the ≤153
baseline. Churn gone ⇒ accepted as-is; churn persists ⇒ take the extension.

**Log**

- (pre-catalogue) — shipped in plugin 0.4.2.
- 2026-08-14 — catalogued (interventions.md §5) as in place → measure. Baseline recorded: comment
  findings ≈49% of all findings on slices 149–153, all pre-0.4.2; slice 143 is the first run on
  0.4.2. Measurement blocked on I1.
- 2026-08-14 — first post-0.4.2 measurement (144+145, via I1): comment-prose findings 5 of 12
  (~42% by count vs ≈49% baseline) but all advisory, one sentence each, zero fix rounds, zero
  relitigation — $0 of prose rework against slice 153's $11.70 analog. The mechanically-fixable
  prose residue was absorbed by the completion consults (~$2 each, one claim verified by actually
  running node); the judgment calls became cards. Count barely moved, cost went to zero — the
  design intent. The blocking carve-out extension stays held.
- 2026-08-15 — 146: comment-prose findings 1 of 4 (25 %), advisory, one sentence, no fix
  round; prose rework $0 for the third consecutive run.

## B3 — Explanatory prose lives in docs, not comments

**Status:** new
**Cost:** M · **Rank:** 12 · **Depends on:** B1; waits on B2's measurement

**Summary.** Architectural narrative and rationale move to the docs the doc-writer already maintains
diff-based once per slice; inline comments keep only B1's invariants.

**Decides it.** Whether comment churn survives 0.4.2 at a level that justifies losing locality —
the explanation no longer sitting next to the code is a real onboarding cost.

**Log**

- 2026-08-14 — catalogued (interventions.md §5). Held explicitly for the 0.4.2 measurement; the
  grounding motive is slice 152's 16 live comments describing a subsystem that no longer existed.

## B4 — Semantic-equivalence bar for prose findings

**Status:** validating
**Cost:** S · **Rank:** 6 (with B1) · **Depends on:** — (subsumed by B2's extension if that lands)

**Summary.** A prose finding must show the text is *wrong* — contradicted by code or spec — not that
different words would be better. Meaning-preserving wording drift is not a finding.

**Decides it.** Comment-category finding rate (I1); and whether B2's extension lands first, in which
case this folds into it.

**Log**

- 2026-08-14 — catalogued (interventions.md §5). One register rule.
- 2026-08-14 — implemented (plugin 0.4.5), with B1: one sentence in the code-reviewer's
  comment/prose rule — a prose finding must show the text is wrong (contradicted by code or
  spec); meaning-preserving wording drift is not a finding. Kept to a single sentence per D2's
  register-growth warning. → validating.
- 2026-08-15 — first data point (146): the one prose finding was a wrongness finding as B4
  asks — the comment claimed a post-condition the code cannot observe — not a wording
  preference. Held.

---

## C1 — Anchoring taxonomy for blocking findings

**Status:** validating
**Cost:** S · **Rank:** 2 · **Depends on:** — (schema shared with I1; C2 builds on it)

**Summary.** Replaces "failing-input logic or a test sketch" with a closed anchor list — failing
test/command, concrete repro trace, analyzer output, requirement-to-code contradiction with
file:line, coverage gap against a named AC. No anchor ⇒ advisory by construction.

**Decides it.** Blocking precision (I3) rises and fix rounds are triggered only by demonstrable
failures; the anchor-type distribution (I1) shows what the old bar was letting through.

**Log**

- 2026-08-14 — catalogued (interventions.md §6) as partial → strengthen, ranked 2: 87% of S7's
  false rejections would fail this bar.
- 2026-08-14 — pairs with I1 at no extra cost (same verdict-schema change). Part of the open
  decision on the run batch.
- 2026-08-14 — implemented (plugin 0.4.3): the closed anchor list replaces "failing-input logic
  or a test sketch" in the reviewer register; `blocking` requires an anchor, `none` is advisory
  by construction, the never-anchor categories are named. → validating.
- 2026-08-14 — first validation data (144+145). Anchor distribution: repro-trace 2, coverage-gap
  1, none 9; every `none` was advisory, and the single blocking finding (144 P2 F1, Major) carried
  a repro-trace with a file:line evidence trail and was confirmed real. Anchored ≠ blocking held
  in the right direction too: 145 P3 F1 (Major, repro-trace) stayed advisory because it contests
  an operator ruling's premise, and was routed to a card. One boundary case for I3's audit: 145
  P4 F1 (a mutation-survival claim — deleting the growth guard leaves the suite green) was
  labeled `none` rather than coverage-gap, defensibly, since no named AC covers it.
- 2026-08-15 — 146: 4/4 findings `anchor: none`, all advisory, no fix round — C1 holding, and
  no data added to I3. Cumulative over three runs: repro-trace 2, coverage-gap 1, none 13. Two
  limits of the read named: (a) anchors are required only for `blocking`, so advisories carrying
  full file:line traces (146's goroutine-leak finding spans five call sites) record `none` and
  the "what the old bar let through" read is not available from the field — noted, not acted
  on (a register line for a measurement's sake). (b) The 144/145 boundary case recurred — 146
  P1 F1 is a surviving mutation on the slice's own new test, recorded `none`/`other` — and is
  resolved (plugin 0.5.1): the `coverage-gap` anchor now names vacuous coverage explicitly, "a
  mutation you ran that the criterion's test survives". 145 P4 F1 stays `none` under it: no AC
  covers the guard it concerns.

## C2 — Demonstrate-failure-first fix protocol

**Status:** validating
**Cost:** M · **Rank:** 3 · **Depends on:** C1

**Summary.** A fix round for a blocking finding starts by witnessing the failure — write the failing
test or run the claimed repro. If it cannot be made to fail, the finding is refuted: flipped to
advisory with the refutation attached, no code change, no relitigation.

**Decides it.** Refuted-finding rate, rework share (I2) and blocking precision (I3) before/after.
Success target for the C1+C2 pair: precision ≥80% with rework share stable or down.

**Log**

- 2026-08-14 — catalogued (interventions.md §6) as the highest-confidence C intervention: S7's
  fix-guided verification filter cut false rejection by 30–67 points at ≤2.5 points added false
  acceptance.
- 2026-08-14 — operator: proposed starter #2 (C1+C2) neither accepted nor rejected. Open.
- 2026-08-14 — operator accepted the pair by actioning the batch. Implemented (plugin 0.4.3):
  fix rounds witness executable-anchor findings before touching code; an unwitnessable finding
  is refuted via the executor verdict's `refuted` list — carded with evidence, recorded onto
  the review file, never relitigated; all-blocking-refuted with no code change settles the
  review without another round. Inspection anchors keep their current handling. → validating.
- 2026-08-14 — first live firing (144 P2 r2), textbook: the executor witnessed before fixing —
  removed the fabricating harness helper and watched three tests fail exactly as the reviewer
  traced (0 rolled, 3 failed) — then fixed the harness, pinned the exposed pass-wide refusal
  with a test red against the old predicate, and carded the surfaced product question (upgrade
  roll cascading on an at-cap node) instead of changing production behavior unilaterally. The r2
  reviewer mutation-verified and signed off; no relitigation. Refute path not yet exercised;
  blocking precision so far 1/1.
- 2026-08-15 — 146: did not fire (no blocking finding). Blocking precision still 1/1 lifetime;
  two of the last three runs produced no blocking finding at all — I3 accumulates slowly. What
  did move: every review in 146 verified by mutation unprompted (4/4; 10/12 across 144–146
  against 13/29 on 149–153, keyword proxy), P4's re-witnessing the phase's own done-condition —
  the discipline C2 encodes has generalised into signoff. Catalogued as I5 (make it countable)
  and C8 (make it mandatory where cheapest, test-only phases); neither implemented.

## C3 — Round caps, rising bar, one-report lifecycle

**Status:** accepted
**Cost:** none · **Rank:** — · **Depends on:** —

**Summary.** The 0.4.x design already caps fix rounds and review rounds, raises the funding bar per
round, and forbids relitigation. Kept as-is.

**Decides it.** Settled. Recorded so the caps aren't loosened in a future "more review = better"
mood; reopening needs evidence that a cap is losing real defects.

**Log**

- (pre-catalogue) — shipped across 0.4.x.
- 2026-08-14 — catalogued (interventions.md §6) as in place → keep, and endorsed on three
  independent grounds: self-bias grows with refinement iterations while human-rated quality stays
  flat, intrinsic re-critique degrades outcomes with more rounds, and bias grows with pool size k.

## C4 — Evidence-gated contest channel for the coder

**Status:** new
**Cost:** S–M · **Rank:** 9 · **Depends on:** C2 (which subsumes the executable half)

**Summary.** The executor may return "contested + evidence" instead of a fix; contested findings go
to the existing bare consult with the evidence attached, and the ruling is final.

**Decides it.** Whether an inspection-anchored remainder — spec readings, coverage disputes — still
produces capitulation once C2 handles the executable claims.

**Log**

- 2026-08-14 — catalogued (interventions.md §6). Motive: models wrongly admit a mistake on 42–98%
  of answers they had right when challenged confidently.

## C5 — Agentic false-positive validator before fix rounds

**Status:** new
**Cost:** M–L · **Rank:** 11 (conditional) · **Depends on:** I3, C1, C2

**Summary.** A bare, evidence-seeking session with repo read access validates each blocking finding
before an executor round is spent — gating only mechanically-checkable anchor classes, never taste.

**Decides it.** Explicitly conditional: build only if I3 shows blocking precision still low *after*
C1+C2. Then judged on validator overturn rate and net cost per avoided fix round.

**Log**

- 2026-08-14 — catalogued (interventions.md §6) with the strongest single measured effect in the
  reading (residual FP 98.3%→6.3%) and the strongest caveat: judgment/policy classes suffered
  50–85% true-positive suppression.

## C6 — Advisory-card lifecycle governance

**Status:** new
**Cost:** S · **Rank:** 8 (with I4) · **Depends on:** I4 (measures the need)

**Summary.** Cards get an explicit lifecycle: batch triage at `slice-dag` time, auto-expiry for
cards skipped by two consecutive triages.

**Decides it.** I4's net backlog trend — a queue that clears itself needs no governance.

**Log**

- 2026-08-14 — catalogued (interventions.md §6). Process change, no loop code.
- 2026-08-14 — card pressure from 144+145 acknowledged (see I4's log), but the operator is
  attacking the queue at intake instead: the triage skill was reworked (plugin 0.4.4) to filter
  cruft and quickly close cards not worth progressing. C6's catalogued mechanism (slice-dag batch
  triage + two-triage auto-expiry) stays unbuilt; whether the intake filter alone keeps the net
  backlog flat is exactly what I4 would measure.
- 2026-08-15 — C7 (close-out report) decided: the per-finding card queue moves off the board
  into one document per slice, dispositioned by the operator; C6's mechanism is not built — the
  question it governed no longer exists in that form. Stays `new` as a record; revisit only if
  operator-filed cards from close-out dispositions accumulate the same way.
- 2026-08-15 — C7 shipped (plugin 0.5.0); the run loop mints no per-finding cards from this
  version on. What reaches the board is one close-out card per slice plus whatever the operator
  files at disposition — the queue C6 would govern is now operator-made.

---

## C7 — Close-out report replaces per-finding cards

**Status:** accepted (2026-08-17; the 0.5.3 shape refinements get their own read)
**Cost:** M · **Rank:** — (operator-directed, 2026-08-15) · **Depends on:** — (rides I2 for the header's cost line)

**Summary.** One `close-out.md` per slice, created at plan start, written by every agent in one
fixed shape as it goes, reconciled by the completion consult, Summary and Focus lines by the
doc-writer, header stamped by the driver. Everything out of the loops' own scope goes there;
nothing from a run is carded per finding; one close-out card per slice; the operator dispositions
entries in place, the `close-out` skill executes, triage reads what remains. Design and decisions
in [close-out-report.md](close-out-report.md); build in [close-out-plan.md](close-out-plan.md).

**Decides it.** After a handful of slices: the operator processes reports in one sitting and
files markedly fewer cards than the run used to; gen-1 appended phases and rework share not up
(hypothesis: down); Notable events surface workflow defects that today live only in `log.txt`.
Kill signal is reports that grow *and* stop being read — answered by shape, never by caps.

**Log**

- 2026-08-15 — decided by the operator after reviewing Ansible slice 007's ten cards (615–624:
  one must-act, one real cross-project bug, one ruling, one already fixed in-run, six
  minor/nit/doc) with the assessment; design note and implementation plan written the same day at
  plugin 0.4.5. Baselines for the read: 007 — 11 entries → 10 cards, 3 appended phases, rework
  13.8 %; KubeCoderSpecs 117/135/107 — 24/17/16 card entries; 149–153 rework band 9.3–15.7 %.
- 2026-08-15 — implemented as plugin **0.5.0**, per the plan: `docs/close-out.md` +
  `close-out-template.md`, `tools/close_out.py` (init / append / stamp / counts, imported by
  both loops), the `close-out` skill; every agent register lost `cards` and gained the report;
  `state.json` lost `cards`, gained `bailouts` and `appended_phases`; `/dev:run-slice` files one
  close-out card; `/dev:triage` reads the report. Open decisions closed: 0.5.0 (a contract
  change touching every agent); the driver's entries carry a blank `Disposition:` like every
  other; no Summary/Focus pass on a `blocked`/`question` doc phase. **Validating from the first
  slice planned or run on 0.5.0** — the run's `state.json` will show `bailouts`/`appended_phases`
  and its folder a `close-out.md`; measurement per design §7 (entry counts by section,
  dispositions by kind, cards filed at disposition, gen-1 appended phases, rework share,
  bail-outs) logged here per slice as the 0.4.3 batch was.
- 2026-08-15 — first slice run end to end on 0.5.0 (KubeCoder 146; assessment in the operator's
  hands). **Content held**: 6 entries (3 Notable events, 3 Bugs; A/Q/S empty), one close-out
  card, one bug accepted at disposition — its claim and line numbers verified from the report's
  text alone (H3's writing rule working); the doc-writer's Focus lines ranked the bugs and drove
  the pick; the header read `4 phases (3 planned, P4 appended) · 0 bail-outs · 1 test round · doc
  phase done · $45.06 (…)`, correct against `state.json`; live-committed through the whole
  lifecycle (plan-loop init → reviewers → consults → test agent → doc-writer → driver stamp); the
  P1–P3 reviewers wrote their advisories into the report directly. H1 ✓ (10 → 1). H3 ✓. H4
  partial: every Notable event is product-side; P3's `gofmt: command not found` and the test
  agent's five tool errors around `track_build.py` went unreported. **Shape did not hold**: no
  entry carried an id, `Provenance:` or `Disposition:` (`### minor — …`, `### Consult 1 (…) …`),
  so `counts` read 0 (Trello #630) and consult 1 deleted the two entries it absorbed instead of
  striking them. Cause: every register says "the shape is in the file" and `init` wrote a file
  holding section charters only — the plan-writer wrote the first entry freehand, every later
  author read the file and copied the precedent (transcripts: Read then Edit, each time). Fixed
  in plugin 0.5.1: the template's head comment carries the entry shape and the struck form, so
  `init` writes it; `close_out.py` reads headings outside HTML comments; `counts` reports
  headings not in entry shape; the Notable-events charter names workflow deviations. **H2 not
  readable from 146**: I2 could not see appended-phase cost (fixed — I2's log), and the gen-1
  bar still carried card economics — consult 1 appended P4 for a test-durability nit ($4.02
  with the consult it forced, 8.7 % of the slice) reasoning "cheaper to fix than to card", a
  comparison 0.5.0 deleted. The bar was re-priced in 0.5.1: append only work the plan owes and no
  phase delivered; a phase's three rounds against one operator word. From 0.5.1 the gen-1 count
  reads against a moved bar; 146's P4 is the last append under the old one, and would be an
  entry under the new (consult 1 itself found implementing work for every AC). Redundancy
  watch, early: two of the three Notable events narrate things going right (consult 2's restates
  `consult_2.json`); noted against the kill signal, not acted on from one slice.
- 2026-08-17 — six reports read across both projects, all dispositioned by the operator in one
  sitting each (Ansible 008 on 0.5.0, 015 on 0.5.1; KubeCoder 154, 155, 156, 157 on 0.5.1/0.5.2):
  **76 entries** (A 2 · N 6 · B 43 · Q 0 · S 25), 22 struck in-run by the consult or the doc
  phase (154 alone: 10 of 16 Bugs were comment residue consult 1 fixed in one commit, 4 of 9
  Suggestions were doc-phase pointers), **14 progressed by the operator, 7 tracker cards**
  (015 S3 → AIWorkflow; 154 S2/S4/S6; 155 B2, S2+S3 on one card; 156 B3), 3 fixed inline at
  close-out, 3 notes into pending slices, the rest closed. Operator's own words: "we struck gold
  … 1 or 2 things out of anywhere between 10 and 30 … solved the biggest frustration I was
  having with the system." **H1 ✓** across projects (~1 card per slice against 007's ten).
  **H2 ✓**: gen-1 appended phases 0 in six runs; rework 8–16 % (008 9, 015 11, 154 10, 155 8, 156
  16, 157 16) inside the 149–153 band, appended-phase cost now included. **H4 ✓ in part**: 015 N1
  (`$JENKINS_TOKEN` unset, `track_build.py` could not track — polled by hand) and 015 S3 (V08 is
  doc-owed but the test phase checks off `verification.json` before the doc phase runs — a loop
  ordering, carded to AIWorkflow by the operator) are workflow defects surfaced by the report
  rather than `log.txt`; 154's one bail-out and 155's are in the header, not entries. Kill signal
  not seen: 154's 42 KB / 25 entries was read whole and dispositioned. **Shape held** on
  0.5.1+ (ids, `Provenance:`, blank `Disposition:` on every entry; `counts` non-zero; strikes,
  never deletes) — 008 predates 0.5.1 in its environment and shows why. **What was uneven — the
  consequence**: the template carried it as body placeholder prose, so 154/155 wrote a
  `Consequence:` paragraph on most entries, 157 wrote the template's own "Why it matters:",
  156 none, and the entry the operator called "very dense" (155 B2) had one that said what the
  code did rather than what a real environment risks. Also seen: entries about entries (157
  N1→N2 about B1; 156 B6 refuting B4 — the consult struck the bullet and left B6 as "the record
  of why"); the executor's record in three places across three sessions; 008/015's sessions
  did not strike on `close`. **0.5.3** answers these: `**Consequence:**` / `**Provenance:**` /
  `**Disposition:**` bold and in that order on every entry, the Consequence chartered for triage
  (deployed-shape, plain words, what has to happen for it to be reached; `none` said plainly);
  `append` requires one; `counts` names live entries lacking Consequence or Provenance; "one
  entry per thing" — a later note is a dated paragraph under the existing entry; the skill
  presents Consequence lines, handles blanket closes, strikes as `— closed by the operator,
  <date>`, records execution after the operator's words. Recommended, not built: collapsing
  consult-struck bodies (they are duplicates of the review file, and in 154 they were most of
  the Bugs section). Next read: the first slice on 0.5.3 — Consequence lines written for triage,
  smoke counts at zero, no meta-entries.
- 2026-08-17 — **0.5.4** (evidence class on every entry: `Provenance:` opens `witnessed | read`,
  symptom-first bodies, strikes name the re-run, Focus lines rank on Consequence + evidence,
  skill answers claim-questions from the entry; from S5–S7 — see the design note's revision
  line) and **0.6.0** (the report is tool-written and rendered: `close_out.py append | note |
  strike | list | render`; every dispatch of both loops names the installed tool; the consult
  reconciles through `strike`/`note` only; the driver renders before the doc phase and at
  completion — verified on 154's pre-disposition report: 6 live Bugs first by severity, 10 struck
  folded, second render byte-identical). Built by a delegated agent from a written brief, diff
  reviewed. Both unpushed at time of writing. Next read, first slice on 0.6.0: do headless agents
  actually use the tool (installed-path `python3` from a kc session), `counts` shows no drift, the
  consult's strikes carry commit + re-run, and the read cost per dispatch drops now that authors
  `list` instead of reading the file.

## C8 — Mutation-witnessed signoff for test-only phases

**Status:** new
**Cost:** S · **Rank:** — · **Depends on:** C1's 0.5.1 coverage-gap clause; I3 to judge

**Summary.** One reviewer-register sentence scoped to test-only phases: a signoff names one
mutation that takes the phase's new test red; a test-only phase whose reviewer cannot has been
read, not reviewed.

**Decides it.** I3 precision on test-only phases and their fix-round rate before/after; the
rule dies if precision falls.

**Log**

- 2026-08-15 — catalogued (interventions.md §6) from 146 P1 F1 ($4.02 to fix a self-satisfying
  test one generation late) and 145 P4 F1. Not implemented — a reviewer-register rule, batched
  and A/B'd per D2.

---

## D1 — Same-model separation is weaker than it looks

**Status:** accepted
**Cost:** none · **Rank:** — · **Depends on:** —

**Summary.** An insight adopted as standing guidance, not a change: register/session/prompt
separation does not neutralize stylistic bias, because judge preference tracks perplexity to the
judge. The response is to keep the strongest model and ground its verdicts in external evidence
(C1/C2), not to introduce a weaker-but-different reviewer.

**Decides it.** Settled unless a genuinely different frontier-strength model becomes available
in-loop as consult or validator — the clean fix, and the one thing that would reopen this.

**Log**

- 2026-08-14 — catalogued (interventions.md §7) and adopted as the reason wording findings are
  treated as structurally low-information (B4).

## D2 — Reviewer prompt and context hygiene

**Status:** new
**Cost:** S · **Rank:** 10 · **Depends on:** I3 (for the A/B discipline)

**Summary.** Two rules: the reviewer/consult sees the artifact and the acceptance criteria, not the
coder's narration (audit that review dispatches match bare consults); and the reviewer register
stays lean, with every future addition A/B-checked against finding precision.

**Decides it.** The audit finding — either review dispatches already pass only artifact + AC, or
they don't; plus whether the lean-register rule survives contact with B1/B4/C1, all of which add
register prose.

**Log**

- 2026-08-14 — catalogued (interventions.md §7). Cuts directly against the other entries' prompt
  growth: elaborate review instructions shifted GPT-4o's false-negative rate 26%→73%. Batch and A/B
  register edits rather than accreting them.

## D3 — Comparative-judgment toolkit

**Status:** new
**Cost:** — · **Rank:** — (dormant) · **Depends on:** a selection step existing at all (A5)

**Summary.** A reference kit for any future candidate-selection step: order randomization with a
swap-consistency test, majority vote among ≥3 strong judges for near-ties, length normalization,
provenance hiding, and independent samples + vote in preference to multi-agent debate.

**Decides it.** Dormant by construction — the loop issues absolute verdicts today. It activates only
if A5 or a best-of-k fix step is built.

**Log**

- 2026-08-14 — catalogued (interventions.md §7) as reference material, nothing to implement.
