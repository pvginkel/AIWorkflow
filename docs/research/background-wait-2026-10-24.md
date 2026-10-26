---
issue: AIWF-102
status: ruled 2026-10-26 — "let's start with the added line"; the managed-CLAUDE.md line not taken yet
---

# How a run-loop role waits on a backgrounded command — proposal

**Recommendation.** Add one line, written once as a driver constant, to the first prompt of every
role either loop dispatches. It says the role runs as its own headless session, not as a
sub-agent: a command it backgrounds re-invokes it when the command exits, so it waits by ending
its turn, never by polling or a waiter it builds. It also says to run a gate in the foreground
under `timeout(1)` when the gate fits the Bash tool's 10-minute cap, and to background only what
can outrun that cap.

## Why the role could not tell

The managed CLAUDE.md gives two rules. A session waits on backgrounded work by ending its turn.
A *sub-agent* waits in the foreground, because its ended turn is its report. A run-loop role
matches both descriptions: the driver "dispatches" it and its definition says "Spawned by the
run loop". So a code-writer that backgrounded a 4-minute gate (PilotApp, 2026-10-23) could not
tell which rule was its own, and it hand-built a waiter.

The facts are in the plugin already:

- Every role is a top-level headless session (`kc session create-headless --agent <role>`). `kc
  session send` resolves only on the terminal result, so a turn that ends with background work
  in flight is a wait, not a hand-back (`plugins/dev/docs/agent-dispatch.md` § Delegate, then
  yield).
- A headless session is re-invoked when a backgrounded command completes. Every one of 71
  corpus cases was resumed (0.9.16's reversal, `docs/rationale/improvements.md`).
- Ending the turn has one race, the engine's (KubeCoder #840): a completion that lands mid-turn
  can die with the process. The driver recovers from it (`LOST_WAIT_PROMPT`), at the cost of a
  recovery turn. A foreground run has no such race, so foreground is the better default
  wherever it fits.

## The line

> You run as a headless session of your own, not as a sub-agent: a command you background
> re-invokes you when it exits. Run a gate in the foreground under `timeout(1)` when it fits the
> Bash tool's 10-minute cap. Background only what can outrun it, and then wait by ending your
> turn, with a reply and no tool call. Never poll it, and never build a waiter.

It goes into `run_kc_session`'s first prompt for every role: one constant, imported by
`plan_loop.py`, and nothing added to the eleven agent definitions. It does not restate the
managed file, which the 0.9.33 ruling keeps out of plugin prose. It tells the role which of the
file's two rules applies to it, a fact the managed file cannot know.

## The other ways

- **Fix it in KubeCoder's managed CLAUDE.md**: "a session `kc session create-headless` started
  is not a sub-agent, whoever started it". That fixes every script-driven session in the fleet
  (the card pass, Pilot's sessions), not only this plugin's. It is a KubeCoder change: a KC
  card, rolled out with the managed file. It can go beside the line, not instead of it, if
  you want both.
- **Always foreground under `timeout(1)`.** That fails for a suite past 10 minutes, which the
  Bash tool backgrounds at its cap anyway, so the role still needs the rule for that case.

Cost of the recommendation: one constant, one test pinning it in every dispatch, and a changelog
line.
