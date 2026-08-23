# Memo — Context Economics in the Dev Loop (research run 2)

Companion to [research-2.md](research-2.md) (the briefing) and the standing catalogue
[interventions.md](interventions.md) (run 1). **A proposal for discussion, not a decision.** Nothing
here is actioned.

**Follow-through (2026-08-23):** the operator kept the dollar target and chose the turn-count
reading of these numbers — [turns-plan.md](turns-plan.md) is the stepwise action plan (T1 turn
taxonomy first); this memo stays the evidence.

Produced 2026-08-22 from: the 809 sessions of 32 slices (KubeCoderSpecs 144–170, AnsibleSpecs
006–015) replayed turn by turn with [tools/context_profile.py](tools/context_profile.py) — full
tables in [context-profile-2026-08-22.md](context-profile-2026-08-22.md); 19 papers and 22 web
pages mirrored under [articles/](articles/); one extract per source under [extracts/](extracts/)
(Opus extraction agents on the full text; the ★ sources' extracts were checked by the lead against
the article). Every number below is either from the profile report or cites an extract.

**How to read an entry.** Each candidate carries **Evidence** (paper + finding, or our data),
**Effect** (expected, with the share of spend it can reach), **Measure** (how we'd know), **Cost**
(S/M/L), **Risks** (what it loses). Spend shares are of the $2,420 the 32 slices cost.

---

## 0. The answer in one paragraph

Context is the cost — but not the way the briefing frames it. Of all tokens the models processed
(2.97 G), **29 % were the fixed prefix paid again on every turn, 17 % the session's own prior output
(7 % retained thinking), and 54 % tool results — and ≈ 40 % of everything processed was file
contents read into context once and re-read at 0.1× on every later turn.** Prefix breaks are
negligible (0.7 % of headless spend). The cost of a session is therefore set by two things we
control: **how many turns it takes** (each turn re-pays the prefix and the history) and **how much
it drags along** (the tail of long sessions: 7 % of sessions ≥ 80 turns = 25 % of spend; the
doc-writer alone 13 %). The research supports cutting *irrelevant* context (it harms Claude most,
by abstention — Chroma; distractors — one is enough) and does **not** support cutting context
mechanically (every untrained compressor lost resolve rate with Claude Sonnet 4.5 — SWE-Pruner;
window size is two-sided — SWE-agent). So the candidates are: fewer turns per session (batched
reads, an orientation digest in the dispatch, frictions delivered at the point of use), a trimmed
fixed prefix, and a bounded doc phase — with the measurement wired in first, because the quality
side of every trade is unmeasured today.

---

## 1. What our data says

Medians unless stated; "headless" = every role except the two interactive orchestrators.

- **Where the dollars go.** Cache read 56 %, cache write 23 %, output 21 %, uncached input ≈ 0.
  By role: code-writer 29 %, code-reviewer 17 %, doc-writer 13 %, plan-writer 8 %, plan
  orchestrator 7 %, test-agent 6 %, Explore sub-agents 6 %, consult 5 %, run orchestrator 3 %,
  plan-reviewer 3 %.
- **What a turn's context is made of.** Fixed prefix ≈ 32 k tokens for every dispatched role
  (Explore 12 k): Claude Code system prompt + tool schemas ≈ 16 k (cache-read across sessions for
  writers/reviewers; written in full by doc/plan/test sessions — the git-status snapshot in the
  system prompt makes sequential sessions' prefixes differ, see [extracts/web-claude-code-docs-harness.md](extracts/web-claude-code-docs-harness.md))
  plus ≈ 16 k session-specific: preambles (org 5.6 KB + project 8.8 KB + specs 3 KB), register
  (3–8 KB), dispatch (1.3 KB) and **≈ 23 KB of harness listings** (deferred-tool names 7.5 KB,
  skills 10 KB, agents 4.3 KB, MCP instructions 1.5 KB) that headless roles never use, bar the test-agent's Jenkins/gitblit calls. Fixed share of
  processed tokens: 39 % for the median writer and reviewer, 22 % doc-writer.
- **Growth.** Writers +1.0 k tokens/turn, reviewers +2.7 k, Explore +3.4 k, doc-writer +1.2 k. Median
  per-turn context 81 k writer / 83 k reviewer / 144 k doc-writer; ctx-max p50 108 k, 51 sessions
  > 200 k, 6 > 300 k, max 438 k (the 170 doc-writer: 192 turns, $33). Sessions ≥ 80 turns: 7 % of
  sessions, 25 % of spend; the last quartile of turns is 26 % of spend (cost-weighted).
- **Tool results by volume.** Writers: Read 45 %, Bash `cat`/`sed -n` 32 %, grep 9 %, git 7 %, **gate
  output 1 %** (median gate result 112 chars — the suite runs cost turns and minutes, not tokens).
  Reviewers: `cat`/`sed` 38 %, Read 31 %, git-inspect 16 %, grep 11 %. Explore: `cat`/`sed` 36 %,
  grep 28 %, Read 26 %. Read results p50 6 k chars, p90 29 k; the 14 % of Reads over 20 k chars carry
  49 % of Read volume. Agents already read windows: `sed -n <range>` is the single most common
  orientation call (585 of ≈ 2,200 across 145 writer sessions), grep second (572).
- **Turns.** Writers issue **1.07 tool calls per turn** (8 % of turns batch ≥ 2); reviewers 1.43,
  doc-writer 1.18, Explore 1.82. Median writer session: 37 turns, 38 calls. Orientation (turns
  before the first edit): median 14 (p25 8, p75 20, max 64) = **38 % of a writer session's cost**
  (p25–p75 30–46 %); context at first edit 77 k. **164 of 184** writers run the gate at some point
  and **12 of 181** run one before their first edit (corrected 2026-08-23: the "136/184 … before
  editing" this line first carried matches no cut of the corpus).
- **Turns, by what they do** (added 2026-08-23 from T1's taxonomy, §13 of
  [context-profile-2026-08-23.md](context-profile-2026-08-23.md)): `orient-read` is the largest
  class of turn — 37 % of all headless turns and 33 % of their cost, 28 % of the writer's own
  turns. `edit` is 16 %, `gate` 4 %, `commit` 3 %. The 1.07 tool calls per turn above understate
  batching, because a writer chains reads inside one Bash command: counting those, a writer turn
  that reads at all does **1.67** reads (reviewers 2.5, Explore 3.0) — real batching, but well
  short of what the read-only runs would allow.
- **Re-reads.** Within a session files are rarely read twice (ratio ≈ 1.0). Across sessions the
  same few files recur: plan.md is Read by 36 sessions (+49 `cat plan.md` in orientation),
  `environment_service.py` by 35 (75 reads), `store.py` by 32, slice.md by 31, the persisted
  Bash-output file by 29 (1.3 MB — `cat plan.md` spills to disk and is then Read whole). Parents
  re-reading what their own sub-agent already read (same path): doc-writer 25 % of post-dispatch
  reads, plan-writer 18 %, plan-reviewer 17 %, reviewer ≈ 0 — the briefing's "returns into a context that re-reads the
  same files" is weakly supported.
- **Prefix breaks and TTL.** 82 breaks in 809 sessions, $32 (1.3 %); in headless sessions $14
  (0.7 %): test-agent 21 breaks (deploy waits), interactive orchestrators 48 (human-paced). Gaps
  > 5 min in headless producer sessions: 29. The loop's cost is steady growth, not breaks.
- **Thinking is retained.** On 664 probe turns (big thinking, tiny tool result) context grew by
  1.04× the previous turn's *full* output (p25 1.02, p75 1.08) — 7.5× if thinking were stripped.
  Retained thinking = 6.9 % of processed tokens, **$96 = 4.0 %** of spend at the read rate. With
  output at 21 %, effort reaches ≈ 25 % of spend — A3's accounting was short by a fifth, and the
  conclusion stands.
- **What a cut or an expiry would buy, computed on the real trajectories** (`--what-if`): the best
  single cut with a 4 k-token hand-off and 40 k of re-orientation saves 7.6 % of writer spend
  (35/184 sessions > 5 %), **19.9 % of doc-writer**, 8.9 % of test-agent, ≈ 0 for reviewers and
  Explore. Expiring tool results older than 20 turns (optimistic, ignoring the cache invalidation
  the docs say it causes, and not reachable from Claude Code anyway — §2): writer 11 %, doc-writer
  18 %, reviewer 2 %.
- **Explore sub-agents** are 148 sessions, $153 (6.3 %), 116 on Opus (they inherit the dispatcher's
  model; the built-in Explore lost its Haiku pin at Claude Code v2.1.198) — Sonnet-priced they would
  be $102 (−$51, 2.1 %).

## 2. Where the briefing is wrong, unsupported, or different from what the data says

1. **Caveat 1 — "effort reaches only the output share": wrong, as suspected.** Prior-turn thinking
   is kept by the API on Opus 4.5+ ([extracts/web-claude-code-docs-harness.md](extracts/web-claude-code-docs-harness.md) §5, vendor context-windows page) and the transcripts
   confirm it (probe above). Effort reaches ≈ 25 %, not 18 %. Still a minority lever; A3 stays
   withdrawn.
2. **Caveat 2 — prefix breaks and TTL: not our problem.** 0.7 % of headless spend; the 5-minute TTL
   is refreshed on every use and measured from request start; headless sessions wait > 5 min 29
   times in 704 sessions. "Cut the session" has to be evaluated on growth alone — done (§1 what-if).
   Note `FORCE_PROMPT_CACHING_5M=1` is documented as a debugging switch; the production knob is
   `ENABLE_PROMPT_CACHING_1H`, which at 2× writes would cost us more, not less.
3. **Caveat 3 — "read less → know less" is not monotone, and the evidence cuts both ways.** For:
   Chroma's focused-vs-full LongMemEval gap is largest for Claude, driven by abstention
   ([extracts/web-chroma-context-rot.md](extracts/web-chroma-context-rot.md)); Xia et al. raised accuracy
   +1.6–4.0 by shrinking retained context ([extracts/2606.29718](extracts/2606.29718-diagnosing-and-mitigating-context-rot-in-long-horizon-search.md)); Sinha: a fresh context pays for what the old one *contains*, not its length ([extracts/2509.09677](extracts/2509.09677-the-illusion-of-diminishing-returns-measuring-long-horizon-execution.md)).
   Against: every untrained read-shaper lost resolve rate with Claude Sonnet 4.5 (RAG 50, summarise
   56, LongCodeZip 54, LLMLingua2 54 vs 62 unshaped; only the trained goal-hinted skimmer won, 64 at
   −31 % tokens — [extracts/2601.16746](extracts/2601.16746-swe-pruner-self-adaptive-context-pruning-for-coding-agents.md)); SWE-agent's window ablation is two-sided (30 lines 14.3, 100 lines 18.0, whole file 12.7 —
   [extracts/2405.15793](extracts/2405.15793-swe-agent-agent-computer-interfaces-enable-automated-software.md)); Context-Folding's ordering at 10× smaller context is truncation −19/−12, summarisation −9/−6, folding −6/−6
   points ([extracts/2510.11967](extracts/2510.11967-scaling-long-horizon-llm-agent-via-context-folding.md)). **Curated and smaller are different treatments**, and the only safe mechanical cut is of *irrelevant* material.
4. **Caveat 4 — 290 k per doc-writer turn is real.** Opus 5's window is 1 M by default (vendor
   context-windows page); Claude Code's auto-compact defaults to the model limit, so no session ever
   compacted (max 438 k). The figure is the mean context of 192 turns, exactly as measured.
5. **Caveat 5 — sub-agents: confirmed, and sharper than framed.** Kim et al.'s one doubly-robust
   predictor is capability saturation — coordination goes net-negative once the single agent
   already exceeds ≈ 45 %; on SWE-bench Verified every multi-agent variant loses; tokens 1.6–6.2×
   ([extracts/2512.08296](extracts/2512.08296-towards-a-science-of-scaling-agent-systems.md)). The "Anthropic most sensitive" line rests on two figure captions and the same paper has Anthropic best of three families on its 16-tool benchmark — don't carry it forward. What the paper *does* support: per-surface work with a verifying consistency pass, and orientation-only exploration where the parent's own baseline is low.
6. **P2's "50–70 turns of orientation"** is the tail (max 64); the median is 14, p75 20. **P3's
   "≈ 40 k tokens before the first useful call"** understates it: context at first edit is 77 k
   median, but 32 k of that is the fixed prefix.
7. **"Repeated full gate runs" as a context cost** — gate output is ≈ 1 % of writer tool volume.
   Gate runs cost turns (3 median, up to 12) and minutes; the six-suite-run phase was a turn
   problem, not a token problem.
8. **The S3 relevance note on PEEK overstates one word**: PEEK never maps a repository or a context
   that mutates between runs; it validated on Codex CLI with a single `context.txt` and has a
   per-item `stale` tag, not a staleness policy ([extracts/2605.19932](extracts/2605.19932-peek-context-map-as-an-orientation-cache-for-long-context-llm-agents.md)). MemDocAgent's "one
   trajectory" is rhetoric: each unit is a ≤ 10-step sub-task whose context is refreshed; continuity
   lives in an external memory — it is evidence *for* a per-surface split with a consistency pass,
   not against ([extracts/2605.14563](extracts/2605.14563-remember-your-trace-memory-guided-long-horizon-agentic-framework-for.md)). Aider's map has no staleness rule because it is recomputed per request, never authored ([extracts/web-aider-repomap.md](extracts/web-aider-repomap.md)).
9. **Q2's "establish whether context editing is reachable"**: it is not. API-side tool-result /
   thinking clearing and server-side compaction appear nowhere in the Claude Code docs; Claude
   Code's own compaction is client-side, threshold `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (100 K–1 M,
   default = model limit), and `kc session create-headless` passes `--print
   --dangerously-skip-permissions --output-format stream-json [--agent] [--model] [--effort]` plus
   `-e` env vars — so env-var and plugin-hook levers are reachable, `--bare`/`--settings` are not.

