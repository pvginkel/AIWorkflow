# Turn Economics — Action Plan (research run 2 follow-through)

Companion to [interventions-2.md](interventions-2.md) (the memo — evidence, effect sizes and risks
live there and are not restated), [context-profile-2026-08-22.md](context-profile-2026-08-22.md)
(the numbers) and [status.md](status.md). Written 2026-08-23 at plugin 0.9.4 / Claude Code
2.1.239, before anything is built. Line numbers cite 0.9.4 and are where to look, not proof.

**Scope decision (operator, 2026-08-23).** The target is dollars, not wall-clock (parallel lanes
absorb time). The memo found no large *context* lever; what its data shows is that **the cost is
the number of model invocations** — so this plan is a more thorough attempt to cut turns per slice
without cutting what a role reads or how hard it thinks. The settled decisions in
[research-2.md](research-2.md) § Workflow context stay settled; nothing here re-opens model, effort,
review depth or loop shape.

---

## 0. The number this plan works on

- 809 sessions, **28,176 turns, $2,420 → ≈ $0.086 per turn**, and the per-turn cost is nearly flat
  across roles ($0.06 Explore/test-agent … $0.12 doc-writer) because every role sits at 50–145 k
  context and re-reads it at 0.1×. **≈ 880 turns per slice (≈ $75).**
- The memo's cost model (§4 Q2) is linear in turns for every session under ≈ 50 turns — the median
  of every role. A turn saved is ≈ 9 ¢ whatever the role; the open question is how many of the 880
  are avoidable, and by which lever.
- Writers: 1.07 tool calls per turn (8 % of turns batch ≥ 2; reviewers 1.43 / 42 %, Explore 1.82 /
  69 %), 14 orientation turns before the first edit = 38 % of the session's cost, 602 `sed -n` +
  589 `grep` orientation calls over 141 editing sessions, plan.md the most-read file. Sessions
  ≥ 80 turns are 7 % of sessions and 25 % of spend; the doc-writer alone 13 %.

**Shape.** Measure (T1) → instrument (T2) → the free set (T3) → one A/B at a time in the order T1's
numbers dictate (T4 digest, T5 batching, T6 doc phase) → T7 as an operator call. Every step ends
with *Decides*: the observation that opens the next step or stops the line. Plugin steps ship as
their own version (bump + changelog + push + marketplace update — the installed copy is a GitHub
clone) and are read on the next 2–3 slices through T2's readout before the next one ships.

## Checklist

- [x] **T1** turn taxonomy — profiler extension, regenerated profile, the avoidable-turn number — **read 2026-08-23**, below
- [ ] **T2** the context readout per run — `slice_cost.py --write-state` block + table (plugin)
- [ ] **T3a** trim the fixed prefix — env vars now; `kc` flags if the env vars fall short
- [ ] **T3b** frictions — W2 (`close_out.py` takes the report path), then T1's top fumbles
- [ ] **T4** phase-scoped orientation digest in the writer dispatch — phase-level A/B
- [ ] **T5** batched reads — why the existing rule is not followed; dispatch-line A/B (T1: below its bar — folds into T4)
- [ ] **T6** bounded doc phase — per-repo units + consistency pass; two-slice A/B
- [ ] **T7** Explore on Sonnet + the sub-agent return contract — operator call

---

## T1 — Turn taxonomy (measure; no plugin change)

**What.** Extend [tools/context_profile.py](tools/context_profile.py) with a per-turn class and a
per-turn read count, regenerate the profile, and produce the one table the memo lacks: **what the
880 turns per slice do**, per role, cost-weighted — and from it the avoidable share.

**How.** The turn dicts already carry everything needed (`replay()` :197–286: per turn `tools`
with `name`, `cmd`, `result_chars`, `is_error`; `tool_class()` :94–101; per-turn `$` via
`_tier_cost` :163–172; `first_write_turn` :404). Add in the `profile()` loop (:389–420):

- **Class per turn**, one of (first match in this order when a turn mixes calls): `dispatch`
  (Agent/Task) · `edit` (WRITE_TOOLS, plus Bash `sed -i` / heredoc or `>` redirection / `tee` /
  `git apply` — today Bash edits are invisible, :60) · `gate` · `commit` (git-mutate) · `record`
  (Edit/Write to `plan.md` or the verdict path — done-record and verdict turns) · `retry` (same
  tool re-issued within two turns after an `is_error` result, a non-zero exit, or a result starting
  `usage:` / `error:` / `No such file`) · `fumble` (`--help`, `-h`, `close_out.py list`, a `usage:`
  result, command-not-found) · `wait` (`sleep`, status polling) · `git-inspect` · `orient-read`
  (read-class call before `first_write_turn`) · `work-read` (read-class after it) · `think`
  (0 tool calls) · `other`.
