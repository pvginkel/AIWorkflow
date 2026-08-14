# `dev` plugin — changelog

Notable changes to the `dev` slice-workflow plugin, newest first. Entries below the plugin rework
are retained as history — they document the template-era workflow this plugin supersedes (when the
workflow was copy-and-fill templates rather than an installed plugin).

## 2026-08-14 — comments must be witnessable, prose findings must show wrongness (v0.4.5)

The comment-economy pair from `docs/research/interventions.md` (B1+B4), one rule each side of the
review boundary. Coder side (B1): the "invariants only" comment rule gains its missing criterion —
verifiability. A comment must state a condition code, a test, or a gate can witness; predictions
and strength-graded claims ("will/may/should …" about future or external behavior) are deleted,
not hedged, while load-bearing warnings ("must run before X") are invariants and stay. Reviewer
side (B4): a prose finding must show the text is *wrong* — contradicted by the code or the spec —
not that different words would be better; meaning-preserving wording drift is not a finding.
Together they remove the substrate the will→may findings grow on and the reviewer's license to
prefer its own phrasing. Effect is read off I1's comment-category finding rate and comment density
per diff (`docs/research/status.md` tracks both entries).

## 2026-08-14 — triage filters the cruft before planning spends on it (v0.4.4)

The triage skill, reworked ground-up around a filtering layer — the plan phase was where items
that should never progress got expensive. Raw material lands on disk verbatim before anything
else (also when triage starts mid-session); items are split mechanically and labelled against a
worked-example rubric — nit pick (user-visible/internal), corner case, minor, major, improvement,
feature, invalid — with every label justified by a verbatim source quote, never a generated
rationale, judged per-item in isolation, keyed on the stated consequence (a claimed severity
stands until the operator or a research verdict says otherwise). One consolidated operator pass
adjudicates via typed rulings — close / answer / override / remark — where a bare remark never
moves a label. Items whose label neither the source nor the operator settles get one read-only
sub-agent answering one named question ("cannot determine" allowed); the verdict settles the
label and none of it carries into the slice. Invalid and corner case are guarded — never
assignable from belief — and no item is ever closed by machine judgment alone. The final
category is stamped on each slice.md requirement and the README Pending line. Steps that don't
apply are skipped. Design honed against the docs/research corpus (judge-mode bias, sycophancy,
fact-vs-impact reliability split, premature disengagement); scope note added to interventions.md
A4 — an operator-adjudicated label is not the rejected automatic-routing grade.

## 2026-08-14 — the intervention catalogue's first batch ships (v0.4.3)

Six entries from `docs/research/interventions.md`, actioned together: the instrumented review/fix
contract (I1, C1, C2), the cost readout (I2), and the shape-bound plan contract (A1, A2). Per-entry
state and success criteria are tracked in `docs/research/status.md`.

- **Findings telemetry (I1).** The code-reviewer's verdict reports every finding
  machine-readably — id, severity, impact, category, anchor — and the driver persists the list
  into `state.json`'s history rows, alongside a fix round's `refuted` list. Problems B and C
  become measurable per run; slices 143+ against the ≤153 baseline is the 0.4.2 before/after.
- **Anchoring taxonomy (C1).** A `blocking` impact tag now requires one of five recorded
  anchors — failing test/command, repro trace, analyzer output, requirement-to-code
  contradiction, coverage gap against a named AC. No anchor is advisory by construction, and
  readability/taste/hypothetical-performance/unspecified-edge-case findings can never anchor.
  Replaces the looser "failing-input logic or a test sketch" severity bar.
- **Demonstrate-failure-first fix rounds (C2).** A fix round witnesses each executable-anchor
  blocking finding before changing code — the failing test rides the fix as its regression
  test. A finding that cannot be made to fail is **refuted**: no code change, carded with the
  refutation evidence, the record appended to the round's review file, never relitigated; a fix
  round that refutes every blocking finding with no code change settles the review outright.
  Inspection anchors (contradiction, coverage gap) keep their current handling.
- **Cost readout (I2).** `slice_cost.py` derives the close-out ratios — planner share,
  research-subagent share, rework share (rounds ≥2 + consults) — and `--write-state` appends
  them to `state.json` as `cost`; `/dev:run-slice` runs it at close-out, so cost trends read
  off committed run records instead of transcript archaeology.
- **Task shape + question-gated research (A1+A2).** The plan-writer declares
  `pre-settled` / `localized` / `cross-cutting` in plan.md before investigating, justified in
  one line from slice.md facts; `pre-settled` forbids research sub-agents and repo sweeps, and
  at any shape a research dispatch must name the open question it settles — a settled question
  is never re-dispatched. The plan-reviewer checks the declaration against slice.md. Grounding:
  slice 153 spent $27.72 before any code existed on a slice whose slice.md said "you are not
  designing anything".

## 2026-08-13 — fix rounds stop relitigating comments (v0.4.2)

