# The task workflow — slices, tasks, and the runner

How a change moves from idea to merged code. Three operator-initiated sessions plus one script:

1. **`/triage`** — turns findings/requests into **slice folders** (numbered, under
   `<spec-repo>/slices/backlog/`), each holding a self-contained `slice.md` change request.
2. **`/plan-slice`** — interactive planning: breaks one slice into ordered, project-local **tasks**
   (plan-writer + plan-reviewer), emits acceptance criteria and verification artifacts, and
   promotes the slice from `slices/backlog/` up into `slices/`.
3. **`/run-slice`** — launches `${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py` as a background shell
   and handles bail-outs. The **script**, not a session, drives execution.

The design principle: **files are durable, sessions are ephemeral.** No long-lived session drives the
work. The runner is the only resident process; every agent it spawns is a fresh headless
`kc session` (a `claude --agent` under the hood) that reads its inputs from the slice folder, does
one job, writes its outputs (including a machine-readable verdict), and exits.

**Two repos, two placeholders.** `<spec-repo>` is the path in the target repo's `CLAUDE.md`
`Spec repo:` line — where slices, tasks, and the run's `state.json`/`log.txt` live. The **target
code repo** is where the runner branches and merges (its git root). A task's `project` is one of
the target repo's components, as named by `kc project list` (from `.kubecoder/project.yaml`). The
project contract is `${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`.

## Escalation ladder

Each level handles what the level below cannot; nothing skips a level.

1. **The runner** counts and enforces: round caps, task order, git mechanics, protocol validity.
   It never judges.
2. **Consult sessions** (fresh Opus, spawned by the runner) judge: is the tester stuck, how to
   proceed at a limit, is a flagged problem real. Triggered only when (a) a bound is hit or (b) an
   agent flags a problem — plus the per-task checkpoint.
3. **The `/run-slice` session** investigates bail-outs: reads `bailout.json` + state, decides or
   defers, optionally authors new tasks (via `/write-task` in a sub-agent), relaunches the runner.
4. **The operator** decides everything above that: scope changes, spec contradictions, pushes.

Agents never work around environmental problems (a broken tool, a failing harness, missing
credentials). They stop and report `blocked` — screaming early is correct behavior.

## Slice folder layout

`/triage` writes a new slice to `slices/backlog/NNN_slug/` holding only `slice.md`; `/plan-slice`
adds the planning artifacts below and promotes the folder to `slices/NNN_slug/`.

```
<spec-repo>/slices/NNN_slug/
  slice.md                   ← /triage: the change request (intent, absorbed sources, Q&A,
                                operator-provided API/spec definitions at signature fidelity)
  acceptance_criteria.json   ← /plan-slice (unchanged schema: id, area, description)
  api_contract.json          ← /plan-slice, when the slice changes wire surfaces
  verification.json          ← /plan-slice seeds; close-out verification fills verdicts
  qa_log.md                  ← /plan-slice: planning Q&A with the operator
  tasks/
    01_slug/                 ← ordered by two-digit prefix; strictly sequential execution
                               (a letter suffix inserts a task: 04a runs between 04 and 05)
      task.json              ← metadata (below)
      plan.md                ← plan-writer: the task's implementation plan
      plan_review.md         ← plan-reviewer verdict on the breakdown/plan
      focus_notes.md         ← code-writer → code-tester hints (what to exercise, where to focus)
      test_results_r<N>.md   ← code-tester round-N writeup (non-trivial findings only)
      code_review_r<N>.md    ← code-reviewer round-N review
      *_result.json          ← per-agent verdicts (contract below)
      consult_<N>.{json,md}  ← consult decisions
  state.json                 ← runner-owned execution state (only the runner writes it)
  log.txt                    ← runner + session output (append; stdout stays quiet unless -v)
  bailout.json               ← runner, written when it exits with a bail-out
  test_findings.md           ← final-verification findings (bail path)
```

Task artifacts live in the specs repo (shared working tree): commit by staging files **by name**,
never `git add -A`.

## task.json

```json
{
  "id": "01",
  "slug": "api_surface",
  "project": "<a component name from `kc project list`>",
  "title": "One-line imperative title",
  "summary": "2-4 sentences: what this task delivers and why it is its own task."
}
```

`project` is exactly one of the target repo's components — the names `kc project list --output=json`
reports (from `.kubecoder/project.yaml`); the runner validates `project` against that set —
**a task never spans projects.** Cross-project work is consecutive tasks with the interface defined
at planning time (the producing task first). Execution order is the two-digit prefix (99 tasks is
plenty, and two digits keeps task ids visually distinct from three-digit slice numbers); there is
no dependency graph — the planner orders tasks so that each can assume all lower-numbered tasks
are merged. A task added mid-run at a specific point gets a letter suffix (`04a_slug` runs between
`04` and `05`) instead of renumbering.

