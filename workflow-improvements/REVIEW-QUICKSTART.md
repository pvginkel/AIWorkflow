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

## What changed after 072 — verify each on the next run

KubeCoder commits `35a7639` + `3e3dd3d` (this repo: `06f0942`, `8fb0b26`):

1. **Two-tier checkpoint consults** (merge `--stat` in prompt; tier 2 only on plan-grounding
   overlap) → expect: fewer/no unbounded diff dumps in consult transcripts; call out whether the
   genuinely-overlapping case still goes tier 2 (it should — 072's consult 3 was the model).
2. **Final-verification findings → consult** (`fix_tasks` / `proceed_flagged` / `bail`) → a
   dormant/pre-existing residual must NOT hard-bail; check the consult's judgment and that
   `flagged_findings` → Triage cards at close-out.
3. **Transcript paths in `state.json` + session ids in `log.txt` + log.txt committed** → confirm
   the close-out actually kept them (072's log was deleted; the convention flipped after).
4. **Batching rule in every agent definition + `-q` suites** → measure: multi-tool-call turns per
   session (was ~zero for reviewers/testers/test-agent), turns/session and cache-read/session vs
   072's fleet, no `-v | tail -N` suite dumps. This is the fix with a measurable target: material
   turn-count drop at equal quality.

Open levers if cost is still unsatisfying: split task-04-sized tasks at planning time (072's
biggest writer session was $31 on an 866-line diff); a SessionStart-hook registry for interactive
sessions; Sonnet writers for mechanical tasks (only after 2+ clean runs — writers are where the
quality came from).

## Report shape the operator expects

Verdict on the slice's code first; then cost vs the table above; then agent behavior (concrete,
quantified, role by role); then what was fixed/landed vs what's recommended-but-pending. Update
`PLAN.md` §Validation runs and the auto-memory pointer when done.
