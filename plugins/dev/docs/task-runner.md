# The task runner — executing a planned slice

`${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py` executes a slice's task breakdown unattended: one
bounded loop per task, then final verification. It spawns every dev session, enforces every bound,
and consults fresh decision sessions on its own, so an uneventful slice needs nothing from
`/dev:run-slice` between launch and the final report. What it records and how a run resumes is
[runner-state.md](runner-state.md); how it spawns sessions is
[agent-dispatch.md](agent-dispatch.md).

```
task_runner.py run <slice-dir> [--resume] [-v] [--dry-run]
task_runner.py status <slice-dir>
```

Run it from the **target code repo** — the repo root comes from `git rev-parse --show-toplevel`,
and `kc` resolves the manifest against it. Stdout is one line naming `<slice>/log.txt`; runner and
session output goes there, so progress never lands in a calling session's context and outcomes are
read from the exit code, `state.json`, and `bailout.json`.

**Preflight** runs only on a fresh start, never on `--resume`: the slice folder must have a
`slice.md`, `tasks/` must hold at least one `NN[a]_slug` folder, every `task.json` must parse and
name a known project (one `kc project list` reports), the target repo's worktree must be clean,
and HEAD must be on the recorded base branch. The runner re-scans `tasks/` before every task and
takes the lowest-sorting unmerged folder, which is how a checkpoint's `amend` and a
`/dev:write-task` insertion take effect on resume.

## The per-task loop

**1. Branch.** `git checkout -b task/<slice-number>-<task-id> <base>`. The base is whatever branch
the runner was launched on, captured once in `state.json` as `base_branch` — not a hard-coded
`main`. On resume the existing branch is checked out and hard-reset to HEAD, unless an interrupted
session is being reattached, in which case its uncommitted work is preserved exactly as the crash
left it.

