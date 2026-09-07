---
name: onboard
description: Make a repo usable by the dev pipeline — retire any in-repo copy of the pre-plugin workflow, settle the manifest's curated automation, write the .aiworkflowrc contract, and scaffold or migrate the spec repo. Finishes when preflight --for run is green.
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
second, and visit every decision point below.

**The pre-ruled headless run is a supported shape.** Much of what follows stops and asks; a
dispatching prompt that has already answered those questions does not turn them into traps. Where
the prompt has ruled, apply the ruling and record it as an assumption; where it has not, apply the
default this skill states, and record that too; reserve stopping for what would be unsafe to guess.
The decision points are still *visited* — a ruling can be stale, or name a file that no longer
exists — but a visit that agrees with the ruling is silent, and only a disagreement becomes a
question. Report the assumptions and whatever the prompt genuinely did not cover, together, at the
end.

**A ruling is about a class, not the list that illustrates it.** A prompt naming
`backend/.claude/agents/` in a repo whose frontend holds byte-identical copies has ruled on both:
apply it to every member step 1's inventory found, and report the extension. Deleting only what was
listed leaves exactly the shadowing the step exists to remove — the list was written from memory,
the inventory was not.

## Procedure

### 1. Inventory — report before you touch anything

Establish what is already true. Do not fix anything yet; a repo part-way onto the workflow is the
normal case, and the gap list drives the rest.

```bash
git fetch origin && git log --oneline HEAD..@{u}    # what the remote knows and your checkout does not
git rev-parse --abbrev-ref @{u}                     # fails = no upstream, and preflight will not say so
git status --porcelain                              # the operator's untracked files, before step 4 lands beside them
kc project list --output=json                       # components + effective cwds (empty/error = no usable manifest)
cat .kubecoder/project.yaml 2>/dev/null             # the manifest, if any
cat .aiworkflowrc 2>/dev/null                       # the project's own contract, if any
find . -name .claude -type d -not -path './.git/*'  # recursive: older layouts put agents per-subproject
${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run  # the gap list, in its own words
```

**Inventory at the tip, not at your checkout.** Onboarding writes durable prose about this repo's
gates, and another session may have changed one yesterday: a run that inventoried behind its remote
wrote three documents asserting a gate that a pushed commit had already reversed, and `git push`'s
auto-rebase carried the false prose onto `main`. Read `HEAD..@{u}` before writing any of it — and
after any rebase, re-verify every gate in the tree you will actually commit. A gate's colour is a
property of a tree, not of a run.

**No upstream is not "in sync".** Preflight's sync `continue`s past a branch with no tracking ref
and reports green having synced nothing, which is indistinguishable from success; a repo that
reaches `/dev:run-slice` that way never syncs and checks its push against no tracking ref.
`git branch --set-upstream-to=origin/main main` is the whole fix — git config, host-local, nothing
to commit.

**Untracked files are the operator's, and preflight's clean-tree check meets them at the end.**
Drafts sitting in exactly the `docs/` directory step 4 fills turn into a bad choice under time
pressure — commit someone else's work, or exclude it. Find them now and ask in the same breath as
everything else.

**A state note at the repo root is not yours to overwrite.** `/kubecoder:onboard` writes
`ONBOARDING-STATE.md` there, and on a full-tier repo this run is usually asked for one under the
same name. Read what you find — a diagnosed test race, a lint breakdown, an unanswered question
list is precisely the input step 4's testing-strategy doc needs — move it aside under a distinct
name (`ONBOARDING-STATE.kubecoder-env.md`), and carry its open items forward rather than dropping
them. Add both to `.git/info/exclude` **before** the first preflight run: its clean-tree check
counts untracked files, so the note fails the very check it documents, and `.gitignore` is the
wrong file because that one is committed.

Preflight fails on the **first** violation, so re-run it as you go — it is a worklist, not a report.
Summarize for the operator: which contract pieces exist, what the components are, whether a spec
repo is named and what state it is in, and what pre-plugin workflow remains. Then work down.

### 2. Retire the in-repo copy of the old workflow

A repo that ran the pre-plugin workflow carries its own skills, agents, and driver. They now shadow
the plugin: a stale in-repo `code-writer` or `run-loop.md` outranks nothing, it just gets read
instead. Delete **only** what `dev` supersedes.

