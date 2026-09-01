# The doc phase, two-stage — proposal for Triage #716

Answers the card "Rework the documentation phase" (Operator Actions, 2026-08-26): the doc phase
becomes a coordinator that identifies work packages plus authoring sub-agents, and the card's
three open questions — who spawns the units, whether an earlier phase should identify the
packages, whether Sonnet prep at the end of each coding phase pays. Written 2026-08-27 from a
turn-by-turn read of three doc-writer sessions (184, 186, 170), the 33-session cost trajectories
(`tools/doc_split_whatif.py`), and the KubeCoder headless engine's turn semantics. It replaces
[turns-plan.md](turns-plan.md) § T6, whose per-repo unit the evidence below falsifies.

**Recommendation in one paragraph.** Ship three small fixes first — they are independent of the
rework and take 15–25 % off today's doc-writer on their own. Then rework the phase as **one
coordinator session that walks the diff, writes the work packages to a file, dispatches one
authoring sub-agent per doc *scope* and yields until they return, then reconciles their output
as a whole, gates once and commits**. The coordinator spawns the units itself (no driver loop
change); the package file is the durable record and the migration path if the driver ever needs
to run the units. Package identification stays in the doc phase; neither the code-writers nor a
per-phase Sonnet prep should do it. "More agents over fewer" holds for big slices only: a unit
costs ≈ $0.35–0.60 before it does any work, so it needs ≈ 3 pages of work to pay for itself —
2–4 units on a typical KubeCoder slice, 6–8 on a 170-sized one, never one per page.

## Phasing — what to ask for

- **Phase 1 = § 3**, one plugin version, prose + dispatch + a small driver addition; no new
  agent, no A/B needed (nothing in it exposes quality). Read on the first two slices it reaches
  with `t4_readout.py writers --role doc-writer` (§ 8) — the expected signature is orientation
  turns down, `ctx_fe` down ≈ 10–20 k, and no Explore report arriving after the first edit.
  **Shipped as dev 0.9.9 (2026-08-27)**, with § 6 items 1–2; the dispatch's verb block carries
  `list`, `append`, `note` — not `strike`, which close-out.md reserves for the completion
  consult. KubeCoder's `slice-doc-plan.md` § 1 names the diff files in place of the ranges.
- **Phase 2 = § 4 + § 6 items 1–2**, the new `doc-unit` agent and the `units.json` contract,
  A/B per § 8. **Shipped as dev 0.9.14 (2026-09-01)** under the § 7 defaults this proposal
  states: the unit is a documentation-model scope (KubeCoder's `slice-doc-plan.md` § 2),
  doc-comments in the diff's own files are named there as a surface, the `api/*.md` gap was
  closed by #738, and the counts ruling is still the operator's. § 6 item 3 is **dropped**: the
  doc plan's append-time rule (#572 — read `decisions.md` when you append, because the spec
  repo is shared by parallel sessions) makes a dispatch-time high-water mark a stale-id trap,
  and the phase-1 read prices the hunt at 1–3 turns per session.
- **Phase 1 read** (2026-09-01; slices 190–193 on 0.9.12/0.9.13 — `t4_readout.py writers
  --role doc-writer`, plus the four transcripts read for the yield). Median session 64 turns /
  $6.19 / `ctx_fe` 96 k against the 16x–170 corpus's 78 / $8.09 / 127 k, and the whole corpus's
  59 / $6.04 / 118 k — the post-T3 sessions were already at the corpus median on turns; what
  moved is the context at first edit, −21 k. No writer opened plan.md or slice.md and none ran
  `git diff` for the slice diff: the diff files and the digest hold. The yield holds for the
  first report on all four — a pure dispatch turn, one no-op turn (`echo waiting`: the headless
  session parks by burning a turn rather than ending bare), the report. It is not held for a
  fan-out's later reports (190 dispatched 2 surveys, 193 3): those landed 3–21 turns after the
  first edit — but no longer as waste; the writer edited only the scope whose report had landed
  and opened each later scope after its report, a pipeline. Survey reports are 16–48 KB each,
  delivered whole into the writer's context; sub-agents are 17–33 % of the phase ($1.24–4.42 on
  $6.04–8.85 writers). (`turn_profile.replay` attributes a sub-agent's report to its launch
  turn — the Agent tool's `tool_result` is only the launch ack, the report arrives as a later
  task notification — so the yield cannot be read from its rows; the transcripts' notifications
  were read directly.) Two contract consequences for phase 2: the coordinator yields again until
  every unit has reported (the harness resumes on each completion), and briefs a survey for a
  list, never page contents.
