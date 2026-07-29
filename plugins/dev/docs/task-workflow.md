# The task workflow — slices, tasks, and the runner

How a change moves from idea to merged code. Three operator-initiated sessions and two scripts
carry it; this doc is the contract they share — the slice folder layout, the task rules, the
verdict schema, and who escalates to whom. The scripts' own mechanics live next door:
[plan-loop.md](plan-loop.md), [task-runner.md](task-runner.md), [runner-state.md](runner-state.md),
and [agent-dispatch.md](agent-dispatch.md).

1. **`/dev:triage`** turns findings and requests into **slice folders** under
   `<spec-repo>/slices/backlog/NNN_slug/`, each holding a self-contained `slice.md`.
2. **`/dev:plan-slice`** settles the design with the operator, then runs
   `${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py` to a reviewed task breakdown; the session verifies
   fidelity, presents it, and `git mv`s the folder up into `slices/NNN_slug/`.
3. **`/dev:run-slice`** launches `${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py` as a background
   shell, handles bail-outs, and closes out with `${CLAUDE_PLUGIN_ROOT}/tools/close_slice.py`
   (which moves the folder to `slices/completed/` and the spec README's entry Pending →
   Completed, staging by name and leaving the commit to the session).

**Files are durable; sessions are ephemeral.** No long-lived session drives the work — the scripts
do. Every agent they spawn is a fresh headless `kc session` that reads its inputs from the slice
folder, does one job, writes a machine-readable verdict, and exits. Rulings and findings travel
through the slice folder's files, never through relayed prompt content.

**Two repos, two placeholders.** `<spec-repo>` is the path in the target repo's `CLAUDE.md`
`Spec repo:` line — where slices, tasks, and the runs' state and logs live. The **target code
repo** is where the runner branches and merges (its git root). A task's `project` is one of the
target repo's components, as named by `kc project list` (from `.kubecoder/project.yaml`); the
project contract is [project-contract.md](project-contract.md).

The plugin's agent definitions are the normative instructions for the agents themselves; this doc
states only what the scripts and the folder guarantee.

## Escalation ladder

Each level handles what the level below cannot; nothing skips a level.

1. **The scripts** count and enforce: round caps and budgets, task order, git mechanics, protocol
   validity, and the deterministic test gate (running `kc project test` and checking an exit code
   is counting, not judging). They never judge.
2. **Consult sessions** — fresh, agent-less, spawned by the task runner — judge: is the fix loop
   stuck, do these findings fund another round, is a flagged problem real. Triggered only when a
   bound is hit, an agent flags a problem, or a task merges.
3. **The `/dev:run-slice` session** investigates bail-outs: reads `bailout.json` and `state.json`,
   decides or defers, optionally authors new tasks (`/dev:write-task` in a sub-agent), relaunches
   with `--resume`.
4. **The operator** decides everything above that: scope changes, spec contradictions, pushes.

Agents never work around an environmental problem — a broken tool, a failing harness, a missing
credential. They stop and report `blocked`; screaming early is correct behavior.

## Slice folder layout

`/dev:triage` writes `slice.md` alone; `/dev:plan-slice` adds the planning artifacts and `tasks/`;
the runner adds everything under `state.json` and inside each task folder.

```
<spec-repo>/slices/NNN_slug/
  slice.md                     /dev:triage — the change request: numbered requirements in the
                               operator's words, the sources it absorbed, and any operator-given
                               API/spec definition at signature fidelity
  qa_log.md                    plan-scribe — the operator's planning rulings, verbatim
  grounding.md                 slice-grounder — the claim→source ledger every later pass reads
                               instead of re-deriving (grounding-ledger.md)
  plan_brief_*.md              slice-grounder / plan-briefer — the evidence behind one operator
                               choice; written for the interactive session, never by the loop
  acceptance_criteria.json     plan-writer — {"criteria": [{id: "CT-NN", area, description}]}
  api_contract.json            plan-writer, when the slice changes a wire surface
  verification.json            {"items": [{id: "VNN", source, area, description, verdict,
                               rationale, evidence}]} — seeded by the plan loop, filled at close-out
  plan_review_r<N>.md          plan-reviewer round N
  plan_questions_r<N>.md       plan-writer round N blocking questions
  plan_writer_result_r<N>.json / plan_review_result_r<N>.json    planning verdicts
  plan_state.json / plan_log.txt / plan_bailout.json             plan-loop-owned
  tasks/
    NN[a]_slug/                two-digit prefix, sorted lexicographically, run strictly in order
      task.json                metadata (below)
      plan.md                  plan-writer — this task's implementation plan
      grounding.md             code-writer — the per-task ledger for behavior-describing prose
      gate_r<N>.log            full output of the runner's Nth gate run for this task
      test_results_r<N>.md     test-fixer round-N escalation (non-trivial failures only)
      code_review_r<N>.md      code-reviewer round N
      writer_result_r<N>.json / fixer_result_r<N>.json / review_result_r<N>.json   verdicts
      consult_<N>.{json,md}    task-scoped consult decisions
  test_agent_result_r<N>.json  final-verification verdict
  test_findings.md             final-verification findings
  consult_<N>.{json,md}        slice-scoped consult decisions (final verification)
  state.json / log.txt / bailout.json                            runner-owned
```

