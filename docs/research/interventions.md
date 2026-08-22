# Intervention Catalogue — Overthinking and Review Economics

Companion to [research.md](research.md). This is the standing menu of interventions the reading
supports: every candidate we can defend from the evidence, whether or not we ever action it.
Selection happens separately and jointly; nothing in here is a decision.

Produced 2026-08-14 from: full reads of the six ★ papers and the Opus effort documentation,
structured extractions of the twelve remaining papers (including Shi et al. 2406.07791, located and
mirrored into `articles/`), a survey of the current loop (`plugins/dev` at 0.4.2), and a grounding
sample of five recent slice runs (KubeCoderSpecs 149–153). The per-paper extraction reports behind
every citation here live in [extracts/](extracts/).

**How to read an entry.** Each carries: **Status** (`in place` / `partial` / `new` /
`decision record`), **Evidence** (paper + specific finding), **Effect** (expected, with measured
analog where one exists), **Measure** (how we'd know), **Cost** (S/M/L implementation effort),
**Risks** (failure modes and what we lose). Cross-references like C2→I3 mean "depends on".

---

## 1. Grounding: what our own data says

Sample: slices 149–153 (most recent 5 of 129 completed KubeCoderSpecs slices; $45–174 per slice).
**All five predate 0.4.2's comment rules — slice 143, running now, is the first on 0.4.2.** So
these numbers are the *baseline* against which 0.4.2 gets measured.

- **Planner cost is flat regardless of task size.** Planner core (orchestrator + plan-writer +
  plan-reviewer) sits at $11–19 across a 4× spread in slice cost; 22–29% share on small slices vs
  11–12% on large. Research-subagent spend ($1.31–17.77) is uncorrelated with need: slice 153,
  whose slice.md said *"you are not designing anything"*, still spent $16.17 planner + $11.55
  research = **$27.72 (34% of the slice) before any code existed**. Problem A is real and it is a
  *floor* problem: the planner never scales down.
- **Comment/prose findings are ~49% of all findings** (28 of 57 across the sample). Slice 153's
  review output was 100% comment-related — $11.70 of rework chasing prose accuracy. The churn
  concentrates where a phase's deliverable *is* prose (152's two prose phases produced 10 of its 14
  comment findings). Problem B is real at baseline; whether 0.4.2 already fixed it is unmeasured.
- **Within-run amplification is bounded, not unbounded.** Review+rework is a stable 9.3–15.7% of
  cost across all five slices; no phase went past review round 2; every escalation resolved in one
  fix pass. The runaway version of problem C, if it exists, lives *across* slices (advisory cards,
  appended phases, deferred findings — 153 deferred one finding to 143) and is currently
  unmeasured.

Current state relevant to the entries below (from the loop survey, 0.4.2):

- Code-review findings carry Blocker/Major/Minor severity plus a `blocking`/`advisory` impact tag;
  **only blocking findings trigger fix rounds**; advisory rides to close-out as cards.
- Comment/prose findings are **advisory by default** (blocking only if following the words causes
  harm), earn one plain sentence, and are **never relitigated across rounds**.
- Blocker/Major already require "failing-input logic or a test sketch" or they demote to Minor.
- Round caps: fix cap 3 per gate, review rounds capped at 5 with a per-round rising funding bar;
  appended work passes a generation bar (gen 3 bails to operator).
- Models: Opus `xhigh` for every role except the always-Sonnet test roles. No per-task routing —
  a graded lane was tried and retired ("produced Opus redos whenever mechanical turned out to mean
  judgment").

---

## 2. Where the briefing is wrong or overstated

1. **"Error accumulation in long chains" (S2 note) cites the wrong paper.** Chen et al.
   (2412.21187) show *redundancy* — later solution rounds are correct-but-repetitive, >92% of the
   time the first solution was already right — not compounding error; their one accuracy loss came
   from *under*-thinking (truncation on hard problems). The claim is supported instead by
   2502.18080: erroneous reasoning rounds grow monotonically with chain length.
2. **FrugalGPT cascades do not escalate on "verified failure".** The stop signal is a learned
   confidence proxy (DistilBERT scorer) that can be indecisive and needs thousands of labeled
   examples. Any cascade we build would use genuinely verified signals (gates, review verdicts) —
   stronger than what the paper demonstrates, but the paper doesn't demonstrate *our* variant.
3. **Problem C's "grows without bound" is not what our data shows within a run** (stable 9–16%
   rework share, no phase past round 2 — the 0.4.x caps appear to work). The defensible framing:
   the blocking-finding *false-positive rate* is the cost driver (S7-style overcorrection, ~49%
   comment share at baseline), and possible *cross-slice* accumulation via cards/appended work is
   unmeasured.
4. **The S5 note conflates two mechanisms.** "Review verdicts without external feedback are
   unreliable and can degrade output" is Huang et al. (intrinsic self-correction flips correct
   answers to incorrect more often than the reverse). Sharma et al. show something different:
   preference signals reward agreement and persuasiveness over truth, and producers wrongly
   capitulate when challenged (42–98% wrongly admit a mistake on answers they had right). Both
   matter — one indicts the reviewer's verdict, the other the coder's capitulation.
5. **Self-preference is a familiarity (perplexity) effect, not self-recognition per se**
   (Wataoka et al.: judge preference tracks how familiar the text is *to the judge*, nearly
   identically whether or not the judge authored it). Consequence: separating producer and reviewer
   by prompt/session/register does **not** neutralize stylistic bias when both are the same base
   model — only a genuinely different model, or grounding in external evidence, does.
