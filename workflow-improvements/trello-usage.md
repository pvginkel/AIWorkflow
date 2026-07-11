# Trello MCP token usage — findings and fixes

**Purpose.** A usage report flagged the **Trello MCP server at ~7% of all token usage** over 7 days.
This document records what that 7% actually is (measured from local transcripts), what the responses
look like, the fixes applied to the mcp-filter spec, and what still needs an upstream fork. It is a
companion to [`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md) — its thesis (**cost = context size ×
turns**; the expense is re-reading a large long-lived context every turn) is exactly why a fat MCP
response is expensive far beyond its one-time size.

**Status (2026-07-11):** filter-config fixes applied to the working tree of `../HelmCharts` and
`../DockerImages` (mcp-filter unit tests green); **not yet committed/deployed** at time of writing.
The two input-shape asks (#3, #4 below) need an upstream fork and are **not started**.

---

## 1. What the 7% actually is

The usage breakdown counts **input tokens** attributable to the server — i.e. the size of tool
*results* (and call args) that land in context. Two facts make it much larger than it looks per-call:

1. **The payloads are big.** Machine-wide across all local transcripts (`~/.claude/projects/**/*.jsonl`):

   | | calls | ~tokens |
   | --- | --: | --: |
   | **All Trello result payloads** | 2,452 | **~2.38M** |
   | Trello call *args* (agent-written) | 2,452 | ~0.27M |
   | **`get_cards_by_list_id`** (75% of results) | ~470 | **~1.79M** |
   | `add_card_to_list` | 397 | ~168k |
   | `move_card` | 446 | ~147k |
   | `update_card_details` | 309 | ~97k |
   | `get_board_labels` | 86 | ~77k |

2. **Each result is re-read on every later turn.** A result persists in the conversation and is
   re-sent as cached input on every subsequent turn until the session ends. So the 2.38M raw
   footprint is a *floor*; the attributed usage is that footprint × how many turns re-read it. This
   is the same multiplier ORCHESTRATOR-COST.md measured (sessions run ~95–98% `cache_read`). It also
   explains why the report co-flagged *subagent-heavy* and *>150k context*: every subagent that
   touches Trello re-incurs these payloads.

**Not the tool schemas.** Consistent with ORCHESTRATOR-COST.md's retracted schema-bloat claim, MCP
tool definitions load lazily in this harness — the cost is result payloads, not the ~44 `tools/list`
entries.

*Caveats:* token counts are `chars/4` estimates; the sweep covered **all** local transcripts, not the
report's rolling 7-day window. Treat totals as order-of-magnitude; the **shape** (one tool = 75%,
`desc` = the bulk, re-read multiplier) is solid.

## 2. What a response looks like

`get_cards_by_list_id` returns, per card, the **full `desc`** (this operator writes paragraph-long
card bodies) plus — depending on code path — up to ~36–38 raw Trello fields. Measured on the real
captured responses (401 responses / 3,871 cards):

- **`desc` alone = 54% of the payload (~960k tokens).**
- Distribution: mean **3,826 tok/call**, median 2,880, up to **12,361 tokens in one call** (40 cards).

The "fat" shape carries fields the agent never uses: `badges`, `limits`, `checkItemStates`, `cover`,
`dateLastActivity`, `descData`, `idMembersVoted`, `nodeId`, `mirrorSourceId`, `subscribed`, … Most
were already stripped by the mcp-filter `drop_keys` denylist. One correction worth recording:
**`descData` is *not* a duplicate of `desc`** — its value is always `{"emoji": {}}` or `null` (4–13
chars, ~3 tokens/card). It was wrongly singled out as heavy; the real weight is `desc` + the
*collective* drag of many small metadata fields, not any one fat field.

## 3. The mcp-filter boundary (why only some asks are filter-doable)

The mcp-filter (`../DockerImages/mcp-filter`) is a FastMCP proxy that **only rewrites `tools/call`
result JSON** via an `on_call_tool` middleware. It forwards `initialize`, `tools/list`, resources,
and prompts **verbatim**. Therefore:

- Changing a **result** (drop a key, shrink an object) → **filter config**, no code, no redeploy of
  the image (the Trello spec is mounted from a Helm ConfigMap at runtime).
- Adding a **tool** or a **parameter** (changes `tools/list` / input schema) → **impossible in the
  filter**; requires forking the upstream `@delorenj/mcp-server-trello`.

Rules available (see the mcp-filter README): `drop_closed`, `drop_empty`, `drop_keys` (denylist),
`keep_keys` (allowlist, applied at *every* nesting level), `truncate_keys`, `max_depth`, plus a
`mutation` rule that collapses matching tools to an `identity` field set.

## 4. Fixes applied (filter config)

Two changes, mirrored into **both** spec copies (see §6) and covered by unit tests:

### #1 — `get_cards_by_list_id` no longer returns `desc`

```diff
- keep_keys: [id, name, desc, due, idList, idShort, labels, closed, url, idChecklists]
+ keep_keys: [id, name, due, idList, idShort, labels, url, idChecklists]
```

Removes `desc` (**~54% / ~960k tokens** of that tool's payload) and `closed` (redundant after
`drop_closed`). Rationale: a list view is for triage/navigation — read a card's body with `get_card`.
This is the single biggest lever and is config-only.

### #2 — mutations no longer echo the fat card object

```diff
- identity: [id, name, url, shortUrl, shortLink, idShort, closed]
+ identity: [id, idShort, url]
```

The shared `mutation` rule (`^(add|create|update|delete|remove|move|archive|assign|attach|set|perform)_`)
now collapses every mutation to a 3-field confirmation (~25 tok vs the old ~61, vs the raw ~330–420).
**Not empty** — deliberately: the same rule catches `add_*`/`create_*`, and a create genuinely needs
its new `id`/`idShort` back, so a tiny identity feeds that for free while pure mutations
(`move`/`update`/`archive`) get a harmless confirmation. The ~15-token gap between this and `{}` is
noise next to the desc win.

**Gotcha for anyone wanting literally empty `{}`:** `spec_from_dict` in `filters.py` has a
falsy-empty-list bug — `if identity:` ignores an explicit `identity: []` and silently falls back to
the 7-field default. Truly-empty mutations would need that 1-line fix **and** splitting creates out of
the mutation pattern (so they keep their id). Judged not worth it. Recorded so the footgun is known.

Leave `get_card` on the default pipeline: a `keep_keys` allowlist there would strip its nested
`checklists`/`checkItems`/`board` (allowlist applies at every level), which is the whole point of the
detail view. `get_my_cards` still carries `desc` (3 calls total — trim for parity if desired).

## 5. Needs the upstream fork (input-shape changes)

Both are about what the client *sends*, so they cannot live in the filter — fork
`@delorenj/mcp-server-trello` (the deployment runs it via `npx -y @delorenj/mcp-server-trello`;
vendor a patched build the way `../DockerImages/telegram-mcp-server` is vendored).

- **`get_card_by_id_short(idShort)`** — kills the "scan every list to find a card" loop. Maps to
  Trello REST `GET /1/boards/{boardId}/cards/{idShort}` (a card is addressable by its board-local
  number); use the server's active board + `idShort`. Filter its result like `get_card`.
- **Optional `label`/`labelId` on `get_cards_by_list_id`** — filter server-side before returning.
  **Highest-value item for this setup:** the Triage/Kanban boards are *shared across projects with one
  label per project*, so "only my project's cards" is the real access pattern on every list call —
  today you receive every project's cards and discard most.
- **Bundle while forking:** a `get_cards_by_board(boardId, label)` returning all open cards on a board
  in one lean, label-filtered call — this directly replaces the scan-every-list pattern that motivates
  `get_card_by_id_short`, collapsing several list calls into one.

## 6. Is this enough? Two things matter more than further trimming

1. **Call Trello less (workflow).** Trimming helps linearly; the *multiplier* is the real cost. The
   task-runner architecture (#175) already handles most of it — the `/run-slice` orchestrator is idle
   while the runner drives, and subagents never touch Trello (verified). The residual leak is narrow:
   the orchestrator **scans a whole list to locate the `[NNN]` card before every lifecycle move**
   (measured: 225 `get_cards_by_list_id` calls, 66 adjacent scan→move pairs) because the card id is
   persisted nowhere. Fix = persist the card id at `/triage` and move by id. Written up as
   [`HANDOVER-trello-workflow.md`](HANDOVER-trello-workflow.md). Ties to PLAN.md's "files durable,
   sessions ephemeral".
2. **Single source of truth for the filter spec.** The spec is duplicated by hand in two files that
   were byte-identical and *will* drift:
   - `../HelmCharts/charts/trello-mcp/templates/filter-configmap.yaml` — **deployed** (mounted into
     the filter sidecar).
   - `../DockerImages/mcp-filter/examples/trello.yaml` — what the mcp-filter **test suite** validates.

   Both were updated and a sync note added, but the real fix is one source (chart mounts the example,
   or a CI diff-check).

## 7. Files touched / open items

**Applied (working tree, not committed at time of writing):**
- `../HelmCharts/charts/trello-mcp/templates/filter-configmap.yaml` — the two fixes (deployed spec).
- `../DockerImages/mcp-filter/examples/trello.yaml` — mirror (tests + docs).
- `../DockerImages/mcp-filter/tests/test_filters.py` — tightened `test_cards_allowlist` (asserts `desc`
  gone) and `test_mutation_collapses_to_identity`; added `test_pure_mutation_drops_fat_object`. Unit
  suite: 29 passed.

**Deploy note:** committing the HelmCharts ConfigMap rolls the shared `trello-mcp` pod via ArgoCD (the
deployment's timestamp annotation forces the restart so the ConfigMap remounts — `subPath` mounts do
not hot-reload). The mcp-filter image needs **no** rebuild; it reads the spec from the ConfigMap.

**Open:**
- [ ] Commit + deploy the filter fixes (operator go-ahead — it's a shared service).
- [ ] Fork `@delorenj/mcp-server-trello` for #3/#4 + `get_cards_by_board` (§5).
- [ ] Persist the Kanban card id at `/triage`; move by id in `/plan-slice`+`/run-slice` (§6.1) —
      brief in [`HANDOVER-trello-workflow.md`](HANDOVER-trello-workflow.md).
- [ ] De-duplicate the two filter-spec copies (§6.2).
