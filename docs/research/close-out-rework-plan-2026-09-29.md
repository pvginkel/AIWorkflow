# The close-out report, reworked — plan (2026-09-29)

Companion to [close-out-read-2026-09-28.md](close-out-read-2026-09-28.md) (the evidence; this
plan does not restate it). The operator's ruling on that read: "I like the changes that are
suggested here, and I would like this session to actually deliver them." And one request on top
of it:

> If we do this, I think the format of the close out report should change also. It goes from
> important -> not important -> important -> not important -> important, etc. A's, N's, major
> B's, minor B's, nit B's, and then S's are just unsorted. Can you also design a more radical
> rework of the close out report so that it structures the information better?

**Status: for the operator's ruling.** Nothing in the plugin changed. § 4 has the four decisions
that are the operator's; every one has a default, so "go" builds the plan as written.

**The plan in short.**

1. **The report is ordered by what the operator has to do with an entry, not by what kind of
   thing the entry is.** What they act on or decide leads, in full. What one line settles
   follows, body folded. The record — what the run settled itself, and its events without a
   consequence — comes last. An entry's kind stays on its id (`B3`, `S7`) and its grade on its
   heading (§ 2).
2. **Every live entry carries a proposed disposition**, written by one agent — the sorter — on a
   line of its own above the operator's. The sheet at the head of the report is those lines,
   collected by the tool. A proposal closes nothing (§ 2.4).
3. **The sorter has two callers and one set of rules.** `/dev:close-out` dispatches it when it
   opens a report that is not sorted (R1); the run loop dispatches it when the run completes
   (R4). The rules are the ones the read replayed (§ 2.4, § 3).
4. **Whoever fixes an entry strikes it, and a pass that went right is not an event** (R2, R3),
   unchanged from the read. The Focus lines go: the sheet does what they were for (§ 3, D2).
5. **Three versions, built in this order**: 0.9.56 the two author-side rules, 0.9.57 the new
   shape with the sorter and the skill, 0.9.58 the sort at the end of the run (§ 5).

## 1. What the rework answers — today's order is inverted

`close_out_readout.py order` places every entry of a report in reading order and asks where the
ones the operator progressed (carded, fixed, folded) sit. 84 reports with at least four entries
ruled; the 30 held-out reports of the read carry its replayed sort.

| reading order | reports | 1st fifth | 2nd | 3rd | 4th | 5th | picks in the first third | in the last third |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| today's (`render`) | 84 | 26 % | 31 % | 38 % | 40 % | 44 % | 25 % | 39 % |
| mechanical — severity across kinds | 84 | 44 % | 43 % | 42 % | 30 % | 22 % | 38 % | 23 % |
| today's, held-out | 30 | 25 % | 20 % | 28 % | 34 % | 39 % | 25 % | 42 % |
| mechanical, held-out | 30 | 39 % | 38 % | 30 % | 21 % | 19 % | 43 % | 21 % |
| sorted by the revised rules, held-out | 30 | 37 % | 43 % | 44 % | 10 % | 10 % | 46 % | 10 % |

The five middle columns are the progressed share of the entries ruled, per fifth of the report's
words.

1. **The report gets more important as it goes on.** The first fifth is progressed at 26 %, the
   last at 44 %. Notable events (6 % progressed) stand second in the file and Suggestions (40 %)
   last, unsorted; four in ten of the operator's picks start in the last third.
2. **Severity alone turns it around.** 420 of the 522 Suggestions ruled carry a grade that
   `render` does not read — it sorts Bugs only. Ordered by grade across kinds, with the run's
   events last, the first fifth is progressed at 44 % and the last at 22 %. No model is needed
   for that.
3. **The sort cuts the report in two.** In bucket order the first three fifths are progressed at
   37–44 % and the last two at 10 %: the operator can stop reading where the sheet says so.
   The sort does not rank inside the first part, and is not meant to — its buckets say what is
   asked of the operator, which is the order they work in.

## 2. The design

### 2.1 Four rules

