# `dev` plugin — changelog

Notable changes to the `dev` slice-workflow plugin, newest first. Entries below the plugin rework
are retained as history — they document the template-era workflow this plugin supersedes (when the
workflow was copy-and-fill templates rather than an installed plugin).

## 2026-07-16 — the merge runbook becomes `/dev:merge-repos`

`runbooks/MERGING.md` → `plugins/dev/skills/merge-repos/SKILL.md`. Not a move: the runbook was
written against the template era and three of its load-bearing claims had rotted.

- **Phase 3 pointed at a source of truth that no longer exists** — "execute `AIWorkflow/ADOPTING.md`,
  apply its Step 1 copy-map and Step 2 variable substitution", at an absolute path predating `/work`.
  The plugin rework deleted the copy-map, the Jinja vars, and all of `scripts/`. Phase 3 is now two
  halves: project scaffolding sourced from `../DesignAssistant` (which still has it), then
  `/plugin install` + `/dev:onboard`. `build-all.py` and `run-suite` stop being copied scripts and
  become the manifest's `build:`/`test:` statements — the runner gates on `kc project test`, so that
  is where they belong.
- **One baked-in decision inverted.** The runbook said the four per-stack dev agents "stay
  per-subproject in `backend/.claude/agents/` + `frontend/.claude/agents/`". `/dev:onboard` deletes
  exactly those now. The skill says to leave them for onboard to sweep rather than hand-delete.
- **Learning #4 (the `orchestrator/pyproject.toml` Jinja vars) is gone** with the templates it
  described. The other eight survive; their sources re-point from the dead template to
  DesignAssistant.
