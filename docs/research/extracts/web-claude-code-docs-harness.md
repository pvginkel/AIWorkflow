---
source: web-claude-code-docs-{context-window,prompt-caching,costs,model-config,headless,memory,hooks,agent-sdk-cost-tracking,agent-sdk-agent-loop}.md
paper: Claude Code documentation — the harness pages on context, caching, cost, models, headless, memory, hooks, and the SDK loop — Anthropic, mirrors fetched 2026-08-22 — https://code.claude.com/docs/en/
read: full (context-window, prompt-caching, costs, model-config, headless, memory, agent-sdk-cost-tracking, agent-sdk-agent-loop); partial (hooks: lifecycle, handler fields, hooks-in-skills-and-agents, input/output + exit codes + JSON output + decision control, SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PostToolBatch, SubagentStart/Stop, PreCompact/PostCompact, async hooks)
extracted_by: claude-opus-5[1m], 2026-08-22
---

Vendor documentation, not a study. Everything below is what the docs assert; illustrative numbers are
flagged as such. Where a doc is silent I say **not stated**.

## 1. The fixed prefix: what loads, what it costs, what can be trimmed

**What loads before the first prompt** (context-window, "What the timeline shows"): system prompt,
auto memory, environment info, MCP tool *names*, skill descriptions, user CLAUDE.md, project
CLAUDE.md. The page's simulated token counts are **explicitly illustrative** — the widget's own
tooltip reads "Token counts are illustrative. Actual values vary with your CLAUDE.md size, MCP
servers, and file lengths." With that caveat: system prompt 4,200; auto memory 680; environment info
280; MCP tools (deferred) 120; skill descriptions 450; `~/.claude/CLAUDE.md` 320; project CLAUDE.md
1,800.

- **Environment info**: "Working directory, platform, shell, OS version, and whether this is a git
  repo. Git branch, status, and recent commits load as a separate block at the very end of the
  system prompt."
- **MCP**: "By default, full schemas stay deferred and Claude loads specific ones on demand via tool
  search… Set `ENABLE_TOOL_SEARCH=auto` to load schemas upfront when they fit within 10% of the
  context window, or `ENABLE_TOOL_SEARCH=false` to load everything."
- **Skills**: one-line descriptions only; "Full skill content loads only when Claude actually uses
  one. Skills with `disable-model-invocation: true` are not in this list. They stay completely out
  of context until you invoke them with `/name`."
- **CLAUDE.md**: loaded from cwd "and every directory above it", concatenated root-down; subdirectory
  CLAUDE.md files "are included when Claude reads files in those subdirectories"; `@path` imports are
  "expanded and loaded into context at launch" (max depth four), so "Splitting into `@path` imports
  helps organization but doesn't reduce context". Cap: "Claude Code loads a CLAUDE.md file of up to
  4 MiB in full and skips a larger file"; recommended target "under 200 lines". Block-level HTML
  comments are stripped before injection.
- **Auto memory**: "The first 200 lines of `MEMORY.md`, or the first 25KB, whichever comes first, are
  loaded at the start of every conversation." Topic files are **not** loaded at startup.
- **Agent (subagent) listing**: **not stated** — no page in this set attributes a startup context
  cost to the registered-agent list. Tool definitions generally: "Built-in tool schemas load every
  request" and "Every tool definition takes context space" (agent-loop).

**Trim levers, as documented**
- `--bare` (headless): "reduce startup time by skipping auto-discovery of hooks, skills, custom
  commands, subagents, plugins, MCP servers, auto memory, and CLAUDE.md… `--bare` is the recommended
  mode for scripted and SDK calls, and will become the default for `-p` in a future release." In bare
  mode Claude has "the Bash, file read, and file edit tools"; context is re-added via
  `--append-system-prompt(-file)`, `--settings`, `--mcp-config`, `--agents`, `--plugin-dir`.
- `--safe-mode` (model-config) "disables customizations such as CLAUDE.md, skills, MCP servers, and
  hooks."