- **Reads per turn**, counting read operations inside compound Bash (`;`, `&&`, `|`, `||`) — the
  profile's tools/turn undercounts batching done inside one shell command, and the harness's
  bypass-permissions instruction (every `kc` session runs `--dangerously-skip-permissions`) tells
  the model to "read with cat/sed, search with grep" — so `reads/turn` is the honest batching metric.
- **Batchable turns**: runs of consecutive read-only turns (`orient-read`, `work-read`,
  `git-inspect`); Σ(len − 1) is the perfect-batching upper bound; a stricter count keeps only turns
  whose target path already appeared in context before the previous turn's result (the read did
  not depend on what it followed).

**Output.** A §13 in the regenerated report: class × role → turns, share of role turns, $, share of
role cost; per-session medians of `reads/turn`, `retry+fumble`, `batchable` (both bounds); and one
line per slice: *avoidable = retry + fumble + batchable(strict) turns × $0.086*. Also reconcile the
memo's "136/184 writers run the gate before editing" (§1) with the profile's "9 of 141" (§8
`orient_gate`) — the memo line is wrong or mis-scoped; correct it in interventions-2.md.

**Decides.** The order and go/no-go of T3–T6 by size: `fumble + retry` ≥ 5 % of writer turns → T3b
carries weight; `orient-read` the largest class with plan reads inside it → T4; `batchable(strict)`
≥ 15 % of writer turns → T5 deserves its own A/B even though the rule exists; below those → ship
T2 + T3 only and stop the line there. **Cost** S (half a day). **Files** `tools/context_profile.py`
(`profile()` :389–420, trajectory :474–477, a new `_bd_turn_classes` printer beside `_bd_tool_volume`
:891–930 and `_bd_orientation` :933–958), a new `context-profile-<date>.md`, interventions-2.md §1.

**Read (2026-08-23).** Done: §13 of [context-profile-2026-08-23.md](context-profile-2026-08-23.md),
same 32-slice corpus. `orient-read` is the largest class — 36.6 % of headless turns, 32.9 % of their
cost (writers 28 %, reviewers 36 %, Explore 84 %; the doc-writer's largest is `edit` at 29 %, the
test-agent's is `other` at 32 %) — against `edit` 16 %, `gate` 4 %, `commit` 3 %. Avoidable =
`retry + fumble` 1,393 + `batchable(strict)` 2,162 = **3,555 turns, 12.6 %, $305** (median slice 95
of 755 turns); the perfect-batching upper bound is 10,174 turns ($874). Against the bars: T3b
**4.5 %** (below 5), T5 **8.1 %** (below 15), T4's bar met. So **T4 proceeds**; **T5 folds into T4**
instead of its own A/B — hypothesis (a) holds, writers do chain reads inside one Bash command
(1.67 per reading turn), so the 1.07 tools/turn overstated the gap; **T3b keeps its S for W2 alone**
(188 of the 1,248 fumble-and-retry turns), the rest being wrong-path guesses no hook can fix. Full
log in [status.md](status.md) § T1.

## T2 — The context readout per run (memo P4.1; plugin)

**What.** Every run writes the numbers T1 reads, so every later step is measured on the slices it
runs on rather than by a one-off replay. Per role: sessions, turns, tools/turn, reads/turn,
orientation turns (median), `ctx_first` / `ctx_mean` / `ctx_max`, `retry + fumble` turns,
`batchable(strict)` turns, prefix breaks.

**How.** The replay core is stdlib-only already (`context_profile.py` imports `slice_cost.py` via
`importlib`). Lift the per-session part (`replay`, `tool_class`, the per-turn class from T1,
`profile` minus breakdowns) into a plugin module `plugins/dev/tools/turn_profile.py` with a
`test_turn_profile.py` (fake transcripts, no agent spawned); `slice_cost.py --write-state`
(`write_state` :396–409) writes a `turns` block next to the derived I2 figures in `state["cost"]`,
`print_report` (:356–393) prints a `turns` table; the research tool imports the plugin module so
the logic lives once. Close-out: at most one short piece in the `Run:` header (`run_header`,
close_out.py :641–683) — operator's call, §Open decisions 1.

**Decides.** Done when a slice's `state.json` carries the block and `slice_cost.py` prints it; it
is the instrument, not a trial. **Cost** S–M. **Files** `slice_cost.py`, new `turn_profile.py` +
test, `close_out.py` + `plugins/dev/docs/close-out.md` if the header changes, `context_profile.py`
(import), `plugin.json` bump, changelog.

## T3 — The free set (no quality exposure; ship together as one version)

### T3a — Trim the fixed prefix (memo P1.2)

**What.** Every dispatched role starts at 31–34 k tokens (`ctx1`; Explore 12 k). The memo's
breakdown: ≈ 16 k Claude Code system prompt + tool schemas, ≈ 4.5 k preambles, 1–2 k register, and
**≈ 23 KB (≈ 6 k tokens) of listings headless roles never use** — deferred-tool names, skills,
agents, MCP instructions. What loads into a headless session comes from the user's `~/.claude`:
`~/.claude.json` MCP servers `gitblit, jenkins, kubecoder-worker, telegram, trello`, plus
`ENABLE_CLAUDEAI_MCP_SERVERS=true` in `~/.claude/settings.json` `env` (the claude.ai Trello /
Gmail / Drive / Calendar / Atlassian servers), both plugins' skills and agents, and auto-memory.

**How, in order of reach.**

1. Env vars through `run_kc_session`'s `extra_env` (`SPAWN_ENV`, run_loop.py :175 — today only
   `FORCE_PROMPT_CACHING_5M=1`): `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` for every role;
   `ENABLE_CLAUDEAI_MCP_SERVERS=false` for every role but the test-agent — **verify first** whether
   a `-e` var beats the settings `env` block (kc's help says "pass-through wins"); measure `ctx1`
   before/after on one dispatch of each role.
2. If the listings survive step 1: a small `kc` change. The spawn argv is the operator's own code
   (KubeCoder `worker/internal/headless/process.go` :47–63: `--print --dangerously-skip-permissions
   --output-format stream-json [--resume] [--agent] [--model] [--effort]`); add pass-through flags
   to `kc session create-headless` for `--disallowedTools`, `--strict-mcp-config` /
   `--mcp-config`, `--disable-slash-commands` so `run_kc_session` can pass a per-role trim: writers,
   reviewers, doc-writer, consult → no MCP servers, no skills; test-agent keeps `jenkins`. Explore
   and other sub-agents inherit the parent's trim for free. Not `--bare`: it skips hooks (kc's own
   `SessionStart` recorder) and plugin loading (the `dev:` agents).

