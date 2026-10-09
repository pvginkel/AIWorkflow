# Preflight — the pipeline's gate, expressed over `kc`

`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run` is one repo-shipped,
**stdlib-only** script each pipeline skill runs as **step one**. The checks are `kc` primitives
plus the repo's `.aiworkflowrc` contract from [`project-contract.md`](project-contract.md) — and
two steps that act rather than check: installing the spec-tree guard in the spec repo
(§ Notes on the spec-tree guard), and the sync that brings the environment's repos up to their
origins (§ Notes on the sync).

**Silent on success** — but for one line, on a pass, when the session's plugin copy is stale
(§ Notes on the plugin check). On failure it prints **one** actionable message — what is missing,
the exact line/fix, and a pointer to `project-contract.md` — so a new repo self-onboards from the
error text. Each skill relays that message verbatim on a non-zero exit and stops; the run loop
does **not** re-run preflight, so `/dev:run-slice` is the gate.

## Exit codes

| Code | Meaning | Who fixes it |
|:---:|---|---|
| `0` | pass (silent) | — |
| `1` | contract violation | the project (add a line, author the manifest, clean the tree, resolve a refused pull, fix the build, move a foreign pre-commit hook out of the spec repo) |
| `2` | environment broken | the environment (`kc` not on PATH, the control plane down, not in a git repo, a fetch that fails, a spec repo git dir the pod cannot write) |

## Profiles

| Check | triage | plan | run |
|---|:-:|:-:|:-:|
| `kc` on PATH | ✓ | ✓ | ✓ |
| Control plane healthy: `kc status` (worker daemon + controller) | – | ✓ | ✓ |
| Manifest valid: `kc project list --output=json` returns ≥1 component | – | ✓ | ✓ |
| `.aiworkflowrc` present, parses, names no unknown key | ✓ | ✓ | ✓ |
| `spec_repo` set, path exists (directory) | ✓ | ✓ | ✓ |
| The spec-tree guard installed: the spec repo's pre-commit hook | ✓ | ✓ | ✓ |
| `design_philosophy` set, target doc exists | – | – | ✓ |
| `test_phase.strategy` set + exists — only when the phase runs | – | – | ✓ |
| `doc_phase.plan` set + exists — only when the phase runs | – | – | ✓ |
| `devlock.lease` resolvable — only when one is named | – | – | ✓ |
| Clean working tree | – | – | ✓ |
| Synced with origin: fetch, then fast-forward or rebase the checked-out branch — the target repo, every checkout beside it, the spec repo | – | ✓ | ✓ |
| Baseline: `kc project build` (all components) | – | – | ✓ |
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

- **What it is.** The spec repo's pre-commit hook, `tools/spec-tree-guard.sh`. It refuses a commit
  on a `phase/*` branch unless `DEV_PHASE_BRANCH` names that branch, so only the run that checked
  a phase branch out in the shared spec tree commits onto it. [run-loop.md](run-loop.md) § The plan
  is the queue says who sets the variable and what a refused session does.
- **Every profile, because every session commits there.** Triage files slice folders, plan-slice
  writes the plan, close-out records the rulings. The hook has to be in place before any of them
  meets a running phase's branch, and installing it destroys nothing, so preflight installs it
  rather than asking for it.
- **Where.** `git rev-parse --git-path hooks/pre-commit` in the spec repo, so a `core.hooksPath`
  is honoured. A spec repo that isn't a git repo has nothing to guard and is skipped, as the run
  loop's lease is a no-op there.
- **Which hook wins.** The hook carries `# aiworkflow spec-tree guard v<N>`, where N changes only
  when the hook's text does. No hook: installed. Ours and older: replaced. Ours and the same or
  newer: left alone, because the git dir is shared and environments run different plugin
  versions. A hook without the marker is someone else's: left alone, and preflight fails (exit 1)
  naming the file. The hook is written to a temporary file beside the target and renamed into
  place, so a commit never runs half a hook. A git dir preflight cannot write is exit 2.

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
- **Which branch.** The checked-out one, against its upstream, because that *is* the base: the run
  loop records as a repo's base whatever branch is checked out the first time it touches that repo
  ([`run-loop.md`](run-loop.md)). Detached HEAD → skipped. A run loop's `phase/<slice>-…` branch
  → refused (exit 1) first, upstream or not, in any repo of the set. It is usually a live run's,
  often another environment's: pushing it, tracking it or checking something else out would
  change that run's branch under it. So preflight never gives that advice for one. It looks the
  slice up in the spec repo (`slices/`, then `backlog/`, then `completed/`) and probes its
  `run.lock` without taking it. A held lock names the run by its holder note (the spec tree's
  lease holder as well, when the repo is the spec repo), and the message says to wait for the
  phase to merge, since the run checks the base back out itself. A free lock says a bail left the
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
  the shared spec repo included.
- **Exit codes.** A fetch that fails is environment (exit 2). A refused dirty tree, a branch with no
  upstream or a rebase that does not apply is the operator's to resolve by hand (exit 1) — the
  relaying session does not resolve it either. A repo on a phase branch is exit 1 too, but a
  live run's branch is waited out, not resolved.
- **Mid-run, the loop moves no local branch.** Its own fetches are refs-only
  ([`run-loop.md`](run-loop.md) § Fetch); the pull that brings a base up to its origin is the
  operator's call, made once here.

## Notes on the run baseline

- The baseline is **`kc project build` only, always on** (no skip flag). A baseline-broken suite
  screams on the first phase's gate run anyway, and a project that cares can put a cheap collect
  step in its manifest's `build` list. A manifest with no `build` statement passes: kc exits 3
  (nothing ran), and there is no baseline to break. Full `kc project test` is **not** a preflight
  step — it is the per-phase gate the run loop owns.

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
