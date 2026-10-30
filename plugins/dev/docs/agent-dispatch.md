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

- **`--agent dev:<role>`** for the dev, plan, test, doc and wrap-up agents — the definitions ship with the
  plugin (`${CLAUDE_PLUGIN_ROOT}/agents/`) and are dispatched **namespaced**, so the lookup cannot
  land on a same-named agent the target repo happens to ship. Consults run bare: no
  agent definition, the prompt is the whole protocol. `create-headless` does **not** validate the
  agent name — an unknown one spawns a plain SDK session that answers anyway — so both scripts
  assert their definitions exist before dispatching anything.
- **cwd** is the invoking repo's root for every dispatch — including phases targeting a sibling
  repo: the definitions resolve from the plugin regardless of cwd, and the dispatch prompt carries
  the sibling's path; the *driver's* git and gate operations root at the `Target:` repo — at its
  worktree, for a shared target ([run-loop.md](run-loop.md) § The plan is the queue).
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
  and the Agent tool's sub-agents are untouched). A skill the plan names still reaches the
  role that needs it, as a file: where a phase's section or the plan's text outside every phase
  names `` `<plugin>:<skill>` ``, the driver resolves it through
  `~/.claude/plugins/installed_plugins.json` and puts the installed `SKILL.md`'s path in that
  phase's executor, fix-round and reviewer dispatches — and the plan loop, from `slice.md` and
  `plan.md`, in the plan-writer's and the plan-reviewer's. A name no installed plugin carries is
  said so, so the role does not search the disk for it. The second keeps the operator's `~/.claude.json`
  servers out of a role's session: their instructions leave the prefix (their tool schemas were
  never in it — Claude Code defers them since 2.1.212), and with them a reach no role's contract
  ever gave it — a finding about the work goes to the close-out report, never to a tracker; CI is
  the test-agent's. **The promoted servers are the exception**: `PROMOTED_MCP_SERVERS` in
  `run_loop.py` names them. `fieldnotes`, because what got in a role's way while it worked goes
  there and not into the report ([close-out.md](close-out.md#what-it-is--and-is-not)), and a role
  that cannot post cannot follow that rule. `gitblit`, the read-only mirror of the operator's
  repos, because a role — or a slice ruling it follows — may need the code of a repo the
  environment does not check out; it carries no token and reaches no tracker. `kubecoder-worker`,
  the environment's own worker, for its `notification` tool, so a ruling that asks a role to keep
  the operator posted works as written; its session header (`${KUBECODER_SESSION_NAME:-}`) is
  copied unexpanded and the spawned claude expands it. Pilot's own server is not promoted: the
  stage's session registers every document on the roles' behalf ([pilot.md](pilot.md)). The loop
  copies each named entry verbatim out of the user-level `mcpServers` of `~/.claude.json` into
  `~/.claude/aiworkflow-promoted-mcp.json` (mode 0600, written atomically, once per process at the
  first dispatch) and passes that path as `--mcp-config` beside `--strict-mcp-config`. An entry
  may carry a bearer token, which is why it travels as a file under the home and never on a command
  line, in the log or in a slice folder. A promoted server the operator's config does not hold is
  one line in `log.txt` and a role spawned without it, never a failed run. The test-agent keeps
  the operator's servers whole because it drives CI through Jenkins, a server the operator's config
  names and the plugin cannot. Sub-agents inherit the dispatching session's trim; a nudge resumes
  with the role's own flags, since a prefix that differs from the original's misses the cache. With
  the env vars, ≈ 7–8 k tokens off every turn's prefix — measured 2026-08-23 at `ctx1` 24.0–25.6 k
  per role against the corpus's 31–34 k, before a promoted server's instructions came back into it.
  Once, as `SPAWN_FLAGS` / `spawn_flags()` in `run_loop.py`.
- Session output goes to the loop's log file, never stdout (`-v` echoes it) — progress must not
  land in a calling session's context. The turn's response text is read back (`send`'s
  `--response-file`) solely to detect the account session-limit notice below; outcomes come only
  from verdict files.

## Models — one config, explicit flags, no grading

**Everything runs Opus at `xhigh`**, set explicitly via `--model`/`--reasoning-effort` on every
outer dispatch from a single config per script (`MODELS` in `run_loop.py` / `plan_loop.py`):
code-writer, code-reviewer, doc-writer, wrap-up, plan-writer, plan-reviewer, and every consult.
Sub-agents
inherit from the dispatching session — the intended mechanism; ambient inheritance is the
*absence* of the explicit flags.

The only exceptions are the **always-Sonnet agents**, which additionally pin `model: sonnet` in
their own definitions so they stay Sonnet even as sub-agents: **test-agent** (the test phase),
**test-fixer** (mechanical suite repair), and the **rebase-agent**. Two Opus agents pin their
model too. The
**plan-preparer** pins `model: opus` and `effort: xhigh`: it grounds the slice and writes the
requirements asks the operator rules on, and that work does not inherit the model of the stage's
session ([plan-slice](../skills/plan-slice/SKILL.md)). The **wrap-up** pins `model: opus` too, though the driver is its one caller now
and passes the same flags: what fixes code unreviewed runs on Opus whoever dispatches it
([close-out.md](close-out.md#the-wrap-up)).

There is no per-task grading and no model routing by difficulty — the graded lane measured out:
the premium tier bought nothing on an inflated base, and "mechanical" routing produced Opus redos
whenever mechanical turned out to mean judgment.

## Timeouts

Run-loop sessions: code-writer, doc-writer and wrap-up 7200s, code-reviewer 3600s, consults
1800s, test-agent 14400s (it waits out a CI build). Plan-loop sessions: plan-writer 7200s, plan-reviewer
3600s. Both scripts give a protocol nudge 900s, and the gate subprocess 3600s. A timeout is a
bail, not a retry — a stuck agent is a problem to surface, not to mask; the wrap-up's is the one
that does not stop the run ([run-loop.md](run-loop.md) § After the last phase). On timeout the dispatch
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
and write-back stays with the dispatching agent. A stage's session is the exception: it judges
nothing it would have to read for, so its reading and the writing that rests on it go to
sub-agents pointed at the slice folder — the `dev:plan-preparer` grounds a slice and writes its
requirements asks, and a sub-agent carries each answered document into the plan
([pilot.md](pilot.md)). The doc phase's pages are not delegated:
a per-scope authoring sub-agent was built (0.9.14) and read on nine slices — about twice the cost
per phase of shipped work, a fresh session re-orienting on every hand-over brief — and reverted
(`docs/research/doc-phase-read-2026-09-04.md` § 5–6); the doc-writer surveys through sub-agents
and writes every page itself.

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
with nothing else in flight; the doc-writer's contract says so in its own words, and the
plan-writer/plan-reviewer overlap (17–18 %) is the same pattern, not yet addressed. A stage's
own session, `/dev:plan-slice` or `/dev:run-slice` under Pilot, is no role and waits the other
way: a turn's end is its work item's, so it dispatches every sub-agent in the foreground
([pilot.md](pilot.md) § A turn's end is the run's end).

**Ending the turn is a reply with no tool call.** A no-op command — `true`, `echo waiting` — is
a spin, not a wait: every tool call re-invokes the model, and each return re-reads the whole
context at cache-read price. Slice 197's doc-writer wrote "ending the turn until they report"
354 times, each beside a `true`, and never ended it — $21.49 of a $32.17 phase
(`docs/research/doc-phase-read-2026-09-04.md` § 5, finding 19). A role that has dispatched and
has nothing else to do replies in prose and stops.

**Every role is told it is not a sub-agent.** The managed CLAUDE.md gives two rules: a session
waits on backgrounded work by ending its turn, and a sub-agent waits in the foreground, because
its ended turn is its report. A role the driver dispatches matches both descriptions, and a
PilotApp code-writer that backgrounded a 4-minute gate could not tell which was its own and
built a waiter by hand (2026-10-23). So the first prompt `run_kc_session` sends a fresh session,
in either loop, opens with one line (`HEADLESS_WAIT_LINE`). It says the role is its own headless
session, so a command it backgrounds re-invokes it. It runs a gate in the foreground under
`timeout(1)` when the gate fits the Bash tool's 10-minute cap, backgrounds only what can outrun
that, and waits on it by ending the turn, never by polling or a waiter of its own. Foreground is
the default because it has no race, unlike the wait below.

The wait has one race, the harness's, not the role's. A completion that lands while the session
is mid-turn is queued for its next turn, but the engine counts it delivered; a session that then
ends that turn to wait for the very task that has already finished ends the send, and the queued
report dies with the process — slice 198 P6's registry push, slice 201's fourth survey (its
report finished 13 seconds before the doc-writer's last turn ended). The first prompt into such
a session is consumed by the harness's stopped-task bookkeeping and never reaches the model. The
driver reads that no-op: a session that also owes its verdict is resumed with a recovery prompt
in place of the nudge it lost — the report is gone but the sub-agent's transcript is saved, and
the harness's notice says so — and recovers the report and finishes; the other nudges are sent
once more ([run-loop.md](run-loop.md) § Protocol invariants). The engine-side fix is KubeCoder's.
Nothing here changes what a role does: it ends the turn with nothing else in
flight, and when a resume brings one report of several, it ends the turn again.
