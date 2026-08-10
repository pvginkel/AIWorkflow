---
name: merge-repos
description: Turn a backend repo plus its separate UI repo into one history-preserving monorepo, consolidate its Jenkinsfiles and its two architecture producers into one each, and onboard the result onto the dev pipeline. Run once per repo; the last runs are DHCPApp, ElectronicsInventory, ZigbeeControl.
argument-hint: <Repo>
---

# Merge Repos

Turn `<Repo>.git` (a Python/Poetry backend) + `<Repo>UI.git` (a pnpm + Playwright frontend) into a
single history-preserving monorepo, consolidate three Jenkinsfiles into one, and hand the result to
`/dev:onboard`. Modeled on `../DesignAssistant`, the monorepo that already has this shape — it is
the source for the project scaffolding below, and worth reading when this skill is ambiguous.

**Run once per repo.** IoTSupport is done. What is left is **DHCPApp**, **ElectronicsInventory**,
**ZigbeeControl** — each has an issue-tracker card carrying its own Phase-0 findings. When the last
one lands, delete this skill; it has no second use.

**Decisions baked in:**

- The whole merge happens **locally, in a temp clone**; nothing touches GitHub. The operator pushes
  and retires `<Repo>UI.git` afterward (Phase 6).
- **No DTAP.** One `Jenkinsfile`; no `Jenkinsfile.deploy-*`.
- The merged repo **becomes a KubeCoder project** — it gets a `.kubecoder/project.yaml` and joins
  the pipeline through `/dev:onboard` (Phase 3). The `dev` plugin is kc-native and has no non-`kc`
  fallback, so this is a precondition, not a detail.

**Stop and ask** at anything that would discard real work. Phases 1 and 5 both touch un-pushed and
gitignored files, and a merge is not the place to be brave.

## Learnings from run 1 (IoTSupport)

These bit once and will bite again. Each is expanded inline in its phase; this is the index.

1. **Keep the frontend OUT of the pnpm workspace** unless it genuinely imports a sibling workspace
   package. IoTSupport's frontend has no `workspace:` deps; making it a workspace member (as
   DesignAssistant does — DA's frontend needs `packages/shared-ui`) forced a fresh root lockfile
   that drifted **28 of 45** direct deps to newer minors and broke `pnpm check`. The frontend stays
   a **standalone pnpm project with its own lockfile**; the root gets no `pnpm-workspace.yaml`,
   `package.json`, or lockfile. Check `grep "workspace:" <Repo>/frontend/package.json` first.
2. **`suite_runner` is a real port of `validation-entrypoint.sh`, not "drop portal".** Its
   `_wait_for_services()` and per-suite steps are DA-specific. Rewrite `local.py` to mirror this
   repo's own `validation-entrypoint.sh` flow exactly (Phase 3).
3. **The backend may need Python 3.13** (e.g. `queue.ShutDown`) even where `backend/pyproject.toml`
   says `^3.11` — the default `python3` here is 3.12. Keep DA's `HAS_PYTHON313` /
   `poetry env use python3.13` logic. It is not DA-specific.
4. **`cli prepare` may not exist.** DA's `preflight.py` / `regenerate-openapi.py` assume a
   `poetry run cli prepare`; IoTSupport's backend has none (tests bootstrap from pytest fixtures).
   Drop the step — `pytest --co` is the readiness check.
5. **Gitignored local config is LOST in the merge** — fresh clones omit it. Carry `backend/.env`,
   `backend/.env.test`, any `frontend/.env*` forward into the merged tree (Phase 5). They stay
   gitignored; the backend's `pytest --co` and local dev need them.
6. **`suite_runner` deps:** only `psutil` is actually imported (`process.py`). `portpicker`,
   `jsonschema`, `jsonpatch` are **not** used — don't add them. `remote.py` / `run-suite-remote` is
   DA's k8s runner; drop it.
