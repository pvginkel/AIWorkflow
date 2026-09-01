# Intervention Status Board

Tracks the state of every entry in [interventions.md](interventions.md). That document stays
authoritative for evidence, expected effect, cost and risks; this one records only **where each
entry stands and what happened to it**. One chapter per entry, in catalogue order (I, A, B, C, D,
W).

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

**Status:** accepted
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
- 2026-08-22 — sixteen slices (155–170) read from the fields alone: the cross-slice table — r1
  `issues` 12/71, blocking 15 / refuted 0, comment-prose 43/114, anchor distribution, bail-outs,
  appended phases, test rounds — was one script over `state.json`, no transcript archaeology
  (assessment in `tmp/slice-170-assessment.md`, untracked). Limit stands: anchors are recorded only
  where `blocking`, so an advisory's evidence is not in the field. → accepted.

## I2 — Standard cost readout per run

**Status:** accepted
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
- 2026-08-22 — the `cost` block is on every run 155–170: rework 2–19 % (median ≈ 7 %; 170: 2.9 %),
  planner $14–27 absolute, research 0.7–12.7 % (the > 10 % points are the interactive refinement
  session's Explore agents, outside A2's gate). One gap found on 170: a round whose session returns
  no verdict leaves no history row and is unpriced — test r1 was ≈ $8.27 by hand, so the true cost
  was ≈ $221 against $212.78 priced (W4 records such rounds; W5 proposes the trend readout as a
  command). → accepted.

## I3 — Sampled blocking-finding precision audit

**Status:** accepted (answered by C2’s refute path; no sampled audit built)
**Cost:** S–M · **Rank:** — (gate for the C entries) · **Depends on:** I1, C1 (anchor taxonomy)

**Summary.** Periodically sample N blocking findings across recent slices and adjudicate them
valid/invalid; the metric is blocking precision, target ≥80%.

**Decides it.** Its own value: precision sustained ≥80–90% is the sunset criterion for C2/C5, and a
low number is the only justification for building them.

**Log**

- 2026-08-14 — catalogued (interventions.md §3). Needs C1's anchor taxonomy to anchor adjudication,
  so it follows rather than leads.
- 2026-08-22 — answered by the loop's own instrument rather than a sampled audit: 15 blocking
  findings on 155–170, 0 refuted by C2's witness-first fix rounds, every one fixed and re-verified
  by the r2 reviewer; 170's one (P2 F1, Major, `contradiction`) carried a file:line trail and was
  confirmed. Blocking precision by the evidence gate 15/15 — the ≥ 80 % bar is met without building
  the audit. → accepted; this reading is the sunset for C4 and C5.

## I4 — Cards ledger

**Status:** rejected (moot — the report is the ledger)
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
- 2026-08-22 — 155–170 reports carry 3–30 entries each; operator-filed cards 0–6 per slice (170: 30
  entries → 6 cards, 7 fixed at close-out, 15 closed in one sitting); no run-made backlog accrues on
  the board. Nothing left to aggregate. → rejected (moot).

## I5 — Witnessed-signoff field in the review verdict

**Status:** rejected
**Cost:** S · **Rank:** — · **Depends on:** I1 (same schema path); feeds I3

**Summary.** The reviewer verdict gains `witnessed: mutation | targeted-run | none` — what the
review rests on beyond reading — persisted into `state.json` history beside the findings.

**Decides it.** Whether I3's audit, given the field, separates witnessed signoffs from read ones
without archaeology; and whether the field's presence moves review cost.

**Log**

- 2026-08-15 — catalogued (interventions.md §3) from the slice 146 assessment: 4/4 reviews
  mutation-verified, the evidence in prose only. Not implemented — a register field, so D2's
  batch-and-A/B discipline applies; the operator picks batches.
- 2026-08-22 — 170: 11 of 13 reviews executed something unprompted — mutations (P1, P6, P9, P10), a
  kaniko build (P1), contract regeneration + diff (P3), `sshd -t`/`-T` on a rendered config (P5), a
  `helm template` re-render loaded through the controller's own parser plus the live cluster (P12);
  only P7 read alone. The behaviour is present without a field, I3 no longer needs the measurement,
  and a field is register prose (D2). → rejected.

---

## A1 — Task-shape declaration in the plan contract

**Status:** accepted
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
- 2026-08-18 — slice 158: `pre-settled` declared honestly again — the justification even names
  the two requirements (R4, R6) that carry no ruling and must stay reviewable — and the shape
  read true at run time for what it claims: no design decisions surfaced. Planner $21.13 (26 %) +
  research $2.01 (2 %): the plan loop's own two writer rounds plus review are $9.34, inside the
  band; the rest is a 165-minute interactive refinement session ($11.78), which the register does
  not govern — and the research is that session's four Explore sub-agents; the plan-writer itself
  ran none, as the register requires. **One defect in the plan's substance:** the r2 plan-writer,
  rebuilding P1 to the operator's ruling, wrote "Two departures … are known" into P1's
  *constraints the executor cannot derive* while applying a review whose evidence paragraph named
  the third (the open redirects' bare 404, `plan_review_r1.md:62`); the plan-reviewer had already
  run, the code-writer transcribed it, and the code-reviewer caught it at run time for the price
  of a fix pair. The fact *was* derivable (`controller-api.md:899`, `app.py:356/359/394`), so the
  label was wrong as well as the count. Logged here because a `pre-settled` plan is where the
  executor trusts the constraints most; one instance, watch for a second. It is also why slice
  158's P1 bounce is not counted against A3 (see A3, same date).
- 2026-08-22 — the discrimination test passed both ways: 159 and 170 declared `cross-cutting`
  honestly (170's justification names the spec's three statements the repo overturned), the small
  slices `pre-settled`; plan-writer research $6.76 on 170's cross-cutting plan (four named surveys),
  0 on the pre-settled ones; planner absolute $14–27 across 155–170 with the interactive refinement
  session the variable part (170: $12.7 of $27). → accepted.

## A2 — Question-gated research budget

**Status:** accepted
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
- 2026-08-22 — plan-writer research 0 on every pre-settled slice in 155–170 and four question-named
  surveys on 170's cross-cutting plan (worker capability framework; controller side;
  bot/MCP/contracts; what 165 landed); the 3–13 % research shares in I2 are the refinement session's
  Explore agents, which the gate does not govern. → accepted.

