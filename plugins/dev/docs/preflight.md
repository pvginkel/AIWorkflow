# Preflight — the pipeline's gate, expressed over `kc`

`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run` is one repo-shipped,
**stdlib-only** script each pipeline skill runs as **step one**. The checks are `kc` primitives
plus the repo's `.aiworkflowrc` contract from [`project-contract.md`](project-contract.md) — and
three steps that act rather than check: removing the spec-tree guard an older plugin installed in
the spec repo (§ Notes on the spec-tree guard), the sync that brings the environment's repos up
to their origins (§ Notes on the sync), and the `kc project setup` the run baseline runs before
its build (§ Notes on the run baseline).

**Silent on success** — but for one line, on a pass, when the session's plugin copy is stale
(§ Notes on the plugin check), under `plan` a `warning:` line for each repo the sync passed
over (§ Notes on the sync), and under `run` a `warning:` line when the baseline's setup went red
or timed out and its build was green (§ Notes on the run baseline). On failure it prints **one** actionable message — what is missing,
the exact line/fix, and a pointer to `project-contract.md` — so a new repo self-onboards from the
error text. Each skill relays that message verbatim on a non-zero exit and stops; the run loop
does **not** re-run preflight, so `/dev:run-slice` is the gate.

## Exit codes

| Code | Meaning | Who fixes it |
|:---:|---|---|
| `0` | pass (silent) | — |
| `1` | contract violation | the project (add a line, author the manifest, clean the tree, resolve a refused pull, fix the build) |
| `2` | environment broken | the environment (`kc` not on PATH, the control plane down, not in a git repo, a fetch that fails, a spec repo git dir the pod cannot write) |

## Profiles

| Check | triage | plan | run |
|---|:-:|:-:|:-:|
| `kc` on PATH | ✓ | ✓ | ✓ |
| Control plane healthy: `kc status` (worker daemon + controller) | – | ✓ | ✓ |
| Manifest valid: `kc project list --output=json` returns ≥1 component | – | ✓ | ✓ |
| `.aiworkflowrc` present, parses, names no unknown key | ✓ | ✓ | ✓ |
| `spec_repo` set, path exists (directory) | ✓ | ✓ | ✓ |
| The spec-tree guard removed: a pre-commit hook an older plugin installed in the spec repo | ✓ | ✓ | ✓ |
| `design_philosophy` set, target doc exists | – | – | ✓ |
| `test_phase.strategy` set + exists — only when the phase runs | – | – | ✓ |
| `doc_phase.plan` set + exists — only when the phase runs | – | – | ✓ |
| `devlock.lease` resolvable — only when one is named | – | – | ✓ |
| Declared Target repos cloned: no pending phase of the `--slice` plan targets a repo path `.kubecoder/config.yaml` declares and the pod has not cloned — only with `--slice` | – | ✓ | ✓ |
| Clean working tree | – | – | ✓ |
| Synced with origin: fetch, then fast-forward or rebase the checked-out branch — the target repo, every checkout beside it, the spec repo; under `plan` only the target repo, the spec repo and the `--slice` plan's Target repos block | – | ✓ | ✓ |
| Baseline: `kc project setup`, then `kc project build` (all components) | – | – | ✓ |
| The session's plugin is the installed one — else a line naming the installed loop, still a pass | – | ✓ | ✓ |

Checks run in that order (cheapest first, the baseline build last). `kc` is checked before anything
that shells out to it, and the two environment checks run before the repo is resolved — neither
needs it. The repo root and `.aiworkflowrc` are resolved from `git rev-parse --show-toplevel` at the
invocation cwd — so run the command from the target code repo.

A phase the project switched off is checked for nothing: its procedure doc is absent by contract
(the config refuses a phase that is off *and* names one), and gating on it would make an optional
phase mandatory again. See [`project-contract.md`](project-contract.md) for the schema.

## Notes on the control-plane check

- **`kc status` is an environment check (exit 2), not a contract violation.** It probes the worker
  daemon (one loopback `/healthz`) and the controller (the authenticated env self-read, which also
  proves the per-env token is accepted); it exits non-zero when either fails. A dead control plane
  means every `kc session` dispatch fails — nothing in the project is wrong, so the project is not
  the one asked to fix it.
- **Not in the triage profile.** Triage spawns no `kc` session and touches no `kc` surface; it
  is intake — its optional fact-checks are session-local sub-agents needing no control
  plane. Gating it on live controller reachability would fail work that needs none of it — the
  cost of the check there is a false gate, not the 20ms.
- Both probes are bounded by the CLI itself (5s daemon, 10s controller), so preflight adds no
  timeout of its own.

## Notes on the spec-tree guard

