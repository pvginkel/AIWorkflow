---
issue: AIWF-29
---

# Running `run_loop.py` past the harness's 2 h background cap — the plan

`/dev:run-slice` launches the loop with the Bash tool's `run_in_background`, whose cap is
7 200 000 ms at most, whatever `timeout` the session passes (the skill passes none). At the cap
the harness kills the command — "stopped after reaching its background time limit" — and
re-invokes the session. Three slices met it on 2026-09-30: Ansible 034 (11 phases) mid doc
phase, KubeCoder 237 (5 phases) ten seconds into its test phase after 28 minutes on the
devlock, and Ansible 035. The operator's direction: run the loop detached, wait on it an hour
at a time, and have the session check quickly that everything is still OK each time it wakes.
This is the fleshed-out form of that, with the two things the card asked to cover beside it.

## 1. Two limits, not one

- **The harness's cap** bounds one Bash command: 2 h, hard. It kills the driver process, not
  the kc session the driver was waiting on — that session carries on in kc and finishes on its
  own; the driver that would have read its verdict is gone.
- **The plugin's own caps** bound one session or one wait, never the run: `TIMEOUTS` gives the
  code-writer, the doc-writer and the wrap-up 7 200 s each and the other roles less;
  `GATE_TIMEOUT` 3 600 s; `NUDGE_TIMEOUT` 900 s; the spec-tree lease and the devlock wait up to
  4 h. These exist so a stuck agent surfaces as a bail instead of an indefinite wait, and none of
  them is the 2 h the operator remembered — that memory is the per-session 7 200 s.

A run is the sum: N phases × (writer, gate, review, fix rounds) + consults + the test phase +
the doc phase + the wrap-up, plus every wait on a lock. Five phases behind a busy devlock is
enough.

## 2. What the kill costs today

- No `bailout.json`, no exit code: the session learns of the kill from the harness's message
  and reads `state.json` to guess where the run was.
- `run.lock` keeps the dead driver's note (`host`, `pid`, `started`). The lock itself is an
  `flock`, released by the kernel with the process — a dead holder never blocks `--resume`;
  only the note misleads, and the sessions that met it spent a `kill -0` on the pid to be sure.
- The in-flight session's work is at risk at the resume. `--resume` reattaches to it by session
  id with `REATTACH_PROMPT` and nudges. The doc-writer reattached after Ansible 034's kill read
  "the session ended" as its own outcome and wrote `doc_phase_result.json` `blocked` within
  18 seconds ("The session ended mid-survey: no doc edit was made"); the loop bailed `blocked`,
  the second `--resume` started a fresh doc session, and ~10 minutes of survey were lost with
  one extra bail/resume round.
- The hand workaround (`setsid nohup … &`, the pid from `ps` because `$!` is setsid's, a
  `timeout 7000 sh -c 'while kill -0 PID; do sleep 30; done'` waiter re-armed at its cap, the
  outcome read from `bailout.json` because the exit code is lost) is what this plan builds in.

## 3. The options

| | option | why not |
|---|---|---|
| A | **the loop runs detached; the session waits on it an hour at a time** — below | — |
| B | the loop checkpoints itself and exits resumably before the cap | a phase session in flight cannot be checkpointed without a reattach; every 2 h adds a reattach's risk to the run; the kill would still come for a wait that outran the window |
| C | document the cap; `--resume` after each kill | one lost doc phase and a reattach every 2 h of run; what happened three times on one day |
| D | drive the loop from a kc headless session or a timer | a second orchestrator above the one `/dev:run-slice` already is; the exit code and the questions still have to reach the operator's session |

## 4. The design — option A

### 4.1 `run_loop.py run <slice> [--resume] --detach`

The driver detaches itself (double fork, `setsid`, stdin/stdout/stderr on `/dev/null`) and the
parent exits 0 once the child holds `run.lock`, printing the child's pid — or exits with the
child's refusal where the lock is held or the preconditions fail (exit 2, as today, with the
same message). Nothing else about the run changes: the same `state.json`, `bailout.json`, log
and exit codes. The stdout progress feed (`announce`) is lost with the terminal; it was a
window the session never acted on, and `log.txt` holds every line of it.

