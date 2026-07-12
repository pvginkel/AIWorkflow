# Adopting the `dev` plugin

The workflow is no longer a template you copy and fill in — it is a plugin you install once, plus a
small **project contract** each repo provides so the generic plugin can describe *this* project.
This guide covers both. The authoritative, preflight-enforced contract is
[`plugins/dev/docs/project-contract.md`](../plugins/dev/docs/project-contract.md); this is the
how-to.

> **Environment.** `dev` is kc-native: it targets the KubeCoder environment and expects `kc` on
> PATH (always true inside a KubeCoder pod). There is no non-`kc` fallback.

## 1. Install the plugin

From any Claude Code session:

```
/plugin marketplace add /work/AIWorkflow      # or the repo's git URL
/plugin install dev@aiworkflow
```

Installed into `~/.claude`, the plugin's commands resolve as `/dev:triage`, `/dev:plan-slice`,
`/dev:run-slice`, `/dev:write-task`, `/dev:slice-dag`, `/dev:arch-design`, and its agents as
`dev:code-writer`, `dev:code-reviewer`, … . The runner spawns those agents by their namespaced name
through `kc session create-headless --agent dev:<role>`, so the kc-spawned headless sessions must
see the same `~/.claude` install (they do — same home).

> **Iterating on the plugin itself?** `--plugin-dir` only reaches your own operator session, not the
> kc-spawned headless agents. Develop by adding this repo as a local marketplace, installing `dev`,
> and re-installing after edits.

## 2. Make a repo adoptable — the project contract

A repo becomes usable by the pipeline when it provides these. Preflight
(`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run`, which each command runs as step
one) checks every item and, on failure, prints exactly what to add.

### 2a. `.kubecoder/project.yaml` — the component manifest

Declare the repo's components and their curated automation so `kc project list --output=json`
returns the project set + each component's effective cwd, and `kc project build|test|lint --project
<name>` runs the deterministic checks. This is the **only** source of the project map — the plugin
never hardcodes it. See `kc`'s `project-manifest.md` for the schema. A task's `project` field must
be one of these component names.

### 2b. Three `CLAUDE.md` lines (root of the target repo)

Add these machine-checkable lines (markdown decoration around them is tolerated; paths may be
absolute or relative to the repo root):

```
Spec repo: <path to the spec/planning repo>
Slice testing strategy: <path to the project's slice-test-plan doc>
Design philosophy: <path to the project's change-discipline doc>
```

- **`Spec repo:`** — where slices, tasks, and each run's `state.json`/`log.txt` live (a separate
  git repo). Required by all three profiles.
- **`Slice testing strategy:`** — the project-owned deploy-verification procedure `run-slice`
  resolves to (it never names the doc). Required by `run`.
- **`Design philosophy:`** — the change-discipline doc `code-writer` reads. Required by `run`.

The rest of a good root `CLAUDE.md` (overview, repo structure, design summary, doc pointers) is
described in [`project-contract.md`](../plugins/dev/docs/project-contract.md#what-a-good-root-claudemd-contains).

### 2c. Host conventions (`~/.claude/CLAUDE.md`)

The commands reference the issue tracker and notifications **generically** ("file findings to the
issue tracker", "notify per the host convention", "the project's owner tag"). The concrete wiring —
kanban tool, board/list names, the owner-tag rule, the notify command — lives in the host
`~/.claude/CLAUDE.md`. Nothing to do per-repo if the host already has it.

### 2d. The spec repo

Slices live in the spec repo under `slices/` (backlog → active → `completed/`). `/dev:triage`
allocates slice numbers with a concurrency-safe helper the spec repo owns — see
[`specs/scripts/allocate-next-slice.sh`](../specs/scripts/allocate-next-slice.sh) for a reference
implementation (flock-guarded counter; prints a zero-padded 3-digit number). Commit spec-repo
artifacts early and often, staging **by name** (it is a shared working tree).

## 3. Worked example

A repo `Kestrel` (components `api`, `worker`; spec repo `../KestrelSpecs`):

**`.kubecoder/project.yaml`** (sketch — see the schema for the real shape):

```yaml
projects:
  api:    { cwd: api,    build: [...], test: [...], lint: [...] }
  worker: { cwd: worker, build: [...], test: [...], lint: [...] }
```

**`Kestrel/CLAUDE.md`** (the three contract lines among the usual content):

```markdown
# Kestrel — build-log aggregator for distributed CI runs

Kestrel is a two-component service: an `api` and a `worker`.

Spec repo: ../KestrelSpecs
Slice testing strategy: docs/operations/slice-test-plan.md
Design philosophy: docs/conventions/change-discipline.md

## Design philosophy
- Clean breaking changes — fix callers, don't add shims.
- No tombstones — delete replaced code.
- Testability is critical — a feature without a test is incomplete.
```

Then, from the `Kestrel` repo:

```
/dev:triage            # groups findings/cards into slice folders in ../KestrelSpecs/slices/backlog/
/dev:plan-slice 042    # breaks a slice into ordered, component-local tasks
/dev:run-slice 042     # launches the runner; drives write→test→review→merge→verify
```

If any contract piece is missing, the first command's preflight tells you the exact line or file to
add — a new repo self-onboards from the error text.