7. **`tar`/`mv` are same-filesystem** here, so the Phase-5 `mv` is a fast rename — but verify with
   `df` against the target path before relying on it.
8. **The SSE gateway runs from the `ssegateway` PACKAGE, never a sibling checkout.** It is already a
   frontend devDependency (`github:pvginkel/SSEGateway#stable`), and the Playwright harness and the
   prod sidecar already consume it that way — so the **only** thing the merge wires is the dev
   launcher. ⚠️ Do **not** follow `backend/.vscode/tasks.json`'s "SSE Gateway" task: it shells into
   a `../../SSEGateway` sibling clone via `SSE_GATEWAY_ROOT`. That sibling path is the wart. Details
   in Phase 3.
9. **One repo publishes ONE architecture producer** — not one per subrepo. Run 1 consolidated the
   two architecture *jobs* but left the frontend artifact declaring `producer: <repo>-ui`, and never
   touched `Architecture.git`'s producer registry. That broke the Architecture pipeline, and it went
   unnoticed for **six weeks** because the merged job was independently red the whole time. Phase 4c
   is the full checklist; Phase 6 carries the operator-owned half.

## Phase 0 — Per-repo inputs

Derive these by reading the repo's **existing** `backend/Jenkinsfile*` and `frontend/Jenkinsfile*`.
The repo's card holds what run 1 already worked out for it.

| Variable | How to get it | IoTSupport (worked example) |
|---|---|---|
| `REPO` | the folder / backend repo name | `IoTSupport` |
| `BACKEND_URL` | `git -C <Repo>/backend remote get-url origin` | `…/IoTSupport.git` |
| `FRONTEND_URL` | `git -C <Repo>/frontend remote get-url origin` | `…/IoTSupportUI.git` |
| `IMAGE_APP` / `IMAGE_UI` | the kaniko tags in each `Jenkinsfile` | `iotsupport-app` / `iotsupport-ui` |
| `VALIDATION_VAULT` | `frontend/Jenkinsfile.validation` `withVault` | `kv/jenkins/keycloak-iotsupport-admin` |
| `VALIDATION_SIDECARS` | `frontend/Jenkinsfile.validation` Job YAML | `minio`, `opensearch` |
| `S3_BUCKET` | `frontend/Jenkinsfile.validation` env | `iot-support-validation` |
| `ARCH_BACKEND_KIND` / `ARCH_FRONTEND_KIND` | each `Jenkinsfile.architecture` header | generated (Vault OIDC) / hand-authored |
| `ARCH_API_URL` / `ARCH_DATASET_URL` | `backend/Jenkinsfile.architecture` | `https://iot.ginbov.nl` / `architecture.webathome.org/…` |

Per-repo checks to run before Phase 2 (all from the learnings):

```bash
grep "workspace:" <Repo>/frontend/package.json            # empty → frontend stays standalone (#1)
grep -rn "queue import.*ShutDown\|3.13" <Repo>/backend    # → keep the python3.13 pinning (#3)
grep -rn "prepare" <Repo>/backend/app/cli.py              # absent → drop the `cli prepare` step (#4)
ls -a <Repo>/backend/.env* <Repo>/frontend/.env*          # → carry forward (#5)
grep ssegateway <Repo>/frontend/package.json              # present → wire the dev launcher (#8)
```

Also read the repo's `frontend/scripts/validation-entrypoint.sh` (+ `wait-for-services.py`) — it is
the spec for the `suite_runner` `local.py` rewrite and for the Jenkinsfile's sidecars and env. And
confirm whether the backend has a `worker`/`beat` runner for `Procfile.dev`.

## Phase 1 — Pre-flight safety

```bash
REPO=<Repo>
SRC=/work/$REPO
WORK=$(mktemp -d /tmp/monorepo-$REPO.XXXX)

# Both subrepos must be clean AND pushed: the merge clones fresh from origin, so anything
# uncommitted or unpushed is LOST.
for s in backend frontend; do
  echo "== $s =="; git -C "$SRC/$s" status --porcelain
  git -C "$SRC/$s" rev-list --count @{u}..HEAD   # must be 0
done

git filter-repo --version >/dev/null && gh --version >/dev/null   # tooling
```