- **Per-repo status moved to the issue tracker** (cards #234–236, one per remaining repo). Work
  state does not belong in a procedure that rewrites itself after every run. IoTSupport's run
  history is dropped — it is done, and git has it.
- `code_health` is not copied into new merges; the runbook was seeding the fork the archive is
  removing.

The skill is **finite**: DHCPApp, ElectronicsInventory, ZigbeeControl, then delete it. Its own
frontmatter and card #236 both say so.

## 2026-07-16 — `/dev:onboard`, and the allocator moves into the plugin

A seventh skill: `/dev:onboard` brings a repo onto the pipeline. In the template era onboarding was
mostly copying — skills, agents, scripts. The plugin ships all of that, so what is left is the parts
a plugin *cannot* provide: the project describing itself, and the cleanup of whatever it used before.

- **Retiring the old in-repo workflow** is by name, not by folder, and sweeps **every** `.claude`
  found recursively (older layouts put agents per-subproject). It deletes only what `dev`
  supersedes — including a `docs/**/task-workflow.md`, which the plugin now owns and which would
  otherwise sit there as a second, drifting contract. The four `upkeep`-era commands (`update-docs`,
  `refactor-audit`, `quality-*`) are explicitly **left**: `upkeep` is not built, so deleting them
  removes capability nothing restores.
- **The manifest's `test:` statements are the onboarding decision**, now that the runner gates on
  `kc project test`. A component that declares none is green by definition — right for a docs-only
  component, and the skill says so rather than inventing a gate.
- **The spec repo is scaffolded or reshaped, not assumed.** Preflight only checks the path is a
  directory, so a repo can pass preflight and still die at `/dev:triage` on a missing allocator or
  `slices/backlog/`. The bar is **shape, not contents**: the tree and its lifecycle folders, the
  `.gitignore`, the README `## Pending` list — plus whole superseded eras archived wholesale.
  Old-format slice *bodies* are explicitly left alone: `/dev:plan-slice` reads one and deals with it
  when it plans it, and reworking a slice nobody is planning is speculative effort spent without the
  context the planner will have. Numbers are never recycled or renumbered.
- **Done is machine-checkable:** `preflight.py --for run` exits 0.

**`allocate-next-slice.sh` moves into `plugins/dev/tools/`** and takes the spec repo as an argument
instead of deriving it from its own location. `/dev:triage` calls the plugin's copy, so a spec repo
carries none: N copies across N spec repos were N chances to drift, and the numbering space is the
project's while the algorithm is the workflow's. The repo's template-era `specs/` reference tree
(the last of the Jinja placeholders — `{{ project_short }}`, `{{ specs_repo_path }}`) is deleted
with it.

## 2026-07-16 — the six commands become skills

`plugins/dev/commands/<name>.md` → `plugins/dev/skills/<name>/SKILL.md`, one directory per skill,
each with a mandatory `name:` matching its directory. **Nothing about invocation changes:**
`/dev:triage`, `/dev:run-slice`, … resolve exactly as before, and every `${CLAUDE_PLUGIN_ROOT}`
reference, `argument-hint`, and `write-task`'s `allowed-tools` carry over untouched. Claude Code
loads skills and commands into one registry — the move is a layout change, not a behavior change.

The motivation is that `commands/` is the legacy path: Claude Code 2.1.211 tags it
`loadedFrom: "commands_DEPRECATED"` internally while skills load as `"skills"`. Skills also unlock
per-skill supporting files and `context: fork` if the pipeline ever wants them.

Verified against the running build rather than the docs (the network here resolves them to a
captive redirect): the binary's own strings confirm plugin-sourced skills are both user- and
model-invocable, `name`/`description` are the only required frontmatter, and `version:` is **not**
required. A widely-cited GitHub issue (#41842) claiming plugin `skills/` never register as slash
commands does **not** hold for this build — Anthropic's own `example-plugin` ships a skill whose
body states the two formats are "functionally identical … only the file layout differs."

## 2026-07-16 — the runner runs the gate; the tester becomes a fixer

Syncs the workflow changes KubeCoder validated after the plugin rework (its commits `ca1d5c1`,
`2d7c320`, `6f8a9c2`, `8b1d6b6`, `c88c3d8`, `d08d5ea`). The rework of 2026-07-12 migrated from
KubeCoder's `.claude/` + `tools/`, so that is this sync's baseline; everything KubeCoder changed
since is either here, or recorded below as deliberately not ported.

- **The runner runs the gate.** The `code-tester` agent is gone. Detecting green is deterministic —
  no session is spawned to learn the gate's color — and only fixing red needs a model, so a
  `test-fixer` spawns on red and its `clean` is confirmed by a gate re-run, never trusted. **A red
  gate cannot merge** (new bail reason: `gate_red`); red can stall a task, never ship it.
- **The gate is `kc project test --project <name>`, not a script path.** KubeCoder's
  `<project>/tools/run_tests.py` is a stopgap for exactly this by its own docstring, and
  `project-contract.md` already declared the seam — so the contract ported, not the path. It runs
  from the repo root: `kc` resolves `.kubecoder/project.yaml` against its own cwd with no upward
  walk. What "test" means for a component is the operator's call, declared in the manifest; a
  component that declares no statements is green by definition, and that is a valid answer, not a
  gap for the runner to second-guess. `kc` rejecting the component *name* is different — that is
  `protocol_failure`, since the name came from `kc project list`.
- **`grounding.md` replaces `focus_notes.md`.** The writer keeps a claim→source ledger for
  behavior-describing prose; the reviewer verifies citations instead of re-deriving every claim
  (slice 084: each fix round minted new false claims — a vague sentence sharpened into a precisely
  false one).
- **The review cap becomes a budget** (2 → 3, extendable by 2 grants to 5). A finding raised in the
  final round had its fix written but never re-reviewed; `another_round` buys the confirming round
  instead of merging it unseen (slice 082: 4 of 11 tasks, every one a real defect).
- **The plugin has tests.** KubeCoder's runner suite ports (23 tests), with the `kc` seams stubbed.
  It caught a real port defect immediately: `_task_state` must back-fill keys missing from states
  written before those keys existed, or any resume across this change dies on `KeyError gate_runs`.

Not ported, deliberately: `af72dfc` (adds `RETEST_PROMPT`, which `d08d5ea` then deletes — the
plugin never carried it); KubeCoder's `CLAUDE.md` changes (project facts with no plugin
destination — the plugin cannot ship a `CLAUDE.md` by design); and KubeCoder's `slice-dag.md`, where
the plugin is the fresher copy. `run-slice.md`'s `gate_red` route was authored here — KubeCoder's
own copy never grew one.

## 2026-07-12 — the workflow becomes the `dev` plugin (v0.1.0)

The slice workflow stops being templates you copy into a repo and becomes an installable Claude Code
plugin, `dev`, hosted in this repo's marketplace (`.claude-plugin/marketplace.json`). Instead of
copy-and-fill, a repo describes itself: everything that was a Jinja blank or a hardcoded per-repo
constant is now either a `kc` call or a short `CLAUDE.md` entry.

- **kc-native runner.** `task_runner.py`'s three project-specific seams collapse into `kc`:
  `PROJECT_DIRS` → `kc project list --output=json`; the `claude_session.py` wrapper (retired) →
  `kc session create-headless|send|status|end`; `FORCE_PROMPT_CACHING_5M=1` → `-e` on
  create-headless. `REPO_ROOT` now comes from `git rev-parse --show-toplevel` (the runner no longer
  lives in the target repo). Agents spawn namespaced as `dev:<role>`; consults spawn bare. Verified
  against the actual kc surface (KubeCoderSpecs slice 079): the flag is `--output=json`, and the
  status snapshot carries `sessionId` (empty until the first turn).
- **Plugin surface.** 6 commands (`triage`, `plan-slice`, `run-slice`, `write-task`, `slice-dag`,
  `arch-design`) → `/dev:*`; 8 agents; `task_runner.py` + a new stdlib-only `preflight.py`; contract
  docs (`task-workflow.md`, `project-contract.md`, `preflight.md`). All plugin-internal paths use
  `${CLAUDE_PLUGIN_ROOT}`.
- **Project contract.** `.kubecoder/project.yaml` + three machine-checkable `CLAUDE.md` lines
  (`Spec repo:`, `Slice testing strategy:`, `Design philosophy:`), enforced by preflight (profiles
  `--for triage|plan|run`). Issue-tracker + notification wiring is referenced generically; the
  concrete form lives in the host `~/.claude/CLAUDE.md`.
- **Repo rework.** `orchestrator/`, `project/`, `EXAMPLE.md`, and the retired `tools/ai_workflow`
  scripts are deleted; `MERGING.md` moved to `runbooks/`; `README`/`ADOPTING`/`AUTHORING` rewritten;
  the auxiliary commands + `documentation-model.md` parked under `plugins/upkeep/` as backlog for a
  planned second plugin.

Not yet live-tested against `kc` (no `kc` in the authoring env) — the operator validates on a real
slice. See `plugin-plan.md` for the full plan and open items.

## 2026-07-10 — #175: the task-runner workflow (developed in KubeCoder, not yet synced here)

The workflow's execution core moved from LLM-driven skills into a script. Developed and validated
in `../KubeCoder` first; this repo's templates (`orchestrator/`, `project/`, `tools/`) sync after
the validation slices. An adopting repo replays:

**New pipeline.** `/triage` → `/plan-slice` → `/run-slice` + `tools/ai_workflow/task_runner.py`.
Canonical contract: the target repo's `docs/conventions/task-workflow.md` (folder layout, verdict
schema, bounded loops, escalation ladder, session mechanics).

