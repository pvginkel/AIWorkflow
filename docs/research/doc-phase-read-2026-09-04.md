# The doc phase reworked, read on seven slices (2026-09-04)

The pre-registered read of dev 0.9.14's two-stage doc phase — a coordinator that packages the
work into `units.json` and dispatches one `dev:doc-unit` sub-agent per doc scope, then reconciles
([doc-phase-plan.md](doc-phase-plan.md) § 4, § 8; Triage #716). The proposal asked for "the next
four doc phases"; seven have run, so all seven are here.

**Status: verdict held.** The operator, on this read (2026-09-04): "hold verification until
we've run a few slices that are more representative" — six of the seven are 5–8-phase slices
against the corpus's 3.5 median, and § 2's per-phase normalisation is what the decision turns
on. Re-read on the next few representative slices, appending here: the tool run above plus the
per-phase table of finding 7. Nothing in the doc phase changes meanwhile.

**Corpus.** Seven KubeCoder slices completed on plugin 0.9.20/0.9.22 — 198, 199, 200, 201, 202,
208, 212 — nine doc-writer sessions (200 and 201 each ran a first round that died; § 4). The
marketplace never ran 0.9.14–0.9.19 alone, so all seven carry the whole rework plus § 3's three
fixes. Before-side: the tool's built-in corpus, the 26 single-stage doc phases of slices 144–170.

Every number regenerates from `t4_readout.py writers --role doc-writer --new <the seven dirs>`,
`slice_cost.py <slice_dir>` (all seven and all 26 corpus slices), `close_out.py list`, and
`git show --stat` in `/work/KubeCoder` on each doc-phase commit.

## 1. Cost

From `t4_readout.py writers` (the per-session lines carry `subagents=N (turns $; surveys=n($)
unit_agents=n($))` and `units=<units>/<pages>`) and `slice_cost.py` for the slice total and
`ctxmax`. "Doc phase" below is always **coordinator + its surveys + its units**, both eras; 200's
and 201's rows pool both rounds, the dead one included (§ 4).

| slice | ph | coord $ | surveys $ | units $ | **doc phase $** | slice $ | share | units | ctx_max |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 198 | 6 | 9.81 | 1.43 | 6.58 | **17.82** | 96.21 | 18.5 % | 2 / 22 pp | 228.8 k |
| 199 | 6 | 8.08 | 2.52 | 7.08 | **17.68** | 59.48 | 29.7 % | 5 / 24 pp | 207.7 k |
| 200 | 6 | 11.79 | 6.87 | 12.63 | **31.29** | 135.57 | 23.1 % | 5 / 39 pp | 210.9 k |
| 201 | 8 | 13.66 | 6.33 | 11.33 | **31.32** | 123.18 | 25.4 % | 6 / 38 pp | 279.8 k |
| 202 | 5 | 7.61 | 2.61 | 13.72 | **23.94** | 100.10 | 23.9 % | 4 / 29 pp | 200.1 k |
| 208 | 1 | 2.09 | 0.52 | 1.15 | **3.76** | 27.06 | 13.9 % | 1 / 3 pp | 102.7 k |
| 212 | 7 | 6.29 | 3.33 | 8.79 | **18.41** | 53.28 | 34.6 % | 4 / 33 pp | 189.1 k |
| **median** | | 8.08 | 2.61 | 8.79 | **18.41** | 96.21 | **23.9 %** | 4 / 29 pp | 207.7 k |
| **corpus (26)** | | 7.40 | — | — | **8.89** | 55.67 | **16.1 %** | — | 196.0 k |

1. **The doc phase costs 2.1x what it did** — median $18.41 against the corpus's $8.89 — and takes
   a larger share of a larger slice, 23.9 % against 16.1 %. Pooled over the seven: $144.22, of
   which $14.61 is the two dead first rounds (§ 4).
2. **The coordinator did not get cheaper.** The seven *surviving* coordinator sessions run 65
   turns / $8.08 (median) against the corpus's 71.5 / $7.40 and the 16x–170 band's 78 / $8.09:
   −9 % turns, +9 % dollars. Stage 4 left the coordinator (its post-dispatch edit turns are 2–12,
   median 9 — the reconcile) but two new costs replaced it: the survey fan-out grew from 1–2
   Explore agents to 2–6, and the coordinator now *writes* a 6–41 KB `units.json` (median 30.3 KB)
   at output rate. `$/turn` rose from 0.119 to 0.126.
3. **The whole increase is the sub-agent tier.** Sub-agent spend per coordinator session: median
   $9.60 against the corpus's $1.56 (16x–170 band) — 6x. Units are $1.15–13.72 per slice,
   surveys $0.52–6.87.
4. **A unit agent costs $1.15–3.43, median $1.89 — not the plan's $0.35–0.60.** § 2's *fixed*
   cost was about right (unit `ctx1` is 13.7–17.2 k against the 21 k assumed), but the test it
   licensed is the wrong test: a unit does not stop at the 8–10 turns that repay its prefix. Units
   run 23–60 turns each (median 30) with `ctx_mean` 54–113 k and `ctx_max` up to 188 k. By the
   plan's own rule every unit clears break-even three-to-six times over; the rule simply does not
   predict the bill, because a unit is not a bounded chunk of stage 4 — it is a second writer that
   re-orients, greps and reads on its own account.
5. **`ctx_max` < 150 k is met on 1 of 7** (208, the one-phase slice, 102.7 k). The other six are
   189–280 k, median 207.7 k, against the corpus's 196.0 k median — the criterion is missed and
   the number did not move. The coordinator's `ctx_fe` (context when it writes `units.json`, which
   `turn_profile` scores as its first edit) *is* down: 105.0 k median against 122.5 k / 127.0 k —
   the § 3 digest and diff files still hold. What the split did not shrink is the tail: the
   coordinator ends the slice holding the diff, the survey reports **and** every unit receipt.
