---
name: plan-slice
description: The planning of a triaged slice, as a stage Pilot runs — a headless session that has the plan-preparer ground the slice and put its requirements asks, registers them, carries the answers into plan.md, launches ${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py detached and waits on it inside its turn, registers what the loop asks, and at its end promotes the plan. Started by a work item whose brief opens `/dev:plan-slice <slice>`; without Pilot, the operator starts it the same way and writes the answers into the documents.
argument-hint: <slice-number-or-path>, then the brief
---

# Plan Slice

The planning of one triaged slice, as a stage of Pilot. The contract every stage keeps — the
brief, the four ways a turn opens, the documents, the continuation, the clarification, the nudge
and the halt, the cards, the fallback without Pilot — is `${CLAUDE_PLUGIN_ROOT}/docs/pilot.md`.
This skill restates none of it: it says what planning does in each turn, and where the turn ends.

**The session coordinates; it never reads the slice.** The `dev:plan-preparer` grounds the slice
and writes its requirements asks. `plan_loop.py` drives the plan-writer and the plan-reviewer
(`${CLAUDE_PLUGIN_ROOT}/docs/plan-loop.md`), and the plan's shape is
`${CLAUDE_PLUGIN_ROOT}/docs/plan-template.md`. This session launches, waits, registers, carries
out and commits. What has to be read — the slice, an answer to carry into the plan, a bail to
diagnose, a question about the slice — goes to a sub-agent pointed at the slice folder. Nobody
downstream reads `slice.md` or a document: what reaches the executors is `plan.md`.

Below, `<spec-repo>` is your `.aiworkflowrc`'s `spec_repo`, `<slice>` the slice folder under
`<spec-repo>/slices/backlog/` that the brief's first line names, `<task>` the brief's plan task,
and a tool is `python3 ${CLAUDE_PLUGIN_ROOT}/tools/<tool>`. Run from the target code repo.

- **A sub-agent runs in the foreground** (pilot.md § A turn's end is the run's end). Brief it with
  the slice folder, the paths it works on and the section of this skill it follows. It loads
  `/dev:writing` before it writes an ask, and hands back a receipt: what it did, with the commits,
  and the path of any store of asks it wrote.
- **The tracker** — the slice card, the cards routed to the slice, the cards a ruling asks for —
  speaks your host convention (`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md` §3). Load it
  before the first tracker call, yours or a sub-agent's. The slice card's id is `slice.md`'s
  `issue:`.
- **An ask is a document**: a store under `<slice>/asks/` through `asks.py`, `--step <task>`,
  rendered, registered and backed as pilot.md § The documents says. Commit every store, document
  and file of the folder you changed by name before the turn ends
  (`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`).

## The start

1. **Read the brief** (pilot.md § The brief): the slice from the first line, the ticket from its
   `Ticket:` line, `<task>` from "This work item serves plan task `<id>`". While
   `/work/.quota-limit-halt-requested` exists, do not start: end the turn saying so.
2. **Preflight**: `preflight.py --for plan --slice <slice> --json`. A failure is an `action`
   document: its heading the fix in a line, its body the `fact`, the `fix` and the `output`,
   `--check "preflight --for plan passes its <check> check"`. Register it and end the turn; its
   continuation starts again at this step. Fix nothing in the environment yourself. A failure
   with no slice folder to hold a document — no slice of that name, or no spec repo — ends the
   turn with its last line saying what failed and what fixes it. A pass's notes go into the
   turn's last line.
3. **Prepare**: dispatch `dev:plan-preparer` with `<slice>`, `<task>` and the ticket. It leaves
   `grounding.md` and `plan.md`'s seeded header in the folder and hands back the path of
   `asks/1-requirements.json`, or `nothing to ask`.
4. **Put the requirements**: `asks.py render <store>`, register `asks/1-requirements.md`, attach
   `grounding.md` and `slice.md` to it, commit `plan.md`, `grounding.md` and `asks/` by name, and
   end the turn. With nothing to ask, commit `plan.md` and `grounding.md` and go to
   [the loop](#the-loop).

## The loop

**Launch, detached**: `plan_loop.py run <slice> --detach --step <task>`. It returns once the loop
holds the slice, its last line the `next:` wait. A rerun is the same command; the loop takes it
up where it paused and always dispatches the writer's fix pass after a review. Refused (exit 2)
because another plan loop holds `plan.lock`, the loop is live: wait on it,
`plan_loop.py wait <slice>`. Refused because the slice's run loop holds `run.lock`, re-planning
would rewrite the queue it executes: that is an `action` document as in the start's step 2.

**Wait**: run the `next:` line's `wait` in the foreground, a plain Bash call; it returns within
nine minutes. Its exit code is a signal, and the lines it prints are all there is to read:

- **5, running** — run the new `next:` line again at once. Read nothing in between.
- **6, gone** — the loop died with no exit recorded: run the `next:` relaunch, then wait again.
- **0, ended** — act on `ended: exit <n>`:

| The loop's exit | The turn |
|---|---|
| **0**, plan complete | [the promotion](#the-promotion) |
| **4**, the writer's questions or the review's findings | register the `document:` line's file; attach `plan.md`, and for a review its prose, `plan_review_rN.md`; commit `asks/`; end the turn. With no `document:` line, a sub-agent puts the hand-back file the exit names as a `question` document first. |
| **3**, a bail, or **1** | [the diagnosis](#an-error) |
| **7**, halted | end the turn, its last line the `halted:` line |
| **130**, interrupted | someone stopped the loop: end the turn saying where; a nudge resumes it |

A `plugin_version` bail is rerun from the installed `tools/` path `plan_bailout.json` names, not
from `${CLAUDE_PLUGIN_ROOT}`: this session's copy is the stale one.

## An error

A sub-agent diagnoses the bail by this section. It reads `plan_bailout.json` and the files it
names before deciding anything, `plan.md`'s requirements and rulings among them; the loop's
message is a diagnosis from a process that cannot see the plan, not an instruction. Then the root
cause:

- **Mechanical or environmental, and the workflow's** — a stale checkout, a wrong path, the spec
  repo checked out off its base: the sub-agent fixes it and says so, and the session reruns the
  loop and waits.
- **An environment fact only the operator can change** — a tool or a service this environment
  does not run: an `action` document, its check the fact.
- **Anything else** — the sub-agent writes a `decision` store: the diagnosis, and of retry,
  change the plan and stop here the options that are live, with its recommendation. The session
  renders and registers it, attaches `plan_bailout.json` and the files it names, commits and
  ends the turn.

## The continuation

A sub-agent reads back the documents Pilot's message names and carries them out by this section
and pilot.md § The continuation, each with `asks.py absorb <document>`. Every ruling lands in
`plan.md`'s `## Requirements / rulings` in the operator's words, a ruling that corrects an earlier
one replacing it in place, and is committed by name before anything is launched: the next writer
reads the plan, not the document. Two readings beside pilot.md's:

- **A hedged answer is not a ruling.** One that rules conditionally ("if X, then fine") has its
  condition checked; where it holds, the ruling stands as given, and where it does not, the ask
  goes again in a new document with what was found.
- **A note that asks back is answered**, under `/dev:writing` § A question back, in a new
  document that puts the ask again.

By what the document asked:

- **The requirements.** Besides the rulings:
  - a ruling that forbids pushing a repo needs its `- <repo> — <why>` bullet under
    `## Push holds`, and one that waives a target's gate, accepts a red lint, build or test, or
    authorizes a promotion its `## Driver rulings` bullet (`gate`, `accept`, `prd`;
    plan-template.md). Without it the driver runs the rule the ruling bent. An in-phase push
    ruled lands as its ordering constraint too;
  - a repository to create, ruled so, is created now, as
    [below](#a-repository-the-slice-creates);
  - a slice split, or an item kicked back, gets its folders from the allocator under
    `/dev:triage`'s conventions, and an adjacent slice pulled in is absorbed as the preparer
    absorbs a card;
  - an arch design first, or the slice cancelled: planning stops here, nothing is launched, and
    the turn ends saying so.
- **The loop's questions or review.** The rulings alone; the rerun's fix pass applies them to
  the phases and `verification.json` (plan-loop.md).
- **An action, done.** Nothing to write: the step that raised it runs again.
- **The error's decision.** Retry reruns; change the plan lands as a ruling does. Stop here lands
  as a ruling too, and planning stays stopped where it stood, resumable by a later
  `/dev:plan-slice` of the slice; the turn ends.
- **An answer deferred** takes its subject out of the slice: a line under `## Not in scope`
  quoting its `to`. Where the plan cannot go on without it, planning stops as stop here leaves
  it.

Then the session launches the loop, or reruns it, and waits. What the sub-agent could not carry
out as ruled comes back as a store of asks, which the session renders, registers and ends the
turn on instead.

### A repository the slice creates

Created before the loop runs, with a manifest in it: the plan loop's dry run clones every
`github:` target, and one without a `.kubecoder/project.yaml` has no gate. Build its first commit
locally in `/work/scratch/<Repo>` (`git init -b main`): the README and a seed
`.kubecoder/project.yaml` whose `test` needs no file in the repo — for a deploy repo, a
`helm template` of the pinned upstream chart. Prove the seed with `kc project test` from that
directory, commit, and push with `gh repo create <owner>/<repo> --private --source . --push`, not
`--add-readme`, which writes a README-only first commit on GitHub. Leave the clone clean, for the
driver adopts it, and record the seed and its commit in `## Requirements / rulings`: the phase
that builds the repo replaces it with the real manifest.

## The promotion

At exit 0, in this order:

1. `run_loop.py run <slice> --dry-run` — the plan parses, every `Target:` resolves, the gates
   print. A failure is [diagnosed](#an-error) as a bail is.
2. `git mv <spec-repo>/slices/backlog/<NNN_slug> <spec-repo>/slices/<NNN_slug>`, and commit the
   move with the loop's `plan_state.json` and `plan_log.txt`, staged by name; drop a stale
   `plan_bailout.json` and the emptied `plan.lock`. The folder is clean after. No document of the
   slice is open at exit 0, so the move is safe (pilot.md § The documents).
3. A sub-agent brings the tracker in line with the plan. The slice card goes from triaged to
   planned, its highlights matching the plan's scope where planning moved it. Each card
   `grounding.md` names as routed to the slice is closed as the convention closes an absorbed
   task where the plan carries its ask, and is left open with a comment quoting the ruling where
   it does not.
4. End the turn, its last line the plan's path and its phases, counted.

## The clarification

A fresh sub-agent pointed at the slice folder — `grounding.md`, the asks, `slice.md`, `plan.md` —
answers each question (pilot.md § The clarification). The turn's last message is its answers, as
the sub-agent gave them.

## The nudge

Carry on from where the session stood (pilot.md § The nudge and the halt): a loop still live is
waited on (`plan_loop.py wait <slice>`); one that exited 7 or 130 is rerun and waited on; a
document still unanswered is left as it is, and the turn ends; one answered in place is read back
as the continuation reads it. A start that ended before its document was registered takes the
step it stood at again.

## Bounds

- **Nothing else is yours**: no reading of the slice or the code, no grounding, no plan text but
  what a sub-agent writes by this skill, no phases. Never answer a pending question from your own
  judgment.
- **Notify nobody, and tell nothing outside a document.** Pilot puts what the operator needs in
  front of them.
- **The loop outlives this session.** A later session meets the `plan.lock` refusal while the
  loop lives, and waits on it. `plan_loop.py stop <slice>` interrupts it as Ctrl-C would. A loop
  is dead only when `plan_log.txt` has gone quiet, never on `ps`, which sees only this pod.
- **Running is a separate work item.** Do not start `/dev:run-slice`.