## 3. Candidate interventions

### P1 — Context is the cost (cut what every turn re-pays)

**P1.1 Batch independent reads — fewer turns, same content. S.**
**Evidence:** our writers issue 1.07 tool calls per turn and spend 14 turns orienting; every turn
re-pays ≈ 77–110 k tokens at the read rate plus the prefix write. Anthropic's research harness cut
wall-time up to 90 % by issuing 3+ tools per turn ([extracts/web-anthropic-engineering-posts.md](extracts/web-anthropic-engineering-posts.md)); Cognition's "single-threaded" rule concerns writes, not reads ([extracts/web-cognition-multi-agents.md](extracts/web-cognition-multi-agents.md)). Nothing
in the reading argues against reading in parallel.
**Effect:** if the median writer's 14 orientation turns became 6–8, the session loses 6–8 × (77 k ×
0.1 × $5/M + output) ≈ $0.30–0.45 of $3.7 — **≈ 8–12 % of writer spend (2–3 % of total)**; more on
the tail. **Measure:** tools/turn, turns/session, orientation turns, cost/session — all in the
profile; quality by the run-1 instruments (blocking-finding rate, gate-red, rework, refuted).
**Cost:** one sentence in the code-writer (and doc-writer) register, A/B'd against finding
precision per the register discipline. **Risks:** over-fetching (batching invites reading more than
needed — the very bulk Chroma says hurts Claude); the model may not comply at xhigh.

