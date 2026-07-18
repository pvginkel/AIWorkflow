---
name: plan-slice
description: The refinement session — interactively bottom out a triaged slice with the operator and break it into 3-6 ordered, project-local tasks (plan-writer + plan-reviewer) with acceptance criteria seeded 1:1 from the slice's requirements. The task runner executes the result.
argument-hint: <slice-number-or-path>
---

# Plan Slice

Break a slice into its executable task breakdown. **Required input: a slice folder** produced by
`/triage` (`<spec-repo>/slices/backlog/NNN_slug/` with a `slice.md`). Argument: the slice
number or path. This is the interactive planning session — the operator is present; everything downstream of
you runs unattended, so what you freeze here is the only dispatch context the dev agents get.

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line (a machine-checkable entry).
The workflow contract (folder layout, task rules, verdict schema) is
`${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md`; the project contract (what `CLAUDE.md` and
`.kubecoder/project.yaml` must provide) is `${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`.

**Preflight (step 0).** Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for plan` and relay
its message verbatim if it exits non-zero — it bails when the manifest or the `Spec repo:` entry is
missing (you cannot allocate a plan with nowhere to write it). A silent exit 0 means every gate
passed.

**Normative keywords.** MUST / MUST NOT / SHOULD / SHOULD NOT / MAY in `slice.md` and the
artifacts you produce carry their RFC 2119 meaning.

## Your role

You are a **coordinator and the PO's advocate**, not the technical architect. This is the
**refinement session** — the dev team going through the idea with the PO. Triage recorded the ask
in the operator's words, asked only comprehension questions, and read no code; grounding each
requirement and working interactively toward the better solution happens **here**. Your value:

1. **Faithful capture** — every explicit request in `slice.md` becomes an acceptance criterion and
   lands in exactly one task. No silent substitution, ever; infeasibility is discussed, not
   designed around.
2. **Completeness** — nothing falls between tasks; cross-project interfaces are pinned before
   execution.
3. **Push-back** — feasibility concerns and pattern conflicts surface now, to the operator.

The plan-writer reads the code and designs the breakdown; the plan-reviewer attacks it. You drive
them and validate fidelity.

**Stay idle while a sub-agent works.** The sub-agent mechanism notifies you when each one finishes.
Do **not** poll for its progress — no `ls` of the slice folder, no `grep`/`test -f` for an artifact
it has not written yet, no reading a file it is mid-write. Polling burns tokens to learn nothing the
notification won't tell you for free, and a half-written artifact is worse than no artifact. Wait,
then read what it produced. While you wait, the only useful work is grounding **you** need for the
fidelity check (step 3) — never a check on the agent.

## Procedure

### 1. Absorb the slice

Read `slice.md` and every attachment in the slice folder. Its numbered requirements list is the
authoritative statement of intent, in the operator's own words — and deliberately thin. Bottoming
the ask out is yours, with the operator: walk the requirements that leave the *how* open, and bring genuine choices, conflicts
with established patterns (docs, decisions, API contracts), and anything your reading reveals
that changes the shape. Don't relitigate settled input — a requirement that arrives pinned (a
debugged root cause, an operator-settled design) is absorbed as spec, not reopened. Treat every
claim or citation the slice carries as **unverified input**. Log every exchange to `qa_log.md`
in the slice folder (`Q:`/`A:` pairs).

### 2. Dispatch the plan-writer

Dispatch the `plan-writer` sub-agent with the slice folder path. It produces `tasks/NN_slug/`
(each `task.json` + `plan.md`), `acceptance_criteria.json`, and `api_contract.json` when wire
surfaces change. If it returns blocking questions, answer what `slice.md` answers; take the rest
to the operator (and log them).

If the breakdown wants more than 10 tasks, stop and discuss splitting the slice with the operator
(a follow-up slice gets its own folder via `/triage`'s allocator conventions).

Triage bundles on the asks as written — bundling mistakes are expected and yours to fix:
**split** a slice, **kick an item back** to the backlog as its own slice, or **pull in** an
obviously-adjacent backlog slice. Discuss the re-shape with the operator in-session;
follow-up folders come from the allocator.

### 3. Verify fidelity yourself

The slice's numbered requirements are the **starting acceptance-criteria set, 1:1** — each becomes
a criterion carrying the requirement's wording, and a criterion may drop or re-word a requirement
**only on an explicit operator ruling logged in `qa_log.md`**. Walk the list requirement by
requirement: a matching, testable criterion in the operator's wording, and a task that owns it.
Operator-provided API/spec definitions survived at signature-level fidelity. This check is yours —
do not delegate it.

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
owning `docs/` topic doc per your project's documentation model (e.g. a decision index the spec
repo maintains). Commit the slice folder to the spec repo as pieces settle — stage files **by
name** (shared working tree).

### 8. Promote the slice out of the backlog

Once the plan is approved and committed, move the slice from the backlog into the active set so
`/run-slice` can pick it up:

- `git mv <spec-repo>/slices/backlog/NNN_slug <spec-repo>/slices/NNN_slug` and commit
  the move (stage by name).
- Move the slice's Kanban card from **To Do** to **Ready**.

The slice is now Ready; running it is a separate operator instruction.

## Quality checklist

- [ ] Every numbered requirement in `slice.md` → acceptance criterion (1:1, operator's wording) +
      owning task; any dropped or re-worded requirement has an operator ruling in `qa_log.md`.
- [ ] Tasks are project-local, ordered producers-first, 3–6 (max 10), each independently
      testable and PR-sized.
- [ ] Cross-project interfaces stated identically in both plans, at signature level.
- [ ] Plans carry verified `file:line` citations, no code, no prescribed symbol names.
- [ ] `plan_review.md` decision is GO.
- [ ] `verification.json` seeded; `qa_log.md` holds the planning Q&A.
- [ ] Decisions lodged in docs; everything committed to the specs repo.
