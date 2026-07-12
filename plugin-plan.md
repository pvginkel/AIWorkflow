# Plan — rework AIWorkflow into the `dev` plugin (kc-native)

**Status:** draft for review (2026-07-12), open decisions resolved (§9). Deliverable is this plan,
not an implementation. Supersedes the "sync the #175 rework back into `orchestrator/`/`project/`
templates" direction recorded in `CHANGELOG-workflow.md` — instead of copy-and-fill templates,
the workflow becomes an **installable Claude Code plugin** named `dev`, and this repo becomes its
home.

**Scope.** This plugin version targets the **KubeCoder environment only**, so a hard dependency on
`kc` is fine — no abstract provider interface, no non-`kc` fallback. The plugin is **developed in
this repo**. Retiring KubeCoder's own copy of the workflow (`../KubeCoder/.claude/commands` +
`.claude/agents`) is a later cleanup the operator owns and is **out of scope of this plan**.

---

## 1. The decision in one paragraph

The slice workflow (validated across KubeCoder slices 072, 074–078) stops being a template you
copy into a repo and becomes a **plugin** installed once into `~/.claude`. Its commands namespace
to `dev:triage`, `dev:plan-slice`, `dev:run-slice`, `dev:write-task`, `dev:slice-dag`,
`dev:arch-design`; its 8 agents ship inside the plugin; its Python runner ships inside the plugin.
Everything that used to be a Jinja blank or a hardcoded per-repo constant is replaced by one of two
things: a **`kc` call** (subproject discovery, curated build/test/lint, session drive) or a **short
entry the target repo's own `CLAUDE.md` provides** (where the spec repo lives, which doc holds the
slice testing strategy). This host runs the workflow inside KubeCoder pods where `kc` is always on
PATH, so a hard dependency on `kc` is not a portability loss — it is what *makes* the plugin
portable across every KubeCoder project, because each project describes itself in
`.kubecoder/project.yaml` instead of in the workflow's code.

---

## 2. Target architecture — the pipeline is unchanged; the substrate changes

The three operator sessions and the runner are exactly as validated:

```
/dev:triage  →  /dev:plan-slice  →  /dev:run-slice  ──launches──▶  task_runner.py (state machine)
  (findings→        (plan-writer +       (thin: preflight,               │ per task:
   slice.md)         plan-reviewer →       bail-outs, close-out)          │ branch → code-writer
                     tasks/NN_slug/)                                      │ → code-tester (cap 3)
                                                                         │ → code-reviewer (cap 2)
                                                                         │ → ff-merge → checkpoint consult
```

**"Files durable, sessions ephemeral"** and **"scripts drive, agents judge"** are unchanged. What
changes is the three seams that were project-specific, each now backed by a `kc` primitive:

| Seam (was) | Becomes |
|---|---|
| `PROJECT_DIRS` / `VALID_PROJECTS` hardcoded maps | `kc project list` (name → effective cwd → description, from `.kubecoder/project.yaml`) |
| "test/build/lint commands" read from each subproject's `CLAUDE.md` | `kc project test\|build\|lint --project <name>` (curated, terse, fail-fast, exit-coded) |
| `claude_session.py` (801 ln) shelling `claude --agent` over stream-json | `kc session create-headless \| send \| status \| end \| interrupt` — the docs state these "do what `claude_session.py` does today, done right" |

This is the crux of the rework: **the code that made the workflow non-portable (two hardcoded
dicts, per-repo test commands, a bespoke `claude` wrapper) all collapses into `kc` calls.**

---

## 3. The generic ↔ project boundary, after `kc`

| Ships in the `dev` plugin (generic, portable) | Provided by the target project |
|---|---|
| 8 agents (code-writer/tester/reviewer, plan-writer/reviewer, test-agent, slice-verifier, arch-design) | `.kubecoder/project.yaml` — the subproject/build-unit manifest (`kc` reads it) |
| 6 pipeline commands (triage, plan-slice, run-slice, write-task, slice-dag, arch-design) | `CLAUDE.md` entry: **"The spec repo is at `<path>`"** |
| `task_runner.py` (kc-native state machine) | `CLAUDE.md` entry: pointer to the project's **slice testing strategy** doc |
| the contract doc `task-workflow.md` | `CLAUDE.md` entry: pointer to design-philosophy / change-discipline |
| the verdict / state / bailout JSON contracts + task-folder anatomy | `docs/operations/slice-test-plan.md` (or equivalent) — the actual test/deploy strategy |
| preflight logic (expressed over `kc` primitives) | The `~/.claude/CLAUDE.md` (host-global) conventions for **issue tracking + notifications** |