**2. Write.** A fresh `code-writer` session with the task folder, running in the task's component
directory, its dispatch carrying the task's
[grounding freshness line](grounding-ledger.md#where-it-runs). The writer implements, lints, runs
only the tests it wrote or touched, commits, and hands back its verdict; `missing-task` bails so
the orchestrator can author the missing task.

**3. Gate and fix loop — deterministic, fixer rounds capped at 3.** The runner runs the
component's test gate itself: `kc project test --project <name>`, from the repo root, exit 0 =
green, full output to `gate_r<N>.log` (N is a per-task gate counter across every stage, not a
round number). Green spawns nothing. Green also stamps `gate_green_commit` and `gate_green_log`,
the evidence the reviewer's dispatch later cites. Red spawns a fresh `test-fixer` whose whole job
is turning the gate green: mechanical fixes it commits itself; non-trivial failures go in
`test_results_r<N>.md` with outcome `issues`, and a **fresh** writer session fixes them — every
input it needs (the escalation, `task.json`, `plan.md`, the branch diff) is on disk, and resuming
the original session instead would replay its accumulated context every turn. The gate re-runs
after every fixer or writer round: a fixer's `clean` is confirmed, never trusted. The fixer never
audits the change or fact-checks prose — finding issues is the reviewer's job. A third round with
the gate still red triggers a consult, after which the loop proceeds to review regardless; review
can start on a red gate, but merge cannot.

What "test" means for a component is the operator's call, declared in the manifest's statements
and read only by `kc`. A component that declares none — a docs-only project, say — is green by
definition; that is a valid answer, not a gap the runner second-guesses. (`kc` rejecting the
component *name* is different: that is `protocol_failure`, since the name came from
`kc project list`.)

**4. Review loop — round 1's fix is automatic, later rounds are consult-funded, backstop cap 5.**
A fresh `code-reviewer` over the branch diff, given the full requirements chain: `slice.md` (the
authoritative ask), `task.json`, `plan.md` (requirement decomposition and pinned cross-task
interfaces), the acceptance criteria, and the task's `grounding.md`, whose citations it verifies
rather than re-deriving the prose claims. It judges outcomes, not approach — deviating from the
plan while meeting the requirements is not a finding; a missed planned edge behavior, a broken
pinned interface, or a silent substitution against `slice.md` is. It is told the slice spans
several tasks and only this one is under review, and it tags every finding's **impact**
(`blocking` or `advisory`) alongside its severity.

- **Rounds are banked on a verdict, not on dispatch.** A round that produced no review — blocked,
  protocol failure, or an account session-limit window — advances neither the round counter nor
  the reviewed-HEAD marker, so it cannot raise the funding bar or force a cold re-review.
- **Rounds 2+ are delta-scoped.** The dispatch names `<previously-reviewed HEAD>..HEAD`: verify
  the previous round's findings against the fix range, and review the fix commits for new
  problems. An unchanged HEAD falls back to a full `merge-base..HEAD` review.
- **Every round is told the gate's state**, so the review does not spend turns re-running the
  suite and linter step 3 just ran. The green claim is made only when the recorded green commit
  **is** the commit under review; otherwise the dispatch says *unverified* rather than passing on a
  stale pass. The green line is explicit about its two limits: it covers this task's project only
  (sibling-repo work is the reviewer's to verify) and it says the tests pass, never that they are
  good. Targeted runs stay in scope — probing a suspect test, an uncovered case, or a mutation
  still earns its turn, and vacuous coverage of new behavior stays a Major.
- **From round 2 on — and for any `critical`, including in round 1 — an `issues` verdict goes to a
  funding consult before a writer round is spent.** The runner states the bar, which rises a step
  each round: rounds 1–2 fund only blocking findings; round 3 only Blocker-grade harm (data
  corruption, a broken core flow, a wire-contract falsity a consumer would implement against);
  round 4+ only a `critical` verdict. When the round's fix range touched no production code the
  bar applies one step early — a deterministic call from `git diff --name-only`, where a path
  counts as non-production only if it ends `.md` or `_test.go` or has a `tests`, `docs`, or
  `manual` component. The consult judges the findings against the stated bar and returns
  `fix_round`, `merge`, or `bail`. Round cost is flat while the marginal value of extra rounds
  decays hard, which is what the rising bar prices in.
- **Findings never vanish.** A `merge` under open findings records every one of them in
  `flagged_findings` for the operator; a funded fix always gets its next review, so no fix ever
  merges unreviewed. After a fix round the gate re-runs and red gets one fixer round; still red
  proceeds to the next review round, because merge re-checks anyway.

**5. Merge.** A dirty worktree here means an agent wrote outside its commit boundary — protocol
failure. **A red gate cannot merge:** unless HEAD is the commit the gate last verified green, the
gate re-runs, and red bails with `gate_red`. Then `git merge --ff-only` into the base branch and
`git branch -D`. Red can stall a task; it can never ship.

**6. Checkpoint.** A fresh consult judges whether the *remaining* breakdown still holds, given two
deterministic inputs: the merge's `git diff --stat` (truncated to 30 lines) and the grounding
checker's drift summary for the remaining tasks. Its prompt prescribes two-tier
judgment — tier 1 from the history summaries, the review verdict and the stat; tier 2 (reading
diffs and code) only where tier 1 leaves genuine uncertainty, above all a merged file a remaining
`plan.md` grounds itself in. It returns `proceed`, `amend` (it edits upcoming task folders
directly, and the runner re-scans), or `bail`. The checkpoint is **skipped after the last task
merges** — there is no remaining breakdown to judge, and post-slice gaps belong to final
verification.

## Final verification

After every task merges, the runner spawns the **test-agent** at the repo root with
`acceptance_criteria.json` and `verification.json`: run every affected project's full suite and
report findings; live-deploy checks are out of scope. `clean` exits 0 with a summary. `findings`
writes `test_findings.md`, and then a consult judges whether the findings block — the test-agent is
a finder, not a judge. `fix_tasks` bails with `reason=test_findings` so the `/dev:run-slice`
session can turn the findings into new task folders (`/dev:write-task`) and relaunch, which
executes them as ordinary tasks. `proceed_flagged` records them in `flagged_findings` for the
operator and completes the slice.

**Cap: 3 verification rounds**, counted in `state.json` and accumulating across resumes; a fourth
bails. Deploy verification is a separate step `/dev:run-slice` runs at close-out — the project's
slice testing strategy, resolved through the target repo's `CLAUDE.md`
`Slice testing strategy:` line.

## Consults

A consult is a fresh session with no agent definition, spawned with a runner-made prompt: the
trigger, the relevant verdicts and write-ups, pointers into the slice folder, and an explicit
action vocabulary. It writes `consult_<N>.json` with its chosen action and reasoning, optionally
`consult_<N>.md` for detail. The runner maps the action to a transition; an action outside the
offered vocabulary is a protocol failure, and `bail` raises `consult_bail`. Consults are never
reattached after a crash — they are cheap, and their vocabulary may have changed.

| Trigger | Actions |
|---|---|
| Agent reported `blocked`, or a protocol failure | `retry` (offered once per role per task) · `bail` |
| Fix-round cap reached with the gate still red | `fresh_writer` (restart with a fresh writer on the original input, told to test its own work) · `fresh_writer_reset` (same, after dropping every commit made after the writer's last one) · `proceed_to_review` (carry the red gate to review) · `bail` |
| Review round ≥ 2 with `issues`, or any `critical` | `fix_round` · `merge` (findings carded) · `bail` |
| Review round at the backstop cap | `merge` · `bail` — funding is withheld |
| Post-merge checkpoint | `proceed` · `amend` · `bail` |
| Final-verification findings | `fix_tasks` · `proceed_flagged` · `bail` |