- **What it was.** Until 0.9.93 a phase targeting the spec repo checked its branch out in the
  shared tree, and `tools/spec-tree-guard.sh`, installed as the spec repo's pre-commit hook,
  refused everyone else's commit on it. A phase now works in a worktree of its own
  ([run-loop.md](run-loop.md) § The plan is the queue), and the hook would refuse that worktree's
  commits: hooks in the shared git dir run for every worktree.
- **The step.** At `git rev-parse --git-path hooks/pre-commit` in the spec repo (so a
  `core.hooksPath` is honoured), a hook carrying `# aiworkflow spec-tree guard` is deleted, in
  every profile, with one line saying so. Any other hook is left alone, and a spec repo that is no
  git repo is skipped. A git dir preflight cannot write is exit 2.
- **Why it stays.** The git dir is shared, and an environment still on an older plugin installs
  the hook again at its own preflight until it is updated.

## Notes on the Target clones

- **Why it exists.** A repo added to `.kubecoder/config.yaml` while the environment runs is cloned
  at the next pod start. Until then a phase targeting it as `../Repo` read as a wrong path:
  preflight passed, and the run loop nudged a session to fix a plan that was fine, then asked the
  operator (AIWF-73).
- **What it checks.** With `--slice`, every pending phase of the slice's `plan.md` whose `Target:`
  is a repo path (`../Repo` or absolute) with no checkout there. Only then is `kc env describe`
  asked: its repo list is config.yaml as it stands now, so it lists a repo the pod has not cloned.
  A declared one is exit 2, one line per phase, naming the fix: `kc env restart`, or a clone at
  the declared path plus `kc project setup` there. `/dev:plan-slice` and `/dev:run-slice` pass the
  slice; without `--slice` there is no plan to read, and the check passes.
- **What it leaves alone.** A missing Target config.yaml does not declare is the plan's to fix,
  and `kc env describe` not answering is no evidence: both pass, and the loop reports a Target
  that does not resolve, as before. A `github:` Target's scratch clone is the run loop's to make,
  and a component name is not looked up. A run that meets the same Target stops with
  `target_not_cloned` ([run-loop.md](run-loop.md) § The plan is the queue).

## Notes on the sync

- **A step that acts.** The checks refuse and report; this one pulls. What decides
  is what a step could destroy: cleaning a dirty tree throws away the operator's work, so the
  clean-tree check refuses; fast-forwarding a clean checkout onto its origin throws away nothing
  (the reflog keeps the old tip), so the sync does it. It replaces the pull-every-repo the operator
  otherwise ran by hand before each plan and run.
