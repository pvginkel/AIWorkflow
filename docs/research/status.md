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

## A3 — Effort step-down for the plan registers

**Status:** new
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

**Status:** new
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

**Status:** new
**Cost:** S · **Rank:** 6 (with B1) · **Depends on:** — (subsumed by B2's extension if that lands)

**Summary.** A prose finding must show the text is *wrong* — contradicted by code or spec — not that
different words would be better. Meaning-preserving wording drift is not a finding.

**Decides it.** Comment-category finding rate (I1); and whether B2's extension lands first, in which
case this folds into it.

**Log**

- 2026-08-14 — catalogued (interventions.md §5). One register rule.

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