**P1.2 Trim the fixed prefix headless roles never use. S.**
**Evidence:** ≈ 23 KB (≈ 6 k tokens) of the 32 k prefix is deferred-tool names, skill and agent
listings and MCP instructions; headless roles use none of the Trello/Telegram MCP tools (test agents
use Jenkins). Costs page: "Disable unused servers"; deny-listing a bare tool name removes it from
context; `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` ([extracts/web-claude-code-docs-harness.md](extracts/web-claude-code-docs-harness.md) §1).
**Effect:** −6 k of 32 k on every turn ≈ **5 % of processed tokens, ≈ 4 % of spend**, zero quality
exposure. **Measure:** `ctx_first` per role in the profile. **Cost:** S — per-role `-e` env vars in
`run_loop.py`'s spawn if a listing can be disabled by env, else the project's `.claude/settings.json`
(per-project, outside the plugin — note the portability line). **Risks:** a role that did need a
listed tool (test-agent → Jenkins) must keep it; verify per role from the tool mix first.

**P1.3 Not proposed, with numbers.** Thinking clearing (4 % of spend, and clearing breaks the
cached prefix every turn); the 1-hour TTL (2× writes for 29 long gaps); tool-result expiry (≤ 11 %
writer / 18 % doc-writer *before* the invalidation it causes, and unreachable); and effort (25 %,
settled).