## A3 — Effort step-down for the plan registers

**Status:** rejected (withdrawn 2026-08-19, plugin 0.7.3)
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
- 2026-08-18 — first read: slice 158 (`pre-settled`, 5 phases, 0.7.0; $81.77). Two round-1s
  ran `high` (P1, P2) and both drew a Major blocking finding; the fuse tripped after P2, and
  P3–P5's round 1 ran `xhigh` — all three signed off on round 1 with advisories only. Cost per
  tier: no Cuadron pathology — the `high` rounds were not longer or dearer (P2 r1 `high` 46
  turns/5 m/$2.84 against P5 r1 `xhigh` 46 turns/6 m/$3.49; different work, not a matched pair,
  so it bounds nothing). Gate-red-on-r1: 0 and uninformative — P1's target (the spec repo) has no
  gate, and P2's gate was green with the prose wrong. **Attribution matters more than the count:**
  P1's finding was plan-authored — the `xhigh` plan-writer's r2 wrote "Two departures … are known"
  into a constraint labelled *cannot derive* while applying a review whose evidence named the
  third (`plan_review_r1.md:62`); the writer transcribed it, the code-reviewer caught it — not a
  tier event. P2's finding is the tier event: the writer lengthened the recovery remedy without
  asking who renders it, and the bot's 400-char per-issue clamp truncated it mid-word — the
  skipped "who consumes this?" check, the failure shape the operator saw with Opus 4.x. Baseline
  for the comparison is the reviewer's round-1 `issues` outcome per phase: 24 % over 140–157
  (19/80), 27 % on same-era `xhigh` rounds (3/11, 155–158); the arm is 1 tier-attributable in 2.
  (An earlier read of 5 % was a telemetry artifact — `findings[].impact` is absent from history
  rows before 144 and on 149–153; use the outcome, not the field.) Rework 19 % — the highest of
  the measured set — but the attributable part is P2's fix pair ≈ $4.02 against ≈ $0.95 saved on
  the two `high` rounds: a wash on cost, one qualitative strike on quality. Confound on record:
  both stepped-down phases were ungated prose, all three `xhigh` phases gated Go, so this slice
  cannot separate tier from gate coverage. The fuse fired at the first available evidence and the
  remaining 60 % of the run went clean — but it also counted P4, whose r1 died `rc=1` with no
  verdict and whose r2 was only the re-dispatch after the operator resumed the loop.
