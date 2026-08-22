# Prompt for the second research run — context economics

How to use: paste everything below the rule into claude.ai (Fable, web search on). Attach
`docs/research/research.md` (the first briefing — it is the shape we want back) and
`docs/research/interventions.md` (what the first run proposed and how it was decided — so nothing
is re-proposed). `tmp/slice-170-assessment.md` is optional grounding. Save the answer as
`docs/research/research-2.md`; a Claude Code session with repo access then reads the papers and
writes `interventions-2.md`, the way the first run went.

---

I want a second research briefing for our agentic development loop, in exactly the shape of the
first one (attached as `research.md`): **Purpose · Workflow context · Observed problems · Subjects
and reading list · Questions to answer · Deliverable**. You are selecting and framing the reading
and asking the questions; you are not reading the papers in full and not proposing interventions.
A separate session — one with our repository, 27 slices of run transcripts, per-message token
usage and the cost tooling — will read what you select and write the proposal. The first run
worked because the briefing did three things well: it named subjects with the *specific result* we
needed from each, it stated our observed problems with numbers, and it asked questions instead of
prescribing answers. Do the same.

## How the first run went, so you can calibrate

The first briefing (overthinking and review economics; problems A planner depth, B comment
churn, C work amplification) produced a catalogue of 25 interventions; six were shipped within a
day, measured over 27 slices, and the rest were closed on the measurement. Every problem as
briefed now has a measured answer: the planner has a cost floor and declares its task shape
honestly; comment churn costs $0 of rework; within-run amplification is bounded (rework median
≈ 7 %, 15 blocking findings / 0 refuted over 16 slices). One trial — running the code-writer at
lower effort — was withdrawn because it moved only output tokens, ≈ 20 % of a session's cost. What
that trial exposed is the subject of this run: **the cost of our loop is context, not thinking.**

## The system (what you need to know to choose the reading)

- **Shape.** An operator refines a slice with a session, then a script (the plan loop) dispatches a
  plan-writer and a plan-reviewer; a second script (the run loop) takes the plan — a queue of
  phases in a markdown file — and for each phase dispatches a code-writer, runs the project's
  deterministic gate, dispatches a code-reviewer, loops on blocking findings only, merges; then a
  completion consult, a test agent, a doc-writer. Twelve phases on the reference slice (SSH
  transport, ≈ 5.6k lines across four repos, 12 phases, $221, rework 2.9 %, one blocking finding in
  thirteen reviews).
- **Every agent is a fresh headless session** (Claude Code, spawned per dispatch) with **no
  carry-over**: it gets a dispatch prompt naming paths, a role register (3–8 KB of markdown),
  two repository preambles loaded every turn (≈ 14 KB), and reads everything else itself with
  tools. Sessions are single-threaded tool loops of 20–200 turns. Files are durable, sessions are
  ephemeral: the plan, per-phase done-records, the review files and a close-out report are the
  only inter-session memory. **Scripts drive, agents judge**: anything deterministic (gates, git,
  caps, stamping, parsing) is Python; judgment is an agent.
- **Models.** Claude Opus at maximum effort for every producer and judgment role; Sonnet for the
  test agent, the rebase agent and the test-fixer. Effort is fixed per session. Prompt caching is
  on: each session's growing prefix is cached; our tooling prices cache writes at 1.25× and cache
  reads at 0.1× of the input price.
- **Sub-agents exist and are used unevenly.** Any agent may spawn an "Explore" sub-agent — a fresh
  context that searches and returns a conclusion. The plan-writer (grounding surveys), the
  plan-reviewer (citation checks) and the doc-writer (doc-surface surveys) do; code-writers and
  the consult never do; reviewers almost never.
- **The implementation surface** is stdlib-only Python scripts and markdown registers, generic
  across projects (a project describes itself in a TOML file and a manifest); no per-task tuning.
- **Measurement in place** from the first run: per-finding telemetry (severity, blocking/advisory,
  category, anchor type, refuted), a per-run cost readout (planner/research/rework shares), and
  the raw transcripts (JSONL, per-message `input`/`output`/`cache_creation`/`cache_read` usage),
  so the reading session can compute anything per turn, per role, per slice.

## Observed problems

**P1 — Context is the cost.** On the reference slice 82 % of spend was cache read (63 %) and
cache write (19 %); output tokens were 18 %. Across every Opus role on the seven slices before it,
context was 67–84 % of cost. Effort (thinking) was the lever the first run tried; it reaches
only the output share and was withdrawn. The remaining lever is *what a role reads per turn*.

