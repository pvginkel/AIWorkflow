# Handover: execute the docs diet in KubeCoder

A self-contained brief for a future session (schedulable; no context from the #175 work needed
beyond this file). **The job: bring KubeCoder's existing documentation set into compliance with
the diet rules that `docs/documentation-model.md` established during #175.** The rules shipped;
the existing docs were never reworked to meet them — `CHANGELOG-workflow.md` lists this under
*Known open items*.

## Why it matters (and why it was deferred)

Every task plan carries a required-reading list of `docs/` topics, and **every downstream session
re-reads those docs on every turn**. An oversized or redundant doc is a tax paid indefinitely, per
session. It was deferred from #175 because it touches every scope's docs and none of it blocks the
task-runner workflow itself.

## The rules to enforce

Canonical text: `/work/KubeCoder/docs/documentation-model.md` (read it first). The load-bearing
rules for this pass:

- **One subject per doc; split rather than grow.** 100 lines is big — a doc that size is usually
  several topics wearing one title.
- **State every fact exactly once.** No recap/summary sentences, no restating another doc (link
  it). Delete redundancy; never delete the only statement of a fact.
- **No tombstones.** Superseded conventions are rewritten, not appended to.
- **Index discipline.** `docs/index.md` per scope is a pure fan-out: one line per doc, no entry
  without a doc, no doc missing from the index. Splits must update it.
- **Decisions.** Rationale lives in topic docs; `../KubeCoderSpecs/decisions.md` stays a thin
  index (one ≤100-char row per `DNNN` pointing at the owning doc).

## Current state (measured 2026-07-10, lines per doc)

Docs over the ~100-line bar, largest first — the primary worklist:

| Lines | Doc |
|---|---|
| 233 | `controller/docs/kubernetes/pod-composition.md` |
| 216 | `docs/operations/live-verification.md` |
| 207 | `docs/conventions/task-workflow.md` — *contract doc; see note below* |
| 170 | `docs/operations/deploy-operations.md` |
| 161 | `worker/docs/cexec.md` |
| 157 | `controller/docs/kubernetes/build-toolchains.md` |
| 144 | `bot/docs/conventions.md` |
| 140 | `worker/docs/binary-modes.md` |
| 128 | `worker/docs/sessions/connect-cli.md` |
| 128 | `packages/kubecoder-contracts/docs/go-codegen.md` |
| 126 | `vscode-extension/docs/restore-flow.md` |
| 124 | `bot/docs/ux/status-formatting.md` |
| 122 | `packages/kubecoder-contracts/docs/conventions.md` |
| 120 | `worker/docs/testing.md` |
| 120 | `controller/docs/state/storage-and-metadata.md` |
| 116 | `bot/docs/ux/confirmations.md` |
| 110 | `worker/docs/setup/claude-json-write-discipline.md` |
| 107 | `bot/docs/testing.md` |

(Re-measure before starting: `find docs */docs packages/*/docs -name '*.md' | xargs wc -l | sort -rn`.)

Note on `task-workflow.md`: it is the canonical workflow contract, deliberately one document. Split
only if a genuinely separable topic falls out (e.g. session mechanics); do not shred the contract
to hit a line count. Line count is a smell, not a rule — the rule is one subject per doc.

## Method

Per scope (root, `controller/`, `worker/`, `bot/`, `packages/kubecoder-contracts/`,
`vscode-extension/`):

1. Read the scope's `index.md` and each over-bar doc. Identify the distinct subjects inside.
2. Split into small topic docs (folders by area where a scope has grown); rewrite rather than
   cut-paste where prose is chronological or repetitive; dedupe facts across docs by linking.
3. While touching a doc, spot-check grounding — the model requires documenting what is true in
   the code; fix drift you can verify, flag drift you can't.
4. Update `index.md` 1:1; keep `decisions.md` rows pointing at the (possibly new) owning docs.
5. Nothing is lost: every fact in the old doc exists in exactly one new doc.

## How to run it

Two workable shapes; the operator picks:

- **Direct:** one `/update-docs` session per scope with the scope as the hint (the skill already
  fans out Explore sub-agents and owns exactly this job). Cheapest; docs-only, so the task-runner
  machinery adds little here.
- **As a slice:** `/triage` a docs-diet slice and run it through `/plan-slice` → `/run-slice`,
  one project-local task per scope. Heavier, but gives per-scope review and a verification round.

Commit per scope as pieces settle. No pushes without the operator's green light (standing rule).

## Done when

- Every doc is single-subject; the over-bar list above is empty or each survivor is a justified
  single topic.
- No fact stated twice across a scope's docs; no recap sentences; no tombstones.
- Every `index.md` is a correct 1:1 fan-out; `decisions.md` rows all resolve to an owning doc.
