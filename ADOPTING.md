# Adopting this template into a project

This guide walks you through copying the template into a new codebase. The workflow assumes a monorepo with one or more subprojects (e.g., `backend/`, `frontend/`, `portal/`) and a separate **specs repo** sitting next to the main repo holding slice documentation and feature artifacts.

## Prerequisites

- A monorepo checkout at some path (e.g., `/work/MyProject`).
- A specs repo at a sibling path (e.g., `/work/MyProjectSpecs`). This is where slice documentation and per-feature planning artifacts live. Keep it separate so slice documents don't clutter your main repo.
- An **issue log** in any kanban tool with a decent MCP server — Trello, Linear, GitHub Projects, Jira, etc. The workflow only assumes a four-state lifecycle (**New** → **Reviewed** → **Planned** → **Implemented**) and a tagging system for issue type (`Bug`, `Enhancement`, `Tech Debt`, `Needs Discussion`) and area (one per subproject). Wire the tool's MCP server into Claude Code so the orchestrator can read and write cards. The template's defaults are written with Trello as the reference implementation; if you use something else, adjust the orchestrator's `CLAUDE.md` issue-log block to match its terminology (lists vs. columns vs. statuses, labels vs. tags vs. custom fields).
- Python 3 available for the tooling scripts.

## Step 1: Copy the files

From the root of the template, copy into your project:

```
# Root / orchestrator content
orchestrator/CLAUDE.md               → <project_root>/CLAUDE.md
orchestrator/commands/*.md           → <project_root>/.claude/commands/
orchestrator/agents/*.md             → <project_root>/.claude/agents/
                                       (orchestrator agents — arch-design,
                                        slice-verifier — at the repo root;
                                        dev agents are per-subproject, below)

# Root scaffolding (Poetry/pnpm/gitignore)
orchestrator/pyproject.toml          → <project_root>/pyproject.toml
orchestrator/pnpm-workspace.yaml     → <project_root>/pnpm-workspace.yaml
orchestrator/.gitignore              → <project_root>/.gitignore
orchestrator/.codehealthignore       → <project_root>/.codehealthignore

# Orchestration scripts
orchestrator/scripts/*.py            → <project_root>/scripts/
                                       (preflight.py, build-all.py,
                                        regenerate-openapi.py, _initd_log.py
                                        — referenced by /run-slice's
                                        pre-flight and Step 2)

# Runtime tools
tools/ai_workflow/*.py               → <project_root>/tools/ai_workflow/
                                       (or wherever you want the scripts to live;
                                        update the `{{ session_manager_path }}`
                                        and `{{ notification_script }}` variables
                                        to match)
tools/code_health/                   → <project_root>/tools/code_health/
                                       (Python + TypeScript sidecar; wired as
                                        the `code-health` Poetry script)

# Per-subproject content — repeat for each subproject
project/CLAUDE.md                    → <project_root>/<subproject>/CLAUDE.md
project/docs/*.md                    → <project_root>/<subproject>/docs/
project/agents/*.md                  → <project_root>/<subproject>/.claude/agents/
                                       (the four dev agents plan-writer/
                                        plan-reviewer/code-writer/code-reviewer
                                        — one copy per subproject; see note below)
```

**Agent discovery walks *up* from the session's cwd to the git root**, merging every `.claude/agents/` it passes — the same hierarchical rule `CLAUDE.md` uses. So the orchestrator agents (`arch-design`, `slice-verifier`) live in the repo-root `.claude/agents/`, and the **dev agents live per subproject** in `<subproject>/.claude/agents/`. The session manager dispatches each dev agent with its cwd set to that subproject (`claude_session.py` runs `claude` with `cwd=<subproject>`), so the dev session sees its own subproject's agents **and** the root orchestrator agents. Copy one set of dev agents into each subproject and replace `{{ subproject }}` with the subproject's name; this lets each subproject specialize its dev agents (matching how DesignAssistant ships a tailored `code-writer` per stack). Shared per-subproject context still belongs in that subproject's `CLAUDE.md` + `docs/conventions.md`, which load automatically from the dev agent's working directory.