**Skills.**
- `/write-slice`, `/major-change`, `/minor-change` — **deleted.** Triage's output folder *is* the
  slice (`slices/NNN_slug/slice.md`; triage allocates the number, opens the Kanban card, archives
  source cards, adds the README Pending line). The major/minor distinction no longer exists —
  planning is slice-level, execution is uniform per task.
- `/plan-slice` — **new**: interactive session that dispatches plan-writer/plan-reviewer to break a
  slice into 3–6 ordered, project-local tasks (10 the hard limit — the cap is per slice, not per
  project as pre-#175); verifies requirement fidelity itself; seeds `verification.json`. Task
  folders are `tasks/NN_slug/` — two-digit ids, visually distinct from three-digit slice numbers;
  a letter suffix (`04a`) inserts a task between existing ones mid-run.
- `/run-slice` — **rewritten thin**: preflight → launch the runner as a background shell → handle
  bail-outs (`bailout.json` reasons → `/write-task` + `--resume`, or defer to operator) →
  close-out. It never drives the dev loop.
- `/write-task` — **new**: author one task folder from a findings / missing-task write-up.
- Every skill carries a self-sufficient `description:` frontmatter (the root CLAUDE.md skill list
  is gone).

**Agents.** All dev agents rewritten to the thin shape (identity + output contract + bounds); the
output contract is literally the verdict-file schema. `code-tester` (Sonnet, fresh per round,
fixes-and-closes trivial issues) and `test-agent` (Sonnet, verification handovers) are new;
code-writer loses testing (keeps lint); reviewers describe problems and never prescribe fixes;
tester and code-reviewer receive `slice.md` and the task's `plan.md` as requirements — framed, not
raw: the tester mines the plan for coverage but never treats it as verified truth, the reviewer
judges outcomes rather than approach (plan deviation that meets requirements is not a finding;
missed planned edge behavior, broken pinned interfaces, and silent substitutions against
`slice.md` are), and both are scope-guarded (the slice spans tasks; only this task is under
test/review). The plan-writer's companion JSONs
(`requirements.json`, `file_map.json`, `test_plan.json`) are gone. The external-surface-probe /
substitution-test blocks are deleted in favor of a one-line grounded-claims rule. "Never work
around environmental problems — report `blocked` and stop" is now a bound in every agent.
`slice-verifier` (the `/run-slice` close-out check, on probation) keeps its evidence discipline
unchanged but is reframed for the new pipeline: the log is seeded by `/plan-slice`, not maintained
by an orchestrator, and its artifact blindness now names the current slice-folder files — it
deliberately does NOT read `slice.md`/`plan.md` (unlike the dev-loop tester/reviewer), staying the
one check with no shared framing.

**Tools.** `claude_session.py` gains `--cwd`, `--agent`, `--model`, quiet-by-default stderr
(`-v` restores) and a `run_claude()` library entry; `task_runner.py` is new (spawns fresh
`claude --agent` sessions with `FORCE_PROMPT_CACHING_5M=1`, cwd = the task's project);
`track_build.py` gains `--diagnose`. A session that ends without its verdict file or with
uncommitted changes gets **one resume-nudge** to finish its protocol; after that a missing verdict
is `blocked` and a dirty tree bails — the runner never `git add -A`s an agent's leftovers.
Runner output goes to `<slice>/log.txt`, never stdout (`-v` echoes it) — the orchestrator reads
exit code + `state.json`/`bailout.json`, so no progress stream ever floods its context. A crashed
run (host restart, quota stop, Ctrl-C) reattaches on `--resume`: `state.json` tracks the in-flight
session id and the worktree is preserved for it (consults and timed-out sessions never reattach).
The post-task checkpoint consult is unconditional (`--no-checkpoint` removed), and preflight fails
hard (exit 2, both in the runner and `scripts/preflight.py`) on a dirty working tree.

**CLAUDE.md set.**
- Root: stripped to a generic project brief (orchestrator guidance, skill list, agent management,
  deploy/cexec mechanics, Trello/notification detail all removed). Keep: slice-workflow pointer,
  specs layout, commit discipline + the push-green-light hard rule, design philosophy summary,
  conventions, issue-tracking pointer.
- Deploy happy path → `docs/operations/deploy-operations.md`; cexec was already in worker docs.
- Two-board Trello model + MCP ids + card conventions + push-notification rule →
  `~/.claude/CLAUDE.md` (host-global; cross-project by design). **Deferred:** the same content
  into the env-pod CLAUDE.md template (worker `internal/claudemd` — application code, needs a
  task).
- Subproject CLAUDE.mds: Design-philosophy → `docs/conventions/change-discipline.md` (now with the
  internal-vs-external boundary), Decision-making sections deleted, testing policy notes → each
  project's `docs/testing.md`, worker's VS-Code packaging → `worker/docs/vscode-extension.md`.
- "Never dismiss failures as flaky" lives in code-tester/test-agent definitions + a run-slice
  note, not CLAUDE.md.

**Docs.** `documentation-model.md`: diet rule ("state every fact exactly once; no recap
sentences; 100 lines is big") + primary doc keeper is `/plan-slice`.

**Deploy verification → a project slice test plan.** `/run-slice`'s close-out no longer hardcodes
the push/CI/live-test dance. The skill is repo-agnostic (this repo owns it; targets hold a copy), so
its deploy-verification section is now a **bare pointer**: run the project's slice test plan once the
tasks are merged. All testing-strategy detail — whether it pushes, what it checks, how findings
resolve — lives in the **project-owned** `docs/operations/slice-test-plan.md`. An adopting repo
**authors its own** such doc and repoints the deploy-verification line in
`docs/conventions/task-workflow.md`. KubeCoder's plan (the worked example, because it has no isolated
per-slice test environment): one operator gate → fetch/rebase/push/CI → live tests on prd, findings
fixed in-slice only on significant breakage (minor/cosmetic defer to a related slice; doubt to the
operator), so each in-slice fix means another push-and-test gate.

**Known open items.** Skill-vs-agent-type naming collisions (`arch-design`, `update-docs` vs
`update-architecture`) unresolved; Trello **Accepted** list is vestigial (triage now archives
source cards directly); docs-diet splitting of oversized topic docs (`config-model.md` etc.) not
yet done; env-template CLAUDE.md addition deferred (above).
