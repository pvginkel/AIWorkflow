# The project contract — what a repo must provide to use the pipeline

The pipeline is generic and portable; each project describes **itself**. A repo becomes usable
by the pipeline when it provides the six things below. Nothing here is a template you copy — it is
a small set of facts the pipeline reads (via `kc` and four `CLAUDE.md` lines), all **enforced by
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

## 2–5. Four `CLAUDE.md` entries (machine-checkable line prefixes)

A `CLAUDE.md` cannot be shipped with the workflow (it is project/user memory, discovered by
walking the repo tree). Instead the target repo's **root `CLAUDE.md`** carries four lines the
pipeline reads by exact label prefix (markdown decoration — list markers, `**bold**`, `` `backticks` ``
— is tolerated; the value may be an absolute path or one relative to the repo root):

```
Spec repo: <path>
Slice testing strategy: <path-to-doc>
Slice doc plan: <path-to-doc>
Design philosophy: <path-to-doc>
```

Each **bails, not warns** — it is one line to add:

- **`Spec repo:`** — where slices and each run's `state.json`/`log.txt` live (the separate
  spec/planning repo). `triage` and `plan-slice` cannot allocate or plan a slice with nowhere to
  write it, so all three profiles require it and check the path exists (a directory).
- **`Slice testing strategy:`** — points at the project-owned doc describing the slice-level
  deploy-verification procedure (what it pushes, what it checks, how findings route). The run
  loop's **test phase** is "read this doc and execute"; nothing else names the doc. Run profile
  checks the target file exists.
- **`Slice doc plan:`** — points at the project-owned doc describing the slice-level
  documentation pass (which doc surfaces, the gates, how it lands). The run loop's **doc phase**
  is "read this doc and execute". Run profile checks the target file exists.
- **`Design philosophy:`** — points at the project's change-discipline / design-philosophy doc.
  `code-writer` reads it (delete-don't-tombstone, no defensive caveats, testability, etc.). Run
  profile checks the target file exists.

## 6. Host conventions (`~/.claude/CLAUDE.md`)

The skills reference the **issue tracker** and **notifications** generically ("file findings to
the issue tracker", "notify per the host convention", "the project's owner tag"). The concrete
wiring — which kanban tool, board/list names, the owner-tag rule (the bare repo name), the
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
- **The three contract lines are read by machine.** Keep the labels exactly as written above.

Onboarding a repo — when the contract lines go in — is when the trim is cheapest to make.

## What a good root `CLAUDE.md` contains

Beyond the four required lines, a `CLAUDE.md` that serves the pipeline well describes the project
so a fresh dev session lands oriented. A rough shape (prose, not a template):

- **One-paragraph overview** — what the project is and its high-level shape (the components map to
  `kc project list`).
- **The three pipeline lines** above.
- **Repo structure** — one line per component and where the spec repo lives; the commit-early rule
  for the spec repo (it is a separate git repo).
- **Design philosophy** — the non-negotiable cross-component rules (the `Design philosophy:` line
  points at the fuller doc; a short summary here is fine).
- Pointers to the per-component `docs/` a dev agent reads (code style, conventions), and to the
  project's decision index if it keeps one.

Each component may also carry its own `CLAUDE.md` and `docs/`; a phase's plan section points the
executor at what its Target's docs require (dispatches run at the repo root — see
[agent-dispatch.md](agent-dispatch.md)).
