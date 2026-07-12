# Plan — rework AIWorkflow into the `dev` plugin (kc-native)

**Status:** **EXECUTED 2026-07-12** — the plugin is built (`plugins/dev/`) and the repo is reworked
into a marketplace. Phases 2 (scaffold), 3 (kc-native runner), 4 (preflight + contract), and 5 (repo
shell) are done; phase 1's mechanics were pre-verified. The `kc` surface was re-verified against the
**actual** implementation (KubeCoderSpecs slice **079**, which landed cards #191 + #192) and the
runner/preflight were written against it — with the corrections noted inline below (the biggest:
the flag is `--output=json`, **not** the `--output-json` this plan originally assumed). **Not yet
live-tested against `kc`** (no `kc` in the authoring env); the operator validates on a real slice.
Remaining follow-ups are collected in §11.

Supersedes the "sync the #175 rework back into `orchestrator/`/`project/` templates" direction
recorded in `CHANGELOG-workflow.md` — instead of copy-and-fill templates, the workflow becomes an
**installable Claude Code plugin** named `dev`, and this repo becomes its home.

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
| `PROJECT_DIRS` / `VALID_PROJECTS` hardcoded maps | `kc project list --output=json` (name → effective cwd → description, from `.kubecoder/project.yaml`; `--output=json` — the flag name shipped in slice **079**, correcting this plan's original `--output-json` assumption) |
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
│   ├── task_runner.py                  # kc-native; claude_session.py RETIRED
│   └── preflight.py                    # profile-based preflight, stdlib-only (§6d)
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
2. **`CLAUDE.md` — spec repo entry.** The line `Spec repo: <path>` (machine-checkable prefix, §6d).
   `triage` and `plan-slice` **bail if this is absent** (they cannot allocate/plan a slice with
   nowhere to write it).
3. **`CLAUDE.md` — slice testing strategy pointer.** The line `Slice testing strategy:
   <path-to-doc>`, so `run-slice`'s "run the slice testing strategy defined for this project"
   resolves. The doc itself (`docs/operations/slice-test-plan.md` in KubeCoder) is project-owned;
   `run-slice` preflight bails if the line or the doc is absent.
4. **`CLAUDE.md` — design-philosophy pointer.** The line `Design philosophy: <path-to-doc>`
   (change-discipline). `code-writer` reads it; `run-slice` preflight bails if absent.
5. **`~/.claude/CLAUDE.md`** (host) provides the issue-tracker + notification conventions the
   commands reference generically.

Instead of shipping `CLAUDE.md` templates (a plugin cannot ship `CLAUDE.md` — it is project/user
memory discovered by walking the repo tree), the plugin ships a **prose description of what a good
`CLAUDE.md` contains** plus a preflight/doctor check that the required entries exist. This is the
"general descriptions on what a CLAUDE.md should look like should suffice" you asked for.

---

## 6. The `kc` integration — the real engineering

### 6a. Subproject discovery → `kc project list --output=json`
Replace `PROJECT_DIRS` / `VALID_PROJECTS` and the project enum baked into `plan-writer` + the
`task.json` schema with **`kc project list --output=json`** (shipped in slice **079** — supersedes
the earlier "read `.kubecoder/project.yaml` directly" decision). **As built:** `load_project_dirs()`
runs `kc project list --output=json` (cwd = target repo) and parses the bare JSON array of
`{name, cwd, description}` into a name→cwd map; the cwd-resolution rule stays implemented exactly
once, in `kc` (`ResolveCwd`), and the runner needs no YAML parser — it stays stdlib-only.
`.kubecoder/project.yaml` remains the source manifest; only `kc` reads it. **New structural fact
(implementation):** the plugin's runner no longer lives inside the target repo, so `REPO_ROOT` can
no longer be derived from `__file__` — it comes from `git rev-parse --show-toplevel` at the
invocation cwd (`/dev:run-slice` runs the runner from the target code repo). An absent/malformed
manifest is a loud non-zero from `kc`, which the runner surfaces as a bail.

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
exit codes, `--resume`. So `claude_session.py` (801 ln) is **deleted**, and its ~150-line kc-native
replacement (`run_kc_session` + `_kc_send` + `_kc_session_id`) is **inlined into `task_runner.py`**
(the plugin's `tools/` ships only `task_runner.py` + `preflight.py`). The runner keeps everything
above the session boundary: the task loop, caps, consults, verdict-file validation, git management,
`state.json`, resume, exit codes. `MODELS` → `--model`; `TIMEOUTS` → a deadline the runner enforces
around `send` (on expiry it SIGINTs `send`, which fires a worker interrupt, then `end`s the session).

**Prompt-caching (as built).** The `-e NAME=VALUE` env pass-through on `kc session create-headless`
shipped in slice **079** (with a `--env` long alias; cobra `StringArray`, so a value may contain
`,`/`=`; a malformed token — no `=` or empty NAME — is a usage error, exit 2). The runner threads
`SPAWN_ENV` as `-e FORCE_PROMPT_CACHING_5M=1`.

**Session-id timing (verified against the `StatusSnapshot` contract).** `create-headless` prints the
assigned **name**; the claude **`sessionId`** is empty until the first turn completes, so the runner
reads it from `kc session status <name> --output=json` *after* `send` and records it (for `--resume`
across rounds and the transcript locator). This shifts `on_session` from init-time (old claude path)
to post-send — a narrowed window for crash-during-turn reattach, flagged in §10/§11.

### 6d. Preflight — plugin-shipped, expressed over `kc` (spec agreed 2026-07-12)
`scripts/preflight.py` (project-owned today) is replaced by one plugin-shipped, **stdlib-only**
script: `${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for triage|plan|run`. **Silent on success.** On
failure it prints one actionable message — what's missing, the exact line to add, and a pointer to
`project-contract.md` — so a new repo self-onboards from the error text. Exit codes: **0** pass,
**1** contract violation (the project must fix something), **2** environment broken (`kc` missing).
Each command runs its profile as step one and relays the message verbatim on non-zero; the runner
does **not** re-run preflight — `run-slice` is the gate.

| Check | triage | plan | run |
|---|:-:|:-:|:-:|
| `kc` on PATH | ✓ | ✓ | ✓ |
| Manifest valid: `kc project list --output=json` returns ≥1 project | – | ✓ | ✓ |
| Spec-repo entry in `CLAUDE.md`, path exists | ✓ | ✓ | ✓ |
| Testing-strategy pointer in `CLAUDE.md`, target doc exists | – | – | ✓ |
| Design-philosophy pointer in `CLAUDE.md`, target doc exists | – | – | ✓ |
| Clean working tree | – | – | ✓ |
| Baseline: `kc project build` (all projects) | – | – | ✓ |

All three `CLAUDE.md` entries **bail, not warn** — each is one line to add. They are
machine-checkable line prefixes (defined in `project-contract.md`, read by preflight and agents
alike, §5):

```
Spec repo: <path>
Slice testing strategy: <path-to-doc>
Design philosophy: <path-to-doc>
```

The baseline is `kc project build` only, always on (no skip flag). The old pytest-collection step
has no `kc` equivalent and is an accepted loss: a baseline-broken suite screams on task 1's
code-tester round, and a project that cares can put a cheap collect step in its manifest's `build`
list. Full `kc project test` is not a preflight step. **No daemon-reachability check in v1** — a
`kc status` health command is carded (Triage **#194**, "add this to the preflight when delivered");
until it lands, the first `create-headless` failure is the signal. This section becomes
`docs/preflight.md` when the plugin is built.

### 6e. Dependency ordering — resolved
`kc project` (slice 074) and `kc session` headless (slice 075) were already landed. The two
remaining gaps — **#191** (`-e NAME=VALUE` pass-through on `create-headless`) and **#192**
(`--output=json` on `kc project list`) — **both shipped in slice 079**, so the full `kc` surface the
runner/preflight call is present. The runner and preflight were written against slice 079's actual
surface (see the corrections in §6a/§6c). Still outstanding, and the reason this is not yet
end-to-end validated: **no adopting repo has a `.kubecoder/project.yaml` yet**. The operator onboards
a first repo (e.g. IoTSupport) and authors its manifest; real-slice validation (§8 phase 3) needs at
least one repo with a manifest + a live `kc` (absent from the authoring env). See §11.

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

1. **Verify the mechanics** — ✅ done. Plugin-agent discovery verified 2026-07-12 (stub-plugin test,
   §4); manifest schemas re-confirmed against the current plugin docs. The `kc` gates (#191/#192)
   landed in slice 079. Residual: one smoke test after the real marketplace install.
2. **Scaffold the plugin** — ✅ done. `plugins/dev/` + `marketplace.json` + `plugin.json`; the 6
   commands and 8 agents moved over (then adapted, phase-B commit) and the contract docs shipped.
   *End-to-end install + trivial-slice confirmation is deferred to the operator's live-test pass
   (no `kc` / no manifest in the authoring env).*
3. **Cut the three seams to `kc`** (§6a–6c): ✅ implemented. `task_runner.py` rewritten kc-native;
   `claude_session.py` retired (its replacement inlined). Written against slice 079's actual surface;
   ruff-clean and compiles. *Not yet run/validated on a real slice — the operator's pass; then
   re-measure with the workshop tools (orchestrator share should stay ~15%).*
4. **Preflight + project contract** (§6d, §5): ✅ done. `preflight.py` (profiles, exit 0/1/2, silent
   on success) + `project-contract.md` (the three line prefixes) + `preflight.md`; `triage`/`plan`
   bail on a missing spec-repo entry; `run-slice` uses the "slice testing strategy defined for this
   project" wording.
5. **Rework the AIWorkflow repo shell** (§7): ✅ done. Deleted `orchestrator/`/`project/`/`EXAMPLE.md`
   and the retired `tools/ai_workflow` scripts; **moved** `MERGING.md` → `runbooks/`; rewrote
   `README.md`, `docs/ADOPTING.md`, `docs/AUTHORING.md`; repurposed `CHANGELOG-workflow.md`; parked
   the `upkeep` backlog.
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
6. **Project map (review amendment 2026-07-12):** ✅ `kc project list --output=json` (#192) —
   supersedes the earlier direct `.kubecoder/project.yaml` read.
7. **`MERGING.md` (review amendment):** ✅ moved to `runbooks/`, not deleted — it's the monorepo-merge
   runbook with pending runs, unrelated to templates.
8. **`ux-design` command (review amendment):** ✅ deleted — unused.
9. **Preflight spec (agreed 2026-07-12):** ✅ per-command profiles, bail-not-warn contract entries as
   machine-checkable line prefixes, baseline = `kc project build` only (always on, pytest-collection
   loss accepted), no daemon check until `kc status` (#194) lands.

---

## 10. Risks / things to verify before committing

- **Plugin-agent discovery for `kc session --agent dev:<role>`** — ✅ verified 2026-07-12 (§4):
  namespaced and bare names both resolve headlessly; unknown names fail loudly (exit 1). Residual:
  one smoke test after the real marketplace install (the stub test used `--plugin-dir`).
- **Project map** — ✅ resolved and implemented: `kc project list --output=json` (slice 079; §6a).
  The cwd-resolution rule stays in `kc` only. Caveat: no adopting repo has a manifest yet — a first
  repo onboards before validation (§6e).
- **Headless prompt-caching** — ✅ resolved and implemented: `-e NAME=VALUE` pass-through on
  `kc session create-headless` (slice 079; §6c). The runner passes `-e FORCE_PROMPT_CACHING_5M=1`.
- **Crash-recovery parity** — the runner reattaches via `kc session create-headless --resume
  <sessionId>` + `status`, mirroring the old path. Caveat surfaced during implementation (§6c): the
  `sessionId` is only known post-first-turn, so a crash *mid-turn* leaves `in_flight.session` unset
  and the stage re-runs fresh (safe, but loses the crashed turn's uncommitted work) rather than
  reattaching. Confirm a killed run reattaches cleanly on the live-test pass; enhance if the
  mid-turn window matters.
- **Existing-backlog layout** — most on-disk slices still use the pre-#175 `overview.md` +
  per-project-subfolder shape; the plugin targets the `tasks/NN_slug/` layout. Backlog re-planning is
  independent of this rework but worth noting so nobody points the new runner at an old-shape slice.
- **`runner_sessions.py` / `slice_costs.py`** — see §7 Repurpose/keep: the runner must keep
  recording session-id → transcript locations under `kc session`, or the workshop goes blind. **As
  built:** `state.json`'s `history` still records `transcript` = `_transcript_path(cwd, sessionId)`
  (`~/.claude/projects/<munged-cwd>/<sessionId>.jsonl`) — an assumption to confirm live (that `kc`'s
  headless `claude` writes the transcript to the same location under the same `~/.claude`).

---

## 11. Remaining follow-ups (post-execution, for the operator's live-test pass)

The build is complete and self-consistent, but was written without a live `kc` or a real manifest.
Before relying on it, validate:

1. **Marketplace install smoke test.** `/plugin marketplace add /work/AIWorkflow`, `/plugin install
   dev@aiworkflow`, confirm `/dev:*` commands resolve and `kc session create-headless --agent
   dev:code-writer` resolves the agent headlessly (the stub test used `--plugin-dir`).
2. **First manifest.** Onboard a repo with a `.kubecoder/project.yaml` + the three `CLAUDE.md` lines;
   run `preflight.py --for run` and confirm each gate (manifest, entries, clean tree, baseline
   build) passes/fails as intended, and the failure messages read well.
3. **Runner on a trivial real slice.** Confirm `create-headless → send → status → end` drives a
   task; the `sessionId` reads back from `status --output=json`; `-e FORCE_PROMPT_CACHING_5M=1`
   reaches the spawned `claude`; timeouts SIGINT-interrupt cleanly; `--resume` chains across writer
   fix rounds; and a killed run reattaches (note the mid-turn caveat in §10).
4. **`kc project` verbs from the agents.** Confirm `code-tester`/`test-agent` running `kc project
   test|build|lint --project <name>` produces the green signal expected.
5. **Workshop still sees runs** (§10 last bullet): transcript paths recorded in `state.json` resolve.
6. **Then:** re-measure orchestrator share (~15%), and — separately, operator-owned — retire
   KubeCoder's in-repo `.claude/commands` + `.claude/agents` copies (out of scope here).