- **One reading order, falling.** Position says what is asked of the operator: act, decide,
  confirm, glance, nothing.
- **Kind is a property, not a place.** Action, event, bug, question, suggestion: the id's
  letter. The five kind sections leave the file.
- **The sorter proposes, the operator disposes.** A proposal is a line on the entry. Nothing is
  struck, filed or fixed on it — the constraint of 2026-08-17, kept.
- **Judgment in one agent, everything else in the tool.** The sorter writes a bucket and a
  why-clause per entry. Order, sheet, folds, counts and the card's body are `render`'s, from
  those lines, and a report nobody sorted still gets the mechanical order of § 1.

### 2.2 The file

```markdown
# Close-out — slice NNN <slug>

Run: <stamped by the driver>

<!-- head comment: the tool that writes here, the five kinds, the labels -->

## Summary            the doc-writer's: the slice and what shipped

## Sheet              render's: every live entry on one line under its bucket, with the counts

## Unsorted           entries without a proposal — all of them before the sort, late ones after

## Your actions       ┐
## Needs your eyes    │ read in full
## Card               ┘

## Fix now            ┐
## Fold               │
## Test gaps          │ one line each — body folded; heading, Consequence, proposal
## Close              │ and Disposition stay in view
## Already done       ┘

## Record             the run's events without a consequence, as headlines;
                      then what was struck — in the run or on the operator's ruling — folded
```

`render` writes the sections that hold something and leaves out the rest, except Summary and
Sheet. Inside a bucket the order is grade (major, minor, ungraded, nit, cosmetic), then kind,
then id. A report that was never sorted has everything live under Unsorted, in that same
mechanical order with the actions first.

The sheet, as `render` writes it and `close_out.py sheet` prints it:

```markdown
## Sheet

Sorted 2026-09-29 from the report alone. A proposal is not a ruling: nothing here is closed,
filed or fixed until you say so.

12 live: 3 actions · 2 need your eyes · 1 card · 1 fix now · 1 fold · 2 test gaps · 2 close.
1 event of the run without a consequence is in the record.

**Your actions (3)** — one card in your action queue
- A1 — Deploy both repos in order, then confirm the projection live — owed before the slice holds
- …

**Needs your eyes (2)**
- S6 — worker: the preamble asserts `~/.kube/config` is the default · minor — the entry cannot
  say how many deployments name the file otherwise
- …
```

### 2.3 The entry

One label more, the sorter's, above the operator's:

```markdown
### S11 — controller: the catalog-presence gate is reachable only through … · nit

<details><summary>body</summary>

<the body, its dated notes included>

</details>

**Consequence:** None to an operator; a reader of V02 may take it for a live path.
**Provenance:** read — code-reviewer, P3 r1
**Proposed:** close — true, without effect today, and the entry names no one-edit fix
**Disposition:**
```

The fold is `render`'s, put on in the five one-line buckets and taken off when an entry moves to
a bucket that is read in full. The `Disposition:` line goes back to holding the operator's words
and what was done; the "suggested …" the skill writes there since 0.9.38 is the `Proposed:`
line now.

### 2.4 The sort

**One agent, `dev:close-out-sorter`**, on Opus, pinned in its definition: a session on another
model that dispatches it must not move it there. Its input is the report and nothing else — the
arm the read replayed. It proposes for every live entry that has no proposal, in one call
(`close_out.py propose`), and hands back a verdict when the driver dispatched it, a receipt when
the skill did.

**Its rules are the appendix of the read**, reworded for an agent definition, in the order that
was tested — the first bucket that fits: already done · action · fold · fix now · test gap ·
card · needs your eyes · close. That is the order of precedence. The order of reading is
§ 2.2's.

**Two callers.**