> **The one hard requirement is the `description:` frontmatter field** — *not* placement. Claude Code silently drops any agent file that has only a `name:` from the Task tool's `subagent_type` enum, wherever it sits. (Learned the hard way: the dev agents originally shipped name-only, and *every* change-workflow run silently fell back to `general-purpose`. The fix was adding a `description`, not moving the files — a two-phase experiment later confirmed that subproject agents register fine as long as they carry one. See [`WRITING_GUIDE.md`](WRITING_GUIDE.md).)

## Step 2: Fill in the variables

Every file uses Jinja2-style placeholders. Do a find-and-replace pass with the values for your project. The common variables:

| Variable | Meaning | Example |
|---|---|---|
| `{{ project_name }}` | Full name of the project | `Kestrel` |
| `{{ project_short }}` | Short name for prose | `Kestrel` |
| `{{ project_tagline }}` | One-sentence description | `build-log aggregator for distributed CI runs` |
| `{{ specs_repo_path }}` | Relative path from project root to specs repo | `../KestrelSpecs` |
| `{{ subproject }}` | Subproject name (per-project files only) | `backend` / `frontend` / `worker` |
| `{{ subproject_tagline }}` | Short description of the subproject | `FastAPI ingest API, log normalizer, and query service` |
| `{{ session_manager_path }}` | Path to `claude_session.py` from project root | `tools/ai_workflow/claude_session.py` |
| `{{ notification_script }}` | Path to your push-notification script | `tools/ai_workflow/send_message.py` |
| `{{ check_command }}` | Lint/type/format command for the subproject | `poetry run check` / `pnpm run check` |
| `{{ test_command }}` | Test command for the subproject | `poetry run pytest` / `pnpm exec playwright test` |
| `{{ full_suite_command }}` | Full test suite command for the whole monorepo | `poetry run run-suite-remote` |
| `{{ regen_api_command }}` | Command to regenerate generated API artifacts (if applicable); commit the regenerated caches separately afterward | `scripts/regenerate-openapi.py --frontend --portal` |
| `{{ issue_log_url }}` | URL to the project's issue log board | `https://trello.com/b/abc123/my-project-issues` |
| `{{ subproject_names }}` | Subproject names for `claude_session.py` `VALID_PROJECTS` | `"backend", "frontend", "portal"` |
| `{{ external_projects }}` | External project map for `claude_session.py` `EXTERNAL_PROJECTS` | `{"gateway": PROJECT_ROOT.parent / "Gateway"}` or `{}` |

Per-template block sections (`{% block foo %}…{% endblock %}`) are free-form and need to be replaced with prose specific to your codebase. They are marked with `{# … #}` comments explaining what belongs there. Examples:

- `{% block project_overview %}` — what the project does, who it's for
- `{% block architecture_snapshot %}` — one-paragraph description of the stack and folder layout
- `{% block code_organization %}` — layered architecture rules (API → services → models, etc.)
- `{% block testing_requirements %}` — test coverage expectations, how to run tests, fixtures
- `{% block design_philosophy %}` — opinions about backwards-compat, tombstones, defensive code
- `{% block key_documentation %}` — pointers to the docs a dev agent should consult

## Step 3: Write `docs/conventions.md`

The template's per-project `CLAUDE.md` is deliberately lean. Detailed conventions — DI patterns, error handling, database patterns, testing patterns, naming conventions — belong in a separate `docs/conventions.md` inside each subproject. `CLAUDE.md` points at it; the dev agents read it when needed.

This split exists so `CLAUDE.md` stays small (it is prepended to every agent turn) while detailed rules remain discoverable. See `WRITING_GUIDE.md` for the reasoning.

There is no template for `conventions.md` — its content is entirely project-specific. Start with the rules you already have written down somewhere and curate them into one document per subproject.

## Step 4: Set up the tooling

The scripts in `tools/ai_workflow/` (`claude_session.py`, `codex_exec.py`, `send_message.py`) are runtime dependencies of the `run-slice` skill. Make sure:

- They are executable (`chmod +x`).
- `python3` is on PATH.
- `claude_session.py` can find the `claude` CLI.
- Any paths hardcoded inside the scripts (if you edit them) match your project layout.

