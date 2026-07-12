# Plan — rework AIWorkflow into the `dev` plugin (kc-native)

**Status:** reviewed 2026-07-12 — facts verified against KubeCoder, this repo, and the plugin docs;
review findings applied (see §9 additions). Open decisions resolved (§9). Deliverable is this plan,
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
| `PROJECT_DIRS` / `VALID_PROJECTS` hardcoded maps | `kc project list --output-json` (name → effective cwd → description, from `.kubecoder/project.yaml`; `--output-json` is Triage #192, in flight) |
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
├── .claude-plugin/plugin.json          # { name: "dev", description, author, version } — bump version per release
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

**Agent-discovery resolution — ✅ verified 2026-07-12.** Installed into `~/.claude`, the plugin's
agents resolve everywhere as `dev:<name>`. The runner spawns them by that namespaced name via
`kc session create-headless --agent dev:code-writer --cwd <subproject-cwd>`; `kc` passes the string
through opaquely and Claude Code's `--agent` resolver (present in the CLI at v2.1.207, undocumented
in the headless docs) does the lookup. Verified with a stub plugin: `claude -p --agent
stubtest:echo-probe` resolves the plugin agent headlessly; the bare name also resolves while
unambiguous (the runner uses the namespaced form); an unknown name fails loudly (exit 1, listing
available agents with the namespaced spelling as canonical). Residual verification at cutover: one
smoke test after the real marketplace install (the stub test used `--plugin-dir`), and confirm
consults still spawn bare (no `--agent`). The kc-spawned session's `~/.claude` is guaranteed to be
the same home as the operator's install.

**Plugin-internal paths.** Everything the plugin ships is referenced via `${CLAUDE_PLUGIN_ROOT}`
(substitution works in command and agent content): `run-slice` invokes
`${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py`; agents and commands reference
`${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md` (etc.) instead of repo-relative paths. No plugin file
is ever addressed by a path inside the target repo.

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

