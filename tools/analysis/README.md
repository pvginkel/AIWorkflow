# Analysis tools

Read-only research tooling over Claude Code transcripts (`~/.claude/projects/`) and the
task-runner's slice artifacts. Nothing here mutates a repo or a transcript.

## The one accounting rule

Stream-json transcripts log one line per *content block*, repeating the same `message.id` with an
identical `usage` payload — naive summation overcounts tokens ~2–3×. Every tool here dedups by
`message.id` before summing. A session's sub-agents live in separate files next to its transcript
(`<session-id>/subagents/agent-*.jsonl`) and are counted as sidechain usage.

## Tools

- **`slice_costs.py`** — fleet-wide ranking: attributes *every* conversation (manager sessions +
  sub-agents) to a slice and ranks slices by tokens/$/wall-clock. Written against the pre-#175
  orchestrator model but the attribution is text-based (`slice NNN` mentions), so it still catches
  runner-era sessions. Start here for "where does the money go across slices".

- **`runner_sessions.py`** — per-slice drill-down for task-runner (#175) slices: reads the slice's
  `state.json` and prints one row per agent session (task, role, round, outcome, transcript path;
  `--tokens` adds deduplicated usage + sticker cost, counting a resumed session's transcript once).
  The transcript paths are what you hand to a research sub-agent — newer runs record them in
  `state.json` directly; for older runs the tool globs the session id across
  `~/.claude/projects/*/`.

Price tables carry public sticker prices per model and the standard cache multipliers (write 1.25×
input, read 0.10×); update them when models change.

## Conventions

New analysis tooling goes in this folder, self-contained (stdlib only), with a `--json` mode when
another tool might build on it. Keep outputs compact — these tools get run inside sessions, where
a dumped table is context spend.