- *The skill (R1).* `/dev:close-out` opens the report; if it holds live entries without a
  proposal, it dispatches the sorter; then it makes the check no run-end step can make — what
  has moved since the run (finding 12 of the read: 74 entries in 30 sessions) — and re-proposes
  what it found as `already done`, naming the commit. It renders, presents the sheet, waits.
  The operator rules in one message. "Go" is every proposal as proposed; the needs-your-eyes
  set takes a word each; an amendment wins over the sheet; the test gaps are closed as a group
  unless the operator says to card them, as one card. The entry-by-entry way needs no procedure
  of its own: naming entries is ruling them.
- *The driver (R4).* After the doc phase and before the final render and stamp, the run loop
  dispatches the same agent. It never fails the run: a timeout, a missing verdict or a `blocked`
  is logged, the report keeps the mechanical order, and the skill sorts when it opens.
  `/dev:run-slice` puts the sheet in the close-out card's body in place of the Focus lines, so
  the card says what is waiting before a session is opened.

### 2.5 Without a sort

A run that stops before its end, a sorter that failed, a report written by an older plugin:
`render` orders mechanically — actions, then grade across kinds, the run's events last — and
moves the events whose `Consequence:` opens with "none" to the record, as headlines (R3). That
order needs no judgment and is the second row of § 1's table.

### 2.6 The tool

`close_out.py` stays the only pen. What changes:

| verb | change |
|---|---|
| `append` | `--kind` names one of the five kinds (`--section` and the five section names stay accepted); the entry lands under Unsorted; the id is the next number of its letter in the whole file |
| `propose` | new — reads `<id> \| <bucket> \| <why>` lines from stdin, checks every id and bucket before it writes any, sets or replaces each entry's `**Proposed:**` line |
| `sheet` | new — prints the sheet |
| `render` | the layout of § 2.2: buckets, folds, the record, the sheet; idempotent; reads a report in either layout |
| `list` | unchanged in content, grouped by kind whatever the file's layout — it is what an agent reads before it appends |
| `counts` | the per-kind line as it is, plus the number of live entries without a proposal |
| `strike`, `note`, `stamp`, `init` | find an entry by id anywhere in the file; `init` lifts the new skeleton |

The importable functions both loops use (`append_entry`, `live_entries`, `find_by_headline`) keep
taking the kind by its present name, so the pre-run action check and the plan loop's seeding do
not change.

### 2.7 Reports that exist

The 99 reports in the two spec repos are closed and nothing renders them again. A report still
open — a run in flight, the two Ansible reports not yet processed — is read in its old layout
and written in the new one at its next `render`: entries by id into the buckets, a written Focus
line carried under the Summary with its section's name before it, the section charters dropped.
The research tools that read reports by section (`close_out_readout.py`) learn the kind from the
id and record the `Proposed:` line, so the next read scores proposals against rulings from the
file itself.

### 2.8 Slice 202, before and after

Twelve live entries at hand-over; in brackets what the operator ruled.

```
today                                                         reworked
## Outstanding actions                                        ## Sheet   12 live: 3 actions · 2 need
  A1  deploy both repos, confirm live      [done]                        your eyes · 1 card · …
  A2  push the charts when the hold lifts  [done]             ## Your actions
  A3  push the product when the hold lifts [done]               A1, A2, A3                 [done]
## Notable events                                             ## Needs your eyes
  N1  test round 2 re-verified 19 criteria [closed]             S6 · minor                 [carded]
## Bugs                                                         S8 · minor                 [fixed]
## Open questions and rulings                                 ## Card
## Suggestions                                                  S3 · minor                 [carded]
  S1            gap 8 is closed by this    [fixed]            ── below: one line each ──
  S2            the gate design assumes…   [fixed]            ## Fix now
  S3  · minor   catalogKey and grant.name  [carded]             S1                         [fixed]
  S4  · minor   the route's key argument   [carded]           ## Fold
  S6  · minor   the default kubeconfig     [carded]             S2                         [fixed]
  S8  · minor   the dependency inventory   [fixed]            ## Test gaps
  S10           the chart's descriptions   [closed]             S4 · minor                 [carded]
  S11 · nit     the catalog-presence gate  [closed]             S10                        [closed]
                                                              ## Close
                                                                S11 · nit                  [closed]
                                                              ## Record
                                                                N1 — headline only         [closed]
```