**Decides.** `ctx1` per role from T2 (target −5–6 k on every turn ≈ 4 % of spend); zero quality
exposure. Portability: env vars and flags are generic; nothing names a project. **Cost** S (+ S in
KubeCoder for step 2). **Files** run_loop.py :175 and :614–625, `plugins/dev/docs/agent-dispatch.md`
§ Spawning (the flag list), KubeCoder `process.go` + `kc` CLI if step 2.

### T3b — Frictions at the point of use (memo P3.2 + W2)

**What.** Turns spent re-learning the tooling. Known today: `close_out.py` is called 85 times in
145 writers' orientation phases — every subcommand takes `slice_dir` (argparse :716–761) and the
agents pass the report path, get an error, run `list` / `--help`, retry (**W2**). T1's `fumble` and
`retry` classes name the rest.

**How.** W2 first: accept a `.md` path as the positional and use its parent; contract line in
`plugins/dev/docs/close-out.md`. Then the top fumbles from T1 — designed away where the tool can be
fixed; otherwise delivered by a plugin hook: `plugins/dev/hooks/hooks.json`, `PostToolUse` on a
Bash result matching a known pattern → `additionalContext` with the correct invocation. Hooks run
under `kc`'s `-p` spawn (the user-level `SessionStart` hook `record_session.sh` is how kc records
its sessions) — confirm with one `PostToolUse` hook on one dispatch before relying on it; each hook
that fires costs tokens, so ≤ 3 measured fumbles, after W2. Nothing goes into a preamble or register (the register-growth
discipline is satisfied by construction).

**Decides.** T2's `fumble + retry` per session → ≈ 0 on the next two slices. **Cost** S. **Files**
`close_out.py` + `test_close_out.py`, `plugins/dev/docs/close-out.md`, new `plugins/dev/hooks/` if
used, bump + changelog.

## T4 — Phase-scoped orientation digest in the writer dispatch (memo P3.1; A/B at phase level)

**What.** Today `EXECUTOR_PROMPT` (run_loop.py :794–811) opens "Read the whole plan" and
code-writer.md :6–8 says "read the whole plan (it is small by design)" — plans are 15–74 KB, plan.md
is the top orientation read (128 Reads + 30 `cat` over 141 sessions, and the `cat` spills to a 1.3 MB
persisted-output file that is then Read whole), and the writer spends 14 turns re-deriving what the
driver already knows. The driver parses phases (`parse_plan` :367–397, `Phase.body`,
`resolve_target` :358–363), owns git and the gate command.

