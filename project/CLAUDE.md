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

## Conventions

Detailed conventions — architectural patterns, layering rules, dependency injection, database and schema patterns, error handling, observability, testing patterns — live in **`docs/conventions.md`**. Read it when you need to make technical choices. If the user proposes a new convention, update `docs/conventions.md` to reflect it (not this file).

This `CLAUDE.md` intentionally stays lean. It is prepended to every turn and to every dev-agent subagent dispatched from this subproject, so every line here is paid for many times over.

## Testing expectations

{% block testing_expectations %}
{# What does "done" look like? Include:
   - What kinds of tests are required (unit, integration, e2e)
   - Test data conventions
   - Any testing infrastructure that matters (real DB vs mocks, fixtures)
   - Non-negotiable rules (e.g., "every feature ships with test coverage")
   Keep it short. Details go in docs/conventions.md.
#}
- Every feature must ship with test coverage. A feature without tests is incomplete.
- Tests live in `tests/` mirroring the `app/` structure.
- Use real services where practical; see `docs/conventions.md` for specifics.
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
