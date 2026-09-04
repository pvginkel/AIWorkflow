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
  the 1-hour cache-write premium. **`-e CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`** and
  **`-e CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`** beside it: a dispatched role never reads or writes
  the operator's auto-memory and never invokes a bundled skill, so neither listing rides in its
  prefix (≈ 3 k tokens of every turn). Project knowledge reaches a role through the project's
  `CLAUDE.md` and procedure docs, never through the operator's memory. The set lives once, as
  `SPAWN_ENV` in `run_loop.py`.
- **`--disable-slash-commands`** on every `create-headless`, and **`--strict-mcp-config`** on every
  one but the test-agent's — `kc` passes both through to the spawned claude, finishing the trim the
  env vars start. The first drops both plugins' skill listings from the prefix (a headless role
  invokes no skill; the plugin's *agents* are not skills and still register — `--agent dev:<role>`
  and the Agent tool's sub-agents are untouched). The second, with no `--mcp-config` beside it,
  spawns with no MCP server at all: the operator's `~/.claude.json` servers' tool schemas and
  instructions leave the prefix, and with them a reach no role's contract ever gave it — a finding
  goes to the close-out report, never to a tracker; CI is the test-agent's. The test-agent keeps
  the operator's servers whole because it drives CI through Jenkins, a server the operator's config
  names and the plugin cannot. Sub-agents inherit the dispatching session's trim; a nudge resumes
  with the role's own flags, since a prefix that differs from the original's misses the cache. With
  the env vars, ≈ 7–8 k tokens off every turn's prefix — measured 2026-08-23 at `ctx1` 24.0–25.6 k
  per role against the corpus's 31–34 k. Once, as `SPAWN_FLAGS` / `spawn_flags()` in `run_loop.py`.
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
**test-fixer** (mechanical suite repair), and the **rebase-agent** — and the one always-Fable
agent, the **refinement-writer**, which pins `model: fable`: it writes the operator's decision
document from the plan-slice session's material and nothing else
([refinement.md](refinement.md)); the interactive session that dispatches it runs whatever the
operator chose.

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
and write-back stays with the dispatching agent. Two *writes* are delegated. The doc phase's:
the doc-writer coordinator packages a slice's doc work into `units.json` and a `dev:doc-unit`
sub-agent authors each package's pages — the pages are independent per doc scope, and the writes
that need the whole picture (indexes, decision ids, cross-scope consistency, the commit, the
verdict) stay with the coordinator ([run-loop.md](run-loop.md) § Doc phase). And the
interview's: the plan-slice session hands its grounded material to the `dev:refinement-writer`,
which writes `refinement.md` for the operator and returns a receipt; the grounding, the rulings
and the plan stay with the session ([refinement.md](refinement.md)).

Sub-agents hand back **receipts and conclusions, never evidence**: evidence handed upward sits in
the caller's context for the rest of its session, which is exactly the cost the delegation exists
to avoid. `Explore` is the leaf — it cannot dispatch agents, so it is the terminal reader of
every delegation tree.

**Delegate, then yield.** The Agent tool is asynchronous: a sub-agent's report reaches the
dispatching session when the harness re-invokes it, which for a headless session means after it
ends its turn — `kc session send` keeps stdin open and resolves only on the terminal result, so
ending a turn with a sub-agent in flight is a wait, not a hand-back. A session that dispatches
and carries on does the delegated work itself meanwhile and then pays to carry a report it no
longer needs: in the doc-writer sessions read for the doc-phase rework
(`docs/research/doc-phase-plan.md` § 1), every survey report landed 18–49 turns after dispatch,
past the writer's first edit, at 15–21 % of the session. So a role that delegates ends the turn
with nothing else in flight; the doc-writer's contract says so in its own words (it yields
twice — for its survey, then for its units), and the plan-writer/plan-reviewer overlap (17–18 %)
is the same pattern, not yet addressed.

The wait has one race, the harness's, not the role's. A completion that lands while the session
is mid-turn is queued for its next turn, but the engine counts it delivered; a session that then
ends that turn to wait for the very task that has already finished ends the send, and the queued
report dies with the process — slice 198 P6's registry push, slice 201's fourth survey (its
report finished 13 seconds before the coordinator's last turn ended). The first prompt into such
a session is consumed by the harness's stopped-task bookkeeping and never reaches the model, so
the driver sends a nudge answered with that synthetic no-op once more
([run-loop.md](run-loop.md) § Protocol invariants); the engine-side fix is KubeCoder's (Triage
#840). Nothing here changes what a role does: it ends the turn with nothing else in flight, and
when a resume brings one report of several, it ends the turn again.