- 2026-08-18 — 0.7.1: a re-dispatch after a crashed or `blocked` session or a protocol bail-out is
  not a redo — it runs at the round-1 tier and does not count toward the fuse; `spawn_executor`
  carries an explicit `redo` flag, an operator-ruled re-dispatch still is one, and the round
  number stays the attempt counter (a3-plan.md's preface has the note). Without it a crash on the
  first two phases trips the fuse on noise and moves a `high` phase into the `xhigh` arm unseen.
- 2026-08-18 — **the next read is pre-registered.** On the next `pre-settled`/`localized` slice,
  each blocking finding on a `high` round 1 is classified before it is counted: *plan-carried*
  (a wrong or missing fact the plan handed the writer as a constraint — P1's kind; the plan
  loop's account, not this one) or *writer-derivable* (a check the writer could have made from
  the repo and skipped — P2's kind; counts). Operator's rule: **one more writer-derivable event
  and the step-down is killed** — `--writer-effort xhigh` or flip `DEFAULT_WRITER_EFFORT`, stage
  2 stays unbuilt. Compare against the 27 % same-era rate, and read the fuse only from 0.7.1.
- 2026-08-19 — slice 159 read: **no signal for the trial — a control point only.** The plan
  declared `cross-cutting` (three requirements across composer, Go worker and a HelmCharts chart
  edit — an honest declaration), so the step-down never engaged: all six writer rounds ran
  `xhigh` (log line 1 says so; history rows agree) and the fuse had nothing to guard. The
  pre-registered read still waits for the next `pre-settled`/`localized` slice. As a baseline
  point: five phases at `xhigh`, one blocking finding (P3, 20 % — on the 24–27 % baseline), and
  its shape was plan-carried, P1-of-158's kind at full effort: the `xhigh` plan-writer settled
  "two causes the worker cannot tell apart", the writer split the refusal on that model, the
  reviewer found the third population (a pod composed before the manifest edit) — enumeration
  blindness at planning altitude, A1's account, nothing writer-derivable. Side effect fixed in
  0.7.2: the run header printed the launch flag (`writer high`) on a run whose shape made it
  inert; it now prints the tier round 1 actually ran at (`writer xhigh`), and 159's header was
  re-stamped in place.
- 2026-08-19 — slices 160 and 161 read (both `pre-settled`, 0.7.2; $63.53 and $37.92 by
  `slice_cost`): **no kill event — and no power.** Seven round-1s ran `high` (160 P1, P1a, P2,
  P3, P4; 161 P1, P2) and all seven went gate-green and `signoff` on round 1: 0 blocking
  findings, 5 advisories (3 comment-prose, 2 Minor design notes — 160 S1, 161 S3), fuse
  untouched, rework 3 % and 11 %. 161's one bail-out was two consecutive API 529s on P2's first
  session (no verdict, $0), re-dispatched at `high` under 0.7.1 and clean — not a writer event;
  it does show `slice_cost` still booking that re-dispatch as rework (round ≥ 2: $1.92 of 161's
  $3.91), which is 0.7.1's principle not yet reaching the cost report. **The operator's worry
  that the slices came out small is right, and it is the whole read.** 160 arrived with seven
  requirements and refinement dropped four; the seven `high` phases changed 27–227 lines (median
  79) in 17–47 writer turns (median 36), against a 140–157 population median of 139 lines / 46
  turns. In that band the `xhigh` baseline almost never draws a blocking finding either: over
  140–157, reviewer r1 `issues`/`blocked` is 2/42 (5 %) on phases ≤ 47 turns against 18/38
  (47 %) above, and 4/39 (10 %) at ≤ 230 lines against 11/17 (65 %) above (146–157 alone: 2/30
  and 1/27 in the small band). Expected blocking for these seven at full effort is ≈ 0.4–0.7,
  so 0/7 is what `xhigh` would have produced too — the read distinguishes nothing. Pooled, all
  nine `high` round-1s to date sit in the small band and drew 2 blocking (158 P1 plan-carried,
  158 P2 writer-derivable) against 2/30–2/42 for small `xhigh` phases: the point estimate is
  against `high`, one-sided Fisher p ≈ 0.14–0.22, n too small to call either way. **The lever
  is also smaller than a3-plan.md assumed.** Effort moves output tokens, and output is ≈ 20 % of
  a writer round's cost — context is the rest, 56 % cache reads and 25 % cache writes on the
  `high` rounds (155–161: code-writer out-$ 21 % of the role; every Opus role 16–33 %). The
  `high` r1s ran 457–466 output tokens/turn against 466 (159), 550 (158/159) and 567 (146–157
  small band) at `xhigh`, so the saving on 160+161's $15.90 of `high` rounds is somewhere
  between $0 and ≈ $1 — ≤ 1 % of slice cost — while 158 P2's one writer-derivable strike cost
  ≈ $4 of rework. The same arithmetic bounds stage 2: the plan-writer's output is 25 % of a 9 %
  role, ≈ 2 % of spend at most. **Recommendation put to the operator: drop** — not on the kill
  rule, which has not fired, but because the shape gate confines the trial to phases where
  neither tier fails, so it cannot gain power, and the upside it gambles for is ≤ 1 % against a
  witnessed ≈ 4 % loss. Decision is the operator's; if dropped, `DEFAULT_WRITER_EFFORT` →
  `xhigh`, the flag stays, stage 2 stays unbuilt. The cross-cutting lesson has no catalogue
  entry yet: the spend is in what a role *reads* per turn (context — cache reads and writes —
  is 67–84 % of every Opus role's cost), not in how hard it thinks; no intervention in
  interventions.md addresses context volume per turn, and the A-lane's ceiling is set by that.
  Advisory texture did not differ by tier (0.7/phase at `high`, 0–3/phase on 155–159 `xhigh`
  signoffs, comment-prose in both).
- 2026-08-19 — **withdrawn: plugin 0.7.3 reverts 0.7.0–0.7.2** (CHANGELOG-workflow.md has the
  entry). The operator's decision on the read above, in their words: "My preference is we
  revert, really … For me it's additional complexity, dead weight." Two alternatives were
  weighed and set aside in the same ruling: `medium` instead of `high` — the lever is bounded by
  output's ≈ 20 % share of a writer round whatever the tier, and the code-writer is itself
  ≈ 24 % of spend, so a tier change would have to reach every role to matter and the judgment
  roles are the instrument; and Sonnet as the writer — tried when the 5 family shipped, "it
  really did not pan out". Stage 2 is not built and will not be. Removed: the round-1 rule,
  `--writer-effort`, the fuse, the run loop's `## Task shape` reader, the `task_shape` /
  `writer_effort` / `effort_fuse` state keys, `effort` on history rows in both loops, the
  header's `shape … · writer …` segment with `round1_writer_tier`, the `redo` flag on
  `spawn_executor`, `slice_cost`'s `tiers` line and effort column; kept: the session round in
  `slice_cost`'s table. A1's `## Task shape` declaration is untouched — it binds the
  plan-writer's investigation and the plan review checks it; only the run loop stopped reading
  it. The record stands: `a3-plan.md`, the four reads above, and slices 158–161's state files
  with their extra keys. What outlives the entry is the measurement it forced — per-turn context
  volume, not effort, sets 67–84 % of every Opus role's cost — which has no catalogue entry and
  is where the A-lane's ceiling actually sits.

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

**Status:** rejected
**Cost:** M–L · **Rank:** 13 (last) · **Depends on:** D3 (judge controls); only if A1–A3 underdeliver

**Summary.** Generate k=2 plans at low effort and have a bare comparative judge pick one, with order
swap and a third vote on near-ties.

**Decides it.** Only becomes live if A1–A3 leave planner share high; the ceiling is bounded because
the planner is 11–29% of slice cost and this doubles plan latency.

**Log**

- 2026-08-14 — catalogued (interventions.md §4) and ranked last by the catalogue's own proposal.
- 2026-08-22 — planner absolute holds at $14–27 on 155–170 and the planner share is a floor effect
  on small slices; doubling plan latency for a bounded saving has no case. → rejected.

---

## B1 — Coder comment policy: verifiable invariants only

**Status:** accepted (as-is)
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
- 2026-08-22 — comment-prose findings 43/114 (38 %) on 155–170 against ≈ 49 % baseline; 170: 8/25.
  The count moved a little, the cost went to zero (B2). What survives is one-line enumeration nits
  ("the fifth open route" after a sixth landed) in files the diff touched — the consult's rider, not
  the writer register, is the lever (W3). → accepted as-is.

## B2 — Reviewer comment scope

**Status:** accepted
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
- 2026-08-22 — $0 prose rework for 27 consecutive slices since 0.4.2 (143–170); every comment-prose
  finding advisory, one sentence, no relitigation; the blocking carve-out extension is not needed. →
  accepted.

## B3 — Explanatory prose lives in docs, not comments

**Status:** rejected
**Cost:** M · **Rank:** 12 · **Depends on:** B1; waits on B2's measurement

**Summary.** Architectural narrative and rationale move to the docs the doc-writer already maintains
diff-based once per slice; inline comments keep only B1's invariants.

**Decides it.** Whether comment churn survives 0.4.2 at a level that justifies losing locality —
the explanation no longer sitting next to the code is a real onboarding cost.

**Log**

- 2026-08-14 — catalogued (interventions.md §5). Held explicitly for the 0.4.2 measurement; the
  grounding motive is slice 152's 16 live comments describing a subsystem that no longer existed.
- 2026-08-22 — the doc phase is already 8–21 % of every slice on 155–170 (170: $33.28, the costliest
  single session at 290k tokens/turn) and comment churn costs $0; moving prose there grows the
  costliest role to save nothing and loses locality. → rejected.

## B4 — Semantic-equivalence bar for prose findings

**Status:** accepted
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
- 2026-08-22 — held across 155–170: the prose findings seen are wrongness findings (170's
  B2/B3/B5/B11/B12/B19/B22 are all "the text counts N, the code has N+1"), no wording-preference
  findings. → accepted.

---

## C1 — Anchoring taxonomy for blocking findings

**Status:** accepted
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
- 2026-08-22 — 155–170: every blocking finding anchored (contradiction, repro-trace, failing-test);
  anchored ≠ blocking held in both directions on 170 — P3 F1 and P6 F1 are Major + repro-trace and
  advisory with the reason stated (a sequencing window the plan closes; a fallback narrower than its
  failure class, unreachable on today's image), and the operator agreed (B10 carded, P3's S3 closed
  as historical). → accepted.

## C2 — Demonstrate-failure-first fix protocol

**Status:** accepted
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
- 2026-08-22 — fired 15 times on 155–170, 0 refutations; every r2 reviewer re-verified the fix in
  the tree; 170 P2's finding was inspection-anchored and handled as such. The refute path is
  unexercised after 15 firings — it is the instrument I3 now rests on, so it stays. → accepted.

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

**Status:** rejected
**Cost:** S–M · **Rank:** 9 · **Depends on:** C2 (which subsumes the executable half)

**Summary.** The executor may return "contested + evidence" instead of a fix; contested findings go
to the existing bare consult with the evidence attached, and the ruling is final.

**Decides it.** Whether an inspection-anchored remainder — spec readings, coverage disputes — still
produces capitulation once C2 handles the executable claims.

**Log**

- 2026-08-14 — catalogued (interventions.md §6). Motive: models wrongly admit a mistake on 42–98%
  of answers they had right when challenged confidently.
- 2026-08-22 — no capitulation event observable in 15 fix rounds (each fix verified by the r2
  reviewer, none refuted, none contested) and precision reads 15/15 (I3); the channel has nothing to
  carry. → rejected.

## C5 — Agentic false-positive validator before fix rounds

**Status:** rejected
**Cost:** M–L · **Rank:** 11 (conditional) · **Depends on:** I3, C1, C2

**Summary.** A bare, evidence-seeking session with repo read access validates each blocking finding
before an executor round is spent — gating only mechanically-checkable anchor classes, never taste.

**Decides it.** Explicitly conditional: build only if I3 shows blocking precision still low *after*
C1+C2. Then judged on validator overturn rate and net cost per avoided fix round.

**Log**

- 2026-08-14 — catalogued (interventions.md §6) with the strongest single measured effect in the
  reading (residual FP 98.3%→6.3%) and the strongest caveat: judgment/policy classes suffered
  50–85% true-positive suppression.
- 2026-08-22 — conditional on low precision after C1+C2; precision reads 15/15 on 155–170 (I3). →
  rejected.

## C6 — Advisory-card lifecycle governance

**Status:** rejected (moot)
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
- 2026-08-22 — the queue it would govern is operator-made cards from close-out dispositions, 0–6 per
  slice, filtered at triage intake; nothing to build. → rejected (moot).

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
- 2026-08-22 — slice 170, the largest report yet (30 entries: A 2 · N 1 · B 22 · Q 0 · S 5;
  initialised on 0.9.2, run on 0.9.3): dispositioned in one sitting in three buckets — 6 cards, 7
  fix-now, 15 closed, A1/A2 done ("everything works as expected" on prd) — and B14 (an expired host
  certificate reads as certified) was carded from the text alone. Shape held (one entry without
  Provenance). Two defects: the Summary and the Notable-events Focus say "no bail-out" under a
  2-bail header (as 161 did), and the test-phase round the loop lost is nowhere in the report; and
  seven of the fix-nows were rider-grade comment nits the consult left for the operator, though the
  Bugs Focus line itself said "one disposition could cover the set". → W3, W4.

## C8 — Mutation-witnessed signoff for test-only phases

**Status:** rejected
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
- 2026-08-22 — same evidence as I5: reviewers mutate unprompted (170: P1, P6, P9, P10); the
  test-only remainder the rule would bind has not shown up. → rejected.

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

**Status:** accepted (as standing rule)
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
- 2026-08-22 — kept as discipline: no reviewer-register growth since 0.5.1's coverage-gap clause,
  and the lean register reads precise (I3 15/15). The dispatch audit is moot while that holds. →
  accepted as a rule.

## D3 — Comparative-judgment toolkit

**Status:** rejected (dormant; no selection step will be built)
**Cost:** — · **Rank:** — (dormant) · **Depends on:** a selection step existing at all (A5)

**Summary.** A reference kit for any future candidate-selection step: order randomization with a
swap-consistency test, majority vote among ≥3 strong judges for near-ties, length normalization,
provenance hiding, and independent samples + vote in preference to multi-agent debate.

**Decides it.** Dormant by construction — the loop issues absolute verdicts today. It activates only
if A5 or a best-of-k fix step is built.

**Log**

- 2026-08-14 — catalogued (interventions.md §7) as reference material, nothing to implement.
- 2026-08-22 — A5 rejected, so no selection step exists to apply this to. → rejected (dormant
  reference).

---

## W1 — Headless waiting

**Status:** new
**Cost:** S · **Rank:** — (from the 2026-08-22 read) · **Depends on:** —

**Summary.** A dispatched agent waits on external work in the foreground (`track_build.py` with a
Bash timeout that outlasts a Jenkins build), never by backgrounding it and stopping — in a
headless `kc session` the turn end is all the driver sees; and the driver's narration says a
session is idle with N background tasks pending instead of printing `[result] Done`. The
wait-by-notification rule itself lives in the in-pod preamble (KubeCoder repo, since 0.7.4); the
plugin's half is the narration and one line in `test-agent.md`.

**Decides it.** No further round returns without a verdict row; `Done`-while-waiting lines gone
from `log.txt`.

**Log**

- 2026-08-22 — catalogued from slice 170's test-phase r1 (`log.txt` L2133–2155): the foreground
  `track_build.py` was killed by Bash's 2-minute default timeout, the agent re-ran it
  backgrounded and stopped to wait — as the preamble says — was re-woken by the notification,
  pushed HelmCharts, stopped again; `Done` printed twice while the session was merely waiting,
  and the loop was restarted 3m45 later (cause unknown — the operator was away; a shared-specs
  environment and Kubernetes are both candidates). Resume worked and the round's durable work
  (rebase, pushes) survived — the operator's point: the system coped. The defect is that the
  round left no record (I2, W4) and that a waiting session is indistinguishable from a finished
  one. Not built.

## W2 — `close_out.py` accepts the report path

**Status:** validating
**Cost:** S · **Rank:** — · **Depends on:** —

**Summary.** `dispatch_line()` names the report *file*; `list`/`append`/`note`/`strike` take the
slice *directory*. Resolve a `.md` argument to its parent (or name the directory in the dispatch
line) so the first call works.

**Decides it.** `Show close_out.py usage` turns per run → 0.

**Log**

- 2026-08-22 — catalogued from slice 170: every session's first `list` failed (`list --file …` or
  `list <report.md>` → "unrecognized arguments" / "slice directory not found"), read `--help`,
  retried — 20 sessions × 3 turns ≈ 50–57 turns, a few dollars and minutes per run, and the
  same trap caught the assessor. Not built.
- 2026-08-23 — shipped (plugin 0.9.6), as T3b's one surviving item. The positional takes the slice
  directory or the report's own path (any `.md` resolves to its parent, before `init` too), and
  the dispatch line shows the invocation whole with the report path, so the first call is the
  right one. T1's fumble table sized it at 225 of the corpus's 1,248 fumble-and-retry turns
  (`list` 188, bare 37). Validating: `fumble` turns on `close_out.py` → 0 in T2's readout.

## W3 — The consult fixes the report's residue entries under the rider

**Status:** new
**Cost:** S · **Rank:** — · **Depends on:** C7

**Summary.** The generation rider already says mechanical residue — comment or formatting fixes
with no behaviour change, in files the slice's diff touched — is fixed by the finder, never
reported. Reviewers cannot commit to the branch, so their comment-nit advisories reach the report
as Bugs entries; the completion consult is the one pass with the tree and the rider, but reads
"residue" as its own scan of the diff. One sentence in `COMPLETION_CONSULT_SITUATION`: walk
the live nit entries; fix those the rider covers, commit, strike with the commit.

**Decides it.** Operator fix-now dispositions per report → 0–1 without the consult touching
anything outside the rider's bound (the sweep re-runs on its commit).

**Log**

- 2026-08-22 — catalogued from slice 170: seven fix-nows (B2, B3, B5, B11, B12, B19, B22), all
  enumeration nits in touched files; the report's own Bugs Focus line said "one disposition
  could cover the set"; the consult reported "no mechanical residue — no TODO/debug leftovers,
  gofmt clean" and noted B6/B7 only. 154's consult fixed ten such entries in one commit;
  163–168's consults struck 0; other slices show 0–3 operator fix-nows. Not built.

## W4 — Bail-outs and vanished rounds become Notable events by construction

**Status:** new
**Cost:** S · **Rank:** — · **Depends on:** C7

**Summary.** The driver already appends refuted findings and funding-consult merges to Notable
events itself; bail-outs reach only the header, which is stamped after the doc phase — and the
doc-writer writes the Summary and Focus lines from the file. Append one N entry at bail time
(reason, phase, the dirty paths) and one when a dispatched session ends without a verdict,
before the nudge.

**Decides it.** The header's bail-out count equals the N entries about bail-outs; a round with no
verdict row has an entry; the Summary stops contradicting the header.

**Log**

- 2026-08-22 — catalogued from slices 161 and 170: both Summaries/Focus lines say "no bail-out"
  under a non-zero header; 170's two bail-outs were not agent failures (slice 168's
  `close-out.md` was dirty in the shared specs worktree — bail #1 blamed "an agent", bail #2
  named the path) and its lost test round is nowhere in the record. Not built.

## W5 — Cross-slice trend readout

**Status:** new
**Cost:** S · **Rank:** — (optional) · **Depends on:** I1, I2

**Summary.** `slice_cost.py --trend <completed-dir>` (or a sibling script): per slice, cost and
the three shares, phases, executor/review rounds, r1 `issues`, findings by impact / category /
anchor, refuted, bail-outs, appended phases, test rounds, doc stage, `close_out.py counts` — from
`state.json` and the report. Measurement only.

**Decides it.** The next read is one command instead of a one-off script.

**Log**

- 2026-08-22 — catalogued: today's 16-slice table was a one-off script over the I1/I2 fields
  (I1/I2 made the fields, not the read). Not built.

---

# Turn-economics steps

Ids **T1–T7** come from [turns-plan.md](turns-plan.md) rather than interventions.md — the same
template, one chapter per step of the turn-economics follow-through.

## T1 — Turn taxonomy

**Status:** accepted
**Cost:** S · **Rank:** — · **Depends on:** —

**Summary.** `context_profile.py` places every turn in exactly one of thirteen classes (`dispatch`,
`edit`, `gate`, `commit`, `record`, `retry`, `fumble`, `wait`, `git-inspect`, `orient-read`,
`work-read`, `think`, `other`), counts the read ops chained inside one Bash command, and marks the
turns a perfect batcher would fold away — so the profile can say what a slice's ≈ 880 turns do,
cost-weighted, and how many of them are avoidable. Research tooling; no plugin change.

**Decides it.** The order and go/no-go of T3–T6, by the size of each class against the bars
turns-plan.md set: `fumble + retry` ≥ 5 % of writer turns, `orient-read` the largest class,
`batchable(strict)` ≥ 15 % of writer turns.

**Log**

- 2026-08-23 — built and read over the frozen 32-slice corpus (809 sessions, 28,176 turns, $2,420):
  §13 of [context-profile-2026-08-23.md](context-profile-2026-08-23.md). **`orient-read` is the
  largest class** — 36.6 % of headless turns and 32.9 % of their cost; 28 % of the writer's own
  turns, 36 % of the reviewer's, 84 % of Explore's. The exceptions are the doc-writer, whose
  largest class is `edit` (29 %), and the test-agent, whose largest is `other` (32 %: `cexec`,
  `curl` and `kubectl` live checks). Work itself is small — `edit` 16 % of turns, `gate` 4 %,
  `commit` 3 %.
- 2026-08-23 — **avoidable = 3,555 turns, 12.6 %, $305** over the 32 slices (median slice: 95 of
  755 turns, ≈ $8 of $60) = `retry + fumble` 1,393 + `batchable(strict)` 2,162. The perfect-batching
  upper bound is 10,174 turns (36.1 %, $874), so the strict count keeps 21 % of it. Against the
  plan's bars: `fumble + retry` **4.5 %** of writer turns (below 5), `batchable(strict)` **8.1 %**
  (below 15), `orient-read` the largest class (bar met). Read: **T4 proceeds** and is where the
  money is; **T5 folds in behind it** rather than earning its own A/B — writers already chain
  reads inside one Bash command (1.67 reads per reading turn, reviewers 2.5, Explore 3.0), so the
  memo's "1.07 tool calls per turn" overstated the serial-read gap; **T3b stays worth its S** on
  one item, W2, which alone is 188 of the 1,248 fumble-and-retry turns — the rest are wrong-path
  guesses (`grep` 87, `ls` 73, `sed` 29, `cat` 19, `Read` 20), which no hook can fix, plus
  `cexec iac` 51 and `track_build.py` 32.
- 2026-08-23 — two corrections to the memo's §1 fall out of the taxonomy. Bash edits were invisible
  to the profiler (WRITE_TOOLS only), so orientation was being measured against a first `Edit` that
  43 of 184 code-writers never make; counting heredoc rewrites, `sed -i` and redirections, 181 of
  184 edit and the median writer's first edit is turn 13, not 15. And "136/184 writers run the gate
  before editing" matches no cut of the corpus: 164 of 184 run a gate at all, 12 of 181 run one
  before their first edit. Both fixed in interventions-2.md §1.

## T2 — The context readout per run

**Status:** accepted
**Cost:** S–M · **Rank:** — · **Depends on:** T1

**Summary.** The per-session replay and the turn taxonomy T1 built move into the plugin as
`turn_profile.py`; `slice_cost.py` prints a per-role turn table and `--write-state` writes it into
`state.json` as `cost.turns`. Every run now records what its turns did — per role: sessions, turns,
tools and reads per turn, orientation turns, `ctx_first` / `ctx_mean` / `ctx_max`, retry-and-fumble
turns, batchable(strict) turns, prefix breaks; per slice: cost per turn and the avoidable share.
The instrument every later step is read on, not a trial of anything.

**Decides it.** Nothing on its own — done when a slice's `state.json` carries the block and
`slice_cost.py` prints it. What it decides is whether T3–T6 can be judged on the slices they run
on rather than by replaying the corpus by hand.

**Log**

- 2026-08-23 — shipped (plugin 0.9.5). `turn_profile.py` (+ 21 tests) carries the replay, the
  tool-call classes and the per-turn taxonomy; `slice_cost.py` aggregates them per role and the
  `cost` block gains a `turns` sub-block. `context_profile.py` imports the plugin module instead of
  its own copy, and regenerates the 32-slice profile byte-identical — the lift changed no number.
  The close-out `Run:` header is untouched (§ Open decisions 1: table + block only).
- 2026-08-23 — the readout on slice 170 (the four-repo `ssh_transport`, the corpus's most expensive):
  2,110 turns at $0.101, avoidable 386 (18.3 %, $39) — well above the corpus median of 12.6 %,
  concentrated in the code-writer (921 turns, 31 orientation turns at the median, 122 batchable) and
  the test-agent (20 retry-and-fumble turns in 95). Which is the T4 case restated on one slice: the
  writer's orientation is where the money is.

## T3 — The free set: a lighter prefix (T3a) and the close-out tool's path (T3b = W2)

**Status:** accepted
**Cost:** S · **Rank:** — · **Depends on:** T1, T2

**Summary.** Every dispatched session's prefix loses the operator's auto-memory and Claude Code's
bundled skills — two env vars in `SPAWN_ENV`, the environment every `create-headless` already
carries — and, since 0.9.8, the plugins' skill listings and (every role but the test-agent) the
operator's MCP servers, through kc's claude-flag pass-through (`spawn_flags`); and `close_out.py`
takes the report's own path as well as the slice directory, with the dispatch line showing the
whole invocation. Quality exposure near zero by construction: the env-var half removes nothing a
dispatched role ever used, the kc half a few dozen sub-agent Jenkins/gitblit lookups across a
thousand sessions, and nothing a role is told changes but one tool line.

**Decides it.** T2's readout on the next two or three slices: `ctx_first` per role down by
≈ 3.3 k against the corpus's 31–34 k (≈ 7–8 k once 0.9.8's kc half is in the runs), and `fumble`
turns on `close_out.py` at zero. Both are
mechanical; what the readout confirms is that the spawn path reaches real runs as it reached the
probes.

**Log**

- 2026-08-23 — T1 reduced T3b: `fumble + retry` 4.5 % of writer turns (under the 5 % bar), and
  of 1,248 such turns `close_out.py` is 225 while the rest are wrong-path guesses no hook fixes
  (`grep` 87, `ls` 73, `sed` 29, `cat` 19, `Read` 20, `cexec iac` 51, `track_build.py` 32). The
  hook programme is not built; W2 is.
- 2026-08-23 — T3a measured before shipping, one trivial `run_kc_session` dispatch per role in
  `/work/KubeCoder`: baseline `ctx1` 32,172 / 32,760 / 31,677 / 31,686 / 33,957 (writer, reviewer,
  test-agent, doc-writer, consult). `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` −1,320;
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` through `-e` no effect (settings `env` beats the spawn env)
  and moot — the claude.ai servers barely load headless (−316 via `--settings`) and no headless
  role ever called one; `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1` (found in the 2.1.241 binary, not
  in the plan) −1,207. Through kc, the two together: **−3,347 for every role**, consult −4,029 —
  ≈ 10 % of the prefix. Corpus check behind the safety claim: in 809 sessions no dispatched role
  read or wrote a memory file, and headless roles invoked a skill twice (neither bundled).
- 2026-08-23 — shipped (plugin 0.9.6): `SPAWN_ENV` + agent-dispatch.md § Spawning; `close_out.py`
  positional + dispatch line + close-out.md contract; and `plugin_version` in `state.json` /
  `plan_state.json` (runner-state.md) so runs read before/after a plugin change without guessing
  from dates. The unreached ≈ 3.6 k (`--disable-slash-commands` −3,233 less the bundled 1.2 k;
  `--strict-mcp-config` −1,612, measured on `claude -p` directly) needs `kc` to pass claude flags
  through — written up in turns-plan.md § T3a as a KubeCoder ask, the operator's to file.
- 2026-08-23 — the kc half shipped (plugin 0.9.8): `kc session create-headless` gained
  `--disable-slash-commands` / `--strict-mcp-config` / `--mcp-config`; `run_kc_session` takes
  `flags`, `spawn_flags(role)` sends the first to every role and the second to every role but the
  test-agent (Jenkins: 118 calls in 21 of 64 corpus sessions; kept whole, not by name — the server
  is the operator's, not the project's), nudges resume with the role's flags. Corpus re-read first,
  sub-agents attributed to their dispatcher: every other headless role reached an MCP server in
  ≈ 10 of ~1,100 sessions (Jenkins 32 calls / 6 sessions, gitblit 10 sessions, `notification` 4,
  the reviewer's Trello cards pre-C7), plan-writer in 0 of 98 — the trade-off as weighed. Measured
  as the env-var half was, one trivial dispatch per role: `ctx1` **24,488 / 25,040 / 25,553 /
  23,966 / 25,494** (writer, reviewer, test-agent, doc-writer, consult), −2.8 to −4.4 k against
  0.9.6 and −6.1 to −8.5 k against the corpus's 31–34 k; all nine `dev:` agents still register in
  every role, the strict roles hold no `mcp__` tool, the test-agent the full Jenkins set. Still
  **validating**: T2's readout on the next two or three slices decides, now against 24–25.5 k.
- 2026-08-23 — **first read on real runs (preliminary — the operator runs more before judging):**
  slices 173/174/175 (0.9.8) and 179 (0.9.7), the method and tables in
  [t4-read-2026-08-23.md](t4-read-2026-08-23.md) § 4, regenerated by `tools/t4_readout.py`. Per-role
  `ctx1` medians on 0.9.8: reviewer 25.8 k, doc-writer 24.5 k, test-agent 28.3 k, consult 27.7 k,
  plan-writer 25.3 k, plan-reviewer 24.8 k — −6.5 to −7.0 k against the corpus (test-agent −4.0 k,
  the MCP listing it keeps), as the probes promised; 179 sits at the env-var half's −3.3 k. Slice-wide
  $/turn 0.073–0.080 against the corpus's 0.086; reviewer $/phase −10 % with its turns flat (the
  reviewer's dispatch being the one T4 left alone, that is T3 in isolation). No headless role
  called an `mcp__` tool in any of the four slices; the test-agent tracked Jenkins via
  `track_build.py`; no skill call, no "no such tool" error. T3b: the code-writer's `close_out.py`
  fumbles are 0 in 16 sessions, but `close_out.py --help` is still called once per session by the
  doc-writer (4 of 4 slices) and by the test-agent, reviewer, consult and plan-reviewer — 9 turns
  over four slices; only the writer's dispatch shows the invocation whole. Leftover, not acted on.

- 2026-09-01 — **confirmed at scale** ([readout-2026-09-01.md](readout-2026-09-01.md) § 5; 15
  slices 180–193 + Ansible 016, 118 reviewer / 15 doc-writer / 15 test-agent sessions): `ctx1`
  reviewer 25.8 k, doc-writer 24.5 k, test-agent 28.3 k against the corpus's 32.4 / 31.1 /
  32.3 k; reviewer $/turn 0.090–0.096 against 0.107; no headless role called an MCP tool.
  What the trim bought the writer, the digest spends (§ T4) — the writer's cache-read dollars per
  turn are flat against the ≥ 2.1.234 corpus. → accepted.

## T4 — The phase digest in the writer's dispatch

**Status:** accepted
**Cost:** S–M · **Rank:** — · **Depends on:** T1, T2

**Summary.** Every executor round's prompt — first round and fix rounds, each a fresh session —
carries `build_phase_digest()`'s rendering of what the driver already holds, rebuilt per round:
the slice's intent paragraph and the plan's title, `## Requirements / rulings` and `## Not in
scope` verbatim, this phase's section whole, earlier phases' done-records (from their `**Done`
opener — not their phase text), later phases' headings and targets, every acceptance criterion,
and `git diff --stat` of what earlier phases changed per touched repo. "Read the whole plan" is
gone from the prompt and the register; the plan stays the file the writer edits and opens for what
the digest points at. The reviewer's dispatch is unchanged. Memo P3.1; the plan's one measured
trial so far, before/after against the corpus rather than arms (turns-plan.md § T4 Read).

**Decides it.** T2's readout on the next 2–3 slices against the corpus slices in their size band:
writer orientation turns before the first edit (corpus median 14), plan.md reads per writer
session (≈ 1 → 0 is the mechanism working), `ctx_first` (expected +≈ 8 k — the digest's size —
not a regression), $/phase; and the quality instruments of § Protocol — r1 blocking-finding
rate, refuted findings (baseline 0), gate-red, rework share (2–19 %, median ≈ 7 %), abstention
verdicts (baseline below), appended phases. Kill on any instrument outside its baseline range on
two consecutive slices, or cost not below baseline.

**Log**

- 2026-08-23 — the digest's content settled against the plans themselves. Done-records open
  `**Done (P<id>).**` in 296 of 296 done phases across both spec repos (an unwritten convention,
  now plan-template.md's rule), so "earlier done-records verbatim" needs no format change — the
  digest reads from that opener. The `## Requirements / rulings` section goes in, which neither
  the memo's list nor the plan's carried: it is the plan's intent and the mid-run rulings' home,
  and a digest that pointed at it would send the writer back to the whole file — the trial would
  then test a digest riding beside the plan read, not replacing it.
- 2026-08-23 — size, over every phase of every corpus plan (296): **30 KB ≈ 7.7 k tokens at the
  median phase**, p90 57 KB, max 110 KB (140's P12), against the plan's 3–5 k estimate and a 45 KB
  median plan (the digest is 74 % of the plan by bytes). Composition: rulings + not-in-scope ≈ 40 %;
  earlier done-records 2.5 KB each at the median and **31 lines against the ~25-line cap — 77 %
  of records exceed it**, max 101 lines; the phase's own section 2.3 KB; acceptance criteria 5 KB
  per slice (max 20 KB); the intent paragraph 260 bytes. Without the rulings: 18 KB ≈ 4.6 k — so
  the estimate was the miss, not the rulings. The digest does not truncate a record; if the
  readout shows records dominating it, the cap is the lever, a separate step.
- 2026-08-23 — shipped (plugin 0.9.7): `build_phase_digest` + `plan_sections` / `slice_intent` /
  `done_record` in run_loop.py, appended by `spawn_executor` to every executor round (the three
  executor prompts name it; `EXECUTOR_PROMPT` opens on the phase instead of the file); three
  tests; code-writer.md's opening and rule 11, run-loop.md § The per-phase round, plan-template.md's
  done-record bullet. Files touched per repo from `state.json`'s `slice_base` — `..<merge base>`
  for the target repo, `..<base branch>` for the others — elided past 40 rows.
- 2026-08-23 — the pre-check, the abstention baseline (turns-plan.md § T4 Pre-check): over the
  corpus's 179 `code_review_r*.md` files, the generous pattern set (cannot/could not/unable to
  determine|verify|confirm|…, unverifiable, insufficient …, no way to tell) hits 10 times, and
  read in context **none is an abstention** — nine are the reviewer's idiom "the gate / the test /
  the reader cannot see X" used as evidence *inside* a confident finding, one is soft. A broader
  sweep of every bare `cannot` / `could not` (182 occurrences, ≈ 44 epistemic-shaped ones read)
  adds three soft cases: **0 hard, 4 soft abstentions, in 4 of 32 slices** — each a failed
  concrete falsification stated plainly and still followed by a graded verdict. Baseline for the
  T4 readout: a hard abstention on any T4 slice is a signal; the soft count is ≈ 0.1 per slice.
  Evidence: [abstention-baseline-2026-08-23.md](abstention-baseline-2026-08-23.md).
- 2026-08-23 — **first read (preliminary — the operator runs more before judging):** slices
  173/174/175 on 0.9.8 and 179 on 0.9.7, against the corpus's 2–4-phase band (12 slices, 36 phases)
  and the 16x–170 tail; method, tables and the per-session lines in
  [t4-read-2026-08-23.md](t4-read-2026-08-23.md), regenerated by `tools/t4_readout.py all`.
  **Mechanism:** whole-plan reads before the first edit 0 of 16 writer sessions (corpus 182 of 184
  read it); every remaining plan.md touch is the done-record append (`grep -n "^###"` → `sed -n`
  region → heredoc insert); no verification.json / slice.md / CLAUDE.md reads; turn 1 is `git
  branch` + the target file, fix rounds open on the review file. Orientation before the first edit
  median 8 (r1: 10) vs 11.5 in the band and 16 in the tail; context at the first edit 64 k vs
  77 k / 85 k. **Cost:** writer $/phase $2.82 vs $4.83 (band; $5.53 KubeCoder-only) — −40 % pooled,
  writer turns/phase −33 %; but the median r1 writer session is only −8 % ($2.35 vs $2.56, 33 vs
  35.5 turns): the pooled gain is the missing long tail (p90 47 vs 78 turns, max 50 vs 150), which
  n = 10 cannot yet attribute to the digest. Whole-slice $/phase −17 % against the band. The digest
  measures ≈ 9–10 k tokens on the dispatch (writer `ctx1` 35.5 k vs reviewer 25.8 k in the same
  slices) — above the 7.7 k estimate (≈ 3 chars/token, not 3.9); net `ctx1` +4 k against the corpus
  after T3. **Quality, all inside the baseline:** r1 blocking phases 3/13 (179 P2, 173 P1, 173 P2 —
  all test-reach gaps found by reviewer mutation, none a plan-context miss), refuted 0, gate-red 0,
  abstentions 0, rework 4.9 / 6.5 / 17.7 / 12.3 %; 173's appended P4 is the test-agent's rebase
  conflict with the parallel lane 174. Nothing trips the kill rule. **Confounds:** Claude Code
  2.1.241 — the writers made zero Read/Edit/Write tool calls in 16 of 16 sessions (all reads `sed`/
  `cat`/`grep`, all edits heredocs and `python3 -`), a shift that began at 2.1.234 and is in the
  corpus tail; the band's early slices ran under other effort settings (writer thinking 2.7 k per
  session there, 11 k in the tail and now). Still **validating**; 2–3 more slices decide between
  "median −8 %" and "pooled −40 %".

