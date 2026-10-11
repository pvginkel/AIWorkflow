# Shared repos: a phase works in a worktree — plan, 2026-10-11

*Status: proposal. The decisions the operator rules on are § 5; what is built follows § 6.*

## 1. The problem, and the decision

The spec repo is `shared: true` in `.kubecoder/config.yaml`: one clone, mounted into every
environment of the project (`kc env describe` prints it `(shared)`; KubeCoder's own manual
recommends the flag for "big read-only reference repositories … nothing you intend to edit from
two places at once"). A phase whose `Target:` is that repo checks `phase/NNN-P<id>` out *in that
shared tree*, so from its checkout to its stamp — hours — every other session's commit (a stamp,
a done-record, a close-out entry, a triage filing, the operator's own) lands on the phase's branch,
and every uncommitted edit anyone leaves there bails the phase at its merge.

Five releases coped with that in place — 0.9.20 (bases restored at a bail, the tree asserted on
its base), 0.9.36 (the lease), 0.9.44/0.9.45 (the reviewer's leftover entry committed before the
checkout back, preflight naming the live run), 0.9.86 (the pre-commit guard), 0.9.88
(`spec_commit.py`) — and the bails kept coming: AIWF-52, AIWF-69 and AIWF-70 were filed in the
last four days alone, each from a hand recovery in AnsibleSpecs.

**Decision.** A phase whose Target resolves to a repo kc marks `shared` works in a **linked
worktree** of that repo under `/work/scratch/`, on its phase branch; the shared checkout never
leaves its base, and nobody's commit or edit there can reach the phase. Everything that existed
only because the shared tree was branched in place is removed (§ 3). The rule is keyed on kc's
flag, not on `.aiworkflowrc`'s `spec_repo`: the spec repo is the one shared repo an onboarded
project has today, but what matters is the mount, not the role.

## 2. Design

### 2.1 Which repos

`kc env describe --output=json` carries `repos: [{url, dir, shared, ref}]`. The run loop reads it
once per process — `run_loop._env_described` already parses that output for `sections` — and
records the shared dirs in `state.json` (`shared_repos`), so a resume reads the same set. A
resolved target whose `git_root` is one of them is shared. Three cases need no worktree: a
`github:` scratch clone is per environment; an unshared sibling is unchanged; a **shared primary
repo** (the invoking repo) is refused at startup — the gate and the dev services belong to the
environment's own checkout, and no project has that layout.

### 2.2 The worktree

- **Path** `/work/scratch/worktrees/<RepoName>/<NNN>-P<id>`: per environment; on `/work`, so the
  cexec sidecars see it and a restart keeps it (a Reset wipes it, as it wipes the scratch clones
  — the manual's `behavior/persistence`); beside, not inside, `github_target`'s
  `/work/scratch/<Repo>` clones, which preflight's sync walks by their mark and so never mistakes a
  worktree for one.
- **Creation** `git -C <shared> worktree add --lock --reason "slice NNN P<id>: <env id>, <host>,
  pid <pid>" <path> -b <branch> <base>` for a fresh phase; `… <path> <branch>` for a resume whose
  branch exists. **The lock is load-bearing.** The registration lives in the *shared* git dir
  (`<shared>/.git/worktrees/<name>`), and every other environment sees its `gitdir` pointer as a
  missing path. `git worktree prune` — which `git gc` runs — deletes such a registration; locked,
  it is kept. Probed on git 2.51: a locked worktree whose path is moved away survives `prune -v` and
  `gc --prune=now`; unlocked, it is pruned at once.
- **Resume.** `phases.P<id>.worktree` records the path. Present and on the branch → reused — a
  reattached session needs the tree as it left it, and `_reset_tracked` there is a plain
  `reset --hard` (no scoping: nothing but the phase writes in it). Missing — a Reset, or a resume
  in another environment after a bail — → every registration of that branch is unlocked and
  pruned (`git worktree unlock <name>`, `git worktree prune`), then the worktree is re-added from
  the branch. The committed work is in the shared git dir; the uncommitted is lost, as a lost
  code-repo tree loses it today (AIWF-58's patch would catch it the same way).
- **The old hook.** Before any dispatch into a worktree the driver removes a hook carrying
  `# aiworkflow spec-tree guard` from the shared git dir. Hooks run for worktrees too, the
  variable the hook wants is gone, and an environment still on an older plugin re-installs the
  hook at every preflight (§ 6.4). Ten lines; it does nothing once every environment has moved.

### 2.3 The phase, in the worktree

`_run_phase` resolves the target as today and then substitutes the worktree as the target's
working root — `ResolvedTarget` gains `work_root` (= `git_root` for every unshared target), and
`gate_cwd` follows it — while `git_root` stays the shared repo for `bases`, `landed.root`, the
test phase's pushes and the doc phase's diffs. Everything that reads or changes a working tree
runs in the worktree: the dirty checks, the resume reset, the gate (`kc project test` from the
worktree's root where a manifest exists — kc's verbs are cwd-bound, which is how the scratch
clones are gated already; a `gate` ruling or AIWF-68's committed check otherwise), the rebase onto
a moved base, the reviewer's `where`. The executor's dispatch says: work in `<worktree>`, a
checkout of `<Repo>` on `<branch>`; the shared checkout `<Repo>` stays on `<base>`, and the
done-record goes to `<plan_path>` there — the same shape as every sibling target carries today.
`BOOKKEEPING_NOTE` goes: the run record is untracked and so not in the worktree at all.

**The slice tree in the worktree.** The worktree holds `slices/**` at the branch's state, so a
writer that greps for `plan.md` can find the wrong copy. The rule run-loop.md already states —
the slice tree is never a phase's deliverable — becomes one mechanical step: before the merge,
if the branch touched `slices/**`, the driver reverts those paths on the branch to the base's
state in one commit and logs the files. A done-record written there is thereby lost from the
plan, which the reviewer's out-of-scope read and the plan's own nudges already answer for.
Excluding `slices/` by sparse checkout was considered and dropped: cone mode cannot exclude a
directory, non-cone mode is the form git is moving away from.

### 2.4 The merge

In order, bounded at five attempts:

1. The worktree dirty → `protocol_failure`, as today; only the phase writes there now.
2. `slices/**` reverted on the branch (§ 2.3).
3. The base moved under the branch → `_rebase_onto_moved_base`, in the worktree — today's code,
   now the common path, since the shared base moves with every session's commit; a conflict →
   `blocked` with the rebase request, as today.
4. The gate re-run where the green no longer covers the head, as today.
5. `git -C <shared> merge --ff-only <branch>` in the shared tree, on its base:
   - *not possible to fast-forward* — the base moved again → back to 3;
   - *your local changes / untracked files would be overwritten by merge* — another writer's
     uncommitted edit in a file the phase changed. The driver **sweeps it**: `git add -A --
     <those paths>` and one commit on the base, `slice NNN: edits left uncommitted in <Repo>,
     swept at P<id>'s merge`, then back to 3. The rebase then either applies — a change on other
     lines of the same file — or conflicts, which is the one real overlap and bails `blocked` as
     a rebase conflict does. The operator's stance: a sweep is fine, the commits need not be
     pristine (D2);
   - `index.lock` held by a concurrent `git add` → a short retry, as preflight's fetch retry.
6. `git worktree remove <path>`, `git branch -D <branch>` (git refuses the delete while a
   worktree holds the branch, so in that order), the stamp.

### 2.5 Bail, stop, exit

A bail or a stop leaves the worktree and its branch for the resume, exactly as a code repo's
phase branch is left today, and the shared tree needs no restoring: `_restore_bases` keeps its
code-repo job and loses the spec-only steps (`_commit_slice_edits`,
`_untrack_committed_record`). Exit 0 leaves nothing: every phase removed its own worktree. An
abandoned slice leaves one under `/work/scratch/worktrees/`, which `git worktree list` shows and
`git worktree remove` clears — not worth a `run_loop.py` verb.

### 2.6 What stays, as a check

The spec repo on its base before the driver's own commit there (stamp, report) and before a
dispatch — one function per loop, no wait, no branch argument. From now on it fires only on a
hand checkout, or on a pre-worktree run during the transition (§ 6.4). Kept because it is five
lines and names the one state the loop cannot work in. Also kept, as generic rather than coping:
`_base_branch` refusing a `phase/` branch as a base; preflight refusing a phase branch in any repo
and naming the run from its `run.lock` (AIWF-13 — minus the lease holder note); `SliceLock`;
`_rebase_onto_moved_base`; *stage by name* (§ 3.2).

### 2.7 Doc phase, wrap-up, test phase

Unchanged in shape. The doc-writer and the wrap-up commit into a *touched* shared repo directly
on its base — `_wrap_up_repos` already leaves the spec repo out, and the doc phase only ever
branched the primary — and the test phase pushes it from the shared tree. The branches for the
layout "the primary repo is the spec repo" (`_wrap_up_spec_home`, the doc branch cut in the spec
tree, the wrap-up's `spec_branch`, the lease-less `spec_branch` assertion there) go with the
`spec_branch` plumbing: CLAUDE.md's ruling of 2026-10-09 (AIWF-50) says that layout serves no
project (D4).

## 3. The revert — inventory

### 3.1 Removed: it existed only because the shared tree was branched in place

| Release | What | Where |
|---|---|---|
| 0.9.36 | `SpecTreeLock` — lease, intent, holder note; `SPEC_TREE_POLL/MAX_WAIT`; `spec_tree_timeout`; the shared hold around every dispatch, nudge and driver commit in both loops; the exclusive hold from checkout to stamp; the release at bail/interrupt | `run_loop.py` 1792–1972, 3236, 3288–3325, 5455–5461, 5612, 8110–8118; `plan_loop.py` 97, 259, 361–385, 430, 492, 798, 949; `preflight.spec_tree_holder` 392–446; `runner-state.md` 132, 196–204; `run-loop.md` 91–105; `plan-loop.md` 44–50 |
| 0.9.86 | `spec-tree-guard.sh`; `PHASE_BRANCH_ENV`/`DEV_PHASE_BRANCH`; `_spawn_env`, `_own_spec_branch`, the `phase_branch=` argument of `git()`/`specs_git()`; `preflight.check_spec_tree_guard` and the `spec_tree_guard` entry of every profile → replaced by the hook's **removal** (§ 2.2, § 6.4) | `run_loop.py` 290, 3399–3432, 4335–4353; `preflight.py` 264–300, 645–675; `preflight.md` 6–7, 33, 66–84; `agent-dispatch.md` 33; `run-loop.md` 107–124; `README.md` 42; `CLAUDE.md` 87 |
| 0.9.36/0.9.44 | `spec_branch` through `_spawn`, `_spawn_once`, `_consult`, the review-funding consult, the wrap-up dispatch; `_assert_spec_on_base`'s `expected`/`phase_id` forms and its "this run's own branch" message | `run_loop.py` 3450–3496, 4467–4560, 4775–4802, 5508, 5819, 6014, 6728, 7351–7356, 7598–7603 |
| 0.9.44 | `_commit_slice_edits` (merge, bail, wrap-up settle); `_untrack_committed_record`; `_green_covers`' bookkeeping clause | `run_loop.py` 3541–3660, 5580, 5599, 3909–3912, 5614–5632, 7690 |
| pre-0.9.20 | `_bookkeeping_pathspec` and every scoped query on it — the dirty check, the resume reset, the rebase's deliverable diff, the doc diffs, the wrap-up discard; `BOOKKEEPING_NOTE`/`_bookkeeping_note` | `run_loop.py` 3497–3540, 5155–5163, 5656, 6894, 7725; `run-loop.md` 66–90 |
| 0.9.20 | `_restore_bases`' spec-only steps; the bail's "not with the spec repo on a phase branch" render condition (AIWF-70's symptom) | `run_loop.py` 3909–3912, 8325–8335 |
| 0.9.88 | `spec_commit.py`, `test_spec_commit.py`; `docs/spec-tree.md` § Another writer's edit; the snapshot steps in wrap-up, plan-writer, doc-writer, triage step 7, close-out `fold`; the wrap-up's `leave` on an overlap (D1) | `agents/wrap-up.md` 52–54, `plan-writer.md` 96–97, `doc-writer.md` 70; `skills/triage/SKILL.md` 303–309; `skills/close-out/SKILL.md` 110; `CLAUDE.md` 89 |
| 0.9.44/0.9.45 | the "primary repo is the spec repo" doc-branch and wrap-up branches: `_wrap_up_spec_home`, the spec-tree doc branch, the wrap-up's `spec_branch` (D4) | `run_loop.py` 7199–7210, 7240, 7267, 7298, 7351–7356, 7847, 7938 |

Tests: 35 named tests across `test_run_loop.py`, `test_plan_loop.py` and `test_preflight.py` cover
the lease, the guard, `spec_branch`, the bookkeeping scoping and the base restore's spec steps;
they go or are rewritten against § 2. New: shared detection from kc's JSON; worktree create /
reuse / re-add after a stale locked registration; `slices/**` reverted; the merge loop's three
retries (moved base, dirty collision swept, `index.lock`); hook removal; a shared primary refused.

### 3.2 Kept

- **Stage by name, never `git add -A`, in the shared tree** — `docs/spec-tree.md` shrinks to that
  one section plus one sentence: a commit that carries another writer's uncommitted hunk in a file
  you also commit is accepted, not a defect. The ~16 "stage by name" pointers at the page stay;
  the page remains the rule's one home (AUTHORING.md's "state every claim once").
- `_rebase_onto_moved_base`, `_base_branch`'s refusal, preflight's phase-branch refusal,
  `SliceLock`, the no-wait base assertion (§ 2.6).
- `residual-sweep.md` l. 54: `sweep_slice.py` still refuses a spec repo off `main`; the reason
  reworded (a hand checkout, not a parallel run's phase branch).

### 3.3 The premise, checked

"The work we did to detect multiple writers was only because of the phases targeting the shared
repos (if I'm not mistaken)." Mostly right, with one exception:

- The lease, the guard, the base assertions and restores, `_commit_slice_edits`, the record
  untracking: **yes** — each incident behind them was a phase holding the shared tree on its
  branch (#954 slice 223/224; AIWF-2/12 slices 022/231; AIWF-50 slices 050/053/054).
- `spec_commit.py` (AIWF-53): **no.** Its incident was a wrap-up's `slices/DAG.md` fix that would
  have carried *the operator's own* uncommitted lane ticks into its commit, with no phase
  involved; the plan-writer had deferred the same fix for that reason. The new stance ("no problem
  one agent sweeping up a change of a different agent") covers it, but the edit swept is yours —
  hence D1.
- *Stage by name* predates all of it and is about files, not hunks: a `git add -A` in the shared
  tree commits every other slice's in-flight folder. It stays.

## 4. The open cards

Read: every `project: AIWF State: New` card (there are none Accepted), plus a text search for
"spec tree" and "worktree" across projects.

**Superseded — close when the release ships, with a comment naming it:**

- **AIWF-69** (close AIWF-50's accepted gap: an edit outside `slices/` bails the phase; keep the
  lease at a bail). Nobody's edit in the shared tree can reach a worktree; there is no lease.
- **AIWF-70** (a bail renders `close-out.md` on main while the phase branch is unmerged, and the
  resume's checkout fails). The shared tree is never checked out by the run; the render on main
  is right, and the render condition goes.
- **AIWF-52** (`_stamp_done` writes before the lease is held). No lease; the stamp lands in a
  tree the run never moves.

**Stay, each touched by this change — a comment on the card:**

- **AIWF-58** (save a dead round's uncommitted work as a patch before `_reset_tracked`). Still
  wanted; the reset it hooks is the plain one in the worktree now, so the patch is `git diff HEAD`
  from `phases.P<id>.worktree`.
- **AIWF-61** (fast-forward a plain-ancestor local base before cutting the branch). For a shared
  repo the base is the tree everyone commits to, so it is usually *ahead* of origin; where it is
  behind and clean the fast-forward moves the shared working tree, and a dirty file it would
  touch has to make it skip, not bail.
- **AIWF-68** (a committed check a spec-repo phase's dispatch names as its gate). Unchanged in
  substance; the dispatch names the check from the worktree's root.
- **AIWF-47** (environment, host, pid and heartbeat in the state files). The worktree's lock
  reason carries the environment id, host and pid already (§ 2.2) — one more place the card's
  record is useful; the heartbeat is still its own.

**Closed cards whose build this replaces — a comment each:** AIWF-50 (the guard), AIWF-53
(`spec_commit.py`), AIWF-13 (the lease holder in preflight's message); AIWF-2/-12 (the stranded
tree) are moot by construction.

**Unrelated, read and left:** AIWF-46, -48, -49, -51 (its `git add -A` is the slice folder's at
close), -55, -57, -60, -62, -63, -64, -66, -67.

## 5. Decisions for the operator

- **D1 — revert `spec_commit.py` (AIWF-53) too?** It protected your own uncommitted DAG ticks
  from a wrap-up's commit; reverting means the ticks ride whichever commit next touches
  `slices/DAG.md`. *Recommended: yes* — your stance covers it, and `snap`/`commit` is a step every
  writer pays on every spec-tree edit for a case you no longer mind.
- **D2 — a dirty collision at the fast-forward: sweep, or bail?** *Recommended: sweep* (§ 2.4
  step 5): one commit on the base carrying the other writer's edit, then the rebase decides; a
  bail is what you have today.
- **D3 — `slices/**` on the phase branch: revert and log, or bail?** *Recommended: revert and
  log* (§ 2.3): a writer's misplaced done-record is a review finding, not a stopped run.
- **D4 — drop the "primary repo is the spec repo" branches with the plumbing?** *Recommended:
  yes*; CLAUDE.md's ruling says the layout serves no project, and the code only survives because
  `spec_branch` threads through it.
- **D5 — one release or two?** *Recommended: one* (0.9.93, § 6.3). A revert shipped without the
  worktree reopens #954/AIWF-50 for the days between; the worktree shipped without the revert
  leaves an installed hook refusing every worktree commit.

## 6. Build

### 6.1 Code — one Opus sub-agent, disjoint from the prose

`plugins/dev/tools/run_loop.py`, `plan_loop.py`, `preflight.py`, their suites; delete
`spec-tree-guard.sh`, `spec_commit.py`, `test_spec_commit.py`. In this order inside the agent's
brief: (a) `shared_repo_dirs()` beside `_env_described`, recorded in state; (b) `ResolvedTarget.
work_root`, the worktree helper (`_ensure_worktree`: create / reuse / unlock-prune-re-add; the hook
removal; the lock reason), `_run_phase` using it; (c) the merge loop of § 2.4 with the `slices/**`
revert; (d) the removals of § 3.1, `_restore_bases` and `_bail` simplified, both loops' base
assertion reduced to the no-argument form; (e) preflight: `check_spec_tree_guard` → a removal of
any marker hook, `spec_tree_holder` gone, `refuse_phase_branch` keeps the `run.lock` message;
(f) tests. Verify: `kc project test`, `kc project lint`, and
`python3 plugins/dev/tools/run_loop.py run <slice> --dry-run` against a spec-repo-target plan in
`/work/AIWorkflowSpecs`. Review its diff before committing.

### 6.2 Prose — the session's own model

- `run-loop.md` § The plan is the queue: the lease, guard and bookkeeping paragraphs (ll. 66–143)
  replaced by the worktree contract (§ 2.2–2.6, as contract text, without the rationale).
- `runner-state.md`: `spec_tree_timeout` row out; `protocol_failure` row reworded; `phases.P<id>.
  worktree` and `shared_repos` added; the lease paragraph (ll. 196–204) replaced by one on the
  worktree's lock.
- `plan-loop.md` ll. 42–50; `preflight.md` (ll. 6–7, 33, § Notes on the spec-tree guard → one
  note on the removal, ll. 105–106); `close-out.md` l. 332; `agent-dispatch.md` l. 33;
  `residual-sweep.md` l. 54; `spec-tree.md` to § 3.2's shape; `plan-template.md` unchanged (its
  spec-repo lines are about ids, not trees).
- Agents: the snapshot sentences in `wrap-up.md`, `plan-writer.md`, `doc-writer.md` back to the
  stage-by-name pointer. Skills: `triage` step 7, `close-out` steps 7/9, `run-slice`'s bail
  paragraph (ll. 152–160), `slice-dag` l. 97.
- `README.md` 42/95; `CLAUDE.md` tools and docs lists, plus one settled-rulings line: a shared
  repo is never branched in place — the lease, the guard and `spec_commit.py` were removed for
  the worktree (this plan). `docs/rationale/improvements.md`: one entry for the change, and a
  *superseded by* line on the 0.9.36 and 0.9.86 entries (the evidence trail stays).
- `CHANGELOG-workflow.md`: one newest-first entry with the upgrade note of § 6.4.

### 6.3 Version

`origin/main` is at 0.9.88 (61b8cbd); 0.9.89–0.9.92 sit unpushed here. The change is 0.9.93 —
re-checked against `origin/main` at commit time, per CLAUDE.md. One commit for the code and one
for the prose, or one for both: the operator's habit either way.

### 6.4 Rollout

Push; marketplace update in **every environment that shares a spec repo before any of them runs a
spec-repo phase** — the same rule 0.9.86 carried, for the mirror reason. During the transition an
older run loop still branches the shared tree in place and takes a lease the new one ignores: a
new loop's commit would land on that phase's branch, which the kept base assertion (§ 2.6) turns
into a `blocked` bail rather than a silent misplacement. The first preflight or run on the new
version removes the guard hook from each shared git dir; an older environment's preflight puts it
back until it is updated, and the run loop removes it again before each worktree dispatch. The
lease files (`dev-spec-tree.lock`, `.intent`, `.holder`) left in the git dirs are inert; delete
them by hand or leave them.

### 6.5 Cards

At the release: close AIWF-52, -69, -70 as superseded with a one-line comment; comment on
AIWF-58, -61, -68, -47 with § 4's notes; comment on AIWF-50 and AIWF-53 that the worktree
replaced their builds. Whether the build itself gets an AIWF card is the operator's: AIWorkflow is
not on the pipeline, so the route is theirs (as it was for 0.9.86 and 0.9.88).
