# Orchestrator deep-dive: `aa40ad86` — the "heaviest track_build user" session

> **Correction (verified after this report was written):** the "fixed baseline (system prompt + 4 MCP
> servers' schemas, 48.7K tokens)" attribution is **wrong on the MCP part**. This session loads MCP
> tools **lazily** via `ToolSearch` (verified: 2 ToolSearch calls; only the 2–3 MCP tools actually
> invoked enter context). The ~48k base floor is the Claude Code system prompt + built-in tool schemas
> + the deferred-tool *name* list + `CLAUDE.md` — **not** MCP server schemas. **Ignore the MCP-surface
> angle.** The other findings stand. See `../../ORCHESTRATOR-COST.md`.

Transcript: `/home/ubuntu/.claude/projects/-work-KubeCoder/aa40ad86-348a-4ec2-8d42-f97ceade4736.jsonl`
Model: `claude-opus-4-8` · 116 deduped turns (313 raw JSONL assistant records, 2.7x) · wall 4.91h (294 min) · **$18.78**, 21,253,492 tokens (95.2% cache_read)

> **Methodology note (important):** `digest.py`'s dedup-by-`message.id` assumes each duplicate JSONL line repeats the *whole* message. In this transcript that assumption is wrong: each logical turn is logged as **one JSONL line per content block** (a `thinking` line, then a `text` line, then one line per `tool_use`), all sharing one `message.id`. Keeping only the first-seen line per id (what `digest.py` does) keeps only the `thinking` fragment and silently drops the turn's real text and tool calls — which is why the stock digest header shows only `TOOLS: {Edit:5, Bash:4, Read:2, move_card:1}` for a 116-turn, 4.9-hour session. The token totals in the header (in/out/cache_write/cache_read, cost) are **not** affected, because `usage` is identical across every fragment of a given id — only the tool/text attribution is broken. All tool-use, tool-result, and phase-timeline figures below were recomputed from the raw JSONL by reconstructing full turns (concatenating every content-block fragment per `message.id`, then reading `tool_result`s from the `user` records, which are *not* fragmented — each `tool_use_id` appears exactly once). This matters directly for the headline question below.

## 0. Headline correction: "38 track_build invocations" is a line-grep artifact, not 38 tool calls

`grep -c track_build <file>` on the raw JSONL returns **exactly 38** — that is almost certainly how this session was selected as "the heaviest track_build user." But `grep -c` counts *matching lines*, and this transcript logs ~2.7 lines per logical turn plus duplicates every mention (memory docs, decisions.md diffs, Telegram messages, git-log blobs that happen to contain the string `track_build.py` in a commit subject). Reconstructing actual `Bash` tool calls whose **command** invokes `tools/ai_workflow/track_build.py`, there are exactly **3**, all clustered at the very end of the session:

| Turn | Elapsed | Command | Result | Size |
|---|---|---|---|---|
| 58 | 273.8m | `track_build.py --help` (usage check, combined with a `$JENKINS_TOKEN` presence check) | prints usage | 1,329 chars |
| 62 | 275.2m | Real attempt, fed the **wrong credential** (Jenkins MCP proxy bearer token) | `error: authentication failed (401)` | 240 chars |
| 114 | 294.0m | Real attempt, **after** the operator provisioned `$JENKINS_TOKEN`, against the *already-completed* build | resolves commit→build→downstream, both SUCCESS, exit 0 | 575 chars |

So this session is not a stress test of track_build at scale — it is the opposite: **track_build was broken (401, missing REST token — only an MCP proxy bearer token was available) for essentially the entire 294-minute run**, and was smoke-tested successfully exactly once, after the real work was already done, purely to confirm the fix. The actual CI/deploy tracking for slice 045's push was done the old way — manual Jenkins MCP polling + background sleep pacing — which is exactly the failure mode track_build was built to eliminate. That makes this session an excellent case study of **"where cost lands when track_build isn't available,"** which is what Section 2 quantifies.

