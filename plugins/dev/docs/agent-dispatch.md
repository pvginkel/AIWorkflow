# Dispatching agents — session mechanics, models, and nested delegation

How the workflow's two scripts spawn the sessions that do the work, and the house rule any agent
follows when it delegates further. The loops themselves are [plan-loop.md](plan-loop.md) and
[run-loop.md](run-loop.md).

## Spawning

Both scripts go through `run_loop.py`'s `run_kc_session`, which maps one dispatch onto the
`kc session` verbs: `create-headless` assigns a session name, `send` runs the turn synchronously
(it owns the SSE stream and fires a worker interrupt when signalled), `status --output=json` reads
back the claude `sessionId` — the transcript locator and the crash-reattach handle — and `end`
tears the session down, always and best-effort, so no session outlives its dispatch. `kc` owns the
raw process and stream mechanics; the scripts keep only the loop, the caps, git, and verdict
validation.

- **`--agent dev:<role>`** for the dev, plan, test and doc agents — the definitions ship with the
  plugin (`${CLAUDE_PLUGIN_ROOT}/agents/`) and are dispatched **namespaced**, so the lookup cannot
  land on a same-named agent the target repo happens to ship. Consults run bare: no
  agent definition, the prompt is the whole protocol. `create-headless` does **not** validate the
  agent name — an unknown one spawns a plain SDK session that answers anyway — so both scripts
  assert their definitions exist before dispatching anything.
- **cwd** is the invoking repo's root for every dispatch — including phases targeting a sibling
  repo: the definitions resolve from the plugin regardless of cwd, and the dispatch prompt carries
  the sibling's path; the *driver's* git and gate operations root at the `Target:` repo.
- **`-e FORCE_PROMPT_CACHING_5M=1`** on every `create-headless`: ephemeral sessions must not pay
  the 1-hour cache-write premium.
- Session output goes to the loop's log file, never stdout (`-v` echoes it) — progress must not
  land in a calling session's context. The turn's response text is read back (`send`'s
  `--response-file`) solely to detect the account session-limit notice below; outcomes come only
  from verdict files.

## Models — one config, explicit flags, no grading

**Everything runs Opus at `xhigh`**, set explicitly via `--model`/`--reasoning-effort` on every
outer dispatch from a single config per script (`MODELS` in `run_loop.py` / `plan_loop.py`):
code-writer, code-reviewer, doc-writer, plan-writer, plan-reviewer, and every consult. Sub-agents
inherit from the dispatching session — the intended mechanism; ambient inheritance is the
*absence* of the explicit flags.

The only exceptions are the **always-Sonnet agents**, which additionally pin `model: sonnet` in
their own definitions so they stay Sonnet even as sub-agents: **test-agent** (the test phase),
**test-fixer** (mechanical suite repair), and the **rebase-agent**.

There is no per-task grading and no model routing by difficulty — the graded lane measured out:
the premium tier bought nothing on an inflated base, and "mechanical" routing produced Opus redos
whenever mechanical turned out to mean judgment.

## Timeouts

Run-loop sessions: code-writer and doc-writer 7200s, code-reviewer 3600s, consults 1800s,
test-agent 14400s (it waits out a CI build). Plan-loop sessions: plan-writer 7200s, plan-reviewer
3600s. Both scripts give a protocol nudge 900s, and the gate subprocess 3600s. A timeout is a
bail, not a retry — a stuck agent is a problem to surface, not to mask. On timeout the dispatch
interrupts the `send` (which posts a worker interrupt, so the turn is never stranded) and ends
the session.

## Account session limits are not an agent outcome

A session killed by the API's "You've hit your session limit · resets …" notice surfaces that
notice as its whole output instead of doing any work. The driver detects it (only when the
verdict is invalid, so a completed session is never mistaken for one), records a `session_limit`
history row, sleeps until the stated reset plus a five-minute grace — half an hour when the reset
does not parse, and never more than twelve hours in one wait — and then **redispatches the same
round**. No nudge, no consult into the same wall, and nothing counted.

## Nested delegation

Every agent — including one a script spawned — can dispatch sub-agents of its own. The working
rule: **delegate the reading, keep the judgment.** Mechanical, independent, per-item work —
hunting the evidence for one verification item, surveying one axis of a subsystem, a rebase, a
red-suite repair — goes to a sub-agent that returns conclusions. Every verdict, severity call,
and write-back stays with the dispatching agent.

Sub-agents hand back **receipts and conclusions, never evidence**: evidence handed upward sits in
the caller's context for the rest of its session, which is exactly the cost the delegation exists
to avoid. `Explore` is the leaf — it cannot dispatch agents, so it is the terminal reader of
every delegation tree.
