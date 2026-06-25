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
  `canon`, `worker`/`beat`, SSE `gateway`, UAT/manuals/locales — **omit** them. (DesignAssistant
  carries all of those; these repos have none.)
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
  `backend/` for a Celery/queue runner).
- **`scripts/`**: `preflight.py`, `build-all.py`, `regenerate-openapi.py`, `_initd_log.py`
  from the template; in `build-all.py` keep only the `backend`/`frontend` steps; in
  `regenerate-openapi.py` keep only `--frontend`. Add `dev.py` (honcho launcher) if the
  template ships it.
- **Root manifests** (`pyproject.toml`, `pnpm-workspace.yaml`, `package.json`,
  `.gitignore`, `.codehealthignore`, `.dockerignore`): take the lean template versions.
  `pnpm-workspace.yaml` packages = `frontend` + `tools/code_health/cognitive`.
  `pyproject.toml` = template's lean set (honcho, pathspec, `code-health` script,
  `packages=[{include="tools"}]`) **plus** the `run-suite`/`run-suite-remote` scripts and the
  deps suite_runner needs (per DA: `portpicker`, `psutil`, `jsonschema`, `jsonpatch`). **No**
  canon dep.
- **`tools/code_health/`** copy whole (generic). **`tools/suite_runner/`** — bring it in
  (run-suite is now the validation mechanism). Source from the current AIWorkflow template if
  present, else from `../DesignAssistant/tools/suite_runner/`; set its project set to
  `backend`, `frontend` (drop `portal`).
- **Root `CLAUDE.md`**: render `orchestrator/CLAUDE.md` with the Phase-0 variables; trim the
  issue-log block to a placeholder; point "Key documentation" at `backend/` + `frontend/`
  docs only.
- Per ADOPTING Step 3: `docs/conventions.md` per subproject is project-specific — these repos
  may already have backend/frontend conventions; don't invent, just wire pointers.

Then install per ADOPTING Step 4b:
```bash
cd "$WORK/mono" && poetry install && pnpm install
poetry run code-health --help    # smoke
```
Commit the scaffolding:
```bash
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Add AIWorkflow orchestrator scaffolding"
```

---

## Phase 4 — Jenkinsfiles: 3 build → 1 (DA shape), 2 architecture kept separate

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
   `helmCharts.kaniko("frontend/Dockerfile", ".", ["registry:5000/$IMAGE_UI:<tag>"])`.
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

### 4b. Keep the two architecture pipelines separate
DA's single Jenkinsfile has **no** architecture stage — leave architecture as its own jobs.
After the merge, fix their relative paths for the new prefixes:
- Backend (generated producer): keep its Vault OIDC (`kv/jenkins/<repo>-pipeline-oidc`),
  `gen-architecture.py`, `$ARCH_API_URL`, `$ARCH_DATASET_URL`. Its body references
  `./tools/...`, `./scripts/arch-validate.py`, `docs/architecture/*.yaml` — now under
  `backend/`. Wrap the body in `dir('backend')` (or move the file to root as
  `Jenkinsfile.architecture-backend` with `backend/`-prefixed paths).
- Frontend (hand-authored): same treatment under `frontend/` →
  `Jenkinsfile.architecture-frontend`.
- The user re-points the two Jenkins architecture jobs at the new file paths (GitHub/Jenkins
  side = user's responsibility).

Commit:
```bash
git -C "$WORK/mono" rm backend/Jenkinsfile frontend/Jenkinsfile frontend/Jenkinsfile.validation
# write root Jenkinsfile + relocate/patch the two architecture files
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Consolidate CI: single Jenkinsfile; keep architecture producers separate"
```

---

## Phase 5 — Validate, then swap into place

```bash
cd "$WORK/mono"
scripts/preflight.py            # build-all + backend pytest --co + cli prepare
# optional: honcho/Procfile.dev dev session smoke
git log --oneline --graph -3   # confirm merge + scaffolding + CI commits
```
Swap the assembled monorepo into the canonical location (Phase 2 swap block):
`mv $SRC $SRC.pre-merge.bak && mv $WORK/mono $SRC`.

---

## Phase 6 — Handoff (user-owned, GitHub side)

Not done by this runbook (user said "I'll handle GitHub"):
- `git push --force origin main` to `<Repo>.git` (now the monorepo).
- Retire/archive `<Repo>UI.git`.
- Re-point Jenkins: the multibranch/build job → root `Jenkinsfile`; the two architecture jobs →
  the relocated architecture files.
- (Later, when resuming work) create `../<Repo>Specs` and the issue-log board; fill the
  deferred placeholders.

---

## Per-repo notes
- **IoTSupport** — values pre-filled in Phase 0. Stray `.llmbox/docker-compose.yml` edit in
  frontend → discard before Phase 2.
- **DHCPApp / ElectronicsInventory / ZigbeeControl** — re-derive the Phase-0 table from each
  repo's own existing Jenkinsfiles before Phase 2. Confirm each backend's dev runner (does it
  have `worker`/`beat`?) for `Procfile.dev`, and each repo's validation sidecars + suite command.
