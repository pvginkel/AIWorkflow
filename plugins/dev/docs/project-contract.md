# The project contract — what a repo must provide to use the pipeline

The pipeline is generic and portable; each project describes **itself**. A repo becomes usable
by the pipeline when it provides the three things below. Nothing here is a template you copy — it is
a small set of facts the pipeline reads (via `kc` and one config file), all **enforced by
preflight** (`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py`; see [`preflight.md`](preflight.md)). A new
repo self-onboards from preflight's error text.

## 1. `.kubecoder/project.yaml` — the component manifest

Present and valid, so `kc project list --output=json` returns the repo's components (each with a
`name`, an effective `cwd`, and a description) in file order. This is the single source of the
**project set** and each component's working directory — the pipeline never hardcodes them and never
parses the YAML itself; only `kc` reads it. The manifest also declares the **curated automation**
(`kc project build|test|lint --project <name>`) the dev agents run for a deterministic green signal.

- **Absent or malformed** → preflight (plan/run) bails.
- A phase's `Target:` in `plan.md` must name one of these component names (or a sibling repo
  path — see [run-loop.md](run-loop.md)).

See `kc`'s own `project-manifest.md` for the manifest schema.

## 2. `.aiworkflowrc` — everything else the pipeline reads

TOML at the repo root. One file carries every fact about the project the pipeline needs: where its
slices live, which procedure docs its phases execute, which phases it runs at all. The schema of
record is [`project_config.py`](../tools/project_config.py); a repo that has none gets the whole
file printed back at it by preflight.

```toml
spec_repo = "../KestrelSpecs"
design_philosophy = "docs/conventions/change-discipline.md"

[test_phase]
strategy = "docs/operations/slice-test-plan.md"

[doc_phase]
plan = "docs/operations/slice-doc-plan.md"

[devlock]
lease = "scripts/.devlock.lock"

[push]
enabled = true
```

Paths are absolute or relative to the repo root, except `devlock.lease` — the one key whose subject
is the spec repo, because the lease is shared by every code repo contending for the same dev
instance. Unknown keys are refused rather than ignored: `enable = false` silently running the phase
the project meant to switch off is the failure this file exists to prevent.

- **`spec_repo`** — where slices and each run's `state.json`/`log.txt` live (the separate
  spec/planning repo). `triage` and `plan-slice` cannot allocate or plan a slice with nowhere to
  write it, so all three profiles require it and check the path is a directory.
- **`design_philosophy`** — the project's change-discipline / design-philosophy doc
  (delete-don't-tombstone, no defensive caveats, testability). Named in every `code-writer`,
  `code-reviewer`, `plan-writer` and `plan-reviewer` dispatch. Run profile checks the file
  exists.
- **`test_phase.strategy`** — the project-owned doc describing the slice-level deploy-verification
  procedure (what it pushes, what it checks, how findings route). The run loop's **test phase** is
  "read this doc and execute"; nothing else names the doc.
- **`doc_phase.plan`** — the project-owned doc describing the slice-level documentation pass (which
  existing doc surfaces a shipped slice brings up to date from its diff, the gates, how it lands).
  The run loop's **doc phase** is "read this doc and execute".

### The switches

**Defaults are the pipeline's full behaviour**, so a project that names only its pointers runs
every phase and nobody loses one by omission. Each switch is an opt-*out*:

- **`test_phase.enabled`** (default true) — a project with nothing to deploy-verify sets it false
  and names no `strategy`. A phase that is off and still names its procedure doc is refused: one of
  the two is wrong.
- **`doc_phase.enabled`** (default true) — likewise for the documentation pass.
- **`push.enabled`** (default true) — whether a run's work reaches `origin` at all. With a test
  phase, that phase's procedure doc pushes and the driver checks it happened; **with no test phase
  the driver pushes**, because nothing else does — `_run_phase` ff-merges into the base locally,
  primary repo and siblings alike. Set it false and the slice's commits stay in the pod, the doc
  branch lands against the local base, and no push check runs. This is the project's standing mode;
  a single slice holding a single repo is [`plan.md`'s `## Push holds`](run-loop.md) instead, which
  is reported as an outstanding action where this is not.
- **`devlock.lease`** — the flock inode for the cooperative occupancy lease over a single dev
  instance, held for the test phase and again for the doc landing's push — never for the doc
  phase's writing ([run-loop.md](run-loop.md)). This one defaults **off**: one dev instance is a
  fact about a deployed project, not about every repo, and a lease that is not named cannot be
  taken. Run profile checks the directory it would live in
  exists — a typo'd path takes a lock nothing else contends for, which looks exactly like
  coordination and is none.

A phase that is off is not checked for anything: preflight requires a procedure doc only for a
phase that runs, or an optional phase would be mandatory again.

## 3. Host conventions (`~/.claude/CLAUDE.md`)

The skills speak about the **issue tracker** and **notifications** in the workflow's own
vocabulary, never a concrete tool's: an **intake queue** of owner-tagged cards, the **operator's
action queue**, **deferred**/**rejected** dispositions, one **slice card** per slice advancing
**triaged → planned → in progress → done**, and the **Solution Known** mark
([residual-sweep.md](residual-sweep.md)). The concrete wiring — which tracker, which board, list
or label realises each of those roles and states, the owner-tag rule (the bare repo name), the
notification command — is environment-specific and lives in the host `~/.claude/CLAUDE.md`, which
already holds it. The workflow neither ships nor duplicates it.

## Keeping `CLAUDE.md` disciplined

Every dev session loads it, every turn, so its size is a running cost paid by every agent the
pipeline spawns:

- **State every fact once.** A rule that belongs in a `docs/` topic doc goes there, with a pointer —
  not inline *and* in the doc. Two copies drift, and agents reading different copies behave
  differently.
- **Two strikes, one screen.** Per Anthropic's guidance, `CLAUDE.md` grows only when the same issue
  has bitten twice, and never exceeds ~one screen (~80–100 lines). When it is full and something new
  must go in, something old moves out — usually demoted to a `docs/` topic doc (read on demand
  instead of every turn), not deleted.
- **Nothing the pipeline reads by machine lives here.** That is what `.aiworkflowrc` is for; a fact
  in both files is a fact that will disagree with itself.

Onboarding a repo is when the trim is cheapest to make.

## What a good root `CLAUDE.md` contains

A `CLAUDE.md` that serves the pipeline well describes the project so a fresh dev session lands
oriented — it is for the reader, human or agent, where `.aiworkflowrc` is for the driver. A rough
shape (prose, not a template):

- **One-paragraph overview** — what the project is and its high-level shape (the components map to
  `kc project list`).
- **Repo structure** — one line per component and where the spec repo lives; the commit-early rule
  for the spec repo (it is a separate git repo).
- **Design philosophy** — the non-negotiable cross-component rules (`.aiworkflowrc`'s
  `design_philosophy` points at the fuller doc; a short summary here is fine).
- Pointers to the per-component `docs/` a dev agent reads (code style, conventions), and to the
  project's decision index if it keeps one.

Each component may also carry its own `CLAUDE.md` and `docs/`; a phase's plan section points the
executor at what its Target's docs require (dispatches run at the repo root — see
[agent-dispatch.md](agent-dispatch.md)).
