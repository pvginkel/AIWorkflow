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
`/dev:write-task`, `/dev:slice-dag`, `/dev:arch-design`, plus `/dev:onboard` to bring a repo onto the
pipeline in the first place and `/dev:merge-repos` to fold a split backend+UI pair into one repo
that can be onboarded. `run-slice` launches a kc-native task
runner (`task_runner.py`) that drives each task through a bounded loop — branch → code-writer →
test gate + test-fixer (cap 3) → code-reviewer (cap 3, extendable to 5) → ff-merge → checkpoint —
spawning every agent as a headless `kc session`. The gate is `kc project test`, run by the runner
itself: detecting green needs no model, only fixing red does. **Files are durable; sessions are
ephemeral;** scripts drive, agents judge.

- **`plugins/dev/`** — the plugin: 8 skills, 8 agents, the `task_runner.py` (+ its suite),
  `preflight.py`, `grounding_check.py` (+ its dispatch helper and their suites), and
  `allocate-next-slice.sh` tools, and the contract docs (`task-workflow.md`,
  `project-contract.md`, `preflight.md`, `grounding-ledger.md`).
- **`.claude-plugin/marketplace.json`** — makes this repo installable.

### Install

```
/plugin marketplace add <this repo>     # e.g. /plugin marketplace add /work/AIWorkflow
/plugin install dev@aiworkflow
```

Then make a repo adoptable — author a `.kubecoder/project.yaml` and add the three `CLAUDE.md` lines
(`Spec repo:`, `Slice testing strategy:`, `Design philosophy:`). Preflight enforces the whole
contract and tells a new repo exactly what is missing. See **[`docs/ADOPTING.md`](docs/ADOPTING.md)**.

## The workshop

- **`tools/analysis/`** — `slice_costs.py` and `runner_sessions.py`: how a run's cost and session
  timeline are measured from `state.json` + the recorded transcript paths.
- **`workflow-improvements/`** — the R&D / evidence trail behind the workflow's design.
- **`archive/quality/`** — the retired quality capability (`quality-improver`,
  `quality-issue-finder`, `refactor-audit`) and the `code_health` grader, one folder per source
  project because the copies drifted apart. Parked while the tool is rebuilt; `/dev:onboard` sweeps
  each project's copies in here. See [`archive/quality/README.md`](archive/quality/README.md).
The monorepo-merge runbook that used to live in `runbooks/` is now the `/dev:merge-repos` skill;
its per-repo status lives on the issue tracker, where work state belongs.

## The `upkeep` plugin (planned)

`plugins/upkeep/` parks **`update-docs`** and `documentation-model.md` as migration backlog — the
maintenance capability that feeds `/dev:triage` and is **not** blocked on anything. It is **not
built yet** (not listed in `marketplace.json`); `dev` ships first and stands alone. The quality
capability that used to be parked alongside it now lives in `archive/quality/`, blocked on the
`code_health` rebuild. See [`plugins/upkeep/README.md`](plugins/upkeep/README.md).

## Docs

- **[`docs/ADOPTING.md`](docs/ADOPTING.md)** — install the plugin and make a repo adoptable
  (manifest + `CLAUDE.md` entries), with a worked example.
- **[`docs/AUTHORING.md`](docs/AUTHORING.md)** — the durable rules for writing/maintaining agents,
  skills, and docs so they stay lean and drift-free.
- **[`plugins/dev/docs/`](plugins/dev/docs/)** — the plugin's own contract: `task-workflow.md`
  (the canonical loop/verdict/state contract), `project-contract.md`, `preflight.md`,
  `grounding-ledger.md` (the claim→source ledger format and its drift checker).
- **[`CHANGELOG-workflow.md`](CHANGELOG-workflow.md)** — the plugin's changelog.