### P2 — Sessions grow; the longest dominate

**P2.1 Bound the doc phase: one writer per repo/surface in dependency order, then a consistency
pass. M.**
**Evidence:** the doc-writer is 13 % of spend, the longest sessions (66 turns median, up to 192;
144 k mean context, up to 438 k), and the one role where a cut pays on the real trajectories (20 %
of its spend, 24/32 sessions). MemDocAgent runs per-unit with a script-computed order and an
external consistency check: cross-document inconsistency 13 % → 3 %, read time −41 %, quality rising
on larger repos where stateless baselines fall ([extracts/2605.14563](extracts/2605.14563-remember-your-trace-memory-guided-long-horizon-agentic-framework-for.md)). Kim et al.: per-surface + verifying pass is the best-supported multi-agent shape; Cognition 2026: one writer per scope, a non-writing pass synthesises ([extracts/web-cognition-multi-agents.md](extracts/web-cognition-multi-agents.md)); Anthropic's harness post: incremental units with a progress artefact. Chroma: bulk irrelevant context hurts Claude most — the whole-slice diff plus 55 doc files is the loop's bulkiest context.
**Effect:** doc-writer spend −20–35 % (**≈ 3–4 % of total**), ctx-max from 300–438 k to < 150 k;
quality effect unknown in either direction (cross-surface consistency is the risk; bulk distraction
is the opportunity). **Measure:** doc-writer cost share and ctx-max; inconsistencies caught by the
consistency pass; operator doc fix-nows at close-out; a sampled read of two slices' docs before/after.
**Cost:** M — the doc phase becomes a queue of units the driver already knows how to run (phases
with a Target), plus one consistency session reading the units' diffs; the consistency session is
where MemDocAgent says the value is. **Risks:** the coordination tax (Kim: 1.6–6.2× tokens when an
agent already does well alone — mitigated because units run sequentially, not fan-out); a
cross-repo fact that lived in the whole-diff view; more sessions = more fixed prefixes (≈ 32 k × turns
each).