## The verdict contract

Every runner-spawned agent MUST end its session by writing the JSON verdict file named in its
dispatch prompt (always inside the task folder). Shape:

```json
{
  "outcome": "<role-specific enum>",
  "summary": "1-3 sentences for the runner log and consults",
  "details": "optional relative path to a writeup in the task folder"
}
```

| Role | Outcomes |
|---|---|
| code-writer | `done` \| `blocked` \| `missing-task` |
| code-tester | `clean` \| `issues` \| `blocked` |
| code-reviewer | `signoff` \| `issues` \| `critical` |
| test-agent | `clean` \| `findings` \| `blocked` |
| consult | one of the actions offered in its prompt |

- `blocked` — an environmental or premise problem the agent must not work around (details required).
- `missing-task` (writer) — the task needs work outside its own project first (e.g. a backend test
  endpoint for a frontend task). Details name what is missing; the runner bails so the orchestrator
  can author the missing task.
- A missing or unparseable verdict file after the session ends gets **one resume-nudge** (the
  runner resumes the session, asking it to write the verdict now); still missing after that is a
  **protocol failure** — the runner treats it as `blocked`.
- The same one-nudge rule applies to uncommitted changes: a session that ends with a dirty
  worktree is resumed once and asked to commit its work; a still-dirty tree is a bail-out. The
  runner never commits an agent's leftovers itself.

## The task loop (runner-enforced)

For each task, in order:

1. **Branch.** `git checkout -b task/<slice>-<task-id>` from the clone's `main`.
2. **Write.** Fresh `code-writer` session (task folder + plan). It implements, lints, commits its
   work, writes `focus_notes.md`, then its verdict. A writer (or tester) that leaves uncommitted
   changes is nudged once to commit them, so the branch is always clean before the next stage.
3. **Test loop — hard cap 3 rounds.** Fresh `code-tester` (Sonnet) each round, given `slice.md`
   (intent), the task's `plan.md` (edge behavior and what-must-be-tested drive coverage — never
   treated as verified truth), the acceptance criteria, and `focus_notes.md` as hints only. It
   tests from its own grounding; trivial fixes it makes and commits itself (reported only as a
   count); non-trivial issues go in `test_results_r<N>.md` with outcome `issues`, and the **same**
   writer session is resumed to fix them. `clean` exits the loop. A 3rd `issues` round triggers a
   consult.
4. **Review loop — hard cap 2 rounds.** Fresh `code-reviewer` over the branch diff
   (`merge-base..HEAD`), given the full requirements chain — `slice.md` (the authoritative ask),
   `task.json`, `plan.md` (requirement decomposition, pinned cross-task interfaces), acceptance
   criteria. It judges **outcomes, not approach**: deviating from the plan while meeting the
   requirements is not a finding; a missed planned edge behavior, a broken pinned interface, or a
   silent substitution against `slice.md` is. Both tester and reviewer are told the slice spans
   multiple tasks — only this task's scope is under test/review. `signoff` → merge.
   `issues` → the writer session fixes, one fresh tester round re-tests, then review round 2.
   Round 2 without signoff triggers a consult (typically: merge with the findings flagged for the
   operator at slice end, or bail).
5. **Merge.** Fast-forward the task branch into the clone's `main`; delete the branch.
6. **Checkpoint.** Fresh consult reads the slice state and the merged result: `proceed`, `amend`
   (it edits upcoming task folders directly — inserting or adjusting tasks), or `bail`.

Commit discipline makes resets safe: the writer's work is always committed before a tester runs, so
"drop the tester's changes" is a clean `git reset --hard` to the last writer commit.

## Final verification (v1)

After all tasks merge, the runner spawns the **test-agent** (Sonnet) with a handover assembled from
`acceptance_criteria.json`/`verification.json`: run the full suites, report findings. `clean` →
runner exits 0 with a summary. `findings` → `test_findings.md`, then a **consult judges whether the
findings block** (the test-agent is a finder, not a judge): `fix_tasks` → bail-out
`reason=test_findings`, and the `/run-slice` session turns the findings into new task folders
(`/write-task`) and relaunches the runner, which executes them as ordinary tasks;
`proceed_flagged` → the findings are non-blocking (pre-existing, dormant, out-of-scope) — recorded
in `flagged_findings` for the operator (issue-tracker items at close-out) and the slice completes. **Cap:
3 verification rounds** (tracked in `state.json`); a 4th bails to the operator. Deploy verification
is separate — `/run-slice`'s final close-out step runs the **slice testing strategy defined for this
project**, resolved through the target repo's `CLAUDE.md` `Slice testing strategy:` pointer (this
plugin never names the doc).

## Consults

