# A3 Implementation Plan — Effort Step-Down Across Both Loops

Companion to [interventions.md](interventions.md) §4 (A3) and [status.md](status.md). Written
2026-08-14 at plugin 0.4.4, before implementation; scheduled after B1+B4.

**Scope decision (operator, 2026-08-14).** The catalogue's A3 covers the plan registers only. The
operator widened it: the run side is the large majority of slice spend (I2: planner share 18.6% /
26.9% on 144/145 — the run loop is the rest) and the bigger gain, so this plan covers **both
loops as one cascade**. The catalogue entry gets a scope amendment when this ships.

**Stage 1 (§3, §4, §8a) implemented 2026-08-18 as plugin 0.7.0** (status.md A3 has the log line;
the catalogue entry carries the scope amendment). §9 resolved as recommended: **default `high`**,
`--writer-effort xhigh` the escape hatch. Where the build departed from the text below: the fuse
counts *any* phase that needed an executor round beyond r1, whatever tier its r1 ran at —
behaviourally identical (before the fuse trips every r1 in the reduced arm is reduced; in the
`xhigh` arm the fuse changes nothing) and the count then means the same thing in both arms;
`in_flight` records the dispatched `effort` so a crash reattach resumes at the tier the session
was created with, even under a different `--writer-effort` on the resume; the shape/tier record
was **not** duplicated into `slice_cost.py`'s `cost` block — it already sits at `state.json`'s
top level (`task_shape`, `writer_effort`, `effort_fuse`), the close-out `Run:` header names it
(`shape … · writer … (fuse tripped)`), and `slice_cost.py` prints a `tiers` line and each
session's round and effort, which is the per-arm read §4 wants; the tier is settled after
preflight so a precondition error strands no `state.json`; `run_loop.py status` and `--dry-run`
show the shape and the round-1 tier. Plan-loop history rows carry `effort` (§4), but nothing of
§2 is built — `plan_state.json` has no `writer_effort` or `escalated` — and stays unbuilt until
the run trial reads out. The pre-0.7.0 line numbers below are where to look, not proof.

**0.7.1 (2026-08-18):** a re-dispatch after a crashed or `blocked` session or a protocol bail-out is
not a redo — it runs at the round-1 tier and does not count toward the fuse. Slice 158, the first
read, had the fuse counting P4, whose r1 died `rc=1` with no verdict and whose r2 was only the
re-dispatch after the operator resumed the loop; left as it was, a crash on the first two phases of
a small-shape slice would trip the fuse on noise and silently move a `high` phase into the `xhigh`
arm. `spawn_executor` now carries an explicit `redo` flag; the round number stays the attempt
counter.

**Withdrawn 2026-08-19 — plugin 0.7.3 reverted 0.7.0–0.7.2.** This document is the record of what
was built and why it was taken out; [status.md](status.md) A3 carries the four reads (158–161) and
the operator's ruling. Nothing below is live in the plugin.

---

## 1. The design in one paragraph

One rule, applied at every dispatch boundary: **judgment roles keep `xhigh`; producer roles start
at a reduced tier only where a verified signal is in place to catch a cheap-tier failure, and
every signal-triggered round runs at `xhigh`.** The gate for the reduced start is A1's task
shape — a checkable label, declared from slice.md facts, verified by the `xhigh` plan-reviewer,
read by the operator. `cross-cutting` (or an absent declaration) never steps down. Effort tiering
stays inside Opus — this is not the retired model-routing lane (§6).

Roles: **plan-writer** and **code-writer** step down. **plan-reviewer, code-reviewer, consults**
stay `xhigh` unconditionally — they are the escalation signal source and the A/B instrument;
degrading the instrument invalidates the cascade (D1: keep the strongest judge; D2: the reviewer
is what makes producer step-down safe). **doc-writer** stays `xhigh` in this stage — the doc
phase has no reviewer, so no signal catches a cheap-tier failure there (§7 names what a follow-up
would need). Test roles are already Sonnet-pinned and untouched.

The §8 constraint "effort stays fixed within a session; tiering only at dispatch boundaries" is
satisfied by construction — every pass in both loops is a fresh `kc session`.

## 2. Plan-loop half

### The gate problem