- § 5 lists what neither phase does; § 7's last three items are KubeCoder rulings, not plugin
  work.

## 1. What the doc-writer actually does (the reverse-engineering the card asked for)

Three sessions read turn by turn; the whole corpus (25 sessions, 144–170) plus the eight post-T3
sessions (173–186) for the medians.

| | 186 (1 repo, 2 phases) | 184 (1 repo, 3 phases) | 170 (3 repos, 12 phases) |
|---|---|---|---|
| turns / $ | 65 / $7.65 | 78 / $8.40 | 192 / $33.28 |
| + its own Explore sub-agents | 1 / $1.16 | 2 / $1.55 | 2 / $4.19 |
| ctx: first turn → first edit → max | 24.5 k → 119 k → 222 k | 24.5 k → 123 k → 233 k | 32 k → 184 k → 438 k |
| first edit at turn | 22 | 31 | 34 |
| doc files committed | 14 | 15 | 55 |
| source diff | 12 files, +1.0 k | 21 files, +1.8 k | 80 files, +5.4 k |

**Every session is the same five stages**, and only one of them grows:

| stage | 186 | 184 | 170 | scales with |
|---|---|---|---|---|
| 1 intake — procedure doc, `git log/--stat`, **plan.md whole** (8–18 k tokens), slice.md | 4 t | 4 t | 6 t | fixed (plan length) |
| 2 diff walk — per-file `git diff`, new source read whole | 5 t | 6 t | 15 t | the diff |
| 3 survey — greps, `find`, doc model, index files, Explore dispatch | 12 t | 20 t | 12 t | the doc tree |
| 4 **read page → edit page alternation, ≈ 2.5 turns per surface** | 29 t | 37 t | **114 t** | **the surface count** |
| 5 tail — gates, git review, close-out Summary/Focus, commits, verdict | 22 t | 25 t | 45 t | fixed ≈ 20–25 t |

Stages 1 + 5 are 26–29 turns whatever the slice (45 % of 186, 26 % of 170). Stage 4 is the only
unbounded term and it tracks **doc surfaces, not diff lines**: 170's diff is 5× 184's, its
surface count 3.7×, its turn count 2.5×. Orientation (stages 1–3) is 22–31 % of the dollars
directly, but the 95–150 k tokens it loads are carried at cache-read rate by every later turn:
attributed, ≈ 45 % of each session. The single worst line item is plan.md read whole and never
referenced after the diff walk — $0.30 / $0.37 / $1.71 of carry.

Three defects the read names, all fixable without the rework:

1. **The Explore sub-agents are a pure loss.** All five dispatched (one in 186, two each in 184
   and 170) had good briefs and returned the exact candidate list the writer needed — and every
   report arrived **18–49 turns after dispatch, after the writer's first edit**, because the
   Agent tool is asynchronous and the writer does not yield: it carries on with orientation,
   which *is* the survey, re-derives it by hand (46–66 % of the paths it read after dispatch were
   paths its own sub-agent had read), then pays to carry a report it no longer needs. Cost:
   the agents ($1.16 / $1.55 / $4.19) plus the carry ($0.16 / $0.58 / $1.88) — **15–21 % of each
   session.** The engine is not the problem: `kc session send` leaves stdin open so the harness
   re-invokes the model when a backgrounded sub-agent finishes, and resolves only on the
   terminal result (KubeCoder `worker/docs/sessions/headless-engine.md`). A headless agent
   *can* wait by ending its turn; the contract never tells it to. (The same pattern is visible
   in plan-writer/plan-reviewer overlap, 17–18 % — out of scope here, worth one line in their
   registers.)