6a. **Not faster — slower, absolutely and per phase.** Wall-clock of the doc-writer session
   (`slice_cost.py`'s per-session duration; the units run inside the coordinator's session):
   the corpus sample's single writer took 9–32 minutes, median 14.5, or 3.9 minutes per phase;
   the reworked coordinator's finished rounds take 12–40 minutes, median 26, or 5.0 per phase
   (+30 %). The pipeline is serial where the old pass was one stage — surveys, then
   `units.json`, then units, then reconcile, then the gate — and a unit is a 23–60-turn session
   of its own; the units' parallelism buys back less than the extra stages cost. The phase's
   wall-clock from first log line to landing is the session plus about a minute in the corpus
   and on 198, 199, 208 and 212; 200's ran 2 h 23 (the dead round, the bail and the relock) and
   202's 1 h 27 against a 25-minute session — not broken down here.
6. **The Explore carry is gone.** In every session that reached `units.json`, all survey reports
   landed before it: the surveys are dispatched at t4–t14, `units.json` follows 6–11 turns later,
   and no survey is dispatched after any edit (turn-by-turn trace of the nine coordinator
   transcripts through `turn_profile.turn_ops`). Against § 1's old picture — reports arriving
   18–49 turns after dispatch, *after* the first edit, 46–66 % of the writer's post-dispatch paths
   already read by its own sub-agent — the overlap is 0. The yield contract works; it is also what
   § 4's two failures are made of.

## 2. Output — what the money bought

`git show --stat` on each doc-phase commit in `/work/KubeCoder` (the pattern is one commit on
`phase/<slice>-docs`, subject `<slice> docs: …`; 200 has two, the second a self-correction before
the gate). Corpus sample: 144, 146, 148, 153, 163, 167, 168, 170 — whose doc-phase cost median,
$9.32, matches the full 26's $8.89, so they are a fair output sample.

| | files committed | lines ±  | lines/file | doc-phase $ | **$ / file** |
|---|--:|--:|--:|--:|--:|
| new (7) | 4 · 26 · 26 · **29** · 29 · 32 · 39 | median 524 | 20.1 | median 18.41 | **0.80** |
| new, second rounds only | — | — | — | median 18.41 | **0.69** |
| corpus (8) | 3 · 7 · 10 · 10 · **11** · 14 · 22 · 55 | median 167 | 14.0 | median 9.32 | **0.85** |

