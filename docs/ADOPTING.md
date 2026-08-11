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

Installed into `~/.claude`, the plugin's skills resolve as `/dev:triage`, `/dev:plan-slice`,
`/dev:run-slice`, `/dev:slice-dag`, `/dev:arch-design`, and its agents as
`dev:code-writer`, `dev:code-reviewer`, … . The run loop spawns those agents by their namespaced name
through `kc session create-headless --agent dev:<role>`, so the kc-spawned headless sessions must
see the same `~/.claude` install (they do — same home).

> **Iterating on the plugin itself?** `--plugin-dir` only reaches your own operator session, not the
> kc-spawned headless agents. Develop by adding this repo as a local marketplace, installing `dev`,
> and re-installing after edits.

## 2. Make a repo adoptable — the project contract

A repo becomes usable by the pipeline when it provides these. Preflight
(`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run`, which each skill runs as step
one) checks every item and, on failure, prints exactly what to add.

### 2a. `.kubecoder/project.yaml` — the component manifest

Declare the repo's components and their curated automation so `kc project list --output=json`
returns the project set + each component's effective cwd, and `kc project build|test|lint --project
<name>` runs the deterministic checks. This is the **only** source of the project map — the plugin
never hardcodes it. See `kc`'s `project-manifest.md` for the schema. Each plan phase opens with a
`Target:` line naming one of these components (or a sibling repo).

### 2b. Four `CLAUDE.md` lines (root of the target repo)

Add these machine-checkable lines (markdown decoration around them is tolerated; paths may be
absolute or relative to the repo root):

```
Spec repo: <path to the spec/planning repo>
Slice testing strategy: <path to the project's slice-test-plan doc>
Slice doc plan: <path to the project's slice-doc-plan doc>
Design philosophy: <path to the project's change-discipline doc>
```

- **`Spec repo:`** — where slices and each run's `state.json`/`log.txt` live (a separate
  git repo). Required by all three profiles.
- **`Slice testing strategy:`** — the project-owned deploy-verification procedure the run loop's
  test phase resolves to (it never names the doc). Required by `run`.
- **`Slice doc plan:`** — the project-owned doc procedure its doc phase resolves to, the same way.
  Required by `run`.
- **`Design philosophy:`** — the change-discipline doc `code-writer` reads. Required by `run`.

The rest of a good root `CLAUDE.md` (overview, repo structure, design summary, doc pointers) is
described in [`project-contract.md`](../plugins/dev/docs/project-contract.md#what-a-good-root-claudemd-contains).

### 2c. Host conventions (`~/.claude/CLAUDE.md`)

The skills reference the issue tracker and notifications **generically** ("file findings to the
issue tracker", "notify per the host convention", "the project's owner tag"). The concrete wiring —
kanban tool, board/list names, the owner-tag rule, the notify command — lives in the host
`~/.claude/CLAUDE.md`. Nothing to do per-repo if the host already has it.

### 2d. The spec repo

Slices live in the spec repo under `slices/` (backlog → active → `completed/`), which needs a
specific layout — `/dev:onboard` scaffolds a new spec repo and brings an old one's tree into shape,
so run it rather than building the tree by hand. Slice numbers come from the plugin's own flock-guarded allocator
(`${CLAUDE_PLUGIN_ROOT}/tools/allocate-next-slice.sh <spec-repo>`), which `/dev:triage` calls; the
spec repo carries no copy. Commit spec-repo artifacts early and often, staging **by name** (it is a
shared working tree).

## 2e. Onboard a repo

`/dev:onboard` does all of section 2 as a guided pass — it inventories what a repo already has,
retires any in-repo copy of the pre-plugin workflow, settles the manifest's curated automation, adds
the contract lines, and scaffolds or migrates the spec repo. It finishes when
`preflight.py --for run` exits 0.

## 3. Worked example

A repo `Kestrel` (components `api`, `worker`; spec repo `../KestrelSpecs`):

**`.kubecoder/project.yaml`** (sketch — see the schema for the real shape):

```yaml
projects:
  api:    { cwd: api,    build: [...], test: [...], lint: [...] }
  worker: { cwd: worker, build: [...], test: [...], lint: [...] }
```

**`Kestrel/CLAUDE.md`** (the four contract lines among the usual content):

```markdown
# Kestrel — build-log aggregator for distributed CI runs

Kestrel is a two-component service: an `api` and a `worker`.

Spec repo: ../KestrelSpecs
Slice testing strategy: docs/operations/slice-test-plan.md
Slice doc plan: docs/operations/slice-doc-plan.md
Design philosophy: docs/conventions/change-discipline.md

## Design philosophy
- Clean breaking changes — fix callers, don't add shims.
- No tombstones — delete replaced code.
- Testability is critical — a feature without a test is incomplete.
```

Then, from the `Kestrel` repo:

```
/dev:triage            # groups findings/cards into slice folders in ../KestrelSpecs/slices/backlog/
/dev:plan-slice 042    # settles the slice with you, then plans it as an ordered phase queue
/dev:run-slice 042     # launches the run loop; drives write→test→review→merge, then test + docs
```

If any contract piece is missing, the first skill's preflight tells you the exact line or file to
add — a new repo self-onboards from the error text.