Anything dirty or unpushed: **stop and ask.** Commit and push it, or carry it forward by hand after
the merge — never discard it to get moving.

## Phase 2 — History-preserving merge

Fresh clones from origin, so `filter-repo` runs clean and the result is reproducible.

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

# filter-repo strips origin; re-point it at the backend repo so the operator can push (Phase 6)
git -C "$WORK/mono" remote add origin "$BACKEND_URL"
```

Verify:

```bash
git -C "$WORK/mono" log --oneline --graph --max-count=5           # one merge commit, two parents
git -C "$WORK/mono" log --oneline -- backend/pyproject.toml | tail -1   # reaches backend's first commit
git -C "$WORK/mono" log --oneline -- frontend/package.json   | tail -1   # reaches frontend's first commit
ls "$WORK/mono"                                                   # backend/  frontend/
```

## Phase 3 — Scaffolding, then onboard

Two halves, in this order: the project scaffolding the repo needs to build and test itself, then the
pipeline. `/dev:onboard` demands a green baseline, so it cannot run first.

### 3a. Project scaffolding — from `../DesignAssistant`

DesignAssistant is the source for all of it. Take:

- **`tools/suite_runner/`** — `__init__.py` (set `ALL_SUITES = ["backend", "frontend"]`),
  `display.py`, `process.py` as-is. **Not** `remote.py` (learning #6). **Rewrite `local.py`** to
  mirror this repo's `validation-entrypoint.sh` (learning #2). IoTSupport's flow was: backend
  install → wait for sidecars → backend `pytest` → frontend `pnpm install` → `pnpm build` →
  `pnpm playwright install chromium` → `pnpm playwright test`. Specifics that bit:
  - **No vitest** unless the repo has it (DA runs vitest + build-fast; IoTSupport had neither).
  - **Python 3.13**: keep DA's `HAS_PYTHON313` / `poetry env use python3.13` before the backend
    install (learning #3).
  - **Service wait**: delegate to the repo's own `wait-for-services.py` via the **backend** venv
    (`poetry run python frontend/scripts/wait-for-services.py`, cwd=`backend` — it needs `boto3`, a
    backend dep). Gate it on `S3_ENDPOINT_URL` so local runs without sidecars skip it. Keep
    `wait-for-services.py`; only `validation-entrypoint.sh` retires.
  - **Frontend install runs in `frontend/`** (cwd), not the root — the frontend is standalone.
- **`Procfile.dev` + `scripts/dev.py`** — DA's honcho launcher (PTY for colors,
  `unshare --user --pid --fork` for clean child cleanup, per-service `logs/*.log`). It is
  project-agnostic; only fix the docstring's `-e <service>` example. Keep only the Procfile lines
  this backend has (`worker`/`beat` only if it actually runs them).
- **`scripts/dev-sse-gateway.sh`** — only if the repo has an SSE gateway (learning #8). Keep DA's
  shape: `cd frontend && exec node -e "require(require.resolve('ssegateway'))"`. Take the port,
  callback, and exact env from this repo's `frontend/tests/support/process/servers.ts`
  `startSSEGateway` — the authoritative working invocation. DA needs
  `RABBITMQ_URL`/`RABBITMQ_ENV_PREFIX`; IoTSupport needed only `PORT=3102` +
  `CALLBACK_URL=http://localhost:3101/api/sse/callback`. Then **delete the sibling-checkout cruft**:
  `backend/scripts/dev-sse-gateway.sh`, the `backend/.vscode/tasks.json` "SSE Gateway" task, any
  orphaned `frontend/scripts/dev-sse-gateway.sh`. Trim every `.vscode/tasks.json` to just `Claude`.
  Smoke-test: the launcher boots on the gateway port and answers `GET /readyz` with 200.
- **Root manifests** — `pyproject.toml`, `.gitignore`, `.dockerignore`. ⚠️ **No root
  `pnpm-workspace.yaml` / `package.json` / `pnpm-lock.yaml`** (learning #1): the frontend keeps its
  own lockfile and `packageManager` pin — do not touch them. `pyproject.toml` = the lean root set
  (honcho, pathspec, `packages=[{include="tools"}]`) plus the `run-suite` script and **`psutil`**.
  Do **not** add `portpicker`/`jsonschema`/`jsonpatch`, `run-suite-remote`, or any canon dep.
- **`scripts/regenerate-openapi.py`** — if the repo generates a client. Keep only `--frontend`, and
  drop its `cli prepare` step where the backend has no such command (learning #4).

**Do not bring**, though DA still has them — they are retired, and copying them re-creates forks
this workflow is removing:

- `tools/code_health/` and the `code-health` script — archived pending a rebuild
  (`archive/quality/` in the AIWorkflow repo).
- `scripts/claude_session.py`, `scripts/codex_exec.py` — the runner drives sessions through `kc`.
- `scripts/preflight.py`, `scripts/build-all.py` — superseded. Preflight is the plugin's; the build
  steps become the manifest's `build:` statements (3b).
- `.claude/agents/`, `.claude/commands/` — the plugin ships these. **Note the inversion:** the
  subrepos carry their own per-subproject dev agents in `backend/.claude/agents/` and
  `frontend/.claude/agents/`, and they ride through the merge automatically. `/dev:onboard` deletes
  them. Leave them for onboard to sweep rather than hand-deleting.

### 3b. The manifest

Author `.kubecoder/project.yaml` with two components, `backend` and `frontend`, and their curated
automation — this is what makes the repo a KubeCoder project and what the pipeline gates on:

- **`build:`** — what `build-all.py` used to do: root `poetry install`, backend `poetry install`
  (with the conditional `poetry env use python3.13`, learning #3), frontend `pnpm install`
  (cwd=`frontend`), frontend `pnpm build`.
- **`test:`** — `poetry run run-suite` and the per-component suites. The runner executes
  `kc project test --project <name>` as its per-task gate, so this is the statement that decides
  whether a task merges.
- **`lint:`** — backend `poetry run check`, frontend `pnpm run check`.

Then install and smoke it:

```bash
cd "$WORK/mono" && poetry install               # root tools
( cd frontend && pnpm install --frozen-lockfile )   # standalone, own lockfile
poetry run run-suite --help                     # suite_runner imports cleanly
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Add project scaffolding + manifest"
```

### 3c. Onboard

```
/plugin install dev@aiworkflow
/dev:onboard
```

Onboard owns the rest of the contract — the three `CLAUDE.md` lines, the spec repo, sweeping the
subrepos' `.claude/` copies, and the `preflight --for run` green light. Do not hand-build any of it
here; if onboard reports something missing, fix it there.

## Phase 4 — CI: 3 build → 1, 2 architecture → 1, 2 producers → 1

### 4a. Single root `Jenkinsfile`

Model on `../DesignAssistant/Jenkinsfile` and adopt DA's order — **validate the working tree first,
then build, then deploy** — trimmed to backend + frontend:

1. **`Cloning repo`** — `checkout scm`; capture branch + gitRev.
2. **`Run validation`** — tar the whole monorepo working tree; `withVault` on `$VALIDATION_VAULT`;
   stand up the inline k8s `Job` on a **base image** (no validation-container build) with only this
   repo's `$VALIDATION_SIDECARS` (drop DA's rabbitmq/pgvector/document-conversion); copy the source
   in; `poetry install` + `poetry run run-suite --output-mode full --junitxml-dir … --retries …`;
   parse `===SUITE_RESULT:` markers for both suites; collect `validation.log` + JUnit;
   `kubectl.deleteJob` in `finally`. Playwright image resolved from `frontend/pnpm-lock.yaml`.
3. **`Building <app>`** — `helmCharts.kaniko("backend/Dockerfile", "backend", ["registry:5000/$IMAGE_APP:<tag>"])`.
4. **`Building <app>-frontend`** — write `frontend/git-rev`;
   `helmCharts.kaniko("frontend/Dockerfile", "frontend", ["registry:5000/$IMAGE_UI:<tag>"])`.
   ⚠️ **Context is `frontend`, not `.`** (learning #1): the frontend is standalone, so its
   Dockerfile is unchanged and needs no workspace-aware rewrite.
5. **`Deploy Helm charts`** — `cicd.helmDeploy()`.

**Tag scheme (no DTAP):** bare `${currentBuild.number}` + `latest`. Validation runs before the
build, so tag `latest` at build time — no post-validation promote stage.

**Drop entirely** vs the old split files: `*-build.json` artifacts, `archiveArtifacts` handoff,
`build job: 'Validation'`, `copyArtifacts`, the second re-clone-by-gitRev, the
`BACKEND_BUILD`/`FRONTEND_BUILD`/`TRIGGERED_BY` params, the GitHub clone credential. All keep
`library identifier: 'JenkinsPipelineUtils', changelog: false`.

### 4b. One combined `Jenkinsfile.architecture`

DA has no architecture stage — it stays its own job. The operator wants **one** architecture job
*and* **one producer** (4c), so fold both into a root `Jenkinsfile.architecture` sharing one
`python` pod:

- One `withVault` (backend OIDC `kv/jenkins/<repo>-pipeline-oidc`) → `podTemplate(python)` → `node`
  → `stage('Cloning repo'){ checkout scm }`.
- **Generate backend architecture** — `dir('backend'){ container('python'){ pip install -r
  ./tools/requirements.txt; gen-architecture.py (with `$ARCH_API_URL`/`$ARCH_DATASET_URL`) } }`.
- **Validate backend / frontend architecture** — `arch-validate.py` over each subrepo's
  `docs/architecture/*.yaml`. The backend stage's `pip install` runs first in the same pod, so the
  frontend stage inherits those deps. Two stages, but one producer — see 4c.
- ⚠️ **`dir()` + `archiveArtifacts` gotcha:** `dir()` only moves the cwd for `sh` steps.
  `archiveArtifacts`/`junit` globs resolve **workspace-root-relative** regardless. Keep
  `checkout scm` and `archiveArtifacts` at the top level and **prefix the globs**
  (`backend/docs/architecture/*.yaml`), wrapping only the `container('python') { sh … }` in `dir()`.

```bash
git -C "$WORK/mono" rm backend/Jenkinsfile frontend/Jenkinsfile frontend/Jenkinsfile.validation \
    backend/Jenkinsfile.architecture frontend/Jenkinsfile.architecture \
    frontend/scripts/validation-entrypoint.sh
# write the root Jenkinsfile + the combined Jenkinsfile.architecture
git -C "$WORK/mono" add -A && git -C "$WORK/mono" commit -m "Consolidate CI: single Jenkinsfile + single Jenkinsfile.architecture"
```

### 4c. Fold the two producers into one

One repo publishes **one** producer. That is the standard `DesignAssistant` sets: a single
`design-assistant` producer covers five in-house products (backend, frontend, portal, manuals,
canon-docs) from one monorepo. The collector accepts many artifact files per producer, so the two
subrepo trees can stay where they are — what changes is what they *declare*.

In the merged repo:

- `frontend/docs/architecture/architecture.yaml` — change `producer: <repo>-ui` to the backend's
  producer id (e.g. `iotsupport-app`). **Leave every element id alone**: ids are what the rest of
  the federated model references; only the provenance stamp moves.
- Fix `sourceRepository:` on the UI's `applicationComponents` — it still names
  `git:pvginkel/<Repo>UI`, which Phase 6 retires.
- Update the artifact's header comment; it typically says the API it consumes "is a separate
  producer".

In **`Architecture.git`** — a separate repo, and the step run 1 missed entirely:

- Delete the `<repo>-ui` entry from `pipeline-producers.yaml`.
- Compare `defaultLogo` on both entries first. If they differ, the UI elements silently change logo
  — carry the value over deliberately rather than by accident.
- `grep -rn '<repo>-ui'` for live references (`*.yaml`, `*.ts`, `*.py`). Hits under `docs/backfill/`
  are historical seeding prompts and stay.

⚠️ **Why this bites, and why it hides.** The collector copies a job's artifacts into
`producer-artifacts/<producer-id>/` and fails when a file's declared `producer:` does not match the
directory it landed in:

```
iotsupport-app/frontend/docs/architecture/architecture.yaml: at /producer:
declared producer 'iotsupport-ui' does not match directory name 'iotsupport-app'
```

Run 1 shipped exactly this and it stayed invisible for six weeks, because the merged job was
independently red the whole time: it failed in its first stage, so nothing was ever archived, and
the collector went on serving the last green artifacts from before the merge. **A red producer job
does not fail the Architecture pipeline — it silently freezes that producer's slice of the model.**
So confirm by watching `AaC/Architecture` go green *after* the merged job does. A green Architecture
run while the producer is red proves nothing.

## Phase 5 — Validate, then swap into place

```bash
cd "$WORK/mono"

# ⚠️ Carry forward gitignored local config (learning #5) — fresh clones omit it, but the backend's
# pytest --co and local dev need it. These stay gitignored.
for f in backend/.env backend/.env.test frontend/.env frontend/.env.test; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$WORK/mono/$f"
done

kc project build                 # the baseline preflight will demand
kc project test --project backend
kc project test --project frontend
git log --oneline --graph -3     # merge + scaffolding + CI commits
```

Expect failures if python3.13 isn't picked up for the backend (learning #3) or `backend/.env.test`
is missing its `S3_*` keys (learning #5).

Swap into the canonical location:

```bash
mv "$SRC" "${SRC}.pre-merge.bak"    # the old two-clone container, kept as backup
mv "$WORK/mono" "$SRC"
```

`/tmp` and the work tree are the same filesystem here, so this is a fast rename — confirm with `df`
(learning #7).

⚠️ **Re-run the Poetry installs at the final path.** Poetry keys venvs by **project path**, so
everything created under `$WORK` is orphaned by the swap: the next `poetry run …` at `$SRC` silently
builds an empty venv and reports "command not found". pnpm's `node_modules` is in-tree and survives.

```bash
cd "$SRC" && poetry install --no-interaction
( cd backend && poetry env use python3.13 && poetry install --no-interaction )
```

Re-run `preflight.py --for run` at the final path to confirm the repo is still pipeline-ready after
the move.

## Phase 6 — Handoff (operator-owned)

Not this skill's to do — report them and stop:

- `git push --force origin main` to `<Repo>.git`, which is now the monorepo.
- Retire / archive `<Repo>UI.git`.
- **Delete the `AaC/<Repo>UI` Jenkins job.** Retiring the repo alone leaves the job pointing at a
  deleted remote, where it lingers as a zombie — it can never build again, but the collector keeps
  serving its last successful artifact, so the frozen slice goes on looking healthy. IoTSupportUI's
  job sat like that from 2026-06-22 until someone went looking.
- Push the `Architecture.git` half of 4c (dropping the `<repo>-ui` producer). Land it together with
  the monorepo push: until both sides agree, one of them fails validation.
- Re-point Jenkins: the multibranch build job → the root `Jenkinsfile`; the single architecture job
  → `Jenkinsfile.architecture`.

Then close the repo's merge card, and note anything the next run should know — the learnings above
exist because run 1 wrote them down.