- Per-agent tool restriction: "Use the `tools` field on `AgentDefinition` to scope subagents to the
  minimum set they need" (agent-loop).
- Deny rules: "Adding a bare tool name like `Bash` or `WebFetch` as a deny rule removes that tool
  from Claude's context entirely" (prompt-caching).
- `claudeMdExcludes` (glob, any settings layer) skips ancestor CLAUDE.md files; managed-policy
  CLAUDE.md cannot be excluded. `--setting-sources` can exclude `project` (skips `.claude/rules/`)
  and `local`.
- Costs page: "Prefer CLI tools when available… they don't add any per-tool listing"; "Disable unused
  servers"; "Move instructions from CLAUDE.md to skills"; `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

## 2. Auto-compact

- **Default threshold**: "If you don't set an auto-compact window, Claude Code compacts when the
  conversation reaches the model's context limit", with exceptions: cloud sessions compact "as the
  conversation approaches the model's limit"; Sonnet/Opus 4.6 without extended context, and Opus 4.8
  and Opus 5 running with a 200K window, compact at 200K; Sonnet 5 auto-compacts "at about 967K
  tokens by default". It is a token count, not a documented percentage.
- **Configurable**: `/autocompact 500k` (saves `autoCompactWindow`), the `--autocompact` launch flag,
  or `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, which "takes precedence over the command, the flag, and the
  setting". Accepted range 100K–1M, "capped at the model's context window". `DISABLE_COMPACT`
  "disables all compaction" (named in the gateway-window section).
- **In headless**: not stated for `claude -p` in so many words; the SDK page states the behaviour for
  the same loop — "When the context window approaches its limit, the SDK automatically compacts the
  conversation… The SDK emits a message with `type: "system"` and `subtype: "compact_boundary"`."
- **What `/compact` costs**: "Claude Code sends a separate request with the same system prompt, tools,
  and history as your conversation, plus a summarization instruction appended as a final user
  message. While the cache is warm, that request reads your prefix from the cache, so a mid-session
  `/compact` costs a fraction of what the context size suggests and spends most of its time
  generating the summary." Cold (past the TTL) "the summarization request reprocesses the full
  history as uncached input". After compaction the system-prompt layer is reused and project context
  is reloaded from disk, "which cache-hits only if CLAUDE.md and memory are unchanged since the
  session started".
- **What survives** (table): system prompt/output style unchanged; project-root CLAUDE.md, unscoped
  rules and auto memory re-injected from disk; `paths:` rules and nested CLAUDE.md "Lost until a
  matching file is read again"; invoked skill bodies re-injected "capped at 5,000 tokens per skill
  and 25,000 tokens total; oldest dropped first"; the skill *listing* is not re-injected.
- **PreCompact hooks**: matcher `manual`/`auto`; input carries `trigger` and `custom_instructions`;
  "Exit with code 2 to block compaction… You can also block by returning JSON with
  `"decision": "block"`." Blocking a proactive auto-compact means "Claude Code skips it and the
  conversation continues uncompacted"; blocking one triggered to recover from a context-limit error
  means "the underlying error surfaces and the current request fails". `systemMessage` and `continue`
  are discarded. Documented use: "Archive full transcript before summarizing". `PostCompact` gets
  `compact_summary` and has no decision control.
- **Is 1M the default?** Only per model/plan: "On the Anthropic API, Fable 5, Sonnet 5, and Opus 4.7
  and later always run with the 1M window." On Max/Team/Enterprise "Opus is automatically upgraded to
  1M context with no additional configuration"; Pro needs usage credits; API/pay-as-you-go has "Full
  access". Otherwise select `opus[1m]`. "The 1M context window uses standard model pricing with no
  premium for tokens beyond 200K." `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` holds sessions to 200K.

## 3. API-side context editing (clear_tool_uses / clear_thinking / server-side compaction)

**Not stated.** None of the nine pages mentions context editing, `clear_tool_uses`, `clear_thinking`,
or server-side compaction, and none exposes a Claude Code setting, env var, or flag for them. The
only server-side mechanism these pages describe is prompt caching ("Caching happens server-side, in
whichever infrastructure serves your model"). Compaction as documented here is entirely client-side:
Claude Code "sends a separate request… plus a summarization instruction appended as a final user
message."

## 4. Hooks as a tool-output lever

Yes, for both directions, and the docs make the shaping explicit: "For redaction or transformation
use cases, intercept at `PreToolUse` for outbound tool inputs and `PostToolUse` for inbound tool
results."

**PostToolUse can replace a result.** Fields (PostToolUse decision control):
- `updatedToolOutput` — "Replaces the tool's output with the provided value before it is sent to
  Claude. The value must match the tool's output shape." Warning: "`updatedToolOutput` only changes
  what Claude sees. The tool has already run… The replacement value must match the tool's output
  shape… For built-in tools, a value that doesn't match the tool's output schema is ignored and the
  original output is used. MCP tool output is passed through without schema validation. Stripping
  error details that Claude needs can cause it to proceed on a false assumption." Example given
  replaces `Bash` output with `{stdout, stderr, interrupted, isImage}`.
- `decision: "block"` — "adds the `reason` next to the tool result. Claude still sees the original
  output; to replace it, use `updatedToolOutput`."
- `additionalContext` — "passes a string from your hook into Claude's context window. Claude Code
  wraps the string in a system reminder and inserts it into the conversation at the point where the
  hook fired." For PreToolUse/PostToolUse/PostToolUseFailure/PostToolBatch it lands "next to the tool
  result". Capped at 10,000 characters; beyond that "Claude Code writes the full text to a file in
  the session directory and passes Claude the file path with a short preview instead."
- `classifierContext` — auto-mode classifier only, not Claude.

**PreToolUse can rewrite the input.** `updatedInput` "Modifies the tool's input parameters before
execution. Replaces the entire input object, so include unchanged fields alongside modified ones.
Combine with `"allow"` to auto-approve". The costs page ships exactly the head/limit example: a hook
matching `Bash` rewrites `npm test|pytest|go test` to `$cmd 2>&1 | grep -A 5 -E '(FAIL|ERROR|error:)'
| head -100` and returns `permissionDecision: "allow"` with `updatedInput.command`; `claude --debug`
prints `modified tool input keys: [command]`. Framing on the same page: "a hook can grep for `ERROR`
and return only matching lines, reducing context from tens of thousands of tokens to hundreds."

**Blocking with a reason.** `permissionDecision: "deny"` + `permissionDecisionReason`, where for
`"deny"` the reason is "shown to Claude"; exit 2 "routes the same way as `"deny"`: Claude sees the
stderr message as the denial reason". Precedence across hooks: `deny > defer > ask > allow`.

**Other events.** `UserPromptSubmit` "can't replace the prompt; it only injects `additionalContext`
alongside it" and can block (erasing the prompt). `PostToolBatch` "fires exactly once with the full
batch… before Claude Code sends the next request to the model", accepts `additionalContext` "injected
once before the next model call", and can stop the loop. `SubagentStart` accepts `additionalContext`
"added to the subagent's context at the start of its conversation, before its first prompt".
`SessionStart` accepts `additionalContext`, plus `initialUserMessage`, which "Applies in
non-interactive mode with the `-p` flag, where it becomes the first turn".

**Cost of hooks themselves**: "Hooks run in your application process, not inside the agent's context
window, so they don't consume context" (agent-loop) — but what they return does, and "it enters
context without truncation" up to the 10,000-character cap.

**Where hooks can be declared**: settings files, plugins, and "directly in skills and subagents using
frontmatter… Subagent hooks: Claude Code runs them only while that subagent is running and removes
them when it finishes." Gotcha for our loop: "Frontmatter hooks in a project subagent run only after
you accept the workspace trust dialog… A `-p` session doesn't count as accepting it", whereas a `-p`
session *does* run "the hooks in a project's `.claude/settings.json`… even in a folder you've never
trusted". Hooks also support `async: true` (results delivered "on the next conversation turn"; in
`-p` "Claude Code kills any async hook still running at teardown") and an `if` permission-rule filter.

## 5. Prompt caching in Claude Code

- **Structure**: three layers ordered least-changing first — system prompt (core instructions, tool
  definitions, output style), project context (CLAUDE.md, auto memory, unscoped rules), conversation.
  "The match is exact, so a change anywhere in the prefix recomputes everything after it. There is no
  per-file or per-segment caching."
- **Model and effort are part of the cache key**: "each model has its own cache… Switching models
  recomputes the entire request even when the content is identical"; "The cache is keyed by effort
  level as well as model."
- **Breaks the cache**: model switch, effort change, fast mode, MCP server connect/disconnect *when
  tools are loaded into the prefix* (deferred tools "only append new content"), enabling/disabling a
  plugin that supplies MCP servers, a bare-tool-name deny rule, compaction, a Claude Code upgrade
  ("Resuming a session after an upgrade reprocesses the entire conversation history with no cache
  hits").
- **Keeps the cache**: editing repo files, editing CLAUDE.md mid-session ("does not invalidate the
  cache, but the edit also doesn't apply… The new content loads on the next `/clear`, `/compact`, or
  restart"), output-style change, permission-mode change, invoking skills/commands, `/recap`,
  `/rewind`, spawning a subagent.
- **Cache scope — decisive for a fleet**: "In Claude Code, the cache is effectively scoped to one
  machine and directory. The system prompt embeds the working directory, platform, shell, OS version,
  and auto memory paths… **Sessions you run in parallel in the same directory build matching prefixes
  and read each other's cache. Sequential sessions share the prefix only when the git status snapshot
  at startup matches, since the system prompt also captures branch and recent commits.**" For fleets
  the page points at "improve prompt caching across users and machines to suppress the per-machine
  sections of the system prompt" (that page is not in this set).
- **TTL**: 5-minute default on API keys/third-party; 1 hour automatic on a Claude subscription;
  `ENABLE_PROMPT_CACHING_1H=1` opts in elsewhere; **`FORCE_PROMPT_CACHING_5M=1` "force[s] the
  five-minute TTL regardless of authentication"**, and the documented purpose is "when you're
  debugging cache behavior, comparing the two TTLs, or overriding an `ENABLE_PROMPT_CACHING_1H` set in
  managed settings."
- **Subagents and the cache**: "A subagent starts its own conversation with its own system prompt and
  tool set… Its first request doesn't read the parent's cache, because the two prefixes differ, and it
  warms a cache of its own across its turns. Subagents use the five-minute TTL even on a
  subscription." A **fork** "inherits the parent's system prompt, tools, and conversation history
  exactly, so its first request reads the parent's cache", and in a workflow fan-out "Claude Code
  briefly holds all but the first so their first requests can read the prefix the first agent cached."
- **Reading the hit rate**: `cache_creation_input_tokens` (billed at write rate) and
  `cache_read_input_tokens` ("billed at roughly 10% of the standard input rate"), readable live from
  a statusline script's `current_usage`, or via OpenTelemetry "per user and session". "A high
  read-to-creation ratio means caching is working well." `/usage` flags behaviours (long context,
  cache misses) at ≥10% of recent usage.
- Disable switches exist per model family (`DISABLE_PROMPT_CACHING[_OPUS|_SONNET|_HAIKU|_FABLE]`).

## 6. Headless / SDK

- **Resume**: `--continue` (most recent, skips background sessions) or `--resume <session-id>`;
  capture the id from `--output-format json | jq -r '.session_id'`. Since v2.1.223 the resume can run
  from a different directory. `--resume` restores the permission mode active at defer time.
- **Caps**: `max_turns`/`maxTurns` "counts tool-use turns only", default **No limit**;
  `max_budget_usd`/`maxBudgetUsd`, default **No limit**; hitting either yields result subtypes
  `error_max_turns` / `error_max_budget_usd`. "The budget cap covers subagents: their spend counts
  toward the total. Once spend reaches the cap, spawning another subagent fails with `Budget limit
  reached`." These are documented as SDK options; equivalent CLI flags are **not stated** on the
  headless page.
- **Structured output**: `--output-format text|json|stream-json`; `--json-schema` with
  `--output-format json` puts the validated object in `structured_output`; failure mode
  `error_max_structured_output_retries`.
- **Usage reporting**: "With `--output-format json`, the response payload includes `total_cost_usd`
  and a per-model cost breakdown… Both figures are client-side estimates." Cache tiers appear as
  `cache_creation_input_tokens` / `cache_read_input_tokens` in `usage`, and as
  `cacheReadInputTokens` / `cacheCreationInputTokens` per model in `modelUsage`.
- **Subagents in usage** — the decisive table: `usage` "Excluded. Counts only the top-level agent
  loop, so tokens consumed inside subagents are not added"; `total_cost_usd` and
  `modelUsage`/`model_usage` "Included". Guidance: "Use `modelUsage`… for whole-tree token
  accounting; the `usage` field undercounts as soon as nesting occurs." Also: per-step
  `output_tokens` on assistant messages "is a placeholder" — read output tokens from the result.
- **Subagent transcripts in the stream**: only `tool_use`/`tool_result` by default; pass
  `--forward-subagent-text` or `CLAUDE_CODE_FORWARD_SUBAGENT_TEXT` "to also emit subagent text and
  thinking blocks, so you can reconstruct each subagent's transcript"; `parent_tool_use_id` ties them
  to the spawning call at every nesting depth.
- **Effort in `-p`**: "A level set with `/effort` in non-interactive mode… applies to the current
  session only… so pass `--effort` at launch instead." Effort levels on Opus 5: `low, medium, high,
  xhigh, max`; default `high`; "The effort scale is calibrated per model." `max` is documented as
  "prone to overthinking. Test before adopting broadly."
- Lifecycle: SIGTERM → exit 143, turn left unfinished; SIGINT ends the turn. Background Bash is killed
  ~5s after the result; background subagents are waited on, capped at ten minutes
  (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`).

