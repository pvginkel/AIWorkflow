# AIWorkflow — the `dev` plugin marketplace + workshop

This repo is a **Claude Code plugin marketplace**. It hosts the slice-development workflow as an
installable plugin (`dev`), and it is the workshop where that workflow is measured and improved.

The workflow used to be a template you copied into each project and filled in. It is now a **plugin
you install once** into `~/.claude`; each project describes *itself* through its
`.kubecoder/project.yaml` manifest (read by `kc`) and three lines in its `CLAUDE.md`. This version
targets the **KubeCoder environment** — it is kc-native and expects `kc` on PATH (always true inside
a KubeCoder pod).

## The `dev` plugin

The validated slice pipeline: **`/dev:triage` → `/dev:plan-slice` → `/dev:run-slice`**, plus
`/dev:slice-dag`, `/dev:arch-design`, plus `/dev:onboard` to bring a repo onto the
pipeline in the first place and `/dev:merge-repos` to fold a split backend+UI pair into one repo
that can be onboarded. `plan-slice` settles the design with the operator, then drives a
plan-writer/plan-reviewer round (`plan_loop.py`) to a reviewed **phase queue**; `run-slice` launches
a kc-native run loop (`run_loop.py`) that takes each phase through a bounded loop — fetch → branch →
code-writer → test gate + test-fixer → consult-funded review rounds against a rising bar → ff-merge
→ `✅ DONE` — then closes the slice out with a loop-tail gate sweep, a completion consult, a test
phase and a doc phase, spawning every agent as a headless `kc session`. The gate is
`kc project test`, run by the loop itself: detecting green needs no model, only fixing red does.
**Files are durable; sessions are ephemeral;** scripts drive, agents judge.

**The plan is the queue.** One `plan.md` per slice holds phases as `### P<id> — <title>` headings,
each opening with a `Target:` line naming a `kc project list` component or a sibling repo. Document
order is authoritative; only the driver stamps a phase done. Every agent in the loop may edit the
plan — appending a phase is how work grows, bounded by a generation bar that folds small in-scope
touch-ups in early and cards the rest at close-out.

- **`plugins/dev/`** — the plugin: 7 skills, 9 agents, the tools (`run_loop.py`,
  `plan_loop.py`, `sweep_slice.py`, `close_slice.py`, `slice_cost.py`,
  `preflight.py`, and `allocate-next-slice.sh`, with their suites), and the contract docs
  (`run-loop.md` / `runner-state.md` / `plan-loop.md` / `plan-template.md` /
  `agent-dispatch.md`, plus `residual-sweep.md`, `project-contract.md`,
  `preflight.md`).
- **`.claude-plugin/marketplace.json`** — makes this repo installable.

`kc project test` and `kc project lint` gate the plugin from this repo — the suites are the reason
the workflow is safe to change here.

### Install

```
/plugin marketplace add <this repo>     # e.g. /plugin marketplace add /work/AIWorkflow
/plugin install dev@aiworkflow
```

Then make a repo adoptable — author a `.kubecoder/project.yaml` and add the three `CLAUDE.md` lines
(`Spec repo:`, `Slice testing strategy:`, `Design philosophy:`). Preflight enforces the whole
contract and tells a new repo exactly what is missing. See **[`docs/ADOPTING.md`](docs/ADOPTING.md)**.

## The workshop

- **`plugins/dev/tools/slice_cost.py`** — what a slice cost, priced from the run's own
  `state.json` / `plan_state.json` records and the transcripts they name. It ships with the plugin
  rather than living here, because it reads a state format the plugin owns.
- **`workflow-improvements/`** — the R&D / evidence trail behind the workflow's design.
- **`archive/quality/`** — the retired quality capability (`quality-improver`,
  `quality-issue-finder`, `refactor-audit`) and the `code_health` grader, one folder per source
  project because the copies drifted apart. Parked while the tool is rebuilt; `/dev:onboard` sweeps
  each project's copies in here. See [`archive/quality/README.md`](archive/quality/README.md).
The monorepo-merge runbook that used to live in `runbooks/` is now the `/dev:merge-repos` skill;
its per-repo status lives on the issue tracker, where work state belongs.

## Docs

- **[`docs/ADOPTING.md`](docs/ADOPTING.md)** — install the plugin and make a repo adoptable
  (manifest + `CLAUDE.md` entries), with a worked example.
- **[`docs/AUTHORING.md`](docs/AUTHORING.md)** — the durable rules for writing/maintaining agents,
  skills, and docs so they stay lean and drift-free.
- **[`plugins/dev/docs/`](plugins/dev/docs/)** — the plugin's own contract: `run-loop.md` (the
  phase queue and the consult/test/doc ladder) with `runner-state.md`, `plan-loop.md`,
  `plan-template.md` and `agent-dispatch.md` beside it, plus `project-contract.md`,
  `preflight.md`, and `residual-sweep.md` (the planning-free lane for card-described residuals).
- **[`CHANGELOG-workflow.md`](CHANGELOG-workflow.md)** — the plugin's changelog.