The six entries the operator progressed all stand above S10 on the right, under the bucket that
says what is asked. On the left they share one heading with everything that is not an action or
an event, in order of arrival.

## 3. The four recommendations in this shape

| | in the read | in this plan |
|---|---|---|
| R1 | the skill sorts when it opens, prose only | the skill opens with the sheet and dispatches the sorter for what is not sorted; the check of what moved stays the session's |
| R2 | the doc-writer strikes what its own commit resolved whole; a partial fix keeps its note | unchanged |
| R3 | a clean pass is not an event | unchanged — the test-agent's register and the kind's charter |
| | a Notable event without a consequence shows as a headline | the record's rule in `render` (§ 2.5) |
| | `Focus: none` over an empty section | superseded — the Focus lines go (D2) |
| R4 | a sort at the end of the run, after R1 has run on some slices | the same agent, dispatched by the driver; built last, shipped with the rest (D3) |

What the read advised against stays out: nothing is closed on the sorter's word, the authors'
bar is not raised, the entry gets no label an author has to fill in, prose gets no cap.

## 4. Yours to rule

**D1 — Fold the bodies of the five one-line buckets.** *Default: yes.* Of the 375 entries of
the held-out reports, 102 are read in full, 238 are folded and 35 events go to the record. The
sheet and the bodies read in full are 42 % of today's words; with every folded entry's
Consequence line read as well, 54 %. The price is finding 17 of the read, made larger: on a
sheet the operator changes 4 % of the closes, on their own reading they progressed 22 % of what
the same sort would close — and a folded body is one more step away from their own reading. The
Consequence line staying in view is the guard. *The other way:* order only, fold nothing but the
record; the file is as long as today and the operator stops where they choose.

