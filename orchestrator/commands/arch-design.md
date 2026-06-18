---
description: Design a well thought out architecture with options and trade-offs, grounded in the project's code base. Proactively suggest to the user to use this skill when creating complex slices that involve cross-cutting decisions or new patterns.
---

# Architecture Design

Produce a grounded architecture design document for a specific question. Argument: a short description of the architectural question (e.g., "how should session decomposition work across backend and portal").

## When to use

Use this skill when a slice or feature involves:

- Cross-subproject coordination (backend + frontend + portal need to agree on an approach).
- New patterns not covered by existing conventions (a new SSE event type, a new delivery pattern, a new storage strategy).
- Structural changes that affect multiple modules or services.
- Decisions where there are genuine trade-offs the user should weigh before committing.

**Do not use** for:
- Slices that follow established patterns — the dev agent's planning phase handles those.
- Implementation-level decisions within a single subproject (callback threading, DI wiring).
- Questions that are answered by `docs/conventions.md` or `docs/architecture_decisions.md`.

## Procedure

### Step 1: Frame the question

From the user's input, formulate a specific architectural question. A good question has:

- A clear subject (which code, module, or concern is being designed).
- A clear scope (what decisions need to be made).
- Context pointers (which slice, which existing code).

If the input is too vague, ask the user to narrow it before proceeding.

### Step 2: Gather requirements

Ask the user for their requirements — the things the design must deliver. These become fixed constraints for the agent. If the user has already stated them (e.g., in a slice overview), extract them verbatim.

### Step 3: Dispatch the arch-design agent

Launch the `arch-design` agent with:

- **Question** — the specific architectural question.
- **Requirements** — the user's stated requirements, listed as fixed constraints.
- **Context** — point to the relevant docs and code. Include architecture decisions (`docs/architecture_decisions.md`), conventions (`docs/conventions.md`), and any slice-specific documents.
- **Output path** — where the design should be written (typically `{{ specs_repo_path }}/slices/<SLICE_DIR>/design_<area>.md`).

### Step 4: Review with the user

Present the design document to the user. Walk through:

- The decisions identified and the recommended options.
- Any risks flagged.
- Open questions that need the user's input.

Wait for the user to review and approve the design before referencing it in slice briefs or proceeding with implementation.

### Step 5: Reference in slice work

Once approved, reference the design document from the relevant slice briefs so dev agents can read it during their planning phase.
