# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

AIWorkflow is a **Claude Code plugin marketplace**, not an application — nothing is built or
deployed from here. It hosts the `dev` plugin (the slice pipeline: `/dev:triage` →
`/dev:plan-slice` → `/dev:run-slice`, plus `/dev:onboard`, `/dev:slice-dag`, `/dev:arch-design`,
`/dev:merge-repos`), and it is the workshop where that pipeline is measured and improved. The
plugin is **kc-native**: it targets the KubeCoder environment and expects `kc` on PATH, with no
non-`kc` fallback.

`README.md` is the map; `docs/AUTHORING.md` is required reading before touching any agent, skill,
or contract doc.

All workflow code is **stdlib-only**. That limitation does however not apply to that written
purely for analysis and research. E.g. the scripts in the `docs/research/` folder use
non-stdlib features. The **stdlib-only** limitation applies only to scripts we distribute
as part of the Claude plugin.

## Commands

```bash
kc project test        # cexec python uv run --with pytest pytest   (the plugin's suites)
kc project lint        # cexec python uv run --with ruff ruff check .
```

- **One suite / one test:**
  `cexec python uv run --with pytest pytest plugins/dev/tools/test_run_loop.py -k <name>`
- **No toolchain, no pytest:** every suite also runs standalone —
  `python3 plugins/dev/tools/test_run_loop.py` (a stdlib `__main__` runner prints ok/FAIL per test).
- **No `build:` or `setup:` target, deliberately.** The plugin's scripts are **stdlib-only** so they
  run inside a KubeCoder pod's toolchain sidecar; pytest and ruff come from `uv run --with`, and
  `pyproject.toml` has no `[project]` table because this repo owns no venv and ships no package.
- Research corpus: `cexec python docs/research/tools/fetch_articles.sh` converts the arXiv papers
  cited in `docs/research/research.md` into `docs/research/articles/` (already-fetched papers are
  skipped).

## Architecture

- **`plugins/dev/tools/`** — the drivers, each with a `test_*.py` beside it. `run_loop.py` (~2.9k
  lines) and `plan_loop.py` carry most of the logic and most of the ~4.7k lines of suite; plus
  `preflight.py`, `sweep_slice.py`, `close_slice.py`, `slice_cost.py`, `allocate-next-slice.sh`.
  Suites load their subject via `importlib.util.spec_from_file_location` (`tools/` is not a
  package) and fake sessions, git, `kc` and the gate — no agent is ever spawned by a test.
- **`plugins/dev/agents/`** (9) and **`plugins/dev/skills/<name>/SKILL.md`** (7) — the dispatched
  roles and the operator-triggered workflows.
- **`plugins/dev/docs/`** — the **canonical contract** for all of the above: `run-loop.md`,
  `plan-loop.md`, `runner-state.md`, `plan-template.md`, `agent-dispatch.md`,
  `project-contract.md`, `preflight.md`, `residual-sweep.md`. Behaviour changes here and in the
  code together; a doc that describes a loop the code no longer runs is a defect.

Four ideas span the files and explain most design choices:

1. **The plan is the queue.** One `plan.md` per slice holds phases as `### P<id> — <title>`
   headings opening with a `Target:` line (a `kc project list` component or a sibling repo path).
   Document order is authoritative, ids are labels, every agent in the loop may edit the plan — and
   **only the driver stamps `✅ DONE`**.
2. **Files are durable, sessions are ephemeral; scripts drive, agents judge.** Deterministic work —
   gates, git, caps, stamping, parsing — stays in Python; judgment goes to a dispatched agent.
   Detecting a green suite needs no model, only fixing red does.
3. **Every agent is a headless `kc session`,** spawned through `run_loop.run_kc_session` (the plan
   loop calls it too). Opus at `xhigh` everywhere via explicit flags, except the always-Sonnet
   agents (`test-agent`, `test-fixer`, `rebase-agent`) which pin `model:` in their own definitions.
4. **The loops bail, they don't chat:** exit 3 = error, exit 4 = operator question. `state.json`,
   `bailout.json` and the exit code are the entire interface to the launching session — loop stdout
   never reaches it.

**Portability is the constraint on every change.** The pipeline is generic; each project describes
itself through `.kubecoder/project.yaml` and four machine-read `CLAUDE.md` lines (`Spec repo:`,
`Slice testing strategy:`, `Slice doc plan:`, `Design philosophy:`), all enforced by `preflight.py`.
Never hardcode a project's names, paths, tracker or tooling into the plugin, and never parse the
manifest directly — only `kc` reads it.

## Conventions

- **State every claim once** (`docs/AUTHORING.md`). Before adding prose, search for what already
  says it; duplication is a drift trap first and a token cost second. Agents don't restate skills,
  skills don't restate agents, neither restates a project's `CLAUDE.md`.
- **An agent without a `description` in its frontmatter is silently not registered** — dispatches
  fall back to `general-purpose` with no error. Check this first when an agent "isn't there".
- Skills live one per directory as `skills/<name>/SKILL.md` (the directory names the skill, and the
  frontmatter `name` must match it); reference plugin files as `${CLAUDE_PLUGIN_ROOT}/...`.
- ruff: `select = E,W,F,I,B,C4,UP`, line length 100, target py313.
- **`archive/` and `workflow-improvements/` are frozen record**, excluded from ruff — the retired
  quality capability and the R&D evidence trail. Don't reformat or tidy them.

## Changing the plugin

- Bump `plugins/dev/.claude-plugin/plugin.json`'s `version` and add a newest-first entry to
  `CHANGELOG-workflow.md` for anything notable; commit subjects carry the version, e.g.
  `dev: fix rounds stop relitigating comments (0.4.2)`.
- Commit subjects are lowercase and scope-prefixed (`dev:`, `docs:`, `repo:`, `archive:`,
  `research:`), stating what changed rather than what was done.
- **The installed copy is what actually runs.** The loops execute
  `~/.claude/plugins/marketplaces/aiworkflow/` — a GitHub clone — so an edit here reaches future
  runs only after push + marketplace update. `--plugin-dir` reaches your own session only, never
  the kc-spawned headless agents.