- 2026-09-01 — **judged** on 180–193 + Ansible 016 (119 writer sessions; 0.9.8 × 11 slices,
  0.9.12/0.9.13 × 4; 181, the $294 desktop-extension slice, counted apart):
  [readout-2026-09-01.md](readout-2026-09-01.md) § 3, `tools/writer_economics.py bands`.
  **Mechanism:** the pre-edit plan read is gone on plans of ≤ 6 phases (0 in 16/18 sessions),
  half-gone on 7–14-phase plans (0 in 32/63 — the rest re-open the heading map and their own
  section, 1–2 turns); verification.json / slice.md reads 0 everywhere. **Cost, r1 sessions by
  plan-size band (median $ / turns / orientation):** 2–4 phases 2.70 / 37 / 12 → 2.40 / 34 / 8
  (0.9.8) and 2.05 / 26 / 7 (0.9.12+); 5–8 phases 2.73 / 39 / 13 → 2.96 / 37 / 12 and 2.92 / 39 /
  11; 9+ phases 3.43 / 44 / 16 → 4.67 / 40 / 14. Pooled writer $/phase 4.65 → 4.69 (0.9.8
  without 181) → 3.07 (0.9.12+, small slices). The first read's −40 % was the draw: it recurs only
  in the 2–4 band; the digest saves 1–5 orientation turns and 7–16 k at the first edit on small
  and mid plans, nothing on large ones, and costs ≈ 10 k on every dispatch — the writer's dollars
  are unchanged, because its context per turn is flat (prefix −7 k, digest +10 k) and its output
  per turn rose (§ 4 of the readout: +330 tokens/turn, +194 of them thinking, effort `xhigh`
  throughout; ≈ $0.01/turn, $3–4/slice, not a lever). **Quality:** refuted 0, gate-red 1 (193 P6,
  a real-clock timer test, green on the fix round), abstentions 0, appended 0, rework median
  8.3 % (184 at 27.6 %: two witness-a-repro fix rounds), test rounds 1 (182: 2); r1 blocking
  phases 21/78 = 27 % on 0.9.8 (13/63 = 21 % without 181; 1/18 today) against 11 % — moved by
  the `coverage-gap` class alone (12 of 22 findings; 1 of 21 in the corpus), reviewer mutation
  activity per session unchanged, fixes cheap, nothing escaped; #720's read has the fuller cut
  and a coverage-gap-share watch. Not read as a kill. → **accepted: kept as the dispatch's
  vehicle; not the turn cut.** T5 folded and dead, T6 superseded by the doc rework, T7 parked —
  the turns plan has no further step.