## 7. Memory: what would carry a per-project "workflow memory" for free vs on demand

**Free in every session** (i.e. in the cached prefix, paid once per session as cache write and then
at ~10% on every turn): project `./CLAUDE.md` or `./.claude/CLAUDE.md`; any `.claude/rules/*.md`
*without* `paths:` frontmatter ("loaded at launch with the same priority as `.claude/CLAUDE.md`");
`@path` imports of either; `~/.claude/CLAUDE.md`; managed-policy CLAUDE.md (cannot be excluded); the
auto-memory `MEMORY.md` index (first 200 lines / 25KB).

**On demand**: skills (descriptions only at startup; body on invoke; `disable-model-invocation: true`
removes even the description); path-scoped rules, which "trigger when Claude reads files matching the
pattern, not on every tool use"; nested CLAUDE.md in subdirectories; auto-memory topic files, which
"Claude reads… on demand using its standard file tools".

**Subagents**: "The main conversation's auto memory isn't loaded into subagents; the exception is a
fork." But "The subagent loads CLAUDE.md too. Same file, same content, but it counts against the
subagent's context, not yours. The built-in Explore and Plan agents skip this for a smaller context."
A subagent can have its own memory directory via the `memory:` frontmatter field.

Debugging aid: the `InstructionsLoaded` hook fires "When a CLAUDE.md or `.claude/rules/*.md` file is
loaded into context… at session start and when files are lazily loaded"; `/context` lists what
actually loaded.

