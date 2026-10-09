# The run loop's run record — state, bail-outs, and resume

What `${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py` writes down, and how a run picks up where it
stopped. This is what a `/dev:run-slice` session reads to decide anything: the driver's stream never
reaches it, so the exit code, `state.json`, and `bailout.json` are the whole interface. The loop
those files record is [run-loop.md](run-loop.md).

## state.json

Written atomically by the driver and by nothing else while the run lives; the one post-run
exception is the `cost` block `slice_cost.py --write-state` appends at close-out — the derived
spend ratios (planner, research-subagent, completion-consult and rework shares, with any pricing
warnings) and a `turns` sub-block (per role: sessions, turns, tools and reads per turn,
orientation turns, context, retry/fumble and batchable turns, prefix breaks; slice-wide: cost per
turn and the avoidable share), so the committed run record both prices itself and says what its
turns did.
Slice level:

`slice`, `created_at`, `updated_at`, `plugin_version` (the plugin the run was created under, from
its manifest — what lets runs be read before/after a plugin change; a resume does not rewrite
it), `orchestrator` (the launching session's id and transcript
path, or `null` for a hand-run), `run_phase` (`phases` | `consult` | `test` | `docs` | `done` —
the stage the run is in; a bail leaves it at the stage it stopped in, which is what `--resume`
re-enters, and records the stop in `bailouts` and `bailout.json`), `bases` (base branch per
target repo — the branch the run found there, never a
`phase/…` one; a bail checks each back out from the run's own branch), `known_phases` (the
plan's phase ids in document
order, as last parsed), `generation` (follow-up generations spent), `test_rounds`, `sweep_runs`,
`gate_sweep` (the loop-tail sweep's record: per-command `results` with log paths and an
`outcome` — `green`, `red` or `nothing_ran` (kc's exit 3), with `green` kept beside it — the
sweep's own `outcome` (red on any red row, else green on any green row, else `nothing_ran`) and
`green`, and the exact `commits` it ran on — reused while every swept HEAD matches, re-run
otherwise),
`consult_seq`, `in_flight`, `exit` (how the run ended — its exit `code` and `ts`, the driver's last
write, after `bailout.json`; cleared when a `--resume` starts, so a run that is not running and
has none was killed from outside), `bailouts` (every stop this run made — `reason`, `phase`,
`question`, `ts`, the `run_phase` it stopped in and its `details` clipped to 600 characters —
kept here because `bailout.json` is unlinked on resume; the resume that follows a stop writes it
into the close-out report as an event and marks the row `reported`, so each stop is entered
once however often the run resumes), `appended_phases`
(the ids the plan gained after the run started — a consult's, the test phase's, or the
operator's, as opposed to the phases it began with), `holds_reported` (the repos held by the
plan's `## Push holds` section that the driver has already entered in the close-out report — one
entry per repo per run), `wrap_up` (the wrap-up's record: `outcome` — `skipped` when nothing
waited for it, `landed`, or `left_out` with its `reason`; its `session`; the `entries` its work
list named at dispatch; `store`, the spec repo commit the store stood at before it; and per
repo its `branch`, the `base` sha the branch was cut from and its `head`), `doc_phase` (the
closing ladder's record: its `stage` — `writer` | `wrap-up` | `gate` | `landing` | `siblings` |
`done` — the writer's `session`, `gate_runs`, `nudges`; `writer: false` in a project that runs
no doc phase, where the ladder starts at the wrap-up; `gate_last`, the doc gate's run the
wrap-up stage made, which the gate stage takes instead of running the sweep again on the same
commit; and `sibling_heads`, each other code repo's base sha as the ladder began, which tells the
`siblings` stage whether a base that diverged from its origin carries only the run's own commits
and may be rebased), `phases`, and `history`.

Per phase: `status` (`pending` | `in_progress` | `merged`), `stage` (`executor` | `gate` |
`review` | `merging` | `null`), `branch`, `target`, `executor_rounds`, `gate_fix_rounds`,
`review_rounds`, `reviewed_head`, `gate_runs`, the gate's evidence pair `gate_green_commit` /
`gate_green_log`, `gate_nothing_ran_commit` (the head the gate last ran nothing on — the
reviewer is told the target defines no tests only when it is the commit under review),
`gate_cmd` (the command whose outcome stands — bare `kc project test` when a root phase's
`--project root` ran nothing; what the reviewer's gate line and a fix round's prompt name),
`rebase_requested` (set when a merge-time rebase bails `blocked` and hands the
rebase to the operator — `base`, `from` (the branch head it asked to rebase), `ts`; cleared when
the resume takes the rebased branch, and at the merge), and `landed` — set at the ff-merge: the
phase's `root`, the `base` sha its branch was cut from and the `head` that fast-forwarded the
base branch. That range is the phase's
own commits and nothing else, which is what the executor digest's touched list and the doc
phase's diff files read; a phase whose merge landed before its record did (the reconcile path)
has none, and the doc dispatch names it as missing from the files.

`history` is append-only, one entry per agent run plus one per gate run (role `gate`), one per
loop-tail sweep (role `sweep`), one per doc gate (role `doc-gate`), one per gate on a wrap-up
branch outside the primary repo (role `wrap-up-gate`) and one per consult: `ts`,
`phase`, `role`, `round`, `outcome`, `summary`, `session`, `transcript`, `duration_s` (a gate,
sweep or doc-gate row's outcome is `green`, `red` or `nothing_ran`; a `wrap-up-gate` row names
its `repo`). A wrap-up row carries the id lists of its verdict. A
code-reviewer row additionally carries the verdict's `findings` list (id, severity, impact,
category, anchor per finding — the review contract's telemetry) and a review-fix executor row
its `refuted` list, exactly as the agent reported them. The
**transcript path** points at that session's conversation JSONL under
`~/.claude/projects/`, with its own sub-agents beside it under `<session-id>/subagents/`, so any
later session can research exactly what an agent saw and did. That is why `/dev:run-slice` commits
`state.json` and `log.txt` with the slice artifacts at close-out: together they are the run's
complete who-did-what record.

**Every timestamp both loops write or print** — the `ts` fields here, the `[HH:MM:SS]` prefixes in
`log.txt` and on the stdout announce lines, the dates stamped into `plan.md` — is the **operator's
local wall clock**, taken from the process's `TZ` (UTC when unset). The ISO stamps stay
offset-aware, so they remain unambiguous to anything that parses them back.

**`close-out.json`** and the **`close-out.md`** rendered from it sit beside `state.json` and are
not the driver's: created by the loops, written by every agent through `close_out.py`, which
renders the report at every write, and rendered by the driver at its stages — the header of the
rendered report is read off this state (`created_at` → `updated_at`, `known_phases` against
`appended_phases`, `bailouts`, `test_rounds`, `doc_phase.stage`, and `cost` once
`slice_cost.py --write-state` has run), and so is which repositories the slice touched: the
`root` of every phase. What goes in the report is [close-out.md](close-out.md).

Session outputs live under `<slice>/phases/P<id>/` (review docs, gate logs, verdict files) and at
the slice root for the consult/test/doc stages and the wrap-up (`wrap_up_result.json`,
`wrap_up_gate_r<N>.log`); the run-start `kc project setup` logs under `<slice>/setup/` (one
`<repo>.log` per Target repo, rewritten at every start); the loop-tail sweep's logs live under
`<slice>/sweeps/r<N>/`; the doc phase's diff files under `<slice>/doc_phase/` (one `<repo>.diff`
per repo a phase merged into, a section per merged phase over its `landed` range, rewritten at
every doc-writer dispatch — git's answer written down, not an agent's copy). Executor inputs
come from `plan.md`, never from copies.

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
| `prerun_action` | ✓ | at startup, fresh or `--resume`, the slice's close-out report holds a live `Before /dev:run-slice` action ([run-loop.md](run-loop.md) § Protocol invariants) |
| `missing_tools` | ✓ | a Target repo's manifest calls a `cexec <tool>` this environment does not run — at startup, fresh or `--resume`, or at a phase gate that meets it mid-run; the details name the tools and the `- use:` lines ([run-loop.md](run-loop.md) § Protocol invariants) |
| `missing_services` | ✓ | a Target repo's `.kubecoder/config.yaml` declares a service this environment does not run — at startup, fresh or `--resume`, or at a phase gate that goes red in that repo mid-run; the details name the services and the `services:` lines ([run-loop.md](run-loop.md) § Protocol invariants) |
| `blocked` | – | an agent reported `blocked`, or a protocol failure after the nudge |
| `gate_red` | – | the gate stayed red through the executor fix cap, or at merge |
| `consult_bail` | – | any consult chose `bail` |
| `devlock_timeout` | – | the dev occupancy lease stayed held past the wait cap |
| `spec_tree_timeout` | – | the shared spec tree's lease stayed held past the wait cap — a parallel run's spec-repo phase, or the sessions in flight such a phase waits for ([run-loop.md](run-loop.md) § The plan is the queue) |
| `timeout` | – | a driver-run gate or sweep command exceeded its limit, or an agent session did with no usable verdict on disk |
| `unpushed` | – | a repo the slice touched was still behind `origin/<base>` after the test phase and its push nudges |
| `plugin_version` | – | the installed plugin's version differs from the loop's own, at startup or before a dispatch; the details name the installed `tools/` path to relaunch from ([run-loop.md](run-loop.md) § Protocol invariants) |
| `protocol_failure` | – | a git command failed, an agent left uncommitted changes, a consult chose an unoffered action, the worktree was dirty at merge, an agent committed the driver's run record onto the phase branch, a `CLAUDE.md` procedure-doc pointer is missing, or a `verification.json` item carries a key outside the schema |
| `lost_work` | – | a commit the driver recorded on a phase branch is not on it any more (and the driver did not ask for the rebase that rewrote it), or a `pending` phase's branch carries commits the run has no record of |