2. **The diff round-trips through disk.** 184 T6–T8: a per-file `git diff` exceeded the tool
   limit, was persisted, and read back in two turns — 7.8 k tokens for nothing. 170 sliced one
   26 k-char diff three times.
3. **The tail's mechanics are discovered, not given.** `close_out.py --help` fumbles (3 in 186,
   1 in 184, 4 in 170), close-out.md read in 5–10 separate turns, previous slices' close-outs
   read as a style reference for the Summary/Focus lines, `kc project info` to find the gate
   names. 8–9 turns of close-out mechanics in the small sessions, ≈ 22 in 170.

**Why T6's per-repo unit is wrong.** 170's second and third repos produced *no* doc-file edits
between them — HelmCharts cost 2 turns, KubeCoderSpecs 3 (decisions.md + close-out.md). A
per-repo split would have bounded 5 of 192 turns and duplicated stages 1 and 5 per repo. Seven
of the nine post-T3 slices are single-repo and run 60–92 turns anyway. The axis that binds is
the **doc scope**: 170's 68 edit turns split controller 27 / worker 16 / root docs 9 / manual 7 /
bot 4, in 19 contiguous runs with 18 scope switches (`worker/docs` visited five separate times).
KubeCoder's documentation model already defines exactly those scopes — the root `docs/`, each
subproject's `docs/`, the manual — so the unit is a project-side concept the plugin never
hardcodes.

**What a per-page split would lose.** 170's 4 edits to `docs/index.md`, 5 to
`startup-and-daemons.md`, the D218 anchor moved after a repo-wide link check, and "two accepted
residuals → three" — a fix that only makes sense with all phases in view. Half of 170's commit
was counted-inventory upkeep (32 of 55 files changed a number-word), which is whole-slice work by
nature.

## 2. The cost model, on the real trajectories

`tools/doc_split_whatif.py` re-prices each session's turns after the first edit as *k* contiguous
chunks run in fresh contexts (prefix + hand-off + re-read files written once, then dragged; same
growth as the original), with the coordinator paying one result turn per unit. Pooled saving
against actual, by the unit's fixed cost:

| unit prefix / hand-off / re-reads | new (8, post-T3) k2 · k3 · k4 · k6 · k8 | corpus (25) k2 · k4 · k6 · k8 |
|---|---|---|
| 21 k / 3 k / 30 k | −13 · −9 · −4 · **+8** · +20 % | −27 · −24 · −17 · −8 % |
| 21 k / 2 k / 15 k | −22 · −19 · −16 · −7 · +2 % | −34 · −33 · −28 · −22 % |
| 12 k / 2 k / 15 k | −26 · −24 · −21 · −14 · −6 % | −38 · −38 · −34 · −29 % |
| 21 k / 3 k / 50 k | −4 · +1 · +8 · +24 · +40 % | −19 · −13 · −4 · +7 % |

Three things the table settles:

- **The saving is the tail's.** Sessions ≥ 100 turns (ctx past 240 k) save 30–50 % at any *k*;
  the post-T3 median session (60–92 turns, 120 k at first edit) saves 10–20 % at k = 2–4 and
  *loses* money past k ≈ 6. The card's "earlier turns are a lot cheaper" is true (a 25 k turn
  costs a fifth of a 140 k one) but a unit does not run at 25 k: its prefix, brief and re-reads
  put it at 40–60 k before the first edit, and each unit writes that once at cache-write rate.
- **A unit's fixed cost is ≈ $0.35–0.60 on Opus** (21 k prefix + 3 k brief + 15–30 k re-reads:
  $0.24–0.34 written, plus $0.02–0.03 per turn dragged). It pays for itself at ≈ 8–10 turns of
  work, i.e. ≈ 3–4 pages. **So: one unit per scope with ≥ 3 pages, small scopes merged into a
  neighbour.** 2–4 units on a typical slice, 6–8 on a 170.