Ansible slice 013 ($45, 3h wall for a small slice) spent the second rounds of two of its three
phases on comment wording. The chain: the reviewer reported advisory prose findings with forensic
evidence (Jenkins build-history archaeology to falsify one comment sentence, a git dig to date a
dead doc anchor); the fix round's "resolve every finding" pulled every advisory in alongside the
one blocking finding; the comment fixes became the delta review's subject and bred new comment
findings; the completion consult mopped up what was left. Three prompt-level bounds close it:

- **Fix rounds resolve blocking findings only.** `EXECUTOR_REVIEW_FIX_PROMPT` scopes the round to
  findings tagged blocking; advisories are the loop's (cards at close-out, the residue rider's
  in-place mop-up for mechanical comment fixes at loop tail — the cheap path that already
  existed). An advisory fixed mid-loop widens the next re-review to everything the fix touched.
- **Delta reviews verify blocking resolutions and stop re-deriving the world.** Unfixed
  advisories are the protocol working, not a gap to re-report; premises the prior round proved
  (live registry state, sibling-repo behavior) are re-derived only where a fix commit touches
  them.
- **Comment and prose findings are advisory by default and earn one sentence, not research.**
  Reviewer rule: harm from following the words is what promotes one to blocking; a comment claim
  that takes live-system or history archaeology to falsify was not worth the archaeology; one
  report is the finding's whole lifecycle. Verdicts now hinge on the impact tag — `signoff` =
  nothing blocking — matching what the better reviews already did in practice.

## 2026-08-11 — the phased-plan rebuild comes home (v0.4.0)

KubeCoder vendored 0.3.1 back onto its `main` on 2026-07-31 and rebuilt the pipeline there
(`KubeCoderSpecs/ai-workflow-redesign/`), against a design that replaces the task-folder model with
a **phased plan**. Four pilot slices ran it end to end — 114, 125, and the parallel pair 104/107 —
at $56–164 each, with the pathologies the redesign targeted staying dead all four times. This
release is that rebuild ported home, and KubeCoder's copy is deleted in the same change: the
workflow has one home again.

**The plan is the queue.** `task_runner.py` becomes **`run_loop.py`**, driving one `plan.md` of
`### P<id>` phases instead of `tasks/NN_slug/` folders. Each phase opens with a `Target:` line (a
`kc project list` component *or a sibling repo* — cross-repo phases are first-class now), document
order is authoritative, and only the driver stamps `✅ DONE`. Every agent in the loop may edit the
plan; appending a phase is how work grows, bounded by a **generation bar** that folds small in-scope
touch-ups in early and cards the rest at close-out.

**The loop owns the whole slice, not just the merges.** After the last phase: a loop-tail
`lint`+`build`+`test` sweep across every touched repo, a completion consult, then a **test phase**
and a **doc phase**, each "read the project's doc and execute it". The driver holds the spec repo's
devlock across both, and under that hold pushing and rolling dev for verification is
pre-authorized — prd stays explicitly operator-gated. Two new agents serve them: **`doc-writer`**
(diff-based over the whole shipped slice) and **`rebase-agent`** (mechanical rebases onto a moved
base, on Sonnet). A fourth `CLAUDE.md` contract line, **`Slice doc plan:`**, is what the doc phase
resolves through.

**The plan loop is one structural round.** `plan_loop.py` no longer iterates: a writer pass, a
reviewer pass, and exit — findings go to the operator for adjudication, whose rulings land in
`plan.md` and drive exactly one fix pass. The review is not optional; exit 0 is refused without a
reviewer verdict on file.

**The grounding ledger is gone** — `grounding_check.py`, `grounding_dispatch.py`, the
`slice-grounder` agent and `grounding-ledger.md`. Grounding survives as evidence citations in
`verification.json`, whose acceptance criteria are outcome-level. Also retired: `plan-briefer`,
`plan-scribe`, `slice-verifier`, and the `write-task` skill (a plan phase is a heading, not a
folder to author).

**New: the residual-sweep lane** (`sweep_slice.py` + `residual-sweep.md`). Cards whose acceptance
criteria triage can write from the card text alone batch into a mechanically generated slice that
skips `/dev:plan-slice` entirely and runs on the ordinary loop.

**This repo gains a gate.** `kc project test|lint` now run the plugin's ~4,700 lines of suite here
(159 tests) — before, nothing in AIWorkflow could run them, which was survivable only while
KubeCoder held a copy. `tools/analysis/` retires with the move: `slice_cost.py` ships in the plugin
and prices a slice from the run's own state records, superseding `slice_costs.py`, which guessed a
session's slice by regex over raw transcripts and hardcoded a `-work-KubeCoder` project map;
`runner_sessions.py` read a `task` key `run_loop.py` no longer writes.

Not ported, deliberately: KubeCoder's `update-docs` skill and `track_build.py` stay project-owned —
the first because a project's documentation model is its own, the second because it is CI tooling
that never belonged to the pipeline.

## 2026-07-29 — `kc status` joins the preflight (v0.3.1)

