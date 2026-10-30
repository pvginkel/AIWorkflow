# The plan loop — one structural write→review round

`${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py` is `/dev:plan-slice`'s mechanical half. The plan-slice
stage settles the slice's requirements and its plan-preparer seeds `plan.md`'s header; the loop then runs a
fresh **plan-writer** pass to complete the plan and **one** fresh **plan-reviewer** pass to
judge it. The review is structural, not optional: **exit 0 is refused without a reviewer
verdict on file**, and it is the only place anything checks the plan against `slice.md` —
nobody downstream reads slice.md again. Session mechanics and models are
[agent-dispatch.md](agent-dispatch.md); the loop that executes the result is
[run-loop.md](run-loop.md).

**There is no review loop.** A `go` verdict completes the plan. Anything else — blocking
findings or questions only the operator can rule — pauses with the findings put to the operator as
a document (below). Their answers go into plan.md's rulings section, **edited in place** (a ruling
that corrects an earlier one replaces it; the round history lives in `plan_review_r*.md`), and the
rerun **always** dispatches one writer fix pass that reads the review plus the rulings and
resolves every blocking finding the rulings do not overrule. Nothing suppresses the pass, and the
loop reads nothing off the plan to guess whether the fixes are in: recording the rulings is
required either way, and a reversed ruling routinely falsifies an ordering or not-in-scope
bullet, so plan maintenance and applied fixes look identical in the file. Nobody re-reviews the
result. Post-GO corrections are the same move without the loop: edit the plan in place,
sanity-check with `run_loop.py run <slice-dir> --dry-run`.

**Every ask is a document before the exit.** A writer's `questions` verdict hands back
`plan_questions_rN.json`, and a review that does not `go` hands back `plan_review_rN.json` beside
its prose review, each shaped as the role's contract says. The loop checks the hand-back as
`asks.py` will render it: one with faults goes back once to the session that wrote it, with the
faults, and then the loop bails `protocol_failure`. It renders the asks into the slice's
`asks/<n>-plan-questions.md` or `asks/<n>-plan-review.md` through `asks.py` and exits 4, the path on
stdout and in `plan_state.json`'s `exit`, for the stage to register with Pilot
([pilot.md](pilot.md) § The documents). A question with options is a decision with its
recommendation, one without them a question. A blocking finding is a decision on the reviewer's
disposition, an operator-decidable one a decision on its options or a question, and an advisory
note stays in the review. The document carries `run --step`'s plan task as its `step`, kept in
`plan_state.json` for the reruns that do not give it. The loop commits none of it: the session
commits what it registers, as it commits the rulings before the rerun. A document that cannot be
written is logged, and the exit stands without it.

Exits: **0** plan complete (a reviewer verdict is on file and the plan parses as a phase
queue) · **4** operator input needed (the writer's questions or the review's findings, as the
document above; answer it, rerun — the loop resumes where it paused) · **3** bailed (`plan_bailout.json`:
`blocked`, `timeout`, `protocol_failure`, `missing_tools` — a plan Target's manifest calls a
`cexec` tool this environment does not run, `missing_services` — the host's own
`.kubecoder/config.yaml` declares a service this environment does not run (another Target repo's
is a warning in the log), both checked at GO as
the run loop checks them at start ([run-loop.md](run-loop.md) § Protocol invariants),
`plugin_version` — the installed plugin is not the loop's own version, checked with
`verification.json`'s keys at startup, before every dispatch and, for the keys, before exit 0;
[run-loop.md](run-loop.md) § Protocol invariants) · **7** halted: Pilot's halt file was there
before a pass — the pass in flight finished, `plan_state.json` is current, and the rerun once the
file is gone takes the next pass under the round it would have had; there at the start, nothing
ran ([run-loop.md](run-loop.md) § Protocol invariants) · **2** refused before it reads or writes
anything: another plan loop holds the slice's `plan.lock`, or its run loop holds `run.lock` ·
**130** interrupted: `plan_loop.py stop <slice-dir>` sends the loop SIGINT, as Ctrl-C, and waits
for `plan.lock` to go free, as the run loop's `stop` does ([runner-state.md](runner-state.md)).
Every exit past the refusals is on disk as `plan_state.json`'s `exit`: its code, and for an exit
4 its `reason` and `document`, for a bail its `reason`, for a halt where it stopped.

