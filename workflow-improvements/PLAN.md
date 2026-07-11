# Workflow improvements — settled design (Trello Triage #175)

**Status:** design settled with the operator (2026-07-09 discussion); execution in progress against
`../KubeCoder`. This file replaced the original workstream plan (see git history for the A–L
version) after the design conversation converged on a materially better architecture than the card's
original shape. Validation is by real slice runs, re-measured with
[`../tools/analysis/slice_costs.py`](../tools/analysis/slice_costs.py).

**Companion evidence:** [`ANALYSIS.md`](ANALYSIS.md) (execution-history analysis) and
[`ORCHESTRATOR-COST.md`](ORCHESTRATOR-COST.md) (per-turn orchestrator deep-dive). Their headline
drove the redesign: **the orchestrator/manager sessions are 68% of all spend; cost = context size ×
turns, and long-lived sessions maximise both.**

**Canonical spec of the new workflow:** `KubeCoder/docs/conventions/task-workflow.md`. This file
records the *why* and the mapping from card #175; that file specifies the *what*.

---

## The settled architecture

**Files are durable, sessions are ephemeral.** No long-lived LLM session drives execution; a Python
state machine does (`tools/ai_workflow/task_runner.py`). Every judgment call is either made once at
planning time or delegated to a fresh, narrow-context session at a defined touchpoint.

The operator's pipeline (one session each, operator-initiated):

1. **`/triage`** — findings/requests → numbered **slice folders** (`slices/NNN_slug/slice.md`).
   The former change-request bundle *is* the slice now; `/write-slice` is retired as ceremony.
   Triage allocates the slice number, creates the Kanban card, and pre-resolves all Trello content
   into `slice.md` (nothing is read from boards mid-run).
2. **`/plan-slice`** (new) — interactive, slice-scoped planning. Plan-writer + plan-reviewer break
   the slice into **3–6 ordered, project-local tasks** (`tasks/NN_slug/`; max 10), each with its own plan;
   cross-project interfaces are defined up front (producing task first); acceptance criteria and
   verification artifacts are emitted here. Planning Q&A with the operator happens once, here — not
   per-project at run time.
3. **`/run-slice`** — thin: launches the **task runner** as a background shell, idles turn-free,
   and acts only as the escalation path for bail-outs (investigate → decide or defer → relaunch).
   Uneventful slices (target ≥50% v1, 75% v2) end with just a final report.