**How.** `build_phase_digest()` in run_loop.py, rendered into the dispatch: the slice's intent
paragraph; **this phase's full section**; the done-records of earlier phases (the contract caps each
at ~25 lines, so verbatim is bounded — no plan-format change, §Open decisions 3); the headings +
`Target:` lines of later phases (the writer may have to edit them); the acceptance criteria
(`verification.json`, all of them — they are short); files touched by prior phases (`git diff
--stat` base..HEAD); the gate command. The prompt changes to "your phase and what settled before it
are below; the plan is at {plan_path} — edit it there (done-record, later phases)"; code-writer.md
:6–8 follows. Size target 3–5 k tokens. Reviewer dispatch unchanged (its re-read is a feature).

**Pre-checks (cheap, offline, before the A/B).** (a) The Claude-specific quality instrument: grep
the 32 slices' review files for abstention verdicts ("cannot determine", "unable to verify",
non-attempt) — the baseline count, one hour. (b) The failure-pair check (memo §6): re-dispatch two
completed phases from their merge-base with the digest prompt on a scratch branch (≈ $4 each) and
diff the outcome against the recorded one — verdict, gate, reviewer findings.

**A/B.** Phase-level: alternate arms within a slice by queue position (each phase is a fresh
session, so arms do not contaminate), recorded per phase in `state.json` (as A3 recorded
`writer_effort`) and printed by `slice_cost.py`; n ≥ 5 phases per arm, paired by size band; one
variable. Cost side: orientation turns, plan reads per session, `ctx` at first edit, $/phase.
Quality side: r1 blocking-finding rate, refuted findings (baseline 0), gate-red, rework share
(baseline 2–19 %, median ≈ 7 %), abstention verdicts, appended phases. Kill: § Protocol.

**Decides.** Expected ≈ 15–20 % of writer spend (≈ 5 % of total) — recheck against T1's
`orient-read` share first. **Cost** S–M. **Files** run_loop.py (`EXECUTOR_PROMPT` :794–811,
`spawn_executor` :2220–2233, `parse_plan`/`Phase` :350–397), `test_run_loop.py`, code-writer.md
:6–8, `plugins/dev/docs/run-loop.md` § The per-phase round (:56–58), `agent-dispatch.md`.

## T5 — Batched reads (memo P1.1): the rule exists and is not followed

**What.** code-writer.md rule 11 (:56–59), doc-writer.md rule 7 (:34–35) and code-reviewer.md rule
10 (:70–71) already say *"Batch independent tool calls into one message"* — and writers do 1.07
tools/turn. T5 is therefore not a sentence to add; it is finding what the writer complies with.

**Hypotheses, tested in T1 first, then one at a time.** (a) The writer batches *inside* one Bash
call — T1's `reads/turn` settles how much of the gap is real. (b) The harness instruction under
`--dangerously-skip-permissions` ("do your work through the Bash tool: read with cat/sed, search
with grep") steers every headless session to serial shell calls; it cannot be removed (kc always
passes the flag), but the register can counter it for reads — "use Read/Grep/Glob, several per
message" — an A/B. (c) Orientation chains (`grep` → `sed -n` on what it found) are genuinely
sequential; T4 removes most of the chain, so T5's reach shrinks after T4 — run T5 after T4's first
read. (d) Position: the rule is 11th of 12 in a 74-line register; one line in `EXECUTOR_PROMPT`
(the first thing read) is the cheaper experiment — an A/B against the register-only arm.

**Measure.** tools/turn, reads/turn, `batchable` (both bounds) per session; quality per § Protocol.
**Decides.** Expected ≤ 8–12 % of writer spend on the memo's arithmetic, realistically a few % after
T4; keep whichever arm moves `batchable(strict)` without moving a quality instrument. **Cost** S.
**Files** run_loop.py `EXECUTOR_PROMPT`, code-writer.md / doc-writer.md (the existing rule, not a
new one), bump + changelog.

## T6 — Bounded doc phase (memo P2.1; M; two-slice A/B)

**What.** The doc-writer is 32 sessions, $318 (13 %), 66 turns median and up to 192, 144 k mean
context — the only role where cutting the session pays on the real trajectories (20 % of its spend,
24/32 sessions). MemDocAgent and Kim et al. support per-unit work plus a verifying consistency
pass; the operator's doc fix-nows at close-out are the quality readout.

