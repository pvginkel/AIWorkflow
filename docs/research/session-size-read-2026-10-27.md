---
status: closed 2026-10-27, not pursued — the operator's aim is cost, and the top 5 % is the cheapest work per line
---

# The top 5 % of slice sessions by context size — what they are, and a plan (read, 2026-10-27)

**Recommendation.** The top 5 % is not a malfunction. These are the pipeline's largest units of
work: code-writer phases that edit 15+ files or 1,000+ diff lines, doc phases over slices of
3,000+ lines, and plans of 10+ phases. Per line they are the cheapest work the loop does. One
lever cuts them in bulk: a measurable phase-size ceiling at plan time (S1). It costs about a
quarter more writer and reviewer spend on the phases it splits, and should buy fewer fix rounds.
Take it if the aim is quality. Skip it if the aim is cost. S2 is a small code-writer rule edit
for the in-session waste the reading found, and S3 is a PilotApp chore. Everything else is
single-digit percent or already closed by a ruling.

## The set

Scope: every session the loops recorded (`state.json`, `plan_state.json`) in KubeCoder, Ansible
and PilotApp slices from 2026-08-27 to 2026-10-26. That is 2,974 headless sessions in 126 slices.
A session's size is its peak context: the largest prompt plus output of any turn. That is also
its last turn, since nothing compacts.

- **p95 = 259k tokens.** The 149 sessions above it are 17 % of headless-session spend ($1,349 of
  $7,895).
- **By role:** 95 code-writers (9 % of all code-writers), 28 doc-writers (21 % of all doc
  phases), 13 plan-writers, 8 test-agents, 3 wrap-ups and 2 plan-reviewers. No code-reviewer
  comes near: the reviewer maximum is 257k.
- **By project:** 55 PilotApp, 55 Ansible, 39 KubeCoder. PilotApp has fewer sessions, so its
  share is the highest.
- **The share is rising fast.** Measured against the fixed p95, it was 0.7 % in early September,
  3.9 % in late September, 5.9 % in early October and 10.9 % in late October.

## Why they are long

**Size of the work, in every role.** No single result blows a session up. Bash output is capped,
and only 27 of the 149 sessions hold any result over 40k characters. Every source grows in
proportion to the work. At the median, a top code-writer takes 79 turns against 31, reads 40 distinct paths against 13,
and makes its first edit at 190k against 88k. Its own output (thinking, text and tool input) is
45 % of its growth (41 % for the rest), and its file reads are 34 % (32 %).

The code-writer's peak tracks the phase's diff (`git diff --shortstat` of the phase's
`landed.base..head`, where the target repo is checked out here: 307 sessions):

| phase diff (lines) | n | median writer peak | in top 5 % |
|---|---|---|---|
| < 600 | 204 | 74–171k | 1 |
| 600–1,000 | 43 | 189k | 19 % |
| 1,000–2,000 | 50 | 212k | 32 % |
| 2,000+ | 10 | 283k | 60 % |

Files edited is the same signal measured in every repo (1,074 writers). At 0–3 files, 2 % reach
the top 5 %. At 15–25 files it is 38 %, and at 25+ files it is 90 %. A top writer's phase has a
median of 1,303 lines in 16 files, against 291 lines in 7 files for the rest.

The doc-writer tracks the slice. Slices under 1,000 lines put 0 of 5 doc phases in the top 5 %,
3,000–6,000 lines put 3 of 5, and 6,000+ put 4 of 4. 23 of the 28 top doc phases are slices of 7+
phases. The plan-writer tracks the plan: 11 of its 13 top sessions finished with a `plan.md` over
60k characters, and 10 came from plans of 10+ phases.

**Test runs, which turn out to be size again.** A code-writer with 15+ test runs lands in the
top 5 % 61–88 % of the time, and one with 12+ runs does so even at 0–6 files edited (14 of 26). A reading of six such sessions
(KubeCoder 181 P11, 228 P6, 241 P6; Ansible 054 P3; PilotApp 008 P7, 022 P5) found the runs were
mostly green TDD increments and the fallout of real behaviour changes. What inflated those
sessions was still orientation reading (whole 700-line files, a large file in three chunks) and
write turns of 11–22k output tokens. Within the loops it found these:

- **Truncated-output re-runs.** A suite piped through `tail` or `grep` shows only a warnings
  footer, so the writer runs it again to see the failure. This happened in 5 of the 6 sessions.
- **Format and lint failing late.** `ruff format --check` fails at the gate and costs one or two
  more edit and gate cycles (054, 008, 022).
- **Mutation checks the writer runs itself.** These are 10–14 of 181 P11's runs. Proving a test
  with a mutant is the reviewer's job (`code-reviewer.md`), and the writer is not asked to do it.
- **One hang.** In 008 P7 a suite behind `| tail -3` deadlocked for about 19 minutes and cost
  about 40 turns of diagnosis. PilotApp's suite has no per-test timeout, and `pytest -n` is
  tried without xdist installed.

