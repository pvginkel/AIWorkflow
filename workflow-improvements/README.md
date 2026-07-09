# workflow-improvements

Preparation material for the Trello Triage **#175 "Workflow improvements"** run against
`../KubeCoder`. **Nothing here has been executed** — this is the plan and the source material for it.
Execution (and later sync-back into this AIWorkflow repo) happens in a separate session.

## Contents

- **[`PLAN.md`](PLAN.md)** — the **settled design** (2026-07-09/10): the task-runner architecture
  ("files durable, sessions ephemeral"), the four-session pipeline, and the mapping from card #175's
  original workstreams to what was delivered in `../KubeCoder`. The original A–L workstream plan is
  in git history. Cross-document migration steps for adopting repos:
  [`../CHANGELOG-workflow.md`](../CHANGELOG-workflow.md).
- **[`ANALYSIS.md`](ANALYSIS.md)** — execution-history analysis: how much each slice cost (all-in,
  deduped), the 3 selected slices (052 / 038 / 044) deep-read, and cross-cutting patterns mapped to
  #175. **Written as source material for a secondary analysis by a different agent.**
- **[`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md)** — per-turn deep-dive of `track_build`-using
  orchestrators: where the tokens go now (inline live/E2E verification is the top sink, ~30–53%/session),
  the `track_build` ROI, and the retracted MCP-schema-bloat claim (MCP loads lazily).
- **[`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py)** — the reusable per-slice
  all-in token/cost/wall-clock tool (root orchestrator + per-project managers + sub-agents, deduped by
  `message.id`).
- **[`data/`](data/)** — the deep-read helper and the generated snapshot:
  - `digest.py` — compact turn-by-turn digest of a single transcript.
  - `slice_ranking.csv`, `sessions.csv`, `slice_roles.json` — generated outputs.
  - `orchestrator-deepdive/` — the three per-turn orchestrator reports.

## The headline from the analysis (worth acting on)

**The orchestrator is the cost centre** — root orchestrator sessions are **53% of all spend**, and the
manager/orchestrator sessions together are **68%** — the part that is easy to miss if you look only at
the sub-agents. The plan attacks the root cause directly: **cost = context size × turns, and the
long-lived orchestrator/manager sessions maximise both.**