At the end, whatever the exit, the loop records how it ended in `state.json` — `exit: {code,
ts}` — written last, after `bailout.json`, and cleared when the next `--resume` starts. The
exit code is the interface the launching session reads (run-loop.md), and detached it has to
be on disk. A process killed from outside leaves no `exit`: that absence is itself the signal.

### 4.2 `run_loop.py wait <slice> [--for SECONDS]`

Blocks until the run ends or `SECONDS` pass (default 3 500 — under a 3 600 000 ms harness
timeout, so it exits by itself rather than being killed), then exits:

- **0 — the run ended**: prints the exit code and, for 3 and 4, the bail's reason and details
  from `bailout.json`. The session goes to Job 2, 3 or 4 by the code, as now.
- **5 — still running**: prints one status line — the phase, stage and round in flight, the
  role and age of the session in flight, the age of the last log line — and the session re-arms.
- **6 — not running, no `exit` recorded**: the driver was killed from outside (a host restart,
  a quota stop, a kill). Prints the dead driver's note from `run.lock`. The session relaunches
  `--resume --detach`.

Liveness is the `flock`, not the pid: `wait` tries `run.lock` non-blocking and lets it go — a
driver that holds it is alive, one that does not is not, and no pid is reused under it.

### 4.3 The quick check

The status line is the check. The loop already bounds every session and every wait with a cap
that turns a hang into a bail, so "still OK" means: alive, and either a session is in flight
within its role's cap or the log moved within the hour. The one thing the session looks into is
a log silent for over an hour with nothing in flight — a driver wedged in a call its caps do
not cover (slice 222's hung send was one, since handled by polling). Then, and only then, it
reads the tail of `log.txt`; otherwise it re-arms without reading anything.

### 4.4 `run_loop.py stop <slice>`

Sends the detached driver SIGINT — its `KeyboardInterrupt` path: lease released, state
current, exit 130, the in-flight session left for the resume to reattach. Without it the
operator's only handle on a detached loop is `kill <pid>` with the pid from `run.lock`.
`TaskStop` on the `wait` command stops the wait, not the loop; the skill says so.

### 4.5 The dead-pid `run.lock`

Nothing to clear: the lock is the kernel's, the file is a note. `wait`'s exit 6 is the
replacement for the `kill -0` ritual, and the resume logs what it found — "the previous driver
(pid N, started T) left no exit record: killed from outside" — before it overwrites the note.
That line is the run's own record of the kill, where the harness's message was the session's.

### 4.6 The resume nudge after a kill

`REATTACH_PROMPT` today: "Your session was interrupted mid-run (the driver process died — host
restart, quota stop, or similar). The working tree is exactly as you left it. Reassess …,
finish your work, commit it, then write your verdict." The doc-writer read its own transcript's
cut as the outcome regardless. The prompt says it outright: the interruption was from outside
and is not an outcome — `blocked` is for what the role cannot do, never for having been
stopped; the survey or the edits already in the transcript stand, carry on from them. One
sentence, every reattached role.

Not in this plan: a driver-side guard that treats a `blocked` verdict within minutes of a
reattach as a restart. With the loop detached the reattach returns to being what it was built
for — a host restart, a quota stop — and the prompt is tried first; the guard is a second step
if the pattern comes back.

### 4.7 The skill

Job 1 launches `run … --detach` (no `run_in_background`), then `wait <slice>` with
`run_in_background: true` and `timeout: 3600000`. Each wake: exit 0 → Jobs 2–4; exit 5 → the
check of § 4.3, then `wait` again; exit 6 → `run … --resume --detach`, then `wait`. The relaunch
after a bail (Jobs 2 and 3) is `--resume --detach` followed by `wait`. The "do not read or tail
`log.txt`" rule stands, with § 4.3's one exception. A note names `stop`, and that the loop
outlives the session that launched it — closing the session does not stop the slice.