## 1. Overview — what this session did

Slice 045 ("Home / github-auth + tunnel robustness") ships three worker-only fixes: idempotent `github-auth` (survives a stranded `~/.gitconfig.lock`), `token.json` as a shared-home symlink, and `Unregister()` on clean tunnel shutdown. The root orchestrator's actual job across the 294 minutes:

| Phase | Turns | Elapsed | What happened | Cost |
|---|---|---|---|---|
| **A** — resume + housekeeping | 0–17 (18) | 0–7.8m | Diagnose a killed dev-agent session (foreground 10-min cap), write a memory fix, re-dispatch the coding session **in the background** | $2.02 |
| *(idle — background dev-agent runs `/major-change`)* | — | 7.8→34.5m (26.7m gap) | No orchestrator turns; wall-clock only | $0 |
| **C** — verify + close out | 18–53 (36) | 34.5–47.8m | Read dev-agent handback, run Go+Python suites **inline**, dispatch an independent `slice-verifier` sub-agent, reconcile `decisions.md`/README, commit specs, move Trello card, update memory, send an interim "complete" report | $5.11 |
| *(idle — waiting on the operator's go-ahead to push)* | — | 47.8→273.0m (225m gap) | No orchestrator turns; real-world wait | $0 (but triggers a cache reset, see §3) |
| **E** — push, deploy-track, live-verify | 54–108 (55) | 273.0–291.0m | Push app+specs, diagnose track_build's 401, fall back to Jenkins MCP polling + background sleep timers, confirm CI #116 → HelmCharts #5141 deploy, **live-verify directly on the `iotsupport` env** (plant a stranded lock, cycle the env, tail logs, confirm idempotency + symlink + unregister in production), tear down, update memory, final report | $9.10 |
| *(2.4m gap — operator asks to retest track_build now that the token is fixed)* | — | 291.0→293.4m | — | — |
| **F** — track_build smoke-test | 109–115 (7) | 293.4–294.3m | Clean up the "track_build unusable" memory note, run the tool once against the completed build, confirm exit 0 | $2.55 |

Cost by token type (matches the digest header): **cache_read $10.12 (53.9%)**, cache_write $5.52 (29.4%), output $3.06 (16.3%), input $0.08 (0.4%). Cache_read dominance confirms the framing: this is a re-read-tax problem, not a per-tool-call problem — total raw tool-*result* bytes ingested all session are only **178,374 chars (~44.6k tokens)**, a rounding error next to the 20.2M cache_read tokens. The other ~20M+ tokens are the same ~40-260k-token context being re-billed every one of the 116 turns.

## 2. track_build footprint — the key question

**Direct footprint of the 3 real track_build calls: negligible.** Their tool results total 1,329 + 240 + 575 = **2,144 chars (~536 tokens)**. Even valuing the worst case (entered turn 58, re-read across all remaining ~58 later turns at $0.50/M), the re-read tax on track_build's own output is under **$0.02** for the whole session. Track_build, when it runs, is exactly as cheap as advertised — a "one-screen summary" (turn 114: `commit 4d131d6 → KubeCoder/KubeCoder #116 SUCCESS (7m58s)` + discovered downstream build, 575 chars total) instead of a blocking, context-hungry poll loop.

**But this session barely got to use it**, so the honest ROI question is: *what did the fallback path actually cost, and what would track_build have saved if the token had been provisioned from the start?*

Reconstructed sub-phases inside phase E (turns 54–108, $9.10 total):

| Sub-phase | Turns | Cost | What |
|---|---|---|---|
| E1 — push app+specs | 4 | $1.56 | (includes the idx-54 cache-reset charge, see §3 — not track_build's fault) |
| **E2 — track_build diagnosis (401 dead-end)** | 6 | **$0.78** | env-var checks, `curl` reachability, grep the script source for how it reads tokens, the actual 401 test |
| **E3 — Jenkins MCP manual polling + background-sleep pacing** | 16 | **$2.23** | `getJob`/`getBuild`/`getBuildChangeSets` (9 calls) to resolve commit→build→downstream deploy, paced with `sleep`-based wake timers because MCP can only be called from the orchestrator's own turns |
| E4 — live-verify prep | 9 | $1.24 | controller routes, token decode, port-forward setup |
| E5 — live-verify execution | 15 | $2.51 | plant lock, cycle env, tail logs, confirm, teardown |
| E6 — close-out | 5 | $0.78 | memory/notification/report |

**E2+E3 = $3.01 across 22 turns is the real cost of track_build being unavailable for this push.** Contrast with what a *working* track_build call actually costs: turns 110–115 (memory cleanup + the real, successful track_build run) cost $0.88 total, and of that, the launch+read of track_build itself (turns 114–115) was only **~$0.29** — because track_build does its polling loop *inside the script*, off the token meter, and returns once, compactly. If `$JENKINS_TOKEN` had been present at turn 58, the E2+E3 sequence (22 turns, $3.01) would plausibly have collapsed to ~2 turns (launch in background, read the completion summary) at roughly **$0.30–0.40** — a **savings of ~$2.6–2.7 per slice-push, ~14% of this entire session's cost**, just from one missing environment variable.

**Contrast with the ~27k-char manual-Jenkins-JSON blob track_build replaced:** interestingly, *this session's* manual fallback was not that bad — its author had already learned to use Jenkins MCP's `tree=` field-selector (e.g. `tree=name,lastBuild[number,building,result]`) rather than dumping raw build JSON, so the 9 Jenkins MCP results here total only 866+841+3,626 = **5,333 chars**, nowhere near 27k. The real cost was *turn count* (16 polling/pacing turns), not payload size. Still, it's worth pricing the worst case the task asks about: if those 9(-ish) polls, or a fuller 38-poll campaign across a slower build, *had* dumped raw ~27k-char Jenkins JSON each time:
- One-time ingestion: 38 × 27,000 chars ÷ 4 ≈ 256,500 tokens × $6.25/M (cache_write) ≈ **$1.60**
- Re-read tax (avg. ~40 later turns before session end) ≈ 256,500 × 40 × $0.50/M ≈ **$5.13**
- Plus ~38 LLM turns' own baseline overhead to issue/interpret each poll, ~$0.20/turn at this context depth ≈ **$7.6**
- **≈ $14–18 total** — on the order of this *entire* 4.9-hour session's actual cost, from build-polling alone.

**Verdict: track_build validates at the unit level (3 calls, ~$0.02–0.03 direct cost, does what it says) but this session cannot demonstrate "38 build-waits stay cheap" because it only ever completed one real wait, and that wait went through the old manual-polling path anyway.** The ROI number worth carrying forward is the **~$2.6–2.7-per-push (≈14% of a slice's orchestrator cost) savings once `$JENKINS_TOKEN` is actually provisioned** — plus the qualitative win of collapsing ~16–22 polling/pacing turns into ~2, which is what actually drove this session's wall-clock and cache-reset exposure (see §3).

## 3. Where the OTHER tokens go

### 3.1 Three full-context cache rewrites dominate cache_write (70% of it)

| Turn | Elapsed | cache_write | Likely trigger |
|---|---|---|---|
| 45 | 45.4m | 173,328 tok | No real-time gap (0.1m) — context had just crossed ~171k tokens; looks like an internal compaction/cache-eviction threshold, not an external event |
| 54 | 273.0m | 182,776 tok | The 225-minute real-world gap waiting for the operator's go-ahead — cache almost certainly TTL-expired (all cache entries in this transcript use the 1-hour ephemeral TTL) |
| 109 | 293.4m | 263,322 tok | Immediately follows the operator setting `$JENKINS_TOKEN` — an environment/tool-availability change plausibly invalidated the cached prefix |

Total: **619,426 tokens = 70.1% of all cache_write**, costing **$3.87** (6.25/M). Notably each rewrite reproduces essentially the *same* context size as before it (e.g. cr was 261,097 right before turn 109's reset; the rewrite is 263,322 — i.e. nothing was pruned), which argues these are cache misses/evictions, not `/compact`-style summarization. **The size of these inevitable rewrites is a direct function of how bloated the running context is at that moment** — every token trimmed from the live context (§3.2–3.4) saves $6.25/M at the *next* reset and $0.50/M on every read until then. This is the strongest structural argument for keeping this orchestrator's context lean: the 3 resets aren't avoidable (idle waits and env changes will keep happening), but their cost is fully a function of accumulated bloat.

### 3.2 Fixed baseline (system prompt + 4 MCP servers' tool schemas): ~$2.80 just to exist

Turn 0 (before any tool result returns) already writes **48,676 tokens** to cache — system prompt, CLAUDE.md, and tool definitions for Jenkins/Trello/Telegram/gitblit MCP servers, none of which have run yet. That baseline sits at the front of context and gets re-read on every one of the following 115 turns: 48,676 × 115 × $0.50/M ≈ **$2.80**, ~15% of the whole session and ~28% of the cache_read bill, before a single line of real work happens. This is unavoidable per-session overhead unless the MCP toolset itself is trimmed (e.g., not loading Jenkins/Trello/Telegram schemas for orchestrators that rarely touch them directly — note this session uses `ToolSearch` twice specifically to lazy-load Trello and Jenkins tools rather than having them always resident, which is the right pattern; the 48.7k baseline is what's left after that).

### 3.3 Biggest individual tool results and their re-read tax

Total raw tool-result bytes across all 119 tool calls: **178,374 chars (~44.6k tokens)** — Bash 93.6k chars (76 calls), Read 73.6k chars (13 calls), everything else under 5k chars combined. The 20 largest, correctly attributed (the stock digest mislabeled every one of these as `?`):

| Size | Tool | Turn | Elapsed | What |
|---|---|---|---|---|
| 11,107 | Read | 15 | 7.7m | `MEMORY.md` — the memory index, already flagged in-session as "over its size limit" |
| 10,040 | Read | 37 | 43.7m | `README.md` (Pending section) |
| 9,242 | Bash | 89 | 285.1m | **kubectl dump of "all objects with any kubecoder/env label"** — cluster-wide, not scoped to the one target env |
| 8,765 | Bash | 35 | 43.3m | `git diff decisions.md` |
| 8,098 | Read | 3 | 0.8m | slice `brief.md` (handover bundle) |
| 7,703 | Read | 3 | 0.8m | slice `overview.md` (handover bundle) |
| 7,468 | Read | 0 | 0.0m | `run_slice_045_handover.md` (handover bundle) |
| 7,467 | Read | 31 | 41.5m | `decisions.md` |
| 6,229 | Bash | 1 | 0.1m | `git log` (app repo recent history) |
| 5,625 | Read | 4 | 1.1m | `qa_log.md` (handover bundle) |
| 5,512 | Read | 0 | 0.0m | slice state file (handover bundle) |
| 5,432 | Bash | 18 | 34.5m | dev-agent's final response tail |
| 5,232 | Read | 3 | 0.8m | `verification.json` (handover bundle) |

Re-read tax (`chars/4 × later_turns × $0.50/M`) for the worst offenders — small in absolute terms because none of these are individually huge and none enter *very* early with *very* many remaining turns:

| Tax | Size | Tool/turn | Later turns |
|---|---|---|---|
| $0.139 | 11,107 | Read MEMORY.md, turn 15 | 100 |
| $0.113 | 8,098 | Read brief.md, turn 3 | 112 |
| $0.108 | 7,703 | Read overview.md, turn 3 | 112 |
| $0.107 | 7,468 | Read handover.md, turn 0 | 115 |
| $0.098 | 10,040 | Read README.md, turn 37 | 78 |

**Sum of re-read tax across ALL 119 tool results: only ~$1.84 (9.8% of the session).** This is the clearest evidence that *individual big reads are not the villain* — the villain is the fixed baseline (§3.2) and the reset mechanics (§3.1), plus the orchestrator's own narrative (§3.4).

### 3.4 The orchestrator's own thinking/text is the largest "silent" growth driver

Output tokens (thinking + text + tool-call params) total 122,239 across the session — every token of it becomes part of context for all subsequent turns. The live-verify phase alone (turns 71–103, 33 turns) generated **35,909 output tokens** of narrative (planning each kubectl probe, narrating results) against only ~4,788 tokens of actual tool-result content in the same span — an **~7.5:1 ratio of "the orchestrator talking about what it's doing" to "data it ingested."** That's healthy for a human-readable transcript but it is real, permanent context weight for a long-lived session; it just happens not to compound much *here* because the session ends 13 turns later. It would compound heavily in an orchestrator that carries the same context across many slices.

### 3.5 Is it running the full suite / live-verify inline? Yes — but efficiently for the tests, poorly for live-verify

- **Test suite (turns 21–24):** run **in the background**, tail-read compactly (264–1,714 chars) — good practice, not a token sink. But it's still done by the ROOT orchestrator directly, in the same breath as later dispatching a *separate* `slice-verifier` sub-agent (turn 27, Agent call, only **738 chars** returned for verifying all 11 acceptance criteria) — two different verification mechanisms doing overlapping work, one inline and one delegated.
- **Live-verify (turns 71–103, 33 turns, $3.75 combined E4+E5):** run entirely inline — controller route discovery, token decoding, port-forwarding, planting a stranded lock file, cycling the `iotsupport` env, tailing pod logs, confirming git-config write counts, tearing down. All of this permanently swells the root orchestrator's context (~40–50k tokens added across these turns) instead of being isolated to a disposable sub-agent whose only visible artifact would be a short PASS/FAIL summary — exactly the pattern already proven cheap by the `slice-verifier` Agent call (738 chars for a whole verification pass).

### 3.6 Trello, handovers, memory — flagged as the operator requested

- **Trello:** 3 calls this session (`get_card` 2,164 chars, `get_lists` 215 chars, `move_card` 272 chars) = 2,651 chars total. Small here, but structurally the same "orchestrator fetches a full card object just to confirm a list-move" pattern the operator wants relocated into the slice bundle — worth fixing for consistency even though this session's Trello bill is only a few cents.
- **Handover bundle reads** (handover.md + brief.md + overview.md + qa_log.md + verification.json + slice-state file, all read in the first 4 turns): 39,638 chars (~9.9k tokens), all entering early (turn 0–4) and therefore paid for at every subsequent cache reset too (§3.1) — roughly **$0.6–0.7** all-in once you count the 3 re-writes. Not huge, but a textbook "read once, then never needs the full text again" case.
- **MEMORY.md:** read once (11,107 chars, the single biggest read in the session) purely to append/update one index line, and edited **5 separate times** across the session (turns 14, 16, 51, 104, 106, 110, 113) for what are each single-line changes. The orchestrator's own comment ("keeping it short — the file's already over its size limit") confirms this is a known, growing structural cost, not a one-off.

## 4. Concrete waste & what to delegate/relocate

Ranked by estimated $ impact for this one session:

1. **Fix `$JENKINS_TOKEN` provisioning so track_build actually runs.** Turns E2+E3 ($3.01, 22 turns) collapse to ~$0.30–0.40. **Highest-leverage single fix**, already self-identified by the orchestrator (it wrote a memory doc and sent a Telegram note about the gap). *Belongs: sandbox/environment provisioning, not orchestrator logic.*
2. **Delegate live-verify (E4+E5) to a dedicated sub-agent**, mirroring the existing `slice-verifier` Agent pattern (738 chars back for a full 11-AC pass). Direct turn cost today: $3.75 for ~40-50k tokens of permanent context growth; delegated, this could return a comparably-sized summary (~$0.5–0.7 to dispatch+read), for savings of roughly **$3.0–3.2**. *Belongs: a "live-verify" or "deploy-verifier" sub-agent, not the root orchestrator's own turns.*
3. **Consolidate the inline test-suite run into the same verifier sub-agent** that already runs 3 turns later (turn 27) rather than having the root orchestrator run Go/Python directly (turns 21–24) and then separately dispatch a verifier. Modest savings (~$0.3–0.5) but removes duplicated responsibility. *Belongs: the slice-verifier agent.*
4. **Cap/relocate `MEMORY.md`.** An 11k-char file that's already "over its size limit," read wholesale for single-line edits, 5+ times this session. Recommend an append/prune tool (targeted line edit without a full Read) or archiving old slice entries out of the live index. Savings modest this session (~$0.1) but the read cost is monotonically increasing per slice as the index grows. *Belongs: memory/index tooling, not manual Read+Edit.*
5. **Scope the kubectl "all objects with any kubecoder/env label" dump** (turn 89, 9,242 chars — the single largest Bash result) to the one target env-id instead of the whole cluster. Trivial fix, ~$0.02–0.05 saved here, but sets the right habit for a command this orchestrator runs on every slice's live-verify. *Belongs: the (to-be-delegated) live-verify sub-agent's own command scoping.*
6. **Move Trello card fetches into the slice bundle**, per standing operator preference. Negligible $ here (2,651 chars) but flagged for consistency — other sessions with heavier Trello use will show this cost more clearly. *Belongs: slice bundle, not live MCP calls from the orchestrator.*
7. **Structural, not really "fixable": the 3 full-context cache rewrites** ($3.87, 70% of cache_write). Not wasteful in the sense of being avoidable — long real-world waits (225 min here) will always blow a 1-hour cache TTL, and an environment/token change will always bust a cached prefix. The actionable takeaway is indirect: every token shaved off items 2–4 above shrinks the *size* of these rewrites too, so their cost drops in lockstep with general context hygiene.

## 5. Savings estimate

| Fix | Savings this session | Basis |
|---|---|---|
| Provision `$JENKINS_TOKEN` (let track_build actually run) | **~$2.6–2.7** (~14% of total) | E2+E3 ($3.01, 22 turns) → ~$0.30–0.40 (2 turns), matching turns 110–115's actual working-track_build cost |
| Delegate live-verify to a sub-agent | **~$3.0–3.2** (~17%) | E4+E5 ($3.75) → dispatch+summary-read at slice-verifier's observed rate (738 chars ≈ negligible read cost) |
| Consolidate inline test run into the verifier agent | **~$0.3–0.5** (~2%) | Removes duplicate turns 21–24 |
| Trim MEMORY.md handling | **~$0.1** (~0.5%) | Removes the 11k-char full-file read, turn 15 |
| Scope kubectl live-verify queries | **~$0.02–0.05** | Removes the 9,242-char cluster-wide dump |
| Relocate Trello fetches to slice bundle | **~$0.01** this session (larger elsewhere) | Removes 2,651 chars of live MCP fetches |
| **Total addressable** | **~$6.0–6.6 (≈32–35% of $18.78)** | Session could plausibly land near **$12–13** with no loss of functionality |

Indirect/compounding benefit not counted above: shrinking the live context by the ~50–60k tokens these fixes remove also shrinks the size of the 3 unavoidable cache-reset rewrites (§3.1) proportionally, which further reduces cache_write cost at each reset and cache_read cost on every turn until the next one — a second-order saving that grows with session length and with how many more slices this same orchestrator pattern runs per day.

**track_build ROI, stated plainly:** on unit economics it is essentially free (3 real calls, ~$0.02–0.03 all-in, a 575-character "one-screen summary" replacing what would otherwise be a 16-turn manual-polling dance). Its demonstrated, session-level ROI here is **~$2.6–2.7 saved per slice-push (≈14% of this orchestrator's total run cost)** — realized only in the single call it actually got to make, and left on the table for the rest of the session because of one missing credential.