## 8. Sub-agent context, read limits, Bash output

- **What a subagent starts with**: "a fresh conversation (no prior message history, though it does
  load its own system prompt and project-level context like CLAUDE.md). It does not see the parent's
  turns" (agent-loop). Its system prompt is "shorter than the main session's". It "gets most of the
  parent's tools, minus several that don't apply in a nested context, including plan-mode controls,
  background-task tools, and by default the Agent tool itself to prevent recursion."
- **What returns**: "Only the subagent's final text response comes back to your context, plus a small
  metadata trailer with token counts and duration." The illustrative example: "The subagent read
  6,100 tokens of files. You got a 420-token result. That's the context savings."
- **Read-tool 2,000-line limit**: **not stated** in these nine pages (the tools-reference page is
  linked but not in this set).
- **Bash output limits**: the threshold is **not stated** here, but the mechanism is: hook output over
  10,000 characters "is saved to a file and replaced with a preview and file path, **the same way a
  large valid Bash result is handled** under Output limits". For failures, "Claude Code
  middle-truncates strings longer than 10,000 characters around a `... [N characters truncated] ...`
  marker", and that error string "is generally the same text Claude receives as the failed tool's
  result".

## Relevance to P1–P4

**P1 (context is the cost).** The docs corroborate the shape: cache reads are "billed at roughly 10%
of the standard input rate", and every turn re-sends the whole history — "a one-line question in a
session that has been open all day still draws usage for the whole conversation". The single most
actionable claim for us is the cache-scope rule: our ≈30 sessions per slice run *sequentially* in one
directory, and "Sequential sessions share the prefix only when the git status snapshot at startup
matches, since the system prompt also captures branch and recent commits." Every phase commit changes
that snapshot, so each session almost certainly pays a full cache **write** for the ~33k prefix rather
than a read. Parallel same-directory sessions do share it. Our `FORCE_PROMPT_CACHING_5M=1` also
forces the shorter TTL, which the docs describe as a debugging switch, not a production setting.