Three things the plugin **references but never owns**:

- **Subproject set** → `kc project list`. Not in the plugin, not in `CLAUDE.md` anymore.
- **Issue tracker + notifications** → referenced generically ("file findings to the issue tracker",
  "notify per the host convention"); the concrete Trello/`send_message` wiring lives in
  `~/.claude/CLAUDE.md`, which is environment-specific and already holds it on this host.
- **Slice testing strategy** → `run-slice` says *"run the slice testing strategy defined for this
  project"*; that phrase resolves through `CLAUDE.md` to the project's own doc. `run-slice` never
  names the doc.

---

## 4. What the plugin ships

```
plugins/dev/
├── .claude-plugin/plugin.json          # { name: "dev", description, author }
├── commands/
│   ├── triage.md          → /dev:triage
│   ├── plan-slice.md      → /dev:plan-slice
│   ├── run-slice.md       → /dev:run-slice
│   ├── write-task.md      → /dev:write-task
│   ├── slice-dag.md       → /dev:slice-dag
│   └── arch-design.md     → /dev:arch-design
├── agents/                             # discovered as dev:<name> when installed
│   ├── code-writer.md   code-reviewer.md   code-tester.md   test-agent.md
│   ├── plan-writer.md   plan-reviewer.md   slice-verifier.md   arch-design.md
├── tools/
│   └── task_runner.py                  # kc-native; claude_session.py RETIRED
└── docs/
    ├── task-workflow.md                # the canonical contract (unchanged in substance)
    ├── project-contract.md             # what .kubecoder/project.yaml + CLAUDE.md must provide
    └── preflight.md                    # the kc-primitive preflight spec
```

Auxiliary commands (`quality-improver`, `quality-issue-finder`, `refactor-audit`, `update-docs`)
are **not in `dev`.** They form a planned **second plugin** in this same marketplace (see §7a),
retained in-repo now as migration backlog.

**Agent-discovery resolution (the "mechanical problem").** Installed into `~/.claude`, the plugin's
agents resolve everywhere as `dev:<name>`. The runner spawns them by that namespaced name via
`kc session create-headless --agent dev:code-writer --cwd <subproject-cwd>`. No `--plugin-dir`, no
repo-local `.claude/agents/`. One verification task before cutover: confirm a
`kc session create-headless --agent dev:code-writer` from a subproject cwd actually resolves the
plugin agent (should, since the plugin is user-global and the headless session inherits it) — and
confirm consults still spawn bare (no `--agent`).

---

## 5. The project contract (what a repo must provide to use `dev`)

Documented in `plugins/dev/docs/project-contract.md`, and **enforced by preflight** — not a template
to fill:

1. **`.kubecoder/project.yaml`** present and valid → `kc project list` returns the subprojects.
   Absent/malformed manifest = preflight bail.
2. **`CLAUDE.md` — spec repo entry.** A line of the form "The spec repo is at `<path>`". `triage`
   and `plan-slice` **bail if this is absent** (they cannot allocate/plan a slice with nowhere to
   write it).
3. **`CLAUDE.md` — slice testing strategy pointer.** A line pointing at the project's slice
   test-plan doc, so `run-slice`'s "run the slice testing strategy defined for this project"
   resolves. The doc itself (`docs/operations/slice-test-plan.md` in KubeCoder) is project-owned.
4. **`CLAUDE.md` — design-philosophy pointer** (change-discipline). `code-writer` reads it.
5. **`~/.claude/CLAUDE.md`** (host) provides the issue-tracker + notification conventions the
   commands reference generically.

Instead of shipping `CLAUDE.md` templates (a plugin cannot ship `CLAUDE.md` — it is project/user
memory discovered by walking the repo tree), the plugin ships a **prose description of what a good
`CLAUDE.md` contains** plus a preflight/doctor check that the required entries exist. This is the
"general descriptions on what a CLAUDE.md should look like should suffice" you asked for.

---

## 6. The `kc` integration — the real engineering

