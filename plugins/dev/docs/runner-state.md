# The run loop's run record — state, bail-outs, and resume

What `${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py` writes down, and how a run picks up where it
stopped. This is what a `/dev:run-slice` session reads to decide anything: the driver's stream never
reaches it, so the exit code, `state.json`, and `bailout.json` are the whole interface. The loop
those files record is [run-loop.md](run-loop.md).

## state.json

Written atomically by the driver and by nothing else. Slice level:

`slice`, `created_at`, `updated_at`, `orchestrator` (the launching session's id and transcript
path, or `null` for a hand-run), `run_phase` (`phases` | `consult` | `test` | `docs` | `done` |
`bailed`), `bases` (base branch per target repo), `slice_base` (the sha each repo stood at before
the slice — the doc phase's diff base), `known_phases` (the plan's phase ids in document order,
as last parsed), `generation` (follow-up generations spent), `test_rounds`, `sweep_runs`,
`gate_sweep` (the loop-tail sweep's record: per-command `results` with log paths, `green`, and
the exact `commits` it ran on — reused while every swept HEAD matches, re-run otherwise),
`consult_seq`, `in_flight`, `cards`, `phases`, and `history`.

Per phase: `status` (`pending` | `in_progress` | `merged`), `stage` (`executor` | `gate` |
`review` | `merging` | `null`), `branch`, `target`, `executor_rounds`, `gate_fix_rounds`,
`review_rounds`, `reviewed_head`, `gate_runs`, and the gate's evidence pair `gate_green_commit` /
`gate_green_log`.

`history` is append-only, one entry per agent run plus one per gate run (role `gate`), one per
loop-tail sweep (role `sweep`), one per doc gate (role `doc-gate`) and one per consult: `ts`,
`phase`, `role`, `round`, `outcome`, `summary`, `session`, `transcript`, `duration_s`. The
**transcript path** points at that session's conversation JSONL under
`~/.claude/projects/`, with its own sub-agents beside it under `<session-id>/subagents/`, so any
later session can research exactly what an agent saw and did. That is why `/dev:run-slice` commits
`state.json` and `log.txt` with the slice artifacts at close-out: together they are the run's
complete who-did-what record.

**Every timestamp both loops write or print** — the `ts` fields here, the `[HH:MM:SS]` prefixes in
`log.txt` and on the stdout announce lines, the dates stamped into `plan.md` — is the **operator's
local wall clock**, taken from the process's `TZ` (UTC when unset). The ISO stamps stay
offset-aware, so they remain unambiguous to anything that parses them back.

**`cards`** is the close-out hand-off list — one entry per finding disposition (a review merged
with unresolved advisory findings, a below-bar test finding, anything an agent's verdict carded),
each with its source and timestamp, recorded as findings land. `/dev:run-slice` files one
issue-tracker card per entry at close-out; the list is a mechanical read, not a memory.

Session outputs live under `<slice>/phases/P<id>/` (review docs, gate logs, verdict files) and at
the slice root for the consult/test/doc stages; the loop-tail sweep's logs live under
`<slice>/sweeps/r<N>/`. Executor inputs come from `plan.md`, never from copies.

## bailout.json and exit codes

```json
{"reason": "<enum>", "phase": "<id|null>", "details": "…", "consult": "<path|null>", "question": false, "ts": "…"}
```

Deleted at the start of every run, so its presence always means *this* run bailed. `question`
splits the two bail classes: `true` exits 4 (only the operator can move it), `false` exits 3 (an
error the orchestrator diagnoses).

| Reason | Question? | Raised when |
|---|:-:|---|
| `operator_question` | ✓ | an executor or the doc-writer returned `question` |
| `plan_doc` | ✓ | the plan doc is broken and no session could fix it on a nudge |
| `generation_exhausted` | ✓ | a third follow-up generation of appended work is pending |
| `blocked` | – | an agent reported `blocked`, or a protocol failure after the nudge |
| `gate_red` | – | the gate stayed red through the executor fix cap, or at merge |
| `consult_bail` | – | any consult chose `bail` |
| `devlock_timeout` | – | the dev occupancy lease stayed held past the wait cap |
| `timeout` | – | a driver-run gate or sweep command exceeded its limit, or an agent session did with no usable verdict on disk |
| `unpushed` | – | a repo the slice touched was still behind `origin/<base>` after the test phase and its push nudges |
| `protocol_failure` | – | a git command failed, an agent left uncommitted changes, a consult chose an unoffered action, the worktree was dirty at merge, an agent committed the driver's run record onto the phase branch, or a `CLAUDE.md` procedure-doc pointer is missing |

Exit codes: **0** slice complete · **3** error bail · **4** operator question · **2** usage or
precondition — a `state.json` that exists without `--resume`, a missing/unparseable `plan.md` or
missing `verification.json`, a dirty tree at preflight, or a missing agent definition · **130**
interrupted · **1** unexpected error.

## Resume and crash recovery

`run_loop.py run <slice-dir> --resume` continues from `state.json`: stamped phases are skipped
(the plan is re-parsed, so phases appended since the bail are picked up), the in-flight phase
restarts from its last clean stage, and a bail from the test or doc stage re-enters that stage
rather than replaying the consult→test ladder. Resume skips preflight entirely — the caller owns
the state it resumes into.

When a run dies mid-agent (host restart, quota stop, Ctrl-C), the `in_flight` record — phase,
role, round, verdict path, session id, start time — lets `--resume` **reattach**: the worktree is
left exactly as the crash left it, and the interrupted session is resumed with a recovery prompt
instead of a fresh dispatch. A reattached round keeps the round number its interrupted dispatch
ran under, so caps do not re-fire and counters do not double-advance.

Two things are deliberately never reattached: **consults**, which are cheap and whose action
vocabulary may have changed, and **timed-out sessions**, whose `in_flight` record is cleared as
soon as the timeout fires — a stuck agent is a problem to surface, not to continue.

A timeout reads the verdict file before it bails, though. Every dispatch unlinks that file first,
so one present when the timeout fires was written by this round: the agent finished its work,
committed it, and the turn wedged afterwards. The driver takes that verdict and counts the round
normally rather than discarding work already on disk — and because the verdict is the last step of
every role's protocol, a salvaged round is a complete one. The bail fires only when the verdict is
missing or unparseable. The devlock is in-process (`flock`), so a crash releases it by
construction.
