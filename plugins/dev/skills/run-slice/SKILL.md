---
name: run-slice
description: The run of a planned slice, as a stage Pilot runs — a headless session that launches ${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py detached and waits on it inside its turn, registers what the run asks as documents, carries the answers back into the run, and at the run's end registers the close-out and carries out its answers. Started by a work item whose brief opens `/dev:run-slice <slice>`; without Pilot, the operator starts it the same way and writes the answers into the documents.
argument-hint: <slice-number-or-path>, then the brief
---

# Run Slice

The run of one planned slice, as a stage of Pilot. The contract every stage keeps — the brief,
the four ways a turn opens, the documents, the continuation, the clarification, the nudge and the
halt, the cards, the fallback without Pilot — is `${CLAUDE_PLUGIN_ROOT}/docs/pilot.md`. This skill
restates none of it: it says what the run does in each turn, and where the turn ends.

**The loop drives the slice, not you.** `run_loop.py` owns every phase's round, the completion
consult, the test phase (it holds the devlock and pushes, on the brief's grants or the
operator's word at the start's step 3), the doc phase and the wrap-up
(`${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md`). What it records is `${CLAUDE_PLUGIN_ROOT}/docs/runner-state.md`, and the close-out report is
`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`. This session launches, waits, registers, carries out
and commits. What has to be read — a bail to diagnose, an answer to carry into the plan, a
question about the slice — goes to a sub-agent pointed at the slice folder, so the session stays
small over a run that may last days.

Below, `<spec-repo>` is your `.aiworkflowrc`'s `spec_repo`, `<slice>` the slice folder under
`<spec-repo>/slices/` that the brief's first line names, `<task>` the brief's plan task, and a
tool is `python3 ${CLAUDE_PLUGIN_ROOT}/tools/<tool>`. Run from the target code repo.

- **A sub-agent runs in the foreground**, `run_in_background: false`, its report the Agent
  tool's result: a turn never ends to wait for one. Brief it with the slice folder, the paths it
  works on and the section of this skill it follows; it loads `/dev:writing` before it writes an
  ask, and hands back a receipt — what it did, with the commits, and the path of any store of
  asks it wrote.
- **The tracker** — the slice card, the cards a ruling asks for — speaks your host convention
  (`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md` §3). Load it before the first tracker call,
  yours or a sub-agent's: nothing in the pipeline loads it for you. The slice card's id is
  `slice.md`'s `issue:`.
- **An ask is a document**: a store under `<slice>/asks/` through `asks.py` (`init`, `append`,
  `render`), its words under `/dev:writing`, `--step <task>`, registered and backed as pilot.md
  § The documents says. Commit every store and document by name before the turn ends
  (`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`).

## The start

1. **Read the brief** (pilot.md § The brief): the slice from the first line, the ticket from its
   `Ticket:` line, `<task>` from "This work item serves plan task `<id>`". While
   `/work/.quota-limit-halt-requested` exists, do not start: end the turn saying so.
2. **Preflight**: `preflight.py --for run --slice <slice> --json`. A failure is an `action`
   document: its heading the fix in a line, its body the `fact`, the `fix` and the `output`,
   `--check "preflight --for run passes its <check> check"`. Register it and end the turn; its
   continuation starts again at this step. Fix nothing in the environment yourself: a dirty tree,
   a refused pull or a clone not made is the action's, and a restart ends this session. A failure
   with no slice folder to hold a document — no slice of that name in the spec repo, or no spec
   repo — ends the turn with its last line saying what failed and what fixes it.
3. **A push that deploys asks first.** Where the brief carries grants that do not pre-approve a
   push that deploys — Pilot's text while auto pilot is off — and preflight's pass says `push`
   is `enabled` and `deploys`, the run's pushes go to the operator before anything moves. The
   repos are the code repos `run_loop.py run <slice> --dry-run` names as `target=`, less any
   `## Push holds` already holds; the spec repo's push is pre-approved and is not asked.
   `asks.py init <slice> push --title "Slice <NNN>'s pushes" --step <task>`, then one
   `decision`: its headline the pushes in a line, its body the repos and that a push of theirs
   deploys, and its `--proposal` the line Agree pushes on ("Push this run's commits to
   `<repos>` as it goes, the test phase's push deploying them"). Render it, register it, commit
   `asks/`, and end the turn. It is asked once a run: a start that finds it answered goes on as
   the continuation says, and with every such repo held there is nothing to ask.
4. **Move the slice card** from planned to in progress, unless an earlier run moved it.
5. **Launch, detached**: `run_loop.py run <slice> --detach --step <task>`, with `--resume`
   where `<slice>/state.json` exists. It returns once the run holds the slice, its last line the
   `next:` wait. Refused (exit 2) because another driver holds the slice, the run is live: wait
   on it, `run_loop.py wait <slice>`. Any other refusal — no plan, an agent definition missing —
   is an `action` document as in step 2.
6. **Wait**, as below.

## The wait, and the run's end

Run the `next:` line's `wait` in the foreground, a plain Bash call; it returns within nine
minutes. Its exit code is a signal, and the lines it prints are all there is to read:

- **5, running** — run the new `next:` line again at once. Read nothing in between: no log, no
  state, no word to anyone.
- **6, gone** — the driver died with no exit recorded (a host restart, a kill): run the `next:`
  relaunch, then wait again.
- **0, ended** — act on `ended: exit <n>`:

| The run's exit | The turn |
|---|---|
| **0**, complete | [the close-out](#the-close-out) |
| **4**, a question | register the `document:` line's file; attach `plan.md`, and the phase's review where the bail names a phase; commit `asks/`; end the turn. With no `document:` line, put `bailout.json`'s details as a `question` document first. |
| **3**, an error, or **1** | [the diagnosis](#an-error) |
| **7**, halted | end the turn, its last line the `halted:` line |
| **130**, interrupted | someone stopped the driver: end the turn saying where; a nudge resumes it |

A `plugin_version` bail is relaunched from the installed `tools/` path `bailout.json` names, not
from `${CLAUDE_PLUGIN_ROOT}`: this session's copy is the stale one.

## An error

A sub-agent diagnoses the bail by this section. It reads `bailout.json` and the files it names
before deciding anything, `plan.md`'s requirements and rulings among them. The driver's message
is a diagnosis from a process that cannot see the plan, not an instruction: "push it, then
resume" over a repo the plan holds is a ruling losing to a state check, and what a working tree
says is never on its own evidence of the right move. When the plan and the driver disagree, the
plan wins and the operator decides. Then the root cause:

- **Mechanical or environmental, and the workflow's** — a stale checkout, a dead service, a wrong
  path in a `Target:`, the spec repo checked out off its base: the sub-agent fixes it and says
  so, and the session resumes (`run_loop.py run <slice> --resume --detach`) and waits.
- **Anything else** — the sub-agent writes a `decision` store: the diagnosis, and of retry (the
  resume, once what the diagnosis names is done), change the plan and stop here the options that
  are live, with its recommendation. The session renders and registers it, attaches
  `bailout.json` and the files it names, commits and ends the turn.

Never by telling an agent to work around it, never by patching application code, never by
re-running suites or re-deriving an agent's work.

## The continuation

A sub-agent reads back the documents Pilot's message names and carries them out by this section
and pilot.md § The continuation; the close-out's by [its own](#the-close-out-answered). A run's
ask is read back with `asks.py absorb <document>`, and its ruling lands by what it answers:

- **A question or a plan problem** — the ruling into `plan.md`'s requirements and rulings section
  in the operator's words, committed by name before the resume: the next writer reads the plan,
  not the document. A ruling that corrects an earlier one replaces it in place. One that forbids
  pushing a repo needs its `- <repo> — <why>` bullet under `## Push holds`; one that waives a
  target's gate, accepts a red sweep row or authorizes a promotion needs its `## Driver rulings`
  bullet (`gate`, `accept`, `prd`; `${CLAUDE_PLUGIN_ROOT}/docs/plan-template.md`). Without it the
  driver bails over the ruling again. A plan problem or a follow-up cap is corrected in `plan.md`
  as the ruling says.
- **The run's pushes** — `Agree`: the start goes on at its step 4. Any other answer holds every
  repo the ask named: a `- <repo> — <their words, quoted>` bullet each under `## Push holds`,
  committed by name, and then the start's step 4. The run pushes none of them, and the close-out
  carries each held push as an action (`${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md`, the push
  check). Deferred, the run is not started, as stop here leaves it.
- **A pre-run action, done** — one whose check is `manual`, or that has none, is struck in the
  close-out store, `close_out.py strike <slice> <id> --reason "done: '<their note>'" --by
  run-slice`, and committed; one with a check is the run's to evaluate when it resumes.
- **An environment or preflight action, done** — nothing to write: the start, or the run when it
  resumes, checks it again.
- **The error's decision** — retry resumes; change the plan lands as a ruling does above, then
  the resume. **Stop here** lands as a ruling too, and the run stays stopped where it bailed,
  resumable by a later `/dev:run-slice` of the slice; the turn ends. Nothing is registered for the
  close-out of a run that has not ended.
- **An ask the run waits on, deferred** — the run stays stopped, as stop here leaves it.

Then the session resumes the run (`run_loop.py run <slice> --resume --detach`) and waits. What the
sub-agent could not carry out as ruled comes back as a store of asks, which the session renders,
registers and ends the turn on instead.

## The close-out

At exit 0, in this order:

1. `slice_cost.py <slice> --write-state` — the slice's cost into `state.json`. Say its warnings
   in the turn's last line; never hand-edit the numbers.
2. `close_slice.py <slice>` — the README entry to Completed, the folder `git mv`ed to
   `slices/completed/`, `run.lock` deleted, all staged by name. Below, `<slice>` is the folder at
   its new path. No document of the slice is open at exit 0, so the move is safe (pilot.md § The
   documents).
3. `close_out.py render <slice> --step <task> --context "<the slice in two lines>"` — the report
   once more, the cost in its record. The two lines come from `slice.md`'s title and the head of
   its ask. With no ticket in the brief, a second `--context`: the cards the answers ask for are
   filed without a parent.
4. Commit the folder by name — `state.json`, `log.txt`, `close-out.json`, `close-out.md`,
   `close-out-record.md`, `asks/` — dropping only a stale `bailout.json`.
5. Move the slice card to delivered.
6. Register `close-out.md`, attach `close-out-record.md`, `plan.md` and `verification.json` to
   it, and end the turn. A report with no ask renders no `close-out.md`: then its end runs at once,
   `close_out.py close`, `render`, the commit and the slice card to done, and the turn ends.

## The close-out answered

A sub-agent carries out close-out.md § The continuation: `close_out.py absorb`, every ruling
carried out and recorded (`rule --did`), `close`, `render`, the store and the record committed by
name. Then the session moves the slice card to done (pilot.md § Cards) and ends the turn. What
the sub-agent could not carry out as ruled comes back as a store of asks: the session renders and
registers it and ends the turn, and the card waits for that document's continuation.

## The clarification

A fresh sub-agent pointed at the slice folder answers each question (pilot.md § The
clarification); one about a close-out entry is answered as close-out.md says. The turn's last
message is its answers, as the sub-agent gave them.

## The nudge

Carry on from where the session stood (pilot.md § The nudge and the halt): a run still live is
waited on (`run_loop.py wait <slice>`); one that exited 7 or 130 is resumed and waited on; a
document still unanswered is left as it is, and the turn ends; one answered in place is read back
as the continuation reads it.

## Bounds

- **Nothing else is yours**: no test running, no pre-exploration, no re-derivation of an agent's
  result, no suite re-run, no doc work. Escalate, don't absorb: work that dispatches dev agents or
  changes code belongs in a phase the loop executes — the one exception is a close-out's
  `fix now`, where close-out.md allows it.
- **Notify nobody, and tell nothing outside a document.** Pilot puts what the operator needs in
  front of them.
- **The loop outlives this session.** A later session meets the `run.lock` refusal while the run
  lives, and waits on it. `run_loop.py stop <slice>` interrupts the run as Ctrl-C would —
  `state.json` current, the in-flight session left for `--resume` to reattach. A loop is dead
  only when its log has gone quiet, never on `ps`, which sees only this pod: the run may live in
  another environment of the project, which `run.lock`'s note and `run_loop.py status` name.
- **The shared spec tree**: commits from other sessions that carry your slice's files mean a
  parallel session swept them into its commit — accepted, not a defect; build on the latest
  state. No run moves the shared tree: a phase targeting it works in a worktree under
  `/work/scratch/worktrees/`, which a bail leaves for the resume. A bail leaves every code repo
  the run touched on its base branch; a tree still on a `phase/…` branch afterwards either had
  uncommitted work on it or is another run's branch, and the log says which.
- **The suite is green before every slice** — preflight does not run it. A failure during the run
  is the slice's regression; never accept "flaky" or "pre-existing" from anyone.
- **Promotion is the operator's; pushing is not.** The brief's grants, or the operator's word on
  the start's push ask, authorize the pushes the slice needs — for dev verification, and to
  production where the project deploys on a push — and the devlock hold serialises them.
  Running a promotion pipeline is the operator's separate decision: assume a project has one
  wherever it has more than one stage, unless its deploy-operations doc says the stages are
  separate environments with nothing promoted between them.