A consult is a fresh session (no agent definition, Opus) spawned with a target-made prompt: the
trigger, the relevant verdicts/writeups, pointers into the slice folder, and an explicit action
vocabulary. It writes `consult_<N>.json` (chosen action + reasoning) and may write
`consult_<N>.md` for detail. The runner maps the action to a transition; an action outside the
offered vocabulary is a protocol failure → bail.

Standard vocabularies:

- **Tester limit (3rd `issues`):** `fresh_writer` (restart with a fresh writer, original input,
  told to test its own work) · `fresh_writer_reset` (same, after dropping all tester commits) ·
  `proceed_to_review` · `bail`.
- **Review limit (round 2 not signoff):** `merge_flagged` (merge; findings surface at slice end as
  issue-tracker items + operator review) · `bail`.
- **Agent flagged `blocked`/protocol failure:** `retry` (once) · `bail`.
- **Checkpoint:** `proceed` · `amend` · `bail`. The prompt carries the merge's file stat and
  prescribes **two-tier judgment**: tier 1 from the history summaries, review verdict, and stat;
  tier 2 (reading diffs/code) only where tier 1 leaves genuine uncertainty — above all a merged
  file a remaining task's `plan.md` grounds itself in.
- **Final-verification findings:** `fix_tasks` (blocking — bail so the orchestrator authors fix
  tasks) · `proceed_flagged` (non-blocking — flag for the operator, complete the slice) · `bail`.

## state.json / bailout.json / exit codes

`state.json` is written atomically by the runner only. It records per task: status
(`pending|in_progress|merged|failed`), branch, rounds used, session ids, and an append-style
`history` list (one entry per agent run: ts, role, round, outcome, session id, **transcript path**,
duration). The transcript path points at the session's conversation JSONL under
`~/.claude/projects/` (its sub-agents sit next to it under `<session-id>/subagents/`), so any
later session can research exactly what an agent saw and did. Slice-level: `phase`
(`tasks|final_verification|done|bailed`) and `verification_rounds`.

`bailout.json`: `{"reason": "<enum>", "task": "<id|null>", "details": "...", "consult": "<path|null>"}`.
Reasons: `missing-task`, `blocked`, `tester_limit`, `review_limit`, `test_findings`,
`verification_limit`, `protocol_failure`, `timeout`, `consult_bail`.

Exit codes: `0` slice complete · `3` bailed (`bailout.json` written) · `2` usage/preconditions ·
`1` unexpected error. Resume with `task_runner.py run <slice-dir> --resume`: merged tasks are
skipped, the in-flight task restarts from its last clean point, and task folders added since the
last run (next free number, or a letter suffix for a specific insertion point) are picked up
automatically — the runner re-scans `tasks/` before every task.

**Crash recovery.** `state.json` tracks the in-flight agent session (`in_flight`: task, role,
session id). When a run dies mid-agent (host restart, quota stop, Ctrl-C), `--resume` reattaches:
the worktree is preserved exactly as the crash left it and the interrupted session is resumed with
a recovery prompt (reassess, finish, commit, write the verdict). Consults are never reattached
(cheap, and their action vocabulary may have changed), and a timed-out session is never reattached
— a stuck agent is a problem to surface, not to continue.

## Session mechanics

The runner drives every session through `kc session` — `create-headless` (assigns a name),
`send` (synchronous; owns SSE reconnect and interrupt-on-kill), `status --output=json` (reads back
the claude `sessionId`), `end`. `kc` owns the raw process/stream mechanics the retired
`claude_session.py` used to; the runner keeps only the loop, caps, git, and verdict validation.
Details:

- All runner and session output written to `<slice>/log.txt` (stdout only under `-v/--verbose`) —
  progress never lands in a calling session's context; outcomes are read from the exit code,
  `state.json`, and `bailout.json`. The log names every spawned session id + transcript path and
  is **committed with the slice artifacts at close-out** — with `state.json` it is the complete
  who-did-what record of the run.

- `--agent dev:<role>` for dev agents (the plugin's agents install namespaced as `dev:<role>`);
  consults run bare (no `--agent`).
- `--cwd` = the task's component directory (dev agents; the effective cwd from `kc project list`)
  or the target repo root (consults, test-agent) — so a dev session loads its component's
  `CLAUDE.md` and docs. The repo root comes from `git rev-parse --show-toplevel`.
- `-e FORCE_PROMPT_CACHING_5M=1` on `create-headless` — ephemeral sessions must not pay the 1-hour
  cache-write premium (the env pass-through threads it to the spawned `claude`).
- Models: code-tester and test-agent run `--model sonnet`; everything else inherits the default.
- Timeouts: writer/tester/test-agent 7200s, reviewer 3600s, consults 1800s, nudges 900s. A timeout
  is a bail (`reason=timeout`), not a retry — a stuck agent is a problem to surface, not to mask.
  On timeout the runner SIGINTs the `send` (which fires a worker interrupt) and ends the session.
