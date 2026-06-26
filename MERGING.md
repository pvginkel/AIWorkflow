# Monorepo Merge Runbook (run once per repo)

Turns a `backend` repo (`<Repo>.git`) + `frontend` repo (`<Repo>UI.git`) into a single
history-preserving monorepo, then layers on the AIWorkflow orchestrator and a single
Jenkinsfile. Modeled on the completed `../DesignAssistant` monorepo, with the orchestrator
driven live from `../AIWorkflow/ADOPTING.md`.

**Applies to:** IoTSupport, DHCPApp, ElectronicsInventory, ZigbeeControl
(all share: `backend` = Python/Poetry clone of `<Repo>.git`; `frontend` = pnpm@9 + Playwright
clone of `<Repo>UI.git`; container folder `/home/pvginkel/source/<Repo>` with an empty
root-owned `.git` stub; both subrepos on `main`).

**Decisions baked in (from the planning Q&A):**
- Do the whole merge **locally in the backend repo**; **do not touch GitHub** — the user
  pushes and retires `<Repo>UI.git` afterward.
- **Agent placement = `ADOPTING.md` (now corrected) = the DesignAssistant layout:**
  orchestrator agents (`arch-design`, `slice-verifier`) at root `.claude/agents/`; the four
  per-stack dev agents (`code-writer/-reviewer`, `plan-writer/-reviewer`) **stay per-subproject**
  in `backend/.claude/agents/` + `frontend/.claude/agents/` (where they already are). Discovery
  walks cwd→root and merges both. The real load requirement is a **`description:` frontmatter
  field** on each agent (not placement) — verify it's present.
