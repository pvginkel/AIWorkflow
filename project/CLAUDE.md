# {{ project_name }} — {{ subproject | title }}

{% block subproject_overview %}
{# One short paragraph: what this subproject is, what it's responsible for,
   and how it fits into the rest of the monorepo. Keep it to 2–3 sentences.
#}
This is the {{ subproject }} of {{ project_name }} — {{ subproject_tagline }}.
{% endblock %}

## Sandbox environment

{% block sandbox_environment %}
{# Describe the dev environment: where the monorepo is mounted, which
   subdirectory this subproject lives in, any container/toolchain notes.
   Keep it factual and brief.
#}
- The monorepo is available at `{{ project_root }}`.
- Dev agents work scoped to the `{{ subproject }}/` subdirectory but commit to the single shared repository.
{% endblock %}

## Design philosophy

{% block design_philosophy %}
{# These rules define how code changes are approached in this project. They
   apply to every agent: plan-writers, code-writers, and reviewers alike.
   Put them here (not just in the orchestrator CLAUDE.md) because project
   agents don't see the root CLAUDE.md — this is their only source.
#}
- **Always do the clean refactor.** When changing an interface, a data model, or a contract: update every caller, fix every test, change every reference. Do not leave the old version alive alongside the new one "for now." Do not add optional parameters that default to old behavior. Do not create adapter layers, shims, thunks, or trampolines that translate between old and new. The number of files changed is not a cost; incomplete migrations are.
- **No backwards compatibility.** This project has no external consumers. All subprojects are developed and deployed together. There is never a reason to preserve an old interface for compatibility.
- **No tombstones.** When code is replaced or removed, delete it completely. No commented-out code, no `# removed` markers, no stub functions, no re-exports at old import paths, no "see X instead" docstrings.
{% endblock %}

## Specs repo

Planning documents (change briefs, plans, plan reviews, code reviews) are stored in a separate specs repo at `{{ specs_repo_path }}`. If you need context on a slice, feature, or prior design decision, look there.

## Documentation

Project-specific documentation is organized by topic area in **`docs/`**. See **`docs/index.md`** for the full index — it links to topic areas like code style, testing, and any project-specific conventions. `docs/index.md` is the entry point; plan-writers survey it to build the required reading list for each plan.

This `CLAUDE.md` intentionally stays lean. It is prepended to every turn and to every dev-agent subagent dispatched from this subproject, so every line here is paid for many times over.

## Testing expectations

{% block testing_expectations %}
{# What "done" looks like for a dev agent in this subproject. Keep it short —
   detail belongs in docs/testing.md. Examples of what to put here:
   - "Every feature must ship with test coverage. A feature without tests is incomplete."
   - Where tests live (mirror `src/` in `tests/`, etc.).
   - Special test infrastructure rules (use real services vs mocks, fixture conventions).
   See docs/testing.md for the actual rules.
#}
- Every feature must ship with test coverage. A feature without tests is incomplete.
- See `docs/testing.md` for fixtures, patterns, and infrastructure.
{% endblock %}

## Code quality

Before committing, verify:

```bash
{{ check_command }}
```

This runs the full lint/type/format/test pipeline. If any step fails, fix it before handing work back.

Individual tools (when you want to run a subset):

{% block individual_commands %}
{# If the check_command umbrella hides multiple tools, list them here
   with short descriptions. If your project just uses one tool, delete
   this block.
#}
```bash
{{ test_command }}      # Tests only
```
{% endblock %}

## Decision-making

When deciding how to approach a problem, choose an approach and commit to it. Avoid revisiting decisions unless you encounter new information that directly contradicts your reasoning. If you're weighing two approaches, pick one and see it through. You can always course-correct later if the chosen approach fails.

Do not over-explore the codebase. Read what you need for the task at hand. If you've found the relevant files and understand the patterns, start working — don't keep searching for more context.