- **Which repos.** The target repo, then every git checkout beside it — in a KubeCoder pod that is
  the environment's repo set under `/work/`, the layout `.aiworkflowrc`'s `spec_repo = "../…"`
  already assumes — then the spec repo if it lives elsewhere, then every clone under
  `/work/scratch/` that the run loop made or adopted for a `github:` Target (it marks them;
  a hand clone there is not the environment's and is left alone).
- **Which repos block, under `plan`.** The target repo, the spec repo, and every repo a Target
  of the slice's `plan.md` names — `/dev:plan-slice` passes the slice as `--slice <N|path>`, and
  without a `plan.md` yet that is the first two. A `../Repo` Target is that sibling, a `github:`
  Target its scratch clone, a component the target repo (a component living in a sibling is not
  looked up). Every other repo is still synced, but a refusal there — any of the ones below — is
  one `warning:` line on exit 0, and the sync goes on: planning does not read or write it, and a
  stranger's repo (an unrebasable local commit, another process's pull, a live run's branch) is
  not the planner's to settle. The run profile refuses it until it is resolved. Two more cases
  are skipped under `plan` in any repo: one whose directory vanished mid-sync (silently — a
  transient clone under `/work`), and one whose GitHub origin answers `Repository not found`
  (one `warning:` line; the repo was deleted or moved, and for a marked scratch clone the line
  names the `git config --unset aiworkflow.scratchClone` that unmarks it). Under `run` both stay
  the failed fetch they are.
- **Which branch.** The checked-out one, against its upstream, because that *is* the base: the run
  loop records as a repo's base whatever branch is checked out the first time it touches that repo
  ([`run-loop.md`](run-loop.md)). Detached HEAD → skipped. A run loop's `phase/<slice>-…` branch
  → refused (exit 1) first, upstream or not, in any repo of the set. It is usually a live run's,
  often another environment's: pushing it, tracking it or checking something else out would
  change that run's branch under it. So preflight never gives that advice for one. It looks the
  slice up in the spec repo (`slices/`, then `backlog/`, then `completed/`) and probes its
  `run.lock` without taking it. A held lock names the run by its holder note, and the message
  says to wait for the phase to merge, since the run checks the base back out itself. A free lock says a bail left the
  branch: commit any work on it, check the base back out, and retry. The clean-tree check refuses
  a phase branch the same way before it looks at the tree, because "commit or stash" must not
  reach a live run's writer. Any other branch with no upstream → refused (exit 1), naming the repo
  and the branch: a checkout preflight cannot fetch for would otherwise report green having
  synced nothing, and reach the run with its push checked against no tracking ref.
- **The rules.** Fetch the upstream's remote — up to three attempts when git reports `incorrect
  old value provided`, the ref-update race two sessions fetching one clone lose, not a network or
  credential fault; any other fetch failure is not retried. Not behind → nothing; ahead-only is left alone
  (unpushed commits are the operator's, and the run pushes at its test phase). Behind and clean →
  fast-forward, or rebase when local commits sit on top — a rebase that conflicts is aborted and
  reported. Behind and dirty → refused: preflight never pulls over uncommitted changes, in any repo,
  the shared spec repo included. Before it refuses, it looks once more after two seconds, because
  another process's pull leaves a tree dirty for a moment: clean at the second look, the repo
  syncs on the second look's counts. Still dirty while git's `index.lock` was held at either look
  → refused with "wait for it to finish", never "commit or stash", which would capture that
  process's half-applied checkout. An untracked `run.lock` is not a change: a live run holds
  one in the spec repo, a clean exit leaves the emptied file until `close_slice.py` deletes it
  at close-out, and no pull writes it — so the dirty test passes it over, in both profiles. Any
  other untracked file, a tracked `run.lock` modified, or `plan.lock` still counts (AIWF-76).
- **Exit codes.** A fetch that fails is environment (exit 2). A refused dirty tree, a branch with no
  upstream or a rebase that does not apply is the operator's to resolve by hand (exit 1) — the
  relaying session does not resolve it either. A repo on a phase branch is exit 1 too, but a
  live run's branch is waited out, not resolved.
- **Mid-run, the loop only fast-forwards.** Its own fetches are refs-only, save that a fresh
  phase's base with no commits of its own is fast-forwarded to its origin before the branch is
  cut ([`run-loop.md`](run-loop.md) § Fetch); the pull that rebases local commits onto origin is
  the operator's call, made once here.

## Notes on the run baseline

- The baseline gates on **`kc project build` only, always on** (no skip flag). A baseline-broken suite
  screams on the first phase's gate run anyway, and a project that cares can put a cheap collect
  step in its manifest's `build` list. A manifest with no `build` statement passes: kc exits 3
  (nothing ran), and there is no baseline to break. Full `kc project test` is **not** a preflight
  step — it is the per-phase gate the run loop owns.
- **`kc project setup` runs first**, bare, from the repo root, capped at the run loop's 900 s
  setup timeout. Otherwise an install that is behind its lockfile reads as a red baseline. In
  PilotApp (2026-10-18), a template sync had added `pg` to `package.json` and the lockfile while
  `node_modules` was older. The frontend type-check failed with `TS2307 Cannot find module 'pg'`,
  and `kc project setup` made it green. Setup takes seconds on an install that is already current:
  0–8 s across the run loop's run-start setups. The build decides, as it does after the run
  loop's own setup ([run-loop.md](run-loop.md) § Protocol invariants, *The loop sets up its
  Target repos*). A repo that defines no setup (exit 3) passes. A red or timed-out setup with a
  green build passes, with a `warning:` line. A red build's failure message carries setup's
  outcome and its last lines, so it shows whether install state is the cause.

## Notes on the plugin check

- **Why it exists.** A session keeps the plugin copy it started with, while the loop it launches
  bails `plugin_version` at once unless it runs the installed version
  ([run-loop.md](run-loop.md) § Protocol invariants). So a marketplace update after the session
  started made the first launch from `${CLAUDE_PLUGIN_ROOT}` a wasted one, and preflight, run
  from the same stale copy, had passed green (AIWF-33).
- **What it prints.** When the two versions differ, preflight exits 0 and prints, after every
  other check has passed, one line naming the installed copy of the profile's loop —
  `plan_loop.py` for `--for plan`, `run_loop.py` for `--for run`. The session launches that path
  instead of `${CLAUDE_PLUGIN_ROOT}`'s, for every launch and relaunch it makes. A pass, not a
  failure: a non-zero exit stops the skill and costs the round-trip the line saves.
- **Fail open, like the loop.** An unreadable manifest, or no entry in
  `~/.claude/plugins/installed_plugins.json`, is no evidence of a mismatch: nothing is printed.
- **It helps from the copy that carries it.** A session whose own copy predates the check gets
  no line, and the loop's bail names the path as before.