**The task runner** enforces the card's bounded loops mechanically: per task — branch → fresh
`code-writer` → fresh Sonnet `code-tester` per round (cap 3) → `code-reviewer` (cap 2) → ff-merge →
checkpoint. Verdict files (`*_result.json`) make agent outcomes machine-readable; consults (fresh
Opus sessions) judge at limits and flags; `state.json` is the decision substrate and resume point.
Sessions spawn via `claude --agent <role>` (a full session — dev agents can use sub-agents, granting
the card's "linting done in a subagent" wish) with `FORCE_PROMPT_CACHING_5M=1` and cwd = the task's
project directory.

**Escalation ladder:** runner counts → consult judges → `/run-slice` session investigates bail-outs
→ operator. Environmental problems are never worked around — agents report `blocked` and stop
(the claude_session.py background-task kill bug that caused the slice-038 12-re-entry pattern is
fixed; the lesson — scream, don't adapt — is now contract).

## Mapping from card #175 / the original workstreams

| Original | Outcome |
|---|---|
| A migration doc | `CHANGELOG-workflow.md` (this repo) records every cross-document move an adopting repo must replay. |
| B standardize skills | Superseded for the retired skills; project-specific commands live in per-project docs/CLAUDE.md and the runner's config, not in skill bodies. |
| C task model + bounded loops | The core delivery: task folders + runner + verdict contract. Branch-per-task (operator's suggestion) kept — clone-per-slice makes it safe, the runner makes it mechanical, review scope = `merge-base..HEAD`. |
| D test agent | `test-agent` (Sonnet, handover in / findings out) runs final verification from the runner. Findings **bail out** in v1 (`test_findings.md`) — the `/run-slice` session authors fix tasks via `/write-task` and relaunches; scripting the findings loop end-to-end is v2. Live-deploy verification stays post-push in `/run-slice` close-out. |
| E resizing | Retargeted at `/triage` (bundle = slice now, so triage groups sizing-aware) and `/plan-slice` (sizes to 3–6 tasks, max 10; may propose splitting a too-big slice during Q&A). |
| F triage fidelity | Already shipped (`a3eccbf`); `slice.md` carries operator specs at signature fidelity. |
| G agent trims | All dev agents rewritten thin: identity + output contract (now literally the verdict schema) + bounds. Reviewers describe, never fix; tester and code-reviewer get `slice.md` + `plan.md` as requirements with outcome framing (coverage-not-truth for the tester, outcomes-not-approach for the reviewer); external-surface/substitution-test blocks (commit `179f3fe`) deleted, replaced by a one-line grounded-claims rule. |
| H CLAUDE.md | Root CLAUDE.md becomes a **generic KubeCoder brief** (orchestrator role guidance removed — it serves the root session *and* every spawned dev session, which now pay its cost per spawn). Issue-log + push-notifications → `~/.claude/CLAUDE.md` + env template; deploy/cexec → `docs/operations/`; skill list deleted (frontmatter descriptions suffice); Decision-making sections deleted; subproject duplication collapsed. |
| I docs diet | "State every fact exactly once; no recap sentences" added to `documentation-model.md`; moved content lands terse. |
| J claude_session.py | Gains `--cwd`, `--agent`, `--model`, quiet-by-default stderr (`-v` restores streaming); its `_run` machinery is the runner's session backend. |
| L naming collisions | Resolved as part of the skill retirements/renames. |
| Orchestrator-cost items | Trello→bundle: absorbed by triage authoring `slice.md` complete. `track_build --diagnose` + `$JENKINS_TOKEN` assert: shipped with the tooling changes. Major/minor distinction: **gone** — planning is slice-level, execution is uniform per task. |

## Decisions closed (former §N)

1. Migration doc: `CHANGELOG-workflow.md` in this repo.
2. Progress log: script-owned JSON (`state.json` history) — agents never write it; append-safety by
   construction.
3. One test agent, differentiated by the handover the dispatcher writes.
4. Branch-per-task inside the per-slice clone; the runner owns all git management; writer commits
   before every tester round so dropping tester changes is a clean reset.
5. "No backwards compatibility" scoped to internal interfaces; external-interface rules live in
   `docs/`.
6. Consult policy: only on limit-hit or agent flag, plus the post-task checkpoint (runner flag,
   default on). Stuck-detection is a consult's judgment, not a script threshold.
7. Not phased — delivered as one wave, validated by the next real slice runs.

## Validation gate

Run 2–4 real slices in KubeCoder on the new workflow. Measure with `slice_costs.py`: the
orchestrator share (53% baseline) and per-session inline-verification share (~30–53%) should drop
sharply; watch planning quality (task premises) — the task folder is now the only dispatch context,
so plan-writer/plan-reviewer carry the weight the per-project managers used to improvise. Then sync
the settled result back into this repo (`orchestrator/`, `project/`, `tools/`).

## Validation run 1 — slice 072 (2026-07-10)

First real slice through the runner (bot reliability + UX; 5 tasks, 11 requirements, ~2.1k
insertions). All 5 tasks merged, suites green, 12/12 acceptance criteria + V13 independently
audited; the only escalation was the final-verification bail (below). Reviewed end-to-end
(operator + Fable session, 2026-07-10); the merged diff held up under an independent read — no new
blockers, and the loop's own rounds caught real bugs (task 01's budget arithmetic ×2, task 04's
display-name regression).

**Cost** (sticker, dedup by message.id; `tools/analysis/runner_sessions.py`): run fleet ≈ **$100**
— writers $71 (task 04 alone $31), reviewers $13, testers $11 (Sonnet), 5 checkpoint consults
$3.8, test-agent $2. `/plan-slice` ≈ **$29** (interactive session $10 + plan-writer $12 +
plan-reviewer $7; 3 review rounds — round 2 caught a genuine wrong-env-safety MAJOR, so the spend
bought real value). Writers dominate; consults are noise-level.

**Fixes landed from the run review** (KubeCoder, to ride the sync-back):

1. **Two-tier checkpoint consults** — evidence: of the 5 checkpoints, 3 were decidable from the
   run-history summaries alone, 1 borderline, 1 genuinely needed code (same-file overlap with a
   remaining task's plan grounding); the deep diff dives never changed an outcome. The runner now
   embeds the merge's `--stat` in the prompt and prescribes tier-1 (summaries + stat) with tier-2
   (targeted diff reads) only on genuine uncertainty.
2. **Final-verification findings go through a consult** (`fix_tasks` · `proceed_flagged` · `bail`)
   — 072 hard-bailed over ONE low-severity, pre-existing, dormant residual the test-agent itself
   framed as a tracking gap; the runner had no severity routing at exactly the one judgment point
   that lacked a consult. Non-blocking findings now land in `flagged_findings` (operator still
   sees them as Triage cards at close-out) and the slice completes.
3. **Conversation traceability** — `state.json` history entries now carry the transcript path per
   session (and `log.txt` names every session id + path at spawn); close-out commits `log.txt`
   instead of deleting it (072's 234 KB log was dropped). `runner_sessions.py` (this repo) turns a
   slice folder into the full session inventory. Interactive sessions (`/plan-slice`,
   `/run-slice`) remain findable only by grepping `~/.claude/projects/` — a SessionStart-hook
   registry is the clean fix if that hurts again.

**Baseline comparison + behavior profile (post-run analysis, same day).** Old-workflow median was
$64/slice across 67 slices, but the size-comparable majors (038/058/044/052) ran **$150–283 at
15–42 active hours**; 072 all-in was **~$137 at ~5 active hours** with a far higher verification
bar, and the orchestrator share collapsed **53% → ~13%** — the redesign's target metric, delivered.
Transcript profiling of 7 fleet sessions found the agents disciplined (waste ≈ 10–15%: a few
E501 lint round-trips, stale-`old_string` Edit retries, one `-v | tail -300` suite dump; zero
scope creep, real adversarial probing, clean artifact hygiene). The dominant residual cost is
**turn count × context size** (cache reads ~40× output tokens): sessions rarely batch — the
reviewer/tester/test-agent sessions had *zero* multi-tool-call turns and every session serialized
the same 3–4-file bootstrap. Fix landed: every spawned-agent definition now carries a
batch-independent-tool-calls rule (+ `-q` suite output for test-running roles) — measure its
effect on validation run 2. Next lever if needed: task 04 was a $31 writer session (866-line
diff); plan-slice could split that scale of task, trading a longer pipeline for smaller contexts.

## Validation runs 2–6 — slices 074–078 (2026-07-10/11)

Five slices in ~36h wall (074 project introspection 4 tasks · 075 headless session control 5 ·
076 MCP server 6 · 077 service/tool instructions 4 · 078 env CLAUDE.md conventions 1); ~17.7k
insertions total, ~9 fleet-active hours. All 19 tasks merged; every test-agent came back clean
round 1; zero flagged findings, zero bailouts, **no round cap ever hit** (worst case one writer
round 2 in each of 075/076/077 — the loop absorbed every finding without escalation). Reviewed
2026-07-11 (Fable session; Sonnet sub-agents on transcripts per REVIEW-QUICKSTART).

**Cost** (sticker, dedup by message.id; plan/orch figures include their sub-agents):

| slice | fleet | plan | orch | all-in | 072-scale comparison |
|---|---|---|---|---|---|
| 074 | $25 | $12 | $10 | ~$47 | old-workflow median slice was $64 |
| 075 | $97 | $69 | $15 | ~$181 | biggest slice yet (8.5k ins, net-new concurrent Go engine); old majors $150–283 at 15–42h |
| 076 | $74 | $15 | $21 | ~$110 | first net-new deployable (5.8k ins) |
| 077 | $26 | $14 | $9 | ~$49 | |
| 078 | $3 | $4 | $7 | ~$15 | floor case: 1 task, 238 ins |

Batch ≈ **$402**; orchestrator share ≈ 15% (held at 072's ~13% vs 53% baseline). 075's plan is the
one planning outlier ever recorded: 4 review rounds because the operator reframed the architecture
at the review gate *after* round 2 had already gone GO on the discarded shape — the other four
slices planned in one write+review pass ($4–15 incl. sub-agents).

**Post-072 fixes verified on real runs:**

1. **Two-tier checkpoint consults ✓** — every inspected consult prompt carried the 30-line-capped
   `--stat` only; tier-2 escalation was always scoped (grep, single-commit `show`, offset-bounded
   reads); no transcript ran an unbounded diff. Consults cost $0.31–1.28. Star exhibit: 076/03's
   **amend** verdict caught task 05's plan still grounding on a 15s HTTP client right after task
   03 had to introduce a 600s one for buffered project commands — a latent cross-task bug no
   task-scoped agent could see; the consult surgically edited task 05's plan.md and it landed
   clean in one round. (The *final-verification* consult path `fix_tasks/proceed_flagged/bail`
   remains unexercised — all five test-agents were clean r1.)
2. **Traceability ✓** — all 92 history entries across the five state.json files carry transcript
   paths; log.txt committed at close-out in all five slices.
3. **Batching rule: measurable win, unevenly distributed.** Fleet turns/session 38.8 (072) → 17.1
   (074) / 21.2 (077) / 31.1 (076) / 11.6 (078); 075 stayed at 38.5 but on a much bigger slice.
   Cache-read/turn fell 132k → 76–106k except 075 (139k, context-size-driven). Reviewers took the
   rule best: 22.5 → 8.8–18.6 turns/session with multi-tool-turn share 23% → 47–64%. Consults
   8.0 → 5.0–7.0 turns. Testers improved least (9–18% multi): transcript profiling found two
   mechanical anti-patterns — `git diff > /tmp/f && Read` next turn (2 turns per diff, ~19% of one
   session) and authoring throwaway Go probe files via Bash heredoc (self-inflicted compile errors
   + resync Reads). Writers' waste is only ~7–14% of turns but lands late (200–250k cached tokens
   per replay): independent new-file Writes and end-of-session doc passes issued one-per-turn —
   the rule text names Read/Bash, and the writers never batch Edit/Write.

**Code verdict:** the merged diffs held up under independent read. 075's headless engine is
carefully built (documented lock invariants; the tester's round-1 End/reap-mid-turn log-corruption
find was real and the `detached`-guard fix is principled — the writer even proved the regression
test has teeth by neutering the guard and watching it fail). 076's MCP layer is disciplined
(docstrings anchored to acceptance-criteria ids, omits unknowable fields rather than fabricating).
Cross-slice template composition 074/077/078 is clean. Two minor findings, both parked as Triage
cards: 074/04's template section never documented in `claude-md-template.md` (visible only
cross-slice); 075 is the only run without a `test_findings.md` audit write-up (protocol-legal —
the runner only mandates it on findings — but thinner than its four siblings).

**Fixes landed from this review** (KubeCoder `.claude/agents/`, same day):

1. Batching rule extended to **Edit/Write** in `code-writer.md` ("N files with no data dependency
   → N calls in one message") — targets the writers' doc-pass/new-file pattern, the highest-$
   residual waste.
2. `code-tester.md` + `test-agent.md`: **read command output directly** — never
   redirect-to-file-then-Read; author probe files with Write/Edit, not Bash heredocs.

**Levers recommended, not landed (operator judgment):**

3. **New-deployable slices need an explicit infra/deploy task at planning time**: 076's
   orchestrator hand-authored Helm templates + five architecture-doc edits (138 turns, $21 —
   the one "thin orchestrator" violation) because nothing else owned that work.
4. Surface consult **amend** verdicts as an explicit close-out line item (076's only shows as a
   commit trailer).
5. Plan-slice: ask the shape-level design question (AskUserQuestion) *before* the first
   plan-writer draft — would likely have saved 075's rounds 3–4 (~$25).