7. **This is 2.8x the pages at 2.1x the cost — and most of the 2.8x is slice size.** 29 files
   against 10.5, 524 changed lines against 167 — but the seven new slices are bigger: 6 phases
   median against the sample's 3.5 (`state.json`'s phase count). Normalised per phase of shipped
   work, the doc phase touches the *same* number of files — 4.9 against 4.7 — and writes 60 %
   more lines, 107 against 67, which is finding 8's 20-against-14 lines per file. Per file the
   phase is cheaper than it was ($0.63–0.80 against $0.85); per phase of shipped work it costs
   15–25 % more — $3.4 counting only the rounds that finished, $3.8 with the two dead rounds,
   against ≈ $3.0 for the old writer with its surveys — and delivers 60 % more doc lines. The
   reworked phase is not a more expensive way to do the old job, and not a much bigger job
   either: it is the same pages, edited deeper, on bigger slices.

   | per phase of shipped work | corpus sample (8) | new (7) |
   |---|--:|--:|
   | phases per slice (median) | 3.5 | 6 |
   | files touched | 4.7 | 4.9 |
   | lines changed | 67 | 107 |
   | doc-phase $ | ≈ 3.0 | 3.4 finished rounds / 3.8 all |
   | doc scopes touched, per slice | 4.5 | 6 |

   The non-doc-tree files in both eras are a handful of doc-comments in source (212: five; 202,
   200, 168: one or two) — no generated artifacts inflate the counts.
8. **The extra volume is not churn.** Lines changed per file is 20.1 against 14.0 — the new
   commits touch more pages *and* change more of each. The scopes are real: 199's 29 files span
   six subprojects' `docs/` trees, 201's 39 span five plus the manual.
9. **Doc-comments in source are now in scope** (a § 7 companion shipped with 0.9.14): 212
   committed five, 200 and 202 one each; the corpus sample has one, in 168.

## 3. Quality

From the seven `doc_phase_result.json` verdicts, the nine coordinator transcripts (receipts arrive
as task notifications and are **not persisted** — `doc_phase/` holds only the diff files and
`units.json`), `close_out.py list`, and a read of two slices' committed doc diffs.

