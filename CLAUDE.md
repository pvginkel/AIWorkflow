# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

AIWorkflow is a **Claude Code plugin marketplace**, not an application — nothing is built or
deployed from here. It hosts the `dev` plugin (the slice pipeline: `/dev:triage` →
`/dev:plan-slice` → `/dev:run-slice` → `/dev:close-out`, plus `/dev:onboard`, `/dev:slice-dag`,
`/dev:arch-design`, `/dev:merge-repos`), and it is the workshop where that pipeline is measured
and improved. The
plugin is **kc-native**: it targets the KubeCoder environment and expects `kc` on PATH, with no
non-`kc` fallback.

`README.md` is the map; `docs/AUTHORING.md` is required reading before touching any agent, skill,
or contract doc. `docs/rationale/` is the explanation layer — why each part is the way it is, with
the evidence — and links to the contract docs rather than restating them.

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
- Research corpus: `docs/research/tools/fetch_articles.sh` converts the arXiv papers cited in
  `docs/research/research-2.md` into `docs/research/articles/` (already-fetched papers are
  skipped; needs pandoc + latexpand on PATH and uv, see the script header) and `fetch_pages.sh`
  mirrors the non-arXiv sources beside them. `docs/research/tools/context_profile.py <slice-dir>...`
  replays a slice's session transcripts into per-turn context profiles (research tooling, not
  plugin — but the replay and the turn classes it reads are the plugin's `turn_profile.py`, which
  it imports; the aggregate analyses are its own); `t4_readout.py {writers,slices,plan-reads,all}`
  beside it reads slices run on a new plugin version against that corpus (the turns-plan T3/T4
  before/after); `risk_readout.py extract|report` scores every completed slice's review
  findings, phase diffs and close-out dispositions against a path-risk map (the #715 research);
  `r1_blocking_readout.py` reads the round-1 blocking rate per phase before/after 0.9.6–0.9.8
  against phase size and the reviewer's and writer's transcripts (the #782 research);
  `writer_economics.py bands|eras|subs` (imports `t4_readout.py`) gives the size-band,
  token-class and sub-agent-attribution views; `plan_qa_readout.py table|stats|dump` reads the
  operator interaction of every interactive `/dev:plan-slice` session — each dialog, its options
  and what the operator answered (the plan-interview readout). Run 1's corpus is frozen under
  `docs/research/archive/run-1/`.
- **Reading a run:** a slice's record is its folder in the project's spec repo
  (`slices/completed/NNN_slug/`): `log.txt` is the driver's narration, `state.json` is per
  `runner-state.md`, `phases/P*/` holds each round's review and result files, beside `plan.md`,
  `slice.md`, `verification.json` and `close-out.md`. `plugins/dev/tools/slice_cost.py <slice_dir>`
  prices it per role/phase/session; `close_out.py counts|list <slice_dir|close-out.md>` reads the
  report; `state.json`'s `plugin_version` says which plugin ran it. A round whose session died
  without a verdict leaves no history row — `log.txt` shows `[result] Done` with no `→ verdict`
  line — so it is absent from the report and from `slice_cost.py`; price it from the transcript
  with `turn_profile.replay`.

## Architecture

- **`plugins/dev/tools/`** — the drivers, each with a `test_*.py` beside it. `run_loop.py` (~3k
  lines) and `plan_loop.py` carry most of the logic and most of the ~4.4k lines of suite; plus
  `close_out.py` (the close-out report's mechanics, imported by both loops), `preflight.py`,
  `sweep_slice.py`, `close_slice.py`, `slice_cost.py` (with `turn_profile.py`, the transcript
  replay behind its turn table), `allocate-next-slice.sh`.
  Suites load their subject via `importlib.util.spec_from_file_location` (`tools/` is not a
  package) and fake sessions, git, `kc` and the gate — no agent is ever spawned by a test.
- **`plugins/dev/agents/`** (11) and **`plugins/dev/skills/<name>/SKILL.md`** (8) — the dispatched
  roles and the operator-triggered workflows.
- **`plugins/dev/docs/`** — the **canonical contract** for all of the above: `run-loop.md`,
  `plan-loop.md`, `runner-state.md`, `plan-template.md`, `refinement.md`, `agent-dispatch.md`, `close-out.md`,
  `close-out-template.md`, `project-contract.md`, `preflight.md`, `residual-sweep.md`. Behaviour
  changes here and in the code together; a doc that describes a loop the code no longer runs is a
  defect.

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
   never reaches it. What an agent noticed but the loop will not act on has one destination —
   the slice's `close-out.md` (`plugins/dev/docs/close-out.md`) — never a tracker card per
   finding.

**Portability is the constraint on every change.** The pipeline is generic; each project describes
itself through `.kubecoder/project.yaml` and an `.aiworkflowrc` (TOML at the repo root: the spec
repo, the procedure docs, and which phases the project runs at all), both enforced by
`preflight.py`. Never hardcode a project's names, paths, tracker or tooling into the plugin, and
never parse the manifest directly — only `kc` reads it.

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
- **Pick the version from `origin/main`, not the local tree** — `git fetch origin` first. Unpushed
  local commits make the local number stale and two changes claim it (0.7.4 was taken twice). On
  a collision, renumber the later change and add the one-line "X, not Y: <the other change> took
  that version while this sat unpushed" note to its changelog entry and commit message.
- **Check before stating push state.** The operator pushes from this pod between turns, so a stale
  `origin/main` lies — `git fetch` (or `git ls-remote`) before saying what is or is not pushed.
- **Who writes what.** Prose — agents, skills, contract docs, the changelog — is written by the
  session's own model or a fork of it (prompt quality is where the plugin's value lives). Code and
  mechanical work — `tools/*.py`, tests, version bumps — goes to an Opus sub-agent on disjoint
  files, briefed with the exact files and verify commands; review its diff before committing.
- Commit subjects are lowercase and scope-prefixed (`dev:`, `docs:`, `repo:`, `archive:`,
  `research:`), stating what changed rather than what was done.
- **The installed copy is what actually runs.** The loops execute
  `~/.claude/plugins/marketplaces/aiworkflow/` — a GitHub clone — so an edit here reaches future
  runs only after push + marketplace update. `--plugin-dir` reaches your own session only, never
  the kc-spawned headless agents.

## Settled rulings — don't re-propose

Operator decisions the code cannot show. Each was proposed, weighed and closed; cite the record
instead of reopening it.

- **No effort tiering, weaker model or Sonnet writer for the main roles** (plan-writer,
  plan-reviewer, code-writer, code-reviewer): the 0.7.0–0.7.2 step-down was withdrawn as "dead
  weight" (`docs/research/status.md` § A3, reverted in 0.7.3). Sub-agents and sub-sub-agents stay
  tunable (`docs/research/turns-plan.md` § T7).
- **No context compression, auto-compact windows, turn or token caps, or history summarisation**
  for writers and reviewers (`docs/research/turns-plan.md` § Deliberately not in this plan). The
  turns plan itself is exhausted (`docs/research/readout-2026-09-01.md` § 7).
- **Fix rounds resolve blocking findings only**; advisory and comment-wording findings never drive
  a round (0.4.2 — "bickering on comments, beyond my patience"). The same taste applies to work in
  this repo: don't relitigate wording.
- **The doc phase is auto docs only** — existing surfaces updated from the shipped diff. A doc
  requirement (close a decision, correct a page) is a plan phase targeting the spec repo (0.9.2).
- **No lanes, literal-edit bundles or no-research plan variant** in the plugin: the 2026-08-14
  lanes were a one-off board clear-out ("if I need this again, I'll ask for it directly").
  `apply the suggested edit` survives only as a triage scope ceiling.
- **No catch-rate or reviewer-recall work** — seeded defects, mutation-testing metrics, reviewer
  reading order or lens, plan pre-mortem, docs drafted in the plan loop — examined and closed
  (commit `dbd18a9`). The operator wants output quality, not defect-finding metrics.
- **No rework lever on cost grounds, and no restoring the writer's whole-plan or
  `verification.json` read**: rework is 9 % pooled with the consult priced apart (0.9.15, #720),
  and the round-1 blocking rise is phase size (`docs/research/r1-blocking-2026-09-01.md`). Fewer
  rounds come from phase sizing at plan time.
- **No `kc` verb for repo sync** (`kc project <verb>`, `kc env sync`, `kc repos`): preflight's own
  git sync (0.9.13) is the answer; the operator's editor entry point is a user-level task.
- **Cross-session messaging in headless sessions is kc's switch**, off by default
  (`crossSessionInbound: refuse` + deny `ListAgents` only; `SendMessage` kept for a session's own
  sub-agents). The plugin passes nothing — no agent-frontmatter `disallowedTools`, no kc
  `--settings` pass-through.