- **Validation uses `run-suite`** (DA's `suite_runner`), **replacing `validation-entrypoint.sh`**.
  No dedicated validation-container build anymore — validation runs on a **base image with the
  working-tree source copied in** (DA's current, working approach).
- **Tag scheme = DA:** validation runs first, so images are tagged `:<build#>` + `:latest` at
  build time; no separate post-validation promote stage.
- Orchestrator scaffolding is installed by **executing the *current* `../AIWorkflow/ADOPTING.md`**
  at run time (it will have evolved) — not copied from DesignAssistant.
- **No DTAP.** Single `Jenkinsfile`; no `Jenkinsfile.deploy-*`.
- Specs side-repo (`../<Repo>Specs`) and issue-log/Trello board are **deferred** — wire the
  path/placeholders but don't create them.

---

## Learnings from run 1 (IoTSupport) — read before starting the next repo

These bit during the IoTSupport merge and will recur on DHCPApp / ElectronicsInventory /
ZigbeeControl. Each is expanded inline in the relevant phase below; this is the index.

1. **Keep the frontend OUT of the pnpm workspace** (unless it actually imports a sibling
   workspace package). IoTSupport's frontend has no `workspace:` deps, so making it a workspace
   member (as DA does — DA's frontend needs `packages/shared-ui`) forced a fresh root lockfile
   that drifted **28/45** direct deps to newer minors (React, TanStack, Vite, eslint plugins,
   and even `ssegateway` to a different git SHA) and broke `pnpm check`. Fix: frontend stays a
   **standalone pnpm project with its own lockfile** (zero drift). The root has **no
   `pnpm-workspace.yaml`/`package.json`/lockfile**; the cognitive sidecar installs standalone.
   Check `grep -L "workspace:" <Repo>/frontend/package.json` before deciding.
2. **`suite_runner` is a real port of `validation-entrypoint.sh`, not "drop portal".** Its
   `_wait_for_services()` and per-suite steps are DA-specific. Rewrite `local.py` to mirror the
   repo's existing `validation-entrypoint.sh` flow exactly (see Phase 3).
3. **The backend needs Python 3.13** (e.g. `queue.ShutDown`) even though `backend/pyproject.toml`
   says `^3.11`. Keep DA's `HAS_PYTHON313` / `poetry env use python3.13` logic in `suite_runner`
   **and** `build-all.py` — it is NOT DA-specific. Locally the default `python3` is 3.12.
4. **`orchestrator/pyproject.toml` and the command templates use Jinja vars NOT in the ADOPTING
   Step 2 table:** `project_name_slug`, `author_name`, `author_email`, `project_root`,
   `specs_repo_absolute_path`, `subproject | title`. Derive them (Phase 0 table below).
5. **`cli prepare` may not exist.** The AIWorkflow `preflight.py` / `regenerate-openapi.py`
   assume a `poetry run cli prepare`. IoTSupport's backend has none (tests bootstrap from
   pytest fixtures). Drop the step (Phase 3); `pytest --co` is the readiness check.
6. **Gitignored local config is LOST in the merge** (fresh clones omit it). Carry forward
   `backend/.env`, `backend/.env.test` (and any `frontend/.env*`) into the merged tree — they're
   gitignored so they won't be committed, but the backend `pytest --co` and local dev need them
   (Phase 5).
7. **suite_runner deps:** only `psutil` is actually imported (process.py). `portpicker`,
   `jsonschema`, `jsonpatch` are NOT used by the suite runner — don't add them. `remote.py` /
   `run-suite-remote` is a DA-specific k8s runner; **drop it** (don't bring it in).
8. **`tar`/`mv` are same-filesystem** here (`/tmp` and `/home` are both on `/dev/sda2`), so the
   Phase-5 `mv` is a fast rename — but verify with `df` on the target repo.
9. **The SSE gateway runs from the `ssegateway` PACKAGE, never a sibling checkout.** The frontend's
   vite dev server proxies SSE to `:3102`. The gateway is already a frontend **devDependency**
   (`frontend/package.json` → `"ssegateway": "github:pvginkel/SSEGateway#stable"`, a SHA-pinned
   GitHub tarball), and **test/CI and prod already consume it that way** — the Playwright harness
   resolves the package and runs `node <entry>` per worker (`frontend/tests/support/process/servers.ts`
   `startSSEGateway`); prod runs a separately-built sidecar image (not built or bundled by this
   monorepo). So the **only** thing the merge needs to wire is the dev launcher. Mirror DA: Procfile
   line `gateway: scripts/dev-sse-gateway.sh`, and a **root** `scripts/dev-sse-gateway.sh` that
   `cd`s into `frontend/` (so Node resolves the package) and `exec node -e
   "require(require.resolve('ssegateway'))"` with `PORT` + `CALLBACK_URL` env. Get the exact port +
   callback + the precise env the gateway needs from that repo's `servers.ts` harness — DA's gateway
   needs `RABBITMQ_URL`/`RABBITMQ_ENV_PREFIX`, **IoTSupport's needs only `PORT` + `CALLBACK_URL`**.
   ⚠️ **Do NOT follow `backend/.vscode/tasks.json`'s "SSE Gateway" task** — it (and
   `backend/scripts/dev-sse-gateway.sh`) shell into a `../../SSEGateway` sibling clone via
   `SSE_GATEWAY_ROOT`/`run-gateway.sh`. That sibling-checkout path is the wart; **delete** the
   backend script + that task. Also delete any orphaned package-based `frontend/scripts/dev-sse-gateway.sh`
   (stale duplicate). Expand inline in Phase 3 (`Procfile.dev` bullet). Smoke-test: the launcher
   should boot on the gateway port and answer `GET /readyz` with 200.

---

## Phase 0 — Per-repo inputs

Fill these before starting. Values you don't know are **derived at run time** by reading the
repo's *existing* `backend/Jenkinsfile*` and `frontend/Jenkinsfile*`.

| Variable | IoTSupport (known) | How to get it for the other 3 |
|---|---|---|
| `REPO` | `IoTSupport` | the folder / backend repo name |
| `BACKEND_URL` | `https://github.com/pvginkel/IoTSupport.git` | `git -C <Repo>/backend remote get-url origin` |
| `FRONTEND_URL` | `https://github.com/pvginkel/IoTSupportUI.git` | `git -C <Repo>/frontend remote get-url origin` |
| `IMAGE_APP` | `iotsupport-app` | from `backend/Jenkinsfile` kaniko tag |
| `IMAGE_UI` | `iotsupport-ui` | from `frontend/Jenkinsfile` kaniko tag |
| `VALIDATION_VAULT` | `kv/jenkins/keycloak-iotsupport-admin` | from `frontend/Jenkinsfile.validation` `withVault` |
| `VALIDATION_SIDECARS` | `minio`, `opensearch` | from `frontend/Jenkinsfile.validation` Job YAML |
| `S3_BUCKET` | `iot-support-validation` | from `frontend/Jenkinsfile.validation` env |
| `ARCH_BACKEND_KIND` | **generated** (Vault OIDC + `gen-architecture.py`) | read `backend/Jenkinsfile.architecture` header |
| `ARCH_FRONTEND_KIND` | **hand-authored** | read `frontend/Jenkinsfile.architecture` header |
| `ARCH_API_URL` / `ARCH_DATASET_URL` | `https://iot.ginbov.nl` / `architecture.webathome.org/...` | from `backend/Jenkinsfile.architecture` |

AIWorkflow `ADOPTING.md` variable values (Step 2 table in that file):

| ADOPTING var | Value |
|---|---|
| `project_name` / `project_short` | `<Repo>` |
| `project_tagline` | one line — lift from existing `backend/CLAUDE.md` / README |
| `specs_repo_path` | `../<Repo>Specs` (placeholder; not created now) |
| `subproject` | `backend`, then `frontend` |
| `session_manager_path` | `tools/ai_workflow/claude_session.py` |
| `notification_script` | `tools/ai_workflow/send_message.py` (env-var version, not DA's hardcoded one) |
| `check_command` | backend `poetry run check` · frontend `pnpm run check` |
| `test_command` | backend `poetry run pytest` · frontend `pnpm exec playwright test` |
| `full_suite_command` | `poetry run run-suite` (suite_runner — replaces validation-entrypoint.sh) |
| `regen_api_command` | `scripts/regenerate-openapi.py --frontend` |
| `issue_log_url` | placeholder (no board yet) |
| `subproject_names` | `"backend", "frontend"` |
| `external_projects` | `{}` |

**Vars NOT in ADOPTING's Step 2 table but present in `orchestrator/pyproject.toml` + command
templates — derive these too:**

| var | Where | Value (IoTSupport) |
|---|---|---|
| `project_name_slug` | `pyproject.toml` `[tool.poetry] name` | `iot-support` (match `backend/pyproject.toml` name) |
| `author_name` / `author_email` | `pyproject.toml` authors | `Pieter van Ginkel` / `pvginkel@gmail.com` (from git config / backend pyproject) |
| `project_root` | commands (`run-slice`, `triage`, `quality-improver`) | the **final** repo path `/home/pvginkel/source/<Repo>` (NOT the temp `$WORK`) |
| `specs_repo_absolute_path` | commands | `/home/pvginkel/source/<Repo>Specs` (absolute form of `specs_repo_path`) |
| `subproject \| title` | `run-slice` | title-case: `Backend` / `Frontend` |

---

## Phase 1 — Pre-flight safety

```bash
REPO=IoTSupport
SRC=/home/pvginkel/source/$REPO
WORK=$(mktemp -d /tmp/monorepo-$REPO.XXXX)

# 1. Both subrepos must be clean & pushed (merge clones fresh from origin, so any
#    uncommitted/unpushed work would be LOST). Stash or commit strays first.
for s in backend frontend; do
  echo "== $s =="; git -C "$SRC/$s" status --porcelain
  git -C "$SRC/$s" rev-list --count @{u}..HEAD   # must be 0
done
# Known: IoTSupport/frontend has a stray .llmbox/docker-compose.yml edit — stash/discard it.

# 2. Tooling present
git filter-repo --version >/dev/null && gh --version >/dev/null
```

If anything is dirty/unpushed and the user wants it kept, commit+push (or carry it forward
manually after the merge). **Stop and ask** rather than discarding real work.

---

## Phase 2 — History-preserving merge (→ monorepo on `main`)

Fresh clones from origin guarantee `filter-repo` runs cleanly and the result is reproducible.

```bash
# Backend becomes the monorepo; its history moves under backend/
git clone "$BACKEND_URL" "$WORK/mono"
git -C "$WORK/mono" filter-repo --to-subdirectory-filter backend --force

# Frontend history moves under frontend/
git clone "$FRONTEND_URL" "$WORK/fe"
git -C "$WORK/fe" filter-repo --to-subdirectory-filter frontend --force

# Unrelated-histories merge
git -C "$WORK/mono" remote add fe "$WORK/fe"
git -C "$WORK/mono" fetch fe
git -C "$WORK/mono" merge --allow-unrelated-histories --no-edit \
    -m "Merge frontend repo (${REPO}UI) into monorepo under frontend/" fe/main
git -C "$WORK/mono" remote remove fe
```

Verify:
```bash
git -C "$WORK/mono" log --oneline --graph --max-count=5         # one merge commit, two parents
git -C "$WORK/mono" log --oneline -- backend/pyproject.toml | tail -1   # reaches backend's first commit
git -C "$WORK/mono" log --oneline -- frontend/package.json   | tail -1   # reaches frontend's first commit
ls "$WORK/mono"   # backend/  frontend/
```

`filter-repo` strips `origin`. Re-point it at the backend repo so the user can push:
```bash
git -C "$WORK/mono" remote add origin "$BACKEND_URL"
```

> After Phases 3–4 finish, swap the assembled monorepo into place:
> ```bash
> mv "$SRC" "${SRC}.pre-merge.bak"   # keeps the old two-clone container as backup
> mv "$WORK/mono" "$SRC"
> ```
> The forked dev agents in `backend/.claude/` and `frontend/.claude/` ride along
> automatically (they were committed in each subrepo) — nothing to do for them (mirrors DA).

---

## Phase 3 — Orchestrator (execute AIWorkflow/ADOPTING.md)

**Source of truth: `/home/pvginkel/source/AIWorkflow/ADOPTING.md` as it exists at run time.**
Re-read it fresh; do not assume this runbook's snapshot. Apply its Step 1 copy-map and Step 2
variable substitution against `$WORK/mono` (the monorepo root), with these project-specific
adjustments:

- **Subprojects = `backend`, `frontend` only.** Wherever ADOPTING/DA reference `portal`,
  `canon`, `worker`/`beat`, a gateway *subproject/workspace package*, UAT/manuals/locales —
  **omit** them. (DesignAssistant carries all of those; these repos have none.) *Note:* the SSE
  gateway is still wired as a Procfile **service** — but from the `ssegateway` package, not as a
  subproject (Learning #9). "Omit the gateway subproject" ≠ "no gateway".
- **Agent placement — straight from ADOPTING.md (corrected):** orchestrator agents
  (`arch-design`, `slice-verifier`) → root `.claude/agents/`; the four per-stack dev agents stay
  per-subproject (they already exist in `backend/.claude/agents/` + `frontend/.claude/agents/`
  from the original repos — nothing to move). Discovery merges cwd→root. **Verify each dev
  agent carries a `description:` frontmatter field** — that, not placement, is what makes Claude
  Code register it (name-only agents silently fall back to `general-purpose`).
- **AI-workflow helpers go in `tools/ai_workflow/`** (current template layout), not `scripts/`
  (DA's older layout). Use the template's **env-var** `send_message.py`
  (`HA_URL`/`HA_TOKEN`/`HA_NOTIFY_SERVICE`), not DA's hardcoded notifier.
- **`Procfile.dev`** (author per ADOPTING Step 4 note): keep only the lines that match this
  backend (start from DA's `backend: cd backend && … poetry run dev` and `frontend: cd frontend
  && pnpm dev`; add `worker`/`beat` **only if** this backend actually has them — check
  `backend/` for a Celery/queue runner). ⚠️ **SSE gateway (Learning #9):** the frontend's vite
  proxy expects an SSE gateway on :3102, served by the **`ssegateway` package** — already a frontend
  devDependency (`frontend/package.json`, `github:pvginkel/SSEGateway#stable`), already used by the
  Playwright harness and the prod sidecar. Wire dev only: add `gateway:  scripts/dev-sse-gateway.sh`
  to the Procfile and **bring DA's root `scripts/dev-sse-gateway.sh`**, which `cd`s into `frontend/`
  and `exec node -e "require(require.resolve('ssegateway'))"`. Two per-repo adjustments:
  - **Port + callback + env** — copy them from the repo's `frontend/tests/support/process/servers.ts`
    `startSSEGateway` (the authoritative, working invocation). DA exports `RABBITMQ_URL`/
    `RABBITMQ_ENV_PREFIX`; **IoTSupport needs only `PORT=3102` + `CALLBACK_URL=http://localhost:3101/api/sse/callback`**.
  - **Cleanup (Learning #9):** the original backend ships sibling-checkout cruft — delete
    `backend/scripts/dev-sse-gateway.sh` and the `backend/.vscode/tasks.json` "SSE Gateway" task
    (both shell into `../../SSEGateway` via `SSE_GATEWAY_ROOT`/`run-gateway.sh`), plus any orphaned
    `frontend/scripts/dev-sse-gateway.sh`. Trim every `.vscode/tasks.json` down to just the `Claude`
    task. Smoke-test the launcher: it should boot on :3102 and answer `GET /readyz` with 200.
- **`scripts/`**: `preflight.py`, `build-all.py`, `regenerate-openapi.py`, `_initd_log.py`
  from the template. In `build-all.py`: steps = root `poetry install`, backend `poetry install`,
  **frontend `pnpm install` (cwd=`frontend`)**, frontend `pnpm build` — plus a conditional
  `poetry env use python3.13` step for the backend (Learning #3). In `regenerate-openapi.py`
  keep only `--frontend`. ⚠️ **`cli prepare` (Learning #5):** both `preflight.py` and
  `regenerate-openapi.py` call `poetry run cli prepare`; IoTSupport's backend has no such
  command, so **remove that step** — `pytest --co` is the harness-readiness check, and
  `regenerate-openapi.py` just starts the backend directly. The template ships no `dev.py`;
  bring **`../DesignAssistant/scripts/dev.py`** (a honcho launcher for `Procfile.dev` — PTY for
  colors, `unshare --user --pid --fork` for clean child cleanup, per-service `logs/*.log`). It's
  project-agnostic; only adjust the docstring's `-e <service>` example to a real service. Also
  bring **`../DesignAssistant/scripts/dev-sse-gateway.sh`** when the repo has an SSE gateway
  (Learning #9) — keep its `cd frontend && exec node -e "require(require.resolve('ssegateway'))"`
  shape; only adjust the exported env (`PORT`/`CALLBACK_URL`, and broker vars iff the repo's
  `servers.ts` sets them).
- **Root manifests** — ⚠️ **corrected from run 1.** Take `pyproject.toml`, `.gitignore`,
  `.codehealthignore`, `.dockerignore`. **Do NOT create a root `pnpm-workspace.yaml` /
  `package.json` / `pnpm-lock.yaml`** unless the frontend genuinely imports a sibling workspace
  package (it doesn't on these repos — verify with `grep "workspace:" frontend/package.json`).
  Making the frontend a workspace member regenerates its lockfile and drifts ~28/45 deps,
  breaking `pnpm check` (see Learning #1). Instead the **frontend stays standalone** (keeps its
  own `frontend/pnpm-lock.yaml` and `packageManager` pin — do not touch them), and the
  `tools/code_health/cognitive` sidecar installs standalone (`cd tools/code_health/cognitive &&
  pnpm install`; code-health degrades gracefully without it).
  `pyproject.toml` = template's lean set (honcho, pathspec, `code-health` script,
  `packages=[{include="tools"}]`) **plus** the `run-suite` script and **`psutil`** (the only dep
  `suite_runner` actually imports). **Do NOT add** `portpicker`/`jsonschema`/`jsonpatch`
  (unused) or `run-suite-remote` (DA's k8s remote runner — dropped). **No** canon dep.
- **`tools/code_health/`** copy whole (generic, incl. the `cognitive/` TS sidecar). **
  `tools/suite_runner/`** — ⚠️ **bigger than "drop portal" (Learning #2).** Copy
  `__init__.py` (set `ALL_SUITES = ["backend", "frontend"]`), `display.py`, `process.py` as-is
  from `../DesignAssistant/tools/suite_runner/`. **Do NOT copy `remote.py`** (DA k8s runner).
  **Rewrite `local.py`** to mirror this repo's existing `frontend/scripts/validation-entrypoint.sh`
  flow, keeping the suite-runner infra (output modes, JUnit→`SUITE_RESULT` markers, `_run_cmd`/
  `_install_cmd`, summary). The IoTSupport flow was: backend install → wait for sidecars → backend
  `pytest` → frontend `pnpm install` → `pnpm build` → `pnpm playwright install chromium` →
  `pnpm playwright test`. Specifics that bit:
  - **No vitest** (DA runs vitest+build-fast; IoTSupport frontend has neither — only `pnpm build`).
  - **Python 3.13**: keep DA's `HAS_PYTHON313` / `poetry env use python3.13` before backend
    install (Learning #3). NOT DA-specific.
  - **Service wait**: delegate to the repo's existing `wait-for-services.py` via the **backend
    venv** (`poetry run python frontend/scripts/wait-for-services.py`, cwd=backend — it needs
    `boto3`, which is a backend dep). Gate it on `S3_ENDPOINT_URL` so local runs without sidecars
    skip it. Keep `wait-for-services.py`; only `validation-entrypoint.sh` is retired.
  - **Frontend install runs in `frontend/`** (`cwd=frontend`), not the repo root, since the
    frontend is standalone (see root-manifests note). Resolve the per-repo sidecar set, env
    block, and pytest/playwright flags from the repo's own `Jenkinsfile.validation`.
- **Root `CLAUDE.md`**: render `orchestrator/CLAUDE.md` with the Phase-0 variables; trim the
  issue-log block to a placeholder; point "Key documentation" at `backend/` + `frontend/`
  docs only.
- Per ADOPTING Step 3: `docs/conventions.md` per subproject is project-specific — these repos
  may already have backend/frontend conventions; don't invent, just wire pointers.

Then install per ADOPTING Step 4b (⚠️ no root `pnpm install` — there's no root workspace; the
frontend and cognitive sidecar install standalone):
```bash
cd "$WORK/mono" && poetry install                              # root tools (code-health, run-suite)
( cd frontend && pnpm install --frozen-lockfile )             # standalone, own lockfile
( cd tools/code_health/cognitive && pnpm install )            # TS sidecar for code-health
poetry run code-health --help                                 # smoke
poetry run run-suite --help                                   # smoke (suite_runner imports cleanly)
```
Commit the scaffolding:
```bash
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Add AIWorkflow orchestrator scaffolding"
```

---

## Phase 4 — Jenkinsfiles: 3 build → 1 (DA shape), 2 architecture → 1 combined

### 4a. Single root `Jenkinsfile`
Model structure on `../DesignAssistant/Jenkinsfile`, **adopt DA's validation flow** (validate
the working tree first, then build, then deploy), trimmed to backend+frontend. Target stages:

1. `Cloning repo` — `checkout scm`; capture branch + gitRev.
2. `Run validation` — tar the **whole monorepo working tree**; `withVault` on
   `$VALIDATION_VAULT`; stand up the inline k8s `Job` on a **base image** (no validation-
   container build) with **only this repo's sidecars** (`$VALIDATION_SIDECARS`, e.g. minio +
   opensearch — drop DA's rabbitmq/pgvector/document-conversion); copy the source in, then
   `poetry install` + `poetry run run-suite --output-mode full --junitxml-dir … --retries …`
   (DA pattern, **replacing `validation-entrypoint.sh`**); parse `===SUITE_RESULT:` markers for
   backend + frontend; collect `validation.log` + JUnit; `kubectl.deleteJob` in `finally`.
   Playwright image resolved from `frontend/pnpm-lock.yaml` as today.
3. `Building <app>` — `helmCharts.kaniko("backend/Dockerfile", "backend", ["registry:5000/$IMAGE_APP:<tag>"])`.
4. `Building <app>-frontend` — write `frontend/git-rev`;
   `helmCharts.kaniko("frontend/Dockerfile", "frontend", ["registry:5000/$IMAGE_UI:<tag>"])`.
   ⚠️ **Context is `frontend`, not `.`** (Learning #1): because the frontend stays a standalone
   pnpm project, its **Dockerfile is unchanged** (builds from the `frontend/` context with its
   own lockfile) — no workspace-aware rewrite needed. Resolve the Playwright base-image tag from
   `frontend/pnpm-lock.yaml` (step 2). Backend image: `kaniko("backend/Dockerfile", "backend", …)`
   unchanged (self-contained). Also `git rm frontend/scripts/validation-entrypoint.sh` in this
   phase (run-suite replaces it) — but **keep `wait-for-services.py`** (run-suite calls it).
5. `Deploy Helm charts` — `cicd.helmDeploy()`.

**Tag scheme (no DTAP):** bare `${currentBuild.number}` + `latest`. Because validation now
runs *before* the build (DA order), tag `latest` directly at build time — no separate
post-validation `crane` promote stage needed. (If "only promote what passed" matters, keep a
trailing promote stage instead; default = tag at build.)

**Drop entirely** vs the old split files: `*-build.json` artifacts, `archiveArtifacts` handoff,
`build job: 'Validation'`, `copyArtifacts`, the second source re-clone-by-gitRev, the
`BACKEND_BUILD`/`FRONTEND_BUILD`/`TRIGGERED_BY` params, and the GitHub clone credential. All
keep `library identifier: 'JenkinsPipelineUtils', changelog: false`. Per-repo substitutions:
registry/image names, `$VALIDATION_VAULT`, `$S3_BUCKET`, the validation env block, job-name
prefix, base image, `run-suite` flags.

### 4b. One combined `Jenkinsfile.architecture` (operator preference)
DA's single Jenkinsfile has **no** architecture stage — architecture stays its own job. The
operator prefers a **single** architecture job (not one per producer), so fold both producers
into one root `Jenkinsfile.architecture` with a stage per producer, sharing one `python` pod:
- One `withVault` (backend OIDC `kv/jenkins/<repo>-pipeline-oidc`) → `podTemplate(python)` →
  `node` → `stage('Cloning repo'){ checkout scm }`.
- **Generate backend architecture** — `dir('backend'){ container('python'){ pip install -r
  ./tools/requirements.txt; gen-architecture.py (with `$ARCH_API_URL`/`$ARCH_DATASET_URL`) } }`.
- **Validate backend architecture** — `dir('backend'){ container('python'){ arch-validate.py
  docs/architecture/architecture.yaml docs/architecture/deployed-architecture.yaml } }` +
  top-level `archiveArtifacts 'backend/docs/architecture/architecture.yaml,…/deployed-architecture.yaml'`.
- **Validate frontend architecture** — `dir('frontend'){ container('python'){ arch-validate.py
  docs/architecture/*.yaml } }` + top-level `archiveArtifacts 'frontend/docs/architecture/*.yaml'`.
  (The backend stage's `pip install` runs first in the same pod, so the frontend stage has those
  deps too — matching the original frontend job, which ran `arch-validate.py` with no install.)
- The operator re-points **one** Jenkins architecture job at `Jenkinsfile.architecture`.
  Artifacts stay separate per producer; combining is purely a job consolidation.
- ⚠️ **`dir()` + `archiveArtifacts` gotcha:** `dir('backend')` only changes the cwd for `sh`
  steps. `archiveArtifacts`/`junit` globs are resolved **workspace-root-relative** regardless of
  the enclosing `dir()`. So keep `checkout scm` and `archiveArtifacts` at the top level and
  **prefix the artifact globs** (`backend/docs/architecture/*.yaml`), wrapping only the
  `container('python') { sh … }` steps in `dir('backend')`. (Run 1 used this structure across
  both producers' stages in one `Jenkinsfile.architecture`.)

Commit:
```bash
git -C "$WORK/mono" rm backend/Jenkinsfile frontend/Jenkinsfile frontend/Jenkinsfile.validation \
    backend/Jenkinsfile.architecture frontend/Jenkinsfile.architecture \
    frontend/scripts/validation-entrypoint.sh
# write root Jenkinsfile + the combined Jenkinsfile.architecture; update frontend Dockerfile only
# if the frontend is a workspace member (it isn't on these repos — see 4a step 4)
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Consolidate CI: single Jenkinsfile + single Jenkinsfile.architecture"
```

---

## Phase 5 — Validate, then swap into place

```bash
cd "$WORK/mono"

# ⚠️ Carry forward gitignored local config (Learning #6) — fresh clones omit it, but the
# backend's pytest --co (and local dev) need it. These stay gitignored (not committed).
for f in backend/.env backend/.env.test frontend/.env frontend/.env.test; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$WORK/mono/$f"
done

python3 scripts/preflight.py    # build-all (+py3.13 backend) + backend pytest --co
# optional: honcho/Procfile.dev dev session smoke
git log --oneline --graph -3   # confirm merge + scaffolding + CI commits
```
`preflight.py` is silent on success (exit 0). Expect failures if: python3.13 isn't picked up
for the backend (Learning #3), or `backend/.env.test` is missing (the S3_* keys — Learning #6).

Swap the assembled monorepo into the canonical location (Phase 2 swap block):
`mv $SRC $SRC.pre-merge.bak && mv $WORK/mono $SRC`. (`/tmp` and `/home` are the same filesystem
here, so this is a fast rename — confirm with `df`.) The carried-forward `.env*` files ride along
in the working tree; the rest of the old clone is preserved in `$SRC.pre-merge.bak`.

⚠️ **Re-run the Poetry installs at the final path after the swap.** Poetry keys its venvs by
**project path**, so the venvs created during the pre-swap preflight (under `$WORK`) are orphaned
once the repo moves — the next `poetry run …` at `$SRC` silently makes an empty venv and "command
not found" (honcho, etc.). pnpm `node_modules` is in-tree and survives. Fix:
```bash
cd "$SRC" && poetry install --no-interaction
( cd backend && poetry env use python3.13 && poetry install --no-interaction )
```

---

## Phase 6 — Handoff (user-owned, GitHub side)

Not done by this runbook (user said "I'll handle GitHub"):
- `git push --force origin main` to `<Repo>.git` (now the monorepo).
- Retire/archive `<Repo>UI.git`.
- Re-point Jenkins: the multibranch/build job → root `Jenkinsfile`; the (single) architecture
  job → root `Jenkinsfile.architecture`.
- (Later, when resuming work) create `../<Repo>Specs` and the issue-log board; fill the
  deferred placeholders.

---

## Per-repo notes
- **IoTSupport** — ✅ **DONE (run 1).** Merged monorepo at `/home/pvginkel/source/IoTSupport`
  (old clones in `IoTSupport.pre-merge.bak`); commits: merge → scaffolding → CI → cli-adaptation
  → frontend-out-of-workspace/py3.13 → combined-Jenkinsfile.architecture. Not pushed (Phase 6 = user). Discarded the stray
  `.llmbox/docker-compose.yml` edit before Phase 2. Backend needed py3.13; frontend kept
  standalone; no `cli prepare`; carried forward `backend/.env`+`.env.test`. Procfile.dev =
  backend+frontend+`gateway` (`gateway: scripts/dev-sse-gateway.sh` — clean-exec root wrapper
  mirroring DA that runs the `ssegateway` **package** via `node`, no sibling checkout; no
  worker/beat). Deleted the sibling-checkout cruft (`backend/scripts/dev-sse-gateway.sh` + its
  `backend/.vscode/tasks.json` "SSE Gateway" task, orphaned `frontend/scripts/dev-sse-gateway.sh`)
  and trimmed all `.vscode/tasks.json` to just `Claude`.
- **DHCPApp / ElectronicsInventory / ZigbeeControl** — re-derive the Phase-0 table from each
  repo's own existing Jenkinsfiles before Phase 2. **Per-repo checks (from run-1 learnings):**
  - `grep "workspace:" <Repo>/frontend/package.json` → if empty, keep frontend standalone (no
    root workspace) per Learning #1.
  - Backend Python: `grep -rn "queue import.*ShutDown\|3.13" <Repo>/backend` and the backend
    `Dockerfile` base — if it needs 3.13, keep the `python3.13` pinning.
  - `grep -rn "prepare" <Repo>/backend/app/cli.py` (+ `register_cli_commands`) → if no `prepare`,
    drop it from `preflight.py`/`regenerate-openapi.py` (Learning #5).
  - Read the repo's `frontend/scripts/validation-entrypoint.sh` (+ `wait-for-services.py`) — it
    is the spec for the `suite_runner` `local.py` rewrite and the Jenkinsfile sidecars/env.
  - List gitignored `.env*` in both subprojects to carry forward (Learning #6).
  - Confirm the backend dev runner (`worker`/`beat`?) for `Procfile.dev`.
  - SSE gateway (Learning #9): `grep ssegateway <Repo>/frontend/package.json`. If present, add
    `gateway: scripts/dev-sse-gateway.sh` + bring DA's root script (runs the **package** via
    `node`); copy the port/callback/env from `frontend/tests/support/process/servers.ts`. Then
    delete the sibling-checkout cruft: `backend/scripts/dev-sse-gateway.sh`, the
    `backend/.vscode/tasks.json` "SSE Gateway" task, any orphaned `frontend/scripts/dev-sse-gateway.sh`;
    trim every `.vscode/tasks.json` to just `Claude`.
