# The runner's run record — state, bail-outs, and resume

What `${CLAUDE_PLUGIN_ROOT}/tools/task_runner.py` writes down, and how a run picks up where it
stopped. This is what a `/dev:run-slice` session reads to decide anything: the runner's stream
never reaches it, so the exit code, `state.json`, and `bailout.json` are the whole interface. The
loop those files record is [task-runner.md](task-runner.md).

## state.json

Written atomically by the runner and by nothing else. Slice level:

`slice`, `created_at`, `updated_at`, `orchestrator` (the launching session's id and transcript
path, or `null` for a hand-run), `phase` (`tasks` | `final_verification` | `done` | `bailed`),
`base_branch`, `verification_rounds`, `consult_seq`, `in_flight`, `flagged_findings`, `tasks`, and
`history`.

Per task: `status` (`pending` | `in_progress` | `merged`), `stage` (`writer` | `testing` |
`review` | `merging` | `null`), `branch`, `writer_session`, `writer_rounds`, `test_rounds`,
`review_rounds`, `reviewed_head`, `last_writer_commit`, `gate_runs`, and the gate's evidence pair
`gate_green_commit` / `gate_green_log`.

`history` is append-only, one entry per agent run plus one per gate run (role `gate`) and one per
consult: `ts`, `task`, `role`, `round`, `outcome`, `summary`, `session`, `transcript`,
`duration_s`. The **transcript path** points at that session's conversation JSONL under
`~/.claude/projects/`, with its own sub-agents beside it under `<session-id>/subagents/`, so any
later session can research exactly what an agent saw and did. That is why `/dev:run-slice` commits
`state.json` and `log.txt` with the slice artifacts at close-out: together they are the run's
complete who-did-what record.

`flagged_findings` is the hand-off list for the operator — one entry per task that merged under
open review findings and one per non-blocking final-verification finding, each naming the review or
findings file and the consult's reasoning. `/dev:run-slice` turns each into an issue-tracker item
at close-out.

## bailout.json and exit codes

```json
{"reason": "<enum>", "task": "<id|null>", "details": "…", "consult": "<path|null>", "ts": "…"}
```

Deleted at the start of every run, so its presence always means *this* run bailed.

| Reason | Raised when |
|---|---|
| `missing-task` | the writer needs work outside its own project first |
| `blocked` | the test-agent reported `blocked` |
| `tester_limit` | the fresh writer spawned after the fix-round cap did not report `done` |
| `gate_red` | a task reached merge with a red test gate |
| `test_findings` | the findings consult judged final verification's findings blocking |
| `verification_limit` | three verification rounds spent with findings still open |
| `consult_bail` | any consult chose `bail` |
| `timeout` | the gate or an agent session exceeded its limit |
| `protocol_failure` | a git command failed, an agent left uncommitted changes, a `task.json` was missing or named an unknown project, a consult chose an unoffered action, the worktree was dirty at merge, or preflight found no `slice.md` / no task folders / the wrong branch |

Exit codes: **0** slice complete · **3** bailed (`bailout.json` written) · **2** usage or
precondition — including a `state.json` that exists without `--resume`, and a dirty working tree at
preflight, which is a hard gate rather than a bail · **130** interrupted · **1** unexpected error.

## Resume and crash recovery

`task_runner.py run <slice-dir> --resume` continues from `state.json`: merged tasks are skipped,
the in-flight task restarts from its last clean stage, and task folders added since the last run
are picked up automatically because the runner re-scans `tasks/` before every task. Resume skips
preflight entirely, so the clean-tree and base-branch gates are not re-applied — the caller owns
the state it resumes into.

When a run dies mid-agent (host restart, quota stop, Ctrl-C), the `in_flight` record — task, role,
round, verdict path, session id, start time — lets `--resume` **reattach**: the worktree is left
exactly as the crash left it, and the interrupted session is resumed with a recovery prompt
(reassess, finish, commit, write the verdict) instead of a fresh dispatch. A reattached round keeps
the round number its interrupted dispatch ran under, so caps do not re-fire and counters do not
double-advance.

Two things are deliberately never reattached: **consults**, which are cheap and whose action
vocabulary may have changed, and **timed-out sessions**, whose `in_flight` record is cleared before
the bail — a stuck agent is a problem to surface, not to continue.
