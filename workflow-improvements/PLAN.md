# Workflow improvements — plan (Trello Triage #175)

**Status:** planning artifact. **Execution happens in a later session; nothing here is applied yet.**

**Target repo:** `../KubeCoder` (not this repo). The workflow is iterated *in KubeCoder* — make the
changes there, validate with a few real slice runs, and only then **sync the settled result back
into this AIWorkflow repo** (the source-of-truth templates in `orchestrator/`, `project/`, `tools/`).
So this plan references KubeCoder files (`.claude/agents/*`, `.claude/commands/*` skills, the
`CLAUDE.md` set, `docs/`, `tools/ai_workflow/*`).

**Companion:** [`ANALYSIS.md`](ANALYSIS.md) — execution-history analysis that motivates several of these
workstreams with hard numbers (source material for a secondary review). Cross-refs below as `[ANALYSIS §x]`.

**How to read this:** card #175 is reproduced as the workstreams below (lettered **A–L**; letters **F** and **K**
are intentionally absent — F, triage fidelity, already shipped (§0), and the analysis tooling moved
to `tools/analysis/`). Each has *Intent* (what the
operator asked, quoted verbatim where prescriptive — the card itself demands verbatim fidelity, so we
model it), *Current state* (evidence with `file:line`), *Changes*, and *Targets*. §0 records what recent commits already did; §M sequences the work; §N lists open decisions for the operator.

---

## 0. What is already partly done (recent KubeCoder commits)

Three commits on `main` have started #175; the first two are **partial**, the third closes one thread.