6. **Verbosity bias is task-dependent in direction** (Saito et al. measure longer-preferred in
   creative/chat tasks; they cite the opposite in summarization). Treat it as "length distorts
   judgment", not "longer always wins".

---

## 3. I — Instrumentation (briefing Q1)

### I1. Findings telemetry in the review contract — **new, S**
Reviewer verdicts gain machine-readable per-finding fields, persisted into `state.json` history:
severity, impact tag, category (`functional` / `comment-prose` / `style` / `other`), and **anchor
type** (see C1: failing test / repro trace / analyzer output / AC-or-spec contradiction / coverage
gap / none).
**Evidence:** producing the grounding above took an agent 38 tool calls of grep + manual
classification; the practitioner literature (Johnson et al. 2013; Christakis & Bird 2016, via
LLM4FPM) puts the tolerable false-positive rate for analysis tools **below 20%** before trust
collapses — a target we cannot track today.
**Effect:** makes problems B and C measurable per run; gives the 0.4.2 before/after for free.
**Measure:** self-proving. **Risks:** reviewer self-labels categories flatteringly — audited by I3
sampling.

### I2. Standard cost readout per run — **new, S**
`slice_cost.py` already prices per role/phase from transcripts. Add the derived ratios as a
close-out artifact appended to `state.json`: planner share, research-subagent share, rework share
(rounds ≥2 + consults), cost per merged slice.
**Evidence:** the A-grounding numbers above; Chen et al.'s outcome-efficiency diagnostic (what
fraction of spend contributed to the accepted result) as the model to approximate.
**Effect:** trend lines for problem A across slices instead of one-off archaeology. **Cost:** S.

### I3. Sampled blocking-finding precision audit — **new, S–M**
Periodically sample N blocking findings across recent slices and adjudicate valid/invalid (operator
spot-check, or an evidence-seeking bare session per C5's mechanics). Metric: **blocking precision**,
target ≥80% (the <20% FP practitioner bar).
**Evidence:** S7 measured 26–88% false-rejection rates for LLM spec-conformance judgment — reviewer
precision cannot be assumed; Sifting the Noise shows evidence-seeking validation of findings is
feasible with strong backbones.
**Effect:** the single number that tells us whether C-interventions are needed and whether they
worked. **Risks:** adjudication itself is judgment — anchor it in C1's evidence taxonomy.

### I4. Cards ledger — **new, S**
Track advisory-card flow: created vs closed per slice, net backlog. Answers whether problem C's
"unbounded" half lives cross-slice.
**Evidence:** grounding found within-run amplification bounded while 153 deferred a finding to 143;
the trust-collapse literature is about unmanaged queues, not individual findings.
**Cost:** S (cards are already recorded in `state.json`; this is aggregation).

### I5. Witnessed-signoff field in the review verdict — **new, S** (added 2026-08-15)
The reviewer verdict gains one field — `witnessed: mutation | targeted-run | none` — naming what
the review rests on beyond reading: a mutation it ran that took a test red, a targeted run, or
nothing executed. Persisted into `state.json` history beside the findings, on I1's path.
**Evidence:** slice 146 — every review verified by mutation and said so in prose only (P4's
re-witnessed the phase's own done-condition rather than taking the done-record's word). Keyword
proxy across the record ("mentions mutation", not "verified one"): 13/29 reviews on 149–153
(pre-0.4.3), 10/12 on 144–146, 4/4 on 146 — the shift lines up with C2 landing, witness-first
generalising from the fix round into signoff, the cheaper and more frequent half. Today I3 cannot
tell a mutation-verified signoff from a read one.
**Effect:** signoff evidence becomes countable the way I1 made findings countable — I3 gains a
second axis (precision of blocking findings, evidence behind clean signoffs). **Measure:**
self-proving. **Cost:** S (one verdict field, one persist line in `run_loop.py`, the register's
Output section). **Risks:** D2 — a named field nudges toward filling it with something other than
`none`, i.e. more mutation work per review; 146's most mutation-heavy review cost $2.74 (10 m),
affordable per phase and worth watching if it becomes universal. An honest `none` must stay
costless.

---

## 4. A — Planner effort (problem A)

### A1. Task-shape declaration in the plan contract — **new, M**
The plan-writer's first output becomes a declared task shape — e.g. `pre-settled` (slice.md fixes
the design; planning is transcription), `localized` (single component, no new pattern),
`cross-cutting` (investigation warranted) — with a one-line justification **anchored in slice.md
facts**, and the register binds investigation to it: `pre-settled` forbids research subagents and
repo sweeps. The plan-reviewer's structural pass checks the declaration against slice.md. This
constrains the planner's *output contract*, not its thinking settings — the lever briefing Q2 asks
about.
**Evidence:** Fan et al. (MiP): models *notice* early that a question needs no further work but
"don't dare" act on the observation and keep thinking — an explicit contract slot gives the act
path; Gema et al. (inverse scaling): models misestimate difficulty from surface framing, so the
declaration must rest on checkable facts (is the design settled in slice.md?) rather than felt
complexity; grounding: 153's $27.72 pre-code spend on a nothing-to-design slice.
**Effect:** on pre-settled/small shapes, planner+research spend approaches the ~$11–13 floor —
roughly **$10–15 saved per small slice (15–30% of its cost)**.
**Measure:** planner+research share by declared shape (I2); mis-declaration rate via plan-reviewer
findings.
**Cost:** M (`plan-template.md` schema + plan-writer + plan-reviewer registers).
**Risks:** under-declaration starves a genuinely cross-cutting slice of investigation — the
plan-reviewer AC-completeness check and the run loop's gates are the backstop; unlike the retired
complexity-grading lane this routes **behavior on verifiable properties of the ask**, not models on
predicted difficulty (see A4 for why that distinction is load-bearing).

