---
name: run-slice
description: Execute a planned slice — launch the plugin's task_runner.py in the background, handle bail-outs (write-task + resume, or defer to the operator), and close out. The runner drives; this session only escalates.
argument-hint: <slice-number-or-path>
---

# Run Slice

Execute a planned slice. Argument: the slice number (e.g., `074`). Requires a slice folder under
`<spec-repo>/slices/` that `/plan-slice` has already filled with `tasks/` — if there is no
task breakdown, stop and tell the operator to run `/plan-slice` first.

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line. Run this from the **target code
repo** (its git root is where the runner branches and merges); the slice folder lives in the spec
repo.

## What this skill does

**The task runner drives the slice, not you.** You launch
`${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py` as a background shell, stay idle while it works, and
act only at the edges: preflight, bail-outs, and close-out. The runner spawns every dev session,
enforces the bounded loops, and consults fresh decision sessions on its own — an uneventful slice
needs nothing from you between launch and final report. The contract (loop, verdicts, bail-out
reasons) is `${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md`.

## Step 1: Preflight

1. **Environment + contract.** Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run`.
   It is the gate: `kc` on PATH, a valid manifest, the three `CLAUDE.md` pointers (`Spec repo:`,
   `Slice testing strategy:`, `Design philosophy:`) present with their target docs existing, a
   clean working tree, and a baseline `kc project build`. Its output is deliberately minimal and
   reports solely through the exit code, so a silent exit 0 means every gate passed. On a non-zero
   exit, **relay its message verbatim** and stop: do **not** work around it and do **not** start the
   runner — fix the root cause only if it is clearly environmental, otherwise notify the operator.
   A dirty working tree is never yours to clean up: surface it to the operator. (The runner does not
   re-run preflight — this is the gate.)
2. **Board.** Move the slice's Kanban card (`[NNN] …`, in Ready) to **In Progress**.

## Step 2: Launch the runner

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py run <spec-repo>/slices/<SLICE_DIR>
```

Run it in the background (`run_in_background: true`). All runner and session output goes to
`<slice_dir>/log.txt` — stdout stays quiet so nothing floods your context. Do **not** read or tail
the log; the background-task mechanism notifies you when the runner exits, and the outcome lives
in the exit code, `state.json`, and `bailout.json`. Grep `log.txt` only when diagnosing a specific
bail-out. (The operator can `tail -f` it, or pass `-v` to echo it to stdout in a manual run.)
Options: `--resume` continues after a bail-out or crash (it reattaches the interrupted agent
session when one was in flight); `--dry-run` lists the tasks without running.

## Step 3: Handle the exit

### Exit 0 — slice complete → close out

1. Read `state.json` (history, rounds) and note any `flagged_findings` — tasks merged with open
   round-2 review findings, and final-verification findings a consult judged non-blocking. File one
   issue-tracker item per flagged finding (per the host's issue-tracker convention) and raise them
   in your report; the operator decides whether any means rework.
2. **Independent verification:** dispatch the `slice-verifier` sub-agent with the slice directory
   and the slice's commit range, nothing else. Route `failed`/`uncertain` entries like findings
   (below) — author a fix task and relaunch — or escalate to the operator if you disagree with the
   verifier. (The verifier is on probation; note in your report whether it produced consequential
   dissent.)
3. Reconcile docs scoped to what the slice changed (drift between authored intent and what was
   built → fix the owning `docs/` topic, or run a docs-update pass if your project provides one).
4. Move the README slice entry **Pending → Completed** (same single line) and
   `git mv` the slice folder to `slices/completed/`; commit with the slice artifacts, **including
   `state.json` and `log.txt`** (they name every agent session id + transcript path — the run's
   who-did-what record; only a stale `bailout.json` is dropped).
5. Move the Kanban card to **Done**, notify the operator per the host's notification convention,
   and report: per-task rounds from `state.json`, verification outcome, flagged findings, anything
   owed.

### Exit 3 — bail-out → investigate, then decide or defer

Read `bailout.json`, the referenced consult/writeup files, and `state.json` **before deciding
anything**. Then route by `reason`:

- **`missing-task`** — the writer needs work outside its project (e.g. a test endpoint). Dispatch
  a sub-agent to author the missing task folder per `/write-task`, ordered before the blocked
  task (a letter suffix like `04a` inserts it there), then relaunch with `--resume`.
- **`test_findings`** — a consult already judged these findings **blocking** (non-blocking ones
  land in `flagged_findings` without a bail). Read `test_findings.md` and the consult's reasoning;
  dispatch a sub-agent per `/write-task` to turn the findings into fix task(s) (grouped per
  project), then relaunch with `--resume`. If you disagree with the consult's blocking call,
  defer to the operator instead. The runner caps verification at 3 rounds — the 4th bails to the
  operator, who may grant another round or wrap up.
- **`blocked` / `timeout` / `protocol_failure`** — an environmental or tooling problem. Diagnose
  the root cause. Fix it only when it is genuinely environmental (a stale checkout, a dead
  service) — never by telling an agent to work around it, and never by patching application code
  yourself. If the cause is unclear or the fix isn't yours, notify the operator and stop.
- **`gate_red`** — the task reached merge with a red test gate, so the runner refused to merge it
  (a red gate can stall a task; it can never ship). This is a real failure the writer/fixer loop
  could not close, not an environmental one — usually a fix-round consult chose `proceed_to_review`
  and nothing turned the gate green afterwards. Read the last `gate_r<N>.log` named in the bail
  details and the `test_results_r*.md` escalations. If the failure needs a decision the loop could
  not make (a task plan is wrong, an interface moved, the fix belongs in another task), make it,
  record it in the task folder, and relaunch with `--resume`. Never make the gate green by
  weakening what it checks; if the fix isn't a small clear decision, defer to the operator.
- **`tester_limit` / `review_limit` / `consult_bail` / `verification_limit`** — a consult chose to
  stop or a cap ran out. Read the consult's reasoning. If a clear, small decision unblocks it
  (adjust a task plan, add guidance to the task folder, drop a bad direction), make it, record it
  in the task folder, and relaunch with `--resume`. Otherwise summarize the situation and defer to
  the operator (push notification).

**Escalate, don't absorb.** You are the escalation path, not a fallback driver — if you find
yourself dispatching dev agents or fixing code, stop; that work belongs in a task the runner
executes.

## Slice testing strategy

Once the slice's tasks are all merged (Exit 0 above, or the decision was made to proceed otherwise),
run the **slice testing strategy defined for this project** — its deploy-verification procedure.
This plugin is shared across projects and owns no project's testing strategy, so the whole plan —
whether it pushes, what it checks, how findings resolve — lives in a project-owned doc. Resolve it
through your `CLAUDE.md`'s `Slice testing strategy:` pointer (preflight has already confirmed the
pointer and its target doc exist); this skill never names the doc.

## Notes

- **Notifications:** notify on completion, on a bail-out you defer to the operator, and on nothing
  else — per the host's notification convention.
- **Shared spec tree:** commits from other sessions appearing in `<spec-repo>` for your
  slice usually mean a parallel session accidentally swept your files into its commit — it is not
  a sign another agent is working your slice. Stage by name; build on the latest state.
- **The suite is green before every slice.** A failure during the run is the slice's regression —
  the runner's agents are told the same; never accept "flaky" or "pre-existing" from anyone.
- **Never push, never deploy, without the operator's explicit green light.** A finished slice, a
  green suite, or "merge with origin" is not that green light.
