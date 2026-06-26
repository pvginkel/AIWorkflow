# AI Workflow

A reusable scaffolding for running a slice-based, multi-agent development workflow with Claude Code.

This repository is a **template**, not a library. Copy its contents into a real project and fill in the marked sections. Jinja2 syntax (`{{ variables }}` and `{% block %}…{% endblock %}`) marks the places that need customization — you do not need to actually run Jinja2; the syntax is only a visual indicator of what is project-specific.

## What's in here

- **`orchestrator/`** — everything that gets copied to the monorepo root. The orchestrator session's `CLAUDE.md`, the slice-management skills (`run-slice`, `write-slice`, `triage`, `arch-design`, `update-docs`, `ux-design`, `quality-improver`, `quality-issue-finder`, `refactor-audit`) and the major/minor change-workflow commands, the **orchestrator agents** (`arch-design`, `slice-verifier`), the documentation-model meta-doc (`docs/documentation-model.md`), root scaffolding (`pyproject.toml`, `pnpm-workspace.yaml`, `.gitignore`, `.codehealthignore`), and orchestration scripts (`scripts/build-all.py`, `scripts/regenerate-openapi.py`).
- **`project/`** — content for each per-subproject Claude Code session (backend, frontend, portal, etc.): a per-project `CLAUDE.md` (and the project-authored `docs/conventions.md` it points at), plus the per-subproject **dev agents** in `agents/` (`plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`). These all load from each subproject directory: the dev session runs with its cwd set to the subproject, and Claude Code discovers agents by walking up from the cwd to the git root — so a dev agent sees both its own subproject's agents and the orchestrator agents at the root. Copy one set per subproject (see [`ADOPTING.md`](ADOPTING.md)).
- **`tools/ai_workflow/`** — runtime scripts the orchestrator depends on: `claude_session.py` (session manager for dispatching dev agents), `codex_exec.py` (wrapper for invoking Codex — optional, only used by `/ux-design` when that path is chosen), `send_message.py` (push-notification helper).
- **`tools/code_health/`** — code-health grader (Python + a TypeScript cognitive-complexity sidecar). Wired as a Poetry script (`code-health`) by `orchestrator/pyproject.toml`. Used by the `refactor-audit` and `quality-issue-finder` skills.
- **`specs/`** — scaffolding for the sibling **specs repo** (not the main repo): `scripts/allocate-next-slice.sh`, the concurrency-safe slice-number allocator that `/write-slice` calls, plus the `.gitignore` lines for its host-local counter files.
- **`.agents/skills/frontend-ux-designer/`** — a Codex skill definition (prompt + UX review checklist + design-doc template) consumed by `/ux-design` if you invoke it via Codex. Only needed if you go down that path; safe to delete if you dispatch UX work as a Claude Code subagent instead.

## Tooling expectations

- **Claude Code** — required. The whole workflow assumes the `claude` CLI is available and dispatches dev agents through it.
- **Codex (OpenAI)** — optional. Only the `/ux-design` skill's "Codex" invocation option uses it, via `tools/ai_workflow/codex_exec.py`. The skill ships with a Claude Code subagent alternative; if you prefer that, you can delete `codex_exec.py` and `.agents/`.
- **Python 3.11+, pnpm, Poetry** — the orchestration scripts and the code-health grader depend on these.

## How to use it

- Read **[`EXAMPLE.md`](EXAMPLE.md)** for a fully-rendered example of what one `CLAUDE.md` looks like after the placeholders are filled in. This is the quickest way to see what the template produces.
- Read **[`ADOPTING.md`](ADOPTING.md)** for how to copy this template into a new project and fill in the variables.
- Read **[`WRITING_GUIDE.md`](WRITING_GUIDE.md)** for the rules that keep these artifacts maintainable over time — where different kinds of content belong, what to duplicate (nothing), and how to structure agent definitions and skills.

## A note on the Jinja syntax

The template files use Jinja2-style syntax (`{{ variables }}` and `{% block %}…{% endblock %}`) as a **visual marker** for the places that need customization. **The template is not actually rendered by Jinja.** You are expected to do a find-and-replace pass with your project's values (variables) and replace each `{% block %}…{% endblock %}` with prose specific to your codebase. Treating the placeholders as syntax hints rather than as runtime templating means you can edit files in any tool, run them through any preprocessor, or skip the substitution entirely and just edit by hand. `EXAMPLE.md` shows the before-and-after.