**Why the share is rising.** The median code-writer peak went from 99k in early September to
189k in late October. In the same time the median files edited per phase doubled from 3 to 6.
At matched size (6–15 files) the peak still rose from 131k to 197k. Of that, base context is
+11k (over all writers, the dispatch prompt grew from 9.5k to 15k and the harness's share from
29k to 36k). Own output is +22k, most of it arriving in late September with the move from Opus
5.1 to Opus 5.5 at `xhigh` (settled, not a lever). The
rest is the bigger phases.

**Long sessions go with rework.** At matched files edited, a top-5 % writer's phase gets a fix
round 41–44 % of the time, against 16–20 % for the rest (15+ files: 29 % against 25 %). This
could be a hard phase causing both. Still, it is the same direction as
[r1-blocking-2026-09-01.md](r1-blocking-2026-09-01.md), where phases of 600+ lines blocked at
50 %.

**Big phases are the cheapest per line.** Writer and reviewer spend over all rounds, per 100
diff lines, measured on phases with a checked-out target:

| phase diff (lines) | phases | median $/phase | $/100 lines | phases with a fix round |
|---|---|---|---|---|
| 300–600 | 44 | 6.34 | 1.60 | 32 % |
| 600–1,000 | 33 | 7.53 | 0.99 | 27 % |
| 1,000–2,000 | 33 | 9.21 | 0.78 | 42 % |
| 2,000+ | 9 | 11.47 | 0.49 | 11 % |

Splitting a 1,300-line phase in two moves it from the 0.78 band to the 0.99 band, about +27 %
on that phase, before the extra gate run. Splitting it in three doubles it.

## The plan

**S1. A measurable phase ceiling at plan time.** "Roughly PR-sized" (`plan-writer.md`,
`plan-reviewer.md` item 5, `plan-template.md`) has no number, and phases have doubled under it.
The change: a phase the plan-writer expects to edit more than about 12 files, or about 1,000
lines, splits along a producer and consumer seam. The plan-reviewer flags one that clearly
exceeds that as a phase-boundary finding. Generated and lock files don't count.
- *Effect:* this targets the 36 top writers from phases of 15+ files and most of the 16 from
  10–15. Each half lands in the 6–15-file band, where 11–14 % reach p95. Doc and plan sessions
  are unaffected.
- *Cost:* about +25 % writer and reviewer spend on the split phases, plus one gate run each.
  Fewer fix rounds offset part of it.
- *Risk:* the writer guesses at plan time. A wrong guess costs one long session, as today.
- *Ruled already:* "fewer rounds come from phase sizing at plan time" (CLAUDE.md § Settled
  rulings). S1 is that lever with a number on it.

**S2. Three lines in `code-writer.md` rule 7.** This is one patch version, not a slice.
- Send a test run's output to a file and read the failures from it. Never re-run a suite to see
  what `tail` or `grep` cut.
- Run the project's formatter in fix mode before the final gate.
- Proving a test with a mutant is the reviewer's job, not the writer's.
- *Effect:* this saves turns more than context, a few to fifteen per affected session.

**S3. PilotApp: a per-test timeout, and xdist if `-n` is meant to work.** This is a project
chore for PilotApp's tracker, not the plugin. It turns a silent hang into a red test. 008 P7 is
the evidence.

## Not in the plan

- **The doc phase.** It is 21 % of doc phases, and the driver is slice size. A split doc phase,
  hand-over stages and prose sub-agents are ruled out (2026-09-05). Slice size is held at about
  seven phases by measured overhead. The doc-writer's survey sub-agents return 16k per session,
  about 5 %, which is not worth a rule.
- **The plan-writer.** It runs long on 10+-phase slices. Triage's ten-phase ceiling is the
  bound already.
- **The test-agent.** All 8 of its top sessions ran between 2026-09-14 and 2026-09-29, one of
  them polling `getBuildLog` 206 times. None has run since.
- **Compaction, caps and history summarisation:** ruled out (turns-plan).
- **Base growth (+11k since September):** this touches every session, not this set. Kept for a
  separate read if wanted.

## Method and caveats

The scripts and the data they collected are in
`docs/research/archive/scripts/session-size-2026-10-27/`. `collect.py` gathers
the sessions through `slice_cost.collect`, `causes.py` attributes each turn's growth to the
previous turn's output and tool results, and `size_vs_diff.py`, `touched.py`, `gates.py`,
`econ.py` and `trend.py` produce the cuts above. Phase diffs exist only where the target repo is
cloned here (KubeCoder, Ansible, PilotApp main repos). Files edited covers every repo but misses
edits made by a Python heredoc without a visible target. The six-session reading was a Sonnet
sub-agent's. Its run counts are lower bounds, because test runs inside heredocs are partly
hidden. Transcripts now carry `api-request-blob` records that repeat tool results. A scan that
does not filter on `type` in (`assistant`, `user`) double-counts them. The plugin's tools filter;
an early version of this read did not, and found re-reads that are not there.
