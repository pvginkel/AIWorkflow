# Example: a filled-in `CLAUDE.md`

The template files in this repo use Jinja2-style syntax (`{{ variables }}` and
`{% block %}…{% endblock %}`) as **visual markers** for the places that need
customization. **Nothing in this repo is actually rendered by Jinja.** The
syntax is a hint to you (and to Claude, if you ask it to help adapt the
template) about where to substitute values and where to write project-specific
prose.

This document shows one end-to-end example so you can see what the template
produces. It picks a fictional project — **Kestrel**, a "build-log aggregator
for distributed CI runs" — and walks through one file (`orchestrator/CLAUDE.md`)
in both forms.

## Before

This is `orchestrator/CLAUDE.md` as it ships in the template, abbreviated:

```markdown
# {{ project_name }}

{% block project_overview %}
{# One-paragraph description of the project: what it is, who it serves, and
   the high-level shape (e.g., "monorepo with backend + frontend + portal").
#}
{{ project_name }} is a {{ project_tagline }}.
{% endblock %}

## Repo structure

{% block repo_structure %}
{# Describe the subdirectories and what each contains. Be brief — one line
   per directory. Also mention where the specs repo lives.
#}
- **Root** — orchestration tooling, slice documentation, architecture decisions.
- **`{{ subproject }}/`** — <one-line description>
- (repeat for each subproject)

A separate **specs repo** at `{{ specs_repo_path }}` holds slice documentation…
{% endblock %}

…
```

Two kinds of placeholder appear here:

1. **`{{ variables }}`** — single tokens like `{{ project_name }}` and
   `{{ specs_repo_path }}`. Do a find-and-replace pass across the file with the
   values from your project. The full variable table is in
   [`ADOPTING.md`](ADOPTING.md).
2. **`{% block name %}…{% endblock %}`** — sections of free-form prose marked
   with `{# … #}` comments explaining what belongs in them. You delete the
   block markers and the comment, and write prose specific to your codebase in
   their place.

## After

This is the same file after the substitutions, for the Kestrel project:

```markdown
# Kestrel

Kestrel is a build-log aggregator for distributed CI runs. It ingests
structured log streams from CI workers across a fleet, deduplicates and
normalizes them, and exposes a query API and a web dashboard for triaging
test failures across the whole fleet.

## Repo structure

- **Root** — orchestration tooling, slice documentation, architecture decisions.
- **`backend/`** — Python (FastAPI) ingest API, log normalizer, query service.
- **`frontend/`** — TypeScript (React + Vite) dashboard for browsing aggregated
  builds.
- **`worker/`** — Go agent installed on CI runners that streams logs into the
  backend.

A separate **specs repo** at `../KestrelSpecs` holds slice documentation and
per-feature planning artifacts (briefs, plans, reviews). Slices live under
`slices/` grouped by lifecycle state — pending at the top, `completed/` /
`deferred/` / `cancelled/` subfolders for the rest; see its README for the
convention.

**Commit to the specs repo early and often.** The specs repo is a separate
git repository. Every document you produce there should be committed as soon
as it's written — not batched up at the end. `cd` to `../KestrelSpecs`,
`git add` the file, and commit. Frequent small commits avoid conflicts and
prevent work loss if a session crashes.

## Your role as orchestrator

You are the **project orchestrator**. You do not edit application code
directly — all code changes are delegated to dev agents via the slice
workflow. If the user requests an ad hoc change, push back and suggest
creating a dedicated slice…

…
```

Notice what changed:

- Every `{{ variable }}` got replaced with a literal value (`Kestrel`,
  `../KestrelSpecs`).
- The `{% block project_overview %}` and `{% block repo_structure %}` markers
  disappeared, along with their `{# … #}` instructional comments.
- The contents of the blocks were rewritten to describe Kestrel specifically —
  the architecture snapshot, the per-subproject one-liners.
- Prose **outside** the blocks (the "your role as orchestrator" section, the
  "commit to the specs repo early and often" paragraph) was kept verbatim —
  those are the template's load-bearing rules that apply to every project.

## How to actually do the substitution

You have three options. Pick whichever fits your workflow.

1. **Find-and-replace by hand.** Open each file in an editor, do
   case-sensitive find-and-replace for each `{{ variable }}`, then write prose
   in each `{% block %}`. Slow but predictable.
2. **Sed/perl script.** Write a small script that substitutes the variables.
   Faster for the simple tokens, but the blocks still need manual prose
   writing.
3. **Ask Claude to adapt the template for you.** Open a Claude Code session in
   your new project directory, copy in the template files, and ask Claude to
   fill in the variables and rewrite each `{% block %}` based on a short
   project description. Review every output before committing — the goal is a
   `CLAUDE.md` that reflects *your* opinions about how the project is built,
   not the model's guesses.

Whichever option you pick, the goal is the same: a `CLAUDE.md` that has no
`{{ }}` or `{% block %}` markers left in it. If any survive into your
project's first commit, that's a missed substitution and the orchestrator
session will read them as literal text.

## Why this is not real Jinja

A few reasons:

- The blocks aren't reused between files — each is a one-shot prose section,
  not a template inheritance hook. Calling it "Jinja" would imply a render
  pipeline that doesn't exist.
- The substitution is one-time. Once you've filled in the values, the file is
  a regular markdown file. You don't re-render it when values change; you
  edit it directly.
- The `{# … #}` comments are read by *humans* (or by Claude, helping you
  adapt the template), not stripped by a renderer. Removing them is part of
  the substitution.

Treating the syntax as a *convention*, not as a runtime, means you can adapt
the template in any way you like — with an editor, a script, an LLM, or a
mix — without committing to a particular toolchain.
