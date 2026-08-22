---
source: web-claude-code-docs-sub-agents.md
paper: Create custom subagents — Claude Code documentation (vendor docs, no authors/date) — https://code.claude.com/docs/en/sub-agents (mirror fetched 2026-08-22); plus https://code.claude.com/docs/en/context-window and https://code.claude.com/docs/en/prompt-caching (WebFetched 2026-08-22)
read: full (sub-agents page in full; context-window page in full incl. the interactive timeline's data; prompt-caching page in full)
extracted_by: Claude Opus 5 (1M), 2026-08-22
---

Vendor documentation, not research. Everything below is what the docs state; nothing is inferred except where marked
"(not stated)".

## Core results

**1. A non-fork sub-agent starts fresh and isolated, but not empty.** "Each subagent starts with a fresh, isolated
context window. It doesn't see your conversation history, the skills you've already invoked, or the files Claude has
already read. Claude composes a delegation message that summarizes the task, and the subagent works from there."
(§ Manage subagent context → What loads at startup.) Its initial context is an enumerated list: **system prompt** —
"the agent's own prompt plus environment details that Claude Code appends, not the full Claude Code system prompt";
**task message** — "the delegation prompt Claude writes when it hands off the work"; **CLAUDE.md files** — "every level
of the CLAUDE.md hierarchy the main conversation loads, including `~/.claude/CLAUDE.md`, project rules,
`CLAUDE.local.md`, and managed policy files"; **git status** — "a snapshot taken at the start of the parent session.
Absent … when `includeGitInstructions` is `false`"; **preloaded skills** — "full content of any skill named in the
agent's `skills` field"; and a **sibling roster** (only with `SendMessage` in tools). "Explore and Plan are the only
subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents
skip them." Three things never reach a non-fork sub-agent: output style, auto memory ("the main conversation's auto
memory isn't loaded"), and the parent's window size ("a subagent's context window is sized by its own model"). Tools:
"Subagents inherit the built-in tools and MCP tools available in the main conversation, narrowed by two filters" — one
strips a fixed list (`AskUserQuestion`, `EnterPlanMode`, `Workflow`, `Agent` at the depth limit, …), the second cuts
*background* sub-agents to ~19 named built-ins (Read/Grep/Glob/Bash/Edit/Write/WebFetch/Skill/…) plus every MCP tool.

**2. Only the final text returns to the parent.** "Only the subagent's final text response comes back to your context,
plus a small metadata trailer with token counts and duration." The transcript is not visible to the parent ("You don't
see the subagent's individual file reads"); it is written to
`~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`. With nesting, "Only the top-level
subagent's summary returns to you." Claude Code scans the final report before Claude reads it (backslash insertion,
`[harness: …]` marker line); "The scan never removes or rewords anything."

**3. Cost, with the doc's own (representative) numbers.** The context-window timeline prices one research delegation as
**80 tokens to spawn + 420 returned** in the parent, against **3,790 of startup inside the sub-agent** (system prompt
900; its own copy of project CLAUDE.md 1,800 — the same 1,800 the parent paid; MCP tools + skills 970; task prompt 120)
plus 6,100 of file reads there — none of which the parent pays: "The subagent read 6,100 tokens of files. You got a
420-token result. That's the context savings." The main session's own startup is priced at 7,850 (system prompt 4,200;
project CLAUDE.md 1,800; auto memory 680; skill descriptions 450; `~/.claude/CLAUDE.md` 320; environment 280; MCP tool
*names* 120 — schema deferral is the default; `ENABLE_TOOL_SEARCH=false` loads everything).

**4. Cache: a sub-agent pays a full cold prefix; a fork does not.** (prompt-caching § Subagents and the cache) "Its
first request doesn't read the parent's cache, because the two prefixes differ, and it warms a cache of its own across
its turns. Subagents use the five-minute TTL even on a subscription, since the automatic one-hour TTL applies to the
main conversation." And: "The parent's cache is unaffected. From the parent's side, the subagent's call and result
append to the conversation, leaving the parent's prefix intact." A fork instead "inherits the parent's system prompt,
tools, and conversation history exactly, so its first request reads the parent's cache… This makes forking cheaper than
spawning a fresh subagent." Fork mode is "off by default in non-interactive mode with `-p` and in the Agent SDK."

**5. Cache scope across *sessions* (prompt-caching § Cache scope).** "In Claude Code, the cache is effectively scoped to
one machine and directory. The system prompt embeds the working directory, platform, shell, OS version, and auto memory
paths… That includes worktrees of the same repository." Then, decisively for a script-driven pipeline: "Sessions you run
in parallel in the same directory build matching prefixes and read each other's cache. **Sequential sessions share the
prefix only when the git status snapshot at startup matches, since the system prompt also captures branch and recent
commits.**" Model and effort level are each part of the cache key. For fan-out: "Claude Code briefly holds all but the
first so their first requests can read the prefix the first agent cached."