10. **The reconcile pass finds something on every slice — 7 of 7 non-zero**, the count § 8 asked
    for. `t4_readout.py` does not separate reconcile edits from packaging edits, so this is the
    coordinators' own post-dispatch edit turns (2–12, median 9) plus what each verdict names:
    - 198 — the eight-built / seven-promoted image counts reconciled across both scopes; D243 and
      D244 allocated at append time; both scope indexes; a gate dependency the launch tests
      introduced.
    - 199 — the key-set fetch policy that had lived only in a module docstring lifted into prose;
      D248 and D249 allocated and cited from *every* surface that honours them.
    - 200 — **two stale counts no unit owned** (the codegen test's 46-defs docstring, the contracts
      index's three-suites row); every quoted refusal and nudge string checked byte-for-byte
      against source; four scope indexes; D250–D252.
    - 201 — **a fact stated in three places trimmed**; two over-claiming comments in
      `manual/mkdocs.yml` and `manual/Dockerfile` corrected; index rows in four scopes; D245–D247.
    - 202 — D085 and D135 amended in place per the operator's ruling; `compose_recovery`'s stale
      docstring; a repo-wide check that no retired symbol survives in any markdown.
    - 208 — the index fan-out entry, and three claims verified still to hold.
    - 212 — D253/D254 with anchors and rows, D240's row corrected, a restated rationale culled.

    The cross-scope items — 200's two orphan counts, 201's fact in three places, 199's D248
    citations — are exactly the class a single-session writer had no reason to look for. This is
    the part of the rework that is working.
11. **The units' unverified-claim receipts are few and they cut the right way.** Grepping the nine
    coordinator transcripts for `unverified|could not verify|not verified` returns mostly the
    coordinator's own briefs (every brief asks for the section, so the contract is being carried).
    The receipts themselves report very little: 208's unit answered *"**Unverified** — none. Every
    claim is grounded in the shipped source: `vscode-desktop/extension.ts` (`runShareCheck` at
    1165-1182, `probeShare` 1189-1220, `openFiles` 1466-1490)"*. 198's is the interesting one — the
    unit **refused its own brief's over-claim**: *"The brief said the shim's 'every emitted body is
    templated from goldens'. I did not write a universal … so I wrote 'whose emitted stream,
    transcript, status and hook bodies are templated from goldens captured off a real Claude Code
    by a committed, re-runnable capture script' — no 'every', no 'nothing is imagined'."* Same
    receipt, on the next claim: *"'no test skips itself for a missing `claude`' — **verified**, not
    assumed"*, with the three `t.Skip` sites and the `t.Fatal` that is not one.
12. **Sampled read, 199 and 202 — grounded.** `git show 03cfcbf9` and `git show 225214cd`, each
    quoted sentence checked against the file it describes.
    - 199, `controller/docs/state/reconcile-from-cluster.md`: *"Both `GET /environments/{envId}`
      and the `/state` stream that pushes the same snapshot raise it from one helper in `app.py`,
      because the stream's connect snapshot is this same `get`."*
      `controller/src/kubecoder_controller/app.py:115-133` is that one helper,
      `_unprojectable_problem`, whose own docstring reads *"Shared by the two `read` routes on the
      env resource — the single-env GET and its state stream, whose connect snapshot comes from
      the same `store.get`"*. Exact, down to the reason.
    - 202, `controller/docs/config/config-model.md`: *"each `file` must be a bare name (no `/`, and
      neither `""`, `.` nor `..`), and no two entries may repeat a `file` or a `catalogKey`. Every
      offence in the list accumulates into one message."* `config.py:768-802`: the validator tests
      `"/" in entry.file or entry.file in {"", ".", ".."}`, appends duplicate `file`/`catalogKey`
      offences, and raises `"; ".join(problems)`. Exact, including the accumulation.
    - A hedge count over the added lines of four new doc commits (03cfcbf9, 225214cd, 1b960f68,
      dd570e5d) against four corpus ones (3d266a9c, 8d0521bb, 4bededba, 1cd5e94f) —
      `typically|generally|usually|may be|might be|in general|roughly|appears to` — gives 2 in
      1 675 added lines (0.12 %) new against 3 in 1 607 (0.19 %) before. **No sign of the vaguer
      sentence.**

13. **Doc-related close-out entries are flat; doc-related operator fix-nows are down.** § 8 sends
    the reader to "§ 1's dispositions list" for the before-rate. **There is no such list** — § 1
    names three mechanism defects; the doc-disposition anecdotes are in § 7. Worse, the report
    post-dates most of the corpus: 144, 148 and 153 have no `close-out.md` (their findings are
    per-card rows in `state.json`) and 146's is the first ever written, empty of entries. The
    baseline is therefore **154, 158, 170**, the only 144–170 slices whose reports carry ids,
    Consequence lines and dispositions.

    | | slices | entries | doc-related | per slice | slices with an operator fix-now on docs | fix-nows |
    |---|--:|--:|--:|--:|--:|--:|
    | new | 7 (198–212) | 105 | 44 | 6.3 | 3 of 7 (199, 201, 202) | **9** |
    | baseline | 3 (154, 158, 170) | 70 | 31 | 10.3 | 2 of 3 (158, 170) | **10** |

    Doc-related volume per slice is *lower*, on a baseline skewed to big slices (154 is a residual
    sweep, 170 the 12-phase one); fix-nows are 1.3 per slice against 3.3. Neither series is clean
    enough to carry weight alone; what they rule out is a rise, which is the kill limb. Most of
    both eras' doc-related entries are **in-source comments** caught by a reviewer or the
    completion consult and closed by its residue commit (new: 200 ×5, 202 ×4, 198 ×2; baseline:
    154 ×10, 170 ×5) — the class 0.9.14's KubeCoder companion newly *named*, present before it was.

    What the new era adds is the doc phase **reporting what it may not edit**: 202 B1/B2, 212 S10
    and 200 S6/S9 are `docs/api/*.md` claims the coordinator checked and found **false**, not
    unverifiable. 202 B1 needed a whole appended phase, and its disposition closes § 7's
    `api/*.md` question project-side — *"change-discipline.md:57-62 puts the `docs/api/*.md`
    correction on the implementing phase and bars the doc phase"*. 201 S13 is the same reflex.

    **Pages the doc model has no home for: none, in either era** — the nearest two outgrew the
    model's own split rule (199 S12, 212 S11), a doc-model finding rather than a homeless surface.
    And the phase keeps *pre-empting* entries: 201's S9, S10, S12 and 200's S16 are struck
    "already resolved in the run — the slice's own doc phase". The corpus did this too (170
    B20/B21): not new, not lost.