Preflight's v1 note said "no daemon-reachability check — the first `kc session create-headless`
failure is the signal". `kc status` now exists (worker daemon over loopback `/healthz`, controller
reachable *and* authenticated), so the signal moves to step one: **`--for plan` and `--for run` gate
on it**, as an environment failure (**exit 2**, alongside the `kc`-on-PATH check) — a dead control
plane means every dispatch fails, but nothing in the project is wrong, so the project is not the one
asked to fix it. The check runs before the repo is resolved and relays `kc status`'s own report,
whichever stream it came out of.

**`--for triage` is deliberately exempt.** Triage dispatches nothing and touches no `kc` surface —
it is intake, doable without the repo. The cost of the check there is a false gate, not the 20ms.

`preflight.py` gains its first suite (7 tests) covering the check, its exit code, its position in
the sequence, and the profile split.

## 2026-07-29 — the last KubeCoder sync (v0.3.0)

KubeCoder — the repo the workflow was developed and validated in — now runs inside a KubeCoder
environment and installs this plugin like every other repo. This sync ports everything its vendored
copy learned since the 2026-07-16 baseline (KubeCoder `912da03`, 35 commits), after which the
vendored copy is deleted and **the plugin is the workflow's only home**: improvements land here
first from now on, there is no upstream left to sync from.

Five sub-syncs, each its own commit:

- **The grounding ledger** (`grounding_check.py` + `grounding_dispatch.py`, suites,
  `grounding-ledger.md`). Claim→source ledgers with mechanical drift checking: the checker
  re-greps every entry's anchor, `--repair` fixes `MOVED` lines with no model involved, and
  tiered handling routes real drift to a scoped re-grounding pass — only a falsified load-bearing
  claim reaches the operator. Both scripts derive the repo root from `git rev-parse
  --show-toplevel` at the caller's cwd (the vendored copies hardcoded their repo).
- **The runner.** The review loop's economics replace the cap-3-plus-2-grants scheme: round 1's
  fix is automatic, every later `issues` verdict goes to a funding consult that judges the
  findings against a bar that rises each round, and the old cap survives only as a backstop (5)
  at which funding is withheld. Rounds bank on a verdict, not on dispatch; rounds 2+ are
  delta-scoped to the fix range; every round is told the gate's verified state. D177 graded
  writer routing lands (`task.json`'s `grade` picks round 1's model — `mechanical` → Sonnet,
  `standard` → Opus, `gnarly` → Fable; every later round runs Opus, and a Sonnet round 1 licenses
  the fix round to redo rather than patch). Fix rounds are fresh sessions (a resumed round's
  accumulated context cost ~2.2× per turn). Account session-limit windows are waited out and the
  round redispatched — never nudged, consulted, or counted. Grounding freshness rides every
  initial writer dispatch, and the checkpoint consult gets a whole-ledger drift summary as
  deterministic input.
- **The plan loop** (`plan_loop.py` + suite, `plan-loop.md`) — `/dev:plan-slice`'s mechanical
  half, which previously had none: fresh plan-writer/plan-reviewer rounds against a stored review
  budget (4, `--grant` extends, `--reopen` re-enters a done loop), `questions` verdicts that pause
  the loop for operator rulings, delta-scoped re-reviews, grounding `--repair` before every
  dispatch and `--prune` at GO, then hygiene, cross-reference lint, and deterministic
  `verification.json` seeding. Three new agents — `plan-briefer`, `plan-scribe`,
  `slice-grounder` — and the `plan-slice` skill rewritten around the loop: the coordinator holds
  decisions, not documents.
- **Close-out and the remaining prose** (`close_slice.py` + suite): the mechanical half of
  `/dev:run-slice`'s close-out — README entry Pending → Completed, folder to `slices/completed/`,
  staged by name, commit left to the session. Run-slice gains a grounding preflight
  (whole-ledger `--repair`; tier 2 dispatches a scoped re-grounding, tier 3 stops before the
  runner starts). The nested-delegation house rule lands — delegate the reading, keep the
  judgment — and `slice-verifier` / `arch-design` fan their per-item reads out under it.
- **The contract docs** reconcile into topic docs, one home per claim: `task-workflow.md` keeps
  the shared contract; `task-runner.md`, `runner-state.md`, and `agent-dispatch.md` (re-authored
  around the `kc session` seam) take the mechanics. `/dev:onboard`'s delete-list now names
  everything the plugin supersedes — eleven agents, five scripts, six contract docs.

Not ported, deliberately: `PROJECT_DIRS` and its `mcp-server` fix (the manifest is the component
source here, so the bug cannot exist); KubeCoder-specific prose — the hardcoded project list in
`plan-writer`, the `cross-repo-tasks.md` required-reading pointer, the `../KubeCoderSpecs`
decision-index path, and `task-workflow.md`'s board-states section (tracker wiring is
host/project business); `update-docs`'s fan-out half (it belongs to the unbuilt `upkeep` plugin);
and `track_build.py`, which is CI-wait tooling, not workflow, and stays with its project.

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
