# `upkeep` — planned second plugin (migration backlog)

**Not built yet.** This directory parks the codebase-maintenance capabilities that feed
`/dev:triage`, retained in-repo as backlog so the retained files have a destination. `upkeep` is
**not** listed in `../../.claude-plugin/marketplace.json` and has no `plugin.json` — it is not
installable. `dev` ships first and stands alone.

## What lands here when it's built

- **`commands/`** — the validated maintenance commands (`update-docs`, `refactor-audit`,
  `quality-improver`, `quality-issue-finder`), copied from KubeCoder's `.claude/commands/`. Per the
  plan these become **skills** (not commands) when `upkeep` is built (§9 decision 2); they are parked
  here in their command form as the migration source.
- **`docs/documentation-model.md`** — the documentation-model reference doc these capabilities use.

## Open backlog item

`tools/code_health/` (in the repo root) gave real value but is messy as a tool. Turning it into a
**proper, shippable tool** is `upkeep`'s load-bearing backlog item — only the quality-* capabilities
consume it. It stays where it is until then.

See `../../plugin-plan.md` §7a for the full scope.