**The test that settles a file is "can you name the replacement?"** — the lists below are how it
usually resolves, not the rule itself. `plan_feature.md` → `/dev:plan-slice`; `code_review.md` →
the `dev:code-reviewer` agent; a `create_brief.md` → nothing the plugin ships, so it stays. That
test reaches what a list of `.claude` names cannot: a repo may keep its whole pre-plugin workflow
as ordinary docs — `docs/workflow.md` and `docs/commands/*.md`, imported into `CLAUDE.md` with `@`
— and never have had a `.claude` tree at all.

So find the workflow before matching it against a list:

```bash
grep -rl 'code-writer\|plan-writer\|code-reviewer\|plan-reviewer' --exclude-dir=.git .
grep -rn '@docs/\|@\.claude/' CLAUDE.md */CLAUDE.md AGENTS.md */AGENTS.md 2>/dev/null
```

The **agent filenames are stable across every era** of this workflow, so they hit where the
slash-command vocabulary does not — that vocabulary is the slice era's, and it returns zero hits in
a repo whose commands were `@`-referenced templates and whose driver was prose. Then take the
second hop: grep for whatever the files you just found *read*. That is what maps the real reference
graph.

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

**What a project keeps owning** are the two docs the config *points at* — its slice testing
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
grep -rn 'ai_workflow\|docs/commands/\|scripts/preflight' --exclude-dir=.git .
```

Sweep the **paths** of what you deleted as well as the command names: a retired command's doc
templates were reached from somewhere, and that somewhere is often a file you kept.

**Do not repoint a reference when the new name would be false.** A `scripts/build-all.py` whose
docstring says "the `/run-slice` pre-flight invokes this script" is not repaired by writing
`/dev:run-slice` into it — the plugin's run loop does not call it. Delete the sentence, or leave
the file and report it; a rewrite that reads plausibly and is untrue costs the next session more
than the stale one did.

**After deleting docs, ask what builds them.** A `docs/` tree can be a published site — a static
build CI ships as an image, failing on a dead link — that `kc project build` never runs and
preflight never sees. Run that build after the deletions, fix the links it names, and gitignore
whatever `dist/` it emits, or it fails the clean-tree check much later and much more confusingly.

Commit this as its own change, so the deletion is reviewable apart from the additions — and stage
by path. **`git commit -- <paths>`, every commit in this skill:** `git rm` stages immediately, so a
bare `git commit -m` here swallows whatever else is already written in the tree.

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

**Two modes, and `kc project list` says which.** Where it already resolves against a current
manifest, this step is *verify*: run the gates, and report a red one as a finding rather than
taking it on here. Where it does not, the automation is being decided now — work through it with
the operator, per component:

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

### 4. `.aiworkflowrc` and the `CLAUDE.md` diet

Write the repo's own contract to `.aiworkflowrc` at the **root**; preflight bails without it, and
prints the whole schema when it is missing. `${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md` is
authoritative on what each key means; do not restate it here or in the repo.

```toml
spec_repo = "<path>"
design_philosophy = "<path-to-doc>"

[test_phase]
strategy = "<path-to-doc>"

[doc_phase]
plan = "<path-to-doc>"
```

Three of those point at **project-owned docs that must exist** — preflight checks the files, and
agents read them:

- **`test_phase.strategy`** — how a *slice* is proven once its phases are merged: what gets
  deployed, which live checks run, where the operator gate sits, how findings resolve. The run
  loop's test phase is "read this doc and execute it"; nothing names the doc. If the repo has no
  such procedure, this is the moment to write one with the operator.
- **`doc_phase.plan`** — the same shape for documentation: which doc surfaces a shipped slice must
  bring up to date, and the rules for each. The doc phase is "read this doc and execute it". A
  repo whose docs are one README says exactly that; the phase then has little to do, which is a
  cheap answer rather than a missing one.
- **`design_philosophy`** — the change-discipline rules `code-writer` obeys (breaking changes,
  tombstones, defensive caveats, what "tested" means here).

**Those three docs are the work; `.aiworkflowrc` is ten lines.** On a first-time onboarding they
run to a few hundred, and two things make them specific rather than generic: a **model** — the same
doc from a repo in the same situation, since one production deployment and no dev instance is a
different procedure from a repo with both — so find one and name it; and **executing the live check
before writing it down**.

- **Write the live check by running it, stop recipe included.** A test agent executes the doc
  verbatim, and the half written from imagination is always the stop. Killing the `cexec` client
  does not reach the process manager it started in the sidecar — the services stay up on their
  ports for the next phase to trip over — and a launcher that ignores SIGTERM by design needs the
  interrupt it does honour. Signal the manager itself, by a pid it wrote to a shared path: the pod
  is one PID namespace, so `pgrep -f` matches the `cexec … pgrep` client's own argv and hands back
  the wrong process. Booting once also corrects the expected responses — a `readyz` 503 a test
  agent would otherwise report as a failure.
- **Check the CI-following recipe is reachable from the pod before writing it.** One `curl` settles
  it: a Jenkins that answers `403` to the unauthenticated JSON API, in an environment holding no
  token, makes "poll the job's JSON API" an instruction that cannot be carried out. What works is
  the MCP tools, or — for a session without them — reporting the pushed commit and the build number
  it expects, and leaving the result to the operator.
- **`EXIT=$?` after a pipe is the pipe's status, not the gate's.** `kc project` verbs buffer their
  output and print it only on failure, so a recipe that pipes one and reads `$?` reports green
  forever. `${PIPESTATUS[0]}`, or do not pipe.
- **Name the known-red gates, and say plainly when there are none.** "No gate is known red, so a
  failure is this slice's" is the more useful sentence where everything is green — it stops a test
  agent hunting for a pre-existing card. Ask for the statement either way.

**Ask before switching a phase off.** `enabled = false` on either phase is the right answer for a
repo with nothing to deploy-verify or nothing to document — an Ansible tree, a config repo — and
the wrong answer for a repo that simply has not written the doc yet. The difference is the
operator's to state, so put the question to them rather than inferring it from an empty `docs/`.
Same for `[push] enabled` and `[devlock] lease`: ask what the repo deploys and whether anything
contends over it.

While in `CLAUDE.md`, apply the diet in `project-contract.md` ("Keeping `CLAUDE.md` disciplined") —
one screen, every fact stated once, demote to a `docs/` topic doc rather than inline. A repo
onboarded before `.aiworkflowrc` still carries the four `Spec repo:` / `Slice testing strategy:` /
`Slice doc plan:` / `Design philosophy:` lines: move them into the config and **delete them from
`CLAUDE.md`** — a fact in both files is a fact that will disagree with itself. Onboarding is when
the cut is cheapest. Propose the trim; let the operator approve it.

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

**A tree scaffolded from zero commits needs a placeholder in each empty folder.** Git carries no
empty directory, so without one the shape exists locally and vanishes on clone — silently, which is
the worst way to lose it. Every spec repo this fleet scaffolded from nothing wrote a `.gitkeep`
into `slices/backlog/` and the four lifecycle folders; take that as the pass's practice, record it
as an assumption, and leave it to the operator to settle as a rule. A spec repo whose folders are
already populated needs nothing.

Slice numbers come from `${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>`, which the
plugin ships and `/dev:triage` calls. A spec repo carries **no copy** — if you find one
(`<spec-repo>/scripts/allocate-next-slice.sh`), delete it once triage resolves to the plugin's, and
keep the `.gitignore` entries. Smoke-test the allocator against a fresh scaffold, then put the
reservation back: it persists what it hands out, so the test burns `001` and the project's first
real slice would come out `002`. `printf '001\n' > <spec-repo>/slices/.next-slice` — or delete the
file, which self-seeds from the highest `NNN_` on disk.

**No spec repo named?** Stop and ask the operator — its location and whether it is a fresh repo or
an existing one is theirs to decide, not yours to guess. Then `git init` it, scaffold the tree, and
set `spec_repo`.

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

**A failure here can belong to a repo this project does not own.** Preflight's sync covers every
checkout beside the target, including hand-clones no manifest lists, so one of them fails the whole
profile with an error naming the environment rather than the project. Check
`git remote get-url origin` on the repo it fell over before assuming a network fault — a stale
embedded credential is the usual cause — and redact it when you report.

A green run profile means the contract holds, the tree is clean, and the baseline builds. Report to
the operator: what was deleted, what was left behind and why, which references you rewrote, what was
archived out to `archive/quality/`, the automation each component now declares (naming any that
declare no tests, as a decision they made), what the spec-repo reshaping moved, and anything still
open. Then hand off to `/dev:triage`.