The trial gate is the declared-small shape, but the shape is declared *by the plan-writer inside
its own session* — the loop cannot know it before choosing the writer's tier. Resolution: A1's
"declare **before** you investigate" ordering does double duty as the gate.

- The initial writer pass dispatches at the reduced tier. Declaring the shape is cheap and needs
  no investigation — it rests on checkable slice.md facts by A1's own contract.
- `pre-settled` / `localized`: the pass continues and completes the plan at that tier.
- `cross-cutting`: the pass **stops immediately** — commits the declaration, hands back a new
  verdict outcome **`escalate`** — and the loop re-dispatches a fresh writer pass at `xhigh`.
  Misprediction cost: one short cheap pass. This is the escalation re-run path the catalogue
  prices as the M half of A3's S–M.

### Mechanics (`plan_loop.py`)

- Split `MODELS` (plan_loop.py:86): plan-reviewer fixed `("opus", "xhigh")`; plan-writer's effort
  becomes state-dependent.
- `run` gains `--writer-effort {xhigh,high,medium}`, persisted into `plan_state.json` as
  `writer_effort` so reruns keep the tier (a differing flag on a rerun overrides and logs).
  `medium` is available behind the flag, **not** the trial tier.
- Sticky escalation: `plan_state.json` gains `escalated: {reason, round, ts} | null`. Once set,
  every subsequent writer pass runs `xhigh`. Setters: writer `escalate` (reason `cross-cutting`),
  writer `questions`, reviewer `issues` or `questions` — i.e. every exit-4 event. That covers all
  three catalogue signals; "AC-coverage gaps" is a reviewer finding class and arrives as `issues`
  (the loop cannot and should not parse the markdown review).
