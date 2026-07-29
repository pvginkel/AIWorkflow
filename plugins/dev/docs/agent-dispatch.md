# Dispatching agents — session mechanics, models, and nested delegation

How the workflow's two scripts spawn the sessions that do the work, and the house rule any agent
follows when it delegates further. The loops themselves are [plan-loop.md](plan-loop.md) and
[task-runner.md](task-runner.md).

## Spawning

Both scripts go through `task_runner.py`'s `run_kc_session`, which maps one dispatch onto the
`kc session` verbs: `create-headless` assigns a session name, `send` runs the turn synchronously
(it owns the SSE stream and fires a worker interrupt when signalled), `status --output=json` reads
back the claude `sessionId` — the transcript locator and the crash-reattach handle — and `end`
tears the session down, always and best-effort, so no session outlives its dispatch. `kc` owns the
raw process and stream mechanics; the scripts keep only the loop, the caps, git, and verdict
validation.

- **`--agent dev:<role>`** for the dev and plan agents — the plugin's agents install namespaced,
  and the dispatch namespaces the bare role itself. Consults run bare: no agent definition, the
  prompt is the whole protocol.
- **cwd** is the task's component directory (the effective cwd from `kc project list`) for the
  code-writer, test-fixer and code-reviewer, so the session loads that component's `CLAUDE.md` and
  docs. Consults, the test-agent, and both plan agents run at the target repo's root.
- **`-e FORCE_PROMPT_CACHING_5M=1`** on every `create-headless`: ephemeral sessions must not pay
  the 1-hour cache-write premium.
- Session output goes to the loop's log file, never stdout (`-v` echoes it) — progress must not
  land in a calling session's context. The turn's response text is read back (`send`'s
  `--response-file`) solely to detect the account session-limit notice below; outcomes come only
  from verdict files.

## Model routing (D177)

`task.json`'s `grade` routes the code-writer's **initial implementation round** only:
`mechanical` → Sonnet, `standard` → Opus, `gnarly` → Fable. An absent or unrecognized grade
falls back to Opus. The planner grades at breakdown time (criteria live in the plan-writer's agent
definition); doubt resolves to Opus, because an under-graded round 1 predictably burns review
rounds while an over-grade costs a bounded premium.

**Every other writer round runs Opus** — the gate fix round, the review fix round, the respawn
after a `blocked` writer, and the fresh writer spawned after the fix-round cap — so a misgraded
round 1 is corrected by the default model, never compounded by the graded one. A fix-round writer
that follows a **Sonnet** round 1 is told so, and licensed to redo the implementation rather than
patch it; a Fable round 1 gets no such note.

The remaining runner roles are pinned: code-reviewer Opus, consult Opus, test-fixer Sonnet,
test-agent Sonnet. The **plan-writer and plan-reviewer pin nothing** — the plan loop passes no
model and their agent definitions declare none, so they run on whatever model the CLI resolves.

## Timeouts

Runner sessions: code-writer and test-agent 7200s, test-fixer and code-reviewer 3600s, consults
1800s. Plan-loop sessions: plan-writer 7200s, plan-reviewer 3600s. Both scripts give a protocol
nudge 900s, and the runner's gate subprocess 3600s. A timeout is a bail, not a retry — a stuck
agent is a problem to surface, not to mask. On timeout the dispatch interrupts the `send` (which
posts a worker interrupt, so the turn is never stranded) and ends the session.

## Account session limits are not an agent outcome

A session killed by the API's "You've hit your session limit · resets …" notice surfaces that
notice as its whole output instead of doing any work. The runner detects it (only when the verdict
is invalid, so a completed session is never mistaken for one), records a `session_limit` history
row, sleeps until the stated reset plus a five-minute grace — half an hour when the reset does not
parse, and never more than twelve hours in one wait — and then **redispatches the same round**. No
nudge, no consult into the same wall, and nothing counted: the round number is reused and no
reviewed-HEAD marker is stamped.

## Nested delegation

Every agent — including one a script spawned — can dispatch sub-agents of its own. The working
rule: **delegate the reading, keep the judgment.** Mechanical, independent, per-item work — checking
a ledger's citations, hunting the evidence for one verification entry, surveying one axis of a
subsystem, spot-reading a list of flagged files — fans out to parallel sub-agents that return
conclusions. Every verdict, severity call, and write-back stays with the dispatching agent.

Sub-agents hand back **receipts and conclusions, never evidence**: evidence handed upward sits in
the caller's context for the rest of its session, which is exactly the cost the fan-out exists to
avoid. `Explore` is the leaf — it cannot dispatch agents, so it is the terminal reader of every
fan-out tree.