**P2 — Sessions grow; the longest ones dominate.** Per-turn context averages ≈ 100k tokens for
reviewers, ≈ 125k for code-writers, ≈ 290k for the doc-writer (no compaction; the window in use is
at least that). The doc-writer — one session, the whole shipped diff, every documentation surface
it touches (55 files on the reference slice), 192 turns — was the single most expensive session
at $33 and is 8–21 % of every slice, second only to the writers in aggregate. Big code-writer
phases spend 50–70 turns of orientation reads before the first edit (one phase: 65 turns, six
full suite runs including a redundant triple; another: ten turns on a linter's line length).
Sessions of 100–200 turns pay for every earlier turn's tool output on every later turn.

**P3 — Every session rebuilds the same picture.** Each dispatch re-reads the plan (≈ 74 KB on the
reference slice), the slice description (14 KB), attached design documents (33–50 KB), project
conventions and the code it touches — ≈ 150 KB, ≈ 40k tokens, before the first useful tool call,
across ≈ 30 sessions per slice — and the registers and preambles ride every turn. Known frictions
burn full-context turns: ~50 turns per run re-learning one CLI's argument shape, 2–4 turns per
review re-deriving line citations, repeated full gate runs. Sub-agent decomposition, where it is
used, returns conclusions into a context that then often re-reads the same files anyway (the
doc-writer's two surveys returned after it had started writing).

**P4 — We do not know what smaller reads would cost in grounding.** The instruments that would
tell — blocking-finding rate, gate-red rate, rework share, refuted findings, operator dispositions
on the close-out report — exist and read well today. The first run's reading already noted
(Gema et al. 2025, inverse scaling) that Claude models degrade with irrelevant material in scope,
which suggests shorter, better-curated context may *improve* judgment, not just cost; we have not
measured that either way. Conversely, the doc-writer and the reviewer are the roles whose value
rests on having the whole diff in view — the trade has two sides.

## What is settled — do not re-open

From the first run (attached catalogue): no effort tiering (tried, withdrawn — ≤ 1 % saving against
a witnessed rework strike), no upfront difficulty routing (a graded lane was built and retired),
no Sonnet or weaker model as writer or reviewer (tried; and judgment resists sway with model
strength), detection is never suppressed (findings are routed and evidence-gated, never
silenced), registers stay lean (every addition is A/B'd against finding precision), the
reviewer sees the artifact and the acceptance criteria rather than the coder's narration, the
loop stays generic with no per-task tuning, files are the memory and sessions are ephemeral,
scripts drive and agents judge. Interventions that need a different serving stack, fine-tuning,
or a non-Claude model are out of scope. Anything in this run that amounts to "think less" has
been tried; this run is about "read less, without knowing less."

## Subjects and reading list — what I need from you

Choose 12–18 papers across the subjects below (add subjects I have missed, drop any that do not
earn a place), mark about six ★ must-reads, and for each subject write the one-line **Relevance**
note the first briefing used: the *specific result* the reading session must extract, and which
problem it bears on. Use web search. **Verify every entry** — title, authors, year, arXiv id or
URL that resolves; prefer 2024–2026 primary sources; say plainly where something could not be
verified or sits behind a paywall (the first run had one paper it had to locate by title). The
list below is seed material, not a decision — replace anything with a better source.

- **S1 — Long-context degradation and irrelevant-context harm** (the quality case for smaller
  reads): Lost in the Middle (2307.03172); RULER (2404.06654); Same Task, More Tokens (2402.14848);
  Large Language Models Can Be Easily Distracted by Irrelevant Context (2302.00093); the Chroma
  "Context Rot" report (2025); LLMs Get Lost in Multi-Turn Conversation (2505.06120); The Illusion
  of Diminishing Returns (2509.09677, long-horizon execution and self-conditioning on earlier
  errors). Gema et al. (2507.14417) was read in the first run — cite, do not re-assign.
- **S2 — Context engineering, compression and compaction**: the context-engineering survey
  (2507.13334); LLMLingua / LongLLMLingua (2310.05736, 2310.06839); what summarisation or
  compaction loses (specifics such as file:line citations, which our reviews depend on);
  Anthropic's "Effective context engineering for AI agents" (engineering post, 2025) as a
  practitioner reference.
- **S3 — Memory and session shape**: MemGPT (2310.08560); Agent Workflow Memory (2409.07429);
  anything solid on one long session versus chained shorter sessions with a hand-off artefact —
  our design already supports the latter (durable files), so the question is what the evidence
  says about where to cut and what must cross the cut.
- **S4 — Decomposition and sub-agents**: Chain of Agents (2406.02818); Why Do Multi-Agent LLM
  Systems Fail? (2503.13657 — information loss and inter-agent misalignment are the failure classes
  that matter here); Anthropic's "How we built our multi-agent research system" (engineering post,
  2025 — token economics of orchestrator + parallel sub-agents); whatever exists on when a fresh
  sub-context returning a conclusion beats continuing in one context, and what gets lost in the
  telephone game.
- **S5 — Agent–computer interface and tool-output hygiene**: SWE-agent (2405.15793 — the ACI
  result: how tool output is shaped changes agent performance); Agentless (2407.01489 — structure
  over agency); OpenHands (2407.16741); evidence on trajectory length versus success; repository
  maps and progressive disclosure (Aider's repo map is the practitioner example).
- **S6 — Retrieval versus reading for code**: RAG vs long-context studies (2407.16833, 2501.01880);
  CodeRAG-Bench (2406.14497) or better; repository-level code understanding; the case for
  just-in-time context against reading whole files and whole plans.
- **S7 — Cost-controlled evaluation and token economics**: AI Agents That Matter (2407.01502 —
  cost/accuracy Pareto, cost-controlled comparisons); Efficient Agents (2508.02694 — verify);
  FrugalGPT was read in the first run — cite only. Plus the vendor economics as a practitioner
  subject: Anthropic's prompt-caching documentation (write/read multipliers, the 5-minute and
  1-hour tiers, cache breakpoints, what invalidates a prefix), the current Opus context window,
  and whether earlier turns' thinking blocks stay in context — state what the docs actually say
  and what we must measure ourselves.
- **S8 — Practitioner references** (not research, labelled as such): the two Anthropic
  engineering posts above, the prompt-caching docs, Claude Code's sub-agent documentation, Aider's
  repo map. Read for what the knobs do; weight independently.

## Questions the briefing must ask the reading session

Write these in the first briefing's voice — questions, with "evaluate at least …" lists where a
question has obvious candidates — and improve them; these are my draft.

1. **Instrumentation.** What composes a turn's context in our loop — fixed prefix (preambles,
   register, dispatch), files the agent read, tool output, its own prior output — and how does
   it grow over a session? What minimal logging makes that visible per role (tokens-per-turn
   trajectory, fixed-versus-accumulated share, re-read ratio for the same file, cache-tier split,
   cost of a session's last quartile of turns)? Which of S1/S2's failure patterns would be
   observable in our transcripts today?
2. **The cost model.** With cache writes at 1.25× and reads at 0.1×, derive when cutting a
   session (fresh context plus a hand-off artefact) beats continuing, how the break-even moves
   with turns and growth rate, and what the vendor docs say about what breaks a cached prefix.
   Separate what can be computed from the transcripts from what must be trialled.
3. **Decomposition.** Where does the evidence say delegation to a fresh context preserves enough
   (and what does it lose), and what coordination cost does it add? Map it onto our roles: the
   code-writer's orientation phase, the doc-writer's per-surface work, the reviewer's whole-diff
   read, the consult. Which decompositions are safe, which are not, and what would a sub-agent
   have to return for the parent not to re-read the source?
4. **Context curation.** Progressive disclosure, tool-output shaping (head/tail, structured
   summaries, compact views), repository maps and curated documentation as the read surface —
   note that our own doc phase *produces* that surface, a loop-internal flywheel — and retrieval
   against reading whole artefacts. Which of these the evidence supports for code agents, what
   each loses, and what a role must still read in full to stay grounded (the acceptance criteria;
   the diff under review).
5. **Session shape.** One long session versus chained sessions with hand-off: what S1/S3 predict
   for 100–200-turn tool loops; what compaction/summarisation costs in specifics; what the
   hand-off must carry. The doc-writer as the concrete case.
6. **Measuring grounding loss.** How to A/B a smaller read without harming quality: which of our
   instruments (blocking-finding rate, gate-red, rework share, refuted, dispositions) detect loss
   fastest, what the cost-controlled-evaluation literature says about comparing agents at equal
   cost, and what the kill signal is.
7. **Cross-cutting.** Conflicts with the settled decisions above and with the generic-loop
   constraint; ranking by expected value per unit of implementation effort — remembering our
   implementation surface is scripts and registers, and that the first run's register-growth
   discipline applies.

## Deliverable (from you, now)

The briefing document only: the six sections, in the first briefing's shape and length (it was
about two pages — keep that). Every paper verified; ★ on the must-reads; a Relevance note per
subject naming the result we need. Flag anything in *my* framing you think is wrong or
unsupported — the first briefing invited that and the reading session used it. Do not propose
interventions and do not rank; that is the reading session's job, and nothing is actioned before
we decide together. Treat every number above as grounding from one operator's two projects over
27 slices, not as law.
