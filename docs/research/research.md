# Research Briefing: Overthinking and Review Economics in a Multi-Agent Development Loop

## Purpose

You are asked to investigate three observed problems in our agentic development workflow, grounded in the research listed below. Download and read the primary sources yourself — do not rely on the one-line relevance notes in this document, which exist only to orient you. Form your own conclusions; you may disagree with the framing given here.

Your output is a proposal, not an implementation. See _Deliverable_ at the end. Nothing gets actioned before we decide together.

## Workflow context

- Loop: planner → coder → reviewers (plan review and code review), one register per role, generic loop driving all tasks. Models: Claude Opus 5 primarily.
- Constraint: the loop stays generic. Per-task manual tuning is not acceptable.
- Constraint: reviewers raising issues is considered good conduct. Detection must not be suppressed; how findings are routed and gated is open for design.

## Observed problems

**A. Planner always deep-dives.** Regardless of task size, the planner performs an extensive investigation. An earlier attempt to grade tasks by complexity upfront and route them to different models/effort levels produced poor results.

**B. Comment churn.** The coder writes many code comments. These go stale as code evolves. Reviewers in later runs generate findings against them — down to weakening claim strength ("will" → "may"). Fixing these findings consumes significant time and money while changing little of functional value.

**C. Work amplification.** More work comes out of the loop than goes in. Reviewer findings are individually fair and defensible on inspection, yet the aggregate volume of raised-then-fixed work grows without bound.

## Subjects and reading list

All arXiv abstract pages link to PDF and HTML versions. Read at minimum the papers marked ★; skim the rest for relevance.

### S1 — Overthinking in agentic settings (the reasoning–action dilemma)

Relevance: taxonomy of failure patterns (analysis paralysis, rogue actions, premature disengagement) and a quantified selection result. Map these patterns to our transcripts.

- ★ Cuadron et al. 2025, _The Danger of Overthinking: Examining the Reasoning-Action Dilemma in Agentic Tasks_ — https://arxiv.org/abs/2502.08235

### S2 — Limits of test-time compute scaling

Relevance: whether "more thinking" helps is task- and context-dependent; failure modes include distraction by irrelevant context (documented specifically for Claude models), error accumulation in long chains, and disproportionate compute on easy problems. Bears on problem A and on how much context each agent should receive.

- ★ Gema et al. 2025, _Inverse Scaling in Test-Time Compute_ — https://arxiv.org/abs/2507.14417
- Chen et al. 2024, _Do NOT Think That Much for 2+3=? On the Overthinking of o1-Like LLMs_ — https://arxiv.org/abs/2412.21187
- _Towards Thinking-Optimal Scaling of Test-Time Compute for LLM Reasoning_ — https://arxiv.org/abs/2502.18080
- Han et al. 2024, _Token-Budget-Aware LLM Reasoning_ — https://arxiv.org/abs/2412.18547

### S3 — Underspecification as an overthinking trigger

Relevance: ill-posed or premise-missing tasks drastically inflate reasoning length instead of triggering clarification requests. Bears on the planner→coder task contract.

- ★ Fan et al. 2025, _Missing Premise Exacerbates Overthinking_ — https://arxiv.org/abs/2504.06514

### S4 — Difficulty routing vs. escalation cascades

Relevance: our upfront complexity-grading experiment failed. Cascade architectures replace upfront difficulty _prediction_ with _measurement_ (attempt cheap, escalate on verified failure). Evaluate whether this fits our generic-loop constraint and what a grounded escalation signal would be.

- Chen, Zaharia, Zou 2023, _FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance_ — https://arxiv.org/abs/2305.05176

### S5 — Limits of intrinsic self-correction; grounded review

Relevance: review verdicts without external feedback are unreliable and can degrade output; structured verification of specific conditions performs differently from open-ended critique. Central to problems B and C, including the hedging edits.

- ★ Huang et al. 2024 (ICLR), _Large Language Models Cannot Self-Correct Reasoning Yet_ — https://arxiv.org/abs/2310.01798
- Wu et al. 2024, _Large Language Models Can Self-Correct with Key Condition Verification_ (PROCO) — https://arxiv.org/abs/2405.14092
- Sharma et al. 2023, _Towards Understanding Sycophancy in Language Models_ — https://arxiv.org/abs/2310.13548

### S6 — Evaluator biases

