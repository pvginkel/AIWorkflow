# Archived: the quality capability and the code-health tool

**Parked, not shipped, not installable.** This is where the pre-plugin quality capability —
`quality-improver`, `quality-issue-finder`, `refactor-audit`, and the `code_health` grader they
feed on — waits while the tool is rebuilt. Nothing here is wired to anything. `/dev:onboard`
sweeps a project's copies in here and then deletes them from that project, so the capability
lives in exactly one place until it comes back properly.

**Why archived rather than migrated into a plugin.** The tool needs a rewrite before the next
quality pass — its current shape gave real value but is not something to build a plugin on. Shipping
the skills without it would ship three capabilities pointing at a tool that is about to change
underneath them, and leaving the copies in the projects means every project keeps a private fork of
a tool that is being replaced. So: out of the projects now, into a plugin when the tool is worth
one.

**What comes back, and how.** A rebuilt `code_health` as a proper tool, then these three as
`upkeep` skills alongside `update-docs` (see [`../../plugins/upkeep/README.md`](../../plugins/upkeep/README.md),
which holds the part that is *not* blocked). Read this archive then, not to restore it verbatim, but
because four projects each solved things here that a rewrite should know about.

## Layout — one folder per source, because the copies disagree

Per-project, deliberately. There is no canonical version to crown: these were copied between repos
for a year and drifted apart, and the divergence is the most useful thing in the archive — it is
four independent answers to the same problem. Measured 2026-07-16, against the copy this repo had
parked:

| Source | `quality-improver` | `quality-issue-finder` | `refactor-audit` | `code_health` |
|---|---|---|---|---|
| `KubeCoder/` | identical | identical | identical | 10 source files; 8 differ from aiworkflow's |
| `IoTSupport/` | differs, 20 lines | differs, 32 lines | differs, 18 lines | 15 source files; 1 differs |
| `DesignAssistant/` | differs, 44 lines | differs, 42 lines | differs, 47 lines | 15 source files; 2 differ |
| `Ansible/` | — | — | — | — (has `update-docs` only, which stays put) |

- **`aiworkflow/`** — this repo's own resident copy: `code_health` in its fullest form (15 source
  files, incl. the `cognitive/` TypeScript sidecar). The closest thing to an original, and the
  natural starting point for the rebuild.
- **`KubeCoder/`** — the three commands, byte-identical to KubeCoder's `.claude/commands/` (they were
  parked in `plugins/upkeep/commands/` as the migration source; provenance is what matters here, so
  they sit under the project they came from). KubeCoder's `code_health` is the odd one out — a
  trimmed 10-file variant — and lands here when KubeCoder is onboarded.
- **`<project>/`** — added by `/dev:onboard` as each project is swept.

`refactor-audit` travels with the tool: it is the **only** consumer of `code_health` (`uv run python
-m tools.code_health --json`, plus pointers into `config.py` and `cognitive_analyzer.py`). The
other two never reference it. That correction matters — the old `upkeep` README claimed the
quality-* capabilities were the consumers, which made the whole capability look blocked when only
`refactor-audit` ever was.

`update-docs` is **not** here: it is not quality, touches no `code_health`, and nothing blocks it.
It stays in the projects that have it and is parked for `upkeep` in
[`../../plugins/upkeep/`](../../plugins/upkeep/).
