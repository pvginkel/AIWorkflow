# The workflow in one read — what it does, who acts, and one slice walked end to end

The explanation layer's entry point: the problem the `dev` plugin solves, the four ideas that
shape it, the pipeline at altitude, what the operator actually does, and one real slice followed
from tracker cards to a merged, deployed, documented result. Mechanics are deliberately not
repeated here — the contract docs hold them ([`run-loop.md`](../../plugins/dev/docs/run-loop.md),
[`plan-loop.md`](../../plugins/dev/docs/plan-loop.md),
[`close-out.md`](../../plugins/dev/docs/close-out.md)); how the shape came about is
[`history.md`](history.md), each rule's origin is [`principles.md`](principles.md), and the
numbers behind every claim are [`measurement.md`](measurement.md).

## The problem

One operator, several repositories, a tracker full of findings, and LLM coding agents that can
do the work but not decide what the work is. The pipeline turns a batch of findings into merged,
tested and documented **slices** — a slice being one coherent change request, usually a handful
of tracker cards grouped by subject — and does it unattended between a small number of fixed
operator touch points. The scarce resource is the operator's attention, not model capacity or
tokens: every design choice below is a choice about where the operator's judgment is genuinely
needed and how to keep everything else off their desk.

The workflow began as a long-lived agent session that orchestrated everything. Measured over 1,338
conversations, that session was 53 % of all spend, re-priming its context on every resume and
personally running test suites and live verification (`workflow-improvements/ANALYSIS.md`,
2026-07-09). The redesign that followed — a Python driver, ephemeral agent sessions, durable files —
is what this repo ships; [`history.md`](history.md) tells that story.

## Four ideas

Everything in the plugin follows from four ideas (stated once in the repo's `CLAUDE.md`; the
incidents behind each are in [`principles.md`](principles.md)):

1. **The plan is the queue.** One `plan.md` per slice holds the work as phases — `### P<id> —
   <title>` headings, each opening with a `Target:` line naming the component or sibling repo it
   lands in. Document order is authoritative, ids are labels, every agent in the loop may edit
   the plan, and only the driver stamps a phase `✅ DONE`. Work grows by appending a phase, bounded
   by a generation bar.
2. **Files are durable, sessions are ephemeral; scripts drive, agents judge.** Deterministic work
   — gates, git, caps, stamping, parsing — stays in Python. Judgment goes to a fresh agent session
   with a bounded job and a machine-readable verdict. Detecting a green test suite needs no model;
   only fixing a red one does.
3. **Every agent is a headless session** spawned by the driver (`kc session create-headless
   --agent dev:<role>`), Opus at `xhigh` everywhere via explicit flags, except three always-Sonnet
   roles (test-agent, test-fixer, rebase-agent). No per-task model routing — the graded lane
   was measured and withdrawn ([`agent-dispatch.md`](../../plugins/dev/docs/agent-dispatch.md)).
4. **The loops bail, they don't chat.** Exit 3 is an error, exit 4 is a question only the operator
   can answer; `state.json`, `bailout.json` and the exit code are the whole interface to the
   session that launched the loop. Whatever an agent notices but the loop will not act on has one
   destination — the slice's `close-out.md` — never a tracker card per finding.

## The pipeline at altitude

```
tracker cards ──► /dev:triage ──► slice.md ──► /dev:plan-slice ──► plan.md + verification.json
                  (adjudicate,                  (refinement with the operator,
                   file survivors)               then plan_loop.py: writer → one reviewer)
                                                                │
                                                                ▼
close-out.md ◄── /dev:close-out ◄── close-out.md ◄── /dev:run-slice (run_loop.py)
(dispositions     (execute the                        per phase: fetch → branch → code-writer →
 executed)         operator's words)                  gate → reviewer rounds → ff-merge → ✅ DONE
                                                      then: gate sweep → completion consult →
                                                      test phase → push check → doc phase
```