## 4. The two failed first rounds

From each slice's `log.txt` and the two dead sessions' transcripts.

14. **Both are the same failure, and it is the harness's, not the contract's** — the coordinator
    ends a turn with sub-agents in flight, exactly as `doc-writer.md` tells it to; KubeCoder's
    headless engine counts a completion delivered when its notification arrives, so one that
    lands while the coordinator is mid-turn is queued for a next turn that never comes once the
    coordinator ends that turn to wait for it — the send resolves, the queued report dies with
    the process, and the driver's nudge resumes a session whose first turn is the CLI's
    stopped-task bookkeeping, not a model turn (KubeCoder #840; the transcript read is on
    AIWorkflow #816).
    - **201**, 19:55–20:01. The coordinator dispatched four scope surveys in one turn (t19) and
      ended its turn at 2m57s. The harness *did* resume it on each report — three further turns at
      5m09s, 5m22s, 5m44s, each one "survey in, waiting on the rest", each correctly ending the
      turn again. The fourth (worker/bot/mcp, the largest) finished thirteen seconds *before* that
      last turn ended — its report was queued, never delivered; the driver's nudge at 20:01:08
      resumed the session into the CLI's stopped-task notice, returned in 13 ms with nothing, and
      the phase was declared `blocked`. Cost: coordinator $1.95 (23 turns, no edit at all) + surveys $2.41 = **$4.36**.
    - **200**, 22:36–22:52. The same coordinator yielded correctly through all four surveys, wrote
      `units.json` (t21) and dispatched four units (t23–t26), then ended its turn at 14m36s with
      all four in flight. The send resolved with the four units still running — the same pending-task
      accounting, noted on #840 — the driver nudged at 22:52:39, got `Done (12 ms)`, and bailed
      `protocol_failure` — *"doc-writer left uncommitted changes in /work/KubeCoder after a commit
      nudge"*: the orphaned units went on editing the tree after their coordinator was gone. Cost:
      coordinator $3.50 + surveys $2.91 + units $3.84 = **$10.25**.
15. **$14.61 wasted, 10 % of the seven slices' doc-phase spend** — 33 % of 200's doc phase and
    14 % of 201's. Neither slice reused anything from the dead round: the replacement
    coordinator re-surveyed and re-dispatched from scratch (200: 4 surveys + 5 units again; 201: 6
    surveys + 6 units). The fan-out is what makes the window wide — the more sub-agents in flight,
    the likelier one completes while the coordinator is mid-turn on another's report. Dev 0.9.26
    re-sends a nudge the harness swallowed, which recovers 201's shape; the engine fix is #840.

## Against § 8

| criterion | verdict |
|---|---|
| wall-clock (not a § 8 criterion, asked by the operator) | **Slower:** 26 minutes median against 14.5; 5.0 minutes per phase against 3.9 (finding 6a). |
| doc-phase $ and share of slice | **Missed on the absolute.** $18.41 median against $8.89, 23.9 % of the slice against 16.1 %; per phase of shipped work +15–25 %, for 60 % more doc lines (finding 7). The plan's honest expectation was −25–35 %; the outturn is +110 % absolute. |
| coordinator `ctx_max` < 150 k | **Missed, 1 of 7** (208 only). Median 207.7 k against the corpus's 196.0 k — unchanged. `ctx_fe` *is* down 18 k, so orientation is bounded; the tail is not. |
| units' turns and $ vs the 8–10-turn break-even | **Met, and the test turns out not to bind.** Every unit runs 23–60 turns for 3–11 pages, three-to-six times the break-even — yet costs $1.15–3.43, not $0.35–0.60. A unit is a second writer, not a chunk. |
| the Explore carry gone (overlap ≈ 0) | **Met.** Every survey report lands before the coordinator's first edit, in all seven sessions that reached `units.json`. Nothing re-derived, nothing carried. |
| reconcile pass's own findings per slice (zero = not looking) | **Met, 7 of 7 non-zero**, median 9 post-dispatch edit turns, and the finds are the cross-scope class a single session had no reason to look for (200's two orphan counts, 201's fact in three places, 199's D248 citations). |
| units' unverified-claim receipts | **Met.** Few, and they cut toward precision — 198's unit refused its brief's "every emitted body" universal and wrote the enumerated sentence instead; 208's reported "Unverified — none" with file:line for each claim. |
| doc-related Bugs / operator fix-nows vs the current rate | **Met, with a caveat about the baseline.** Fix-nows on docs: 9 over 7 slices (1.3 each) against 10 over 3 (3.3). Doc-related entries 6.3 per slice against 10.3. § 8's stated comparator — "§ 1's dispositions list" — does not exist, and only three corpus slices have a close-out with dispositions. |
| sampled read of two slices' docs | **Met.** 199's reconcile-from-cluster sentence and 202's `kubeconfigs` validator sentence each match the source exactly, including the accumulation semantics; hedge words are 0.12 % of added lines against 0.19 % before. |
| **Kill rule** — fix-nows rise, or units write the vaguer sentence | **Not triggered, on either limb.** |

