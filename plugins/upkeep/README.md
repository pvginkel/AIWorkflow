# `upkeep` — planned second plugin (migration backlog)

**Not built yet.** This directory parks the codebase-maintenance capability that feeds
`/dev:triage`, retained in-repo as backlog so the retained files have a destination. `upkeep` is
**not** listed in `../../.claude-plugin/marketplace.json` and has no `plugin.json` — it is not
installable. `dev` ships first and stands alone.

## What lands here when it's built

- **`commands/update-docs.md`** — the validated documentation-model pass, copied from KubeCoder's
  `.claude/commands/`. Per the plan it becomes a **skill** (not a command) when `upkeep` is built
  (§9 decision 2); it is parked here in its command form as the migration source.
- **`docs/documentation-model.md`** — the reference doc it uses.

## What is *not* here: the quality capability

`quality-improver`, `quality-issue-finder`, `refactor-audit`, and the `code_health` grader moved to
[`../../archive/quality/`](../../archive/quality/) on 2026-07-16. They come back as `upkeep` skills
once `code_health` is rebuilt as a proper tool; until then they are archived rather than parked,
because `/dev:onboard` is actively sweeping the projects' copies out and they need one destination.
See that archive's README for the rebuild's starting points.

## The blocker is narrower than it looks

`code_health` is the load-bearing backlog item, and **only `refactor-audit` consumes it** — it is
the sole caller of `uv run python -m tools.code_health --json`. `quality-improver` and
`quality-issue-finder` never reference it, and `update-docs` has nothing to do with it.

This README previously said the quality-* capabilities were the consumers, which made all four look
blocked on one rewrite. Only one is. `update-docs` is unblocked today — it needs a `plugin.json`, a
marketplace entry, the command→skill move, and its KubeCoder-isms stripped; nothing more.

See `../../plugin-plan.md` §7a for the original scope (written before the correction above — it
carries the same misattribution).
