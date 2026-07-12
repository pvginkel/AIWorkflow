---
description: Execute a planned slice: launch tools/ai_workflow/task_runner.py in the background, handle bail-outs (write-task + resume, or defer to the operator), and close out. The runner drives; this session only escalates.
---

# Run Slice

Execute a planned slice. Argument: the slice number (e.g., `074`). Requires a slice folder under
`../KubeCoderSpecs/slices/` that `/plan-slice` has already filled with `tasks/` — if there is no
task breakdown, stop and tell the operator to run `/plan-slice` first.

## What this skill does

**The task runner drives the slice, not you.** You launch
`tools/ai_workflow/task_runner.py` as a background shell, stay idle while it works, and act only
at the edges: preflight, bail-outs, and close-out. The runner spawns every dev session, enforces
the bounded loops, and consults fresh decision sessions on its own — an uneventful slice needs
nothing from you between launch and final report. The contract (loop, verdicts, bail-out reasons)
is [`docs/conventions/task-workflow.md`](../../docs/conventions/task-workflow.md).

## Step 1: Preflight

1. **Freshness.** The working copies can lag origin: `git fetch` and compare
   (`git rev-list --left-right --count origin/main...HEAD`) in this repo and the specs repo before
   concluding anything is missing. Fetch auth uses `$GIT_TOKEN` (see
   `docs/operations/deploy-operations.md` for the inline-credential-helper form).
2. **Environment.** Run `python3 scripts/preflight.py` (gates on a clean working tree, then syncs
   the workspace and collects the whole suite). Its output is deliberately minimal and reports
   solely through the exit code, so a silent exit 0 means every gate passed. On failure: do
   **not** work around it and do **not** start the runner — fix the root cause if it is clearly
   environmental, otherwise notify the operator with the output and stop. A dirty working tree is
   never yours to clean up: surface it to the operator.
3. **Board.** Move the slice's Kanban card (`[NNN] …`, in Ready) to **In Progress**.

## Step 2: Launch the runner

```bash
python3 tools/ai_workflow/task_runner.py run ../KubeCoderSpecs/slices/<SLICE_DIR>
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
   round-2 review findings, and final-verification findings a consult judged non-blocking. Create
   one Triage **Inbox** card (tagged `KubeCoder`) per flagged finding and raise them in your
   report; the operator decides whether any means rework.
2. **Independent verification:** dispatch the `slice-verifier` sub-agent with the slice directory
   and the slice's commit range, nothing else. Route `failed`/`uncertain` entries like findings
   (below) — author a fix task and relaunch — or escalate to the operator if you disagree with the
   verifier. (The verifier is on probation; note in your report whether it produced consequential
   dissent.)
3. Reconcile docs scoped to what the slice changed (drift between authored intent and what was
   built → fix the owning `docs/` topic or run `/update-docs` with a hint).
4. Move the README slice entry **Pending → Completed** (same single line) and
   `git mv` the slice folder to `slices/completed/`; commit with the slice artifacts, **including
   `state.json` and `log.txt`** (they name every agent session id + transcript path — the run's
   who-did-what record; only a stale `bailout.json` is dropped).
5. Move the Kanban card to **Done**, notify the operator
   (`python3 scripts/send_message.py --title "Slice <NNN>" "<summary>"`), and report: per-task
   rounds from `state.json`, verification outcome, flagged findings, anything owed.

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
- **`tester_limit` / `review_limit` / `consult_bail` / `verification_limit`** — a consult chose to
  stop or a cap ran out. Read the consult's reasoning. If a clear, small decision unblocks it
  (adjust a task plan, add guidance to the task folder, drop a bad direction), make it, record it
  in the task folder, and relaunch with `--resume`. Otherwise summarize the situation and defer to
  the operator (push notification).

**Escalate, don't absorb.** You are the escalation path, not a fallback driver — if you find
yourself dispatching dev agents or fixing code, stop; that work belongs in a task the runner
executes.

## Slice test plan

Once the slice's tasks are all merged (Exit 0 above, or the decision was made to proceed otherwise),
run the project's **slice test plan** — its deploy-verification procedure. This skill is shared
across projects and owns no project's testing strategy, so the whole plan — whether it pushes,
what it checks, how findings resolve — lives in the project's docs:
[`docs/operations/slice-test-plan.md`](../../docs/operations/slice-test-plan.md).

## Notes

- **Notifications:** notify on completion, on a bail-out you defer to the operator, and on nothing
  else (`scripts/send_message.py`).
- **Shared specs tree:** commits from other sessions appearing in `../KubeCoderSpecs` for your
  slice usually mean a parallel session accidentally swept your files into its commit — it is not
  a sign another agent is working your slice. Stage by name; build on the latest state.
- **The suite is green before every slice.** A failure during the run is the slice's regression —
  the runner's agents are told the same; never accept "flaky" or "pre-existing" from anyone.
- **Never push, never deploy, without the operator's explicit green light.** A finished slice, a
  green suite, or "merge with origin" is not that green light.