**6. Nesting and parallelism limits.** "By default, a subagent can spawn subagents of its own, up to three layers below
the main conversation" (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`; `1` turns nesting off). Stated rationale: "Nested
subagents suit a delegated task that itself splits into parallel subtasks, such as a reviewer subagent that dispatches a
verifier per finding, so the intermediate output never reaches your main conversation." Concurrency
caps at 20 running sub-agents (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`).

**7. Per-agent model, effort, tools, turns.** Frontmatter: `model` (alias, full ID, or `inherit`; "Defaults to
`inherit`"), `effort` ("Overrides the session effort level… `low`, `medium`, `high`, `xhigh`, `max`"), `tools` /
`disallowedTools`, `maxTurns` ("Maximum number of agentic turns before the subagent stops"), `skills`, `mcpServers`,
`memory`, `permissionMode`, `hooks`, `isolation: worktree`, `background`. Model resolution:
`CLAUDE_CODE_SUBAGENT_MODEL` → per-invocation `model` → frontmatter → main conversation. "As of v2.1.198, subagents also
inherit the main conversation's extended thinking configuration… There is no per-subagent thinking setting."
Built-in **Explore** changed: "As of v2.1.198, Explore inherits the main conversation's model instead of always running
on Haiku," capped at Opus on the Claude API — and "A user or project subagent named `Explore` overrides the built-in
and keeps its own `model` field, so define one with `model: haiku` to keep exploration on a lower-cost model."

**8. Resumability and persistence.** "Each subagent invocation creates a new instance rather than continuing an earlier
one." Resuming (`SendMessage` to the agent ID/name) does continue it: "Resumed subagents retain their full conversation
history, including all previous tool calls, results, and reasoning." But "The built-in Explore and Plan agents are
one-shot and return no agent ID, so they can't be resumed." Transcripts survive parent compaction and session restart;
deleted after `cleanupPeriodDays` (30 default). Cross-*conversation* carry-over exists only via `memory:` — a persistent
directory whose `MEMORY.md` ("the first 200 lines or 25KB… whichever comes first") is injected into the sub-agent's
system prompt; part of auto memory, disabled with it.

**9. Sub-agents auto-compact.** "Subagents support automatic compaction using the same logic as the main conversation.
Compaction triggers under the same conditions, and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` applies to subagents as well."
Compaction is logged as `compact_boundary` with `preTokens` (example shown: `167189`).

**10. When the docs say to use one — and not to.** Sub-agent when "The task produces verbose output you don't need in
your main context", to enforce tool restrictions, or when "The work is self-contained and can return a summary". **Main
conversation** when the task "needs frequent back-and-forth"; when "Multiple phases share significant context, such as
planning, implementation, and testing"; for "a quick, targeted change"; and when "Latency matters. A subagent that isn't
a fork starts fresh and may need time to gather context". Parallel research "works best when the research paths don't
depend on each other", with the warning: "Running many subagents that each return detailed results can consume
significant context." Nothing says writes must be single-threaded; the write-side control offered is `isolation:
worktree` ("an isolated copy of the repository branched by default from your default branch rather than the parent
session's `HEAD`").

## Method and setting (what this source is)

Product documentation for Claude Code, versioned by build number (cited features span v2.1.153–v2.1.238). No experiment,
no benchmark, no measurement: the only quantities are the context-window timeline's, and that page states "The
visualization uses representative numbers" and "representative token counts" — illustrative, not observed. Nothing is
trained; everything is configuration. It describes the harness we actually run, headless `-p` sessions and the Agent SDK
included (called out separately for fork mode and `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1`).

## Relevance to P1–P4

**P1 (context is the cost).** One fact we may not have priced: sequential sessions in the same directory share the
cached prefix **only if the git status snapshot matches** — and our loop commits between sessions. If that holds for our
runs, much of each session's ≈ 33k prefix is being *written* at 1.25×, not read at 0.1×, ≈ 30 times per slice. Effort
and model are also cache keys, which costs us nothing (we fix both per session) but independently confirms the settled
"no effort tiering" ruling.

**P2 (sessions grow; the longest dominate).** Two levers, documented not measured: `maxTurns` caps agentic turns per
agent (the doc-writer's 192 is the target), and sub-agents auto-compact under the same rules as a main session with
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` — so our "no compaction" property follows from window size and thresholds, not from
sub-agents being exempt. The docs do not quantify what compaction costs in fidelity.

**P3 (every session rebuilds the same picture).** Three mechanisms bear on it, all unmeasured here: `skills:` preloads
full skill content at startup ("The full content of each listed skill is injected"), so a role register need not be
discovered by tool calls; `memory:` gives an agent a persistent `MEMORY.md` across conversations — the documented home
for exactly our "re-learning one CLI's argument shape"; and inline `mcpServers` keeps a server's tool descriptions out
of the parent entirely. Against this, the docs confirm duplication we already pay: a sub-agent loads its **own copy** of
the whole CLAUDE.md hierarchy (1,800 tokens in the example), and only Explore/Plan skip it, with no setting to change
which agents do.

**P4 (what smaller reads cost in grounding).** No evidence at all — the page asserts the saving ("That's the context
savings") with no quality measure. Its one grounding caution: "The main conversation reads Explore and Plan results with
full CLAUDE.md context, so most rules don't need to reach the subagent itself. If a rule must, such as 'ignore the
`vendor/` directory,' restate it in the prompt you give Claude when delegating."

## Interventions this paper supports

- **Check whether our ≈30 sequential sessions miss each other's cache** (§ Cache scope). If the git snapshot sits in the
  prefix and changes on every commit, each session pays a 1.25× write on ~33k where it could pay a 0.1× read. Test:
  `cache_creation_input_tokens` on each session's first turn. Candidate lever: `includeGitInstructions: false` — but the
  docs name it only for a *sub-agent's* startup context; its effect on the main-session prefix is **not stated**. Loses:
  branch and recent commits no longer free to the agent.
- **Run same-prefix sessions in parallel where the DAG allows** — "Sessions you run in parallel in the same directory
  build matching prefixes and read each other's cache", and the workflow fan-out deliberately holds all but the first so
  the rest read the first's prefix. Loses: nothing stated; requires the same directory, not worktrees.
- **Pin `Explore` to Haiku with a project agent** if our orientation sub-agents are now inheriting Opus (v2.1.198
  change) — the doc names this override explicitly. Loses: search quality on hard lookups. (Explore is neither writer
  nor reviewer, so the settled model rule does not bar it.)
- **Move re-learned frictions into `memory:`** on the roles that keep re-deriving them (CLI argument shapes,
  line-citation method). Loses: capped at 200 lines/25KB, injected into every run of that agent whether needed or not,
  and dead wherever auto memory is off.
- **Preload the role register with `skills:`** instead of having the agent read it — same tokens, but deterministic and
  at startup rather than after tool turns. Loses: no conditional loading; paid even when unused.
- **Use nesting for fan-out with a return contract** — "Only the top-level subagent's summary returns to you" supports a
  reviewer that dispatches a verifier per finding. Loses: the parent cannot inspect the evidence; only final text plus a
  metadata trailer arrives.
- **Cap the doc-writer with `maxTurns`**; and **prefer a fork over a fresh sub-agent when the task needs the parent's
  picture** ("its first request reads the parent's cache… cheaper than spawning a fresh subagent"). Loses: the docs say
  nothing about what a `maxTurns` stop returns; a fork "drops the input isolation that subagents otherwise provide", and
  fork mode is off by default under `-p`/SDK (`CLAUDE_CODE_FORK_SUBAGENT=1`).

## Applicability caveats

- **No evidence, by construction.** Every number in the context-window walkthrough is labelled representative. There is
  no measurement of quality, latency, or cost anywhere on these pages, and no comparison of a delegated against a
  non-delegated run.
- **Our agents are not sub-agents.** Our ≈30 roles are separate headless sessions launched by a script; the sub-agent
  rules (isolation, tool filters, return contract, depth and concurrency limits) apply only *inside* those sessions —
  i.e. to the Explore sub-agents used by plan-writer, plan-reviewer and doc-writer. The cache-scope facts, by contrast,
  apply to our sessions directly.
- **Version drift is fast.** Cited behaviours change across single patch versions (Explore's model at v2.1.198; nesting
  depth 5 → 1 → 3 across v2.1.172–219). Any lever from here must be checked against the installed build.
- **Several claims are one sentence with no detail**: what the "metadata trailer" contains, how the delegation message
  is composed, what a `maxTurns` stop returns, and whether `includeGitInstructions` affects the main-session prefix.

## Briefing check

The briefing lists this only as "Claude Code sub-agents … (and the context-window visualisation linked there)" under S8,
"Practitioner references (not research; weight independently)", with the vendor-doc rule "state what they say, do not
extrapolate". That framing is right and, if anything, understated: the page is the authority on what a sub-agent call
contains and returns, and the *prompt-caching* page it links — not the visualisation — carries the fact with real force
for P1, that **sequential sessions share a cached prefix only when the git status snapshot matches**. The visualisation
supports no cost claim of its own: "6,100 tokens read → 420 returned" is labelled representative and must not be cited
as evidence for sub-agent economics. Nothing in the note is wrong. Supporting a premise stated elsewhere in the
briefing: S4's "sub-agents everywhere is not supported as framed" is echoed in the vendor's own words — the docs steer
*away* from sub-agents when "Multiple phases share significant context, such as planning, implementation, and testing"
and when latency matters.
