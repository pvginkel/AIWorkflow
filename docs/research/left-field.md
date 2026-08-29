# Left-field ideas — practices from outside the agent literature worth a research pass

Written 2026-08-29. Companion to [interventions.md](interventions.md) / [interventions-2.md](interventions-2.md)
(the catalogues) and [status.md](status.md) (where each entry stands). **A menu, not a plan** —
nothing here is scheduled.

**Why this document exists.** The risk-based-review question (#715) came from a Martin Fowler post,
not from the reading list — and it was worth the research even though the answer was no. Every
other source under [articles/](articles/) was picked to answer a problem we had already named
(context cost, turns, compression). This is the other direction: established practices from
software engineering, manufacturing and decision research that nobody chose because they don't
name a problem we have — and might apply anyway, because the pipeline is a review-and-inspection
process with a queue, and those have been studied for fifty years.

**Selection rule.** An idea is in if it (a) comes from outside the LLM-agent literature, (b) maps
onto a specific role or seam of the pipeline, and (c) can be decided by a measurement we can
actually take — ideally on the corpus we already have. Ideas that would double a role's spend are
out (dollars are the target; [turns-plan.md](turns-plan.md)).

**How to read an entry.** *Background* (the practice, with a source), *Here* (where it lands in
the pipeline), *Worth it because*, *Decides it* (the observation that accepts or rejects it —
same field as status.md), *Cost* (S/M/L, the research effort, not the runtime).

---

## 1. Seeded defects — measure what the reviewer misses

**Background.** Harlan Mills' *error seeding* ("bebugging", IBM, early 1970s): plant known defects
in an artefact before inspection; the fraction of planted defects the inspection catches estimates
the fraction of *unknown* defects it misses. *Capture–recapture* does the same without planting —
two independent inspectors, and the overlap of their finding sets estimates the total defect
count (Lincoln–Petersen); evaluated for software inspections by Briand, El Emam, Freimut &
Laitenberger ([ISSRE 1997, TSE 2000](https://www.researchgate.net/publication/3188084_A_Comprehensive_Evaluation_of_Capture-Recapture_Models_for_Estimating_Software_Defect_Content))
and surveyed after a decade by [Petersson, Thelin, Runeson & Wohlin (JSS 2004)](https://wohlin.eu/jss04-1.pdf).
Background on the seeding idea: [Wikipedia — Bebugging](https://en.wikipedia.org/wiki/Bebugging).

**Here.** Everything we know about the code-reviewer is what it *reports*: r1 issues 12/71,
blocking 15, refuted 0, comment-prose 43/114 (I1 readout). Nothing tells us what it *misses*, and
interventions-2 §0 says it plainly — "the quality side of every trade is unmeasured today". The
experiment: take N shipped phase diffs from the corpus, plant k defects each from a small taxonomy
(off-by-one, dropped error path, stale claim in a doc, a contract deviation, a test that asserts
nothing), dispatch the code-reviewer on the doctored branch *outside the loop*, score catch rate by
defect type. The same harness dispatched 3× on one unaltered diff gives test–retest reliability —
how much of a verdict is noise. Sonnet can plant; Opus reviews as in production.

**Worth it because** it is the yardstick every reviewer-side idea needs (§4, §5 below are
unmeasurable without it), it is offline (no slice at risk, no plugin change), and a recall number
by defect type is the first quality measurement the programme would have that isn't "what the
reviewer said".

**Decides it.** Self-proving: it ships when the harness produces a catch-rate table. The number
then decides the others — a reviewer at 90 % recall has little for §4/§5 to move; at 50 % they
matter.

**Cost.** M — a harness script (research tooling, non-stdlib fine) plus one reviewer dispatch per
doctored diff.

## 2. Mutation testing — measure what the test phase's tests can catch

**Background.** Mutation testing inserts small faults (mutants) into the code and counts how many
the suite kills; a green suite that kills few mutants is a suite that checks little. Google runs it
diff-based on every code review at ~2 GLOC — [Petrović & Ivanković, ICSE-SEIP 2018](https://research.google.com/pubs/archive/46584.pdf),
[Practical Mutation Testing at Scale (2021)](https://arxiv.org/abs/2102.11378) — and reports that
developers shown surviving mutants write tests that kill more of them afterwards. Tools: `mutmut`
/ `cosmic-ray` (Python), PIT (JVM), Stryker (JS/.NET).

**Here.** The test phase runs on Sonnet and its gate is *green* — the pipeline's second principle
("detecting a green suite needs no model") is right, but green measures nothing about the tests'
power. A mutation score on the slice's changed lines is a deterministic quality number for the
test phase, and a candidate *gate*: surviving mutants on the diff are a finding the test-agent gets
mechanically, with no reviewer in the loop. Portability: mutation tooling is a project's curated
target in `project.yaml`, never the plugin's.

**Worth it because** it turns "did the test phase add anything" from a judgment into a number,
and it gives the test-agent a concrete target instead of a strategy doc to interpret.

**Decides it.** Run it once over the corpus slices' diffs (offline, no plugin change). If the
score on changed lines is uniformly high, nothing to gain, rejected. If surviving mutants cluster
in some phases or projects, the gate is worth a before/after on test-round count and on the
reviewer's functional findings.

**Cost.** M — per-language tooling on the project side, one readout script.

## 3. The review-size ceiling — is there a knee in phase size?

**Background.** The SmartBear/Cisco study ([Cohen 2006](https://static0.smartbear.co/support/media/resources/cc/book/code-review-cisco-case-study.pdf);
[summary](https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/)):
defects found per line fall sharply past 200–400 LOC per review and past ~60 minutes;
Google's [small-CLs guidance](https://google.github.io/eng-practices/review/developer/small-cls.html)
codifies the same; Reinertsen's *Principles of Product Development Flow* (2009) gives the
economics — rework and cycle time grow non-linearly with batch size.

**Here.** The plan-reviewer checks "phase sizing" as a judgment with no number behind it. We hold
the data to find one: 30+ slices with per-phase diff size (git), findings and blocking per phase
(I1), fix rounds, turns and $ per phase (`slice_cost.py`). Two scatters answer it: findings per
kLOC and blocking rate against phase diff size (does the *reviewer* have a ceiling like a human's?),
and writer turns against diff size (does the *writer* — the 7 % of sessions ≥ 80 turns that are
25 % of spend — go super-linear past some size?).

**Worth it because** it is a readout on existing data, and a knee would give the plan-writer a
numeric phase cap and the loop a split rule — the cheapest lever on the long-session tail that
interventions-2 identified.

**Decides it.** A knee in either curve. A flat line means the human ceiling doesn't transfer and
the entry closes at the cost of one script.

**Cost.** S.

## 4. Reading order — what the reviewer sees first

**Background.** [Baum, Schneider & Bacchelli, ICSME 2017](https://doi.org/10.1109/ICSME.2017.28)
(*On the Optimal Order of Reading Source Code Changes for Review*): reviewers given changes
ordered by relatedness, rather than alphabetically by file, review better; the
[2019 follow-up](https://link.springer.com/article/10.1007/s10664-018-9676-8) ties the effect to
working-memory load, and [*First come first served* (FSE 2022)](https://dl.acm.org/doi/abs/10.1145/3540250.3549177)
shows the files shown first get disproportionate attention. LLMs have a documented positional bias
of their own, so the transfer is at least plausible.

**Here.** The code-reviewer gets `git diff` in git's alphabetical file order: tests may precede
the code they test, the contract doc may follow the implementation it governs. Ordering the diff
in the dispatch is a small function — contract/doc first, then the entry point, then callees, tests
last (or first: that's the experiment) — and costs no tokens.

**Worth it because** it is free at runtime and the human evidence is unusually direct for a code
review practice.

**Decides it.** Catch-rate delta on the §1 harness, same doctored diffs, two orderings.
Unmeasurable without §1.

**Cost.** S given §1.

## 5. Perspective-based reading — one reviewer, an assigned lens

**Background.** [Basili et al., *Empirical Software Engineering* 1996](https://link.springer.com/article/10.1007/BF00368702)
(NASA SEL): reviewers each reading from an assigned perspective — tester, designer, user — covered
more defects as a team than the same reviewers reading ad hoc or by checklist. Replicated several
times since; the individual effect is mixed, the coverage effect holds.

**Here.** The team form (N reviewers per phase) is ruled out by cost. The cheap form: one reviewer,
and the dispatch names *the* perspective for this phase, derived from what the phase is — a
migration phase reads as "the operator running this against prd", an API phase as "the caller",
a doc phase as "a reader who has never seen the code". The T4 phase digest is where the lens
would ride.

**Worth it because** the current finding mix (comment-prose 43/114) suggests a reviewer with no
assigned stance defaults to what is easiest to see; a stance is a prompt-side change with no
context cost.

**Decides it.** On the §1 harness: does the catch rate by defect *type* shift toward the lens
without dropping elsewhere; in production, does the functional share of findings rise at equal
$/phase.

**Cost.** S given §1.

## 6. Pre-mortem — the plan-reviewer assumes the slice has already failed

**Background.** [Klein, HBR 2007](https://hbr.org/2007/09/performing-a-project-premortem):
before starting, the team assumes the project has failed and writes down why. Grounded in
Mitchell, Russo & Pennington (1989), whose *prospective hindsight* experiments found that framing
an outcome as already having happened raised the number of correctly identified reasons by ~30 %.

**Here.** The plan-reviewer is structural — AC completeness, `Target:` correctness, sizing,
attachment altitude. The plan's actual failure modes are recorded elsewhere: bail-outs (exit 3),
operator questions (exit 4), appended phases and abandoned phases in `state.json`. A pre-mortem
clause is a prompt change: "this slice bailed at a phase / asked the operator a question / had a
phase appended — write the single most likely reason, and if it is fixable in the plan, fix it".

**Worth it because** the cost is one paragraph in an agent definition and the outcome measures
are already collected per slice.

**Decides it.** Bail-outs, exit-4s and appended phases per slice before/after, on the existing
fields; plan-loop $ before/after (the reviewer's session must not grow much). Caveat: intrinsic
self-critique is weak in LLMs ([Huang et al. 2023](https://arxiv.org/abs/2310.01798)) — this
works only if the failure is inferable from the plan, which is exactly what the readout tests.

**Cost.** S.

## 7. Docs first — draft the manual in the plan loop, reconcile it in the doc phase

**Background.** [Readme Driven Development (Preston-Werner 2010)](https://tom.preston-werner.com/2010/08/23/readme-driven-development.html)
and Amazon's *Working Backwards* PR/FAQ: write the user-facing artefact before the code, and let
the code exist to make it true. "A perfect implementation of the wrong specification is
worthless."

**Here.** The doc-writer is the most expensive role (13 % of spend) because it reads the whole
shipped slice, diff-based, at the end; #716 phase 1 attacks *how* it reads. The left-field
alternative changes *when*: the plan loop — which already holds slice.md, the spec and the code
context — drafts the manual and dev-doc delta as part of the plan, and the doc phase becomes a
reconcile of that draft against the diff: a bounded task with a much smaller read. The draft is
also a specification check for free — a plan whose doc can't be written is underspecified (the §6
signal by another route).

**Worth it because** it targets the single largest role by spend with a change the phase-1
rework doesn't cover, and the doc phase has the highest blocking rate in the corpus (the #715
readout) — a draft written from the spec may block less than one written from the diff.

**Decides it.** Doc-phase $ and turns before/after, net of the plan loop's increase; doc-phase
blocking rate. Risk to watch: drift when phases deviate from the plan — measure how often the
reconcile rewrites the draft outright.

**Cost.** M — plan-writer, plan-template and doc-writer contract all move.

## 8. Process behaviour charts — judging a plugin version on four slices

**Background.** Shewhart/Deming statistical process control; [Wheeler, *Understanding Variation*
(1993)](https://www.spcpress.com/pdf/DJW317.Jul.17.History%20of%20XmR%20Chart.pdf) brought the
XmR chart to managerial data: plot the series, compute natural process limits from the moving
ranges, and only a point outside the limits or a run of eight on one side is a signal — everything
else is routine variation you should not act on.
[Introduction](https://commoncog.com/process-behaviour-charts-more-than-you-need/).

**Here.** Every version judgment so far is a before/after on a handful of slices — T3/T4 read
"−40 % pooled, −8 % median, preliminary"; A3 shipped on one read and was withdrawn. The per-slice
series we already produce ($/phase per role, turns/session, findings/phase, r1 blocking) are what
XmR was built for. The method: a running chart per metric across plugin versions, and a version
is accepted when the chart shifts, not when the next four slices look lower.

**Worth it because** the programme's decisions are the expensive part — a withdrawn version costs
more than a script — and the corpus is noisy enough (median vs pooled disagree by 32 points) that
the eye is not a reliable judge.

**Decides it.** It is a decision *method*, so the test is whether it resolves a pending call: does
the T3/T4 "preliminary" verdict come out clean on the chart once the next slices land.

**Cost.** S — a script over `slice_cost.py` / `t4_readout.py` output; pandas is fine here.

## 9. Poka-yoke — retire recurring finding categories into gates

**Background.** Shingo's mistake-proofing (*Zero Quality Control*, 1986): design the step so the
error cannot occur, or is caught at source by a device, rather than by an inspector downstream.
Its analysis side is [Orthogonal Defect Classification (Chillarege et al., TSE 1992)](https://www.chillarege.com/articles/odc-concept.html):
classify each defect by *type* and by the *trigger* that found it; the signature says which
upstream stage leaks what.

**Here.** The pipeline already believes this ("scripts drive, agents judge"; gates in Python). The
systematic form is a readout the I1 telemetry can feed: 16 slices of findings by category, of
which comment-prose was 43/114 — the ruling made them non-blocking, which stops the litigation but
still spends a reviewer turn finding them. The poka-yoke question is, for each recurring finding
type, whether a deterministic check (a lint rule, a done-record shape check, a stale-doc-claim
grep) removes it from the reviewer's plate so that review and fix rounds only ever carry judgment
calls. Adding ODC's *trigger* to the I1 fields — found by reading the diff, by running the code,
by reading the contract — says which gate.

**Worth it because** each retired category is a permanent turn saving with no quality trade, and
the readout is one pass over `state.json` history.

**Decides it.** Share of historical findings a gate would have caught, per category; then each
gate is its own before/after on r1 finding count.

**Cost.** S for the readout, S–M per gate after.

---

## Considered and set aside

- **Ship / Show / Ask** ([Wilsenach, martinfowler.com 2021](https://martinfowler.com/articles/ship-show-ask.html))
  — the same skip-review family as #715; the #715 readout applies.
- **N-version / best-of-N writers** — two independent implementations, pick or diff. Doubles the
  writer's spend; out by the selection rule.
- **Author self-review before the verdict** — a real practice (Google's eng practices), but the
  intrinsic self-correction evidence for LLMs is negative ([Huang et al. 2023](https://arxiv.org/abs/2310.01798));
  only worth a look behind §1, which could measure it.
- **Property-based testing** (QuickCheck / Hypothesis) — a project's testing strategy, not the
  pipeline's; belongs in a project's `slice-testing-strategy` doc if anywhere.
- **Cleanroom** (Mills: developers never run the code, verification by review and statistical
  usage testing) — the opposite bet to our gates, and the gates are right for us.

## Suggested order

§1 first — it is the yardstick for §4 and §5 and the first quality number the programme would own.
§3, §8 and §9 are readouts on data already collected and can run any time. §2, §6 and §7 are
pipeline changes and go one at a time, as the turns-plan entries did.
