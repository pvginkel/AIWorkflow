---
description: Interactively break a triaged slice into 3-6 ordered, project-local tasks (plan-writer + plan-reviewer) with acceptance criteria and a seeded verification log. The task runner executes the result.
---

# Plan Slice

Break a slice into its executable task breakdown. **Required input: a slice folder** produced by
`/triage` (`../KubeCoderSpecs/slices/backlog/NNN_slug/` with a `slice.md`). Argument: the slice
number or path. This is the interactive planning session — the operator is present; everything downstream of
you runs unattended, so what you freeze here is the only dispatch context the dev agents get.

The workflow contract (folder layout, task rules, verdict schema) is
[`docs/conventions/task-workflow.md`](../../docs/conventions/task-workflow.md).

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in `slice.md` and the
artifacts you produce carry their RFC 2119 meaning.

## Your role

You are a **coordinator and the PO's advocate**, not the technical architect. Your value:

1. **Faithful capture** — every explicit request in `slice.md` becomes an acceptance criterion and
   lands in exactly one task. No silent substitution, ever; infeasibility is discussed, not
   designed around.
2. **Completeness** — nothing falls between tasks; cross-project interfaces are pinned before
   execution.
3. **Push-back** — feasibility concerns and pattern conflicts surface now, to the operator.

The plan-writer reads the code and designs the breakdown; the plan-reviewer attacks it. You drive
them and validate fidelity.

## Procedure

### 1. Absorb the slice

Read `slice.md` and every attachment in the slice folder. It is the authoritative statement of
intent — triage already clarified it with the operator. Do not re-interview; return to the
operator **only on a genuine delta**: a conflict with an established pattern (docs, decisions,
API contracts), an ambiguity the slice does not settle, or something your reading reveals that
changes the shape. Log every exchange to `qa_log.md` in the slice folder (`Q:`/`A:` pairs).

### 2. Dispatch the plan-writer

Dispatch the `plan-writer` sub-agent with the slice folder path. It produces `tasks/NN_slug/`
(each `task.json` + `plan.md`), `acceptance_criteria.json`, and `api_contract.json` when wire
surfaces change. If it returns blocking questions, answer what `slice.md` answers; take the rest
to the operator (and log them).

If the breakdown wants more than 10 tasks, stop and discuss splitting the slice with the operator
(a follow-up slice gets its own folder via `/triage`'s allocator conventions).

### 3. Verify fidelity yourself

Walk `slice.md` request by request: each explicit ask has a matching, testable criterion worded as
the request was made, and a task that owns it. Operator-provided API/spec definitions survived at
signature-level fidelity. This check is yours — do not delegate it.

### 4. Dispatch the plan-reviewer

Dispatch the `plan-reviewer` sub-agent (it writes `plan_review.md` with a GO/NO-GO block). Route
findings back to the plan-writer and re-review until GO — typically one round; if it takes more
than two, bring the contested points to the operator.

### 5. Seed the verification log

Create `verification.json` from `acceptance_criteria.json` — one entry per criterion, in order:

```json
{"items": [{"id": "V01", "source": "ac", "area": "<criterion area>",
            "description": "CT-1: <verbatim AC description>",
            "verdict": null, "rationale": "", "evidence": []}]}
```

Append `source: qa_correction` entries whenever a planning answer overrides a direction the
breakdown was taking (the bar is direction change, not clarification).

### 6. Present to the operator

Summarize: the tasks (id, project, title, one line each), the acceptance criteria, open questions,
and any A/B decisions made with their grounds. Wait for approval; fold corrections back through
steps 2–4. Do **not** start `/run-slice` — running is a separate operator instruction.

### 7. Lodge decisions and commit

Decisions or conventions the slice establishes are project documentation: write each into the
owning `docs/` topic doc and its row in the thin `DNNN` index (`../KubeCoderSpecs/decisions.md`),
per [`docs/documentation-model.md`](../../docs/documentation-model.md). Commit the slice folder to
the specs repo as pieces settle — stage files **by name** (shared working tree).

### 8. Promote the slice out of the backlog

Once the plan is approved and committed, move the slice from the backlog into the active set so
`/run-slice` can pick it up:

- `git mv ../KubeCoderSpecs/slices/backlog/NNN_slug ../KubeCoderSpecs/slices/NNN_slug` and commit
  the move (stage by name).
- Move the slice's Kanban card from **To Do** to **Ready**.

The slice is now Ready; running it is a separate operator instruction.

## Quality checklist

- [ ] Every explicit request in `slice.md` → acceptance criterion + owning task.
- [ ] Tasks are project-local, ordered producers-first, 3–6 (max 10), each independently
      testable and PR-sized.
- [ ] Cross-project interfaces stated identically in both plans, at signature level.
- [ ] Plans carry verified `file:line` citations, no code, no prescribed symbol names.
- [ ] `plan_review.md` decision is GO.
- [ ] `verification.json` seeded; `qa_log.md` holds the planning Q&A.
- [ ] Decisions lodged in docs; everything committed to the specs repo.
