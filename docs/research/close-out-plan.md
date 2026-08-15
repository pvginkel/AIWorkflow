# C7 Implementation Plan — The Close-out Report

Companion to [close-out-report.md](close-out-report.md) (the design and the decisions — read it
first; this plan does not restate the why) and [status.md](status.md) C7. Written 2026-08-15 at
plugin 0.4.5, before implementation. Line numbers cite 0.4.5 and are where to look, not proof.

**Implemented 2026-08-15 as plugin 0.5.0** (status.md C7 has the log line). Where the build
departed from the text below: `init_report` returns `bool` (created or not) rather than the
path — the loops need exactly that to decide whether to commit; the driver also stamps the
header itself when the run completes, and `/dev:run-slice` re-stamps after the cost block lands
(idempotent); the consult carry-over line and the `CONSULT_PROMPT` pointer are one line in the
prompt, not two; the driver's refutation and merge entries quote the reviewer's finding
summaries (from the history row) so they stand alone; the doc-writer's last-act instruction
lives in its register only (conditioned on a `done` verdict), the `DOC_PHASE_PROMPT` carries the
path; the header says `0 bail-outs` when the state carries an empty list and omits the piece
only when the key is absent (a pre-0.5.0 state); headings inside fenced blocks are not headings
to `close_out.py`, so a quoted `## Bugs` moves nothing. §12's open decisions: 0.5.0; yes, blank
`Disposition:` on the driver's entries; no Summary/Focus pass on a `blocked`/`question` doc
phase.

---

## 1. The build in one paragraph

A new contract doc + template (`plugins/dev/docs/close-out.md`, `close-out-template.md`) define
the report; a new stdlib tool `plugins/dev/tools/close_out.py` creates it, appends the driver's
deterministic entries, and stamps the run header; both loops call it; every agent register loses
its `cards` field and gains one bounded line — out-of-scope observations go in the slice's
`close-out.md`, in the shape the file itself shows; `state.json["cards"]`, `_card()`, and the
per-finding filing in `/dev:run-slice` Job 4 go away, replaced by one close-out card per slice;
a small `close-out` skill walks the report with the operator; `/dev:triage` names the report as
a source. One version, one changelog entry.

---

## 2. New files

### `plugins/dev/docs/close-out-template.md`

The template exactly as close-out-report.md §4 gives it (skeleton, entry shape, struck-entry
form, header line), with a short preamble in the style of `plan-template.md:1-9`: what the file
is, that both loops create it, that the shape is what agents read off the file itself. The
template body is what `close_out.py init` copies — keep it a fenced block the tool can lift, or
keep the copyable body in a sibling file the doc embeds; either way one source.

### `plugins/dev/docs/close-out.md`

The contract — short, claims stated once, everything else points here:

- what the report is and is not (design §3.1, verbatim in spirit: out of the loops' scope only;
  not a scratchpad; a `question` verdict pauses, an entry never does);
- the sections and what belongs in each (§3.2), the reading aids (§3.3);
- who writes what, when — plan agents, code-writer, code-reviewer (advisories as entries; the
  review file stays the record), consults (completion consult reconciles: strike/merge/mark),
  test-agent, doc-writer (Summary + Focus lines as its last act), driver (refutations,
  funding-consult merges, header) (§3.4);
- append-only for phase agents; reading the report is never a license to act on it;
- the entry rules (§5): write for a reader who has only this document, quote liberally, no limit
  on prose or count, in doubt add it, severity vocabulary, `Disposition:` is the operator's;
- lifecycle (§3.5): created at plan start, live-committed, one close-out card at Job 4,
  operator dispositions, the `close-out` skill executes, triage reads what remains.

`run-loop.md`, `plan-loop.md`, `runner-state.md`, the agents and the skills point at this doc
rather than restating it.

### `plugins/dev/tools/close_out.py` (+ `test_close_out.py`)

