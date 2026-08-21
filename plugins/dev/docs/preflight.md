# Preflight — the pipeline's gate, expressed over `kc`

`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run` is one repo-shipped,
**stdlib-only** script each pipeline skill runs as **step one**. The checks are `kc` primitives
plus the four machine-checkable `CLAUDE.md` lines from
[`project-contract.md`](project-contract.md).

**Silent on success.** On failure it prints **one** actionable message — what is missing, the exact
line/fix, and a pointer to `project-contract.md` — so a new repo self-onboards from the error text.
Each skill relays that message verbatim on a non-zero exit and stops; the run loop does **not**
re-run preflight, so `/dev:run-slice` is the gate.

## Exit codes

| Code | Meaning | Who fixes it |
|:---:|---|---|
| `0` | pass (silent) | — |
| `1` | contract violation | the project (add a line, author the manifest, clean the tree, fix the build) |
| `2` | environment broken | the environment (`kc` not on PATH, the control plane down, not in a git repo) |

## Profiles

| Check | triage | plan | run |
|---|:-:|:-:|:-:|
| `kc` on PATH | ✓ | ✓ | ✓ |
| Control plane healthy: `kc status` (worker daemon + controller) | – | ✓ | ✓ |
| Manifest valid: `kc project list --output=json` returns ≥1 component | – | ✓ | ✓ |
| `.aiworkflowrc` present, parses, names no unknown key | ✓ | ✓ | ✓ |
| `spec_repo` set, path exists (directory) | ✓ | ✓ | ✓ |
| `design_philosophy` set, target doc exists | – | – | ✓ |
| `test_phase.strategy` set + exists — only when the phase runs | – | – | ✓ |
| `doc_phase.plan` set + exists — only when the phase runs | – | – | ✓ |
| `devlock.lease` resolvable — only when one is named | – | – | ✓ |
| Clean working tree | – | – | ✓ |
| Baseline: `kc project build` (all components) | – | – | ✓ |

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
  is intake — its optional category fact-checks are session-local sub-agents needing no control
  plane. Gating it on live controller reachability would fail work that needs none of it — the
  cost of the check there is a false gate, not the 20ms.
- Both probes are bounded by the CLI itself (5s daemon, 10s controller), so preflight adds no
  timeout of its own.

## Notes on the run baseline

- The baseline is **`kc project build` only, always on** (no skip flag). A baseline-broken suite
  screams on the first phase's gate run anyway, and a project that cares can put a cheap collect
  step in its manifest's `build` list. Full `kc project test` is **not** a preflight step — it is
  the per-phase gate the run loop owns.
