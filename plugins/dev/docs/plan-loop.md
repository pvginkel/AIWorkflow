# The plan loop — driving a slice to a reviewed breakdown

`${CLAUDE_PLUGIN_ROOT}/tools/plan_loop.py` is `/dev:plan-slice`'s mechanical half. The interactive
session settles the design with the operator first — requirements in `slice.md`, rulings in
`qa_log.md`, established facts in `grounding.md` — then launches the loop, which dispatches
**fresh** plan-writer and plan-reviewer sessions (never resumed except for the two protocol
nudges) until it reaches a terminal state. Every pass re-reads the slice folder from disk; the
dispatch prompts carry pointers, never relayed content. The folder layout and verdict schema are
in [task-workflow.md](task-workflow.md); the session mechanics are `task_runner.py`'s
`run_kc_session` — the kc dispatch helper both loops share.

```
plan_loop.py run <slice-dir> [--grant N] [--reopen] [-v]
plan_loop.py status <slice-dir>
```

Run it from the **target code repo**: sessions spawn in the repo the loop is launched from (its
root comes from `git rev-parse --show-toplevel`), and the grounding checker resolves citations
against it. There is no `--resume`: rerunning `run` on the same folder continues from
`plan_state.json`. Non-verbose stdout is one line naming `<slice>/plan_log.txt`; everything else
goes to that log, so the loop never floods a calling session's context.

## Phases

`plan_state.json` holds the phase, and the driver dispatches on it: `writing` (initial
plan-writer pass) → `reviewing` (plan-reviewer round) → `fixing` (writer fix pass) → `hygiene`
(one unreviewed cleanup pass) → `done`, with `questions` as the pause state. A phase the driver
does not recognize is a protocol failure.

A first run on a folder that already contains `tasks/NN_slug/` folders starts at `reviewing` — that
is how a reset re-plan re-enters. Once `plan_state.json` exists its stored phase wins; nothing
re-detects `tasks/`.

Verdict routing: writer `done` → `reviewing`; reviewer `issues` → `fixing`; reviewer `go` →
`hygiene` if its verdict reports any hygiene findings, else `done`. A `questions` verdict from
either agent parks the phase and exits 4.

## Terminal exits

- **Exit 0 — GO.** The reviewer signed off. Hygiene findings are then fixed in **one unreviewed
  pass** (the GO stands; hygiene never buys a re-review), the plans' cross-references are linted,
  the ledger is pruned, and `verification.json` is seeded.
- **Exit 4 — questions pending.** An agent returned `questions`. The briefing file differs by
  source: the writer's blocking questions land in `plan_questions_r<N>.md`, the reviewer's
  needs-ruling findings in its own `plan_review_r<N>.md`. The session takes that file to the
  operator, logs every ruling to `qa_log.md` (and to `slice.md` when a requirement changes),
  commits, and reruns — the loop resumes at the pass that paused. Questions never spend review
  budget.
- **Exit 3 — bailed**, with `plan_bailout.json` (`{reason, details, ts}`, rewritten each run so a
  stale one never survives). Reasons: `review_budget`, `blocked`, `timeout`, `protocol_failure`.
- **Exit 2 — precondition.** The slice dir is missing, it has no `slice.md`, the slice folder has
  uncommitted changes at launch, or `--reopen` was passed to a loop that is not at phase `done`.
- **Exit 130** — interrupted; `plan_state.json` is current, rerun to continue. **Exit 1** —
  unexpected error.

## The review budget

**Four review rounds per planning cycle**, stored as `review_budget` in `plan_state.json` and
therefore spanning invocations. A round is charged before the reviewer is dispatched, so a round
that times out still spends budget. Exhausting it without a GO raises `review_budget`; the session
brings the contested points to the operator and reruns with `--grant N` on their say-so. The loop
never extends its own budget.

- `--grant N` adds N to the stored budget every invocation it is passed, and does not reset the
  rounds already spent.
- `--reopen` adds exactly one round and re-enters at `fixing` against the last completed review —
  the round the confirming pass needs after the session's fidelity check or the operator's
  correction turns up something to fix. It requires phase `done`.

A `material` review loops internally: fresh writer fix pass → next review round. Rounds after the
first are delta-scoped — the dispatch names `git diff <last-reviewed sha>..HEAD -- <slice-dir>`, so
the reviewer verifies the previous round's findings against the changes plus reviews what is new,
instead of re-reading artifacts it already reviewed.

## Passes that spend no review budget

Two finalization passes run at GO. Each spawns a plan-writer, consumes a writer round, and is
**never re-reviewed**; a verdict other than `done` from either bails as `blocked`.

- **Hygiene.** One line-scoped pass over the GO round's hygiene findings, sweeping for further
  instances of the same defect classes. No design or scope changes; anything material goes back
  through review.
- **Cross-reference lint.** Every `CT-NNN` a `tasks/*/plan.md` cites must exist in
  `acceptance_criteria.json`, and every `G-NNN` must exist in the grounding ledger; ids compare
  numerically, so `CT-7` and `CT-07` are the same criterion. A dangling id re-enters a
  line-scoped writer fix pass rather than surviving to the session's fidelity check. The lint then
  re-runs; anything still dangling is a protocol failure. When the ledger is legacy (no stamp or no
  `G-NNN` entries) the `G-` half of the lint is skipped rather than calling every reference dead.

## Seeding verification.json

At GO the loop rewrites `verification.json` deterministically — no agent involved. One item per
acceptance criterion, in order, `id` `V01`…`VNN`, `source: "ac"`, `description` prefixed with the
criterion id, `verdict: null`. Every pre-existing item whose `source` is **not** `"ac"` survives,
is appended after the criteria block and renumbered; the coordinator's `qa_correction` entries are
what that rule exists for. The loop commits the result by name if the slice folder is dirty.

## Grounding freshness

Before every writer and reviewer dispatch the loop runs `grounding_check.py --repair` over the
whole slice ledger and the dispatch carries the resulting freshness line — a trust line when the
anchors hold, or the drifted entries for the pass to absorb. No agent step is involved mid-loop,
and repaired citations are committed by name. The hygiene and lint passes carry no freshness line.
At GO the loop runs the checker once more with `--prune`, deleting every ledger entry no plan
cites. A checker that cannot run degrades to an "unverified" line; grounding drift never ends a
planning cycle on its own. Statuses, tiers, and the entry format:
[grounding-ledger.md](grounding-ledger.md).

## plan_state.json

Loop-owned, written atomically, and the reason a rerun resumes rather than restarts: `slice`,
`created_at`, `updated_at`, `orchestrator` (the launching session's id and transcript path),
`phase`, `writer_rounds`, `review_rounds`, `review_budget`, `pending_review`, `pending_questions`,
`last_reviewed_sha`, and an append-only `history` (`ts`, `role`, `round`, `outcome`, `summary`,
`session`, `transcript`, `duration_s`). With `plan_log.txt` it is the plan's complete who-did-what
record — which is why `/dev:plan-slice` commits both when it promotes the slice. `plan_loop.py
status` prints the phase, the counters, and the last eight history rows.
