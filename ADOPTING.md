# Adopting this template into a project

This guide walks you through copying the template into a new codebase. The workflow assumes a monorepo with one or more subprojects (e.g., `backend/`, `frontend/`, `portal/`) and a separate **specs repo** sitting next to the main repo holding slice documentation and feature artifacts.

## Prerequisites

- A monorepo checkout at some path (e.g., `/work/MyProject`).
- A specs repo at a sibling path (e.g., `/work/MyProjectSpecs`). This is where slice documentation and per-feature planning artifacts live. Keep it separate so slice documents don't clutter your main repo.
- A **Trello board** for the issue log. Create a board with four lists: **New**, **Reviewed**, **Planned**, **Implemented**. The workflow uses these lists to track issue lifecycle during slice runs. Set up labels for issue types (`Bug` red, `Enhancement` green, `Tech Debt` orange, `Needs Discussion` pink) and areas (one per subproject — e.g., `Backend` blue, `Frontend` yellow).
- Python 3 available for the tooling scripts.

## Step 1: Copy the files

From the root of the template, copy into your project:

```
# Root / orchestrator content
orchestrator/CLAUDE.md               → <project_root>/CLAUDE.md
orchestrator/commands/*.md           → <project_root>/.claude/commands/
orchestrator/agents/*.md             → <project_root>/.claude/agents/

# Tooling
tools/ai_workflow/*.py               → <project_root>/tools/ai_workflow/
                                       (or wherever you want the scripts to live;
                                        update the `{{ session_manager_path }}`
                                        and `{{ notification_script }}` variables
                                        to match)

# Per-subproject content — repeat for each subproject
project/CLAUDE.md                    → <project_root>/<subproject>/CLAUDE.md
project/agents/*.md                  → <project_root>/<subproject>/.claude/agents/
project/docs/*.md                    → <project_root>/<subproject>/docs/
```

The four dev-agent files (`plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`) are duplicated per subproject on purpose: each can be tuned to its own stack without touching the others. Start with identical copies and diverge only when a rule is genuinely backend-only or frontend-only.

## Step 2: Fill in the variables

Every file uses Jinja2-style placeholders. Do a find-and-replace pass with the values for your project. The common variables:

| Variable | Meaning | Example |
|---|---|---|
| `{{ project_name }}` | Full name of the project | `Design Assistant` |
| `{{ project_short }}` | Short name for prose | `DA` |
| `{{ project_tagline }}` | One-sentence description | `document-backed copy refinement workspace` |
| `{{ specs_repo_path }}` | Relative path from project root to specs repo | `../MyProjectSpecs` |
| `{{ subproject }}` | Subproject name (per-project files only) | `backend` / `frontend` / `portal` |
| `{{ subproject_tagline }}` | Short description of the subproject | `Flask backend serving internal and portal APIs` |
| `{{ session_manager_path }}` | Path to `claude_session.py` from project root | `tools/ai_workflow/claude_session.py` |
| `{{ notification_script }}` | Path to your push-notification script | `tools/ai_workflow/send_message.py` |
| `{{ check_command }}` | Lint/type/format command for the subproject | `poetry run check` / `pnpm run check` |
| `{{ test_command }}` | Test command for the subproject | `poetry run pytest` / `pnpm exec playwright test` |
| `{{ full_suite_command }}` | Full test suite command for the whole monorepo | `poetry run run-suite-remote` |
| `{{ regen_api_command }}` | Command to regenerate the OpenAPI client (if applicable) | `pnpm generate:api` |
| `{{ issue_log_url }}` | URL to the project's Trello issue log board | `https://trello.com/b/abc123/my-project-issues` |

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

The scripts in `tools/ai_workflow/` (`claude_session.py`, `codex_exec.py`) are runtime dependencies of the `run-slice` skill. Make sure:

- They are executable (`chmod +x`).
- `python3` is on PATH.
- `claude_session.py` can find the `claude` CLI.
- Any paths hardcoded inside the scripts (if you edit them) match your project layout.

You will likely also want a push-notification script. The template references `{{ notification_script }}` but does not ship one — provide your own, or remove the notification calls from `run-slice.md` and `triage.md` if you don't use them.

## Step 5: Try a small slice

Before running any real work, do a smoke test:

1. In the root of your project, start a Claude Code session and confirm `CLAUDE.md` is loaded and reads cleanly.
2. Type `/write-slice "add a trivial field to <an existing entity>"` and walk through the authoring flow. Check that the slice directory gets created in your specs repo and that the generated files look right.
3. Type `/run-slice <NUMBER>` on that slice and watch the orchestrator dispatch the dev session(s). Kill it after the pre-flight step if you don't want to run real code changes.

If any step fails with "file not found" or "variable not filled in," that's a signal you missed a placeholder during Step 2.

## Step 6: Read `WRITING_GUIDE.md` before modifying anything

The template makes strong assumptions about where content lives (CLAUDE.md hierarchy, agent definition shape, workflow doc purpose). When you customize or extend, follow those rules or the whole system drifts back toward the duplication this template was built to eliminate. `WRITING_GUIDE.md` documents the rules explicitly.
