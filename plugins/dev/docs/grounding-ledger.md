# The grounding ledger — format, freshness, and the drift checker

The claim→source ledgers the workflow runs on, so that a fact established once is never
re-derived downstream:

- the **slice ledger**, `<slice>/grounding.md` — born in `/dev:plan-slice`, appended by planning
  passes, read by every plan and task dispatch, and mechanically drift-checked;
- the **per-task ledger**, `<task>/grounding.md` — written by the code-writer for
  behavior-describing prose, and verified by the code-reviewer, which checks the citations instead
  of re-deriving the prose. It uses the same entry format but the checker never reads it: an
  uncited behavioral claim, or a citation that does not support its sentence, is a review finding.

This doc is normative for the entry format — the agent contracts point here instead of restating
it.

## Entry format — one line per claim

```markdown
# Grounding — slice NNN

verified: MyApp@1a2b3c4d5e6f — 2026-07-24

## <topic section>

- G-001: <the claim, one sentence> — `app/podcomposer.py:186` — "OVERLAY_DIRS = ["
- G-002: <claim> — `../SharedLib/values.yaml:204-217` — "toolchains:"
```

- **Exactly one line per entry**: `- G-NNN: claim — ` `` `file:line[-line]` `` ` — "anchor"`.
  The separator may be an em dash, an en dash, or a plain hyphen. No prose paragraphs, no history
  narration, no provenance notes ("added in pass 2") — the rule that a document states the current
  design as if always true applies to this file explicitly. A nuance that will not fit one line is
  usually two claims; split it.
- **`G-NNN` ids are stable and never reused.** New entries take the next free number; a deleted
  entry's number stays dead. Plans cite entries as `[G-NNN]` — that reference is what lets the
  checker scope a task's fact set and lets the prune find dead entries.
- **The anchor quotes the deciding text** — a verbatim, greppable substring of one cited line,
  chosen so that if the fact changed the anchor breaks. It is matched as a plain substring within a
  single line, so an anchor that spans a line break can never match. For a universally quantified
  claim ("exactly four", "never", "only") the anchor MUST be the deciding list or condition itself,
  not a nearby landmark: an "exactly four overlays" entry anchors on the overlay list, so a fifth
  entry breaks the anchor.
- **Paths are relative to the target repo's root**; sibling checkouts via `../SharedLib/…`. One
  citation per entry — a claim resting on two sources is two entries. An entry whose body carries no
  line-numbered citation (including the per-task ledger's `path + symbol` form) is reported
  `UNCHECKED` rather than treated as broken.
- **Sweep entries** record a repo-wide search's methodology and its full result, so the next agent
  spot-checks the method instead of re-walking the tree:
  `- G-014 (sweep): rg "corepack" over /work/MyApp /work/SharedLib — exactly 3 hits: a, b, c`.
  The stated method is what makes the universal claim falsifiable; a reviewer stays free to
  distrust it and rerun. The checker does not grep-verify sweep entries (`UNCHECKED`).
- **The `verified:` stamp**, one line below the title, records the HEAD sha of each cited repo at
  the last verification pass — `Repo@sha`, comma-separated — plus the date. Any agent pass that
  verifies or appends entries updates it to the sha(s) it verified against. The checker and
  `--repair` never touch it.

## grounding_check.py — the deterministic drift checker

```
python3 ${CLAUDE_PLUGIN_ROOT}/tools/grounding_check.py <slice_dir> [--task NN] [--repair] [--prune] [--json]
```

It re-greps every slice-ledger entry's anchor against the working tree and reports, per entry:

| Status | Meaning |
|---|---|
| `OK` | the anchor is inside the cited line range |
| `MOVED` | the anchor is elsewhere in the file, at exactly one line |
| `MISSING` | the anchor is nowhere in the file — **or** at several lines, none of them the cited one, which cannot be repaired safely |
| `GONE` | the cited file no longer exists |
| `UNCHECKED` | a sweep entry, or one the checker cannot mechanically verify |

It also reports `commits_since` the stamp, per stamped repo.

**Run it from the target repo**: citations are relative to that repo's root, which the checker
takes from `git rev-parse --show-toplevel` in its cwd — the plugin's tools live under `~/.claude`,
so their own location says nothing about which repo is being checked. Run from outside a git repo
it exits 2, and the dispatch treats that like any other unusable answer.

`--task NN` scopes the check to the entries that task's `plan.md` cites by `[G-NNN]`, and
additionally walks the plan's own backticked `` `path:line[-line]` `` citations: does the file
exist, is the line inside it, and how many cited files were touched since the stamp. `--repair`
rewrites `MOVED` line numbers in place, preserving a range's span — mechanical, no model.
`--prune` deletes every entry no `tasks/*/plan.md` cites; it scans all plans, so it cannot be
combined with `--task`, and it refuses to run when there are no plans at all rather than emptying
the ledger. Neither rewrite is committed by the checker: callers go through
`grounding_dispatch.commit_ledger`, which stages **and** commits `grounding.md` by explicit
pathspec so a parallel session's staged work in a shared spec tree is never swept up.

A ledger with no file, no stamp, or no `- G-NNN` entries is reported as `legacy` and skipped —
dispatches then carry an "unverified" line instead of a trust line. Exit codes: **0** tier 0 or 1
(and legacy) · **3** tier 2 · **2** usage or precondition · **1** unexpected error. The callers
accept 0 and 3 alike as reports and treat anything else as "no mechanical check ran", so a broken
checker degrades rather than stopping a slice.

## Tiered drift handling

The checker's outcome routes mechanically; **only tier 3 reaches the operator**:

- **Tier 0 — no drift.** The dispatch carries a deterministic trust line ("verified at `<sha>`,
  anchors hold at HEAD"); the receiving agent re-derives nothing.
- **Tier 1 — MOVED.** `--repair` fixes the line numbers; no model involved.
- **Tier 2 — MISSING/GONE.** A scoped re-grounding pass (`slice-grounder` in worklist mode) gets
  the checker's filtered JSON as its **whole** worklist: confirm, update, or falsify exactly those
  entries — never a fresh full grounding.
- **Tier 3 — a load-bearing claim falsified.** Stop; do not repair plans in-session. The
  re-grounding pass has already corrected the ledger, so the escalation names the falsified claims
  **and the recovery path — normally a fresh `/dev:plan-slice` re-plan** ("re-plan, don't patch"),
  which reads the corrected ledger from its first turn. A fresh session that sees target state from
  the start beats one steering around a mid-session correction; the escalation's job is a clean
  stop and a precise list, not remediation.

## Where it runs

1. **Plan loop** — `--repair` before every writer and reviewer dispatch, script-only: the summary
   rides the dispatch as a trust line or as the drifted-entry list for that pass to absorb, with no
   extra agent step mid-loop. At GO, once more with `--prune`.
2. **`/dev:run-slice` preflight** — the whole ledger plus all plan citations, `--repair`. Tier 2: the
   orchestrator dispatches the scoped re-grounding pass. Tier 3: stop before the runner starts.
3. **Task dispatch** — `--task NN --repair`, once per task per run and cached, so the writer's
   initial dispatch and any fix round carry the same fact. `MISSING`/`GONE` here mean "treat those
   entries as unverified", never "stop" — tier 2 and 3 escalation is preflight's job. The
   post-merge checkpoint consult additionally gets a whole-ledger drift summary, unrepaired, as
   deterministic input on the remaining tasks.
