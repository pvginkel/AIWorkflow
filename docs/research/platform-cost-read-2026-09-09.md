# The Claude Platform cost post, read against the dev plugin — 2026-09-09

**Source.** Anthropic, *Reducing cost and improving performance with Claude Platform*
(claude.com/blog, 2026-09-08, Lance Martin). Five sections: prompt cache, instructions, effort,
automating cost reduction (`/claude-api cost-optimize`), and getting started (`/claude-api
prompt-audit`, `cost-optimize`, `hillclimb`).

**What this document does.** It takes each of the post's recommendations and answers three
questions against the plugin as it runs today — 0.9.32 on Claude Code 2.1.261; Opus 5 at `xhigh`
for the six main roles, Sonnet 5 for the test-agent and the two Sonnet sub-agents, Fable 5.1 for
the refinement-writer: is it reachable at all from a pipeline that spawns headless Claude Code
sessions instead of calling the API; is it already done; and if not, what it is worth here, in
the corpus's own numbers. Dollar figures are sticker prices via `slice_cost.py`. The account runs
on a Claude subscription (the loop handles the API's session-limit notice), so dollars are a proxy
for plan usage, not an invoice.

## 1. The short version

- **The caching section describes the plugin's current state, not a to-do list.** Every
  dispatched role runs one model at one effort behind a trimmed, stable prefix on the forced
  5-minute TTL; 97 % of the latest slice's prompt tokens were read from cache; prefix breaks cost
  0.7 % of headless spend. The one place the post's advice is inverted here — "use a 1-hour TTL
  for long operations" — is inverted on purpose, and the arithmetic still says so (§ 3.1).
- **The instructions section is where the post has something for us.** `/claude-api
  prompt-audit` run over the plugin's 28 prose files finds a clean surface — no ALL-CAPS
  imperative in any agent, every `never` with its reason beside it — and a short list of real
  items: the arch-design agent and skill are April-era text naming a pipeline that no longer
  exists; `docs/refinement.md`, read by the Fable writer on every dispatch, is about 40 % research
  narrative; anecdotes and numeric caps in three agents; three cross-file contradictions (§ 3.2).
- **Effort is settled for the main roles and the post does not reopen that.** It adds two things
  the ruling did not weigh: the Sonnet roles and every sub-agent run at `xhigh` by accident of the
  operator's global `effortLevel` setting, not by decision; and "a stronger model at lower effort"
  — at Fable 5.1's cache-read price the same tokens cost ≈ 1.15× Opus on this workload, not 2×
  (§ 3.3). Both are the operator's call.
- **`cost-optimize`, `hillclimb`, the Batch API, task budgets and output caps are not reachable**
  from a Claude Code session, and the plugin has no eval for a hillclimb to climb (§ 3.4).
- **Nine suggestions in § 4**, ranked: four free prose fixes, two one-line measured trials, one
  tooling correction, two that touch a ruling. Narration as a cost lever was checked and is dead:
  visible text is 1–2 % of every role's output tokens (§ 2).

## 2. Where the money goes

The post's first step is a token profile. Three views, all from the plugin's own replay
(`turn_profile.py` through `slice_cost.py` and `writer_economics.py`):

| view | cache read | cache write | output | input |
|---|---:|---:|---:|---:|
| r1 code-writer, corpus 144–170 (Claude Code ≤ 2.1.233, 86 sessions) | 63 % | 17 % | 20 % | 0 % |
| r1 code-writer, slices 180–193 (113 sessions) | 55 % | 18 % | 26 % | 0 % |
| slice 218 whole, priced at Opus rates | 58 % | 23 % | 19 % | 0 % |

Slice 218 (`218_kc_describe_and_catalog_output`, nine phases, 0.9.32): $157, 199 M tokens —
192.0 M cache read, 5.97 M cache write, 1.27 M output, 4 k uncached input — over 52 conversations
and 1,954 turns at $0.080 a turn; 6.3 h wall, 12.3 h active. At Opus rates that is $96 of cache
reads, $37 of cache writes and $32 of output. The cache hit ratio (reads over reads + writes +
uncached) is 97.0 %.

| 218 by role | $ | share |
|---|---:|---:|
| code-writer (11 sessions) | 48.89 | 31 % |
| code-reviewer (11) | 26.25 | 17 % |
| doc-writer (1) | 19.29 | 12 % |
| general-purpose sub-agents (13) | 17.37 | 11 % |
| plan-writer (2) | 11.66 | 7 % |
| Explore sub-agents (8) | 9.24 | 6 % |
| orchestrator:plan (interactive) | 7.69 | 5 % |
| consult (1) | 6.80 | 4 % |
| test-agent (1) | 4.53 | 3 % |
| plan-reviewer (1) | 3.45 | 2 % |
| orchestrator:run (interactive) | 2.02 | 1 % |
| refinement-writer (Fable 5.1, 97 k tokens) | 0.00 | unpriced — § 4 S5 |

What the output tokens are, on the 295 main-role sessions of slices 200–218:

| role | sessions | out/turn | thinking | visible text | tool inputs (edits, commands, verdict files) |
|---|---:|---:|---:|---:|---:|
| code-writer | 97 | 772 | 47 % | 2 % | 51 % |
| code-reviewer | 97 | 1,114 | 66 % | 2 % | 32 % |
| doc-writer | 30 | 1,025 | 37 % | 1 % | 62 % |
| plan-writer | 23 | 951 | 55 % | 2 % | 43 % |
| test-agent | 17 | 861 | 52 % | 2 % | 46 % |
| consult | 19 | 718 | 53 % | 2 % | 45 % |
| plan-reviewer | 12 | 1,225 | 69 % | 1 % | 30 % |

What this says. Cache reads are the majority of the bill and are already at the cheapest rate
there is; the bill is turns × context, as `turn_profile.py`'s docstring has said since August. The
levers left are (a) fewer turns and fewer sub-agent sessions — instructions; (b) less thinking per
turn — effort, which reaches 37–69 % of output tokens, i.e. ≈ 10–17 % of spend directly plus what
retained thinking adds at the read rate (4 % in the corpus); (c) cheaper tokens for the same work
— the model. Narration is not a lever: the Opus 5 migration guide names it as a cost, but in
headless sessions it is 1–2 % of output, and output is a fifth of spend.

## 3. The post, section by section

### 3.1 Prompt cache

The post lists five ways to lose cache hits and eight fixes. Against the plugin:

| the post says | here | evidence |
|---|---|---|
| Don't change effort or thinking mid-conversation (Opus 5 / Fable 5.1 can, via a mid-conversation system message) | Done. Every role is dispatched with explicit `--model` / `--reasoning-effort`; a nudge resumes with the role's own flags | 1,387 transcripts of the last 12 days: no headless session mixes model or effort. The 14 mixed-model transcripts are interactive sessions and the harness's `<synthetic>` rows |
| Keep volatile values out of the prefix | Claude Code's prefix; the plugin puts instance data in the dispatch prompt, after it | — |
| Avoid tool definitions that reorder | Deterministic tool set; MCP servers off for every role but the test-agent; MCP schemas are deferred out of the prefix since Claude Code 2.1.212 regardless | `agent-dispatch.md` § Spawning |
| Forks share cache only on a byte-identical prefix, same model, same effort | Sub-agents start fresh prefixes (`ctx1` 5–14 k in 218) — nothing to share; the doc-writer's fan-out is ≤ 2 Explore in one turn, then end the turn | 218 turn table |
| Synchronous calls or sub-agents that outlive the TTL rewrite at 1.25× | Measured: 29 gaps > 5 min in 749 headless sessions, $14 = 0.7 % of headless spend; 21 of the 34 headless breaks are the test-agent's deploy waits | `context-profile-2026-08-23.md` § 3 |
| Monitor the hit rate (Console, cache-diagnostics API) | `turn_profile.prefix_breaks` per session, the `brks` column of `slice_cost.py`; `/usage` shows the ratio since 2.1.251 | 218: 4 breaks in 52 sessions |
| Defer rarely used tools | Claude Code's tool search does it; the plugin trims the *listings* instead — memory, bundled skills, slash commands, MCP | −7–8 k tokens off every turn, measured 2026-08-23 |
| Apply system-prompt updates as messages | Claude Code's mechanism (system-reminders), not the plugin's | — |
| Stable content first | Claude Code's ordering | — |
| Change model or effort only at a breakpoint | Never changed within a session | row 1 |
| Move the breakpoint; pre-warm with `max_tokens: 0` | Not reachable from a session; continuous turns make pre-warming moot | `prompt-caching.md` § Pre-warming: "skip when traffic is continuous" |
| Respect the TTL — set 1 h for longer operations | The opposite, on purpose: `FORCE_PROMPT_CACHING_5M=1` on every dispatch. The interactive orchestrators run on 1 h | below |

**The TTL arithmetic.** Cache writes are 18 % (writer) to 23 % (218) of spend at the 5-minute
1.25× rate. At the 1-hour 2× rate the same writes cost 1.6× as much: +11 % (writer) to +14 %
(218: $37 → $60) on the bill, against the 0.7 % that breaks cost. That is the corpus's
`interventions-2.md` § 2 caveat 2, and it still holds. Two updates to that note:

- The docs now list `FORCE_PROMPT_CACHING_5M=1` **first** in the TTL precedence order — then
  `CLAUDE_CODE_PROMPT_CACHE_TTL` / `promptCacheTtl` (and the sub-agent pair), the sub-agent
  frontmatter `experimental.cacheTtl` (2.1.248+), then `ENABLE_PROMPT_CACHING_1H`, then the
  default. It is a supported switch, not the debugging one the caveat called it.
- The default it overrides matters: the main conversation — interactive *and* `-p` — gets the
  1-hour TTL "on a Claude subscription within plan usage" and 5 minutes on an API key; sub-agents
  get 5 minutes. On this account, without the switch every dispatched role would be writing at 2×.
  The transcripts confirm the switch works: 27.8 M tokens of 1-hour writes in the last 12 days,
  all of them in interactive sessions (159 of the operator's own plus the 24 `/dev:plan-slice` and
  `/dev:run-slice` orchestrators), none in a dispatched role or a sub-agent. For the orchestrators
  1 h is right — they are human-paced, and the corpus charged `orchestrator:run` 16 % of its cost
  to breaks (39 breaks in 29 of 32 sessions).

**The test-agent** is the one headless role with breaks (21 in 16 of 34 sessions, $8.79 = 5.7 %
of its corpus cost). A per-role 1-hour TTL is one env var in its spawn, but 0.75× extra on every
write at an ≈ 18 % write share is ≈ 13 % of the role — more than the breaks. Not worth it.

**One doc fix.** `agent-dispatch.md` § Spawning says `--strict-mcp-config` takes "the operator's
servers' tool schemas and instructions" out of the prefix. Since 2.1.212 the schemas were never in
it (tool search defers them); the server *instructions* and the reach argument — a role should not
be able to write a tracker card — still stand, and the 2026-08-23 measurement of the whole trim
stands. Low priority.

### 3.2 Instructions

The post's claim: prompts accumulate patches for old models' weaknesses, and a frontier model
executes them literally — verification rituals, thoroughness boosters, mandatory procedures and
scratchpads, stale examples, contradictory rules, dated configuration. Its evidence: planting one
anti-pattern at a time in six support prompts and removing it with `/claude-api prompt-audit` cut
cost 14.6 % and raised accuracy 5.3 % (Opus 4.8 → Opus 5). The post says the audit runs on Claude
Code configuration too. So it was run here: the skill's `shared/prompt-audit.md` procedure, by a
sub-agent, over the 10 agents, 7 skills, 11 contract docs and the dispatch prompts in `run_loop.py`
and `plan_loop.py`; the findings below are the ones I re-read in the source.

**Headline.** The surface is unusually clean. No ALL-CAPS imperative in any agent definition; the
`never` count runs 3–12 per agent and each instance encodes a settled ruling with its reason
adjacent (0.4.2's comments, no `✅ DONE` stamp, no push); every output shape a Python driver
parses — the verdict JSON, `### P<id> — <title>` + `Target:`, the two-part done-record, the
close-out entries, the status-document block `triage_verbatim.py` diffs — is load-bearing and was
not flagged. `docs/AUTHORING.md` carries no dated pattern. Clean outright: `rebase-agent`,
`test-fixer`, `refinement-writer`, `plan-reviewer`, the close-out and run-slice skills, seven of
the eleven contract docs, and all of `plan_loop.py`'s prompts.

**Findings.**

| class | where | what | confidence |
|---|---|---|---|
| retired vocabulary, contradiction | `skills/arch-design/SKILL.md:23,60,64`; `agents/arch-design.md:154` | "the dev agent's planning phase", "slice briefs", "so dev agents can read it during their planning phase" — the only four hits in the plugin; the consumer is `/dev:plan-slice` (`skills/plan-slice/SKILL.md:103`). The skill hands the design to a stage that is not there | high |
| pressure language ×3, scratchpad, step choreography | `agents/arch-design.md:53-61, 155` ("Do NOT skim" three times), `:59` ("Take notes on key facts as you go"), `:31-88` (`## Step 1`…`## Step 5`), `:146-155` (an eight-item "What NOT to do" repeating the body) | The one pre-rebuild body (April 2026, ported unchanged 2026-08-11). Keep the output template and the two real bounds; delete the rest | high |
| history narrative in a prompt the model reads every dispatch | `docs/refinement.md:4-17, 42-50, 60-65, 81-82, 112-116, 158-160, 191-193` | The 49-slice readout, the 27–35 KB walls, quoted operator verdicts, slices 183/197/199. The Fable refinement-writer reads the whole file per dispatch; the rules stand without the evidence, which belongs in `docs/rationale/` | medium |
| anecdote in an agent | `agents/code-writer.md:55-56` ("One writer raised a Blocker over a sibling-repo commit…"); `run_loop.py:1601-1603` (`PUSH_NUDGE_PROMPT`'s crash-loop story); `skills/plan-slice/SKILL.md:94-95`; `skills/triage/SKILL.md:136-139, 326-327` | Rule 9's reason is complete without the story, which also sits in `run-loop.md:103` and a code comment | medium |
| deterministic algorithm run by reasoning | `skills/slice-dag/SKILL.md:86` ("Phase 4 — Build the plan (pure reasoning, zero file reads)") and `:171-195` | The layer/order/place packing is fully determined by its inputs. The repo's own principle — scripts drive, agents judge — says script | medium |
| numeric caps | `agents/code-writer.md:29-30` (done-record "hard cap ~25 lines"), `:63` ("±40 lines"); `docs/plan-template.md:101-103` | The qualitative rule is already there ("settlements not narration"). The operator may reasonably keep the numbers | medium-low |
| duplicated harness instruction | "Batch independent tool calls into one message" in eight agents (`code-writer:59`, `code-reviewer:70`, `doc-writer:50`, `plan-writer:72`, `plan-reviewer:62`, `test-agent:36`, `test-fixer:29`, `rebase-agent:23`) | Claude Code's own system prompt carries it. Low value either way — 218 still shows 228 batchable turns (11.7 %) with the line in place | low |
| budget countdown shown to the agent | `run_loop.py:1597` `PUSH_NUDGE_PROMPT` "(nudge {round} of {cap})", and the doc-gate nudge | Invites an early `blocked`. (`:1373` "review round {round} of at most {cap}" is the consult's funding bar — keep) | low |
| boilerplate | `skills/plan-slice/SKILL.md:24-25` (RFC 2119 line) | Two MUST NOTs, both self-evident | low |

**Cross-file contradictions** — the class the post's example lost four refunds to:

1. The arch-design skill vs the pipeline (above).
2. "The suite was green before this slice's work" is stated as fact in `agents/test-agent.md:21-22`
   and `skills/run-slice/SKILL.md:110`; `docs/preflight.md:91-94` says the baseline is `kc project
   build` only and "Full `kc project test` is *not* a preflight step". The never-flaky rule rests
   on a premise nothing checks. Either preflight runs the suite, or the prompt says "treat the
   suite as green" (an instruction) rather than "was green" (a fact).
3. Reviewer on an unverified gate: `agents/code-reviewer.md:65-66` says the branch's test state is
   "yours to probe"; `run_loop.py:1330-1334` (`GATE_UNVERIFIED_LINE`) says "treat … as unverified,
   and say so in your review". One invites running the suite, the other a caveat.

**The Opus 5 checklist.** The API skill's migration guide lists the prompt-tunable behaviour
shifts of the model the six main roles run on. Against the plugin:

| Opus 5 shift (migration guide) | here |
|---|---|
| Over-verification — "delete your verification scaffolding … a delete, not a rewrite" | No self-check scaffolding in any agent. The reviewer is a separate role by design, not a re-check instruction. Nothing to delete |
| Delegates to sub-agents more readily than 4.8 — "any 'delegate more' guidance should come out; you likely want an explicit cap" | Sub-agent spend per slice: $6.41 in the corpus, $12.93 on slices 200–218 like for like (the reverted `doc-unit` split adds $4.08 on top), $26.61 = 17 % of slice 218. The rise is the consult's and the plan orchestrator's general-purpose agents (0 → $1.90 and $0.53 → $2.10 per slice) more than Explore. Only the doc-writer (≤ 2 Explore) and the plan-writer (a research agent only against a named open question) carry a rule; the consult prompt and the plan-slice orchestrator carry none. → S2 |
| Longer written deliverables — calibrate length explicitly | The refinement doc's 27–35 KB walls were exactly this, fixed by 0.9.21's "about 250 words". plan.md, the review files, done-records and close-out entries have qualitative rules and, in two places, the numeric caps above. → S6 |
| Severity filters depress recall — "ask it to report everything with confidence and severity, filter in a separate pass" | Already the reviewer's contract: every finding with severity, impact tag, anchor and confidence; the *round* is filtered to blocking by the driver. Compliant |
| Scope expansion — deliver at the asked scope, finish the whole task | The bounds sections do this per role |
| Narration | 1–2 % of output (§ 2). Not a lever |

**Sonnet 5**, for the test-agent, test-fixer and rebase-agent: the guide says it "follows
instructions closely … interprets prompts literally, particularly at lower effort", and that at
`high`/`xhigh` it "shows substantially more tool usage in agentic search and coding". The first is
an argument for the audit's contradiction 2 (a literal reader of "was green" has been told a
fact); the second is § 3.3's test-agent row.

### 3.3 Effort

The post: effort is the first cost-quality dial; a curve that is flat across effort says the task
is not thinking-bound; a stronger model at lower effort can beat a weaker one at high (Fable 5.1
at `low` ≈ Fable 5 at `high` on CursorBench at a third of the cost); `hillclimb` finds the cell.

**Settled, and the post does not reopen it.** No effort tiering or weaker model for plan-writer,
plan-reviewer, code-writer, code-reviewer (0.7.0–0.7.2 withdrawn as dead weight,
`status.md` § A3); effort reaches ≈ 25 % of spend (`interventions-2.md` § 2 caveat 1) — § 2's
thinking shares agree. There is no eval to sweep against: quality is the operator's judgment on
the shipped slice, and catch-rate work is closed. What the post adds is below, and both are the
operator's call.

**Who runs at what, and why.**

| role | model | effort | where the effort comes from | settable per role? |
|---|---|---|---|---|
| plan-writer, plan-reviewer, code-writer, code-reviewer, doc-writer, consult | Opus 5 | `xhigh` | `MODELS` in `run_loop.py:122` / `plan_loop.py:96`, explicit flag | yes — settled |
| test-agent | Sonnet 5 | `xhigh` | nothing in the loop (`("sonnet", None)`); the operator's `~/.claude/settings.json` `effortLevel: xhigh` and `CLAUDE_EFFORT=xhigh` | yes — one tuple |
| test-fixer, rebase-agent (Sonnet sub-agents) | Sonnet 5 | `xhigh` | inherited from the parent's setting | no — sub-agent frontmatter has no effort field (Claude Code docs, 2.1.26x) |
| Explore, general-purpose (sub-agents) | Opus 5 unless the dispatch says `sonnet`; Explore inherits the parent's model since 2.1.198 | `xhigh` | inherited | model yes, effort no |
| refinement-writer | Fable 5.1 | `xhigh` | inherited | model pinned in frontmatter |

The last 12 days: 41,382 turns at `xhigh`, 138 at `low`, the rest the harness's synthetic rows;
209 of 219 Sonnet sub-agent transcripts at `xhigh`. So every role the ruling left tunable runs at
the top setting by inheritance. The one that is a top-level dispatch, the test-agent, is 3 % (218)
to 6.4 % (corpus) of spend — and every Sonnet figure in the readouts is 1.5× overstated, because
`slice_cost.py` prices Sonnet 5 at the $3/$15 that was scheduled for September and did not happen
(S5). A `medium` test-agent is one tuple and a five-slice read (S4).

**The stronger-model claim, priced for this workload.** Fable 5.1 is $10/$50 against Opus 5's
$5/$25, but its cache-read rate is $0.25 per M against Opus's $0.50 — and cache reads are 55–63 %
of the writer's bill. At equal tokens:

| token class | writer share (180–193) | Fable 5.1 ÷ Opus 5 | contribution |
|---|---:|---:|---:|
| cache read | 55 % | 0.5× | 27.5 % |
| cache write | 18 % | 2× | 36 % |
| output | 26 % | 2× | 52 % |
| **same tokens on Fable 5.1** | | | **≈ 1.15× Opus** |

On slice 218 whole: $186 against $165 at Opus rates, 1.13×. So the question the post poses — does
Fable 5.1 at `high` (the API default) or `medium` do a phase in ≥ 15 % fewer tokens than Opus 5
at `xhigh`, i.e. fewer turns, fewer rounds, less thinking — is a real A/B, not a 2× bet. Its
CursorBench figure (a third of the cost) is on a different workload and a different comparison
(Fable 5 at `high`), so it is a hypothesis here, not an expectation. Prerequisites and risks: S5
first (the tool cannot price a Fable turn today); Fable's safety classifiers can end a turn with a
`refusal` stop on a Kubernetes/RBAC/credentials codebase; the migration guide warns prompts written
for prior models are "often too prescriptive"; a separate rate-limit pool on the subscription. The
ruling's letter (no *weaker* model, no tiering *down*) does not cover it; its spirit — one config,
no grading — does. → S8, operator's ruling.

### 3.4 Automating cost reduction

`/claude-api cost-optimize` profiles an application's own API calls and applies caching,
trimming, the audit, output bounding and batching; with an eval it sweeps effort and model. The
post's public-benchmark results (LegalBench −58 %, tau2-bench −73 %, OfficeQA −52 %, SWE-bench
−55 %) come from caching, `low`/`medium` effort, constrained output and the Batch API. Here:

- **The plugin makes no API call.** Claude Code owns the request; caching, breakpoints and
  ordering are its. The profile the tool would build is § 2, from the plugin's own replay.
- **Batch API** — 50 % off, asynchronous, single-shot — cannot run a tool loop. Not applicable.
- **Output bounding and task budgets** — headless `-p` mode documents no max-output-tokens flag
  and no budget flag; task budgets are an API beta. Not reachable. (SWE-bench's "median steps
  29 → 17" at `medium` is the turns plan's lever family; T1–T4 bought −4 to −9 % turns per phase
  and the box is exhausted, `readout-2026-09-01.md` § 7.)
- **`hillclimb`** needs a frozen eval with a pass signal. The workflow has none by ruling.
- **Context editing and compaction** — settled off for writers and reviewers; the API skill's own
  cost guide now agrees ("context editing cost more than it saved" in the platform docs' run).

### 3.5 Getting started

Of the three commands, `prompt-audit` is the one that applies to Claude Code configuration and it
has been run (§ 3.2). The post's framing — instructions drift relative to the newest model — makes
it a standing item: re-run it on the plugin after each model change, before reading the first
slices on the new model.

## 4. Suggestions

Ranked by value against cost. *Free* = prose, this session's model per CLAUDE.md's "who writes
what"; *measured* = a one-line change read on five slices with the existing tooling; *ruling* =
the operator decides.

- **S1 — Apply the audit (free).** Rewrite `agents/arch-design.md` and `skills/arch-design/
  SKILL.md` for the pipeline that exists (`/dev:plan-slice`, plan attachments; drop the step
  choreography, the triple "Do NOT skim", the notes scaffold, the duplicate don't-list); move
  `docs/refinement.md`'s evidence to `docs/rationale/` and keep the shape and rules; take the
  anecdotes out of `code-writer.md`, the push nudge, the plan-slice and triage skills; resolve
  contradictions 2 and 3 (say "treat the suite as green" or make preflight run it; pick probe or
  caveat for the reviewer); drop the RFC 2119 line and the two nudge countdowns. Effect is
  quality and drift, not tokens — except that a Fable writer stops reading 6 KB of history per
  dispatch. One plugin version.
- **S2 — A delegation rule for Opus 5 (free).** Sub-agent spend doubled per slice like for like
  and the migration guide says the model now delegates freely and wants an explicit rule. Put a
  short one where the rise is: the consult prompt (`run_loop.py`) and the plan-slice orchestrator
  skill, in the guide's shape — delegate for wide, independent surveys; never for a few reads, a
  handful of edits, or verification; one agent over several; brief once. The doc-writer and
  plan-writer rules stay. Measure: `writer_economics.py subs --new` on the next ten slices
  against $12.93.
- **S3 — Explore on Sonnet everywhere (free).** `interventions-2.md` P3.3, catalogued and never
  shipped: Explore locates, it does not judge; two prompts already pin it (`arch-design`,
  `slice-dag`), 218's doc-writer dispatched it on Sonnet, the plan-writer's ran on Opus. Slices
  200–218 spent $6.67 per slice on Explore; at Sonnet 5's live prices (0.4× Opus per class) that is
  ≈ $4 per slice, 2–3 % of a 218-sized slice. Mechanism: `model: sonnet` in the dispatch lines of
  the plan-writer, doc-writer, consult and plan-slice registers. General-purpose sub-agents stay
  as they are — those do judgment.
- **S4 — Test-agent at `medium` (measured).** `MODELS["test-agent"] = ("sonnet", "medium")` in
  `run_loop.py`. The role runs `xhigh` only because the operator's global setting says so; Sonnet
  5's tool use is "substantially" higher at `xhigh`; the work is an enumerated check-off
  (`verification.json`) with a Sonnet fixer beside it. Expected: a fraction of 3–6 % of spend.
  Read on five slices: `slice_cost.py` per role, check-off count, findings routed, `blocked`
  verdicts.
- **S5 — Fix the price table (code, small).** `slice_cost.py` `PRICES`: Sonnet 5 is $2/$10 (the
  introductory price is now the standard price — the September rise did not happen), not $3/$15;
  `claude-fable-5-1` is absent, so 1,742 Fable 5.1 turns in the last 12 days and every
  refinement-writer dispatch price at $0; and the cache-read multiplier is per model now — 0.025×
  on Fable 5.1, 0.1× elsewhere — so `CACHE_READ_MULT` becomes a column. `writer_economics.py`'s
  `RATES` is a second copy. An Opus sub-agent on disjoint files with `test_slice_cost.py`;
  prerequisite for S8 and for every future Sonnet figure.
- **S6 — A length line for written deliverables (free).** The guide's calibration sentence —
  "match the length of written deliverables to what the task needs; no filler sections, redundant
  summaries or boilerplate" — in `code-reviewer` (the review file), `plan-writer` (plan.md) and
  the close-out contract, replacing nothing. Quality, not tokens; the numeric caps in
  `code-writer` can then go or stay on the operator's taste.
- **S7 — Two doc corrections (free).** `agent-dispatch.md` § Spawning on what
  `--strict-mcp-config` removes (§ 3.1); and a line under `interventions-2.md` § 2 caveat 2 that
  the 5-minute switch is the documented top of the precedence order, with the 1-hour default it
  overrides on a subscription.
- **S8 — Fable 5.1 at `high` or `medium` for the code-writer, as an A/B (ruling).** § 3.3's
  arithmetic: 1.15× at equal tokens, so the bet is on fewer tokens per phase. After S5, five 2–4
  phase slices with `MODELS["code-writer"] = ("fable", "high")`, read with `slice_cost.py`
  ($/phase, rounds) and `r1_blocking_readout.py`; watch for `refusal` stops in `log.txt`. I would
  not run it before S1–S4 have been read: it is the most expensive experiment here and the one
  the ruling's spirit covers.
- **S9 — Re-run `prompt-audit` after each model change (free, standing).** § 3.5.

**Checked and not recommended**, so they are not re-proposed:

- A 1-hour TTL for any headless role, including the test-agent (§ 3.1's arithmetic).
- Pre-warming, explicit breakpoints, mid-conversation system messages, the cache-diagnostics API
  — Claude Code's side of the line.
- Context editing, compaction, history summarisation, turn or token caps — settled, and the API
  skill's cost guide now says editing cost more than it saved.
- The Batch API, task budgets, output caps — not reachable from `-p`.
- `hillclimb` and `cost-optimize` as tools — no API calls to profile, no eval to climb.
- A "no reader between tool calls" narration line — measured at 1–2 % of output.
- Effort or a weaker model for the four main roles — settled; nothing in the post moves it.

## 5. Method

- Post: fetched 2026-09-09 and extracted section by section.
- Harness facts: the Claude Code docs (sub-agents, sessions, prompt-caching, model-config,
  headless) read by the `claude-code-guide` agent; the pricing page read directly.
- Audit: the API skill's `shared/prompt-audit.md` procedure, run by a sub-agent over
  `plugins/dev/agents/*.md`, `plugins/dev/skills/*/SKILL.md`, `plugins/dev/docs/*.md` and the
  prompt constants in `run_loop.py` / `plan_loop.py`; every finding in § 3.2 re-read at its
  `file:line`.
- Transcript scan: the 1,419 transcripts under `~/.claude/projects/-work-KubeCoder/` modified in
  the last 12 days, parsed for per-turn `model`, `effort`, `cache_creation.ephemeral_5m_input_tokens`
  / `ephemeral_1h_input_tokens`; the 1-hour writers matched against every session id in
  `slices/completed/2*/state.json` and `plan_state.json`.
- Output composition: `turn_profile.replay` over the 295 sessions those state files name for
  slices 200–218; visible text = assistant text characters ÷ 4.
- Spend views: `slice_cost.py …/218_kc_describe_and_catalog_output`; `writer_economics.py eras`
  and `subs --new …/20[0-9]_* …/21[0-9]_*`; `context-profile-2026-08-23.md` for the corpus.
