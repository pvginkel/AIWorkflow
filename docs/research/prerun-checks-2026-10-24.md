---
issue: AIWF-88
status: proposal, unruled
---

# Pre-run actions with checkable done-conditions — design for review

**Recommendation.** A `Before /dev:run-slice:` action carries one or more **checks**: facts about
the tree or the environment, in a small fixed vocabulary that `close_out.py append --check`
validates and stores on the entry. `preflight --for run --slice` and the run loop's startup
evaluate them with one shared function. When every check holds, the driver strikes the action
itself and the run goes on. When one fails, the run bails `prerun_action` naming the failed
check, and that also happens for an action someone has already struck. A check that names a
commit hash or an environment id is refused when it is appended. Five decisions are below, each
with the recommended option first.

## What went wrong

The run loop's only test today is whether the action entry is still live (`open_prerun_actions`).
A strike from whoever believed the action done lets the run start.

- PilotApp slice 007 (2026-10-19), A2: "restart this environment once 45a9ab3 is on the main the
  run starts from". Another entry named the planning environment (`pvginkel-pilotapp-addac6`).
  The commit was unpushed and the environment was the wrong one for any other pod, yet
  preflight exited 0: it does not look at pre-run actions at all.
- PilotApp slice 018 (2026-10-20): 45a9ab3 was rebased to e91fc82 on push. A check keyed on the
  hash would have failed even though the work was done.

The fact these actions wait on is never the hash. It is a key in `.kubecoder/config.yaml` on
origin's main, an environment variable this pod has after a restart, or a slice that has
completed.

## The checks

One line each. Every check is deterministic and stdlib-only, and none runs a command it was
handed:

| check | holds when |
|---|---|
| `env <NAME>` | the variable is set and non-empty in the driver's environment, the pod that runs the slice |
| `file <repo>:<path>` | the path exists in that repo's working tree; `<repo>` as a `Target:` names a sibling (`../PilotApp`) |
| `origin <repo> <branch>:<path> contains <text>` | after a fetch, `git show origin/<branch>:<path>` holds the text |
| `slice <NNN> completed` | a `NNN_*` folder is under `slices/completed/` |

Slice 007's A2 becomes `origin ../PilotApp main:.kubecoder/config.yaml contains PILOT_DEV_CONTROLLER_TOKEN`
plus `env PILOT_DEV_CONTROLLER_TOKEN`. A1, "deliver slices 003, 004 and 007 first", becomes three
`slice … completed` checks.

## Decisions

- **D1 — where the checks live.** *Recommended:* on the action entry in `close-out.json`
  (`append --check`, repeatable), rendered under the entry as `Done when:` lines. The entry is
  already what the operator reads and what the run loop reads. *Other:* a `## Pre-run conditions`
  section in `plan.md`. It is nearer the plan but a second place to keep in step with the entry.
- **D2 — the vocabulary.** *Recommended:* the four checks above, and no general `cmd <argv>`. An
  arbitrary command makes a check as unreliable as whatever it runs, and preflight would run
  session-written commands. *Other:* add `cmd` for the cases the four do not cover.
- **D3 — when every check holds.** *Recommended:* the driver strikes the action itself (reason:
  the checks, by "the driver") and runs. Nobody has to come back to strike what the tree already
  shows. *Other:* bail as today, and let the operator or the run-slice session strike it.
- **D4 — a struck action whose check fails.** *Recommended:* bail `prerun_action` at start and at
  `--resume`, naming the check and saying the strike did not make it true. This catches slice
  007. The check is not re-run after the first dispatch.
- **D5 — an action that cannot be checked** (a person's approval, a manual step outside any
  tree). *Recommended:* `append --check manual` states it explicitly, and the entry keeps today's
  strike-by-hand. A `Before /dev:run-slice:` action without any `--check` is refused, so the
  plan-writer has to decide. *Other:* `--check` stays optional.

The appending refusals follow from the card: a check holding a 7–40 character hex word (a commit)
or this host's environment-id shape (`<owner>-<repo>-<6 hex>`) is refused with the reason. The
plan-writer's brief and `plan-template.md` get the vocabulary and the rule "a fact, never a
commit or an environment".

## What it costs

- `close_out.py`: a `checks` field, `append --check` with its validation, and the `Done when:`
  render.
- A small `prerun_checks.py`, or a function in `preflight.py`, that both callers import:
  evaluate, report, and a driver strike.
- Run loop: `assert_no_prerun_actions` evaluates instead of only counting.
- Prose: plan-writer, plan-template, run-loop.md, preflight.md, run-slice (whose `prerun_action`
  paragraph changes).

That is one version, about the size of AIWF-83's `settle`.