| Stage | Who acts | Reads | Writes | Stops for the operator when |
|---|---|---|---|---|
| **Triage** (`/dev:triage`) | The interactive session as intake clerk; the operator rules | Tracker cards, findings docs, chat; the close-out reports waiting under `[NNN] close-out:` cards | A verbatim raw dump and a labelled working doc under `handovers/`; verdict labels on the cards; one `slice.md` per surviving subject under `slices/backlog/` | Every label — no item is ever closed by machine judgment alone |
| **Plan** (`/dev:plan-slice`) | The interactive session pins requirements and seeds the plan header; `plan_loop.py` runs one plan-writer pass and one plan-reviewer pass | `slice.md` — the only thing planning reads, and the last time anything reads it | `plan.md` (header in the operator's words, then the writer's phases and task shape), `verification.json`, `close-out.md` (created here), `plan_review_r1.md` | Writer questions; a review with blocking or operator-decidable findings (exit 4); never auto-starts the run |
| **Run** (`/dev:run-slice`) | `run_loop.py` drives; fresh code-writer, code-reviewer, consult, test-agent, doc-writer sessions per job; the launching session has four jobs and never drives | `plan.md` (re-parsed before every phase), `verification.json`, the target repo | Phase branches merged into the base, done-records in `plan.md`, `✅ DONE` stamps, `state.json` history, review files, `close-out.md` entries, pushes (test phase; the doc landing) | An executor's `question`, a generation-bar exhaustion, an unpushed repo, a broken plan nobody can fix (exit 4); errors (exit 3) |
| **Close out** (`/dev:close-out`) | The operator reads and decides; the session records dispositions verbatim and executes them | `close-out.md` | `Disposition:` lines, tracker cards (`card`), `slice.md` asks (`fold into`), strikes (`close`) | Every disposition is the operator's own words |

Two things the table hides. First, **every stage is a preflight away from portable**: each skill
runs `preflight.py --for <stage>` first, and the project describes itself through
`.kubecoder/project.yaml` (the component set, read only through `kc`) and `.aiworkflowrc` (the
spec repo, the procedure docs, which phases run) — the plugin hardcodes no project fact
([`project-contract.md`](../../plugins/dev/docs/project-contract.md)). Second, **the test and doc
phases are "read the project's procedure doc and execute"**: the plugin does not know how a
project deploys or documents; the project's own doc does, and the phase is optional per project.

## What the operator does

The operator's touch points, in order, and nothing else:

- **Adjudicates at triage** — rules on each item's label (nit pick → major, or invalid) and on
  what becomes a slice. Reasons are recorded in the working doc; verdicts persist on the cards.
- **Rules at refinement** — the `/dev:plan-slice` session pins every requirement and open choice
  with the operator, and the rulings land in `plan.md`'s header in the operator's words. At
  0.9.13 this is a Q&A; the dialog form was read in September and is being replaced by a
  refinement document ([`plan-refinement.md`](plan-refinement.md)).
- **Answers exit-4 questions mid-run** — an executor that returns `question`, a plan review with
  operator-decidable findings, an exhausted generation. The answer is written into `plan.md`'s
  rulings (replacing any ruling it corrects, in place) and the loop resumes; the next agent reads
  the plan, not the chat.
- **Dispositions the close-out report** — one word per live entry (`card`, `fix now`, `fold into`,
  `close`, `defer`); the skill executes them.
- **Promotes to production** — the loop's devlock hold pre-authorizes dev deploys for
  verification; prd is a separate, explicit operator decision.

What the operator never does in this pipeline: run tests, review diffs, push a code phase, read
the loop's log, or file a card for something an agent found. A run session that catches itself
doing any of these is told to stop — "escalate, don't absorb" (`skills/run-slice/SKILL.md`).

## A slice, end to end: 190 — fleet state under faults

Slice 190 ran on 2026-09-01 on plugin 0.9.12 against KubeCoder. Its records are under
`KubeCoderSpecs/slices/completed/190_fleet_state_under_faults/`; every figure below is read from
them (`state.json`, `plan_state.json`, `plan.md`, `close-out.md`, `verification.json`).