The consult counter is one sequence per slice, so `consult_<N>` numbers never collide across task
folders. Every artifact here lives in the spec repo — one working tree, possibly shared with
parallel sessions: stage files **by name**, never `git add -A`.

## task.json

```json
{
  "id": "01",
  "slug": "api_surface",
  "project": "backend",
  "grade": "standard",
  "title": "One-line imperative title",
  "summary": "2-4 sentences: what this task delivers and why it is its own task."
}
```

`project` is exactly one of the target repo's components — the names `kc project list
--output=json` reports (from `.kubecoder/project.yaml`); the runner validates it against that set.
It selects the session's working directory (the component's effective cwd) and the test gate, and
**a task never spans projects**: cross-project work is consecutive tasks with the interface pinned
at planning time, producer first.

`grade` routes the first implementation round's model — see
[agent-dispatch.md](agent-dispatch.md#model-routing-d177).

Execution order is the folder prefix, sorted as text. Two digits keep task ids visually distinct
from three-digit slice numbers; there is no dependency graph, so the planner orders tasks such that
each may assume every lower-numbered task is merged. A task inserted mid-run takes a letter suffix
(`04a_slug` sorts between `04` and `05`) rather than renumbering anything.

## The verdict contract

Every script-spawned agent MUST end its session by writing the JSON verdict file named in its
dispatch prompt — in the task folder for the runner's dev agents, the slice folder for the plan
loop's and for final verification.

```json
{
  "outcome": "<role-specific enum>",
  "summary": "1-3 sentences for the log and for consults",
  "details": "optional relative path to a write-up beside the verdict"
}
```

The scripts read `outcome` and `summary`; `details` is for the human and the consult that reads the
write-up.

| Role | Outcomes |
|---|---|
| plan-writer | `done` \| `questions` \| `blocked` |
| plan-reviewer | `go` \| `issues` \| `questions` |
| code-writer | `done` \| `blocked` \| `missing-task` |
| test-fixer | `clean` \| `issues` \| `blocked` |
| code-reviewer | `signoff` \| `issues` \| `critical` |
| test-agent | `clean` \| `findings` \| `blocked` |
| consult | one of the actions its prompt offered |

An outcome outside its role's set is treated as no verdict at all. The plan-reviewer additionally
writes per-class counts `material` / `needs_ruling` / `hygiene`, of which the loop reads only
`hygiene`; a consult may write a longer `consult_<N>.md` beside its JSON.

- `blocked` — an environmental or premise problem the agent must not work around. Details go in a
  write-up in the task folder.
- `missing-task` (code-writer only) — the task needs work outside its own project first, e.g. a
  backend test endpoint a frontend task's tests require. The details name what is missing; the
  runner bails so the `/dev:run-slice` session can author that task.

Two protocol rules both scripts enforce identically:

- **One verdict nudge.** A missing, unparseable, or out-of-enum verdict after the session ends
  gets exactly one resume-nudge asking it to write the verdict now. Still invalid after that is a
  protocol failure — the runner routes it to a consult as `blocked`, the plan loop bails.
- **One commit nudge.** A session that ends with uncommitted work is resumed once and asked to
  commit; still dirty is a bail-out. The two scripts check different trees — the runner checks the
  target repo's worktree after each writer and fixer, the plan loop checks the slice folder in the
  spec repo, excluding its own `plan_state.json` / `plan_log.txt` / `plan_bailout.json`. Neither
  ever commits an agent's leftovers itself, which is what makes a reset safe: the writer's work is
  always committed before a fixer runs, so "drop the fixer's changes" is a clean
  `git reset --hard` to the last writer commit.
