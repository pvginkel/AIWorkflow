# Slice-run review — quick start

Bootstrap for reviewing a completed task-runner slice in `../KubeCoder`, the way slice 072 was
reviewed (2026-07-10, this repo's session `12ba956c…`; findings in [`PLAN.md`](PLAN.md)
§"Validation run 1"). The operator runs slices and asks for a review after; this doc gets a fresh
session from zero to that review without re-deriving the method.

## Ground rules

- **Delegate transcript digging to Sonnet sub-agents** — the review session is typically on an
  expensive model; transcripts are cheap-model work (operator asked for this explicitly). Read the
  slice's *source diff* yourself: the code judgment is the expensive-model job.
- Review only; the slice workflow owns code changes. Workflow/tooling fixes that fall out of the
  review land directly in KubeCoder (`tools/ai_workflow/`, `.claude/agents/`,
  `.claude/commands/`, `docs/conventions/task-workflow.md`) + get recorded in `PLAN.md` here.
- Never push either repo; commit locally and stage specs files by name.

## Where everything lives

- **Slice folder:** `/work/KubeCoderSpecs/slices/completed/NNN_slug/` — `slice.md` (intent),
  `state.json` (the run record: per-task rounds + full `history` with per-session ids,
  **transcript paths**, outcome summaries), `log.txt` (spawn narrative; committed at close-out
  since `35a7639`), per-task `tasks/NN_*/` (plans, verdicts, reviews, consults),
  `test_findings.md`, `verification.json`.
- **Transcripts:** `~/.claude/projects/<munged-cwd>/<session-id>.jsonl` (munge: non-alphanumeric
  → `-`; bot tasks under `-work-KubeCoder-bot`, consults/test-agent under `-work-KubeCoder`).
  A session's sub-agents: `<session-id>/subagents/agent-*.jsonl`. Interactive sessions
  (`/plan-slice`, `/run-slice` orchestrator) are NOT recorded anywhere — grep
  `~/.claude/projects/-work-KubeCoder/*.jsonl` for `plan-slice`/`run-slice` + the slice number.
- **Tools:** `tools/analysis/runner_sessions.py <slice-dir> [--tokens]` — session inventory +
  dedup'd cost (counts a resumed session once). `tools/analysis/slice_costs.py` — fleet-wide
  ranking / old-workflow baseline. Dedup rule: one usage record per `message.id` (raw summing
  overcounts 2–3×).

## The review, in order

1. **Inventory + cost** (cheap, local): `runner_sessions.py --tokens`; skim `state.json` history
   summaries and per-task round counts. Anything with >1 writer/tester/review round is where the
   loop worked or thrashed — read those verdict/review files.
2. **Source diff yourself**: commit range is first-task-commit^..last (see `git log` around the
   slice's timestamps, or the orchestrator's close-out report). Skip test files on the first pass;
   the per-task reviewers were thorough — your marginal value is slice-level coherence, layering,
   and anything the per-task scope split hid.
3. **Sub-agent fan-out** (Sonnet, parallel; prompts that worked are in the 072 session):
   - *Orchestrator + bail path*: find the `/run-slice` session, extract its close-out report and
     how any bail was handled.
   - *Consult behavior*: per consult — tool sequence, artifact-vs-code read share, would tier 1
     have sufficed.
   - *Writer/tester/reviewer profiles* (pick the most expensive + one lean contrast): tool
     histograms, suite-run counts, waste signals (edit retries, re-reads, lint round-trips,
     single-tool turns), discipline signals, inherent-vs-avoidable verdict.
4. **Cross-checks**: flagged_findings → Trello cards actually exist; decisions lodged
   (`decisions.md` + owning doc); docs reconciled; suites green claim vs the test-agent's own runs.

## Compare against (072 = validation run 1)

| Metric | 072 | Old-workflow comparables |
|---|---|---|
| All-in cost (sticker) | ~$137 ($100 fleet · $29 plan · $8 orchestrator) | majors $150–283; median slice $64 |
| Active hours | ~5 (plan ~1.7 + run ~3.5) | 15–42 |
| Fleet turns / sessions | 932 / 27 | 951–2,270 turns |
| Orchestrator share of spend | ~13% | 53% (68% incl. project managers) |
| Fleet split | writers 71% · reviewers 13% · testers 11% · consults 4% · test-agent 2% | — |
| Cache-read : output tokens | ~40 : 1 (cost ≈ turns × context) | — |
| Measured waste | ~10–15% of writer/tester/reviewer spend | — |

## What changed after 072 — status after runs 2–6 (074–078, reviewed 2026-07-11)

All four post-072 fixes verified on real runs — full record in [`PLAN.md`](PLAN.md) §"Validation
runs 2–6": two-tier consults hold (stat-only prompts, scoped tier-2, the 076/03 **amend** caught a
real cross-task bug); traceability held in all five slices; batching cut reviewer turns/session
22.5 → 9–19 (multi-tool share 23% → 47–64%) and fleet turns/session 38.8 → 17–31 on comparable
slices. Still unexercised: the final-verification findings consult (`fix_tasks` /
`proceed_flagged` / `bail`) and every round-cap consult — all five runs were clean-r1 with worst
case one writer r2.

Verify on the NEXT run (landed 2026-07-11, KubeCoder `.claude/agents/`):

1. **Edit/Write batching in `code-writer.md`** → expect writers' new-file pairs and end-of-session
   doc passes issued in one message (075's writers had zero multi-tool turns after the research
   phase; the doc pass was 6 files = 6 turns at ~250k cache-read each).
2. **Tester/test-agent output-directly rule** → no `cmd > /tmp/f` + Read-next-turn (cost one 075
   tester ~19% of its turns), no Bash-heredoc probe files.

Open levers if cost is still unsatisfying: an explicit infra/deploy task when a slice stands up a
new deployable (076's orchestrator absorbed Helm + arch-docs work, $21); pre-draft shape questions
in /plan-slice (075's operator reframe after a GO round cost ~2 review rounds); split
task-04-sized tasks at planning time; a SessionStart-hook registry for interactive sessions;
Sonnet writers for mechanical tasks (only after 2+ clean runs — writers are where the quality
came from).

## Report shape the operator expects

Verdict on the slice's code first; then cost vs the table above; then agent behavior (concrete,
quantified, role by role); then what was fixed/landed vs what's recommended-but-pending. Update
`PLAN.md` §Validation runs and the auto-memory pointer when done.