Stdlib. Importable by both loops the way `plan_loop.py:60-67` imports `run_loop`
(`sys.path.insert(0, tools_dir)`), and a CLI for the skills:

- `init_report(slice_dir) -> Path` / `close_out.py init <slice_dir>` — create `close-out.md`
  from the template if absent, substituting the slice's `NNN <slug>` in the title; idempotent
  (an existing file is never touched); prints the path.
- `append_entry(slice_dir, section, headline, body, provenance=None, severity=None) -> str` /
  `close_out.py append <slice_dir> --section <name> --headline … --body … [--provenance …]` —
  finds the section by heading, allocates the next id from the section's letter (count existing
  `### <L><n>` headings incl. struck), appends the entry in the standard shape with a blank
  `Disposition:` line, returns the id. Used in-process by the driver; the CLI exists so a skill
  session can add an entry without hand-editing.
- `stamp_header(slice_dir) -> str` / `close_out.py stamp <slice_dir>` — replaces the
  `Run: …` line with the header from `state.json`: run window (`created_at` → `updated_at`),
  phases merged and how many were appended (see §3 `bailouts`/`appended` fields), bail-outs,
  test rounds, doc phase outcome, and the `cost` block if `slice_cost.py --write-state` has run
  (`cost_usd`, `planner_share`, `research_share`, `rework_share`). Missing pieces are omitted, not
  guessed. Idempotent — re-stamping overwrites the same line.
- `entry_counts(slice_dir) -> dict[str, int]` — per section, non-struck entries; for the driver's
  `_summary` and the close-out card body.