Exit codes: **0** slice complete · **3** error bail · **4** operator question · **2** usage or
precondition — a `state.json` that exists without `--resume`, a slice another driver is already
running (`run.lock` held), a missing/unparseable `plan.md` or missing `verification.json`, a dirty
tree at preflight, or a missing agent definition · **130** interrupted · **1** unexpected error.

**Detached.** `run … --detach`, what `/dev:run-slice` launches, puts the driver in a session of
its own, off any terminal, so no caller's cap on one command can kill it — the harness's
background cap is 2 h, and on 2026-09-30 it killed three runs mid-flight. It returns once the
driver holds `run.lock`, or with the driver's own refusal and exit 2; the run is unchanged, its
exit code on disk as `exit`. `run_loop.py wait <slice-dir> [--for S] [--from OFFSET]` waits on
it, 3 300 s by default, and answers **0** the run ended (its code, and for a bail the reason,
question and details), **5** still running (the stage, the session in flight against its role's
cap, the age of the last log line) or **6** gone with no `exit` recorded — each time with the
driver's own `log.txt` lines since `--from`, the in-flight session's latest narration, and the
command to run next. Liveness is the `flock`, never the pid. `run_loop.py stop <slice-dir>`
sends the driver SIGINT: the 130 path, as Ctrl-C.