**D2 — The Focus lines go; the doc-writer keeps the Summary.** *Default: yes.* They name 78 %
of the entries handed over, only the first-named one carries signal, and 174 of 489 stand over an
empty section. This reverses a decision of 2026-08-15 ("the doc-writer writes Summary and Focus
lines"). What is lost is a ranking made with the shipped diff in view; the sorter has the report
alone.

**D3 — The sort at the end of the run ships with the rest.** *Default: yes.* The read put R4
after a trial of R1, so that the rules would be tested before anything was built on them. In
this design nothing is built on them: the rules are the sorter's definition, the driver only
dispatches it, and a sort that turns out wrong is wrong in the skill just the same. Holding R4
back saves a dispatch per run — a session that reads one file — and costs the card that says
what is waiting. *The other way:* build 0.9.58 after the readout of § 7.

**D4 — Your actions lead, then what needs your eyes, then the cards.** *Default: as written.*
The actions are the only entries the slice's outcome waits on. The skill's sheet has led with
needs-your-eyes since 0.9.38; say so if that should stay.

## 5. The build

Prose — agents, skill, contract docs, changelog — is this session's. Code goes to one Opus
sub-agent per version, briefed with the files and the commands below, its diff reviewed before
the commit. Versions are taken from `origin/main` at commit time; 0.9.55 is the last one taken.

### 0.9.56 — whoever fixes strikes; a clean pass is not an event (R2, R3)

- `agents/doc-writer.md` rule 10: strike what your own commit resolved whole, the reason naming
  the commit; what it resolved in part keeps a note and stays live.
- `agents/test-agent.md` rule 4: a round in which everything passed is not an event — the run
  header counts the rounds and the verdict says what ran.
- `docs/close-out.md`: the three passages that say only the completion consult strikes;
  `docs/close-out-template.md`: the head comment, the Notable events charter.
- `tools/run_loop.py`: the doc-writer's dispatch carries `strike` among its verbs;
  `docs/run-loop.md` follows; one test in `test_run_loop.py`.

### 0.9.57 — the report in reading order, the sorter, the skill (the rework, R1, D1, D2)

- `tools/close_out.py`, `test_close_out.py`: § 2.6 whole.
- `docs/close-out-template.md`, `docs/close-out.md`: rewritten around § 2 — the shape, the
  `Proposed:` line, who writes what, the lifecycle; "an automated triage pass" leaves
  *Deliberately absent* with its constraint stated as a rule.
- `agents/close-out-sorter.md`: new. `skills/close-out/SKILL.md`: rewritten around the sheet.
- `agents/doc-writer.md`, the doc phase's dispatch in `tools/run_loop.py`: no Focus lines.
- `skills/run-slice/SKILL.md` Job 4: the card's body is the sheet and the path.
- `docs/research/tools/close_out_readout.py`: both layouts, the `Proposed:` line.
- `README.md`, `CLAUDE.md`: eleven agents; `docs/rationale/reporting.md`: the rework and its
  evidence.

### 0.9.58 — the sort when the run completes (R4)

- `tools/run_loop.py`, `test_run_loop.py`: the role (model, timeout, verdict), the dispatch
  after the doc phase, a `sort` stage a resume re-enters, the soft failure of § 2.4.
- `docs/run-loop.md`, `docs/runner-state.md`, `docs/agent-dispatch.md` follow.

### Verification

- `kc project test` and `kc project lint` green at every commit.
- **The corpus through the new tool.** Each of the 99 hand-over snapshots, copied to a scratch
  directory: `propose` with the read's replayed buckets where it has them, `render`, `render`
  again. Asserted: every entry id that went in comes out once, no body lost a line, the second
  render changes nothing, `list` and `counts` agree with the old tool's on the same file.
- **The sorter against the replay.** The agent as defined, dispatched on the 30 held-out
  snapshots, scored by `close_out_readout.py score`: the share of the operator's picks it keeps
  should stand where the replay's did (89 %; 87 % on reports ruled by own reading). That is the
  test that the definition says what the replayed brief said.
- **One report end to end**, on a copy: the skill opened on an unprocessed report, the sheet
  presented, a ruling executed, the file rendered.

## 6. What it costs, and what can go wrong

- **A dispatch per run**: one session that reads one file, priced in the replay at roughly
  20 k tokens a report. `slice_cost.py` prices it as its own role.
- **A wait when the skill has to sort**: three to four minutes, for reports the run did not
  sort. With 0.9.58 that is the exception.
- **More inline edits on a "Go"**: the revised rules propose `fix now` for 20 % of the entries
  where the operator had 14 % fixed (finding 23).
- **Two plugin versions on one slice.** A report created from the new skeleton has no kind
  sections, and an older `close_out.py` cannot append to it. A slice planned on 0.9.57 must run
  on 0.9.57 or later; every environment updates its marketplace copy before its next slice.
- **The sorter is not the doc-writer and is not in the doc phase.** The ruling of 2026-09-05
  against hand-over stages stands: that measurement was a fresh session re-orienting on a
  repository from a brief. This one reads a report and nothing else.
- **What stays unmeasured**: whether a headline and a why-clause catch the operator's eye as the
  body did (§ 8 of the read). D1 rests on it.

## 7. The readout after

After ten reports sorted by the run and ruled by the operator, from the files alone
(`close_out_readout.py extract`, which by then reads the `Proposed:` line): proposals against
rulings per bucket, the entries pulled out of `close` and `already done`, the `fix now`
proposals the operator declined, the needs-your-eyes share of each sheet, and the sorter's
price per report. The numbers to hold it against are the held-out replay's (§ 6 of the read).

## 8. Not in the plan

- **Grouping in the tool.** "Entries that are one fix are one card" stays the sorter's
  why-clause ("one card with S4") and the session's act; `render` does not keep partners
  adjacent.
- **A per-project switch for the sort.** It is part of the report, not a phase a project runs
  or leaves out.
- **Rewriting closed reports.** The corpus stays as it was written.
- **Disposition parsing, dedup, validation of an entry's content** — absent as before. `propose`
  checks its own input, not the report.