Deliberately not in the tool: any format validation beyond "the section heading exists"
(operator: don't go overboard), dedup, disposition parsing.

Tests (`test_close_out.py`, stdlib `__main__` runner + pytest like the siblings): init creates and
never overwrites; append allocates ids per section and survives a struck heading; append into a
missing section raises; stamp with and without `cost`, with zero bail-outs, re-stamp is stable;
counts ignore struck entries.

### `plugins/dev/skills/close-out/SKILL.md`

Frontmatter `name: close-out`, `argument-hint: "[slice number or slice dir]"`, and a
`description` that is the trigger — say *when*: the operator opens, discusses, pastes from, or
wants to work through a slice's `close-out.md`; the session invokes it itself in that case; the
operator will not necessarily name it. Not `disable-model-invocation`.

Procedure (numbered, short):

1. Locate the report: the argument, else the newest `slices/**/close-out.md` under the spec repo
   (`Spec repo:` line in `CLAUDE.md`) that still has a blank `Disposition:`.
2. Read it whole. Present the Summary, the Focus lines, and every entry's id + headline. Ask
   nothing yet — the operator reads.
3. Take dispositions — the operator writes them in the file, or says them ("card B1, close B6,
   fold S1 into 009"); write chat dispositions into the file under the entries **in the
   operator's words**, never paraphrased.
4. Execute each: `card [board]` → one tracker card per entry, body = the entry verbatim + its
   Provenance line + the report path (host convention for boards/lists); `fix now` → do it here
   if the project's `CLAUDE.md` classes it as ad hoc work, else say so and offer `fold into`;
   `fold into <slice>` → append the entry verbatim as an ask to that slice's `slice.md`
   (backlog), or a new triage item if the slice does not exist; `close` → strike the heading with
   the reason; `defer` → leave it, it is triage's.
5. Commit the report (stage by name; the spec repo is a shared tree); when no blank
   `Disposition:` remains, archive the slice's close-out card. Report short: counts by
   disposition, cards filed, anything owed.

Bounds: never edit an operator's words; never re-derive an entry's claim (the run's records are
in the slice folder if the operator wants to look); this session files and edits, it does not
plan or design — that is `/dev:triage` → `/dev:plan-slice`.

---

## 3. `run_loop.py`

- **State** (`~2760`): drop `"cards": []`; add `"bailouts": []` — `_bail` appends
  `{reason, phase, ts}` before writing `bailout.json` (the file is unlinked on resume at `~2773`,
  which is why the count needs a home). Record which phases were appended: the completion consult
  and test phase already know when they append — record `appended_phases` (phase ids) when the
  driver detects new phase headings after an `appended`/`findings` verdict (it re-parses the plan
  there already). `runner-state.md` documents both.
- **Init** — at state init call `init_report(self.slice_dir)`; on `--resume` too (idempotent —
  runs started on 0.4.5 get a report mid-run rather than none).
- **`_card()`** (`1223-1230`) and its call in `_spawn` (`1659-1660`): delete. Verdicts keep
  parsing if a `cards` key is present (ignored, one log line) — no protocol failure on an
  installed-plugin lag.
- **Consult carry-over** (`1710-1718`) "Already carded this run — settled, do not re-report":
  replace with one line naming the report path: read it before writing; add if in doubt.
- **`CONSULT_PROMPT`** (`1108-1111`): drop `cards` from the verdict JSON; add the report path
  as a pointer line ("out-of-scope findings and sub-bar leftovers go in {report_path}").
- **`COMPLETION_CONSULT_SITUATION`** (`958-975`): "Record everything that does not clear the bar
  in your verdict's `cards` list" → "…as entries in {report_path}; you are the one pass that
  reconciles it: strike what you absorbed into an appended phase (name the phase), merge
  duplicates you are sure of, mark what a phase resolved."
- **`GENERATION_BARS`** (`932-945`): "goes to cards, never phases" / "Everything else goes to
  cards" → "goes in the close-out report, never phases". **`GENERATION_RIDER`** (`947-956`):
  keep the rule; reword the comment and text from "carded" to "reported"; drop the "a card costs
  the operator a triage pass" justification (fix-in-place stands on its own).
- **`TEST_PHASE_PROMPT`** (`1028-1052`): "goes in your verdict's `cards` list" → "goes in
  {report_path}"; the report path rides the deterministic-facts block.
- **`DOC_PHASE_PROMPT`** (`~1056`): add the report path and the last-act instruction: write the
  Summary and each section's Focus line before handing back (the contract doc holds the rule; the
  prompt carries the pointer).
- **`EXECUTOR_*` prompts**: every executor dispatch (initial, gate-fix, review-fix) gets the
  report path in its bookkeeping/pointer block. **`EXECUTOR_REVIEW_FIX_PROMPT`** (`763-766`):
  "the loop cards them at close-out and the residue rider mops up the mechanical ones" → "they
  stay in the review file and the close-out report; the residue rider mops up the mechanical
  ones". **`REFUTATION_TAG`** (`784`): "carded for the operator with the refutation attached" →
  "recorded in the close-out report with the refutation attached". Review-delta prompt (`833`):
  "the loop cards them at close-out" → "they are in the review file and the close-out report".
- **`REVIEW_BAR_*`** (`873-928`), **`REVIEW_FUNDING_SITUATION`**, **`REVIEW_BUDGET_SITUATION`**:
  "carded" → "go to the close-out report" (they never fund fix rounds — unchanged).
- **`_handle_refutations`** (`2137-2164`): instead of `self._card(...)`, one
  `append_entry(section="Notable events", headline=f"Fix round after review r{n} of P{id} refuted
  {fid}", body=<the evidence line + review file>, provenance=f"code-writer P{id} r{n}")` per
  refuted finding.
- **`_review_funding_consult`** (`2202-2240`) merge branch: `append_entry("Notable events",
  headline=f"P{id} merged with unresolved review findings after r{n}", body=<consult summary +
  review path>, provenance="consult")`.
- **`_summary`** (`2850-2868`): replace the cards lines with `entry_counts` — "close-out report:
  A a · N n · B b · Q q · S s".
- **Reviewer dispatch**: the report path in the reviewer's pointer block (it appends its
  advisory findings as entries — the register says so; the prompt only carries the path).