### 6a. Subproject discovery → `kc project list --output-json`
Replace `PROJECT_DIRS` (task_runner.py:51–58) / `VALID_PROJECTS` (claude_session.py:60) and the
project enum baked into `plan-writer` + the `task.json` schema with **`kc project list
--output-json`** (Triage **#192**, being executed now — supersedes the earlier "read
`.kubecoder/project.yaml` directly" decision). The runner and plan-writer take the valid project
set and each project's *effective* cwd from the JSON, so the cwd-resolution rule stays implemented
exactly once, in `kc` (`ResolveCwd`), and the runner needs no YAML parser — it stays stdlib-only.
`.kubecoder/project.yaml` remains the source manifest; only `kc` reads it.

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
`kc session` flags (`--model`, `--reasoning-effort`) and `status` polling. **Prompt-caching:** `FORCE_PROMPT_CACHING_5M=1` is set in
the child env today; `kc session create-headless` does not thread caller env to the spawned session.
Resolution (operator decision): add a **repeatable `-e NAME=VALUE` env pass-through** to
`kc session create-headless` (docker-style; future-proofs Claude Code's env-controlled knobs) rather
than a caching-specific flag — **Triage #191, being executed now**. Usage is `-e NAME=VALUE` (takes a
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

*(Check set, per-command profiles, and bail semantics are being specced — 2026-07-12 sketch under
discussion with the operator; the agreed result replaces this section and becomes
`docs/preflight.md`.)*

### 6e. Dependency ordering
`kc project` (slice 074) and `kc session` headless (slice 075) are already landed in KubeCoder. Two
confirmed `kc` gaps, both carded and being executed now: **#191** (`-e NAME=VALUE` pass-through on
`create-headless`, §6c — lands *before* the session-drive cutover so caching parity is preserved)
and **#192** (`--output-json` on `kc project list`, §6a — the runner's machine-readable project
map). Separately, **no adopting repo has a `.kubecoder/project.yaml` yet** — KubeCoder itself
included. The operator onboards IoTSupport first and authors its manifest; real-slice validation
(§8 phase 3) needs at least one repo with a manifest. The plugin is authored against `kc` and not
shipped until the `kc` surface it calls is confirmed present.

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
│   └── AUTHORING.md                    # WRITING_GUIDE.md, trimmed to the still-true rules
│                                       #   (project-contract.md ships inside plugins/dev/docs/; link from here)
├── runbooks/
│   └── MERGING.md                      # monorepo-merge runbook — moved, not deleted (see Delete notes)
├── tools/
│   ├── analysis/                       # the measurement workshop — KEEP
│   └── code_health/                    # KEEP as backlog: rebuild as a proper tool for `upkeep` (§7a)
├── workflow-improvements/              # R&D / evidence — KEEP
├── CHANGELOG-workflow.md               # repurposed: the plugin's changelog
├── README.md                           # rewritten: "the dev plugin + workshop"
└── LICENSE
```

### Delete
- `orchestrator/` — **everything not explicitly retained is deleted.** Retained (move to `upkeep`
  backlog, §7a): the four auxiliary commands (`quality-improver`, `quality-issue-finder`,
  `refactor-audit`, `update-docs`) and `docs/documentation-model.md`. Deleted, explicitly: the
  root-CLAUDE template; the retired commands (`major-change`, `minor-change`, `write-slice`);
  `ux-design.md` (unused — operator call 2026-07-12); the stale pre-#175 copies of `triage.md`,
  `run-slice.md`, `agents/arch-design.md`, `agents/slice-verifier.md` (the validated copies migrate
  from KubeCoder, see "Move into the plugin"); all of `scripts/` (`build-all.py`,
  `regenerate-openapi.py`, `preflight.py` — superseded by the plugin preflight, §6d — and
  `_initd_log.py`); root scaffolding (`pyproject.toml`, `pnpm-workspace.yaml`); the dotfiles
  (`.codehealthignore`, `.gitignore`). (`arch-design` command + agent go to `dev`.)
- `project/` — entire tree. Per-subproject `CLAUDE.md` template + per-subproject agent copies. The
  agents move to `plugins/dev/agents/` as a **single copy** (this is the "removed the subproject
  agent definitions" change already made in KubeCoder).
- `EXAMPLE.md` — the rendered-Jinja example has no meaning without templates. Fold a short worked
  example into `ADOPTING.md`.
- `MERGING.md` — **not deleted; moves to `runbooks/MERGING.md`.** Review finding 2026-07-12: this is
  not template-merge guidance but a monorepo-merge runbook (`git filter-repo` phases, Jenkinsfile
  consolidation, hard-won learnings from the IoTSupport run) with per-repo status — the DHCPApp,
  ElectronicsInventory, and ZigbeeControl runs are still pending. Plugin upgrades replace none of it.
- `tools/ai_workflow/claude_session.py` — retired (§6c).
- `tools/ai_workflow/codex_exec.py`, `send_message.py` — Codex path is orthogonal/optional;
  notifications move to host-global. Drop from the plugin surface.

### Move into the plugin (from KubeCoder's validated `.claude/` + `tools/`)
- 8 agents → `plugins/dev/agents/` (strip the residual KubeCoder specifics: the project enum in
  `plan-writer`, the `../KubeCoderSpecs/api/*.md` reference in `code-reviewer`, specs-path examples;
  replace with `kc`/contract-doc references).
- 6 commands → `plugins/dev/commands/` (replace the `../KubeCoderSpecs` literal with the CLAUDE.md
  spec-repo lookup; add `argument-hint`/`allowed-tools` frontmatter, absent today).
- `task_runner.py` → `plugins/dev/tools/` (kc-native rewrite of the three seams; invoked by
  `run-slice` as `${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py`).
- `docs/conventions/task-workflow.md` → `plugins/dev/docs/task-workflow.md` (drop the project enum
  and the two `../KubeCoderSpecs` prefixes; referenced by agents/commands as
  `${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md`).

### Repurpose / keep
- `WRITING_GUIDE.md` → `docs/AUTHORING.md`: the hierarchy diagram is obsolete, but the durable rules
  survive (thin agents = identity + output contract + bounds; no-duplication; **`description` is
  mandatory or the agent silently isn't registered** — observed behavior, the official plugin docs
  are silent on it; the "state every fact once" doc diet).
- `tools/analysis/` (`slice_costs.py`, `runner_sessions.py`) and `workflow-improvements/` — keep as
  the workshop where the workflow is measured and improved. Note `runner_sessions.py` reads
  `state.json`'s recorded `transcript` paths (plus a `~/.claude/projects/` glob); after the cutover
  the runner must keep recording session-id → transcript locations (from `kc session status`), or
  the workshop goes blind.
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
`documentation-model.md` as its reference doc. (The validated copies of these four commands live in
KubeCoder's `.claude/commands/` alongside the pipeline six — migrate from there, not from the stale
`orchestrator/` copies.) Its open backlog item is turning `tools/code_health/`
into a **proper tool** (the current shape is not shippable). These files stay in-repo through this
rework as explicit backlog — parked, not deleted — and are migrated when `upkeep` is built. `dev`
ships first and stands alone.

---

## 8. Sequencing (phases)

1. **Verify the mechanics** (small, do first): ✅ plugin-agent discovery verified 2026-07-12
   (stub-plugin test, §4) — residual is one smoke test after the real marketplace install.
   Remaining gates are in `kc`: `--output-json` on `kc project list` (#192) and the `-e`
   pass-through / headless caching (#191), both carded and being executed now. Gate phase 3 on them.
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
Development happens in this repo. **Iteration loop:** `--plugin-dir` reaches only the operator's
own session — the runner's agents live in kc-spawned headless sessions, which see only what is
actually installed in `~/.claude` (guaranteed to be the same home). So iterate by adding this repo
as a local marketplace (`/plugin marketplace add /work/AIWorkflow`), installing `dev`, and
re-updating the plugin after edits; `--plugin-dir` is only good for operator-side command tweaks.

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
6. **Project map (review amendment 2026-07-12):** ✅ `kc project list --output-json` (#192) —
   supersedes the earlier direct `.kubecoder/project.yaml` read.
7. **`MERGING.md` (review amendment):** ✅ moved to `runbooks/`, not deleted — it's the monorepo-merge
   runbook with pending runs, unrelated to templates.
8. **`ux-design` command (review amendment):** ✅ deleted — unused.

---

## 10. Risks / things to verify before committing

- **Plugin-agent discovery for `kc session --agent dev:<role>`** — ✅ verified 2026-07-12 (§4):
  namespaced and bare names both resolve headlessly; unknown names fail loudly (exit 1). Residual:
  one smoke test after the real marketplace install (the stub test used `--plugin-dir`).
- **Project map** — ✅ resolved: `kc project list --output-json` (#192, in flight; §6a). The
  cwd-resolution rule stays in `kc` only. New caveat: no adopting repo has a manifest yet —
  IoTSupport onboards first (§6e).
- **Headless prompt-caching** — ✅ resolved as a known `kc` gap: `-e NAME=VALUE` pass-through on
  `kc session create-headless` (§6c), Triage #191, being executed now. Lands before the §6c cutover.
- **Crash-recovery parity** — `state.json` in-flight-session reattach must map onto
  `kc session --resume` + `status`; confirm a killed run reattaches cleanly.
- **Existing-backlog layout** — most on-disk slices still use the pre-#175 `overview.md` +
  per-project-subfolder shape; the plugin targets the `tasks/NN_slug/` layout. Backlog re-planning is
  independent of this rework but worth noting so nobody points the new runner at an old-shape slice.
- **`runner_sessions.py` / `slice_costs.py`** — see §7 Repurpose/keep: the runner must keep
  recording session-id → transcript locations under `kc session`, or the workshop goes blind.
