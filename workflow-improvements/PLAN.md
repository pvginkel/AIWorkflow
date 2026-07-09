# Workflow improvements — settled design (Trello Triage #175)

**Status:** design settled with the operator (2026-07-09 discussion); execution in progress against
`../KubeCoder`. This file replaced the original workstream plan (see git history for the A–L
version) after the design conversation converged on a materially better architecture than the card's
original shape. Validation is by real slice runs, re-measured with
[`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py).

**Companion evidence:** [`ANALYSIS.md`](ANALYSIS.md) (execution-history analysis) and
[`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md) (per-turn orchestrator deep-dive). Their headline
drove the redesign: **the orchestrator/manager sessions are 68% of all spend; cost = context size ×
turns, and long-lived sessions maximise both.**

**Canonical spec of the new workflow:** `KubeCoder/docs/conventions/task-workflow.md`. This file
records the *why* and the mapping from card #175; that file specifies the *what*.

---

## The settled architecture

**Files are durable, sessions are ephemeral.** No long-lived LLM session drives execution; a Python
state machine does (`tools/ai_workflow/task_runner.py`). Every judgment call is either made once at
planning time or delegated to a fresh, narrow-context session at a defined touchpoint.

The operator's pipeline (one session each, operator-initiated):

1. **`/triage`** — findings/requests → numbered **slice folders** (`slices/NNN_slug/slice.md`).
   The former change-request bundle *is* the slice now; `/write-slice` is retired as ceremony.
   Triage allocates the slice number, creates the Kanban card, and pre-resolves all Trello content
   into `slice.md` (nothing is read from boards mid-run).
2. **`/plan-slice`** (new) — interactive, slice-scoped planning. Plan-writer + plan-reviewer break
   the slice into **2–4 ordered, project-local tasks** (`tasks/NNN_slug/`), each with its own plan;
   cross-project interfaces are defined up front (producing task first); acceptance criteria and
   verification artifacts are emitted here. Planning Q&A with the operator happens once, here — not
   per-project at run time.
3. **`/run-slice`** — thin: launches the **task runner** as a background shell, idles turn-free,
   and acts only as the escalation path for bail-outs (investigate → decide or defer → relaunch).
   Uneventful slices (target ≥50% v1, 75% v2) end with just a final report.

**The task runner** enforces the card's bounded loops mechanically: per task — branch → fresh
`code-writer` → fresh Sonnet `code-tester` per round (cap 3) → `code-reviewer` (cap 2) → ff-merge →
checkpoint. Verdict files (`*_result.json`) make agent outcomes machine-readable; consults (fresh
Opus sessions) judge at limits and flags; `state.json` is the decision substrate and resume point.
Sessions spawn via `claude --agent <role>` (a full session — dev agents can use sub-agents, granting
the card's "linting done in a subagent" wish) with `FORCE_PROMPT_CACHING_5M=1` and cwd = the task's
project directory.

**Escalation ladder:** runner counts → consult judges → `/run-slice` session investigates bail-outs
→ operator. Environmental problems are never worked around — agents report `blocked` and stop
(the claude_session.py background-task kill bug that caused the slice-038 12-re-entry pattern is
fixed; the lesson — scream, don't adapt — is now contract).

## Mapping from card #175 / the original workstreams

| Original | Outcome |
|---|---|
| A migration doc | `CHANGELOG-workflow.md` (this repo) records every cross-document move an adopting repo must replay. |
| B standardize skills | Superseded for the retired skills; project-specific commands live in per-project docs/CLAUDE.md and the runner's config, not in skill bodies. |
| C task model + bounded loops | The core delivery: task folders + runner + verdict contract. Branch-per-task (operator's suggestion) kept — clone-per-slice makes it safe, the runner makes it mechanical, review scope = `merge-base..HEAD`. |
| D test agent | `test-agent` (Sonnet, handover in / findings out) runs final verification from the runner. Findings **bail out** in v1 (`test_findings.md`) — the `/run-slice` session authors fix tasks via `/write-task` and relaunches; scripting the findings loop end-to-end is v2. Live-deploy verification stays post-push in `/run-slice` close-out. |
| E resizing | Retargeted at `/triage` (bundle = slice now, so triage groups sizing-aware) and `/plan-slice` (sizes to 2–4 tasks; may propose splitting a too-big slice during Q&A). |
| F triage fidelity | Already shipped (`a3eccbf`); `slice.md` carries operator specs at signature fidelity. |
| G agent trims | All dev agents rewritten thin: identity + output contract (now literally the verdict schema) + bounds. Reviewers describe, never fix; no plan fed to tester or code-reviewer; external-surface/substitution-test blocks (commit `179f3fe`) deleted, replaced by a one-line grounded-claims rule. |
| H CLAUDE.md | Root CLAUDE.md becomes a **generic KubeCoder brief** (orchestrator role guidance removed — it serves the root session *and* every spawned dev session, which now pay its cost per spawn). Issue-log + push-notifications → `~/.claude/CLAUDE.md` + env template; deploy/cexec → `docs/operations/`; skill list deleted (frontmatter descriptions suffice); Decision-making sections deleted; subproject duplication collapsed. |
| I docs diet | "State every fact exactly once; no recap sentences" added to `documentation-model.md`; moved content lands terse. |
| J claude_session.py | Gains `--cwd`, `--agent`, `--model`, quiet-by-default stderr (`-v` restores streaming); its `_run` machinery is the runner's session backend. |
| L naming collisions | Resolved as part of the skill retirements/renames. |
| Orchestrator-cost items | Trello→bundle: absorbed by triage authoring `slice.md` complete. `track_build --diagnose` + `$JENKINS_TOKEN` assert: shipped with the tooling changes. Major/minor distinction: **gone** — planning is slice-level, execution is uniform per task. |

## Decisions closed (former §N)

1. Migration doc: `CHANGELOG-workflow.md` in this repo.
2. Progress log: script-owned JSON (`state.json` history) — agents never write it; append-safety by
   construction.
3. One test agent, differentiated by the handover the dispatcher writes.
4. Branch-per-task inside the per-slice clone; the runner owns all git management; writer commits
   before every tester round so dropping tester changes is a clean reset.
5. "No backwards compatibility" scoped to internal interfaces; external-interface rules live in
   `docs/`.
6. Consult policy: only on limit-hit or agent flag, plus the post-task checkpoint (runner flag,
   default on). Stuck-detection is a consult's judgment, not a script threshold.
7. Not phased — delivered as one wave, validated by the next real slice runs.

## Validation gate

Run 2–4 real slices in KubeCoder on the new workflow. Measure with `slice_costs.py`: the
orchestrator share (53% baseline) and per-session inline-verification share (~30–53%) should drop
sharply; watch planning quality (task premises) — the task folder is now the only dispatch context,
so plan-writer/plan-reviewer carry the weight the per-project managers used to improvise. Then sync
the settled result back into this repo (`orchestrator/`, `project/`, `tools/`).