**`claude_session.py` contains Jinja-style placeholders.** Unlike the markdown
files, this is a Python script that won't run until you replace the
`{{ subproject_names }}` and `{{ external_projects }}` placeholders at the top
of the file with literal Python values. The placeholders are documented inline
in the script. See Step 2's variable table.

The template ships a push-notification helper at `tools/ai_workflow/send_message.py` — point it at your Home Assistant instance via `HA_URL`, `HA_TOKEN`, and `HA_NOTIFY_SERVICE` environment variables, or replace its body with a call to a different delivery channel (Pushover, ntfy, Slack, email, etc.). The skills only depend on its CLI contract (`send_message.py [--title TITLE] [--channel CHANNEL] MESSAGE`). If you don't want push notifications at all, remove the notification calls from `run-slice.md` and `triage.md`.

`codex_exec.py` is only needed if you use the `/ux-design` skill's "Codex" invocation option. If you dispatch UX work as a Claude Code subagent instead (see the block in `orchestrator/commands/ux-design.md`), `codex_exec.py` is unused and can be deleted, along with the `.agents/skills/frontend-ux-designer/` directory it relies on.

### Step 4b: Install dependencies

Once the files are in place:

1. **Poetry deps** — `cd <project_root> && poetry install`. This installs the orchestration tools (`code-health`, `claude_session.py`, etc.) and registers the `code-health` Poetry script.
2. **pnpm install** — `pnpm install`. This pulls dependencies for the workspace, including the cognitive-complexity sidecar at `tools/code_health/cognitive/`.
3. **Verify** — `poetry run code-health --help` should print usage. The first time you run it, the sidecar will compile its TypeScript via `tsx` on demand.

If you're not using one or both of Poetry/pnpm, edit `pyproject.toml`/`pnpm-workspace.yaml` accordingly. The orchestration scripts only depend on the Python deps listed in `pyproject.toml`.

**One-command dev startup (optional).** A `Procfile.dev` with [honcho](https://github.com/nickstenning/honcho) or a similar process manager (foreman, overmind) is a handy way to start the backend, frontend, and other long-running services in one shell. Honcho is already listed as a dependency in `pyproject.toml`. The template doesn't ship a `Procfile.dev` because the per-subproject dev commands vary too much; if you want one, create it at the repo root with one `name: command` line per service.

## Step 5: Try a small slice

Before running any real work, do a smoke test:

1. In the root of your project, start a Claude Code session and confirm `CLAUDE.md` is loaded and reads cleanly.
2. Type `/write-slice "add a trivial field to <an existing entity>"` and walk through the authoring flow. Check that the slice directory gets created in your specs repo and that the generated files look right.
3. Type `/run-slice <NUMBER>` on that slice and watch the orchestrator dispatch the dev session(s). Kill it after the pre-flight step if you don't want to run real code changes.

If any step fails with "file not found" or "variable not filled in," that's a signal you missed a placeholder during Step 2.

## Single-project repositories

If your repo has only one codebase (no `backend/` + `frontend/` split), merge the `orchestrator/` and `project/` content into a single set of files at the repo root. The key differences:

- **No `claude_session.py`.** The orchestrator doesn't need to dispatch separate Claude processes for different subprojects. The `run-slice` command dispatches dev agents directly as Task subagents from the same session.
- **Rewrite `run-slice.md`** to dispatch agents directly (Task tool) instead of via the session manager. The step structure is the same (pre-flight → plan-writer → plan-reviewer → code-writer → verify → code-reviewer → iterate), but without the `claude_session.py start/resume/finish` choreography.
- **`CLAUDE.md` combines orchestrator and project content** — design philosophy, issue log, documentation pointers, testing expectations, code quality commands all go in one file.
- **Agents and commands live in `.claude/agents/` and `.claude/commands/`** at the repo root (no subproject nesting).

## Step 6: Read `WRITING_GUIDE.md` before modifying anything

The template makes strong assumptions about where content lives (CLAUDE.md hierarchy, agent definition shape, workflow doc purpose). When you customize or extend, follow those rules or the whole system drifts back toward the duplication this template was built to eliminate. `WRITING_GUIDE.md` documents the rules explicitly.