**P2 (sessions grow; the longest dominate).** With Opus at 1M and no compaction, the documented
default is "compacts when the conversation reaches the model's context limit" — i.e. the 438k
doc-writer session never compacted because it never got near 1M. `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
lets us choose that boundary per session type (100K–1M), and `/compact` while the cache is warm
"costs a fraction of what the context size suggests". A `PreCompact` hook can archive the transcript
first. Transfer gap: the docs say nothing about compaction's effect on output quality in a coding
loop.

**P3 (every session rebuilds the same picture).** Two documented mechanisms attack this without
enlarging the prefix: `PostToolBatch`/`PostToolUse` `additionalContext`, injected "at the point where
the hook fired", and `SubagentStart` `additionalContext` for explore agents. And the standing advice
for anything static is the opposite direction: "For instructions that never change, prefer CLAUDE.md.
It loads without running a script." The docs are silent on how much re-reading actually costs us.

**P4 (what smaller reads cost in grounding).** The docs give mechanisms, not evidence — with one
explicit warning in our direction: "Stripping error details that Claude needs can cause it to proceed
on a false assumption." No measurement of the trade-off appears anywhere in these pages.

## Interventions this paper supports

- **Stop paying the prefix as a cache write per session.** Where the DAG allows, launch a phase's
  sessions in parallel in the same directory ("Sessions you run in parallel in the same directory
  build matching prefixes and read each other's cache"); accept that a commit between sequential
  sessions breaks prefix sharing. Loses: nothing in grounding; costs scheduling complexity.
- **Re-examine `FORCE_PROMPT_CACHING_5M=1`.** Rests on: it "force[s] the five-minute TTL regardless of
  authentication", and its documented purpose is debugging. If our gaps between sessions exceed five
  minutes, `ENABLE_PROMPT_CACHING_1H=1` trades a higher write rate for surviving the gap. Direction:
  fewer full-prefix rebuilds; size unknown, and 1h writes cost more.
- **PreToolUse `updatedInput` wrapper on Bash** to cap gate/test/log output (the costs page's own
  `grep … | head -100` example), configured in `.claude/settings.json` so it applies to `-p` sessions,
  or in a specific agent's frontmatter for a role-specific cap. Loses: an agent can no longer see the
  full failure text — the doc's own warning about stripped error details applies.
- **PostToolUse `updatedToolOutput`** to window a large Read or replace a verbose gate result with a
  summary + path. Constraint: "The value must match the tool's output shape", and a mismatched value
  "is ignored and the original output is used".
- **PostToolBatch `additionalContext`** to deliver known frictions (a CLI's argument shape, citation
  format) exactly when a matching tool ran, rather than adding them to the prefix every session.
  Rests on: it "fires exactly once with the full batch… before Claude Code sends the next request".
- **SubagentStart `additionalContext`** to give explore sub-agents the return contract without
  lengthening the dispatch prompt.
- **`--json-schema`** to make sub-agent and phase hand-offs machine-checked (`structured_output`),
  instead of parsing prose returns.
- **Fix cost accounting**: if `slice_cost.py` reads `usage`, it undercounts — "`usage` Excluded.
  Counts only the top-level agent loop"; use `modelUsage`/`total_cost_usd`. Also read
  `cache_read_input_tokens` vs `cache_creation_input_tokens` per session to measure the prefix-sharing
  claim directly.
- **Budget/turn guardrails** (`max_budget_usd`, `max_turns`) on runaway sessions, noting the cap
  "covers subagents".
- **Set `CLAUDE_CODE_AUTO_COMPACT_WINDOW`** deliberately for the doc-writer rather than inheriting the
  1M limit, with a `PreCompact` archive hook so the pre-compaction transcript survives for review.
- **Prefix hygiene**: `disable-model-invocation: true` on operator-only skills removes them from the
  startup listing; unused MCP servers cost tool *names* only while deferred; per-agent `tools:` scoping
  removes schemas.

## Applicability caveats

- **The token numbers are a simulation, not a measurement.** The context-window page labels them
  "illustrative" and says actual values vary with CLAUDE.md size, MCP servers, and file lengths. They
  cannot be used to validate our measured ≈33k prefix.
- **Vendor docs, version-gated.** Mirrors fetched 2026-08-22; dozens of behaviours carry "Requires
  Claude Code v2.1.x" or "Before v2.1.y" qualifiers. Anything we adopt must be checked against the
  version the KubeCoder image actually runs.
- **`kc session create-headless` is not documented anywhere in this set.** Whether it passes `--bare`,
  which settings sources it loads, whether project hooks and agent frontmatter hooks reach the spawned
  process, and whether the workspace-trust rule ("A `-p` session doesn't count as accepting it")
  blocks subagent-frontmatter hooks are all unverified for our wrapper.
- **No quality evidence.** These pages describe mechanisms and costs; they contain no measurement of
  what truncated tool output does to task success — exactly the P4 gap.
- **1M availability is plan-dependent**, and the auto-compact default differs per model and per
  provider; the effective window under our auth is worth confirming with `/context` rather than
  assumed.
- **`updatedToolOutput` is post-hoc**: "The tool has already run by the time the hook fires", and
  telemetry captures the original output — so it saves context, not execution.

## Briefing check

No one-line relevance note was supplied with this task, so there is nothing to verify against
verbatim. Against the task's own framing — "what the harness gives us as levers" — the pages support
it, with two corrections to the framing itself:

1. The task assumed the question was mainly *how much the fixed prefix costs*. The docs' own numbers
   are explicitly illustrative and cannot settle that; the load-bearing finding is instead the cache
   **scope** rule ("Sequential sessions share the prefix only when the git status snapshot at startup
   matches"), which implies our per-session prefix is largely a cache *write*, not a read — a
   different and larger lever than trimming the prefix.
2. The task listed API-side context editing as something to look for. The docs are silent: no
   setting, env var, or flag for `clear_tool_uses`, `clear_thinking`, or server-side compaction
   appears in any of the nine pages. Client-side compaction is the only documented context-editing
   mechanism, and it is a full summarization request, not a selective clear.