Tests (`test_run_loop.py`): `test_review_funding_consult_merges_and_cards` (`529`) and
`test_all_blocking_refuted_without_code_change_settles_review` (`668`) assert on the report file
instead of `state["cards"]`; `test_later_consults_see_the_carded_list` (`1237`) becomes "later
consults get the report path"; `test_test_phase_cards_ride_the_verdict` (`1299`) becomes "a
`cards` key is ignored"; state fixtures at `964`, `1165`, `1739`, `1954`, `1984` drop `cards`;
new: init creates the report at run start and on resume; `bailouts` recorded; `appended_phases`
recorded; `_summary` counts.

## 4. `plan_loop.py`

- `_init_state` (`509-523`): call `init_report(self.slice_dir)` — the plan loop is the first to
  run, so the report exists before the first writer pass. Nothing else in the loop changes.
- Writer and reviewer dispatch prompts get the report path as a pointer line.
- Test: init creates the report; a rerun leaves an existing one alone.

## 5. Agent registers (one bounded line each; the contract doc carries the rules)

- `agents/code-writer.md` (`58-72`): drop `cards` from the verdict; add a bound: "Anything out
  of your phase's scope you notice — a bug you will not fix, an operator action, a question the
  run does not need answered, an idea — goes in the slice's `close-out.md` (path in your dispatch;
  the shape is in the file). Append only; do not act on what is already there."
- `agents/code-reviewer.md` (`62-90`): "advisory findings of any severity ride along as cards"
  → "…are also entered in the slice's `close-out.md` (Bugs or Suggestions), by you, in its shape;
  the review file stays the full record". Rule 9 (may edit the plan doc only to record a settled
  fact) gains "and `close-out.md`, append only". Rule 2 (describe the problem, never the fix)
  gains: "in the review file; the report's Suggestions section is where a fix idea may go".
- `agents/test-agent.md` (`24-30`): rule 4 "everything else goes in your verdict's `cards`
  list" → "…goes in the slice's `close-out.md`"; rule 5 drop "No fix proposals." (proposals go
  under Suggestions; findings entries stay evidence-shaped). Verdict (`45`) drops `cards`.
- `agents/doc-writer.md` (`38-48`): verdict drops `cards`; bounds gain: doc debt goes in the
  report; as your last act write the report's Summary and each section's Focus line (rule in the
  contract doc).
- `agents/plan-writer.md`, `agents/plan-reviewer.md`: one line each — out-of-scope observations
  about the spec or estate go in the slice's `close-out.md`; in-scope questions and findings keep
  their current route (unchanged).

## 6. Contract docs

- `docs/run-loop.md`: `79-80`, `83-85`, `91`, `121`, `138-145` — "carded" → the report; delete
  the sentence "A card must never cost the operator more to triage than the fix costs to make.";
  the close-out paragraph points at `close-out.md` for the report and says the driver stamps the
  header and the launching session files one card.
- `docs/plan-loop.md`: a short paragraph — the loop creates the report at first dispatch;
  planning agents write out-of-scope observations to it; nothing in-scope moves there.
- `docs/runner-state.md` (`46-50`): the `cards` paragraph → `close-out.md` (created by the
  loops, agent-written, driver-stamped), plus the new `bailouts` and `appended_phases` fields.
- `docs/residual-sweep.md` (`20-22`): the qualifying items are now cards the operator filed at
  disposition from close-out reports; the sweep still consumes tracker cards — wording only.
- `docs/agent-dispatch.md`: no change unless it lists the verdict fields somewhere (check).

## 7. Skills

- `skills/run-slice/SKILL.md` Job 4 (`60-77`): 1 `slice_cost.py --write-state`; 2
  `close_out.py stamp <slice_dir>`; 3 `close_slice.py`; commit together with the slice artifacts;
  4 file **one** card `[NNN] close-out: <slice title>` in the intake queue — body: the report's
  Summary, the six Focus lines, `entry_counts`, and the report's path (spec repo path form);
  5 advance the tracker card to done, notify, report short (per-phase rounds, test/doc outcomes,
  the entry counts, anything owed). The dedupe / one-per-finding / residuals rules are deleted.
