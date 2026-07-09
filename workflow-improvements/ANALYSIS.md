# Execution-history analysis — KubeCoder slice runs

**Purpose.** Source material for a *secondary* analysis (a different agent) aimed at improving the
AI slice workflow. This document does **not** propose fixes — it collects evidence: what the agents
actually did, where the money and wall-clock went, and which behaviours are noteworthy for the
workflow-improvement work described in Trello card #175. Findings are tagged with the card thread
they bear on, e.g. `[#175: Test agent]`.

Scope requested by the operator: attribute cost per *slice*, pick **3** slices that are both
expensive and illustrative, exclude slices **066/067** (Sonnet-vs-Opus comparison runs), and draw
from slices that ran **before 2026-07-04**. Deep-read a few noteworthy conversations per slice.

Everything here is reproducible from the tooling and CSVs in [`data/`](data/) — see §6.

---

## 1. Method

Two properties of these runs make naive token accounting misleading; the tool
([`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py)) handles both.

**Count the managers, not just the sub-agents.** A slice is driven by **top-level "manager"
sessions**: the root orchestrator running `run-slice`, plus the per-project sessions
(`controller`/`worker`/`bot`/`contracts`/`vscode-extension`) that `claude_session.py` starts and
resumes. Counting only the `*/subagents/agent-*.jsonl` files misses these entirely — yet they are
**the majority of spend** (see §2). This analysis counts *all* conversations, attributed per slice,
broken down by role (`manager:<project>` vs `subagent:<type>`).

**Dedup by `message.id`.** The stream-json transcript writes each assistant message multiple times
with an identical `message.id` and identical `usage` (observed up to 5× for one message), so summing
every record overcounts. This analysis keeps **one billed record per `message.id` per file**.
Corpus-wide: **43,001 billed messages behind 106,576 raw records — summed naively that is 2.48×.**

**Attribution.** All sessions run on `git main` (there is no branch-per-slice yet), so slices are
identified by content: the dominant `slice NNN` mention across each transcript and its sub-agents'
task descriptions (sub-agents inherit their parent session's slice). Clustering is a good check —
most slices' manager sessions fall inside a 0–2 day window, which validates the attribution; a few
early/long-lived slices (003, 004, 026, 031) show multi-day bleed and are treated with caution.

**Cost / wall-clock semantics.**
- USD is *derived* from public sticker prices, not billed data. (The persisted transcripts carry raw token `usage` only — **no cost field**; the stream-json `result` event that has `total_cost_usd` is emitted to stdout during a run but never written to the log, so cost must be derived.) These runs were most likely on a **Claude subscription** — main sessions write 1-hour cache and sub-agents 5-minute, which is Claude Code's automatic subscription behaviour — so the derived USD is an **API-equivalent** measure of token *consumption*, not an out-of-pocket bill. The **relative** split across roles (and the token volumes) is the robust, actionable part.
- **`active_h`** = sum of per-conversation durations (start→end of each transcript, includes in-session idle). Overlapping parallel work is double-counted, so read it as an effort proxy, not wall time.
- **calendar span** = first→last conversation timestamp of the slice (includes overnight/idle days).
- **`longest_h`** = the single longest conversation — the most useful "how long did one session sit open" number.

**Caveats.** Slice attribution is heuristic (dominant-mention). The dedup keeps the first record per
`message.id`; if the harness ever logged a *growing* usage under one id we would undercount, but
observed duplicates were identical. Cross-repo work (a slice that also touched `HelmCharts`/
`DockerImages`, which live in other project folders) is **not** folded in — these numbers are the
KubeCoder-repo portion only.

---

## 2. Corpus-level findings (the headline)

Deduped, all-in, across all 6 KubeCoder project folders (1,338 conversations):

| Bucket | Cost | Share |
|---|--:|--:|
| **Grand total (deduped)** | **≈ $5,223** | 100% |
| Manager / top-level sessions | $3,527 | **68%** |
| ─ of which **root orchestrator** | $2,763 | **53%** |
| ─ of which per-project managers | $764 | 15% |
| Sub-agent transcripts | $1,696 | 32% |

The headline for the secondary analysis:

**The orchestrator is the cost centre, not the sub-agents.** The single most expensive "agent" in the
whole system is the **root orchestrator session** at **53% of all spend** — a long-lived session that
re-primes CLAUDE.md + slice context on every resume, holds 200–330k-token contexts for hours, and
personally runs the full test suite (and, in separate post-push sessions, live-deploy verification).
This is exactly the target of `[#175: Test agent]` and `[#175: Context management]`, and it is easy to
miss entirely if you look only at the sub-agents.

Per-token-type, cost is overwhelmingly **`cache_read`**: long-lived contexts mean every turn re-reads
a large prompt. In the deep dives below, `cache_read` is 95–99% of tokens on the expensive sessions.
The lever is context size × turn count, not output volume.

---

## 3. Slice ranking and selection

Eligible pool = ran before 2026-07-04, excluding 066/067. Top of the all-in ranking
(full table in [`data/slice_ranking.csv`](data/slice_ranking.csv); `root%` = orchestrator share):

| slice | cost | root$ | root% | tok(M) | conv | mgr | sub | active_h | longest_h | dates | eligible |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|:--:|
| 003 | $283 | $150 | 53% | 354 | 80 | 11 | 69 | 29.0 | 10.4 | 06-19→06-25 | ✅ |
| **052** | **$273** | $128 | 47% | 315 | 57 | 13 | 44 | 42.1 | 14.0 | 06-26→07-04 | ✅ **picked** |
| 058 | $183 | $63 | 34% | 246 | 22 | 6 | 16 | 15.7 | 4.6 | 06-27→07-05 | ✅ (straddles) |
| **044** | **$171** | $65 | 38% | 217 | 44 | 10 | 34 | 19.2 | 10.4 | 06-26→07-03 | ✅ **picked** |
| **038** | **$163** | $115 | 70% | 172 | 49 | 15 | 34 | 30.0 | 9.8 | 06-26→06-28 | ✅ **picked** |
| 012 | $154 | $103 | 67% | 177 | 42 | 11 | 31 | 17.6 | 7.9 | 06-21 | ✅ |
| 004 | $141 | $59 | 42% | 170 | 42 | 7 | 35 | 90.8 | 71.1 | 06-20→07-06 | ⚠ idle/bleed |

**The three selected** (expensive **and** illustrative of *distinct* waste patterns):

- **052 — the full task/loop workflow at scale.** 5 projects, the complete plan→plan-review→
  code→code-review loop (plan-writer ×6, plan-reviewer ×6, code-writer ×9, code-reviewer ×8), and a
  **14-hour** root session that ran on `claude-fable-5`. Best exhibit for the loop restructuring and
  model-choice threads.
- **038 — orchestrator-dominated / context re-priming.** 70% of the slice's cost is the root
  orchestrator, spread across **12 distinct orchestrator sessions** for one slice. Best exhibit for
  context management and orchestrator cost.
- **044 — the code-writer monster.** Two `code-writer` sub-agents at ~42M tokens / $24 / 167–172
  turns *each*, one implementing a whole 4-part plan and running the full workspace suite itself.
  Best exhibit for task-splitting and "take testing out of the code-writer."

**Honourable mentions (not deep-read):** **003** is the single most expensive slice, but it is an
early slice (06-19, before the agent workflow matured) and spawned **69 `general-purpose` sub-agents**
(a pre-maturity pattern, $85), so it is less representative of the current workflow. **012** has the
cleanest attribution (all conversations on 06-21) and a 67% orchestrator share — a good confirmatory
second data point for the 038 pattern.

---

## 4. Deep dives

### 4.1 Slice 052 — `env_rename` — $273, 57 conversations, 5 projects

Top conversations (by cost):

| role | id | model | turns | tokens | cost | dur |
|---|---|---|--:|--:|--:|--:|
| manager:root | 340e107e | opus-4-8 | 279 | 71.9M | $45.78 | 405m |
| manager:root | c28a671f | **fable-5** | 115 | 26.2M | $44.80 | **841m (14h)** |
| manager:root | 4ff7954f | opus-4-8 | 127 | 29.9M | $22.92 | 659m |
| manager:bot | fdcd8161 | opus-4-8 | 98 | 22.1M | $19.50 | 118m |
| manager:controller | 78d5a6f7 | opus-4-8 | 68 | 11.7M | $10.89 | 62m |
| manager:worker | 2d6b1b09 | opus-4-8 | 64 | 10.6M | $9.97 | 63m |
| subagent:code-writer | ad3b136a | opus-4-8 | 93 | 14.5M | $8.50 | 10m |
| subagent:code-writer | ab7202c4 | opus-4-8 | 79 | 12.7M | $7.88 | 10m |
| … | (4 code-writers ≈ $8 each, then plan-writer ×6, plan-reviewer ×6, code-reviewer ×8) | | | | | |

Role totals: root $128 (47%) · code-writer $39 · plan-writer $13 · code-reviewer $12 · plan-reviewer
$10 · per-project managers $58.

**What happened / noteworthy:**

- **Three separate root orchestrator sessions ($46 + $45 + $23 = $114)** drive one slice, plus one
  per project. The 279-turn `340e107e` and 127-turn `4ff7954f` are long orchestration sessions;
  their cost is almost entirely `cache_read` from a context that grows across the run.
  `[#175: Context management]`
- **A 14-hour root session (`c28a671f`) ran on `claude-fable-5`** — the most expensive model in the
  table ($10/$50 per Mtok). Its work was 8 deploy/k8s Bash calls, Jenkins/Trello MCP calls, and
  `SendUserFile` — i.e. **waiting on a live build/deploy and reporting**, exactly the work the card
  wants delegated to a cheap **Sonnet** test/deploy agent. Running deploy-wait orchestration on
  Fable-5 for 14h is the inversion of the intended model economics. `[#175: Test agent]`
- **The per-project manager crafts large custom dispatch prompts.** The controller manager
  (`78d5a6f7`) emitted a **2,924-output-token** prompt to dispatch a code-writer ("add missing rename
  tests") and a 1,355-token prompt to a plan-writer revision. The manager is already doing the
  "explain how to use the sub-agent" job that `[#175: Targeted issues]` wants to be the norm — good
  evidence that customization belongs in the manager, not the agent definition. But note the manager
  itself carries a ~200–230k `cache_read` context while doing it.
- **The loop ran many rounds:** 6 plan-writers + 6 plan-reviewers + 9 code-writers + 8 code-reviewers
  across the slice. This is the unbounded-loop shape `[#175: Multiple tasks]` wants to bound (3
  writer/tester rounds, 2 review rounds) and split into isolated tasks.

### 4.2 Slice 038 — `worker_cli_taxonomy` — $163, 49 conversations, root 70%

**12 distinct root orchestrator sessions for one slice**, over three days (06-26 → 06-28):

| start | id | turns | cost | dur | slice-038 mention share |
|---|---|--:|--:|--:|---|
| 06-26 07:19 | 30e6ba1e | 45 | $9.61 | 385m | 9/25 |
| 06-26 07:56 | e7e4e40a | 91 | $15.72 | 213m | 19/108 |
| 06-26 11:31 | 142023d6 | 55 | $7.62 | 55m | 23/55 |
| 06-26 12:24 | 884ea7f8 | 7 | $0.71 | 1m | 4/9 |
| 06-26 12:26 | 4b886491 | 34 | $2.89 | 5m | 8/30 |
| 06-26 16:23 | 8764866d | 63 | $12.13 | 125m | 19/109 |
| 06-26 18:22 | 37d7eebf | 61 | $8.90 | 44m | 23/55 |
| 06-26 18:43 | 95f6282b | 62 | $15.43 | 61m | 31/179 |
| 06-26 19:27 | f4c71334 | 5 | $0.71 | 2m | 1/5 |
| 06-27 06:54 | 2570fd6b | 101 | $23.35 | 589m | 171/585 |
| 06-27 17:35 | 4edc6b17 | 123 | $16.19 | 115m | 106/165 |
| 06-28 12:19 | 17917f15 | 20 | $1.32 | 2m | 15/44 |

Role totals: root $115 (**70%**) · worker manager $8 · code-writer $9 · everything else < $8.

**What happened / noteworthy:**

- **The orchestrator is re-entered ~12 times for one slice.** Each re-entry re-primes the root
  `CLAUDE.md` (263 lines) + slice context and re-grounds — a fixed tax paid a dozen times. This is
  the mechanical cause of the 70% orchestrator share, and it matches the operator's own note (seen in
  a later 073 session): *"I had to start a new conversation to manage context."* `[#175: Context management]`
- The two biggest orchestrator sessions sit open for **~10h and ~6.4h** (`2570fd6b` 589m,
  `30e6ba1e` 385m) with relatively few turns — long idle stretches (waiting for builds/deploys)
  while a large context stays live and is re-read on the next resume. `[#175: Test agent]`
- **`Explore` sprawl:** 17 `Explore` sub-agents, most $0.3–0.7 — cheap individually but a long tail.
  Worth noting for whether repeated re-exploration is a symptom of context loss across the 12 re-entries.
- Even the several tiny root sessions (5–20 turns, 1–5 min) each pay the CLAUDE.md re-priming cost
  for very little work — a sign the orchestrator is being bounced in and out.

### 4.3 Slice 044 — `worker_private_state` — $171, code-writer-dominated

Top conversations:

| role | id | turns | tokens | cost | dur | note |
|---|---|--:|--:|--:|--:|---|
| manager:root | d9ea7958 | 163 | 35.2M | $28.14 | 622m (10.4h) | ran full suite + live pod verify |
| **subagent:code-writer** | **ac352744** | **167** | **41.9M** | **$24.24** | 26m | controller half, whole 4-part plan |
| **subagent:code-writer** | **ae678c70** | **172** | **42.0M** | **$23.14** | 26m | worker half |
| manager:root | 130b2590 | 80 | 14.0M | $12.70 | 63m | |
| manager:worker | 1682c641 | 67 | 10.8M | $10.02 | 75m | |
| manager:controller | 949dcc0d | 53 | 8.4M | $7.65 | 73m | hosts code-writer ac352744 |

**What happened / noteworthy — the star exhibit (`code-writer ac352744`):**

- **One code-writer conversation implemented an entire 4-part plan** ("Slice 1: cache+projection,
  Slice 2: wiring, Slice 3, Slice 4") in **167 turns**. This is the plan-writer's
  *"### 14) Implementation slices (only if large)"* mechanism in action: internal sub-slices packed
  into a single plan, executed by a single long-lived code-writer. `[#175: Multiple tasks]` wants
  this broken into **separate PR-sized tasks**, each its own folder/branch and fresh context.
- **Cost is context, not output.** Of 41.9M tokens, **41.4M is `cache_read`**; output was 6.3k tokens
  total. The conversation reads ~15 source + test files up front — the context climbs
  **4k → 210k → 330k** — and then every one of 167 turns re-reads that ~330k context. `[#175:
  Multiple tasks]` calls for "limited grounding overlap across tasks"; this is what unlimited overlap
  costs.
- **The code-writer runs the full test suite itself, repeatedly** — "Run controller test suite after
  slice 1" (602 passed), then notifications+context tests, slice-3 tests, slice-4 events tests, then
  a **final full-workspace pytest across controller + worker + bot + contracts** (1050 passed) plus
  ruff. All on Opus, inside the ballooning context. `[#175: Test agent]` wants this pulled into a
  separate **Sonnet** agent with its own fresh context.
- **The two code-writers together = $47 / 84M tokens.** They are the single biggest lever in the
  slice, and both are the same shape (one plan each, tests inline, huge context).
- **Handover/companion docs are large:** the biggest tool-results the code-writer read were the plan
  (57k chars), source files (35k/30k/28k), and the `file_map.json` / `requirements.json` companions
  (22k/14k chars). `[#175: Targeted issues]` — "hand-over documents may be trimmed significantly."
- **The root orchestrator (`d9ea7958`, 10.4h) again does the expensive tail itself:** seeds
  `verification.json`, commits to the specs repo, runs the **full Python workspace suite**, then does
  **live-pod verification** on a fresh cluster pod ("Inspect worker-side state on the fresh pod",
  "Verify session-report round-trip") — with a multi-hour idle gap (189m → 614m) waiting on the
  build, context held at 330k throughout. `[#175: Test agent]`

---

## 5. Cross-cutting patterns → card #175

Recurring signals across all three slices (and the corpus), for the secondary analysis to act on:

| Pattern (evidence) | Card #175 thread |
|---|---|
| **Root orchestrator = 47–70% of slice cost, 53% of all spend**; invisible to current tooling. | Test agent; Context management |
| **Orchestrator re-entered many times per slice** (038: 12×), each re-priming CLAUDE.md + context. | Context management; CLAUDE.md review (trim root) |
| **Cost is `cache_read` from large, long-lived contexts** (95–99% of tokens on expensive sessions). | Multiple tasks (grounding overlap); Documentation diet |
| **Testing runs inside the code-writer** (full workspace suite, on Opus, in a 330k context). | Test agent; Targeted issues (code-writer) |
| **Full E2E suite run by the orchestrator itself** during `/run-slice` (`run-slice.md:249-257`); **live-deploy verification** runs in *separate* post-push orchestrator sessions (`/run-slice` is gated from deploy, `run-slice.md:338`). Both are root-session cost, with multi-hour idle waits. | Test agent |
| **A single code-writer implements a multi-part plan in 160+ turns** (the "Implementation slices" mechanism). | Multiple tasks; Triage/slice-writer resizing |
| **Unbounded plan/code/review loops** (052: 6+6+9+8 sub-agents). | Multiple tasks (bound the loops) |
| **Model mismatch**: 14h deploy-wait orchestration on `fable-5`; all testing on Opus. | Test agent (use Sonnet) |
| **Large companion/handover docs** (plan 57k, file_map/requirements 14–22k chars) re-read every turn. | Targeted issues (trim handovers) |
| **Agent definitions may be near-irrelevant to cost**: cost is dominated by context size and turn count in managers, not by agent-file guidance — consistent with the operator's note that runs succeeded even when agent files failed to load. | Targeted issues (trim agent files hard) |

**One framing for the secondary pass:** the workflow's dominant cost is not the sub-agents the card
spends most words on — it is the **manager/orchestrator sessions' context economics**. Splitting work
into isolated tasks with fresh contexts, moving testing/deploy-waiting out to cheap fresh agents, and
shrinking what every session re-reads (CLAUDE.md, docs, handovers) all attack the same root cause:
**tokens = context size × turns, and the orchestrator maximises both.**

---

## 6. Reproduce / data appendix

Tooling and outputs — the reusable cost tool is at [`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py); the deep-read helper and generated CSV/JSON are in [`data/`](data/):

- **`tools/analysis/slice_costs.py`** — slice attribution + all-in cost/wall-clock, deduped by `message.id`.
  Run: `python3 tools/analysis/slice_costs.py` (defaults to `~/.claude/projects/-work-KubeCoder*`).
  `--slice NNN` prints per-conversation detail for one slice.
- **`digest.py`** — compact turn-by-turn digest of a single transcript (tool histogram, Bash-by-intent,
  context growth, biggest I/O). Run: `python3 data/digest.py <transcript.jsonl> [--grep pytest] [--tail N]`.
- **`slice_ranking.csv`** — one row per slice: cost, tokens, turns, raw_turns, conv/mgr/sub counts, calendar span, active_h, per-project manager counts.
- **`sessions.csv`** — one row per conversation: slice, kind, role, project, agent type, session id, start/end, duration, turns, raw_turns, tokens, cost, attribution note.
- **`slice_roles.json`** — per-slice role breakdown (`manager:<project>` / `subagent:<type>`).

Transcripts read for the deep dives (paths under `~/.claude/projects/`):
`-work-KubeCoder-controller/949dcc0d…/subagents/agent-ac352744…` (044 code-writer),
`-work-KubeCoder-worker/1682c641…/subagents/agent-ae678c70…` (044 code-writer),
`-work-KubeCoder/d9ea7958….jsonl` (044 root), `-work-KubeCoder/c28a671f….jsonl` (052 root, fable-5),
`-work-KubeCoder/2570fd6b….jsonl` (038 root), `-work-KubeCoder-controller/78d5a6f7….jsonl` (052 controller manager).

**Known limitations:** heuristic slice attribution (dominant-mention); USD is derived from sticker
prices; `active_h` double-counts parallel work; cross-repo (HelmCharts/DockerImages) portions of a
slice are excluded; a stray `slice 185`/`none` bucket collects ad-hoc, triage, and DAG sessions
(≈$364) that are not slice work.