### 6a. Subproject discovery → read `.kubecoder/project.yaml` directly
Replace `PROJECT_DIRS`/`VALID_PROJECTS` (task_runner.py ~48–57, claude_session.py ~50–62) and the
project enum baked into `plan-writer` + the `task.json` schema by **reading `.kubecoder/project.yaml`
directly** (operator's call — cleaner than parsing `kc project list` output). The runner and
plan-writer take the `projects:` keys as the valid set and resolve each task's cwd from the manifest.
**Reproduce `kc`'s cwd-resolution rule**, since the file stores `cwd` verbatim and does *not* resolve
the default: `root` → repo root; absent `cwd` → same-named subfolder under repo root; explicit `cwd`
→ absolute verbatim, else joined under repo root. (`kc project` is still used for the execution verbs
in §6b; only the machine-readable map is a direct file read.)

### 6b. Curated automation → `kc project test|build|lint`
`code-tester` and `test-agent` run `kc project test --project <name>` (and `build`/`lint`) for the
deterministic green signal, instead of reading test commands from a subproject `CLAUDE.md`. This is
the *component-level* test surface; the *slice-level* strategy (E2E, live-deploy) stays in the
project's slice-test-plan doc (§5.3). Agent bodies lose their "read this project's CLAUDE.md for test
commands" lines in favor of the `kc project` verb.

### 6c. Session drive → `kc session …` (retire `claude_session.py`)
The runner's per-round session I/O becomes:
```
name=$(kc session create-headless --agent dev:<role> --model <m> --cwd <cwd> [--resume <id>] \
        [-e FORCE_PROMPT_CACHING_5M=1 …])   # -e pass-through: pending kc card, see below
kc session send "$name" --prompt-file <p> --response-file <r>     # synchronous; owns SSE reconnect
kc session status "$name" --output=json                          # for state/verdict correlation
kc session end "$name"
```
`kc session` already owns: offset-based SSE reconnect on drop, interrupt-on-kill, busy/usage/unknown
exit codes, `--resume`. So `claude_session.py` (801 ln) is **deleted**, and `task_runner.py` shrinks
(no raw subprocess/stream-json management, no reimplemented crash recovery). The runner keeps
everything above the session boundary: the task loop, caps, consults, verdict-file validation, git
management, `state.json`, resume, exit codes. Map the current `MODELS`/`TIMEOUTS`/nudge behavior onto
`kc session` flags and `status` polling. **Prompt-caching:** `FORCE_PROMPT_CACHING_5M=1` is set in
the child env today; `kc session create-headless` does not thread caller env to the spawned session.
Resolution (operator decision): add a **repeatable `-e NAME=VALUE` env pass-through** to
`kc session create-headless` (docker-style; future-proofs Claude Code's env-controlled knobs) rather
than a caching-specific flag — **carded on Triage for KubeCoder**. Usage is `-e NAME=VALUE` (takes a
value; not a bare `-e`); the runner passes `-e FORCE_PROMPT_CACHING_5M=1` once that lands.

### 6d. Preflight re-envisioned on `kc` primitives
`scripts/preflight.py` (project-owned today) becomes a plugin-shipped preflight expressed over `kc`:
- `kc project info` / `kc project list` succeed → manifest present, subprojects known (else bail with
  the "not set up" message `kc` itself emits).
- Optionally `kc project build && kc project test` as a clean baseline before a run (the "safe to
  push" signal), gated by the slice test strategy.
- spec-repo entry present in `CLAUDE.md` (§5.2) → else bail.
- clean working tree (existing check); `kc` on PATH and the worker daemon reachable (needed for
  `kc session`).

### 6e. Dependency ordering
`kc project` (slice 074) and `kc session` headless (slice 075) are already landed in KubeCoder. The
project map is a direct `.kubecoder/project.yaml` read (§6a), so it depends on no `kc` output format.
The one confirmed `kc` gap is the **`-e NAME=VALUE` pass-through on `kc session create-headless`**
(§6c), carded on Triage — it lands *before* the session-drive cutover so caching parity is preserved. The
plugin is authored against `kc` and not shipped until the `kc` surface it calls is confirmed present.

---

## 7. AIWorkflow repo rework — file by file

### New layout
```
AIWorkflow/                             # a marketplace hosting one+ plugins, plus the workshop
├── .claude-plugin/marketplace.json     # makes the repo installable: /plugin marketplace add <this repo>
├── plugins/
│   ├── dev/                            # THE plugin (see §4) — v1 deliverable
│   └── upkeep/                         # second plugin (name TBD) — migration backlog (§7a)
├── docs/
│   ├── ADOPTING.md                     # rewritten: install plugin + author project.yaml + CLAUDE.md entries
│   ├── AUTHORING.md                    # WRITING_GUIDE.md, trimmed to the still-true rules
│   └── project-contract.md             # (or keep this inside plugins/dev/docs/ and link)
├── tools/
│   ├── analysis/                       # the measurement workshop — KEEP
│   └── code_health/                    # KEEP as backlog: rebuild as a proper tool for `upkeep` (§7a)
├── workflow-improvements/              # R&D / evidence — KEEP
├── CHANGELOG-workflow.md               # repurposed: the plugin's changelog
├── README.md                           # rewritten: "the dev plugin + workshop"
└── LICENSE
```

### Delete
- `orchestrator/` — most of the tree. Delete: the root-CLAUDE template, the retired commands
  (`major-change`, `minor-change`, `write-slice`), root scaffolding (`pyproject.toml`,
  `pnpm-workspace.yaml`) and orchestration scripts (`build-all.py`, `regenerate-openapi.py`) — all
  project-specific or obsolete. **Retain** (move to `upkeep` backlog, §7a): the auxiliary commands
  (`quality-improver`, `quality-issue-finder`, `refactor-audit`, `update-docs`, `arch-design` — note
  `arch-design` itself goes to `dev`) and `documentation-model.md`.
- `project/` — entire tree. Per-subproject `CLAUDE.md` template + per-subproject agent copies. The
  agents move to `plugins/dev/agents/` as a **single copy** (this is the "removed the subproject
  agent definitions" change already made in KubeCoder).
- `EXAMPLE.md` — the rendered-Jinja example has no meaning without templates. Fold a short worked
  example into `ADOPTING.md`.
- `MERGING.md` — "how to merge template updates into an adopting repo" is replaced by plugin
  upgrades. (Confirm nothing unique is lost before deleting — not yet read in full.)
- `tools/ai_workflow/claude_session.py` — retired (§6c).
- `tools/ai_workflow/codex_exec.py`, `send_message.py` — Codex path is orthogonal/optional;
  notifications move to host-global. Drop from the plugin surface.

### Move into the plugin (from KubeCoder's validated `.claude/` + `tools/`)
- 8 agents → `plugins/dev/agents/` (strip the residual KubeCoder specifics: the project enum in
  `plan-writer`, the `../KubeCoderSpecs/api/*.md` reference in `code-reviewer`, specs-path examples;
  replace with `kc`/contract-doc references).
- 6 commands → `plugins/dev/commands/` (replace the `../KubeCoderSpecs` literal with the CLAUDE.md
  spec-repo lookup; add `argument-hint`/`allowed-tools` frontmatter, absent today).
- `task_runner.py` → `plugins/dev/tools/` (kc-native rewrite of the three seams).
- `docs/conventions/task-workflow.md` → `plugins/dev/docs/task-workflow.md` (drop the project enum
  and the two `../KubeCoderSpecs` prefixes).

### Repurpose / keep
- `WRITING_GUIDE.md` → `docs/AUTHORING.md`: the hierarchy diagram is obsolete, but the durable rules
  survive (thin agents = identity + output contract + bounds; no-duplication; **`description` is
  mandatory or the agent silently isn't registered**; the "state every fact once" doc diet).
- `tools/analysis/` (`slice_costs.py`, `runner_sessions.py`) and `workflow-improvements/` — keep as
  the workshop where the workflow is measured and improved. Note `runner_sessions.py` assumes the
  `claude_session.py` transcript layout; it will need updating for `kc session` transcripts.
- `specs/scripts/allocate-next-slice.sh` — project/specs-repo-owned; keep as a referenced example in
  `ADOPTING.md`, not plugin-shipped.
- `.agents/` (Codex UX skill) — orthogonal; keep or drop independently of this rework.
- `tools/code_health/` — **keep, do not ship in `dev`.** It gave real value but is messy as a tool;
  it becomes a backlog item to **rebuild as a proper tool** for the `upkeep` plugin (§7a). Only the
  deferred quality-* commands consume it.

### 7a. The second plugin (`upkeep`, name TBD) — migration backlog

Not built in this rework; scoped here so the retained files have a destination. A sibling plugin in
the same marketplace that packages the **codebase-maintenance capabilities that feed `/dev:triage`**:
`update-docs`, `refactor-audit`, `quality-improver`, `quality-issue-finder`, plus
`documentation-model.md` as its reference doc. Its open backlog item is turning `tools/code_health/`
into a **proper tool** (the current shape is not shippable). These files stay in-repo through this
rework as explicit backlog — parked, not deleted — and are migrated when `upkeep` is built. `dev`
ships first and stands alone.

---

## 8. Sequencing (phases)

1. **Verify the mechanics** (small, do first): plugin-agent discovery via
   `kc session create-headless --agent dev:<role>`; `kc project list` machine-readability; headless
   caching behavior. These three can reshape §6, so gate the build on them.
2. **Scaffold the plugin** in `plugins/dev/` + `marketplace.json`; move the 6 commands and 8 agents
   over verbatim (still KubeCoder-flavored), install into `~/.claude`, confirm `dev:*` invocations
   and agent dispatch work end-to-end on a trivial slice.
3. **Cut the three seams to `kc`** (§6a–6c): project discovery, curated automation, session drive.
   Retire `claude_session.py`. This is the bulk of the engineering; validate on a real slice and
   re-measure with the workshop tools (orchestrator share should stay ~15%).
4. **Preflight + project contract** (§6d, §5): rewrite preflight over `kc`; write
   `project-contract.md`; make `triage`/`plan-slice` bail on a missing spec-repo entry; change
   `run-slice` to the "slice testing strategy defined for this project" wording.
5. **Rework the AIWorkflow repo shell** (§7): delete `orchestrator/`/`project/`/`EXAMPLE.md`/
   `MERGING.md`; rewrite `README.md`, `ADOPTING.md`, `AUTHORING.md`; repurpose `CHANGELOG-workflow.md`
   as the plugin changelog.
Development happens in this repo; install into `~/.claude` via `--plugin-dir` while iterating.

**Out of scope:** retiring KubeCoder's own `.claude/commands/` + `.claude/agents/` copies once the
plugin supersedes them. The operator owns that cleanup separately. During development, KubeCoder's
in-repo copies and the installed plugin can coexist (repo-local `.claude/` wins on name collisions);
that is expected and not this plan's concern.

---

## 9. Decisions (resolved)

1. **Repo shape:** ✅ marketplace hosting `plugins/dev/` (and a future `plugins/upkeep/`).
2. **Commands vs Skills:** ✅ the `dev` pipeline stays as `commands/`; the future `upkeep`
   capabilities become skills.
3. **Auxiliary commands:** ✅ not in `dev`. Retained in-repo as `upkeep` backlog (§7a), not deleted.
4. **Where developed:** ✅ in this repo. KubeCoder-copy cleanup is out of scope (see Scope note).
5. **`documentation-model.md`:** ✅ ships with the second plugin (`upkeep`) as its reference doc —
   not in `dev`, not project-owned.

---

## 10. Risks / things to verify before committing

- **Plugin-agent discovery for `kc session --agent dev:<role>`** — the load-bearing assumption (§4).
  **Assumed to work** (operator's call; not testable right now). Low residual risk; revisit if it fails.
- **Project map** — ✅ resolved: read `.kubecoder/project.yaml` directly (§6a). No dependency on any
  `kc` output format. Only caveat: reproduce the cwd-resolution rule.
- **Headless prompt-caching** — ✅ resolved as a known `kc` gap: `-e NAME=VALUE` pass-through on
  `kc session create-headless` (§6c), carded on Triage for KubeCoder. Lands before the §6c cutover.
- **Crash-recovery parity** — `state.json` in-flight-session reattach must map onto
  `kc session --resume` + `status`; confirm a killed run reattaches cleanly.
- **Existing-backlog layout** — most on-disk slices still use the pre-#175 `overview.md` +
  per-project-subfolder shape; the plugin targets the `tasks/NN_slug/` layout. Backlog re-planning is
  independent of this rework but worth noting so nobody points the new runner at an old-shape slice.
- **`runner_sessions.py` / `slice_costs.py`** parse `claude_session.py`-era transcripts; update for
  `kc session` transcript locations so the workshop keeps working.