- `skills/triage/SKILL.md` step 1 (`~39-46`): sources gain "a slice's `close-out.md` — entries
  whose `Disposition:` is blank or `defer`, one item per entry, the entry verbatim as the
  source". Nothing else changes; the 0.4.4 filtering keeps its role.
- `skills/close-out/SKILL.md`: new (§2).

## 8. Version, changelog, research board

- `plugins/dev/.claude-plugin/plugin.json`: **0.5.0** proposed — a contract change touching every
  agent, both loops, two skills, and a dropped state field; operator's call at implementation.
- `CHANGELOG-workflow.md`: newest-first entry in the house voice, naming the design note.
- `docs/research/status.md` C7 → **validating**, log line naming the version and the first slice
  it runs on; I4 and C6 get a log line each ("C7 moves the queue off the board; I4 reframes as
  entries/dispositions per report").
- Push + marketplace update, with the operator's confirmation — the loops run the installed clone.

---

## 9. Measurement (design §7)

Per slice from the report and the state: entry counts by section (`entry_counts`), dispositions
by kind (the close-out session tallies at step 5), cards filed at disposition, appended phases at
generation 1 (`appended_phases`), rework share (I2's `cost.rework_share`), bail-outs. Baselines
recorded in the design note: 007 (11 entries, 10 cards, 3 appended, rework 13.8 %), KubeCoder
117/135/107 (24/17/16 entries), the 149–153 rework band 9.3–15.7 %. Read after a handful of
slices; log per entry in status.md as the 0.4.3 batch was.

## 10. Deliberately out of scope

- Automated triage over the report (the end game; the shape should not need to change for it).
- Any validator beyond "section headings exist"; dedup tooling; disposition parsing.
- Changing the review file, the generation bars, the residue rider, or any B/C rule under
  measurement.
- Back-filling reports for completed slices; old `state.json["cards"]` lists stay as history
  (`slice_cost.py` does not read them).
- Sub-agent registers (`test-fixer`, `rebase-agent`, research sub-agents): they hand conclusions
  to their dispatcher, which writes the report.

## 11. Files touched

- `plugins/dev/docs/close-out.md` — new contract doc (S)
- `plugins/dev/docs/close-out-template.md` — new template (S)
- `plugins/dev/tools/close_out.py`, `test_close_out.py` — new (M)
- `plugins/dev/tools/run_loop.py`, `test_run_loop.py` — §3 (M)
- `plugins/dev/tools/plan_loop.py`, `test_plan_loop.py` — §4 (S)
- `plugins/dev/agents/{code-writer,code-reviewer,test-agent,doc-writer,plan-writer,plan-reviewer}.md` — §5 (S each)
- `plugins/dev/docs/{run-loop,plan-loop,runner-state,residual-sweep}.md` — §6 (S)
- `plugins/dev/skills/run-slice/SKILL.md`, `skills/triage/SKILL.md` — §7 (S)
- `plugins/dev/skills/close-out/SKILL.md` — new (S)
- `plugins/dev/.claude-plugin/plugin.json`, `CHANGELOG-workflow.md` — §8 (S)
- `docs/research/status.md` (C7, I4, C6 log lines) — §8 (S)

## 12. Open decisions at implementation time

- Version number (0.5.0 vs 0.4.6).
- Whether the driver's deterministic entries carry a `Disposition:` line (uniformity says yes;
  the operator rarely has one for them — the assessment's pick is yes, blank is fine).
- Whether the doc-writer's Summary/Focus pass should also run when the doc phase reports
  `blocked`/`question` (pick: no — the operator reads it raw; the run bailed anyway).
