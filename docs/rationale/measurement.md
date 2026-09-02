# Measurement — mining the conversations, and the research method

How the workflow is measured: what a run leaves on disk, the tools that replay it, what they
measure and what that found, the aggregate over today's corpus, and the method a research run
follows from briefing to readout. The papers the research read are in [literature.md](literature.md);
the close-out report's own numbers are in [reporting.md](reporting.md); what each finding changed
in the plugin is catalogued in [improvements.md](improvements.md). The record formats themselves are
the contract's — [runner-state.md](../../plugins/dev/docs/runner-state.md) — and are only named
here.

## What a run leaves behind

Every measurement below reads two kinds of file, and nothing else.

- **The slice folder.** `state.json` holds an append-only `history`: one row per agent run, gate
  run, loop-tail sweep, doc gate and consult, each with `role`, `phase`, `round`, `outcome`, a
  one-line `summary`, `duration_s`, the session id and the **path of that session's transcript**
  ([runner-state.md § state.json](../../plugins/dev/docs/runner-state.md#statejson)). A
  code-reviewer row also carries the verdict's per-finding `findings` list (id, severity, impact,
  category, anchor) and a fix-round writer row its `refuted` list. `plan_state.json` is the plan
  loop's equivalent. Beside them sit `phases/P<id>/` (review markdown, verdict JSON, gate logs),
  the consult and test/doc result files, `sweeps/`, `doc_phase/<repo>.diff`, and `close-out.md`.
  `/dev:run-slice` commits `state.json` and `log.txt` with the slice at close-out, so the folder is
  the run's complete who-did-what record.
- **The transcripts.** Claude Code writes each session as JSONL under `~/.claude/projects/<cwd
  slug>/<session-id>.jsonl`, with its sub-agents under `<session-id>/subagents/agent-*.jsonl`.
  Every assistant message carries `usage` — `input_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `output_tokens`, and thinking tokens in
  `output_tokens_details` — which is all the pricing and the context profiling need. Transcripts
  carry no cost field: dollars are derived from public sticker prices
  (`slice_cost.py`'s pricing table), so every dollar figure in this repo is an API-equivalent
  measure of consumption, not a bill (the runs are on a subscription —
  [ANALYSIS.md § 1](../../workflow-improvements/ANALYSIS.md)).

The state files are the session list. That is the point of recording transcript paths: attribution
is mechanical — a session belongs to a slice because the driver wrote it there — where the first
measurement (July 2026) had to infer a slice from the "slice NNN" a transcript happened to mention
([ANALYSIS.md § 1](../../workflow-improvements/ANALYSIS.md)).

## The tool chain

| Tool | Lives in | Reads | Answers |
|---|---|---|---|
| [`slice_cost.py`](../../plugins/dev/tools/slice_cost.py) | plugin | a slice's `state.json` + `plan_state.json`, the transcripts they name, their sub-agents | what the run cost: totals, per role, per phase, per session; the `derived` ratios (planner, research, rework share); the per-role turn table. `--write-state` appends it all to `state.json` as `cost` |
| [`turn_profile.py`](../../plugins/dev/tools/turn_profile.py) | plugin (library, no `main`) | one transcript | the replay: ordered turns with usage, tool calls and results, each turn in exactly one class; per-session metrics (`ctx_first/mean/max`, orientation, retry/fumble, batchable, prefix breaks) |
| [`context_profile.py`](../research/tools/context_profile.py) | research | slice dirs (sessions enumerated as `slice_cost.py` does) | the per-turn context trajectory, cache-tier split, prefix breaks, thinking retention, tool and re-read mix, orientation span, sub-agent overlap, what-if cuts, and the `--breakdown` turn taxonomy |
| [`t4_readout.py`](../research/tools/t4_readout.py) | research | new slices + the 32-slice corpus | before/after a plugin version: writer sessions, $/phase, quality instruments, every `plan.md` touch |
| [`risk_readout.py`](../research/tools/risk_readout.py) | research | spec-repo git, `state.json` telemetry, review markdown, processed close-outs | per phase what was touched, found, refuted and dispositioned, scored against a path-risk map (#715) |
| [`doc_split_whatif.py`](../research/tools/doc_split_whatif.py) | research | doc-writer trajectories | what a *k*-unit split of the doc phase would cost |
| `plan_qa_readout.py` | research — **in the other checkout**, not in this one | plan-slice transcripts of both projects | every `AskUserQuestion` dialog: the recommendation, the answer, whether it deviated (the 2026-09-01 interview readout, [plan-refinement.md](plan-refinement.md)) |
| [`digest.py`](../../workflow-improvements/data/digest.py) (with `slice_costs.py`, retired in v0.4.0 and no longer in the tree) | frozen R&D trail (July 2026) | template-era transcripts | the first cost attribution, before the loops existed |

The plugin ships the first two because they read a format the plugin owns and every run writes
its own numbers; the research tools build on `turn_profile.py` rather than carrying a copy
(v0.9.5, [CHANGELOG](../../CHANGELOG-workflow.md)).

### What is measured

Definitions as the code has them, so a number in a readout can be traced to a line.

- **Context per turn.** `ctx[t] = input + cache_read + cache_creation` — the prompt the model saw
  at turn *t*; **growth** is `ctx[t] − ctx[t−1]`, what the turn added. A turn is one model
  invocation, the unit the bill is charged in.
- **Cost tiers.** Each turn's cost split into input, cache read (0.1×), cache write (1.25×) and
  output, priced per model from one table in `slice_cost.py`. The loop forces the 5-minute cache
  TTL (`TTL_S = 300`).
- **Prefix break.** A turn whose `cache_read` fell more than 2,000 tokens (`BREAK_SLACK`) short of
  what the previous turn left cached: the prompt did not come back from cache and was written
  again at the write rate. `extra_cost` is the write-minus-read difference on the shortfall.
- **Thinking retention.** On turns that followed a thinking-heavy turn with tiny tool results,
  growth divided by the previous turn's output. A ratio ≈ 1 means the whole previous output,
  thinking included, came back in the next prompt.
- **Orientation span.** The turns before the session's **first edit**, where an edit counts
  whether made through the `Edit`/`Write` tools or through the shell (`sed -i`, a heredoc'd
  rewrite, a `>` redirection) and a turn that only wrote a record (done-record, verdict, close-out
  entry) does not end it (`first_edit_turn`). `slice_cost.py`'s per-role `orient_turns` is the
  median of this over the role's sessions. `first_write_turn` — the first write *tool* call — is
  kept separately and is meaningless for sessions that edit through the shell.
- **Turn classes.** Every turn in exactly one of thirteen classes, first match in this order when a
  turn mixes calls: `dispatch · edit · gate · commit · record · retry · fumble · wait ·
  git-inspect · orient-read · work-read · think · other`. `edit`/`record` are one op split by
  what it wrote; `orient-read`/`work-read` are one op split at the first edit. Bash is classified
  by what it runs (`git diff` is `git-inspect`, `kc project test` is `gate`, `sed -n` is a read),
  and the read ops chained inside one command are counted separately — the batching `tools/turn`
  cannot see. Failure is read from a result's text (`usage:`, `command not found`, `No such
  file`) as well as `is_error`, because the loop's commands end in `2>&1` and fail with exit 0.
  `retry` and `fumble` are lower bounds: the order means a retried edit is an `edit`.
- **Batchable, avoidable.** Consecutive read-only turns are `batchable`; `batchable_strict` also
  requires the later read not to depend on the earlier result. `avoidable = retry + fumble +
  batchable_strict`, priced at the slice's own cost per turn — "a floor, not a target"
  ([context-profile-2026-08-23.md § 13](../research/context-profile-2026-08-23.md)).
- **The derived ratios.** Planner share = the plan loop's own sessions (interactive orchestrator,
  plan-writer, plan-reviewer); research share = the plan loop's sub-agents; rework share =
  run-loop spend past first delivery — writer/reviewer rounds ≥ 2, every consult, every round of a
  phase the run appended (`slice_cost.derive`).
- **Findings telemetry.** Since v0.4.3 each reviewer verdict's findings carry severity, impact
  (`blocking`/`advisory`), category and anchor, persisted in `state.json` — so "how many blocking
  findings did round 1 raise, and how many were refuted" is a field read, not a grep.
- **Abstention.** The one measure taken by hand: a `grep -rniE` pattern set over review markdown
  for "cannot determine / verify / …", then every hit read in context
  ([abstention-baseline-2026-08-23.md](../research/abstention-baseline-2026-08-23.md)).

## What the mining found

**measured** unless labelled otherwise.

- **The template-era orchestrator was the cost.** The first attribution, over 1,338 conversations
  of the pre-plugin KubeCoder workflow: ≈ $5,223 deduped, of which the long-lived root
  orchestrator session was $2,763 (53 %) and all manager sessions together 68 %; `cache_read` was
  95–99 % of tokens on the expensive sessions
  ([ANALYSIS.md § 2](../../workflow-improvements/ANALYSIS.md)). The redesign this produced
  ("files are durable, sessions are ephemeral") is [history.md](history.md)'s Era 1.
- **Context is the cost, not thinking.** Over the plugin-era corpus — 809 sessions, 32 slices (26
  KubeCoderSpecs 144–170, 6 AnsibleSpecs), $2,419.96 — cache read was 56.1 % of dollars, cache
  write 23.0 %, output 20.9 % ([context-profile-2026-08-22.md § 1](../research/context-profile-2026-08-22.md)).
  Of 2.97 G tokens processed, 29.4 % were the fixed prefix paid again on every turn, and
  ≈ 40 % file contents read once and re-read at 0.1× on every later turn
  ([context-profile-2026-08-22.md § 2](../research/context-profile-2026-08-22.md);
  [interventions-2.md § 0](../research/interventions-2.md)). This is what the withdrawn effort
  step-down trial had exposed, and the profile confirmed: effort reaches only the output tier plus
  the re-read of retained thinking — 24.9 % of cost (§ 2) — and the thinking-retention probe put the
  ratio at a median 1.04 (n = 664): prior thinking is billed as input on every later turn (§ 4).
  A3's accounting "was short by a fifth, and the conclusion stands"
  ([interventions-2.md § 2](../research/interventions-2.md)).
- **The tail dominates.** Sessions of ≥ 80 turns were 7.0 % of sessions and 25.0 % of cost
  ($603.78); the doc-writer on slice 170 ran 192 turns to $33.28 with context peaking at 438 k
  ([context-profile-2026-08-22.md § 1](../research/context-profile-2026-08-22.md);
  [doc-phase-plan.md § 1](../research/doc-phase-plan.md)).
- **Prefix breaks do not matter.** 82 breaks across 61 of 809 sessions, $32.19 extra, 1.3 % of
  cost (0.7 % of headless spend when the operator's own sessions are excluded) — so the 5-minute
  TTL and the idle gaps were not a lever (§ 3; interventions-2.md § 0).
- **Every code-writer rebuilt the same picture.** Orientation before the first edit: median 14
  turns (p75 20), 38.4 % of the session's cost, context at the first edit 79,655 tokens; the two
  most common orientation calls were `sed -n <range>` (602) and `grep` (589) over 141 editing
  sessions; `plan.md` was the most re-read file in the corpus — 272 sessions, 328 reads, 8.3 M
  characters — and only 9 of 141 writers ran a gate before their first edit
  ([context-profile-2026-08-22.md § 8–9](../research/context-profile-2026-08-22.md)).
- **What the turns do.** Over 749 headless sessions, 25,353 turns, $2,168.58 at a nearly flat
  $0.086 per turn: `orient-read` was the largest class at 36.6 % of turns and 32.9 % of cost
  ($714.45), `edit` second at 15.6 % / 19.5 %; the avoidable floor was 3,555 turns, 12.6 %,
  $305, ranging 4.5 % (Ansible 013) to 19.5 % (slice 169) per slice; of the 1,248 fumble-and-retry
  turns, 225 were `close_out.py` invocations (188 of them `list`) and the rest wrong-path guesses
  ([context-profile-2026-08-23.md § 13](../research/context-profile-2026-08-23.md);
  [turns-plan.md § T1 Read](../research/turns-plan.md)). Writers issue about one tool call per turn
  (1.07 as the aggregate mean, § 6; 0.99 per-session median, § 13) but chain 1.67 reads per reading
  turn inside one Bash command, so the tools-per-turn figure overstated the batching gap.
- **"Documentation is low risk" is false here.** Over 63 slices (063–186), 300 phases, 375 review
  sessions and 649 findings, the 38 phases that touched only "low"-mapped paths had the highest
  round-1 `issues` rate in the corpus — 37 % against 21 % for code — and none of their 20 blocking
  findings was refuted; the spec repo's wire contracts yielded 78 blocking findings per 100
  phase-touches, the highest of any path. Skipping every low-phase review would have saved ≈ $128
  over 63 slices, about $2 a slice; a "low" narrowed to process docs skips nine sessions (≈ $22)
  and loses nothing on record ([risk-review-2026-08-27.md § 2, 7](../research/risk-review-2026-08-27.md)).
- **Reviewers do not abstain.** 179 review files, 32 slices: 10 raw pattern hits, 44 broadened
  candidates of which 41 were not abstention; 4 soft and 0 hard abstentions in total, across 4
  slices (145, 150, 156, Ansible 006)
  ([abstention-baseline-2026-08-23.md](../research/abstention-baseline-2026-08-23.md)).
- **The doc-writer's dispatch had three fixable defects.** Read turn by turn on 186/184/170: every
  Explore sub-agent's report arrived 18–49 turns after dispatch, after the writer's first edit,
  because the writer never ended its turn to wait — 46–66 % of the paths it read after dispatching
  were its own sub-agent's, 15–21 % of each session; a per-file diff over the tool limit
  round-tripped through disk (7.8 k tokens for nothing); `close_out.py --help` fumbles 3/1/4
  ([doc-phase-plan.md § 1](../research/doc-phase-plan.md)).
- **Review economics on 0.4.2+.** Sixteen slices (155–170) read from the telemetry fields: round-1
  `issues` 17 % (12/71) against a 24 % baseline; 15 blocking findings, 0 refuted; comment-prose 38 %
  of findings, all advisory, $0 rework; rework 2–19 %, median ≈ 7 %
  ([interventions.md § 12](../research/interventions.md)). Before the telemetry existed, producing
  one grounding sample over five slices took "38 tool calls of grep + manual classification"
  (interventions.md I1) — which is why I1 was in the first batch shipped (v0.4.3, with I2, C1, C2,
  A1 and A2).

### What each finding changed

| Finding | Change | Version | Read |
|---|---|---|---|
| orient-read the largest class; plan.md the most re-read file | the driver renders a per-phase **digest** into every writer dispatch instead of "read the plan" — 30 KB at the median phase (≈ 7.7 k tokens, p90 57 KB) against a 45 KB plan, over 296 phases ([turns-plan.md § T4](../research/turns-plan.md)) | v0.9.7 (T4) | whole-plan reads before the first edit 0 of 16 (corpus 182 of 184); writer $/phase −40 % pooled, median session −8 %; every quality instrument inside baseline ([t4-read-2026-08-23.md](../research/t4-read-2026-08-23.md)); **still "validating"** (`status.md` § T4) |
| fixed prefix ≈ 32 k per dispatched role, ≈ 23 KB of listings no headless role uses | auto-memory and bundled skills off at spawn; then `--disable-slash-commands` and `--strict-mcp-config` through `kc` | v0.9.6, v0.9.8 (T3) | `ctx1` code-writer 32,172 → 28,825 → 24,488; every role −6.5 to −7 k against the corpus |
| batchable(strict) 8.1 % of writer turns, below the 15 % bar | no batching trial; folded into T4 | — (T5) | — |
| fumble+retry 4.5 %, below the 5 % bar; `close_out.py list` 188 of 1,248 | `close_out.py` accepts the report path; the hook programme dropped | v0.9.6 (T3b/W2) | writer `close_out.py` fumbles 0/16 on the first read |
| the three doc-writer defects | dispatch-then-yield; diff on disk per repo; plan digested whole; close-out verbs rendered from the tool's parser | v0.9.9 | **pending** — the 0.9.14 doc phases were the next read |
| "documentation is low risk" false | **ruled**: do not skip low-risk reviews; put the risk map in the reviewer's dispatch line instead | not built (#715/#719) | — |
| the first attribution's 53 % orchestrator | the task runner, then the run loop | 2026-07-10, v0.1.0 | slice 072: orchestrator share 53 % → ≈ 13 %, $137 all-in ([PLAN.md](../../workflow-improvements/PLAN.md)) |

## The corpus today

Computed 2026-09-02 over the 44 completed KubeCoderSpecs slices (144–196) whose `state.json` carries
a `cost` block — every slice closed since `slice_cost.py --write-state` shipped (v0.4.3) — 22 of
them (172–196, plugin 0.9.7+) with the `turns` block as well. Method: read
`slices/completed/*/state.json`; take `cost.cost_usd`, `planner_share`, `research_share`,
`rework_share`, `cost.turns.{sessions,turns,cost_per_turn_usd,avoidable_share,by_role}`,
`len(phases)`, `len(bailouts)`, `len(appended_phases)`, and `updated_at − created_at` for wall
time; medians and quartiles per column, roles pooled by summing `cost_usd`/`turns`/`n`. No script
is checked in for this aggregate; it is a page of Python over those fields.

| per slice (n = 44) | min | p25 | median | p75 | max | mean |
|---|---:|---:|---:|---:|---:|---:|
| cost, $ | 20.34 | 44.37 | 61.91 | 99.81 | 293.03 | 78.03 |
| phases | 1 | 3 | 5 | 6 | 14 | 5.2 |
| cost per phase, $ | 4.41 | 11.91 | 15.95 | 20.34 | 53.67 | 17.30 |
| planner share | 0.00 | 0.15 | 0.23 | 0.28 | 0.42 | 0.21 |
| research share | 0.00 | 0.02 | 0.03 | 0.06 | 0.17 | 0.05 |
| rework share | 0.02 | 0.05 | 0.08 | 0.14 | 0.28 | 0.10 |
| wall time, h | 0.8 | 1.5 | 2.1 | 3.1 | 52.0 | 4.8 |
| turns (n = 22) | 311 | 545 | 830 | 1,204 | 2,860 | 993 |
| sessions (n = 22) | 12 | 18 | 26 | 36 | 70 | 29 |
| cost per turn, $ (n = 22) | 0.07 | 0.07 | 0.08 | 0.09 | 0.10 | 0.08 |
| avoidable share (n = 22) | 0.09 | 0.11 | 0.12 | 0.14 | 0.18 | 0.13 |

Total over the 44: $3,433.41. Bail-outs: 13 across 10 slices. Phases appended by a completion
consult: 2, on 2 slices. The two 50-hour wall times (180, 182) are slices left overnight, not
runs of that length. The most expensive slice, 181 at $293.03, had 14 phases, 70 sessions and
2,860 turns; the cheapest, 196 at $20.34, one phase and 311 turns.

Pooled over the 22 slices with turn tables:

| role | sessions | turns | cost, $ | share |
|---|---:|---:|---:|---:|
| code-writer | 153 | 6,225 | 572.89 | 30.7 % |
| code-reviewer | 152 | 4,016 | 366.18 | 19.6 % |
| doc-writer | 22 | 1,989 | 246.28 | 13.2 % |
| plan-writer | 41 | 1,755 | 149.65 | 8.0 % |
| subagent:Explore | 113 | 2,263 | 119.29 | 6.4 % |
| orchestrator:plan | 21 | 1,066 | 105.48 | 5.7 % |
| test-agent | 23 | 1,425 | 90.28 | 4.8 % |
| consult | 24 | 973 | 77.46 | 4.2 % |
| plan-reviewer | 21 | 664 | 66.22 | 3.5 % |
| subagent:general-purpose | 45 | 971 | 42.04 | 2.3 % |
| orchestrator:run | 22 | 323 | 25.41 | 1.4 % |
| subagent:dev:rebase-agent | 8 | 144 | 4.43 | 0.2 % |

The role shares match the 32-slice corpus of August within a point or two (code-writer 28.6 %,
reviewer 16.9 %, doc-writer 13.1 % there — [context-profile-2026-08-22.md § 1](../research/context-profile-2026-08-22.md)):
the digest and the prefix trim moved the per-session numbers, not the shape of the bill.

**Orientation after the digest.** The per-slice code-writer `orient_turns` (turn_profile's
turns-before-first-edit, median over the slice's writer sessions) has a median of 10.5 over the 22
slices (p25 7, p75 14; 0.9.8 alone 11.5, 0.9.13 alone 10.5) against the corpus's per-session median
of 14. Indicative only: a median of per-slice medians over 22 slices is not the same statistic as
a per-session median over 141 sessions, and the phase sizes differ. `ctx_first` for writers sits at
≈ 35–40 k on 0.9.8–0.9.13 because the digest itself is ≈ 9–10 k tokens on top of a trimmed prefix of
≈ 24.5–25.8 k ([t4-read-2026-08-23.md § 2](../research/t4-read-2026-08-23.md)).

## The research method

Two research runs have been through this loop — overthinking and review economics (August 14–22),
then context economics (August 22–27) — and both followed the same shape.

1. **A briefing that defers action.** The operator writes the observed problems, the constraints
   ("the loop must stay generic", "findings must never be suppressed"), a reading list, and the
   questions — and states the rule up front: "Nothing gets actioned before we decide together"
   ([research.md](../research/research.md); [research-2.md](../research/research-2.md), whose
   `research-2-prompt.md` is the prompt that generated it in a separate web session).
2. **The reading.** Papers and pages are mirrored into `articles/` by the fetch scripts and
   extracted against a fixed brief (core results, method and setting, relevance to each problem,
   interventions supported, applicability caveats) into `extracts/`. In run 1 the ★ sources were
   read in full by the session lead and the rest extracted by sub-agents; in run 2 every source was
   extracted by an agent reading the full mirror and the ★ extracts were checked by the lead against
   the article — [literature.md](literature.md).
3. **A catalogue, not a decision.** Each candidate intervention gets Evidence / Effect / Measure /
   Cost / Risks and a rank; the document says of itself "the standing menu of interventions the
   reading supports … nothing in here is a decision" ([interventions.md](../research/interventions.md))
   and "a proposal for discussion, not a decision" ([interventions-2.md](../research/interventions-2.md)).
   The operator selects; the first run's six selections shipped the same day as v0.4.3.
4. **The status board.** `status.md` tracks where each entry stands — `new → validating →
   accepted → rejected` — as an append-only ledger: "append log lines, never rewrite them; a status
   change always gets a log line naming what caused it" ([status.md](../research/status.md)).
5. **Pre-registered bars and kill rules.** The turns plan set its go/no-go before measuring:
   `fumble + retry` ≥ 5 % of writer turns → the friction step carries weight; `orient-read` the
   largest class → build the digest; `batchable(strict)` ≥ 15 % → a batching A/B. The read came in
   at 4.5 %, largest, 8.1 % — so T4 proceeded and T5 folded ([turns-plan.md § T1](../research/turns-plan.md)).
   Its protocol: one variable per trial, paired by project and phase-size band, fixed plugin
   version, model, effort and prices for the trial; quality instruments all already recorded (r1
   blocking rate, refuted findings with baseline 0, gate-red, rework share with baseline 2–19 %,
   abstention, operator fix-nows at close-out); **kill** = any instrument outside its baseline range
   on two consecutive slices, or cost not below baseline (§ Protocol).
6. **Readouts against a frozen baseline.** New slices are compared with the 32-slice corpus,
   matched by phase-count band, through the same replay the plugin ships — "the figures are the
   ones `state.json`'s `cost.turns` carries" ([t4-read-2026-08-23.md](../research/t4-read-2026-08-23.md)). Each
   plugin step ships as its own version, is pushed and installed, and is read on the next 2–3
   slices before the next step ships.
7. **Correcting one's own numbers in place.** The memo's "136/184 writers run the gate before
   editing" matched no cut of the corpus; the taxonomy read replaced it with 164 of 184 running a
   gate at all and 12 of 181 before the first edit, and the wrong line was amended where it stood
   ([context-profile-2026-08-23.md § 13](../research/context-profile-2026-08-23.md);
   [interventions-2.md § 1](../research/interventions-2.md)).

What the method has not managed:

- **A3 was withdrawn by ruling, not by its kill rule.** Four slices in, the writer-effort trial's
  read was underpowered (one-sided Fisher p ≈ 0.14–0.22) and the recommendation said so: "drop —
  not on the kill rule, which has not fired, but because the shape gate confines the trial to
  phases where neither tier fails, so it cannot gain power". The operator's ruling: "additional
  complexity, dead weight" (**ruled**; [status.md § A3](../research/status.md), v0.7.3).
- **T4 has been "validating" since 2026-08-23.** The preliminary read asked for 2–3 more slices to
  tell whether the pooled −40 % is T4's or the draw's — the median session read −8 %; the corpus
  above now holds 22 slices on 0.9.7+ and no second read has been written.
- **The status board stopped on 2026-08-23.** Its last log lines are T3's and T4's; the
  risk-review, the doc-phase plan and the left-field menu that followed never gained a chapter.
- **The quality side is thinner than the cost side.** Every cost figure is mechanical; the quality
  instruments are counts of what a reviewer said (blocking, refuted, abstained) and what the
  operator did at close-out, and the one attempt to score outcomes against risk had to recover 114
  of 300 phase heads from author windows because the test phase's rebases had discarded them
  ([risk-review-2026-08-27.md](../research/risk-review-2026-08-27.md)).

## Traps

Things that mislead a reader of the record, each learned once.

- **Duplicate usage records.** The stream-json transcript logs each assistant message several
  times with identical `message.id` and `usage` — 43,001 billed messages behind 106,576 raw records
  in the first corpus, 2.48× if summed naively. Every tool here deduplicates by message id
  ([ANALYSIS.md § 1](../../workflow-improvements/ANALYSIS.md); `slice_cost.py` docstring).
- **Dollars are derived.** Sticker prices over token counts, on a subscription — a consumption
  measure. The relative split across roles is the robust part.
- **`[subagent: …] [agent] completed (0ms, 0 tools)` in `log.txt` is not a sub-agent.** It is a
  backgrounded command completing. And a headless session *is* resumed when a backgrounded
  command completes — 71 corpus cases, every one resumed — so a session that sits idle is waiting
  on a command that never exits, not on a dead wait. Slice 192 P3 was diagnosed the wrong way round
  on 2026-09-01 and the reading reversed the same evening; the fix (an outer `timeout(1)` on
  anything that can hang) lives in KubeCoder's managed `CLAUDE.md`, not in the plugin. *Recorded in
  session memory; this checkout's docs do not carry it.*
- **Which plugin version ran.** `state.json` carries `plugin_version` from v0.9.6 on; before that,
  `git reflog --date=iso` in `~/.claude/plugins/marketplaces/aiworkflow` against the run's start.
  The installed marketplace sat on 0.9.8 from 2026-08-23 to 2026-09-01, so 0.9.9–0.9.11 never ran
  alone and the first 0.9.12/0.9.13 runs are 190–196.
- **Sessions `state.json` never saw.** `slice_cost.py` prices exactly the sessions the state files
  name plus their `<session>/subagents/` transcripts; a session outside that list (a dispatch the
  driver never recorded) is invisible to it and is priced by hand with `turn_profile.replay(path)`.
  Missing transcripts (a cleaned `~/.claude`, another machine) and unknown model ids are reported
  as warnings, never silently priced at zero.
- **Vanished phase heads.** 114 of 300 `reviewed_head` shas in the 63-slice review corpus no
  longer exist — the test phase rebases the slice onto `origin/main` when lanes diverged and the
  branch heads go with it. Author dates survive a rebase and the history rows give each writer
  session's window, so a phase's files are recovered from commits authored inside that window
  ([risk-review-2026-08-27.md](../research/risk-review-2026-08-27.md)). A "vanished-round" trap of
  the same family is recorded in session memory with a pointer to a "Reading a run" section of
  `CLAUDE.md` that does not exist in this checkout.
- **Two prefix-break percentages.** 1.3 % is of all 809 sessions; 0.7 % is of headless spend
  only. Both are correct; quote the scope.
- **`orient` has two definitions.** `first_edit_turn` (any edit, shell included) is the measure;
  `first_write_turn` (the first `Edit`/`Write` tool call) is meaningless for the sessions that edit
  through the shell — which from Claude Code 2.1.234 on is most of them: 0 of 111 sessions had no
  `Edit` call through 2.1.233, 43 of 73 from 2.1.234 on, and the 16 sessions of the T4 read made
  zero `Read`/`Edit`/`Write` tool calls ([t4-read-2026-08-23.md § 5](../research/t4-read-2026-08-23.md)).
  A before/after that spans that version compares editing styles as well as plugin versions.
- **The LaTeX→Markdown mirrors drop tables.** Silently, in five papers (2505.06120, 2512.24601,
  2601.16746, 2605.14563, 2606.29718); the extracts recovered load-bearing numbers from arXiv's
  HTML, and two papers were converted from HTML outright
  ([extracts/README.md](../research/extracts/README.md)). When a paper's claim is load-bearing,
  verify it against the mirror, and the mirror against the source.
- **`log.txt` is large.** 250 KB on a 12-phase slice; a full read is a delegated read.
