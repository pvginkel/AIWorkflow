# Writing guide for AI Workflow artifacts

This document describes the rules for writing and maintaining the artifacts in this template: `CLAUDE.md` files, agent definitions, skills (commands), workflow docs, and convention docs. The rules exist to prevent duplication, keep context windows clean, and make drift easy to spot.

If you add or modify content anywhere in the workflow, first find which layer it belongs in using the hierarchy below. If something doesn't fit, that's a signal to revisit the hierarchy rather than to duplicate.

## The hierarchy

Content flows in one direction, from most-reused to most-specific:

```
root CLAUDE.md              ← prepended to every orchestrator turn
  └─ skills (run-slice, write-slice, triage, …)
        └─ dispatches dev sessions (backend, frontend, portal, …)

per-subproject CLAUDE.md    ← prepended to every turn in that subproject's session
  └─ docs/conventions.md    ← detailed rules, read on demand
  └─ workflow docs (major/minor change workflow)
        └─ dispatches dev-agent subagents (plan-writer, code-writer, …)
              └─ dev-agent definition files   ← own the agent's role, sections to produce, unique behavior
```

**Every piece of content lives in exactly one place.** If you find yourself wanting to state the same rule in two files, the rule belongs in the higher layer, and the lower layer should reference it (or not mention it at all).

## Layer responsibilities

### Root `CLAUDE.md` (orchestrator)

- What the project is and who the orchestrator serves.
- The orchestrator's role (coordinate, don't write code).
- Which skills exist and when to use each one.
- High-level design philosophy (breaking changes, no tombstones, etc.) — the non-negotiable rules that apply across every subproject.
- A short pointer list to key documentation.