**The ask.** Four tracker cards (#735, #742, #740, #741), grouped at triage because three of the
four had the same defect shape — a fault treated as a fact: a node roll left two environments
terminally errored because a departure detector raced the boot bring-back; an unreadable
credential store degraded to empty and was then written back over the records on disk; a
transient filesystem error announced a live environment as gone; and a reconnecting bot re-seeded
its fleet correctly while rendering none of it. All four were ruled **agreed** at triage — "the
card as written, to the normal route, no ceilings and no qualifications" — and `slice.md` carries
each card in full, in the operator's words.

**Planning** (09:37 → 10:20, 43 minutes wall). The refinement session recorded five rulings in
the plan header — how each of the four is fixed (R1 "by suppressing departure at boot, not by
locking"; R2 covers all three silent-degrade stores; R3 is fixed at the vanish arm, not the
producer; R4 covers the list, the untracking and the cards) and that the four stay one slice. One
ruling knowingly reversed an earlier slice's close-out entry (163's B5, closed as cosmetic after
analysing only the interleaving where the bring-back wins). The plan-writer declared the task
shape **pre-settled** ("the refinement rulings fix each requirement's mechanism, so this pass
transcribed them onto five phases") and wrote five phases and 15 acceptance criteria. The
plan-reviewer returned `questions`: F1, operator-decidable — the plan stated R2's recovery bound
two contradictory ways and V04 pinned one of them; F2, blocking — the plan's own
grounding-corrections block carried three wrong `watch.py` citations; three advisories. The
operator ruled on F1, and one writer fix pass applied the rulings. No second review; the
operator's read is the second look.

**The run** (11:11 → 13:39, 2 h 28 min wall, no operator input). The driver's history, in minutes
from launch:

| Minute | Phase | Session | Round | Outcome | Duration |
|---:|---|---|---|---|---:|
| 11.9 | P1 boot LIST burst stops recording departures | code-writer | 1 | done | 711 s |
| 12.7 | P1 | gate (`kc project test --project root`) | 1 | green | 49 s |
| 21.4 | P1 | code-reviewer | 1 | **issues** — F1 Major/blocking, anchor `coverage-gap`: no test reaches `close_boot_window()`; deleting it keeps the suite green | 520 s |
| 28.8 | P1 | code-writer (fix round) | 2 | done — two tests pin the lifespan's close of the boot window, each failing under its own mutation | 448 s |
| 29.6 | P1 | gate | 2 | green | 49 s |
| 34.8 | P1 | code-reviewer (delta) | 2 | signoff — F1 "resolved and re-derived, not taken on the executor's word" | 310 s |
| 44.9–56.5 | P2 three share-backed stores stop reading a fault as an empty file | code-writer, gate, code-reviewer | 1 | signoff, three advisory findings | 602 / 52 / 646 s |
| 60.2–67.0 | P3 the clients contract states the refusal (`Target: ../KubeCoderSpecs`) | code-writer, code-reviewer | 1 | signoff, two advisory findings; no deterministic gate for the spec repo | 220 / 405 s |
| 76.1–84.4 | P4 the vanish arm confirms the environment is gone | code-writer, gate, code-reviewer | 1 | signoff, two advisory findings | 546 / 50 / 445 s |
| 92.1–104.0 | P5 a bot reconnect's reseed reaches the screen | code-writer, gate, code-reviewer | 1 | signoff, two advisory findings (one Major/advisory, `repro-trace`) | 460 / 49 / 668 s |
| 105.8 | — | loop-tail gate sweep (15 commands: lint, build, test per component) | 1 | green | 104 s |
| 110.1 | — | completion consult | 1 | `complete` — every requirement delivered; struck S6 after fixing it as mechanical residue (a comment) | 260 s |
| 111.6 | — | gate sweep (re-run: the consult committed) | 2 | green | 89 s |
| 127.2 | — | test-agent (Sonnet) | 1 | `clean` — pushed KubeCoder, CI Build-Main #424 and HelmCharts #6065 green, dev rolled with 0 restarts; 15 of 15 acceptance criteria `pass` | 935 s |
| 146.7 | — | doc-writer | 1 | done — 23 doc surfaces updated from the shipped diff | 1,169 s |
| 148.0 | — | doc gate (`mkdocs build --strict`) | 1 | green | 81 s |

The driver then rebase-merged the doc branch, pushed it, rendered the close-out report, and
stamped its header. Five phases, one review round each except P1, no bail-outs, no appended
phases, generation 0.

**What it cost.** $71.56 all-in — planner 22 %, research 3 %, rework 9 % (the P1 fix round and
its re-review). 30 sessions, 944 turns, $0.076 per turn; 154 turns (16 %) classified avoidable
(retries, fumbles, batchable reads). By role, from `state.json`'s cost block:

| Role | Sessions | Turns | Cost | Context at first turn (median) |
|---|---:|---:|---:|---:|
| code-writer | 6 | 255 | $18.79 | 36 k tokens |
| code-reviewer | 6 | 167 | $15.39 | 26 k |
| doc-writer | 1 | 75 | $8.30 | 37 k |
| plan-writer | 2 | 91 | $7.35 | 26 k |
| plan-slice session (interactive) | 1 | 54 | $4.26 | 36 k |
| plan-reviewer | 1 | 29 | $4.01 | 25 k |
| research sub-agents (general-purpose + Explore) | 10 | 188 | $7.17 | 5–16 k |
| test-agent | 1 | 41 | $3.31 | — |
| consult, run-slice session, others | — | — | remainder | — |

**The close-out.** The report ended with 14 entries — three Bugs, one Open question, ten
Suggestions — plus a Summary and a Focus line per section written by the doc-writer ("Focus: **B2
first** — the reseed this slice added renders a false, permanent *Deleted* into a chat when a
one-shot read fault hides a live env from the fleet fetch"). Seven of the fourteen are the
code-reviewer's advisory findings from rounds that signed off, arriving here rather than as fix
work; the rest came from the plan-writer, the plan-reviewer, the code-writer and the consult. The
operator's dispositions: nine entries closed, two fixed by ruling with the commit named on the
heading (S3 in KubeCoder, S7 in the contract), one struck in-run by the completion consult (S6),
and two left live — B2 (major: the new reseed reads a one-shot read fault as a departure), carded
to the tracker, and S9 (the same fault-as-fact shape at another consumer), folded into that card.
Two tracker cards exist for the whole run: `[190] close-out: …`, pointing at the report, and B2's.
[`reporting.md`](reporting.md) reads the same report entry by entry.

## What a slice costs

Over the 44 completed KubeCoder slices that carry a cost block (144–196, plugin 0.4.3 onward;
computed 2026-09-02 from `state.json` — method and per-role table in
[`measurement.md`](measurement.md)):

| | Median | p25 | p75 | Min | Max |
|---|---:|---:|---:|---:|---:|
| Cost per slice | $61.91 | $44.37 | $99.81 | $20.34 | $293.03 |
| Phases per slice | 5 | 3 | 6 | 1 | 14 |
| Cost per phase | $15.95 | $11.91 | $20.34 | $4.41 | $53.67 |
| Wall time (hours) | 2.1 | 1.5 | 3.1 | 0.8 | 52.0 |
| Rework share (fix rounds + re-reviews) | 8 % | 5 % | 14 % | 2 % | 28 % |
| Planner share | 23 % | 15 % | 28 % | 0 % | 42 % |
| Turns per slice (22 slices with turn data) | 830 | 545 | 1,204 | 311 | 2,860 |

Total for the 44: $3,433. Ten of them bailed at least once (13 bail-outs in all); two had a phase
appended by the completion consult. The two 50-hour wall times are slices left paused on an
operator question overnight, not compute. Code-writers are 31 % of spend, reviewers 20 %, the
doc-writer 13 %; the interactive sessions the operator sits in are 7 %.

## Where the mechanics live

| Want to know… | Read |
|---|---|
| The phase loop, the review bar, the loop tail, the generation bar | [`run-loop.md`](../../plugins/dev/docs/run-loop.md) |
| What `state.json` and `bailout.json` record | [`runner-state.md`](../../plugins/dev/docs/runner-state.md) |
| The one write→review planning round | [`plan-loop.md`](../../plugins/dev/docs/plan-loop.md), [`plan-template.md`](../../plugins/dev/docs/plan-template.md) |
| How sessions are spawned, models, timeouts, nested delegation | [`agent-dispatch.md`](../../plugins/dev/docs/agent-dispatch.md) |
| The close-out report's contract and entry shape | [`close-out.md`](../../plugins/dev/docs/close-out.md), [`close-out-template.md`](../../plugins/dev/docs/close-out-template.md) |
| What a repo must provide; preflight | [`project-contract.md`](../../plugins/dev/docs/project-contract.md), [`preflight.md`](../../plugins/dev/docs/preflight.md), [`docs/ADOPTING.md`](../ADOPTING.md) |
| Each role's bounds and verdict shape | `plugins/dev/agents/*.md` (9 agents) |
| Each operator workflow's procedure | `plugins/dev/skills/*/SKILL.md` (8 skills) |
| Every change, newest first, with the incident behind it | [`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md) |