### A2. Question-gated research budget — **new, S**
Research subagents may be dispatched only against a named open question the plan must settle; the
dispatch names the question; a settled question cannot be re-dispatched. Structural, not numeric —
deliberately no token cap.
**Evidence:** grounding: research spend uncorrelated with need ($11.55 on 153); TALE's token
elasticity: budgets set too tight *increase* output (a 10-token budget produced more tokens than a
50-token one) — hard numeric caps backfire, structural gates don't; Cuadron et al.'s
analysis-paralysis pattern is exactly unfocused exploration unattached to a question.
**Effect:** removes exploratory drift; complements A1. **Measure:** research share (I2), questions
per dispatch. **Cost:** S (register prose). **Risks:** questions can be manufactured — reviewable
in plan output.

### A3. Effort step-down for the plan registers, escalation on verified signals — **new, S–M**
Run plan-writer at `high` (or `medium`) instead of `xhigh`; escalate to `xhigh` only when the plan
loop's real signals fire: writer hands back `questions`, reviewer verdict `issues`, or AC-coverage
gaps. A cascade on *measurement*, using signals FrugalGPT never had — actual review outcomes, not a
learned proxy.
**Evidence:** Cuadron et al.: two low-effort samples + selection matched/beat one high-effort run
at 57% of cost; effort docs: Opus 5 guidance is to "use low and medium liberally as your primary
control … wherever your evals show quality holds", `high` equals the default; 2502.18080 (and its
prompting-only replication): optimal effort is task-dependent and *excess* effort actively hurts on
easy tasks.
**Counter-evidence, stated honestly:** Cuadron et al. also found o1-*low* had 35% **higher**
overthinking scores than o1-high in agentic settings — less effort is not automatically less
overthinking; and effort must stay fixed within a session for prompt caching (each dispatch is a
fresh session, so tiering at dispatch boundaries is safe).
**Effect:** planner spend down on the ~$11–19 floor itself; unknown quality delta — that's what the
trial measures.
**Measure:** A/B on declared-small shapes (needs A1): plan-reviewer verdict rate, downstream
gate_red/appended-phase rate, planner cost per tier.
**Cost:** S (`MODELS` dict) + M if an escalation re-run path is added to `plan_loop.py`.
**Risks:** cheap-plan failures surface downstream where they're expensive — hence trial-gated,
small shapes only.
**Scope amendment (2026-08-14, decided; 2026-08-18, shipped in part):** the operator widened the
entry to both loops as one cascade — the run side is the large majority of slice spend — and
staged it run-loop-first ([a3-plan.md](a3-plan.md)). Stage 1 shipped as plugin 0.7.0: the
**code-writer's executor round 1** runs at `high` (`--writer-effort`, default `high`) on a
declared `pre-settled`/`localized` shape, every round ≥ 2 and every judgment role stay `xhigh`,
and a fuse returns round 1 to `xhigh` once two phases have needed a redo. The plan-register half
above — the `escalate` outcome and the sticky escalation in `plan_loop.py` — is stage 2,
conditional on stage 1's read, and unbuilt.
**Withdrawn (2026-08-19, plugin 0.7.3 — 0.7.0–0.7.2 reverted)** after the 160/161 read: the shape
gate confined the trial to phases where neither tier draws a blocking finding, and effort moves
only the ≈ 20 % of a writer round that is output tokens, so the saving was ≤ 1 % of a slice
against one witnessed ≈ 4 % rework strike; the operator ruled it dead weight. Stage 2 was never
built. [status.md](status.md) A3 has the numbers and the words.

### A4. Keep rejecting upfront complexity grading — **decision record, none**
The reading explains *why* the graded lane failed, which is worth recording so it isn't retried:
difficulty is not a stable property of the request (FrugalGPT: cost/quality rankings invert across
datasets; cheap models beat GPT-4 on 6–13% of queries), models misjudge difficulty from surface
framing (inverse scaling: famous-paradox framing triggers complex solutions to trivial questions),
and judges are least reliable exactly on near-ties (Shi et al.: position consistency collapses as
the quality gap δq → 0) — an upfront grader lives entirely in that regime. Escalation designs (A3)
condition on *outcomes*, which is strictly more information.

**Scope, to prevent misreading:** what this record rejects is the grade as an **automatic routing
input** — model or effort selection keyed on predicted difficulty, where a misjudged grade
silently ships its consequences. A label a human adjudicates before anything acts on it — the
triage category filter (v0.4.4) — is not this lane: the grade carries no automatic consequence,
and the near-tie unreliability lands on the operator's desk instead of a dispatcher.

