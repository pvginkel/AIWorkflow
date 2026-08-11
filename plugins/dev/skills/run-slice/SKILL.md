---
name: run-slice
description: Execute a planned slice — launch ${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py in the background, correct errors, relay operator questions into plan.md, close out. The loop drives; this session has exactly four jobs.
argument-hint: <slice-number-or-path>
---

# Run Slice

Execute a planned slice. Argument: the slice number (e.g., `074`). Requires a slice folder under
`<spec-repo>/slices/` that `/dev:plan-slice` has filled with a `plan.md` phase queue and
`verification.json` — if there is no plan, stop and tell the operator to run `/dev:plan-slice` first.

`<spec-repo>` is the path in your `CLAUDE.md`'s `Spec repo:` line. Run this from the **target
code repo**. The loop's mechanics are `${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md`; what it records
is `${CLAUDE_PLUGIN_ROOT}/docs/runner-state.md`.

**The loop drives the slice, not you.** `${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py` owns the whole
flow — every phase's executor→gate→review→merge round, the completion consult, the test phase
(it holds the devlock; pushing and rolling dev for verification under that hold is
pre-authorized), and the doc phase. You have exactly four jobs; an uneventful slice needs
nothing from you between launch and close-out.

## Job 1 — start the loop

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/preflight.py --for run`. On a non-zero exit, **relay
   its message verbatim** and stop — fix the root cause only if it is clearly environmental,
   otherwise notify the operator. A dirty working tree is never yours to clean up.
2. Advance the slice's tracker card (`[NNN] …`, planned) to **in progress**.
3. Launch, in the background (`run_in_background: true`):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py run <spec-repo>/slices/<SLICE_DIR>
   ```

   All output goes to `<slice_dir>/log.txt` — do **not** read or tail it; the background-task
   mechanism notifies you when the loop exits, and the outcome lives in the exit code,
   `state.json`, and `bailout.json`. The loop's stdout is a deliberately terse progress feed —
   one timestamped line per job start and phase merge; it is all the mid-run visibility you
   need. Grep the log only when diagnosing a specific bail.
   (`--resume` continues after any bail; `--dry-run` validates the plan without running.)

## Job 2 — errors (exit 3)

Read `bailout.json` and the referenced files **before deciding anything**. Diagnose the root
cause. Fix it only when it is genuinely environmental or mechanical-at-the-workflow-level (a
stale checkout, a dead service, a wrong path in the plan's `Target:`) — never by telling an agent
to work around it, never by patching application code yourself, and never by re-running suites or
re-deriving an agent's work in your own context. Then relaunch with `--resume`. If the cause is
unclear or the fix isn't yours, summarize and notify the operator.

## Job 3 — operator questions (exit 4)

The loop paused on something only the operator can decide (`bailout.json` carries the question —
an executor's `question` verdict, a contested plan edit, an exhausted follow-up generation). Ask
the operator, then **write the answer into plan.md's requirements/rulings section — in the
operator's words — and commit it (stage by name) before resuming**: the next executor reads the
plan, not this chat. A ruling that corrects an earlier one **replaces it in place** — no
correction-chains; git holds the history. Then relaunch with `--resume`.

## Job 4 — close out (exit 0)

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_slice.py <slice_dir>` (moves the README slice
   entry Pending → Completed and `git mv`s the folder to `slices/completed/`, staging by name);
   commit together with the slice artifacts, **including `state.json` and `log.txt`** (the run's
   who-did-what record; only a stale `bailout.json` is dropped).
2. File `state.json`'s `cards` list to the issue tracker (per the host convention) — the
   loop recorded every advisory finding disposition there. Dedupe entries that state the same
   finding, then: behavioural and design findings file **one card each**; mechanical trivia —
   comment/formatting residue, cosmetic polish, test-shape nits — batches into **one
   `Slice NNN residuals` card** listing the items. What goes where is the only judgment call
   here; the list itself is a mechanical read.
3. Advance the tracker card to **done**, notify the operator per the host's notification
   convention, and report short: per-phase rounds from `state.json`, test/doc phase outcomes,
   the cards filed, anything owed.

Nothing else is yours: no test running, no pre-exploration, no re-derivation of agent results,
no suite re-runs, no doc work. **Escalate, don't absorb** — if you find yourself dispatching dev
agents or fixing code, stop; that work belongs in a phase the loop executes.

## Notes

- **Notifications:** notify on completion, on anything you defer to the operator, and on nothing
  else.
- **Shared spec tree:** commits from other sessions appearing in `<spec-repo>` for your slice
  usually mean a parallel session accidentally swept your files into its commit. Stage by name;
  build on the latest state.
- **The suite is green before every slice.** A failure during the run is the slice's regression —
  never accept "flaky" or "pre-existing" from anyone.
- **Production stays operator-gated.** The loop's devlock hold pre-authorizes the pushes the slice
  needs for dev verification — even one whose GitOps effects reach past dev (a shared chart
  reconciles every environment it deploys); promoting anything into production is the operator's
  separate, explicit decision, per the project's deploy-operations doc.