**`7ad7f65` "Merged all agent definitions"** — deleted the per-subproject copies of the four dev
agents and kept a single set at the repo root `.claude/agents/` (+18 net lines, −3,229). Root
`.claude/agents/` now holds the canonical `code-writer`, `code-reviewer`, `plan-writer`,
`plan-reviewer` (plus the orchestrator's `arch-design`, `slice-verifier`). This delivers the
**agent** half of workstream **B** (standardize / de-duplicate) — agents now live once, at root.
*Not yet done:* the same de-duplication for **skills** (`.claude/commands/*` are still a single set,
but per-project customization is baked into them — see B/§11), and the content trims in **G** (the
merged root agents still carry all the bloat the card wants removed).

**`8e2dd47` "Partial CLAUDE.md cleanup"** — removed the 5-line *"Keep the root `.claude/agents/`
dev-agent copies"* note from root `CLAUDE.md` (it described the now-obsolete dual-location model).
This is a small down-payment on workstream **H**; the large CLAUDE.md moves (issue-log, push-
notifications, deploy, cexec, Decision-making, skill list, testing) are **all still pending**.

**`a3eccbf` "triage skill: treat operator-provided API/spec definitions as specs"** — adds triage
steps (Phase 1c + Phase 5 + a key principle) that carry an operator's *considered* API/interface
definition into the change-request bundle at **signature-level fidelity** (evolving with recorded
deltas is fine; substituting a different API is not). This resolves the card's triage-fidelity thread
(*"when I get prescriptive, I expect requirements copied verbatim … into specs and ACs"*), so it is
**not** a workstream below.

**Implication for execution:** treat B-agents as done, keep going on B-skills; everything else in the
card is open. The two commits also mean the current agent-resolution model is **root-only** — no
per-subproject agent files — which simplifies G and H (no need to reconcile duplicated copies).

---

## A. Migration document / change-log (the card's framing question)

**Intent (verbatim):** *"I need a migration document for the stuff below to be added to AI workflow.
I'm not sure. Maybe as part of `ADOPTION.md` or maybe even a change log. There are cross document
(skill/agent/`CLAUDE.md`) changes that aren't trivially inferred from changes in the AI workflow repo."*

**Current state:** this repo has [`ADOPTING.md`](../ADOPTING.md) (adoption runbook) and
[`MERGING.md`](../MERGING.md). There is no change-log that maps a workflow-template change to the
cross-document edits a *target* repo must make to adopt it.

**Changes:** during execution, keep a running **migration log** that records, per change, the edits an
adopting repo must make that are *not* mechanically derivable from a template diff (e.g. "moved the
issue-log section from root `CLAUDE.md` to `~/.claude/CLAUDE.md`"). Decide its home — **recommendation:
a new `CHANGELOG-workflow.md` (or a section in `ADOPTING.md`)** — see §N. This is a deliverable *of*
execution, not a prerequisite; the plan just reserves the slot.

---

## B. Standardize skills (remove per-project copies; customization → docs)

**Intent (verbatim):** *"Sub projects have copies of skills. These need to be removed. Variation per
project like build instructions need to go in `CLAUDE.md`, or better into a docs file."* Plus
*"I want all customization gone from the AI workflow files. Move all of them into docs/ files."*

**Current state:** agents already de-duplicated (§0). Skills (`.claude/commands/*`) are a single set,
but they **embed KubeCoder-specific customization** [survey §11]:
- `run-slice.md` — `python3 tools/ai_workflow/claude_session.py …` (`:9,15,121,192,198,221`),
  `python3 scripts/preflight.py` + `uv sync --all-packages --frozen` (`:67,70`), `uv run pytest`
  (`:254`), `track_build.py` with hardcoded Jenkins jobs `KubeCoder/KubeCoder`, `DockerImages`,
  `IaC/HelmCharts` (`:350,358-370`).
- `major-change.md:62-63,103-104`, `minor-change.md:65-66,96` — `uv run ruff check .`, `uv run pytest`.
- `refactor-audit.md:14` — `uv run python -m tools.code_health --json`.
- `quality-improver.md:29-32` — hardcoded `/work/KubeCoderSpecs`, `quality-audits/` paths.
- `write-slice.md:114` — `../KubeCoderSpecs/scripts/allocate-next-slice.sh`; pervasive
  `../KubeCoderSpecs/...` literals across triage/write-slice/run-slice/slice-dag.

**Changes:**
1. Extract project-specific commands/paths (build, lint, test, session-launch, Jenkins job names,
   specs-repo path) into a **docs file** (e.g. `docs/conventions/workflow-commands.md`) and/or
   `CLAUDE.md`, and have skills reference "the project's verification commands" abstractly.
2. Confirm skills are single-location only; remove any residual per-project skill copies if present.

**Targets:** all `.claude/commands/*.md`; new `docs/conventions/workflow-commands.md`; `CLAUDE.md`.
**Depends on:** informs H (CLAUDE.md) and I (docs). **Motivation:** `[ANALYSIS §5]` — customization in
agent/skill files appears near-irrelevant to outcomes (runs succeeded with agent files unloaded).

---

## C. Task model + bounded loops (the structural core of #175)

**Intent (verbatim, preserved in full because it is prescriptive):**

> *The plan writer must split out the work into separate tasks that can be executed in relative
> isolation.* Important aspects of a task: **Can be tested independently** (full code/test/review
> cycle, committed); **focuses on a clear sub part** (planner clarifies focus area + reading material;
> *limited grounding overlap across tasks*); **PR-sized** (*"5 tasks per brief is high, maybe even the
> upper limit. 2 to 4 is the sweetspot"*); **may be large if simple/mechanical**, complex work favors
> smaller tasks. *"The planner decides on the tasks. Every task gets their own sub folder with their
> own implementation plan, code review, etc."*

The loop (verbatim):

> - The **code writer** does the implementation and writes up focus areas for the code tester (what
>   specs to run, where to focus).
> - The **code tester (Sonnet model!)** performs the tests and fixes issues from *its own grounding*,
>   using the writer's output only as hints. Per issue: **Simple fix** (Ruff finding, clear stack
>   trace) → fix, close it itself, do NOT report it (maybe a headline/count); **Non-trivial fix** →
>   write it up in the test-results doc and kick it back to the code writer.
> - If there are issues for the writer: the (same) code writer fixes them; a **new** code tester
>   (Sonnet, *fresh context every time*) re-tests. Loop until exhausted.
> - The **code reviewer** reviews; if issues, the same writer fixes and the rest of the loop repeats
>   (test, fix, review) until the reviewer signs off.
> - *"Create a branch per task. When the code reviewer signs off, the branch is merged. The code
>   reviewer focuses on the whole branch of the task, every time."*

Bounds (verbatim):

> - **Writer/tester loop hard limit = 3.** If the third tester escalates back: start a **new code
>   writer** (fresh context), same input as the original, told to do its own testing and complete the
>   pending work. Same escalation if the *workflow agent* determines from the tester's write-up that
>   it's stuck / went a bad direction (e.g. far too many changes — should have escalated instead). If
>   the tester's changes are bad, **drop them** (reset the branch/outstanding changes).
> - **Max 2 code-review rounds.** If the 2nd review found critical issues, **create Trello cards** and
>   raise to the operator at slice end; the rest of the slice proceeds. The operator decides whether
>   round-2 issues mean the slice needs rework.

Progress log (verbatim):

> *"a log must be kept in the slice folder. Every agent run gets one line with what happened, the
> result and decision. Very concise… This must follow a strict format and must be specified. CSV could
> make sense."*

Major changes the card calls out: work split into tasks (*"opens the door for larger slices!"*);
testing taken **out of** the code-writer's context (*"Big win… Fresh agent every time is important! The
testing agent doesn't need the implementation plan"*); code-reviewer also **doesn't get the
implementation plan**; loops allowed but strictly bounded.

**Current state:**
- Splitting today is *inside one plan*: `plan-writer.md:186-188` **"### 14) Implementation slices
  (only if large)"** — internal sub-slices, executed by a **single** code-writer. `[ANALYSIS §4.3]`
  shows the cost: one code-writer implemented a **4-part plan in 167 turns / 42M tokens / $24**, tests
  inline. There is no per-task folder/branch, no bounded loop, no progress log.
- `write-slice.md:102-104` defaults **"one bundle → one slice… Prefer one slice; do not split"** —
  must be reconciled with the new task model (workstream E).
- Testing lives *in* the code-writer today: `code-writer.md:21` "Testing is mandatory", `:32` "Run the
  project's verification commands… before declaring the work done". Reviewer already excludes some
  inputs but code-reviewer reads the plan (`code-reviewer.md:14`) — card wants it to **not** get the
  implementation plan.

**Changes:** introduce a **task** as the unit below a slice — plan-writer emits N (2–4) tasks, each
with its own subfolder (`plan.md` + companions + `code_review.md` + test-results + branch). Add the
code-tester (Sonnet) role; wire the bounded writer↔tester↔reviewer loop with the exact caps above;
define the **CSV progress log** format (columns: `ts, task, agent, model, round, action, result,
decision` — to be finalized). Update `run-slice.md`/`major-change.md`/`minor-change.md` to orchestrate
tasks+branches+merges. Remove the code-writer's testing responsibility (keep lint — see D). Stop
feeding the implementation plan to the code-tester and code-reviewer.

**Targets:** `plan-writer.md`, `code-writer.md`, `code-reviewer.md`, a **new `code-tester.md`** agent
(Sonnet), `run-slice.md`, `major-change.md`, `minor-change.md`; a new slice-folder log spec.
**Depends on:** E (sizing), D (test agent), G (agent trims). **This is the largest workstream.**

---

## D. Test agent (E2E + live deploy via handover docs; Sonnet)

**Intent (verbatim):** the orchestrator spends many tokens on tests — *"Re-running the end to end test
suite in cluster… Doing a live deployment/tests (waiting for the build to complete and running the
live tests)."* Make these **sub-agents** using **handover documents**: the E2E agent writes findings
to a handover doc; the live-deploy agent takes a test plan and returns the same findings doc. *"I want
this to become a single agent… The orchestrator can just write up what it needs the agent to do. The
agent definition then stays relatively simple… what output it's expected to deliver, and the bounds of
its responsibilities."* Switch models: *"Prime use case for Sonnet 5."*

Findings loop (verbatim): *"the project agent is initiated (a clean one) with a write up of what was
found and a request to fix it. That agent writes up a task in the same format as normal tasks. The
rest of the process is then business as usual."* Combine findings per project (one call per project).
**Limit to three rounds**; on a 4th round with findings still open, **stop the slice and inform the
operator** (who may request another round with guidance, or wrap up). *"Code writer does run lints
itself. If subagents could call subagents, I'd have the linting done there."*

**Current state / evidence:** `[ANALYSIS §2]` — the root orchestrator is **53% of all spend**;
`run-slice.md:249-257` has the orchestrator run the full suite itself; live-deploy verification runs
in separate post-push orchestrator sessions (`run-slice.md:338` gates deploy out of `/run-slice`).
`[ANALYSIS §4.1]` a 14h deploy-wait ran on **`fable-5`**; `[ANALYSIS §4.3]` the root session ran the
full workspace suite + live-pod verification with multi-hour idle. A single Sonnet test agent with a
handover doc directly removes this from the (expensive, long-lived) orchestrator context.

**Quantified (post-`track_build`):** [`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md) — even with
build-tracking already mitigated, the orchestrator is still ~44% of a slice's cost, and the **inline
live/E2E verification is now the single biggest sink: ~30–53% of a session** (~$18–21), run inside a
400–570k-token context at 1.7–1.8× cost/turn. This makes the deploy/E2E-verifier agent the **top
cost-reduction lever** (~30–40%/session). Also confirmed: an idle cache-TTL rewrite tax (~$2.1–3.9/
session) that a short-lived verifier avoids by not holding the context alive across the wait.

**Changes:** add a **single `test-agent.md`** (Sonnet) with a thin definition (output = findings
handover doc; bounds only). Orchestrator writes the per-run instructions. Route E2E-suite runs and
live-deploy/test runs through it. Wire the findings→clean-project-agent→task→normal-loop path with the
3-round cap and 4th-round stop-and-inform. Keep lint in the code-writer.

**Targets:** new `test-agent.md`; `run-slice.md` (Step 7 + live-verification + deploy-owed handling);
handover-doc format. **Depends on:** C (task format for findings), G (thin-agent style). **Motivation:**
`[ANALYSIS §5]` — model mismatch + orchestrator context economics.

---

## E. Triage / slice-writer resizing

**Intent (verbatim):** *"When the runtime skills and agents have been updated, the triage and slice
writer agents need to be updated so that they can resize slices."* (The task model *"opens the door for
larger slices."*)

**Current state:** `write-slice.md:102-104` "prefer one slice, do not split"; per-brief length ceilings
`:252-258`; `run-slice.md:205` minor threshold "≤~200 lines / ≤~5 files". `triage.md` deliberately does
**not** size slices (`:96` "group by subject, not slice boundaries"). [survey §12]

**Changes:** update `write-slice.md` sizing so a slice is sized to hold **2–4 tasks** (not "prefer one
slice"); align brief ceilings and the minor/major boundary with the task model. Update `triage.md` only
where its bundle guidance affects downstream sizing.

**Targets:** `write-slice.md`, `triage.md`, `run-slice.md`. **Depends on:** C (must land first — the
task model defines what a slice now sizes to).

---

## G. Targeted agent-file review (trim hard; reviewer describes, not fixes)

**Intent (verbatim, selected):** *"I want a thorough review of all agent files… I had runs where none
of the agent files loaded because of bugs. I still had decent results. That means most of the guidance
in the agent files are likely useless. I want them trimmed for things that are important."* Example:
the no-mocks rule *"There's like 4 mentions in the code review agent… It can be a single line… the
code review agent definition can likely be brought back to 25% of its current contents without loosing
any fidelity."* Code-writer: *"I don't see the point of the workflow section"*; the *"before writing
code"* section *"needs to go"* (the manager explains how to use the agent instead — *"It can even take
a different approach (direct ask). This stuff does not belong in the agent definition"*). The
"substitution test" block *"I don't think this adds value… I'm thinking: 'Claims must be grounded. Mark
ungrounded claims as major issues.'"* *"All 'External-surface claims' sections were added very hap
hazard. Check version control and delete them."* Plus: *"The code reviewer agent shouldn't be
suggesting fixes. It should describe the problem it found well, and why… but not an implementation
suggestion."* *"The code writer['s] reporting results section… needs to be brought back to the bare
minimum."* *"Hand over documents may be trimmed down significantly."* *"There's a lot of overlap in the
plan review and the code reviewer. Feels like they should be more distinct."* *"Remove subproject
wording… The plan writer agent only has to reference 'project documentation'."* And fix the skills-vs-
agent-types naming collision (arch-design / update-docs / update-architecture appear as both).

**Current state (first-hand + survey):**
- `code-reviewer.md` (172 lines): fix-suggestions baked in (`:60` "fix (minimal viable change)", `:153`
  "Prefer minimal fixes"); **"External-surface claims"** section `:121-146`; near-duplicate adversarial
  sweep `:83-101`. → trim to ~25%; strip fix suggestions; delete external-surface section (replace with
  a single "claims must be grounded; ungrounded claims are Major" line); make distinct from plan-review.
- `code-writer.md` (76 lines): **"Before writing code"** `:13-17`, **"Workflow"** `:27-33`, **"External
  surfaces"** `:36-59`, **"When reporting results"** `:70-76`, testing responsibility `:21,32`. → delete
  Before-writing/Workflow/External-surfaces; minimize reporting; remove testing (keep lint) per D.
- `plan-writer.md` (263 lines): **"External-surface probes (mandatory)"** `:198-237` (40 lines),
  "Cross-component wiring" `:239-248`, 16 plan sections overlapping the reviewer's sweep; root/subproject
  wording `:52`. → delete external-surface probes; de-overlap with reviewer; "project documentation"
  not "root ../docs/".
- `plan-reviewer.md` (149 lines): **"External-surface claims"** `:98-123` incl. the **substitution
  test** `:112-117` (the exact block the card quotes); sweep `:66-84` ≈ code-reviewer's. → same
  treatment; sharpen the plan-review vs code-review distinction.
- **External-surface phrasing also lives in skills** [survey scan]: `major-change.md:71`,
  `minor-change.md:69`, `run-slice.md:147` — delete/replace those too.
- **Provenance (the card's “check version control”):** the External-surface probe gate, the
  “substitution test”/anti-anchoring block, and the derivation-first mandates were all introduced in
  **one commit — `179f3fe` (2026-07-04, co-authored by Fable 5)** — across every dev agent plus
  `major-change`/`minor-change`/`run-slice`/`write-slice`. Its commit message enumerates exactly what
  it added and where — use it as the delete/trim checklist.
- Manager-writes-the-dispatch is already happening: `[ANALYSIS §4.1]` the per-project manager emits a
  2,924-token custom code-writer prompt — evidence that customization belongs in the manager, not the
  agent file.

**Changes:** rewrite the four dev agents to the "thin agent" shape (identity + output contract + bounds;
no workflow narration, no external-surface sections, no fix suggestions in reviewers); collapse the
no-mocks rule to a single grounded-claims line and a short requirements list; make plan-review and
code-review distinct (plan-review = design/fit/coverage-of-plan; code-review = correctness of the diff);
remove subproject/root wording; fix the skill-vs-agent-type naming collision.

**Targets:** `.claude/agents/{code-writer,code-reviewer,plan-writer,plan-reviewer}.md`,
`major-change.md`, `minor-change.md`, `run-slice.md`; new `code-tester.md`/`test-agent.md` follow the
same thin shape. **Depends on:** C/D define the new roles the trims must match.

---

## H. `CLAUDE.md` review (move content out; drop noise)

**Intent (verbatim, mapped to evidence):**
- Coding guidelines → `docs/` or (general ones) the code-writer. bot's *"Design philosophy"* → plan/
  code writer, but qualify *"No backwards compatibility"* to **internal interfaces**; external-interface
  rules → `docs/`. (`bot/CLAUDE.md:17,20`; dup `controller:23`, `worker:32`.)
- *"a lot of repetition between 'Testing expectations' in `bot/CLAUDE.md` and e.g. plan/code writer.
  I want this cleaned up."* Code-quality section → a `docs/` file included in the plan (a **required-
  reading starter set** the plan-writer builds from). (`bot/CLAUDE.md:33`.)
- *"The 'Decision-making' section needs to go. We need to trust the model."* — it's in
  `bot:69 / controller:89 / worker:116` (not root). [survey §2]
- worker *"Packaging the VS Code session-restore extension (slice 034 / D121)"* → `docs/`.
  (`worker/CLAUDE.md:78-101`.) [survey §7]
- The *"never run a slice"* remark → the **write-slice/run-slice skill** (preferred), not root
  `CLAUDE.md`. (`CLAUDE.md:33-35`.) [survey §4]
- *"even the skill list is pointless. That's already in context… do move the description into
  `description:` fields… But don't have a skill list."* — root skill catalogue `CLAUDE.md:44-57`.
  [survey §1] → delete the list; ensure each skill's `description:` frontmatter carries its summary.
- *"Deploying KubeCoder", "cexec"* → `docs/` (except *"operator must green light pushes"* stays). It's
  the testing/deploy strategy. (`CLAUDE.md:136-188` deploy, `:241-258` cexec.) [survey §5]
- *"The whole issue log section… into `~/.claude/CLAUDE.md` (and into the `CLAUDE.md` template for the
  KubeCoder environments). Same for push notifications."* (`CLAUDE.md:190-231` issue log, `:234-239`
  push.) [survey §3]
- *"Never dismiss test failures as flaky" → the new testing agent(s) files.* (`CLAUDE.md:110`;
  semantic dup `run-slice.md:377`; **no agent file** currently has it.) [survey §8]
- Remove **root/subproject wording**; project layout → each subproject's own `CLAUDE.md` explaining it
  is in a monorepo and that the parent `docs/` applies; plan-writer references *"project
  documentation"*. (Pervasive: root `:15,86-87`; each subproject Documentation para.) [survey §9]
- **Add** a note (to orchestrator `CLAUDE.md` or preferably `run-slice`): *"when you see someone else
  committing changes for your slice, it's very likely a different agent accidentally swooped up your
  changes because the specs repo is shared. Do not use it as an indication that a different agent is
  working on the same slice."*

**Current state:** root `CLAUDE.md` is 263 lines (deploy + issue-log + push + cexec dominate); each
subproject `CLAUDE.md` repeats Documentation/Decision-making/No-backwards-compat/Testing paragraphs.
`[ANALYSIS §4.2]` — the root `CLAUDE.md` is re-primed on every one of 12 orchestrator re-entries for a
single slice; trimming it has direct token payoff.

**Changes:** execute the moves above; leave root `CLAUDE.md` as a lean orchestrator brief. Create the
`~/.claude/CLAUDE.md` and env `CLAUDE.md`-template destinations for issue-log + push-notifications.
**Targets:** all six `CLAUDE.md`, several `docs/` files, `~/.claude/CLAUDE.md`, the env template,
`run-slice.md`/`write-slice.md`. **Depends on:** B, G (where content lands), I (docs style).

---

## I. Documentation diet

**Intent (verbatim):** *"docs/ entries **MUST** be concise and may not repeat things. Something like
'State every fact exactly once. No recap or summary sentences.'"* *"Can't the 'Linting / formatting
(ruff)' stuff go into config?"* *"Is 'Where tests live' smart/necessary?"* *"I'd like the entries
smaller. 100 lines is big. `controller/docs/config/config-model.md` is a good example. I think I prefer
this be 3 topics."* On `build-toolchains.md`: *"It's kind of good, right? It's lessons learned. Better
here than in `CLAUDE.md`. Still, it's a big one."* And (context-management): *"Everything in `docs/`
can go on a diet… the back filled ones are more terse… keep new ones as terse as existing ones."*

**Current state:** 94 docs files, ~6,290 lines across 6 scopes (controller 29/1,833; worker 29/1,813).
Older seed docs are terse (`errors.md` 29, `no-database.md` 30); the 2026-07-05 wave is denser/narrative
(`build-toolchains.md` 157, `config-model.md` 100, `pod-composition.md` 233), with some inter-doc
overlap. [survey §15-16]

**Changes:** add a **"state every fact exactly once; no recap/summary sentences"** rule to
`docs/documentation-model.md`; split oversized entries (target ~≤3 topics / smaller files) starting with
`config-model.md`; consider moving ruff config into actual config and dropping "Where tests live";
de-duplicate inter-doc overlap (e.g. toolchain fields in config-model vs build-toolchains).
**Targets:** `docs/documentation-model.md`, oversized `*/docs/*` entries, `pyproject.toml`/ruff config.
**Depends on:** receives content from B/G/H; the diet rule should land early so those moves are terse.

---

## J. `claude_session.py` — cwd + stderr-in-context

**Intent (verbatim):** *"I want to know whether the stderr output of `claude_session.py` appears in the
context. If so, it needs to be suppressed (add a -v/--verbose option)."* And *"I want `claude_session.py`
to take a cwd. KubeCoder regularly calls out into other projects… `cd /work/HelmCharts && kc session
start-headless`… It then loads the `project.yaml` file from that repo… I'm fine if we keep both options.
With the work done for #169 we're going to get this anyway."*

**Current state:** `tools/ai_workflow/claude_session.py` streams progress to **stderr** (`_run` →
`processor.process_line` → `print(..., file=sys.stderr)`), and projects are a fixed enum resolved from
`PROJECT_ROOT` (`VALID_PROJECTS`, `_project_dir`); there is no `--cwd` and no verbosity flag. Whether
that stderr lands in an orchestrator's context depends on how the orchestrator shells out (the card
wants this verified). `[ANALYSIS §1]` notes cost is context-driven, so stray stderr in context matters.

**Changes:** (1) verify whether the orchestrator's Bash captures this stderr into context; if so, add
`-v/--verbose` and make progress quiet by default. (2) Add first-class **cwd** support so a session can
run in a sibling repo and load that repo's `project.yaml` (coordinate with #169). Keep the existing
project-enum form as an option.
**Targets:** `tools/ai_workflow/claude_session.py`, `test_claude_session.py`, references in
`run-slice.md`/`major-change.md`/`minor-change.md`. **Independent**; ties to card #169.

---

## L. Cross-cutting naming + hygiene fixes

- Fix the **skill-vs-agent-type collision** (`arch-design`, `update-docs`/`update-architecture` appear
  both as skills and as Agent-tool subagent types) — the card flags the confusing overlap. Decide a
  disambiguating convention. **Targets:** skill files + agent definitions.
- Ensure every skill's `description:` frontmatter is self-sufficient (needed once the root skill list is
  deleted, H).

---

## Orchestrator-cost reductions (verified by the execution analysis)

From the per-turn deep-dive of `track_build`-using orchestrators
([`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md)). `track_build.py` already solved build-polling
(~$0.02–0.05/session; ~$2.6/push ROI); these are the *next* levers, in priority order:

- **Deploy/E2E-verifier agent (biggest win, ~30–40%/session).** Move the live-cluster/E2E verification
  off the orchestrator — this IS workstream **D**, now quantified as the top lever.
- **Trello content → slice bundle.** The orchestrator reads full Trello board dumps live (13–31k chars,
  re-read for 100+ turns). Pre-resolve the needed card content into the change-request bundle at
  authoring time so it is never fetched mid-run. *Targets:* `triage.md` / `write-slice.md` (bundle
  contents), `run-slice.md`. (Operator's suggestion.)
- **`track_build --diagnose` + token assertion.** On a *failed* build the orchestrator still manually
  tails the raw Jenkins log (~13k chars); add a `--diagnose` mode returning only the failure tail. And
  assert `$JENKINS_TOKEN` so `track_build` can't silently fall back to manual MCP polling (observed —
  it cost a slice its ROI). *Target:* `tools/ai_workflow/track_build.py`.
- **Trim `CLAUDE.md`** (workstream **H**) — the only user-controllable part of the ~48k-token base
  context re-read every turn.
- **Rejected:** "trim the MCP tool surface." Verified against the transcripts — MCP tools load
  **lazily** via `ToolSearch`; the base context is not MCP schemas, so there is nothing to gain here.

---

## M. Suggested sequencing (dependencies)

Execution is a later session; rough order that respects dependencies:

1. **Foundational, low-risk, independent:** the I-rule (docs "state once" rule) and J
   (claude_session cwd/stderr). These unblock or de-risk later moves and can land first.
2. **Define the new model:** C (task model + bounded loops + CSV log) and D (test agent) together —
   they define the roles everything else must match. **Biggest, riskiest; do jointly.**
3. **Re-shape the agents/skills to the new model:** G (agent trims), B-skills (de-customize), E (sizing).
4. **Move content out of CLAUDE.md:** H, feeding I (docs diet) as content lands.
5. **Throughout:** maintain the migration log (A); after it settles, **run 2–4 real slices in KubeCoder
   to validate**, then **sync back to this AIWorkflow repo** (`orchestrator/`, `project/`, `tools/`).

**Validation is by real slice runs** (the operator's stated gate), re-measured with `data/slice_costs.py`
to confirm the orchestrator-cost and code-writer-cost patterns from `[ANALYSIS]` actually drop.

---

## N. Open decisions for the operator

1. **Migration doc home (A):** new `CHANGELOG-workflow.md`, a section in `ADOPTING.md`, or a
   per-change log in the slice folder? (Recommendation: `CHANGELOG-workflow.md`.)
2. **CSV progress-log schema (C):** confirm columns/format (proposed:
   `ts,task,agent,model,round,action,result,decision`).
3. **One test agent vs two (D):** the card says "single agent" for E2E + live-deploy; confirm one
   `test-agent.md` handles both via different instruction sets (vs a dedicated live-deploy variant).
4. **Task branching model (C):** real git branches per task with merge-on-signoff, on `main` — confirm,
   given the shared-working-tree caution in root `CLAUDE.md:76` (branches may interact with the shared
   specs tree).
5. **"No backwards compatibility" qualification (H):** confirm the exact internal-vs-external boundary
   wording, and where external-interface rules should live in `docs/`.