### A5. Best-of-k cheap plans with bias-controlled selection — **new, M–L, rank low**
Generate k=2 plans at low effort; a bare comparative judge picks one, with order swap and (if close)
a third vote.
**Evidence:** Cuadron et al.: lowest-overthinking@k=2 hit 27.3% vs 29.1% for high effort at 57%
cost, @k=3 surpassed it; Shi et al. supply the selection protocol (swap consistency, majority for
near-ties); Huang et al.: prefer independent samples + vote over "debate" (debate ≈ self-consistency
at higher cost).
**Effect:** bounded — planner is only 11–29% of slice cost, so the ceiling on savings is low and
this *doubles* plan latency. **Cost:** M–L (new plan-loop mode + judge with D3 controls).
**Risks:** verbosity/familiarity bias in the judge (length-normalize; both candidates same-model so
authorship washes out, familiarity doesn't). Sensible only if A1–A3 underdeliver.

---

## 5. B — Comment economy (problem B)

**Sequencing note:** the 49% comment-share baseline predates 0.4.2. The first B action is
*measuring 0.4.2* (I1 gives the instrument; slices 143+ give the data). B1/B4 are cheap and
compatible either way; B3 waits for the measurement.

### B1. Coder comment policy: verifiable invariants only — **partial → tighten, S**
The register already says comments state invariants the code cannot show, prefer trimming. Add the
missing criterion — *verifiability*: a comment must state a condition that code, a test, or a gate
can witness. Predictions and strength-graded claims ("will/may/should …" about future or external
behavior) are disallowed; delete rather than hedge.
**Evidence:** Huang et al.: models cannot reliably judge unverifiable claims — verdicts on them are
noise; Wu et al. (PROCO): verification works when checking a *specific, checkable condition*, and
degrades to open-ended critique otherwise; Wataoka et al.: hedging-strength preferences are
familiarity-driven style, not substance. Unverifiable comments are the substrate the "will"→"may"
findings grow on; remove the substrate and the findings have nothing to bind to.
**Effect:** comment-category finding rate (I1) drops; less stale prose to relitigate.
**Measure:** I1 category rates before/after; comment density per diff.
**Cost:** S. **What we lose:** narrative context in code (the trade the briefing asks us to name) —
mitigated by B3's docs home; genuinely load-bearing warnings ("must run before X") are invariants
and stay.

### B2. Reviewer comment scope — **in place (0.4.2) → measure, S**
0.4.2 already made comment findings advisory-by-default, one-sentence, never-relitigated. Measure
it before extending. The one extension the evidence supports if churn persists: narrow the blocking
carve-out to *factual contradiction with the code as it stands*, dropping reader-harm judgment
calls — Sifting the Noise found validator judgment worst exactly on policy/judgment classes (50–85%
true-positive suppression) vs mechanically checkable ones (<2.4%), and "would this harm a reader" is
a policy call.
**Measure:** comment-category findings and their blocking share on slices 143+ (I1). **Cost:** S.

### B3. Explanatory prose lives in docs, not comments — **new, M**
Architectural narrative, rationale, and cross-cutting explanation belong in the docs the doc-writer
already maintains diff-based, once per slice; inline comments are limited to B1's invariants.
**Evidence:** grounding — comment churn concentrates where prose is the deliverable and where it
sits inline next to changing code (152: 16 live comments describing a subsystem that no longer
existed); a single diff-scoped doc pass ages prose once per slice instead of re-adjudicating it
every review round. **Effect:** relocates staleness to a surface reviewed once.
**Measure:** comment findings (I1) and doc-phase cost.
**Cost:** M (code-writer, code-reviewer, doc-writer registers + slice-doc-plan docs).
**What we lose:** locality — the explanation is no longer next to the code; a real onboarding cost,
which is why this waits for the 0.4.2 measurement.

### B4. Semantic-equivalence bar for prose findings — **new, S**
A prose/comment finding must show the text is *wrong* (contradicted by code or spec), not that
different words would be better. Wording drift that preserves meaning is not a finding.
**Evidence:** PROCO's exact-match trap: equivalence checking must be semantic or it misclassifies
correct-but-differently-worded answers as wrong — the direct analog of penalizing claim-strength
rewording; Wataoka et al.: the reviewer's preferred phrasing is its own perplexity attractor, so
wording preferences carry no information when producer and reviewer share a base model.
**Cost:** S (one register rule). **Interacts:** subsumed by B2's extension if that lands.

---

## 6. C — Review economics (problem C)

### C1. Anchoring taxonomy for blocking findings — **partial → strengthen, S**
Today Blocker/Major need "failing-input logic or a test sketch". Strengthen to a closed anchor
list, recorded per finding (I1): **(a)** failing test or command, **(b)** concrete repro trace —
named input → wrong output, **(c)** analyzer/gate output, **(d)** requirement-to-code contradiction
with file:line against slice.md/verification.json, **(e)** coverage gap against a named acceptance
criterion. No anchor ⇒ advisory by construction.
This is the briefing's Q5 answered: (a)–(e) is "sufficient anchoring evidence"; the categories that
can *never* anchor — readability, taste, hypothetical performance, unspecified edge cases — are
precisely S7's nitpick/overthink-edge classes and live permanently in advisory/cards.
**Evidence:** S7's false-rejection taxonomy: 48.2% of wrong rejections are unfalsifiable "logic
error" claims, 14.1% hallucinated requirements, 13.2% asserted boundary errors — 87% of the false
positives would fail this bar; PROCO: condition-anchored verification cut wrongly-overturning-
correct-answers from 9.1% to 2.5% while keeping true-error fixes.
**Effect:** blocking precision (I3) up; fix rounds triggered only by demonstrable failures.
**Measure:** I1 anchor-type distribution; I3 precision.
**Cost:** S (reviewer register + verdict schema).
**Risks:** real-but-hard-to-demonstrate defects (races, rare-input corruption) get demoted — anchor
(b) deliberately accepts a *reasoned* trace naming input and wrong outcome, which the fix round
then has to witness (C2); detection is not suppressed — unanchored observations are still recorded,
as advisory.

### C2. Demonstrate-failure-first fix protocol — **new, M**
A fix round for a blocking finding begins by *witnessing the failure*: write the failing test or
run the claimed repro. If the executor cannot make it fail, the finding is **refuted** — flipped to
advisory/card with the refutation evidence attached, no code change, no relitigation.
**Evidence:** S7's Fix-guided Verification Filter — treating the reviewer's claim as an executable
counterfactual cut false rejection by 30–67 points across five models at ≤2.5 points added false
acceptance; Huang et al.: external feedback (test execution) is the *only* setting where
correction reliably works; Sharma et al.: without an evidence gate the coder capitulates to
confident challenge (models wrongly admit mistakes on 42–98% of correct answers) — this converts
producer-reviewer disagreement from a sycophancy contest into an executable dispute.
**Effect:** the highest-confidence C intervention; also produces regression tests as a by-product.
**Measure:** refuted-finding rate; rework share (I2); blocking precision (I3) before/after.
**Cost:** M (fix-round dispatch protocol + a refuted-verdict path in `run_loop.py`).
**Risks:** test-writing cost per blocking finding (bounded — blocking findings are already the
minority post-0.4.2); a shallow test can "witness" the wrong behavior — existing suites and gates
bound the damage; some anchors (d/e: spec contradictions, coverage gaps) are checked by
inspection+citation rather than execution, and keep their current handling.

### C3. Round caps, rising bar, one-report lifecycle — **in place → keep, none**
The 0.4.x design already caps rounds, raises the funding bar per round, and forbids relitigation.
The reading endorses all three: self-bias grows monotonically with refinement iterations while true
quality plateaus (Xu et al.: perceived quality rises for 10 iterations, human-rated quality flat);
intrinsic re-critique degrades outcomes with more rounds (Huang et al.); bias also grows with
candidate-pool size k (Xu et al. §4.3), which cautions any future best-of-k too. Recorded so the
caps aren't loosened in a future "more review = better" mood.

### C4. Evidence-gated contest channel for the coder — **new, S–M**
The executor may return "contested + evidence" instead of a fix; contested findings go to the
existing bare consult with the evidence attached; the ruling is final.
**Evidence:** Sharma et al. (capitulation, above); Huang et al. (challenged models flip correct
answers). **Overlap:** C2 is the stronger mechanism where the claim is executable — C4 covers the
inspection-anchored remainder (spec readings, coverage disputes).
**Cost:** S–M (executor verdict schema + consult routing). **Risks:** symmetric stubbornness —
contests without evidence are not accepted.

### C5. Agentic false-positive validator before fix rounds — **new, M–L, conditional**
A bare, evidence-seeking session with *repo read access* validates each blocking finding before an
executor round is spent.
**Evidence:** Sifting the Noise — an agentic validator on a strong backbone cut residual FP rate
98.3%→6.3%, while *static prompting with oracle-perfect context did nothing* (F1 51.6% = vanilla):
the agency, not the context dump, carries the effect; cross-file access is load-bearing (recall
95.5%→45.5% without); LLM4FPM: precise + complete context each independently improve triage; but
judgment/policy finding classes suffered 50–85% true-positive suppression — so the validator gates
only mechanically-checkable classes (C1 anchors a–c), never taste.
**Effect:** large where blocking precision is low. **Measure:** I3 precision, validator overturn
rate, net cost per avoided fix round.
**Cost:** M–L plus per-finding spend.
**Position:** only if I3 shows precision still low *after* C1+C2 — C2 already buys most of this
via the executor, without a new role.

### C6. Advisory-card lifecycle governance — **new, S**
Cards get an explicit lifecycle: batch triage at `slice-dag` time, auto-expiry for cards skipped by
two consecutive triages.
**Evidence:** the practitioner literature's actual lesson — trust collapse comes from unmanaged
finding queues; grounding: the cross-slice path (cards, deferrals) is where any unbounded version
of C must live, and it's unmeasured (I4). **Cost:** S (process, `triage`/`slice-dag` docs).
**Risks:** auto-expiry drops a real issue — mitigated by the two-triage rule and the card's
provenance link back to its slice.

### C7. Close-out report replaces per-finding cards — **new, M** (added 2026-08-15)
One document per slice, `close-out.md`, created at plan start and written by every agent as it
goes, in one fixed shape (Summary · Outstanding actions · Notable events · Bugs · Open questions
and rulings · Suggestions; one entry shape; a `Disposition:` line per entry for the operator).
Everything out of the loops' own scope goes there — nothing from a run is carded per finding;
the run's only tracker output is one card pointing at the report; the operator dispositions
entries in place and an interactive session executes them; triage reads what remains. Design,
evidence and decisions: [close-out-report.md](close-out-report.md); build:
[close-out-plan.md](close-out-plan.md).
**Evidence:** Ansible slice 007 — ten cards from one run, decided in five places blind to each
other, one already fixed in-run when filed (the consult's absorb never fed back), the operator
runbook not standing alone; KubeCoderSpecs 117/135/107 → 24/17/16 card entries. Mechanism: Fan
et al. (detection without a licensed act → re-visiting) and ProCo (a specific fill-in slot
converges where open-ended critique regresses) — the fixed shape removes the *completion*
decision, the single destination removes the *routing* decision; TALE (limits structural, never
numeric); §8's "detection is never suppressed" taken to its end.
**Effect:** cards per run 10 → 1 by construction; the hypotheses are fewer gen-1 appended phases
and lower rework share (agents stop resolving "what do I do with this?" by doing it), and a report
the operator processes in one sitting. **Measure:** entries and dispositions per report, cards
filed at disposition, `appended_phases`, I2 rework share, bail-outs surfacing as Notable events.
**Cost:** M (tool + template + contract doc, every register one line, both loops, two skills, one
new skill). **Risks:** over-production into a document nobody reads — answered by Focus lines and
ids, never by caps; the report becoming a scope-bleed source — phase agents append only, the
completion consult alone reconciles. **Overlap:** subsumes C6's governance question by moving the
queue off the board; I4's ledger reframes as per-report counts; the 0.4.4 triage filter keeps its
role for deferred entries.

### C8. Mutation-witnessed signoff for test-only phases — **new, S** (added 2026-08-15)
One sentence in the reviewer register, scoped to phases whose diff is test-only: a signoff names
one mutation that takes the phase's new test red; a test-only phase whose reviewer cannot has
been read, not reviewed. Nothing for mixed phases.
**Evidence:** slice 146 P1 F1 — the reserved-`-e` test pinned the echoed token, not the refusal
reason, a self-satisfying assertion — was found by mutation in P1's review, recorded advisory
`anchor: none` / `category: other`, and cost $4.02 (P4 + the consult it forced, 8.7 % of the
slice) to fix a generation later; witnessed in P1 it is a fix round in P1. 145 P4 F1 (deleting the
growth guard leaves the suite green) is the same shape. Reviews already do this unprompted most of
the time (I5's proxy: 10/12 on 144–146), so the rule mostly binds the remainder.
**Effect:** the one finding class that is mechanically checkable stops arriving as evidence-free
advisory. **Measure:** I3 finding precision on test-only phases before/after; their fix-round
rate. **Cost:** S. **Risks:** D2 — register elaboration shifts the decision boundary (S7: FNR
26 %→73 % Direct→Full); one sentence, test-only scope, A/B-checked, never a general "verify by
mutation". **Depends on:** the 0.5.1 clarification of C1's `coverage-gap` anchor (a mutation the
criterion's test survives is a coverage gap) — that clause makes the class anchorable, this entry
would make checking it mandatory where it is cheapest.

---

## 7. D — Judge design and bias controls (briefing Q6)

### D1. Same-model separation is weaker than it looks — **insight, informs B/C**
Register/session/prompt separation does not neutralize stylistic bias: preference tracks perplexity
*to the judge*, essentially unchanged whether the judge authored the text (Wataoka et al.). An Opus
reviewer of Opus code shares the coder's phrasing attractor — one more reason wording findings are
structurally low-information (B4). The counterweight: judging resists sway with model strength
(Sharma: strongest model most resistant; Xu: larger models amplify less self-bias), so the answer
is **not** a weaker-but-different reviewer — it's keeping the strongest model and grounding its
verdicts in external evidence (C1/C2). A genuinely different frontier-strength model as
consult/validator would be the clean fix if one is ever available in-loop.

### D2. Reviewer prompt and context hygiene — **partial, S**
Two rules the evidence supports: **(i)** the reviewer/consult sees the artifact and the acceptance
criteria, not the coder's narration or the plan's persuasion — persuasiveness drives preference
independent of truth (Sharma: the preference model preferred convincingly-argued wrong answers 95%
of the time over plainly-stated right ones); bare consults already do this — audit that review
dispatches do too. **(ii)** Keep the reviewer register *lean*: S7's central result is that more
elaborate review instructions shifted the decision boundary toward rejection (GPT-4o FNR 26%→73%
Direct→Full) — every future addition to `code-reviewer.md` should be A/B-checked against finding
precision (I3), not assumed to help. Inverse scaling adds the same lesson for context volume:
Claude models degrade with irrelevant material in scope.
**Cost:** S (audit + a documented rule for future register edits).

### D3. Comparative-judgment toolkit — **reference, for any future selection step**
The loop currently issues absolute verdicts; comparative judgment applies only if a
candidate-selection step is added (A5, best-of-k fixes). If one is: order randomization + swap
consistency test (single-order judgments are unreliable: 25–89% order-flip rates), majority vote
among ≥3 strong judges for near-ties (>95% instance reliability), length normalization or explicit
anti-verbosity instruction, provenance hiding (self-preference reverses with swapped authorship
labels). Prefer independent samples + vote over multi-agent "debate" — debate underperforms plain
self-consistency at equal call count (Huang et al.).

---

## 8. Conflicts and constraints

- **C2/C5 spend to save.** Positive EV only while blocking precision is low; I3 defines the sunset
  criterion (precision ≥80–90% sustained ⇒ scale the machinery back).
- **A3 needs A1.** Effort step-down is only safe trial-gated on declared-small shapes; cheap-plan
  failures otherwise surface downstream where they're expensive.
- **Detection is never suppressed.** Every B/C entry routes or evidence-gates findings
  (advisory, cards, refutation-with-evidence); none tells the reviewer not to look. C1 demotes by
  anchor, not by silence. This satisfies the briefing's hard constraint.
- **Generic-loop constraint holds throughout.** All entries are register/loop-level and
  task-independent; A1's declaration is derived per-slice by the loop itself from slice.md — no
  per-task manual tuning.
- **Effort and caching:** effort stays fixed within a session; tiering happens only at dispatch
  boundaries (each agent is a fresh `kc session`, so this is free).
- **D2 cuts against prompt growth.** Several entries add register rules (B1, B4, C1); each is a
  few lines, but S7 warns that reviewer-prompt elaboration itself shifts bias — batch these edits
  and A/B them via I3 rather than accreting continuously.

---

## 9. Proposed ranking (proposal — decided jointly, nothing actioned)

Ranked by expected value per unit implementation effort (briefing Q7). "Effect" cites the closest
measured analog, not a promise.

| # | Entry | Why here | Cost |
|---|-------|----------|------|
| 1 | **I1+I2** telemetry + cost readout | Prerequisite for everything; measures 0.4.2 for free; trivially cheap | S |
| 2 | **C1** anchoring taxonomy | 87% of S7's false rejections fail this bar; mostly a strengthening of an existing rule | S |
| 3 | **C2** demonstrate-failure-first | Largest measured analog (FNR −30..−67pts); converts sycophancy into executable dispute | M |
| 4 | **A1** task-shape declaration | Grounded by 153's $27.72; the output-contract lever the briefing asks about | M |
| 5 | **A2** question-gated research | Cheap complement to A1 | S |
| 6 | **B1+B4** verifiable comments + semantic bar | Cheap; removes the will→may substrate; sequenced after 0.4.2 measurement | S |
| 7 | **A3** effort step-down trial | Cheap knob, honest uncertainty; needs A1 + A/B discipline | S–M |
| 8 | **C6+I4** card lifecycle + ledger | Answers where unbounded-C actually lives | S |
| 9 | **C4** contest channel | Partially subsumed by C2 | S–M |
| 10 | **D2** reviewer hygiene audit | Small, protective; makes future register edits disciplined | S |
| 11 | **C5** agentic validator | Strong evidence but conditional on C1+C2 underdelivering | M–L |
| 12 | **B3** prose-to-docs | Real trade-off; wait for 0.4.2 data | M |
| 13 | **A5** best-of-k plans | Bounded ceiling, doubles plan latency; last resort for A | M–L |

**Proposed starters (3):**
1. **I1+I2** — instrument first; without it none of the effects below are observable, and it
   settles whether 0.4.2 already solved B.
2. **C1+C2** — the anchoring taxonomy plus demonstrate-failure-first, as one coherent change to
   the review/fix contract. Success: blocking precision ≥80% (I3), rework share stable or down.
3. **A1 (+A2)** — the task-shape declaration with question-gated research. Success: planner+research
   share on pre-settled/small shapes drops toward the floor; no rise in downstream gate_red or
   appended phases.

---

## 10. Status (2026-08-14) — where the selection discussion landed

Recorded so a fresh session can continue without this conversation's transcript. **Per-entry
state now lives in [status.md](status.md)** — later the same day the operator actioned
I1+I2+C1+C2+A1+A2, shipped as plugin 0.4.3; the phase split and constraints below remain the
implementation map.

**Phase split of the starters** (what committing to each actually touches):

- **A1+A2** — plan loop only (`plan-template.md`, plan-writer, plan-reviewer registers).
- **I1** — run loop (code-reviewer verdict schema + `state.json`); if C1 is taken, I1's per-finding
  anchor/category fields are the same schema change — they land together nearly free.
- **C1+C2** — run loop (code-reviewer register + fix-round protocol in `run_loop.py`).
- **I2** — close-out tooling (`slice_cost.py` ratios); behavior-neutral, phase-independent,
  no commitment implied.

**Operator direction so far:** a planning session is imminent, so plan-phase changes (**A1+A2**)
can be implemented now and exercised by it; run-phase changes get tested on a new slice. The
run-batch decision resolved to **I1+C1+C2** when the operator actioned the batch (status.md holds
the per-entry log). I2 is uncontroversial.

**Practical constraints for whoever implements:**

- The loops execute the installed marketplace clone (`~/.claude/plugins/marketplaces/aiworkflow/`),
  so changes reach planning/run sessions only after push + marketplace update. The operator
  confirms every push.
- Plugin changes bump `plugins/dev/.claude-plugin/plugin.json` and get a `CHANGELOG-workflow.md`
  entry; commit subjects carry the version (repo `CLAUDE.md`).
- Measurement baseline: KubeCoderSpecs slices ≤153 are pre-0.4.2 (comment findings ≈49% there);
  slice 143 is the first run on 0.4.2 — 0.4.2's effect on problem B is read off slices 143+
  against that baseline, via I1 once it exists.

---

## 11. W — Workflow frictions (added 2026-08-22, from the 155–170 read)

Not from the papers: from the run record. Each is a friction the loop's own artefacts showed on
slice 170 (assessment in `tmp/slice-170-assessment.md`) and, where noted, earlier slices — small,
mechanical, and outside the review-economics lanes above. Same entry fields; per-entry state in
[status.md](status.md). None is built.

### W1. Headless waiting — **new, S**
A dispatched agent waits on external work in the foreground (`track_build.py` with a Bash timeout
that outlasts a Jenkins build; the default 2 minutes is what killed 170's first attempt), never by
backgrounding it and stopping; and the driver narrates "session idle, N background tasks pending"
instead of `[result] Done`. The wait-by-notification rule lives in the in-pod preamble (KubeCoder
repo, since 0.7.4) and is right for the operator's session — in a headless `kc session` the turn
end is all the driver sees.
**Evidence:** 170 test-phase r1 (`log.txt` L2133–2155): foreground waiter timed out, backgrounded,
agent stopped to wait, was re-woken by the notification, stopped again; `Done` printed twice while
waiting; the loop was restarted 3m45 later (cause unknown) and r1's ≈ $8.27 / 23 min left no
history row, no price, no report entry. Resume worked and the durable work survived — the system
coped; the defect is the invisibility (W4) and the ambiguity.
**Effect:** a waiting session is distinguishable from a finished one; no silent rounds.
**Measure:** rounds without a verdict row; `Done`-while-waiting lines. **Cost:** S (one preamble
line in KubeCoder, guarded by `TestWaitingOnWork`; one `test-agent.md` line; driver narration).
**Risks:** none of substance — the plugin's half is narration.

### W2. `close_out.py` accepts the report path — **new, S**
`dispatch_line()` names the report file; every subcommand takes the slice directory. Resolve a
`.md` argument to its parent, or name the directory in the dispatch line.
**Evidence:** 170 — every session's first `list` failed, read `--help`, retried: 20 sessions ×
3 turns ≈ 50–57 turns per run (the assessor tripped on it too).
**Effect:** minutes and a few dollars per run; one trap fewer. **Measure:** usage-help turns → 0.
**Cost:** S (one `Path` resolve + a test). **Risks:** none.

### W3. The consult fixes the report's residue entries under the rider — **new, S**
The generation rider already says mechanical residue — comment or formatting fixes with no
behaviour change, in files the diff touched — is fixed by the finder, never reported. Reviewers
cannot commit, so their comment-nit advisories land in the report as Bugs; the completion consult
is the one pass with the tree and the rider but reads "residue" as its own scan of the diff. One
sentence in `COMPLETION_CONSULT_SITUATION`: walk the live nit entries; fix what the rider covers,
commit, strike with the commit.
**Evidence:** 170 — seven operator fix-nows (B2, B3, B5, B11, B12, B19, B22), all enumeration
nits in touched files; the report's own Focus line said "one disposition could cover the set";
the consult reported "no mechanical residue — no TODO/debug leftovers, gofmt clean". 154's
consult fixed ten such entries in one commit; 163–168's struck none; other slices show 0–3
operator fix-nows. Mechanism as C7: the rider licenses the act, the entry list names the targets.
**Effect:** fix-now dispositions → 0–1 per report. **Measure:** fix-now count per report; consult
strikes. **Cost:** S. **Risks:** the consult fixing beyond the bound — unchanged (no behaviour
change, touched files), and the sweep re-runs on its commit.

### W4. Bail-outs and vanished rounds become Notable events by construction — **new, S**
The driver appends refuted findings and funding-consult merges to Notable events itself but not
bail-outs; they reach only the header, stamped after the doc phase, and the doc-writer writes the
Summary and Focus lines from the file. Append one N entry at bail time (reason, phase, the dirty
paths) and one when a dispatched session ends without a verdict, before the nudge.
**Evidence:** 161 and 170 both say "no bail-out" in the Summary/Focus under a non-zero header;
170's bail #1 blamed "an agent" for slice 168's dirty `close-out.md` in the shared specs worktree
(bail #2 named the path); 170's lost test round is nowhere in the record. C7's H4 (workflow
defects surface in the report) then holds mechanically.
**Effect:** the report cannot contradict its header; lost rounds exist. **Measure:** header bail
count = N entries about bail-outs. **Cost:** S (one `append` in the bail path, one at the
missing-verdict branch). **Risks:** an entry for a protocol bail that resumes in a minute — one
line, struck by the consult when resolved, is the shape the report already has.

### W5. Cross-slice trend readout — **new, S, optional**
`slice_cost.py --trend <completed-dir>` (or a sibling): per slice, cost and the three shares,
phases, rounds, r1 `issues`, findings by impact / category / anchor, refuted, bail-outs, appended
phases, test rounds, doc stage, `close_out.py counts`. Measurement only; depends on I1, I2.
**Evidence:** the 2026-08-22 sixteen-slice table was a one-off script over the fields I1/I2
created — the fields exist, the read does not. **Effect:** the next read is one command.
**Cost:** S. **Risks:** none.

---

## 12. Status (2026-08-22) — where the 155–170 read left it

Sixteen slices (KubeCoderSpecs 155–170), all read from the I1/I2 fields: r1 `issues` 17 %
(12/71) against 24 % baseline; 15 blocking findings, 0 refuted; comment-prose 38 % of findings,
all advisory, $0 rework since 0.4.2; rework 2–19 % (median ≈ 7 %); planner $14–27; 0 appended
phases. Slice 170 (12 phases, ≈ 5.6k lines, ≈ $221, rework 2.9 %, 1 blocking in 13 reviews,
0/9 blocking on > 230-line phases against a 65 % baseline, prd-confirmed by the operator) is the
reference run.

**Problems A, B and C as briefed each have a measured answer** (planner floor holds and shapes
declare honestly; prose churn costs nothing; within-run amplification is bounded and precise),
and no remaining I/A/B/C/D entry has a live precondition — [status.md](status.md) records the
closures (I1, I2, I3, A1, A2, B1, B2, B4, C1, C2, D2 accepted; A5, B3, C4, C5, C8, I5 rejected;
I4, C6, D3 moot). What outlives the briefing: the standing measurement (keep reading slices; W5
makes it one command), the W lane above, and one lesson without an entry here — per-turn context
volume sets 80 %+ of every Opus role's cost (170: 82 %; the doc-writer at 290k tokens/turn and
8–21 % of every slice is where it bites) — which is a different research question and, if taken
up, deserves its own briefing rather than a chapter in this one.