## Resume and crash recovery

`run_loop.py run <slice-dir> --resume` continues from `state.json`: stamped phases are skipped
(the plan is re-parsed, so phases appended since the bail are picked up), the in-flight phase
restarts from its last clean stage, and a bail from the test or doc stage re-enters that stage
rather than replaying the consult→test ladder — read off `run_phase`, which the bail leaves
where it was (before 0.9.28 it overwrote it, and slice 209 paid a second full test phase for
that). Resume skips preflight entirely — the caller owns the state it resumes into.

When a run dies mid-agent (host restart, quota stop, Ctrl-C), the `in_flight` record — phase,
role, round, verdict path, session id, start time — lets `--resume` **reattach**: the worktree is
left exactly as the crash left it, and the interrupted session is resumed with a recovery prompt
instead of a fresh dispatch — one that says the interruption came from outside and is no outcome
of its own: Ansible 034's doc-writer, reattached after a kill, read its cut transcript as one and
handed back `blocked` within 18 seconds. The session id is in the record from the turn's first seconds: the
driver polls `kc session status` while the send runs rather than reading it after, because a
send that hangs once the turn has ended never returns (slice 222's test agent) —
the same read logs the id and the transcript path. A reattached round keeps the round number its
interrupted dispatch ran under — executor, gate-fix, review and test rounds alike — so caps do
not re-fire, counters do not double-advance, and the verdict path the resume computes is the one
the record names. The resume reads that file before it dispatches anything: a valid verdict
there was written by the interrupted round (every dispatch unlinks the file first), so the round
is complete — counted from the file under the record's session id, with no duration on its row
and no session resumed or spawned. Slice 222 spent a second full test phase on a `clean` verdict
already on disk.

Two things are deliberately never reattached: **consults**, which are cheap and whose action
vocabulary may have changed, and **timed-out sessions**, whose `in_flight` record is cleared as
soon as the timeout fires — a stuck agent is a problem to surface, not to continue.

A timeout reads the verdict file before it bails, though. Every dispatch unlinks that file first,
so one present when the timeout fires was written by this round: the agent finished its work,
committed it, and the turn wedged afterwards. The driver takes that verdict and counts the round
normally rather than discarding work already on disk — and because the verdict is the last step of
every role's protocol, a salvaged round is a complete one. The bail fires only when the verdict is
missing or unparseable. A session that ends with a non-zero exit — its send killed, the worker
interrupted — is read the same way: a valid verdict on disk counts whatever the exit code, and
only an invalid or missing one is the protocol failure. The commit nudge reads it the same way:
a round the driver had ruled `blocked` for a missing verdict is repaired — the history row and
the outcome the loop acts on — when the nudge that cleaned the tree also left a valid verdict
behind. The devlock is in-process (`flock`), so a crash releases it by construction.

**One driver per slice folder.** The run holds a `flock` on `<slice>/run.lock` from start to exit,
and a second driver on the same folder exits 2 with the holder's host, pid and start time rather
than joining in. The folder is on the spec repo — the mount every environment shares — while the
code repo each driver branches is its own: two drivers therefore write one `log.txt`, one
`state.json` and one `phases/**` while working two different checkouts, and the second finds no
phase branch where the record says work is committed. Held in-process, so a driver that dies
releases it and a `--resume` walks straight in. A clean exit empties the holder note, so a note
on a free lock is a driver that died: the `--resume` that takes the lock logs it as killed from
outside before writing its own.

**A phase's branch is reconciled against its record** before the driver resets or recreates it, and
again after every executor round. Every commit the driver recorded on that branch — the head the
last review read (`reviewed_head`), the gate's last green (`gate_green_commit`) — must still be on
it. Where one is not, the base branch decides: carrying it means the ff-merge landed and the run
died before the record caught up, so the resume stamps the phase and moves on; carrying it nowhere
means the work is gone, and the run bails `lost_work` rather than rebuilding the branch from base
and spending a round redoing a commit it cannot account for. A `pending` phase whose branch exists
with commits the base has not got bails the same way — the `git branch -D` that would otherwise
clear the name takes them with it. Rounds spent before the first gate or review are the one gap:
they leave no commit on the record to check. A base that moved under the branch by merge time is
the one case the driver rewrites the record itself: the branch is rebased onto it, the phase's
diff proven identical before and after, `reviewed_head` repointed at the rebased commit and the
gate's green cleared so it re-runs. When that rebase does not apply cleanly, or changes the
phase's diff, the driver bails `blocked` and hands the rebase to the operator, marking the phase
`rebase_requested`. A hand rebase leaves both recorded commits on neither branch nor base, the
`lost_work` shape, so the mark is what tells the resume the rewrite was asked for: a branch that
now carries the base's tip gets the same repointing (the review stands, the gate re-runs), and a
branch that does not yet carry it bails `blocked` again with the same request. Without the mark,
a rewritten branch is still `lost_work`.
