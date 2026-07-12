# The project contract — what a repo must provide to use `dev`

The `dev` plugin is generic and portable; each project describes **itself**. A repo becomes usable
by the pipeline when it provides the five things below. Nothing here is a template you copy — it is
a small set of facts the plugin reads (via `kc` and three `CLAUDE.md` lines), all **enforced by
preflight** (`${CLAUDE_PLUGIN_ROOT}/tools/preflight.py`; see [`preflight.md`](preflight.md)). A new
repo self-onboards from preflight's error text.

## 1. `.kubecoder/project.yaml` — the component manifest

Present and valid, so `kc project list --output=json` returns the repo's components (each with a
`name`, an effective `cwd`, and a description) in file order. This is the single source of the
**project set** and each component's working directory — the plugin never hardcodes them and never
parses the YAML itself; only `kc` reads it. The manifest also declares the **curated automation**
(`kc project build|test|lint --project <name>`) the dev agents run for a deterministic green signal.

- **Absent or malformed** → preflight (plan/run) bails.
- A task's `project` in `task.json` must be one of these component names.

See `kc`'s own `project-manifest.md` for the manifest schema.

## 2–4. Three `CLAUDE.md` entries (machine-checkable line prefixes)

The plugin cannot ship a `CLAUDE.md` (it is project/user memory, discovered by walking the repo
tree — not a plugin asset). Instead the target repo's **root `CLAUDE.md`** carries three lines the
plugin reads by exact label prefix (markdown decoration — list markers, `**bold**`, `` `backticks` ``
— is tolerated; the value may be an absolute path or one relative to the repo root):

```
Spec repo: <path>
Slice testing strategy: <path-to-doc>
Design philosophy: <path-to-doc>
```

Each **bails, not warns** — it is one line to add:

- **`Spec repo:`** — where slices, tasks, and each run's `state.json`/`log.txt` live (the separate
  spec/planning repo). `triage` and `plan-slice` cannot allocate or plan a slice with nowhere to
  write it, so all three profiles require it and check the path exists (a directory).
- **`Slice testing strategy:`** — points at the project-owned doc describing the slice-level
  deploy-verification procedure (what it pushes, what it checks, how findings resolve). `run-slice`'s
  "run the slice testing strategy defined for this project" resolves through this line; the plugin
  never names the doc. Run profile checks the target file exists.
- **`Design philosophy:`** — points at the project's change-discipline / design-philosophy doc.
  `code-writer` reads it (delete-don't-tombstone, no defensive caveats, testability, etc.). Run
  profile checks the target file exists.

## 5. Host conventions (`~/.claude/CLAUDE.md`)

The commands reference the **issue tracker** and **notifications** generically ("file findings to
the issue tracker", "notify per the host convention", "the project's owner tag"). The concrete
wiring — which kanban tool, board/list names, the owner-tag rule (the bare repo name), the
notification command — is environment-specific and lives in the host `~/.claude/CLAUDE.md`, which
already holds it. The plugin neither ships nor duplicates it.

## What a good root `CLAUDE.md` contains

Beyond the three required lines, a `CLAUDE.md` that serves the pipeline well describes the project
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

Each component may also carry its own `CLAUDE.md`; a dev session runs with `--cwd` at the
component's directory, so it loads that component's `CLAUDE.md` and docs automatically.