**Detached.** `run … --detach` puts the loop in a session of its own, as the run loop's does, and
returns once the loop is past its refusals, or with its refusal's code. `plan_loop.py wait
<slice-dir> [--for S]` is what the stage's session waits on inside its turn, the run loop's `wait`
on `plan.lock` and `plan_state.json` ([runner-state.md](runner-state.md) § bailout.json and exit
codes): **0** `ended: exit <n>`, then for an exit 4 its `reason:` and the `document:` to register,
for a bail its `reason:` and the `bailout:` file, for a halt where it stopped; **5** `running`,
with the `next:` wait to re-arm; **6** `gone`, with the `next:` relaunch, `run … --detach`.

**One plan loop per slice.** The loop holds a `flock` on `<slice>/plan.lock` for the whole run —
the run loop's lock, its note and heartbeat ([runner-state.md](runner-state.md) § Resume and crash
recovery) — and records the same holder in `plan_state.json`'s `driver`, which `status` prints
beside the lock's liveness. A second `plan_loop.py run` exits 2 with the holder's note, and so
does one started while the slice's run loop holds `run.lock`, which the plan loop only probes:
re-planning under a live run rewrites the queue it executes. Two loops on one slice edit one
`plan.md` and interleave one `plan_log.txt`; the environments that share the spec repo do not
share `ps`, so the lock is the only place a second loop can learn of the first. `plan.lock` is
the loop's own file, which its cleanliness checks pass by; a clean exit empties it, and it stays
in the folder until the promote drops it.

Every pass is a fresh context reading its inputs from the slice folder; rulings reach agents
through plan.md only — dispatch prompts carry pointers, never relayed content. Agents must leave
the slice folder committed (staged by name, [spec-tree.md](spec-tree.md)); the loop
nudges once, then bails. Round counts persist in `plan_state.json`, with `base` — the branch the
loop found the spec repo on at its first run, never a `phase/…` branch; before every dispatch and
every commit of its own the loop asserts the tree is still on it and bails `blocked` otherwise —
no run moves the shared tree ([run-loop.md](run-loop.md) § The plan is the queue), so that is a
hand checkout. A plan that already parses with phases (a reset re-plan) enters at review.

The loop is the first thing to run on a slice, so it creates the slice's **close-out report**
(its store `close-out.json`, and the `close-out.md` rendered from it) and commits it before its
first dispatch, and every dispatch names the report and `close_out.py`, the only way to write to
it; what the planning agents write there is [close-out.md](close-out.md)'s. At exit 0 the loop
seeds the report's actions from the plan: one entry per push-hold repo, listing the criteria
owed after that push, and one per criterion owed after anything else. It commits them under the
same branch check, and a headline an action already carries, live or struck, is not
entered again, however often the loop reruns. A seed that `close_out.py` refuses is logged and
left out, never a failed plan. The loop renders the report when it stops, whatever its exit. Every dispatch also names the project's
**change-discipline doc** (`.aiworkflowrc`'s `design_philosophy`) — the same pointer the run
loop's dispatches carry, so the rules a plan's phases will be held to are in view while the plan
is written and reviewed, not discovered at execution.

## The plan doc

`plan.md` is **the one plan** — read by every executor, and by the operator (legibility is a
design goal). The concrete skeleton —
heading levels, the `Target:` line, done-record shape, the `verification.json` schema — is
[plan-template.md](plan-template.md); its shape:

- **Header** (seeded by the plan-slice stage's plan-preparer): the one-liner; **requirements/rulings** — every
  requirement and operator ruling, in the operator's words; this section is authoritative on
  intent, is preserved verbatim by the writer, and is where `/dev:run-slice` records mid-run
  operator answers.
- **Task shape** — declared by the plan-writer *before* it investigates, checked by the review:
  `pre-settled` / `localized` / `cross-cutting`, with a one-line justification anchored in
  slice.md facts. The declaration binds the writer's investigation budget — its register
  carries the binding (`pre-settled` forbids research sub-agents and repo sweeps; research runs
  only against a named open question).
- **Ordering constraints**, **push holds** — the repos this slice must not push, the only `##`
  section the run loop reads and absent from almost every plan — and **not-in-scope**.
- **Phases** — `### P<id> — <title>` sections (format details: [run-loop.md](run-loop.md)), each
  opening with its `Target:` line, **self-sufficient by reference**: outcome, the few constraints
  the executor can't figure out, pointers to attachments. Roughly PR-sized and independently
  reviewable; a phase outgrowing that splits, a section outgrowing ~a page overflows into an
  attachment. No testing phase and no auto-doc phase — the loop owns those — and **no auto-doc
  content anywhere in the plan**: the doc phase derives its updates from the shipped diff and
  the requirements/rulings; the rulings are the only steering it gets. A doc *task* a
  requirement names is a phase like any other (the doc phase carries no slice task).
- **Done-records** are appended under each phase's own heading (never a new `###`) in
  [plan-template.md](plan-template.md)'s two-part shape: the `**Done (P<id>).**` paragraph and its
  `Later phases:` list, then the record. Finds that affect later phases are edited into those
  phases, where their reader will trip over them.

**`attachments/`** — designs only where the executor genuinely cannot derive them, written at the
altitude a smart dev would want handed to them: a functional description of success, never class
names, pseudo-code, or a specced implementation. Read on demand, never inlined.

**`verification.json`** — outcome-level acceptance criteria, complete against slice.md's numbered
requirements 1:1 in the operator's wording, with `file:line` evidence citations where a criterion
rests on a code fact. Coverage-preservation criteria allowed; doc-truth universals banned.
Checked off in the run loop's test phase, except a criterion marked `owed_after` an action the
run cannot take, a held push above all ([plan-template.md](plan-template.md)).

## The reviewer's charter

ACs outcome-level and complete against slice.md; the task shape declared and justified from
slice.md facts that hold; detailed designs correct (load-bearing citations
verified against the code); every phase's `Target:` present and real; phases independently
reviewable and roughly PR-sized; no phase or ordering note that expects a suite the phase's diff
touches to stay red until a later phase — a blocking finding, since the gate runs every touched
component ([run-loop.md](run-loop.md) § The per-phase round); attachments at the altitude
above; no auto-doc content (an altitude finding — flagged, never fact-checked claim by claim)
and no criterion only the doc phase could earn; no correction-chained rulings; nothing
load-bearing silently uncertain; no phase `Target:` or push hold on a scratch clone another
slice in flight holds without an ordering constraint putting this slice after that push — an
operator-decidable finding. For that last one the reviewer's dispatch, alone of the loop's,
lists the push holds the other plans under `slices/` and `slices/backlog/` declare. A step an
ordering constraint shares with a named sibling slice is compared with that slice's `plan.md`,
its done-record too once it has run; each difference is an operator-decidable finding that
names no winner. Findings describe problems, never corrections.
One round, ever — the findings go to the operator. Verdicts: `go` / `issues` / `questions`.
