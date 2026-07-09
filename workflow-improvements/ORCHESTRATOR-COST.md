# Where the orchestrator's tokens go (post-`track_build`)

Follow-up to [`ANALYSIS.md`](ANALYSIS.md), which established that the **root orchestrator is the single
biggest cost centre** (~53% of all spend; ~44% even for slices that use `track_build`). This drills
into *what the orchestrator actually spends tokens on now that build-polling is mitigated*, from a
per-turn read of three orchestrator sessions **that use `track_build.py`**. Source material — the raw
per-turn analyses are in [`data/orchestrator-deepdive/`](data/orchestrator-deepdive/); this file is the
synthesis.

## The three sessions

| Session | Slice | Cost | Turns | Wall | cache_read share | idle share |
|---|---|--:|--:|--:|--:|--:|
| `2dc10628` | 073 close-out | $47.93 | 212 | 8.15h | ~98% | 82% |
| `7fc93cbe` | 069 | $40.45 | 161 | 12.07h | ~97% | 68% |
| `aa40ad86` | (multi) | $18.78 | 116 | 4.91h | ~95% | — |

All three are ~95–98% `cache_read` — the cost is **re-reading a large, long-lived context on every
turn**, not output. (These are subscription runs, so USD is an API-equivalent consumption yardstick,
not a bill — see ANALYSIS §1.)

## `track_build.py` — verdict: it works, and it's a rounding error

Across all three, `track_build`'s own footprint is negligible: **~1,100–1,640 tokens / ~$0.02–0.05 per
session** (background-launch + small summary read), a **30–90× reduction** versus the ~27k-char manual
Jenkins-poll blobs it replaced. Its demonstrated ROI is **~$2.6–2.7 saved per slice-push** (the gap
between a manual-polling dead-end and one working call). **Build-tracking is a solved problem — it is
not where the money goes.** Two residual gaps worth a small fix:

- **No failure mode.** On a *failed* build, `2dc10628`'s orchestrator fell back to manually
  grep/Read/tail-ing the raw 13.3k-char Jenkins log — a mini-recurrence of the old anti-pattern. A
  **`track_build --diagnose`** mode that returns just the failure tail as a small summary would close it.
- **Silent breakage.** In `aa40ad86`, `track_build` was broken all session (HTTP 401, missing
  `$JENKINS_TOKEN`) and silently fell back to manual MCP polling — leaving its ~$2.6 saving on the
  table. The token should be provisioned/asserted so the tool can't quietly degrade.

## Where the tokens go now — ranked

**1. Inline live/E2E verification inside the fat root context — THE lever (~30–53% of a session).**
Once the coding is dispatched and merged, the orchestrator *itself* runs the live-cluster/E2E
verification — kubectl port-forwards, `curl`-to-REST, hand-rolled polling loops, deploy checks, LV
tests — all inside a context that has grown to **400–570k tokens**:
- `2dc10628`: the live-verification arc = **~$18.0 (37.6%)** in the final 26% of turns, at **1.7×**
  cost/turn vs earlier; includes a **71-minute hand-rolled kubectl polling loop**.
- `7fc93cbe`: the post-idle tail (pytest + ruff + live SMB read/write test) = **~$21.3 (52.7%)** in 11%
  of the wall-clock, at **1.8×** cost/turn; 43 "status-check" turns alone burned **$5.80 of cache_read
  for $0.29 of output**.
- `aa40ad86`: inline live-verify = **~$3.75** and ~40–50k tokens of *permanent* context growth — where
  a `slice-verifier`-style sub-agent returned only **738 chars** for a full 11-AC pass elsewhere in the
  same session.
→ **Delegate live/E2E verification to a lean, short-lived deploy-verifier agent** (handover doc in,
findings out). Estimated **~30–40% per-session saving**. This is the same idea as `track_build`, applied
to the verification step: keep the huge, re-read-forever logs out of the orchestrator's context.

**2. Idle cache-TTL rewrites — ~$2.1–3.9/session.** Multi-hour deploy waits outrun even the main
session's **1-hour** cache, forcing a full context re-write on resume:
- `7fc93cbe`: an 8.3h gap → a 368k-token reload = **$2.30** ($2.12 above the warm-read cost).
- `2dc10628`: the 71-min polling loop crossed the TTL = **$2.62** excess.
- `aa40ad86`: three full rewrites (idle + env change) = **619k tokens, $3.87, 70% of its cache_write.**
→ Follows directly from #1: if the orchestrator isn't the thing holding a fat context alive across a
multi-hour wait, the reload tax disappears. Idling itself is free (no turns); the tax is only the
cache breach + the size of what gets reloaded.

**3. Trello content read live instead of pre-baked into the bundle — ~$0.4–0.8/session.** Full board
dumps (`get_cards_by_list_id`, 13–31k chars) enter early and are re-read for 100+ subsequent turns
(`7fc93cbe`: two dumps carried 149 and 113 turns). Small individually, pure waste in aggregate.
→ **Put the needed card content into the slice bundle** at authoring time so the orchestrator never
fetches it live. (Operator's own suggestion — confirmed.)

**4. The fixed base-context floor — ~48k tokens re-read every turn — is mostly not addressable.** Every
turn re-reads the Claude Code system prompt + built-in tool schemas + the deferred-tool *name* list +
`CLAUDE.md`. Only **`CLAUDE.md` is user-controllable** (workstream H already trims it). 

> **Corrected finding.** Earlier drafts of two deep-dives attributed a big chunk of this floor to *MCP
> server schemas* (~$7.76). **That is wrong and has been retracted.** These sessions load MCP tools
> **lazily** via `ToolSearch` (verified: every analyzed session uses ToolSearch; only the 2–3 MCP tools
> it actually calls ever enter context). The full schemas are **not** eagerly loaded, so there is
> nothing to gain by trimming the MCP surface — lazy loading already does it. The two source files
> carry a correction banner.

## Ranked actions → plan mapping

| Action | Saving/session | Where in the plan |
|---|--:|---|
| **Deploy-verifier agent** — delegate live/E2E verification off the orchestrator (handover in, findings out) | **~30–40%** ($15–21) | Workstream **D** (Test agent) — now the top-quantified win |
| **Trello content → slice bundle** (don't read boards live mid-run) | ~$0.4–0.8 + no re-read tail | New item (bundle content) |
| **`track_build --diagnose`** (small failure-tail summary) + assert `$JENKINS_TOKEN` | protects the ~$2.6 ROI | Tooling item |
| **Trim `CLAUDE.md`** (the only addressable part of the base floor) | modest, every turn | Workstream **H** |
| Split coding into tasks / shorter orchestrator sessions | compounds #1–#4 | Workstreams **C**, context-mgmt |
| ~~Trim MCP tool surface~~ | **none — rejected** (lazy-loaded) | — |

**Net:** each analyzed session had **~30–40% addressable** cost, dominated by moving live/E2E
verification out of the orchestrator. Because the orchestrator is long-lived, that fix compounds — a
lean verifier stops *every* future slice's post-deploy checks from running inside an ever-growing
context.

## Reproduce / sources

- Per-turn analyses: [`data/orchestrator-deepdive/`](data/orchestrator-deepdive/)
  (`track_build-073-2dc10628.md`, `track_build-7fc93cbe.md`, `track_build-heavy-aa40ad86.md`).
- Tooling: [`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py) (slice/role cost),
  [`data/digest.py`](data/digest.py) (per-turn transcript digest).
- Method + caveats (dedup, subscription-frame cost): [`ANALYSIS.md`](ANALYSIS.md) §1.