**How.** Units = **the repos in the slice's diff ranges**, in dependency order (the driver already
has `diff_ranges` per repo for `DOC_PHASE_PROMPT`, run_loop.py :1181–1197, spawned at :3033–3038):
one doc-writer session per repo, sequential, each given that repo's range and the done-records;
then one non-writing **consistency session** over the docs diff of all units (cross-surface
contradictions, a claim that moved, a name that differs) whose findings go to `close-out.md`.
Single-repo slices are unchanged, so the split bounds exactly the sessions that blew up (the
four-repo 170 doc-writer: 192 turns, $33). The per-doc-surface variant needs a project-side unit
list and is §Open decisions 5.

**A/B.** Two comparable multi-repo slices per arm; cost side: doc-phase $ and share, `ctx_max`;
quality side: consistency-pass findings, operator doc fix-nows, a sampled read of the docs.
**Decides.** Expected −20–35 % of doc-writer spend (≈ 3–4 % of total) at `ctx_max` < 150 k; the
coordination tax (more fixed prefixes) is the cost to watch. **Cost** M. **Files** run_loop.py
(`DOC_PHASE_PROMPT`, the doc-phase spawn), doc-writer.md, `plugins/dev/docs/run-loop.md`,
`close-out.md` contract (the consistency entries), tests, bump + changelog.

## T7 — Explore on Sonnet + the sub-agent return contract (memo P3.3; operator call)

**What.** 148 Explore sessions, $153 (6 %), 116 of them on Opus by inheritance — the built-in
Explore lost its Haiku pin at Claude Code 2.1.198 (we run 2.1.239); Sonnet-priced they are $102
(−2 % of spend). Explore locates, it does not judge; whether the "no weaker model as writer or
reviewer" settlement covers it is the operator's call.

**How.** A plugin agent `dev:explore` with `model: sonnet` in its frontmatter (as test-agent.md :4
pins), dispatched by name from the three registers that use Explore (plan-writer, plan-reviewer,
doc-writer) instead of the built-in; check first whether a newer Claude Code restored the pin. The
return contract (MAST's hygiene): a four-line shape in those dispatch templates — answer,
`file:line` evidence, verified vs asserted, what was not found. **Decides.** Explore cost from T2;
the contract's value is unmeasured and small in tokens. **Cost** S.

---

## Protocol (condensed from memo P4.2) and kill signals

One variable per trial; pair by project and phase-size band; n ≥ 5 phases per arm (T4, T5) or two
slices per arm (T6); fixed plugin version, model, effort and prices for the trial's duration; cost
by T2's cache-adjusted dollars. Quality instruments, all already recorded: r1 blocking-finding
rate, refuted findings (baseline 0 over 155–170), gate-red, rework share (baseline 2–19 %, median
≈ 7 %), abstention verdicts (T4 pre-check a), operator fix-nows at close-out. **Kill:** any
instrument outside the baseline range on two consecutive slices, or cost not below baseline. Early
signal: trajectory-length variance and wrong-file edits, not length.

## Deliberately not in this plan

Auto-compact windows (memo P2.2), shaped tool output via hooks (P4.3) — protocol only, likely
negative with Claude; effort or model changes for writers and reviewers; turn or token caps; the
1-hour cache; parallel writers; a retrieval layer; summarisation of writer or reviewer history.
Memo §6 has the reasons.

## Bookkeeping

- One chapter per shipped step in [status.md](status.md), ids T1–T7, the existing template; the
  memo stays the evidence; this checklist is the working view. T1 is research-only (`research:`
  commit); T2–T6 are plugin changes (`dev:` commits, bump + changelog); T3a step 2 is a KubeCoder
  change under that repo's conventions.
- After each plugin step: push, marketplace update, then read the next 2–3 slices through T2 before
  the next step ships. T3a and T3b can share one version; T4, T5, T6 one at a time.

## Open decisions at implementation time

1. **T2 surface.** `slice_cost.py` table + `state.json` block only, or also one piece in the
   close-out `Run:` header (recommended: table + block; the header stays as it is).
2. **T3a reach.** Stop at env vars, or make the `kc` flag change (recommended: do both — the flags
   are what reaches the listings).
3. **T4 digest content.** Earlier done-records verbatim (bounded at ~25 lines each, no format
   change — recommended) or a machine-readable "settled" marker in `plan-template.md`.
4. **T4 arm assignment.** Per-phase alternation within a slice (recommended; fastest to power) or a
   per-slice flag.
5. **T6 unit.** Per repo (no project contract change — recommended) or per doc surface from a
   project-side list.
6. **T7.** Whether the Sonnet pin for Explore falls under the settled "no weaker model" line.