## Recommendation

**Keep the rework, with one named change: bound the survey stage.** The headline number is a
doubling, but the denominator moved further — 2.8x the pages committed at 2.1x the cost, so the
doc phase is now *cheaper per page* than the one it replaced ($0.69–0.80 against $0.85) and
about 20 % dearer per phase of shipped work, for 60 % more doc lines, while buying the
cross-scope reconcile that no single session was doing, with no loss of grounding on
any of § 8's four quality probes; roll-back would give up the reconcile and the recovered Explore
spend to save a phase that is not, per page, more expensive. The one place the evidence points at
waste inside the phase is the survey fan-out: it grew from the corpus's 1–2 Explore agents at
$1.04–1.56 to 2–6 at $2.61 median (up to $6.87 on 200) *after* § 3's digest and diff files had
already taken 18 k off the coordinator's `ctx_fe`, it is dispatched across up to six separate
turns rather than one, and every extra agent widens the window in which the driver's nudge lands
on a coordinator still waiting (§ 4, the $14.61 the engine race cost these seven slices) — so
cap it, and require the whole fan-out in a single dispatch turn.

Two changes this read does **not** support. **Fewer units, merged below N pages**: pages per unit
is already 3–11 (median 7.25), well clear of the 3-page floor, and the arm with more units is the
cheaper one — 199 ran 5 units over 24 pages at $0.61 a file, 198 ran 2 over 22 at $0.69.
**Sonnet units**: § 5 deferred that until "the receipts show units doing little more than
transcribing the brief", and the receipts show the opposite — 198's unit read the brief's
universal, went to the source, and wrote a narrower true sentence.

One note for the operator's still-open § 7 item 4, **stop carrying counts**: the split gives that
item a new argument. A count that spans scopes now has no owner, so it falls through to the
reconcile pass by default — 200's two stale counts *"no unit owned"*, 198's eight-built /
seven-promoted reconciliation across both scopes, 202's five-to-seven validator table and its
re-derived 55/44/11, 212's D240 gate enumeration. Counted inventories were whole-slice work
before; under the split they are the coordinator's residue, and they are named in five of seven
verdicts.