### 4.8 What does not change

The exit codes and their meanings; `state.json` and `bailout.json` as the whole interface;
every cap in § 1; the lease, the devlock, the reattach mechanics; the plan loop, which runs for
minutes and keeps `run_in_background`.

## 5. Costs and risks

- One `wait` turn per hour of run instead of one wake per run — a short turn each, no file
  read in the ordinary case.
- A detached loop survives the session: by design, and the reason `stop` exists. An operator
  who closes a session mid-run and starts another on the same slice meets the `run.lock`
  refusal with the live driver's note — the existing guard, unchanged.
- The harness may still kill `wait` at its own cap if `--for` is set too close; the default
  leaves 100 s of slack, and a killed `wait` costs a re-arm, nothing else.
- Tests: the detach is the one piece the suite cannot run as it is (the fakes replace sessions,
  git and the gate, not the process); it is tested by the parent/child protocol around a fake
  child, the `exit` record and `wait`'s three answers against real files and a real `flock`.

## 6. For the operator to rule

1. **Where the mechanics live** — in `run_loop.py` (`--detach`, `wait`, `stop`; stdlib,
   tested, one documented command each) rather than a shell recipe in the skill (`setsid`,
   `ps`, `$!`, a `timeout … kill -0` loop the agent types). Recommended: the tool.
2. **The cadence** — one hour (`--for 3500` under a 3 600 000 ms timeout), as directed. A longer
   `--for` is not available: the harness's cap is the ceiling and 2 h is what it was built to
   avoid.
3. **Where the exit lands** — `state.json`'s `exit`, cleared at the next resume, rather than a
   new run-record file. Recommended: `state.json`.
4. **What the session checks** — § 4.3: the status line only; `log.txt` opened only for a log
   silent over an hour with nothing in flight.
5. **`stop`** — build it with the rest (small) or leave the operator with `kill`.
6. **The reattach prompt** — the one-sentence change of § 4.6 now; the driver-side guard only
   if the pattern returns.
7. **One build**, one version, skill and docs with it; the first slices run on it are the
   readout — nothing to measure beyond "no kill at 2 h, no lost doc phase".

## 7. Rulings (2026-10-01)

1. **The tool** — agreed.
2. **55 minutes**: `wait --for 3300` by default, under the same 3 600 000 ms harness timeout. The
   session wakes inside the hour its conversation's prompt cache lives, so every check reads a warm
   cache.
3. **`state.json`'s `exit`** — agreed.
4. **A small status update at every check**, replacing § 4.3's "re-arm without reading anything".
   The operator: "the logs are terse … I would actually quite appreciate a small status update
   whenever it checks." Built as: `wait` prints, besides its status line, the driver's own log
   lines written since the previous check — the unindented lines, without the
   `session <id> — transcript <path>` ones, the last 40 at most — and the in-flight session's
   latest `[text]` line; it ends with the next `wait` command, `--from` the log offset it read
   up to, so consecutive checks cover the log without a gap. The session turns that into a few
   lines in chat: what landed since the last check, what is in flight, anything that looks off.
   An hour of driver lines measured about 7 KB (slice 236: 15 KB of driver lines in 2 h beside
   87 KB of agent activity), so the check stays a short turn. § 4.3's one exception stands: a
   log silent for over an hour with nothing in flight is when the session reads `log.txt`'s
   tail.
5. **`stop`: built** (left to me). It is the only handle on a loop that outlives its session
   besides `kill` with a pid read off a file, and it is small.
6. **The reattach prompt now, the guard only if the pattern returns** (left to me), as § 4.6
   proposes.
7. **One build** — not a question: the whole of § 4 ships as one version (0.9.69) with the skill
   and the contract docs, and the first slices run on it are judged on "no kill at 2 h, no lost
   doc phase".
