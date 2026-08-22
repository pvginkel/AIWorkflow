# Research Briefing 2: Context Cost in a Multi-Agent Development Loop

## Purpose

You are asked to investigate four observed problems in our agentic development workflow, grounded in the research listed below. Download and read the primary sources yourself — do not rely on the one-line relevance notes, which exist only to orient you. Form your own conclusions; you may disagree with the framing given here, and _Observed problems_ ends with where this briefing itself is most likely wrong.

Your output is a proposal, not an implementation. See _Deliverable_ at the end. Nothing gets actioned before we decide together.

The first briefing (`research.md`; catalogue in `interventions.md`) is closed on measurement. What it exposed is the subject of this one: **the cost of our loop is context, not thinking.** This run is about "read less, without knowing less."

## Workflow context

- Loop: plan loop (plan-writer → plan-reviewer); run loop per phase (code-writer → deterministic gate → code-reviewer → fix on blocking findings only → merge); then completion consult, test agent, doc-writer. Reference slice: ≈ 5.6k lines, four repos, 12 phases, $221, rework 2.9 %, one blocking finding in thirteen reviews.
- Every agent is a fresh headless Claude Code session, no carry-over: dispatch prompt, role register (3–8 KB), two repository preambles (≈ 14 KB, every turn); it reads everything else with tools. Tool loops of 20–200 turns, no compaction. Files are the memory (plan, done-records, review files, close-out report); sessions are ephemeral. Scripts drive, agents judge.
- Models: Opus at maximum effort for every producer and judgment role; Sonnet for test, rebase, test-fixer. Effort fixed per session. Prompt caching on; our tooling prices cache writes at 1.25× and reads at 0.1× of input.
- "Explore" sub-agents (fresh context, returns a conclusion) are used by plan-writer, plan-reviewer and doc-writer; never by code-writers or the consult; almost never by reviewers.
- Implementation surface: stdlib-only Python scripts and markdown registers, generic across projects. Measurement in place: per-finding telemetry, per-run cost readout, raw JSONL transcripts with per-message `input` / `output` / `cache_creation` / `cache_read`.
- Settled, do not re-open: no effort tiering; no upfront difficulty routing; no weaker model as writer or reviewer; detection never suppressed; registers stay lean (additions A/B'd against finding precision); reviewer sees artifact and acceptance criteria, not narration; generic loop; files are the memory. Out of scope: another serving stack, fine-tuning, non-Claude models, anything that amounts to "think less."

## Observed problems

All numbers are one operator's two projects over 27 slices — grounding, not law.

**P1 — Context is the cost.** Reference slice: 82 % of spend was cache read (63 %) plus cache write (19 %); output 18 %. Across every Opus role on the seven prior slices, context was 67–84 % of cost. Effort reaches the output share and was withdrawn; the remaining lever is _what a role reads per turn_.

**P2 — Sessions grow; the longest dominate.** Per-turn context ≈ 100k tokens for reviewers, ≈ 125k for code-writers, ≈ 290k for the doc-writer. The doc-writer (one session, the whole shipped diff, 55 doc files, 192 turns) was the most expensive session at $33 and is 8–21 % of every slice. Big code-writer phases spend 50–70 turns of orientation reads before the first edit (one: 65 turns and six full suite runs; another: ten turns on a linter's line length).

**P3 — Every session rebuilds the same picture.** Each dispatch re-reads plan (≈ 74 KB), slice description (14 KB), design documents (33–50 KB), conventions and touched code — ≈ 40k tokens before the first useful call, across ≈ 30 sessions per slice. Known frictions burn full-context turns: ~50 turns per run re-learning one CLI's argument shape, 2–4 per review re-deriving line citations, repeated full gate runs. Sub-agent conclusions return into a context that then re-reads the same files.

**P4 — We do not know what smaller reads cost in grounding.** The instruments exist (blocking-finding rate, gate-red, rework share, refuted findings, dispositions). Gema et al. 2025 (first run) suggests irrelevant material degrades Claude's judgment, so curated context may improve quality — unmeasured. The doc-writer and reviewer are the roles whose value rests on the whole diff in view; the trade has two sides.

**Where this framing may be wrong — check before trusting it.**

1. _"Effort reaches only the output share."_ The docs now state that Opus 4.5 and later keep prior-turn thinking blocks in context by default, billed as input — so turn-10 thinking is cache-read on every later turn of a 150-turn session. How much of our cache-read share is retained thinking is computable from the transcripts. Re-derive the A3 accounting; do not inherit it.
2. _"Every later turn pays for every earlier turn's tool output."_ At 0.1×. The expensive events are each turn's write and any prefix break, which re-writes everything; with a 5-minute TTL, a gate run or build wait longer than that re-writes the prefix on resume. Separate steady growth from prefix breaks before "cut the session" is evaluated.
3. _"Read less → know less" as a monotone trade._ S6 finds long context beating retrieval on QA when affordable; the quality case for smaller reads rests on irrelevant-context harm, not "less is better." Curated and smaller are different treatments.
4. _290k tokens per doc-writer turn._ Verify the current Opus window; if the figure exceeds it, the measure is not what it appears.
5. _Sub-agents as the obvious lever._ S4 finds tool-heavy and sequential tasks pay a coordination tax, Anthropic models most sensitive; "sub-agents everywhere" is not supported as framed.

## Subjects and reading list

All arXiv abstract pages link to PDF and HTML. Read at minimum the seven ★ papers; skim the rest; "cite only" entries are known results to reference, not re-read. Every entry resolved on 2026-08-22; the one item not pinned to a URL is marked.

### S1 — Long-context degradation and irrelevant-context harm

Relevance: the quality case for smaller reads (P4) — extract the shape of degradation with input length for Claude models, the size of the distractor effect, and the self-conditioning result, which concerns a session's _own history_ and so bears on 100–200-turn loops (P2).

- ★ Hong, Troynikov, Huber 2025, _Context Rot: How Increasing Input Tokens Impacts LLM Performance_ — Chroma technical report, https://research.trychroma.com/context-rot
- ★ Sinha, Arun, Goel, Staab, Geiping 2025 (ICLR 2026), _The Illusion of Diminishing Returns: Measuring Long Horizon Execution in LLMs_ — https://arxiv.org/abs/2509.09677
- Xia, Wang, Huang, Liu 2026, _Diagnosing and Mitigating Context Rot in Long-horizon Search_ — https://arxiv.org/abs/2606.29718 (seven context-management methods compared on performance, cost and rot; open-source models only)
- Laban, Hayashi, Zhou, Neville 2025, _LLMs Get Lost in Multi-Turn Conversation_ — https://arxiv.org/abs/2505.06120 (bears on dispatch-prompt completeness)
- Cite only: _Lost in the Middle_ 2307.03172; Shi et al. 2023 _Easily Distracted by Irrelevant Context_ 2302.00093; Levy et al. 2024 _Same Task, More Tokens_ 2402.14848; _RULER_ 2404.06654; Gema et al. 2507.14417 (first run).

### S2 — Trajectory reduction, compression and compaction

Relevance: what can be removed from a growing session and what it loses (P1, P2) — extract the measured outcome of removing stale tool output in software-engineering agents, a method for finding what must survive compression, and how summarisation compares with reading programmatically.

- ★ Xiao, Gao, Peng, Xiong 2025 (FSE 2026), _Reducing Cost of LLM Agents with Trajectory Reduction_ (AgentDiet) — https://arxiv.org/abs/2509.23586 (closest published setting to ours)
- Kang et al. 2025, _ACON: Optimizing Context Compression for Long-horizon LLM Agents_ — https://arxiv.org/abs/2510.00615 (guideline learned from full-succeeds/compressed-fails pairs)
- Zhang, Kraska, Khattab 2025, _Recursive Language Models_ — https://arxiv.org/abs/2512.24601 (prompt as external environment; compared against compaction and sub-call scaffolds)
- Cite only: Sun et al. 2025 _Context-Folding_ 2510.11967 (RL-trained; read only the folding-versus-summarisation comparison); Mei et al. 2025 survey 2507.13334 (map only); _LLMLingua_ 2310.05736 / _LongLLMLingua_ 2310.06839.

### S3 — Orientation, cross-session memory and the hand-off

Relevance: every session rebuilds the same picture (P3) — extract what an orientation artefact must contain to cut reconnaissance turns, what workflow memory buys on recurring frictions, and the counter-case for one integrated context where consistency is the deliverable.

- ★ Gu, Zhang, Khattab, Madden 2026, _PEEK: Context Map as an Orientation Cache for Long-Context LLM Agents_ — https://arxiv.org/abs/2605.19932 (constant-size context map of a recurring repository; validated on a production coding agent)
- Wang, Li, Fried, Neubig 2024, _Agent Workflow Memory_ — https://arxiv.org/abs/2409.07429
- Bae et al. 2026, _Remember Your Trace: … Repository-Level Code Documentation_ (MemDocAgent) — https://arxiv.org/abs/2605.14563 (argues _for_ one trajectory over the whole repository; the doc-writer's two sides in one paper)
- Cite only: _MemGPT_ 2310.08560.

### S4 — Decomposition and sub-agents

Relevance: when a fresh context returning a conclusion beats continuing (Q3) — extract the task properties under which coordination pays or costs, the failure classes that matter, and the token economics practitioners report.

- ★ Kim et al. 2025, _Towards a Science of Scaling Agent Systems_ — https://arxiv.org/abs/2512.08296 (controlled evaluation across architectures and model families; extract the predictors)
- Cemri et al. 2025, _Why Do Multi-Agent LLM Systems Fail?_ (MAST) — https://arxiv.org/abs/2503.13657
- Cite only: _Chain of Agents_ 2406.02818.

### S5 — Agent–computer interface and tool-output hygiene

Relevance: the orientation phase and tool-output volume (P2) — extract the measured effect of shaping what a file read returns, and what trajectory studies say about navigation versus editing and about length as a failure signal.

- ★ Wang, Shi et al. 2026, _SWE-Pruner: Self-Adaptive Context Pruning for Coding Agents_ — https://arxiv.org/abs/2601.16746 (goal-hinted line-level pruning with Claude Sonnet 4.5 on SWE-bench Verified; the skimmer is a trained model — the shaped-read result is what we need)
- Majgaonkar, Fei, Li, Sarro, Ye 2025 (ICSE 2026), _Understanding Code Agent Behaviour: An Empirical Study of Success and Failure Trajectories_ — https://arxiv.org/abs/2511.00197
- Cite only: _SWE-agent_ 2405.15793 (read only the ACI ablation); _Agentless_ 2407.01489; _OpenHands_ 2407.16741.

### S6 — Retrieval versus reading

Relevance: the just-in-time case against whole artefacts (Q4) — extract when long context beats retrieval and at what cost; both studies are QA, not code, so transfer to plans and diffs is the open question.

- Li, Z. et al. 2024 (EMNLP Industry), _Retrieval Augmented Generation or Long-Context LLMs? A Comprehensive Study and Hybrid Approach_ — https://arxiv.org/abs/2407.16833
- Li, X., Cao, Ma, Sun 2024, _Long Context vs. RAG for LLMs: An Evaluation and Revisits_ — https://arxiv.org/abs/2501.01880
- Cite only: _CodeRAG-Bench_ 2406.14497.

### S7 — Cost-controlled evaluation and token economics

Relevance: comparing a smaller-read variant fairly (Q6) and the vendor facts the cost model rests on (Q2) — extract the cost/accuracy-Pareto methodology, the "token snowball" and "expensive failure" patterns for SE agents, and what the docs actually say about caching, thinking retention and context editing.

- ★ Kapoor, Stroebl, Siegel, Nadgir, Narayanan 2024, _AI Agents That Matter_ — https://arxiv.org/abs/2407.01502
- Fan et al. 2025, _SWE-Effi: Re-Evaluating Software AI Agent System Effectiveness Under Resource Constraints_ — https://arxiv.org/abs/2509.09853
- Cite only: _Efficient Agents_ 2508.02694 (GAIA, not code); _FrugalGPT_ (first run).
- Vendor docs — state what they say, do not extrapolate: prompt caching https://platform.claude.com/docs/en/build-with-claude/prompt-caching (write 1.25× / 1-hour 2×, read 0.1×; prefix hierarchy; invalidation; breakpoints); context windows https://platform.claude.com/docs/en/build-with-claude/context-windows and thinking https://platform.claude.com/docs/en/build-with-claude/thinking (thinking-block retention by model; current Opus window); context editing https://platform.claude.com/docs/en/build-with-claude/context-editing (tool-result and thinking clearing, server-side compaction — API-side; establish whether any is reachable from a headless Claude Code session before counting it as a lever).

### S8 — Practitioner references (not research; weight independently)

- Anthropic, _How we built our multi-agent research system_ (Jun 2025) — https://www.anthropic.com/engineering/multi-agent-research-system (≈ 15× tokens; "most coding tasks have fewer parallelizable parts")
- Anthropic, _Effective context engineering for AI agents_ (Sep 2025) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, _Effective harnesses for long-running agents_ (Nov 2025) — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents (what crosses a context-window cut)
- Cognition (Yan), _Don't Build Multi-Agents_ (Jun 2025) — https://cognition.ai/blog/dont-build-multi-agents. A 2026 follow-up by the same author reportedly narrows this to "writes single-threaded; extra agents add intelligence, not actions" — locate yourself; no URL verified.
- Claude Code sub-agents — https://code.claude.com/docs/en/sub-agents (and the context-window visualisation linked there)
- Aider repository map — https://aider.chat/docs/repomap.html and https://aider.chat/2023/10/22/repomap.html

## Questions to answer

Answer each from the reading plus our transcripts and cost data. Where the research does not settle a question for our context, say so and propose how we would find out cheaply.

1. **Instrumentation.** What composes a turn's context — fixed prefix (preambles, register, dispatch), files read, tool output, the agent's own prior output including retained thinking — and how does each grow per role? What minimal logging makes it visible: tokens-per-turn trajectory, fixed-versus-accumulated share, re-read ratio per file, cache-tier split per turn, prefix-break count and cost, cost of a session's last quartile? Which of S1/S2/S5's patterns (self-conditioning on failed attempts, give-up answers, navigation-dominated trajectories, expensive failures) are observable in the 27 slices today?
2. **The cost model.** With writes at 1.25× and reads at 0.1×, derive when cutting a session (fresh context plus hand-off artefact) beats continuing; how the break-even moves with turns, growth rate and prefix-break frequency; what the docs say about thinking retention and what invalidates a cached prefix, including TTL expiry during long waits. Separate what is computable from the transcripts from what must be trialled. Re-derive "effort reaches only the output share" under the retention rule the docs state.
3. **Decomposition.** Where does the evidence (S4; S2's folding and recursive results; S8's two positions) say a fresh context preserves enough, what it loses, and what coordination cost it adds? Map onto our roles: the code-writer's orientation, the doc-writer's per-surface work, the reviewer's whole-diff read, the consult. Evaluate at least: Explore sub-agents for orientation only; per-surface doc sub-agents with a consistency pass; a returned-conclusion contract carrying file:line evidence so the parent need not re-read. Which are safe, which not, and what is the telephone-game loss in each?
4. **Context curation.** Which of these does the evidence support for code agents, what does each lose, and what must a role still read in full (the acceptance criteria; the diff under review)? Evaluate at least: shaped tool output (head/tail, goal-hinted line selection, compact gate summaries — S5); a per-repository orientation map (S3, Aider) — our doc phase _produces_ that surface, a loop-internal flywheel whose staleness needs a rule; a per-phase plan digest instead of the whole plan; reduction of expired tool results (S2); retrieval against whole artefacts (S6). Treat _curated_ and _smaller_ as distinct treatments.
5. **Session shape.** One long session versus chained sessions with hand-off: what S1/S3 predict for 100–200-turn loops; what compaction costs in specifics (the file:line citations our reviews depend on); what the hand-off must carry (PEEK, the harness post, ACON's failure-pair method for discovering omissions). The doc-writer is the concrete case, with MemDocAgent as the argument against cutting it.
6. **Measuring grounding loss.** How to A/B a smaller or curated read without harming quality: which instruments detect loss fastest; what S7 says about comparing at equal cost; what the kill signal is; whether trajectory length (S5) serves as an early one.
7. **Cross-cutting.** Conflicts with the settled decisions and the generic-loop constraint; which measurements must precede which trials; ranking by expected value per unit of implementation effort — the surface is scripts and registers, and the first run's register-growth discipline applies to anything added to a preamble or dispatch.

## Deliverable

A short memo (not a report): per problem, two or three candidate interventions with — evidence basis (cite the specific paper and finding), expected effect, how we will measure it, implementation cost, and known risks. Flag anything in this briefing you concluded is wrong or unsupported, including the five caveats above. Present the memo for discussion; we decide jointly what to action, then you implement only what was agreed.
