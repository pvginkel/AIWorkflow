# AI Workflow

A reusable scaffolding for running a slice-based, multi-agent development workflow with Claude Code.

This repository is a **template**, not a library. Copy its contents into a real project and fill in the marked sections. Jinja2 syntax (`{{ variables }}` and `{% block %}…{% endblock %}`) marks the places that need customization — you do not need to actually run Jinja2; the syntax is only a visual indicator of what is project-specific.

## What's in here

- **`orchestrator/`** — everything that gets copied to the monorepo root. The orchestrator session's `CLAUDE.md`, the slice-management skills (`run-slice`, `write-slice`, `triage`, `arch-design`, `ux-design`, `quality-improver`, `quality-issue-finder`, `refactor-audit`), the `arch-design` and `slice-verifier` agents, root scaffolding (`pyproject.toml`, `pnpm-workspace.yaml`, `.gitignore`, `.codehealthignore`, `Procfile.dev`), and orchestration scripts (`scripts/build-all.py`, `scripts/regenerate-openapi.py`).
- **`project/`** — content for each per-subproject Claude Code session (backend, frontend, portal, etc.). Contains a per-project `CLAUDE.md`, the four dev agents (`plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`), and the major/minor change workflow documents.
- **`tools/ai_workflow/`** — runtime scripts the orchestrator depends on: `claude_session.py` (session manager for dispatching dev agents), `codex_exec.py` (wrapper for invoking Codex for UX design generation), `send_message.py` (push-notification helper).
- **`tools/code_health/`** — code-health grader (Python + a TypeScript cognitive-complexity sidecar). Wired as a Poetry script (`code-health`) by `orchestrator/pyproject.toml`. Used by the `refactor-audit` and `quality-issue-finder` skills.

## How to use it

- Read **[`ADOPTING.md`](ADOPTING.md)** for how to copy this template into a new project and fill in the variables.
- Read **[`WRITING_GUIDE.md`](WRITING_GUIDE.md)** for the rules that keep these artifacts maintainable over time — where different kinds of content belong, what to duplicate (nothing), and how to structure agent definitions and skills.