- **The brief is the whole game.** The same k = 4 swings from −16 % to +8 % between a unit that
  re-reads 15 k and one that re-reads 50 k. A unit handed the pages, the claims, and file:line
  pointers into the diff reads little; one handed "update the controller docs" re-runs stage 3.

The ceiling: cache-read is 50 % (new) to 63 % (corpus) of the doc-writer's dollars; output is
10–12 % and does not shrink under any split. Combined with the three fixes in § 3 (which take
their share off *before* the split), the honest expectation is **doc-writer −25–35 % on the
median slice (≈ $2–3), −50 % on the tail**, ≈ 3–4 % of slice cost — plus whatever the
reconcile pass buys in quality, which is the part the card is really after.

## 3. Ship first, independent of the rework (S; prose + dispatch; one version)

1. **Yield after delegating.** doc-writer.md rule 8 gains the sentence: *dispatch the survey, then
   stop — end the turn with nothing else in flight; the harness resumes you with the result.*
   −15–21 % on today's sessions, or the same if the delegation is simply dropped (the writer
   re-derives it anyway). Keep the delegation: a survey at 12 k prefix is cheaper than the same
   reads in the writer's 100 k context.
2. **The dispatch carries the plan digested, not the plan.** A whole-plan variant of
   run_loop.py's `build_phase_digest`: every phase's done-record (the `**Done (P…)**` record
   T4 already extracts, same ~25-line bound) plus the requirements/rulings sections, inline in
   `DOC_PHASE_PROMPT`; the writer is told plan.md is there to open only where the digest points
   and that slice.md is not its input (the doc plan's § 1 already says the diff and the rulings
   are all the steering there is). Beside it, the driver writes each repo's diff to
   `<slice_dir>/doc_phase/<repo-basename>.diff` (`git diff --stat` at the top, then the diff)
   and names the files in the dispatch in place of the `git diff` ranges, so the writer reads
   hunks by path with `sed` and no result ever round-trips through the persisted-output file.
   −5–10 %.
3. **The tail's mechanics in the dispatch:** the `close_out.py` verbs the phase uses (`list`,
   `append`, `note`, `strike`, and how the Summary and `Focus:` lines are written) with their
   argument shapes, from `close_out.dispatch_line`'s neighbourhood — the `--help` round trips
   and the "read a previous slice's close-out for the style" turns go. −5–8 turns. (The gates
   need nothing: the project's doc plan names them; 184's `kc project info` turn was a
   component-name lookup, one turn.)

These make the A/B of the rework cleaner, since the coordinator inherits all three.

## 4. The rework (M)

### The shape

```
driver ── dispatch ──▶ doc-writer (coordinator, Opus, one kc session)
                         │ 1. intake: digest + rulings, diff files, decisions.md high-water mark
                         │ 2. walk the diff, survey the doc tree — synchronously, itself
                         │ 3. write <slice_dir>/doc_phase/units.json  (the work packages)
                         │ 4. dispatch one dev:doc-unit sub-agent per unit, in one message; YIELD
                         │      units edit pages on the doc branch's tree; no commits; return receipts
                         │ 5. reconcile: git diff of the doc tree, cross-scope consistency,
                         │    indexes + decisions.md (single writer), gates once, commit,
                         │    close-out Summary + Focus, verdict
                         ▼
driver ── gate sweep ── land ── push   (unchanged)
```

**The coordinator** is today's doc-writer minus stage 4. Its product is `units.json`, written
before any dispatch: one entry per unit with the scope, the pages it owns (existing and new), the
behaviours that changed with file:line pointers into the diff files, the done-record settlements
that bear on it, the counted inventories to re-count, and what it must not touch (generated
surfaces; a page owned by another unit). The file is durable for three reasons: the readout counts
units and pages from it; a crashed coordinator resumes from it; and it is the migration path if
the driver ever runs the units itself (§ 5). The grouping is the coordinator's judgment — the
card's objection to grouping in Python stands; Python supplies lists, never packages (§ 6).