- New transition: `escalate` → phase stays `writing`, re-dispatch the initial prompt at `xhigh`
  with an appended note ("a reduced-effort pass declared the shape cross-cutting and stopped;
  confirm or re-derive the declaration, then complete the plan"). Termination is structural:
  post-escalation the tier is `xhigh`, and `escalate` from an `xhigh` pass is a protocol-failure
  bail — at most one escalation per run.
- `VERDICTS["plan-writer"]` (plan_loop.py:91) gains `escalate`. The dispatch prompt tells the
  writer its tier only when reduced (a conditional line in `WRITER_INITIAL_PROMPT`); at `xhigh`
  the escalate path is invisible and invalid.
- Corollary worth documenting: fix passes are always `xhigh` by construction — a fix pass only
  exists after an adjudication exit, and every adjudication exit escalates. The no-review-loop
  invariant is untouched: escalation never adds rounds, it only re-tiers passes that already
  exist.
- `plan-writer.md` hand-back gains ~3 lines for `escalate` and its condition.

## 3. Run-loop half

### The gate: the shape is already on file

The run side has no discover-then-escalate dance: the shape sits in plan.md's `## Task shape`
section before the run starts — declared by the plan-writer, checked by the `xhigh`
plan-reviewer, read by the operator. The driver gains a small reader (first word of the section
body: `pre-settled | localized | cross-cutting`; plan-template.md:26 fixes the format), records
it into `state.json` as `task_shape`, and treats a missing or unparseable section as
`cross-cutting` — plans predating A1 never step down.

### The cascade: round 1 cheap, every signal-triggered round full

All code-writer rounds in a phase funnel through `spawn_executor` (run_loop.py:1900), which makes
the rule one condition at one site:

- **Executor round 1** of each phase runs at the reduced tier iff the shape is
  `pre-settled`/`localized` and the flag permits.
- **Every later executor round runs `xhigh` automatically** — each one exists only because a
  verified signal fired: a red gate (`_gate_until_green` fix rounds), blocking review findings
  (review-fix rounds, funded from round 2 by the consult bar), or an operator ruling
  (writer-question resume rounds). No per-signal bookkeeping is needed; "round ≥ 2" *is* the
  escalation condition. This also keeps the C2 interplay right: failure-first fix rounds — the
  witness/refute judgment — always run at full effort.
- **Slice fuse** (recommended, small): once **2 phases** in a run have needed an executor round
  beyond r1, remaining phases start at `xhigh` (`state.json`: `effort_fuse` with the tripping
  phases). This is the self-protective answer to the graded lane's failure mode — a slice where
  the cheap tier keeps triggering redos stops paying the redo tax mid-run instead of at the
  retrospective.
- Reattach (runner-state.md's crash recovery) is unaffected: a reattached session keeps the
  effort it was created with — effort is fixed within a session — and its round number, so caps
  and telemetry don't skew.

Unchanged at `xhigh`: code-reviewer (all rounds), every consult (funding bar, completion,
refutation rulings — cheap, judgment-dense, and the C1/C2 anchors depend on strong judgment),
doc-writer (§7). Test-agent/test-fixer/rebase-agent stay Sonnet per their definitions.

### Flag

`run_loop.py run` gains the same `--writer-effort {xhigh,high,medium}`, persisted as
`writer_effort` in `state.json`; `--resume` keeps it.

## 4. Telemetry and measurement

Rides I1/I2 — no new instruments, three small extensions:

- **History rows in both loops gain `effort`** (the value actually dispatched):
  `_record` at run_loop.py:1211 and plan_loop.py:208, fed from the `_spawn` sites where
  `MODELS[role]` resolves today (run_loop.py:1550, plan_loop.py:293).
- **`state.json`** gains `task_shape`, `writer_effort`, `effort_fuse`;
  **`plan_state.json`** gains `writer_effort`, `escalated`.
- **`slice_cost.py`** already reads both state files (slice_cost.py:67); the `cost` block it
  writes at close-out gains `task_shape` and the two `writer_effort` values, so the A/B row is
  one artifact per slice: shape + tiers + planner/rework shares + the run's
  gate_red/appended/generation record.

**Metrics per arm** (reduced vs `xhigh`, on declared-small shapes):

- Plan side: writer-session cost and duration per tier; reviewer verdict mix (`go` vs `issues`);
  escalation rate by shape.
- Run side: executor-r1 cost and duration per tier; gate-red-on-r1 rate; blocking-finding rate
  and anchor mix per tier (I1's per-finding fields make this a mechanical read); executor-round
  ≥2 rate ("escalation rate"); refuted-finding rate; fuse trips; downstream appended-phase /
  generation / test-phase-finding rates; net slice cost.

Baseline: 144/145 (0.4.3, `xhigh`, full I1 telemetry) plus subsequent `xhigh` slices. Confound,
stated: the C1/C2 validation continues on whatever slices run — the per-slice tier record is
what keeps the arms unambiguous. All directional at n < 10; no acceptance call before a handful
of slices per arm.

## 5. Success and kill criteria (for status.md's "Decides it")

**Success:** on declared-small shapes, producer cost per tier down (plan-writer session; executor
r1) with reviewer verdict mix, gate-red rate, blocking-finding rate, and downstream
appended/generation rates not worse than the `xhigh` baseline — and net slice cost down after
the redo tax. Escalation honest: rate meaningfully below 100% on small shapes (else the
step-down never engages), and the first genuinely `cross-cutting` slice declares itself so —
the discrimination test A1 still owes.

**Kill:** either loop shows the redo tax eating the discount — executor-round-≥2 or plan
`issues` rates materially above baseline on the reduced tier, or fuse trips becoming routine —
or the **counter-evidence bites**: Cuadron et al. found o1-*low* scored 35% *higher* on
overthinking than o1-high **in agentic settings**, and the run executor is exactly an agentic
setting. So watch session `duration_s` and cost per tier first: if `high` sessions run longer or
spend more than `xhigh` ones, the trial self-refutes early. On kill: record in status.md, flag
back to `xhigh` — one launch-flag change, no revert needed — and stage 2 stays unbuilt.

## 6. Why this is not A4's rejected lane

A4 rejects **automatic routing on predicted difficulty, where a misjudged grade silently ships
its consequences**. This design differs on each clause: the router input is A1's task shape — a
checkable property of slice.md, not felt complexity — independently verified by the `xhigh`
plan-reviewer and read by the operator; the routed consequence is an effort tier within the same
model, not a model swap (the graded lane's Sonnet-vs-Opus gap is a different order of
capability); and nothing ships silently — every producer output at the reduced tier passes the
same deterministic gates and the same `xhigh` review, and every failure signal re-tiers the very
next round. Escalation conditions on *outcomes*, which is strictly more information than any
upfront grade. The residual honest tension — the starting tier *is* keyed on a declared label —
is why the trial errs conservative: `cross-cutting` and undeclared shapes never step down, and
the kill criteria above are pre-committed.

## 7. Deliberately out of scope

- **doc-writer step-down** — no reviewer covers the doc phase; the only check is the mechanical
  gate sweep, so a cheap-tier quality drop ships silently into the docs. Revisit once B2's
  measurement matures enough to serve as the missing signal (doc-phase finding rates via I1),
  or if a doc review ever exists.
- **Reviewer or consult step-down** — never; they are the instrument.
- **`medium` as trial tier** — available behind the flag for a later step, not the trial.
- **Per-phase shape declarations** — plan-template schema growth without evidence of need; the
  slice-level shape plus per-round escalation covers the same ground.
- **Numeric budgets** — A2/TALE: structural gates, never token caps.

## 8. Files touched

| File | Change | Size |
|---|---|---|
| `plugins/dev/tools/plan_loop.py` | MODELS split, `--writer-effort`, `escalate` transition, sticky escalation, prompt note, history `effort` | M |
| `plugins/dev/tools/run_loop.py` | shape reader, `spawn_executor` r1 tier rule, fuse, `--writer-effort`, state fields, history `effort` | M |
| `plugins/dev/tools/test_plan_loop.py` | tier defaults; escalate → `xhigh` re-dispatch → second escalate bails; escalate at `xhigh` bails; post-signal passes `xhigh`; tier persists across rerun; history carries `effort` | M |
| `plugins/dev/tools/test_run_loop.py` | shape parse (present/absent/malformed); r1 tier by shape/flag; r2+ always `xhigh`; fuse; resume/reattach keep tier; history carries `effort` | M |
| `plugins/dev/tools/slice_cost.py` + test | `cost` block gains `task_shape` + `writer_effort`s | S |
| `plugins/dev/agents/plan-writer.md` | `escalate` hand-back (~3 lines) | S |
| `plugins/dev/docs/plan-loop.md` | tier/escalation contract paragraph | S |
| `plugins/dev/docs/run-loop.md` | per-phase round: tier rule + fuse | S |
| `plugins/dev/docs/runner-state.md` | new state fields, history `effort` | S |
| `plugins/dev/docs/agent-dispatch.md` | rewrite "Everything runs Opus at `xhigh`" into the tier rule for both loops | S |
| `plugins/dev/.claude-plugin/plugin.json` + `CHANGELOG-workflow.md` | version + entry | S |
| `docs/research/interventions.md` + `status.md` | A3 scope amendment; log line → validating | S |

## 8a. Rollout: run loop first, plan loop conditional

Two stages, decided 2026-08-14 (operator + assessment):

- **Stage 1 — the run half** (§3): the simpler build (no new verdict outcome, no loop
  transition, the shape already on file) for the larger effect (the run side is the large
  majority of slice spend), with the stronger safety net — a cheap executor round's failure is
  caught in-loop by the gate and the `xhigh` reviewer, where a cheap plan's failures surface
  downstream in the run. Ships as its own version after B1+B4, and **only after B1+B4 have a
  slice or two of `xhigh` data** — both change what the code-writer produces, and that gap keeps
  B's comment-rate attribution clean (the tier field segments it regardless).
- **Stage 2 — the plan half** (§2): conditional on stage 1's read. If the run trial shows the
  redo tax eating the discount, the plan side's `escalate` machinery — the M-cost half — never
  gets built; if stage 1 holds, stage 2 ships with its precedent established.

Per-loop attribution stays clean across the stages because the metrics are loop-scoped; the
flag name (`--writer-effort`) and semantics are shared so stage 2 adds no new operator surface.

## 9. Open decision: flag default

Recommendation: **default `high`** in both loops, `--writer-effort xhigh` as the escape hatch.
An opt-in flag the launching session must remember produces no trial data; the mechanism is
self-gating (`cross-cutting` and undeclared shapes never step down, reviewers unchanged, gates
unchanged); and the effort docs say `high` *is* the default — `xhigh` is the premium under test.
The conservative alternative — default `xhigh`, the `/dev:plan-slice` and `/dev:run-slice`
skills add the flag during the trial — makes the trial visible in every launch command at the
cost of forgettability. Operator's call at implementation time; everything else in this plan is
independent of it.