**P2.2 A per-role auto-compact window for the tail, with a hand-off the compaction must carry. S
to trial, M to do well.**
**Evidence:** `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (100 K–1 M) is an env var we can pass per role;
Claude Code's compaction keeps "architectural decisions, unresolved bugs, implementation details"
plus the five most recently accessed files; a `PreCompact` hook receives `custom_instructions` and
can archive the transcript ([extracts/web-claude-code-docs-harness.md](extracts/web-claude-code-docs-harness.md) §2; [extracts/web-anthropic-engineering-posts.md](extracts/web-anthropic-engineering-posts.md)). Summarisation costs specifics: ACON's learned guideline is "keep every endpoint, parameter list, raw rows, all positive matches; never replace machine-readable data with prose" ([extracts/2510.00615](extracts/2510.00615-acon-optimizing-context-compression-for-long-horizon-llm-agents.md)); Context-Folding: summarisation −9/−6 points vs truncation −19/−12; Laban: the hand-off must be a consolidated restatement, not a delta ([extracts/2505.06120](extracts/2505.06120-llms-get-lost-in-multi-turn-conversation.md)).
**Effect:** for sessions that would exceed the window (doc-writer, 150-turn writers, test-agent) the
what-if bound: 10–20 % of that role's spend; nothing for the median session. **Measure:**
compaction events and their cost (visible in transcripts), ctx-max, plus the grounding instruments
on the sessions that compacted. **Cost:** S for the env var on the doc-writer; M to add the
`PreCompact` archive and a compaction instruction that names what must survive (done-record
settlements, file:line evidence, the doc unit list). **Risks:** a generic summary loses the
citations reviews depend on; a compaction mid-edit (the harness post's "half-implemented and
undocumented" failure); prefer P2.1 for the doc-writer and keep this for the writer/test tail.

**P2.3 Not proposed:** cutting median writer or reviewer sessions (≤ 8 % / ≈ 0 on the real
trajectories at realistic re-orientation cost); turn/token caps as an early stop (SWE-Effi and
Majgaonkar: length separates failure from success weakly; variance and wrong-file are the sharper
signals, and SWE-agent's most expensive failures ran under a hard cap — [extracts/2509.09853](extracts/2509.09853-swe-effi-re-evaluating-software-ai-agent-system-effectiveness-under.md), [extracts/2511.00197](extracts/2511.00197-understanding-code-agent-behaviour-an-empirical-study-of-success-and.md)).

### P3 — Every session rebuilds the same picture

**P3.1 A script-built orientation digest in the dispatch, phase-scoped. S–M.**
What the driver already knows and the writer currently re-derives in 14 turns: this phase's
section and Target, the acceptance criteria that touch it, the *settlements* of prior phases'
done-records, the headings + Targets of later phases (it may have to edit them), the files prior
phases touched (from git), the gate command, and the slice's one-paragraph intent — instead of
"read the whole plan" (15–74 KB) and `cat slice.md`.
**Evidence:** PEEK: a 1 k-token orientation map in the prompt lifts success +6–20 % with iterations
at or below baseline, a frozen map still wins big, and "presence matters more than size"; a
retrieval-built map gained only +4.9 and mid-run regeneration lost 14.9 ([extracts/2605.19932](extracts/2605.19932-peek-context-map-as-an-orientation-cache-for-long-context-llm-agents.md)). AWM: seven tiny workflow items per site cut steps 25 % at higher success ([extracts/2409.07429](extracts/2409.07429-agent-workflow-memory.md)). Anthropic's harness: a progress file + git log is how a fresh session gets its bearings. Chroma: the rest of the plan — other phases' detail, superseded text — is structurally the near-miss distractor that one instance of already hurts. Laban: a single consolidated instruction retains 95 % of full-instruction performance; shards lose 39 %. Cognition: re-discovery is waste for a *writer* (and a feature for a judge — leave the reviewer's read alone).
**Effect:** orientation turns 14 → ≈ 8 and the plan read 9–18 k → ≈ 3 k tokens: **≈ 15–20 % of writer
spend (≈ 5 % of total)**, plus whatever the distractor removal buys in quality. **Measure:**
orientation turns and cost share, ctx at first edit, plan reads per session; quality by
blocking-finding rate, gate-red, rework, refuted, and — new — abstention/"cannot determine" verdicts
(Chroma: Claude fails by abstaining). **Cost:** S for the digest (the driver parses phases today);
M if the plan format needs a machine-readable settlements block. **Risks:** a constraint that lived
in another phase's prose; the digest going stale mid-phase (it is regenerated per dispatch, so only
within-session drift); "the plan is the queue" — the writer must still be able to edit later phases,
so the digest points at the file, it does not replace it.

**P3.2 Deliver known frictions at the point of use, not in the prefix. S.**
**Evidence:** hooks: `PostToolUse`/`PostToolBatch` `additionalContext` injects text "at the point
where the hook fired" (10 k-char cap), `PreToolUse` `updatedInput` rewrites a command; project
`.claude/settings.json` and plugin hooks run in `-p` sessions ([extracts/web-claude-code-docs-harness.md](extracts/web-claude-code-docs-harness.md) §4). AWM's measured requirement: small, abstract, verified items — unverified ones degrade, and over-following cost 3.3 F1. Our data: `close_out.py` is called 85 times in 145 writers' orientation phases (the W2 `list`→`--help` dance), the gate command is re-derived per session, line citations are re-derived per review.
**Effect:** 2–5 turns per session on the affected roles (≈ 3–8 % of their spend) and zero prefix
growth — the register-growth discipline is satisfied by construction. **Measure:** turns/session,
`close_out.py` calls per session, Bash error rate (2 % today). **Cost:** S — a plugin-shipped hook
file plus W2 (accept the report path). **Risks:** hooks that fire on every call add their own
tokens; a stale hint is worse than none (verify against the installed plugin version); confirm
hooks actually fire under `kc`'s `-p` launch before relying on them.

**P3.3 Sub-agent hygiene: a return contract, and Explore on Sonnet. S.**
**Evidence:** MAST's decisive-but-rare modes — information withholding (2.4, 0 % in successful
traces), derailment, premature termination, reasoning–action mismatch — and its recommendation
that a return carry the constraints the parent's next action depends on, verified-vs-asserted
marking, and an explicit accepted/contradicted disposition ([extracts/2503.13657](extracts/2503.13657-why-do-multi-agent-llm-systems-fail.md)); Kim: orchestrator synthesis cuts context omission 67 % vs concatenation; Anthropic: sub-agents write to the filesystem and pass references to avoid the telephone game; Context-Folding's scope judge found half of SWE sub-agents wandered off brief ([extracts/2510.11967](extracts/2510.11967-scaling-long-horizon-llm-agent-via-context-folding.md)). Our data: parents re-read ≤ 25 % of what their sub-agents read — the telephone-game *cost* is small; the unmeasured part is what the conclusion omitted. Explore runs on Opus by inheritance (116/148) for grep-and-locate work; Sonnet-priced it is $102 not $153.
**Effect:** Explore pin −2.1 % of spend; the contract's value is in quality, unmeasured. **Measure:**
sub-agent scope (did it answer the question asked — a cheap judge, per Context-Folding/Xia),
parent re-reads after dispatch, Explore cost. **Cost:** S — the dispatch template in the three
registers that use Explore; a project-level `Explore` agent definition with `model: sonnet`.
**Risks:** the pin touches the "no weaker model" settlement only if Explore is read as a judgment
role (it locates, it does not judge — the operator decides); a longer return contract costs parent
tokens on every call.

### P4 — We do not know what smaller reads cost in grounding

**P4.1 Instrument first: the context readout per run. S.**
**Evidence:** everything in §1 came from a tool that did not exist this morning; AI Agents That
Matter's sharpest warning is the mis-measured baseline (a 75.0 that reproduced at 89.6 exceeded
every agent's claimed gain — [extracts/2407.01502](extracts/2407.01502-ai-agents-that-matter.md)). Chroma names a new instrument: Claude's overload failure is abstention, so count "cannot determine"/non-attempt verdicts. Xia: a cheap judge on the final reasoning predicts correctness at F1 0.81–0.88 and classifies give-ups at 98.7 % agreement.
**Effect:** makes every P1–P3 candidate measurable per run. **Measure:** self-proving. **Cost:** S —
`context_profile.py` exists; wire a per-role line (turns, tools/turn, ctx_first, ctx_mean, ctx_max,
orientation turns, breaks) into `slice_cost.py --write-state` next to the I2 block, and an
abstention counter into the reviewer/consult result contract. **Risks:** none beyond register
growth (the counter is a field, not prose).

**P4.2 The A/B protocol for any smaller-or-curated read. S (rules), M (discipline).**
**Evidence:** Kapoor et al.: compare on the (quality, dollars) Pareto with task set, scoring, model
versions and dated prices held fixed; report mean ± range over ≥ 5 runs; hold out what you tuned on;
never equal-budget — dominance. Chroma/SWE-Pruner: agreement with the full read proves nothing when
errors are shared (Li Z.: 63 % identical predictions, errors included — [extracts/2407.16833](extracts/2407.16833-retrieval-augmented-generation-or-long-context-llms-a-comprehensive.md)).
**Protocol:** pair by project and phase size; one variable per trial; n ≥ 5 slices per arm; fixed
plugin version, model, effort, prices; primary quality instruments = blocking-finding rate, refuted
findings, gate-red, rework share, abstention verdicts, operator fix-nows; cost by the profile's
cache-adjusted dollars. **Kill signal:** any quality instrument outside the run-1 baseline range
(rework > 19 %, refuted > 0, gate-red up) on two consecutive slices, or cost not below baseline
cache-adjusted. **Early signal:** trajectory-length *variance* and wrong-file edits (Majgaonkar),
not length. **Risks:** 30 heterogeneous slices are thin; a slice-level A/B takes weeks — measure
at phase level where the change is per-phase (P3.1).

**P4.3 Shaped tool output via hooks — evaluate, do not assume. S to build, risky.**
**Evidence for:** SWE-agent's ACI ablations (100-line window > whole file by 5.3 pp; cap-and-refuse
search > paging; collapse observations older than 5 to a stub +3) — all GPT-4 Turbo, and the Claude
3 Opus sweep did not reproduce the optimum ([extracts/2405.15793](extracts/2405.15793-swe-agent-agent-computer-interfaces-enable-automated-software.md)); AgentDiet removed 40–60 % of input tokens at point-estimate parity, but its safety came from the guardrails (2-step delay, 500-token floor) and both operations are harness-owned ([extracts/2509.23586](extracts/2509.23586-reducing-cost-of-llm-agents-with-trajectory-reduction.md)). **Against:** SWE-Pruner — every untrained shaper lost with Claude; cut at line boundaries if at all. Our data: the agents already window (sed -n dominates); the volume is in the 14 % of Reads over 20 k chars and in `cat`.
**Effect:** unknown sign; upper bound ≈ the 49 % of Read volume in big reads ≈ 10 % of writer tool
volume. **Measure:** P4.2, with the Read-size distribution as the mechanism check. **Cost:** S — a
`PostToolUse` `updatedToolOutput` hook windowing Reads over N lines with a "call again with
offset/limit" note, or a `PreToolUse` `updatedInput` capping `cat`. **Risks:** the evidence says
this loses with Claude unless goal-conditioned; scroll-loops (SWE-agent) add turns, which is the
expensive unit here.

## 4. The briefing's questions, answered in brief

1. **Instrumentation (Q1).** A turn's context = fixed prefix (29 % of processed) + own prior output
   (17 %, thinking 7 %) + tool results (54 %; files ≈ 40 %, grep ≈ 5 %, git ≈ 4 %). Growth per role
   in §1. Minimal logging: per-session ctx trajectory, fixed share, tools/turn, orientation turns,
   break count/cost, last-quartile share, re-read ratio, Read-size quantiles — all now produced by
   `context_profile.py` from the existing transcripts; nothing new has to be logged. Observable
   today: the orientation-dominated trajectory (yes, 38 % of writer cost), expensive long tails
   (7 % of sessions = 25 % of spend), navigation-heavy reviewers (Bash 24 vs Read 2 per session);
   give-up/abstention and self-conditioning are *not* instrumented yet (P4.1).
2. **Cost model (Q2).** Per-turn cost ≈ ctx × 0.1 P + new × 1.25 P + out × P_out; with n turns and
   growth g, Σ ctx ≈ n·F + g·n²/2 — fixed-linear dominates up to ≈ 50 turns (F = 32 k, g ≈ 1 k),
   growth-quadratic beyond. A cut pays only where the dropped history exceeds the restart's
   re-orientation for enough later turns: on the real trajectories that is the doc-writer and the
   writer/test tail (§1). Docs: 5-min TTL from request start, refreshed free on every use; hierarchy
   tools → system → messages; 20-block lookback; a changed tool set or effort invalidates
   everything/messages; thinking kept on Opus 4.5+ and preserved in cache; Fable/Opus 4.8/5 can
   append a system instruction mid-conversation without invalidation. Computable from transcripts:
   all of the above. Must be trialled: any quality effect.
3. **Decomposition (Q3).** Fresh contexts preserve enough when the unit is self-contained and
   verified before hand-off (MemDocAgent, Anthropic harness), lose the constraints the parent
   needed (MAST 2.4) and off-brief drift (half of SWE sub-agents), and add 1.6–6.2× tokens with
   coordination overhead that goes net-negative above ≈ 45 % baseline (Kim). Mapped: orientation
   sub-agents for the code-writer — not supported (gate-verified high-baseline role; the digest
   P3.1 is the cheaper form); per-surface doc sub-agents + consistency pass — supported (P2.1);
   reviewer evidence-gathering sub-agents — predicted to pay the tax, and the reviewer's own re-read
   is a feature (Cognition); the consult — share the full context (Cognition's 80/20), don't curate.
   Returned-conclusion contract — supported as hygiene (P3.3); telephone-game cost measured small.
4. **Curation (Q4).** Shaped tool output: supported only where goal-conditioned or cap-and-refuse;
   untrained compressors lose with Claude (P4.3). Per-repository orientation map: supported as a
   *derived*, constant-size, phase-scoped digest built by the driver (P3.1); not as an authored
   per-repo map (PEEK tested no mutating context; Aider's is recomputed per request). Per-phase plan
   digest: yes (P3.1). Expiry of old tool results: unreachable; bounded value. Retrieval against
   whole artefacts: LC beats RAG 4–13 pp on QA, Self-Route's cost curve goes above a full read past a
   small excerpt, chunk retrieval lags summary retrieval (Li Z., Li X.) — our agents already *are*
   the retriever (grep + sed windows); no case for a retrieval layer. Must still be read in full: the
   diff under review and the acceptance criteria (settled, and Cognition agrees).
5. **Session shape (Q5).** S1 predicts that a 100–200-turn loop degrades through what its history
   contains (self-conditioning, distractors), gradually, no cliff; S3 says the hand-off must be a
   consolidated restatement (Laban) carrying settlements and evidence in machine-readable form
   (ACON's guideline), discovered by comparing full-succeeds/cut-fails pairs (ACON's method, prompt-only,
   < $2 a domain — usable on our own transcripts). Compaction costs file:line specifics
   (summarisation −9 vs folding −6 vs truncation −19). The doc-writer: split (P2.1) beats compact
   (P2.2); MemDocAgent is not the counter-case it was filed as.
6. **Measuring grounding loss (Q6).** Fastest detectors: gate-red and refuted findings (per phase);
   then rework share; abstention verdicts as the Claude-specific early signal; trajectory variance
   not length. Compare on the Pareto, n ≥ 5 per arm, fixed versions and prices (P4.2).
7. **Cross-cutting (Q7).** No conflict with the settled decisions except P3.3's Explore pin (operator
   call) and P1.2's per-project settings file (portability). Order: P4.1 before anything; then
   P1.2 + P3.2 (free, no quality exposure); then P3.1 (A/B at phase level); then P2.1; P1.1 as a
   register A/B; P2.2 and P4.3 only with the protocol.

## 5. Ranking by expected value per unit of effort

| # | Candidate | Reach (share of spend) | Quality exposure | Cost | Verdict |
|---|-----------|------------------------|------------------|------|---------|
| 1 | P4.1 context readout per run | — (enables all) | none | S | do first |
| 2 | P1.2 trim the fixed prefix | ≈ 4 % | none | S | do |
| 3 | P3.2 frictions via hooks + W2 | ≈ 2–4 % | low | S | do, verify hooks fire under `-p` |
| 4 | P3.1 phase-scoped orientation digest | ≈ 5 % + quality upside | medium, measurable per phase | S–M | A/B at phase level |
| 5 | P2.1 bounded doc phase + consistency pass | ≈ 3–4 % + bulk-distraction upside | medium | M | A/B on two slices |
| 6 | P1.1 batched reads | ≈ 2–3 % | low–medium | S | register A/B |
| 7 | P3.3 sub-agent contract; Explore on Sonnet | ≈ 2 % + hygiene | low | S | operator call |
| 8 | P2.2 auto-compact window for the tail | ≈ 1–2 % | high | S/M | trial on doc/test only if P2.1 is not taken |
| 9 | P4.3 shaped tool output via hooks | ≤ 5 % | high, likely negative per SWE-Pruner | S | protocol only |

Summed, the low-exposure items (1–3, 6–7) reach ≈ 12–15 % of spend; the two measurable A/Bs (4–5)
another ≈ 8–10 % with the only quality *upside* in the set. Nothing here is a 50 % lever: the
remaining spend is the price of reading code to change it, and the reading supports paying it.

## 6. What is deliberately not in this memo

Compaction or summarisation of writer/reviewer history (cited losses, unreachable API side, and
the real trajectories show ≤ 8 % even if free); a retrieval layer over plans or diffs; an authored
per-repository map with a staleness rule (the derived digest replaces it); effort or model changes
for writers and reviewers (settled); turn or token caps as early stops; the 1-hour cache; parallel
writer sub-agents (Cognition, Kim). Two measurements are worth taking before any of §3 is decided:
the abstention-verdict count on the 27 slices (a grep over review files, one hour), and a
full-vs-digest pair on two already-completed phases (P3.1's ACON-style failure-pair check, cheap,
offline — rerun the phase with the digest and diff the verdicts).