**A unit** (`agents/doc-unit.md`, dispatched as `dev:doc-unit` the way `dev:test-fixer` is;
inherits Opus) receives its `units.json` entry verbatim plus the standing rules — ground every
claim in source, update in place, no tombstones, the project's doc conventions by name — and
returns a **receipt, never evidence**: files edited, claims it could not verify (with what it
wrote instead), index rows it needs (path + one line), decision candidates (never an id), and
cross-scope claims it noticed but does not own. It does not commit, run `close_out.py`, or touch
an index or `decisions.md`. Units own disjoint files, so they run in parallel — one Agent
message — and the coordinator yields once.

**The reconcile pass** is the consistency check MemDocAgent puts outside the model, done by the
one head that has the whole picture: the coordinator reads the doc tree's diff, checks that a
name, a count, a claim moved the same way in every scope, writes the index rows and allocates
`DNNN` ids at append time (the single-allocator rule the doc plan already states), fixes what
the receipts flagged, runs the gates once (manual strict + the touched components'), commits
(specs files by name), writes the close-out Summary and Focus lines as now. 184's own T64 diff
review found its earlier passes inconsistent and re-edited two pages — the pass finds real
things even inside one session. Budget ≈ 15–25 turns at ≈ 100–140 k; the coordinator's
`ctx_max` should sit under 150 k on every slice.

### The card's three questions

**Who spawns the units — the coordinator, via the Agent tool.** Feasible because the headless
engine re-invokes the model when backgrounded sub-agents finish (§ 1); no run-loop change;
units run in parallel; the coordinator keeps its context for the reconcile pass instead of a
resume or a re-orienting successor; `slice_cost.py` already prices sub-agent transcripts, so
the readout needs no new plumbing. What it gives up: per-unit nudges, timeouts, reattach and
state.json rows — a stalled unit sits inside the coordinator's 7200 s timeout and a failed one
is the coordinator's to redo or absorb. `units.json` is the record either way. Promote to
driver-run units only if the A/B shows unit failures the coordinator handles badly.

**Should the code-writers (or any earlier phase) identify the packages — no.** Three reasons.
Identification is the cheap end of the doc session, and § 3 removes most of what makes it
expensive (the plan read, the diff round-trip, the lost survey). A per-phase view misses what
the whole-slice view is for — 170's `docs/index.md` edited four times, one page five times, the
"two → three" count that needs all phases in view. And the code-writer's done-record turn is
its most expensive turn (its context is at its maximum); adding a surface inventory there costs
more per token than the same reads at the doc coordinator's 50–80 k. The done-records already
say what settled; that is the right hand-off and the digest carries it.

**Sonnet prep at the end of each coding phase — not first.** It has the per-phase blind spot
above, adds ≈ $0.4–0.8 × phases of fixed cost, and the coordinator must still merge and verify
its lists against the whole diff. Revisit only if, after § 3, the coordinator's survey stage is
still > 20 turns on typical slices — then a Sonnet *survey* sub-agent inside the doc phase
(yielded for) is the cheaper form of the same idea.

## 5. What is deliberately not proposed

- **Driver-run units from `units.json`** now. It is the upgrade path, not the first cut: it
  costs a new stage loop in run_loop.py with tests, and either a coordinator resume (a
  `send` after the units — the cache is cold by then, a ≈ 120 k re-write ≈ $0.75) or a fresh
  reconciler that re-orients ($2). The coordinator-spawns design gets the reconcile pass for
  the price of the yield.
- **Sonnet units.** The units' work is grounding prose in code — judgment, not mechanics —
  and the first A/B must isolate the split. A Sonnet arm is a later experiment if the receipts
  show units doing little more than transcribing the brief.
- **Per-page units and per-repo units** (§ 1).
- **An auto-compact window** for the doc-writer (memo P2.2): the split bounds the tail
  directly and keeps the file:line specifics a compaction loses.

## 6. Deterministic facts the driver hands over (lists, not packages)

Each is a few lines of Python and a line in the dispatch, in T4's spirit: the writer stops
spending turns on what a script knows.

1. **The diff per repo on disk** with `--stat` at the top (§ 3.2) — deletes the round-trip and
   lets a unit `sed` its hunks by path.
2. **The done-record + rulings digest** (§ 3.2).
3. **`decisions.md`'s high-water mark** — 170 spent six turns over three visits on the next free
   id; 186 three. One line: "last allocated: D223" (the allocation itself stays with the
   coordinator at append time, as the doc plan rules).
4. **A candidate-page list**, optional and marked as such: doc files (`docs/**`, `manual/**`,
   `README*`) that name a changed file's basename or module path, with line numbers; and the doc
   files the slice's own commits touched. It is the raw material of the survey the Explore
   sub-agents produced, minus the judgment; the coordinator still decides. Worth it if the
   coordinator's survey stays > 12 turns after item 1–3; measure before adding.

## 7. Project-side companions (the card's KubeCoder label)

Not plugin work; each is one edit to `docs/operations/slice-doc-plan.md` or the doc model, for
the operator to rule on:

- **Name the unit.** The doc plan's § 2 becomes "one unit per scope — root `docs/`, each
  subproject's `docs/` + README, the manual — merged when small"; the coordinator reads the
  scopes from here, so the plugin hardcodes nothing.
- **Close the `api/*.md` gap** (184's S2: caught by hand in 142, 179 and 184) — either the doc
  phase owns the spec repo's wire contracts or a standing rule says a plan must carry them.
- **Doc-comments in the diff's own files as a named surface.** 184 edited three module
  comments; 173's B4 and several operator fix-nows were docstrings, test comments, a
  Jenkinsfile comment, a `CLAUDE.md` line. The rule exists half-way (mechanical residue in
  touched files is fixed in place); saying it in § 2 makes it the unit's work.
- **Stop carrying counts.** 32 of 170's 55 files changed a number-word ("five routes → six").
  A documentation-model line in the spirit of slice 167 — the mechanism, not the inventory —
  deletes a class of doc work that rots on every slice.

## 8. A/B, readout, kill rule

Before/after against the corpus, as T4 was read: `t4_readout.py writers --role doc-writer` already
carries the per-session medians (turns, $, `ctx_fe`, `ctx_mean`, orientation turns); extend it
with the sub-agent rows (units: count, turns, $ each, from the transcript dir) and the
`units.json` counts (units, pages per unit). Read § 3 alone on the first two slices it reaches,
then the rework on the next four.

- **Cost:** doc-phase $ (coordinator + units) and share of slice; coordinator `ctx_max` < 150 k;
  units' turns and $ against the ≈ 8–10-turn break-even; the Explore carry gone (overlap ≈ 0).
- **Quality:** the reconcile pass's own findings per slice (a count worth reporting: zero means
  the pass is not looking); the units' unverified-claim receipts; doc-related Bugs and operator
  fix-nows in the next slices' close-outs against the current rate (§ 1's dispositions list);
  a sampled read of two slices' docs.
- **Kill:** doc-related fix-nows rise, or receipts show units writing the vaguer sentence where
  the old writer wrote the precise one — grounding lost to the brief.

**Files.** `agents/doc-writer.md` (coordinator contract), new `agents/doc-unit.md` (with a
`description:` — an agent without one is silently not registered), run_loop.py
(`DOC_PHASE_PROMPT`, the diff files, the digest reuse, the high-water mark), `docs/run-loop.md`,
`docs/close-out.md` (units report through the coordinator; nothing changes in the report's
shape), `docs/agent-dispatch.md` (the yield rule under Nested delegation), tests for the diff
files and digest, bump + changelog; KubeCoder `slice-doc-plan.md` § 2 (the unit). Cost: § 3 S,
§ 4 M.