Relevance: self-preference/self-recognition, familiarity (perplexity) preference, verbosity bias, and bias amplification under iterative self-refinement. Bears on producer/reviewer separation, review-round caps, and candidate selection design.

- ★ Panickssery, Bowman, Feng 2024, _LLM Evaluators Recognize and Favor Their Own Generations_ — https://arxiv.org/abs/2404.13076
- Wataoka et al. 2024, _Self-Preference Bias in LLM-as-a-Judge_ — https://arxiv.org/abs/2410.21819
- Xu et al. 2024, _Pride and Prejudice: LLM Amplifies Self-Bias in Self-Refinement_ — https://arxiv.org/abs/2402.11436
- Saito et al. 2023, _Verbosity Bias in Preference Labeling by Large Language Models_ — https://arxiv.org/abs/2310.10076
- (Locate yourself, title search:) Shi et al., _Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge_

### S7 — Reviewer overcorrection and false-positive economics

Relevance: systematic misclassification of correct code as non-compliant; the counterintuitive effect of more elaborate review prompts; the trust-collapse dynamics known from decades of static-analysis practice. Central to problem C.

- ★ _Are LLMs Reliable Code Reviewers? Systematic Overcorrection in Requirement Conformance Judgement_ — https://arxiv.org/abs/2603.00539
- Xiong, Zhang et al., _Sifting the Noise: A Comparative Study of LLM Agents in Vulnerability False Positive Filtering_ — https://arxiv.org/abs/2601.22952
- _LLM4FPM: Utilizing Precise and Complete Code Context to Guide LLM in Automatic False Positive Mitigation_ — https://arxiv.org/abs/2411.03079 (see its citations of Johnson et al. and Christakis & Bird for the practitioner false-positive-rate literature)

### S8 — Practical reference: Opus 5 effort and adaptive thinking behavior

Not research; vendor documentation on the control surface available to us. Read for what the knobs actually do (and do not do — e.g. the relation between effort, thinking volume, and output verbosity), then decide independently how much weight to give it.

- https://platform.claude.com/docs/en/build-with-claude/effort

## Questions to answer

Answer each from the reading plus, where possible, evidence from our own transcripts and cost data. Where the research does not settle a question for our context, say so and propose how we would find out cheaply.

1. **Instrumentation.** Which of the failure patterns in S1/S2/S3/S7 are observable in our loop today, and what minimal logging or metrics would make them measurable? Candidates to consider: reasoning tokens per task phase, findings per changed line, rework ratio (rework tasks generated per input task), sampled finding precision, cost per merged task.
2. **Problem A.** Why, mechanistically, would upfront complexity routing fail while an escalation cascade might not — and does that reasoning survive contact with S2/S4? What would a valid, grounded escalation signal be in our loop? Separately: which structural constraints on the planner's _output contract_ (rather than its thinking settings) are supported by the evidence?
3. **Problem B.** What distinguishes verifiable from unverifiable review targets, and what does S5 predict for reviews of each class? Derive from this: (a) a candidate comment policy for the coder register, (b) a candidate scope rule for reviewers regarding comments, (c) where explanatory prose should live instead. Identify the trade-offs, including what we lose by writing fewer comments.
4. **Problem C.** Given that findings are individually fair, locate the actual defect in the loop design. Evaluate at least: a blocking-vs-backlog finding classification, diff-scoped gating, acceptance criteria emitted at planning time, and a findings budget with mandatory concrete failure scenarios. For each: expected effect, evidence basis, failure modes, and what it would cost to implement.
5. **Review anchoring.** Define what counts as sufficient anchoring evidence for a blocking finding in our loop (failing test, repro, analyzer output, requirement-to-code contradiction, coverage gap against acceptance criteria). Which finding categories can never be anchored, and what happens to them?
6. **Judge design.** Given S6: should producer and reviewer be different models, different contexts, or both? Where in our loop is _comparative_ judgment (selection between candidates) applicable instead of absolute verdicts, and what bias controls (order randomization, length normalization, provenance hiding) does the evidence justify?
7. **Cross-cutting.** Do any of the proposed interventions conflict with each other or with the generic-loop constraint? Rank the full set by expected value per unit of implementation effort.

## Deliverable

A short memo (not a report): per problem, two or three candidate interventions with — evidence basis (cite the specific paper and finding), expected effect, how we will measure it, implementation cost, and known risks. Flag anything in this briefing you concluded is wrong or unsupported. Present the memo for discussion; we decide jointly what to action, then you implement only what was agreed.