Should **not** contain:
- Details about how any one skill works (that's the skill file).
- Project-specific patterns (that belongs in per-subproject `CLAUDE.md` or `docs/conventions.md`).
- Agent management procedures that appear in the skills (the skills describe their own workflow).

Target: **≤ 100 lines.** This file is prepended to every turn of the orchestrator session.

### Per-subproject `CLAUDE.md`

- What the subproject is and what it's responsible for.
- Sandbox environment (paths, toolchain, container mounts).
- Testing expectations — what "done" looks like for a dev agent.
- Code quality commands (lint/type/test) with literal shell invocations.
- A pointer to `docs/conventions.md` for detailed rules.
- Generic Claude Code behavior hints (parallel tool calls, decision-making) if you want them — these are cross-project but scoped to the subproject's session.

Should **not** contain:
- Detailed architectural patterns (DI, layering, error handling) — put them in `docs/conventions.md` and point at them.
- Restatements of the workflow doc or agent definitions.
- Project overview content that already lives in the root `CLAUDE.md`.

Target: **≤ 100 lines.** This file is prepended to every turn of that subproject's dev session *and* to every user-defined dev-agent subagent dispatched from it.

### `docs/index.md` and topic-area files (per-subproject)

Documentation is organized by **topic area** — "what are you working on?" — not by document type. Each topic area is a self-contained file that mixes binding rules and how-to recipes together, because when you're building a service you need both.

`docs/index.md` is the entry point. It is a **pure fan-out document** that contains no rules itself — only links to topic-area files with one-line descriptions. It includes a "Maintaining this index" section explaining that plan-writers dispatch Explore agents to survey the directory.

**Typical topic areas** (vary by project and stack):

- `code-style.md` — linting, type hints, error handling, readability (required reading for every plan)
- `api-design.md` — endpoint patterns, pagination, schema naming
- `services.md` — service layer pattern, dependency injection, metrics
- `database-changes.md` — schema conventions, collation, migrations
- `database-usage.md` — query patterns, relationships, enumerations
- `testing.md` — test organization, fixtures, coverage expectations
- `graceful-shutdown.md` — lifecycle coordinator integration
- `sse-event-targeting.md` — SSE dispatch rules

When a new topic area emerges, create a file, add it to `index.md`, and it's immediately discoverable by plan-writers.

### `docs/conventions/` (per-subproject, optional)

A folder for **detailed convention documents** that are too large for a single topic-area file but still binding and independently referenceable. Typical contents: UI form conventions, data display rules, button standards, tooltip guidelines, UI pattern archetypes (entity management, simple CRUD). `index.md` links to these files.

### `docs/reference/` (per-subproject, optional)

**Orientation docs** about what exists. Architecture diagrams, folder structure, dependency lists, key UI surface inventories. Useful for getting bearings but doesn't prescribe behavior.

### Organizing documentation — the topic-area test

When adding documentation, ask: **"What task would make a developer reach for this?"**

| If the answer is… | Then it goes in… |
|---|---|
| "Any time I write code" | `code-style.md` |
| "When I'm building an API endpoint" | `api-design.md` |
| "When I'm changing the schema" | `database-changes.md` |
| "When I'm orienting on the architecture" | `reference/architecture.md` |
| "It doesn't fit a single task — it's a project-wide rule" | Root `docs/conventions.md` or `CLAUDE.md` |

The goal: each topic-area file is a self-contained reference for one kind of work. A plan links to 2–5 topic areas, and the code-writer reads exactly those files.

### Workflow docs (`docs/major_change_workflow.md`, `docs/minor_change_workflow.md`)

Pure **orchestration sequence**: which agent is dispatched, in what order, with what inputs, and what verification happens between steps.

Should **not** contain:
- The content of each step (that lives in the agent definition).
- Quality standards for a plan or a code review (those live in the agent definitions).
- Restatements of patterns from `CLAUDE.md`.
- "Before starting, read X" instructions — if the agent needs to read X, its own definition says so.

Think of the workflow doc as a script that choreographs the agents, not a place to explain what the agents do.

### Agent definitions (`.claude/agents/<name>.md`)

Each agent definition contains:

1. **Frontmatter** — `name`, `model` (optional), and `description` *only if the LLM needs to choose this agent vs. another*. See "When to write a description" below.
2. **Role** — one paragraph stating what the agent is and what it produces.
3. **Output location** — where the agent writes its artifact.
4. **Sections to produce** (for plan-writer / plan-reviewer / code-reviewer) — the structure of the artifact, with templates and examples.
5. **Unique behavioral rules** — adversarial sweep requirement, decision-block format, "don't act before instructions," etc. Anything that makes this agent different from a plain `code-writer` doing the same job.

Should **not** contain:
- Project architecture rules — those live in `CLAUDE.md` and `docs/conventions.md`. The agent reads them; it doesn't need the rules repeated.
- "Read CLAUDE.md first" — it's loaded automatically. Just say what to read for the *specific task*.
- Filler like "be comprehensive, be constructive" — if the instruction is generic, delete it.

### Skills (`.claude/commands/<name>.md`)

A skill is a task-specific workflow that the user triggers by name. It is expanded into the conversation when invoked, not prepended every turn.

Each skill contains:

1. **What the skill does** — one paragraph.
2. **Procedure** — numbered steps the skill walks through.
3. **Shell commands** to invoke (with real paths, not pseudocode).
4. **Decision points** — where the skill stops and asks the user.

Should **not** contain:
- Content that already lives in `CLAUDE.md` (the skill already has access to it when invoked).
- Detailed agent behavior (the agent's own definition owns that).
- Generic Claude Code etiquette (parallel tool calls, read before write) — those belong in `CLAUDE.md` once, not in every skill.

## When to write a `description` in agent frontmatter

Agent descriptions are visible in the Task tool's `subagent_type` enum at session start. They help the LLM pick the right agent when *the LLM itself is choosing*. The rule:

> Only write a description if the LLM has to decide whether to dispatch this agent. If the agent is always dispatched by name from a workflow doc or a skill, the description is wasted context.

Apply this:

- `code-writer`, `code-reviewer`, `plan-writer`, `plan-reviewer` — **no description needed.** They are dispatched by name from the major/minor change workflow. Their role is obvious from the name.
- `arch-design` — **description needed.** It is dispatched only for specific architectural questions and the orchestrator has to decide when to use it.
- `canon-update`, `triage-subagent`, etc. — **description needed if ambiguous.**

When you do write one, it should describe **when to use** the agent, not what the agent is. "Architecture design for cross-agent coordination and structural decisions" is useful; "Architecture design agent that designs architecture" is not.

## The no-duplication rule

Before adding content to a file, search the rest of the template for anything that says the same thing. If it exists:

- **Delete the new addition** and reference the existing location, or
- **Promote** the content to a higher layer if it should apply more broadly, or
- **Reconcile drift** if the two versions say subtly different things.

Duplication is not just a token cost. It is a drift trap: two copies will diverge over time, and agents reading different copies will behave differently. Single source of truth is a quality mechanism first, a cost mechanism second.

## The "two strikes, one screen" rule for CLAUDE.md

Per Anthropic's own Claude Code guidance: `CLAUDE.md` should grow only when the same issue has bitten you twice, and it should never exceed one screen (~80–100 lines). If you need to add something new and the file is already full, something old has to come out.

When something comes out of `CLAUDE.md`, it usually moves to `docs/conventions.md` — not deleted, just demoted from every-turn to on-demand.

## Keeping the hierarchy honest

A quarterly (or per-slice, when you feel friction) check:

1. Read each `CLAUDE.md` end to end. Delete anything stale, anything restated from another file, anything you don't remember adding.
2. Scan agent definitions for sentences that restate `CLAUDE.md` or the workflow doc. Delete them.
3. Scan workflow docs for sentences that describe what each agent *does* (vs. when it runs). Delete them.
4. If `docs/conventions.md` has sections that are now obsolete, delete them.
5. If two files reference the same rule, pick one and delete the other.

The goal isn't minimalism for its own sake. The goal is that every claim about how the project works lives in exactly one place, so a reader (human or agent) always knows where to look and never has to reconcile conflicting versions.
