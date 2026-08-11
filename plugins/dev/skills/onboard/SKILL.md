---
name: onboard
description: Make a repo usable by the dev pipeline — retire any in-repo copy of the pre-plugin workflow, settle the manifest's curated automation, add the contract lines, and scaffold or migrate the spec repo. Finishes when preflight --for run is green.
argument-hint: "[spec-repo-path]"
---

# Onboard

Bring one repo onto the `dev` pipeline. Installing the plugin is the operator's job (`/plugin
install dev@aiworkflow`); yours is everything the *repo* must provide — the contract in
`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, plus a spec repo the pipeline can actually work
in. There is nothing to copy: the plugin ships the skills, agents, loops, and allocator. What is
left is the project describing itself, and the cleanup of whatever it used before.

**Done means one thing:** `${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run` exits 0. Everything
below exists to get there, except the spec-repo work, which preflight cannot see (it checks only
that the path is a directory — `/dev:triage` needs much more).

**This skill changes the operator's repos and rewrites their spec history.** Inventory first, act
second, and stop at every decision point below. Never delete something you cannot name a
replacement for.

## Procedure

### 1. Inventory — report before you touch anything

Establish what is already true. Do not fix anything yet; a repo part-way onto the workflow is the
normal case, and the gap list drives the rest.

```bash
kc project list --output=json                       # components + effective cwds (empty/error = no usable manifest)
cat .kubecoder/project.yaml 2>/dev/null             # the manifest, if any
grep -nE '^[[:space:]>*`-]*(Spec repo|Slice testing strategy|Slice doc plan|Design philosophy):' CLAUDE.md
find . -name .claude -type d -not -path './.git/*'  # recursive: older layouts put agents per-subproject
${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run  # the gap list, in its own words
```

Preflight fails on the **first** violation, so re-run it as you go — it is a worklist, not a report.
Summarize for the operator: which contract pieces exist, what the components are, whether a spec
repo is named and what state it is in, and what pre-plugin workflow remains. Then work down.

### 2. Retire the in-repo copy of the old workflow

A repo that ran the pre-plugin workflow carries its own skills, agents, and driver. They now shadow
the plugin: a stale in-repo `code-writer` or `run-loop.md` outranks nothing, it just gets read
instead. Delete **only** what `dev` supersedes, by name.

The lists below carry **retired names too** — a repo may have stopped at any older version of the
workflow, and those copies shadow just as effectively as current ones.

Delete (the plugin provides each):

- the pipeline skills/commands — `triage`, `plan-slice`, `run-slice`, `slice-dag`, `arch-design`,
  and a retired `write-task` / `major-change` / `minor-change` / `write-slice` — under
  `.claude/commands/` or `.claude/skills/`, at **every** `.claude` found in step 1, not just the
  root;
- the nine dev agents — `code-writer`, `code-reviewer`, `doc-writer`, `plan-writer`,
  `plan-reviewer`, `test-agent`, `test-fixer`, `rebase-agent`, `arch-design` — plus the retired
  `plan-briefer`, `plan-scribe`, `slice-grounder`, `slice-verifier` and an older `code-tester`,
  likewise at every `.claude`;
- the pipeline scripts and their session machinery — `run_loop.py`, `plan_loop.py`,
  `sweep_slice.py`, `close_slice.py`, `slice_cost.py`, `preflight.py`, `allocate-next-slice.sh`
  and their tests (commonly under `tools/ai_workflow/`), plus the retired `task_runner.py`,
  `grounding_check.py`, `grounding_dispatch.py`, `claude_session.py`, `codex_exec.py`, and any
  `scripts/preflight.py` the plugin's preflight replaces;
- **the in-repo contract docs** — `run-loop.md`, `runner-state.md`, `plan-loop.md`,
  `plan-template.md`, `agent-dispatch.md`, `project-contract.md`, `preflight.md`,
  `residual-sweep.md`, and the retired `task-workflow.md`, `task-runner.md`,
  `grounding-ledger.md` (commonly under `docs/conventions/`). The plugin owns those contracts now
  (`${CLAUDE_PLUGIN_ROOT}/docs/`); a project copy is a second source of truth that will drift and
  be believed.

**What a project keeps owning** are the two docs the contract lines *point at* — its slice testing
strategy and its slice doc plan. Those describe this project's deploy verification and its
documentation set; the plugin resolves them through `CLAUDE.md` and never ships them.

Leave everything else, and **say what you left**. A repo's own agents and commands are its own —
including auxiliary workflow ones `dev` does not replace (`update-docs` is the project's own;
deleting it removes capability nothing restores), and project tooling that merely shares the
folder (a build tracker, a codegen script).

**Leaving a file means leaving it working.** What you kept may reference what you just deleted —
`update-docs` and the quality commands all hand off to `/triage`, which is now `/dev:triage`.
Rewrite those references to their `/dev:` names, and report what you rewrote:

```bash
grep -rn '/triage\|/plan-slice\|/run-slice\|/slice-dag\|/arch-design' \
  <each .claude found in step 1>
```

Commit this as its own change, so the deletion is reviewable apart from the additions.

### 2b. Sweep out the quality capability

Separate from the above, because these are **not** being left: `quality-improver`,
`quality-issue-finder`, `refactor-audit`, and the `tools/code_health/` grader they feed on are
retired pending a rebuild of the tool. They must not stay in the project — a private fork of a tool
that is about to be replaced is exactly what is being cleaned up.

They are not yours to delete outright, though: the copies in each project have **drifted apart**,
and that divergence is the most useful input the rebuild has. So tell the operator to archive
before you remove:

1. List what this repo has — the commands (at every `.claude` from step 1) and `tools/code_health/`.
2. Ask the operator to copy them into the AIWorkflow repo under
   `archive/quality/<this-repo-name>/` (its README explains the layout), and to commit them there.
3. Only once they confirm the archive is committed, delete them here — and say what you deleted.

Do not archive them yourself: it is a different repo, and whether that repo is even checked out is
the operator's business, not an assumption you get to make.

`update-docs` is **not** part of this. It is not quality, touches no `code_health`, and nothing
blocks it — it stays (with its references rewritten, above).

### 3. The manifest and its curated automation

`.kubecoder/project.yaml` is contract item 1 and the pipeline's only source of the component set.
A repo may already have one for its envs while declaring no automation — which is the part that
matters here, because **the manifest's `test:` statements are the gate**: `/dev:run-slice`'s run loop
executes `kc project test --project <name>` itself and merges nothing that comes back red.

Work through it with the operator, per component:

- **`test:`** — what proves this component works? This is a decision, not a discovery. A component
  that declares no test statements is **green by definition**, and for a docs-only or config-only
  component that is the right answer, not a gap. Say so plainly rather than inventing a gate.
- **`build:`** — preflight's run profile runs `kc project build` repo-wide as the baseline gate, so
  a component whose build is red blocks every slice. Confirm it is green now.
- **`lint:`** — the `code-writer` runs the project's lint before handing back.

Verify rather than assume — a manifest that parses but does not run is worse than none:

```bash
kc project list --output=json      # names + cwds resolve
kc project build                   # the baseline preflight will demand
kc project test --project <name>   # per component: does it do what the operator just described?
```

### 4. The contract lines and the `CLAUDE.md` diet

Add the four lines to the **root** `CLAUDE.md`; preflight reads them by exact label prefix and
bails without them. `${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md` is authoritative on their
meaning; do not restate it here or in the repo.

```
Spec repo: <path>
Slice testing strategy: <path-to-doc>
Slice doc plan: <path-to-doc>
Design philosophy: <path-to-doc>
```

Three of those point at **project-owned docs that must exist** — preflight checks the files, and
agents read them:

- **Slice testing strategy** — how a *slice* is proven once its phases are merged: what gets
  deployed, which live checks run, where the operator gate sits, how findings resolve. The run
  loop's test phase is "read this doc and execute it"; nothing names the doc. If the repo has no
  such procedure, this is the moment to write one with the operator; if it has no meaningful
  deploy-verification at all, say that in the doc rather than leaving the line dangling.
- **Slice doc plan** — the same shape for documentation: which doc surfaces a shipped slice must
  bring up to date, and the rules for each. The doc phase is "read this doc and execute it". A
  repo whose docs are one README says exactly that; the phase then has little to do, which is a
  cheap answer rather than a missing one.
- **Design philosophy** — the change-discipline rules `code-writer` obeys (breaking changes,
  tombstones, defensive caveats, what "tested" means here).

While in `CLAUDE.md`, apply the diet in `project-contract.md` ("Keeping `CLAUDE.md` disciplined") —
one screen, every fact stated once, demote to a `docs/` topic doc rather than inline. Onboarding is
when it is cheapest to cut. Propose the trim; let the operator approve it.

### 5. The spec repo

Preflight only checks the path is a directory, but the pipeline needs a shape:

```
<spec-repo>/
  README.md                 # `## Pending` + `## Completed` lists — triage appends to the first,
                            #   close_slice.py moves the entry across; slice-dag reads it
  .gitignore                # slices/.next-slice, slices/.slice-alloc.lock (host-local, self-seeding)
  slices/
    backlog/                # triage writes NNN_slug/slice.md here; plan-slice promotes out of it
    NNN_slug/               # planned + in flight (slice.md, plan.md, verification.json,
                            #   state.json, log.txt)
    completed/  deferred/  cancelled/  archive/
```

Slice numbers come from `${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>`, which the
plugin ships and `/dev:triage` calls. A spec repo carries **no copy** — if you find one
(`<spec-repo>/scripts/allocate-next-slice.sh`), delete it once triage resolves to the plugin's, and
keep the `.gitignore` entries.

**No spec repo named?** Stop and ask the operator — its location and whether it is a fresh repo or
an existing one is theirs to decide, not yours to guess. Then `git init` it, scaffold the tree, and
add the `Spec repo:` line.

**A spec repo that predates the current format?** The bar is **shape, not contents** — a tree the
pipeline can navigate, nothing more.

**Do not rewrite slice bodies.** An old-format slice is not a defect to fix here: `/dev:plan-slice`
reads one and deals with it, with some effort, at the point it plans it (the loop's preflight
accepts `overview.md` beside `slice.md`, and `/dev:slice-dag` expects to meet both). Reworking a
slice you are not planning is speculative effort on something that may never be planned, spent
without the context the planner will have. Leave them.

In scope:

- **The tree.** `slices/` and its lifecycle folders exist, and each slice sits in the one that
  reflects its state — finished under `completed/`, abandoned under `cancelled/`. That is what makes
  the pending set legible to `/dev:slice-dag` and `/dev:plan-slice`; slice bodies are not.
- **Whole eras → `archive/`.** A layout the current pipeline will never read again — a bundle tree,
  a `major-change`/`minor-change`-era folder — moves wholesale. Archive it; do not modernize what is
  done.
- **The repo's own scaffolding.** The `.gitignore` entries, the README's `## Pending` and
  `## Completed` lists, and dropping a per-repo `scripts/allocate-next-slice.sh` now the plugin
  ships one.
- **Numbering.** The allocator floors above the highest `NNN_` anywhere under `slices/`, so
  archiving never recycles a number. Never renumber — the numbers are referenced from cards,
  commits, and docs.

Where a slice's *disposition* is genuinely unclear — is this backlog still wanted? — list them and
ask. That is the operator's call, and it is about state, not format.

Commit spec-repo changes as you go, staged **by name**: it is a shared working tree and parallel
sessions live in it.

### 6. Issue-tracker wiring

The skills reference the tracker generically; the host `~/.claude/CLAUDE.md` holds the concrete
wiring. Per repo, only the identity is new: the owner tag is the **bare repo name from `origin`**
(not the folder name).

```bash
git remote get-url origin
```

Make sure that tag exists on whichever boards the host convention names, and that migrated
outstanding slices are represented — an in-flight slice with no card is invisible to the operator.
Reconciling a migrated backlog against the boards is a judgment call: propose what to create or
close, do not bulk-write cards.

### 7. Finish

```bash
${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run    # must exit 0
```

A green run profile means the contract holds, the tree is clean, and the baseline builds. Report to
the operator: what was deleted, what was left behind and why, which references you rewrote, what was
archived out to `archive/quality/`, the automation each component now declares (naming any that
declare no tests, as a decision they made), what the spec-repo reshaping moved, and anything still
open. Then hand off to `/dev:triage`.
