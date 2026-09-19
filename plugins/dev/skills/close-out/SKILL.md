---
name: close-out
description: Work through a slice's close-out report (close-out.md) with the operator — present it, take the operator's dispositions in their own words, and execute them (card / fix now / fold into a slice / close / defer); or, when the operator hands you the triage, sort the entries into proposed dispositions for one ruling. Invoke it yourself whenever the operator opens, discusses, pastes from, or wants to process a slice's close-out.md, or asks you to do a close-out for them — the operator will not necessarily name this skill.
argument-hint: "[slice number or slice dir]"
---

# Close-out

Execute the operator's dispositions on one slice's `close-out.md` — the report every plan and
run agent wrote its out-of-scope observations to (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md` is
what the report is; `${CLAUDE_PLUGIN_ROOT}/docs/close-out-template.md` its shape). The operator
reads and decides; this session presents, records, files, and edits. `<spec-repo>` is the path
in your `.aiworkflowrc`'s `spec_repo`; the tracker and the notification wiring come from your
host convention (`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, section 3). **Load that
convention before the first tracker call** — where the host ships it as a skill, invoke the
skill: nothing in the pipeline loads it for you, and a convention that is not in context gets
guessed at.

## Procedure

1. **Locate the report — and its card.** The argument names the report (a slice number or a slice
   dir); without one, the newest open `[NNN] close-out: <slice title>` card in this project's
   intake queue names it. The run filed one such card per report, and an open card is what makes
   a report pending — a blank `Disposition:` under a closed card is a closed entry, not work. Find the card by that title now and keep
   its id for step 6; the operator should never have to point you at it. Say which report you
   opened, and say once if the card is not there, then carry on without it.
2. **Present it — ask nothing yet.** Show the `Run:` header, the Summary and every `Focus:` line
   from the file, then `python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_out.py list <slice_dir>` as it
   prints — every live entry as `id — headline` with its `Consequence:` line under it (that line
   is what the operator triages on), struck entries as their headline only, marked as such. The
   operator reads; you wait.
3. **Take dispositions.** The operator writes them into the file under the entries, or says them
   in chat ("card B1, close B6, fold S1 into 009"). Chat dispositions you write into the file on
   the entry's `Disposition:` line **in the operator's words** — never paraphrased, never
   completed. Free form; the usual vocabulary is `card [project]` · `fix now` ·
   `fold into <slice>` · `close` · `defer`. A blanket ruling ("close the rest", "I'm not
   progressing anything else") is a `close` on every entry still blank, each carrying those
   words. What you then did goes after the operator's words on the same line, after ` — `: the
   card id, the commit, the slice folded into.
4. **Execute each disposition:**
   - `card [project]` — one tracker card per entry (in the named project's intake queue, else
     this project's, per the host convention): title = the entry's headline without its
     ` · <severity>` grade — the grade ranks a finding inside its report, and on a card's title
     it reads as a claim about the card — body = the entry verbatim + its `Provenance:` line +
     the report's path.
   - `fix now` — do it here only if the project's `CLAUDE.md` classes the change as ad hoc
     work; otherwise say so and offer `fold into`. Done and committed, strike the entry as a
     `close` is struck, the reason naming the commit (`--reason "fixed in <commit>"`) — a carded
     entry stays live, a fixed one does not.
   - `fold into <slice>` — append the entry verbatim as an ask to that slice's `slice.md` under
     `slices/backlog/`; a slice that does not exist yet becomes a `/dev:triage` item instead.
   - `close` — `python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_out.py strike <slice_dir> <id>
     --reason "closed by the operator, <date>"` (the operator's reason, if given, stays on the
     `Disposition:` line, not in the heading).
   - `defer` — leave it; it is `/dev:triage`'s.
5. **Offer to finish it — don't wait to be asked.** The operator dispositions what they care
   about and stops; the rest of the report is yours to close out, not theirs to work through.
   When their last message is settled — the dispositions executed, the question answered, "fine",
   a shrug — and nothing else is pending, ask in one line whether to strike what is still blank
   (how many entries, by id) and close the close-out card. You raise it, unprompted; once, and
   again only after something has happened since. A yes is a `close` on each of those entries,
   struck per step 4, the words being the ones the operator agreed to; an entry they pull back
   out of the batch is a disposition like any other. A no is a `defer` on each of them — the
   card stays open for `/dev:triage` — and ends the asking.
6. **Render, commit and finish.** Run `python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_out.py render
   <slice_dir>` (live entries first, the newly struck ones folded last), then commit the report
   (staged by name — the spec repo is a shared tree). Close the close-out card found in step 1 as
   resolved unless an entry is deferred or the step-5 question went unanswered: the card's closure
   closes the report (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`), so nothing blank under a closed
   card is owed a disposition. Report short: dispositions by kind, cards filed, anything owed.

## When the operator hands you the triage

"Do the close-out", "triage it for me", "apply your suggestions for the rest" — the operator
wants to rule once, not entry by entry. A report runs to dozens of entries, and their worry is
missing the one that matters, not reading all of them: your product is a sheet they can rule on
in one message, with the few entries that need their eyes pulled out of the rest. You propose,
they dispose — nothing is filed, fixed or struck before the ruling. This stands in for steps 2–3,
over every entry still blank; steps 4–6 then run as written on what they ruled.

1. **Check what can have moved.** A report ages: a later phase, slice or ad hoc commit may have
   fixed what an entry describes. Where an entry's bucket turns on a fact a command or two
   settles — an id list, a page that "still contradicts", a script that may since have been
   fixed — check it before you sort; an entry already fixed is a `close` whose why names the
   commit. That is the whole of the checking: whether the claim still holds today, never whether
   it was right.
2. **Sort every entry into one bucket**, on its `Consequence:` line and its evidence class:
   - **`fix now`** — a small change whose content is already known: the entry says what the text
     should be. Doc, comment and config text above all. Step 4's ad hoc test still applies.
   - **`card`** — a bug with real impact that is not a `fix now`: its Consequence names something
     an operator or user will meet in the deployed shape. Entries that are one fix are one card.
   - **`close`** — edge cases that are real but remote, missing tests with little riding on them,
     nits and cosmetics — and Suggestions, by default: the operator progresses a small fraction
     of them, so a suggestion is closed unless it is clearly interesting, and then it goes to the
     last bucket, not to a card.
   - **Outstanding actions** — all of them on **one** card in the operator's action queue: a
     list they work from, not a card each.
   - **Needs your eyes** — whatever does not sort: a bug whose impact the entry does not let you
     judge, an open question or ruling, the interesting suggestion, an entry two buckets both
     fit. Do not force these — this set is what the sheet is for — and keep it small: a set that
     is a third of the report means the sorting was not done.
3. **Present the sheet and wait.** The `Run:` header and the Summary, then the buckets —
   needs-your-eyes first, each with its count — one line per entry: `id — headline — why this
   bucket`, the why in a clause. The operator rules in one message; an amendment ("card B4
   instead", "S7 is interesting, fold it into 012") is a disposition like any other and wins
   over the sheet. What they leave unruled is step 5's question.
4. **Record it as what it was.** An entry's `Disposition:` line carries the operator's ruling in
   their words, then ` — suggested <disposition>`, then what you did — so the file shows the
   choice was yours and the decision theirs. An entry they ruled on by name carries their words
   for it alone.

## Bounds

- Never edit an operator's words, and never re-derive an entry's claim — the run's records are
  in the slice folder if the operator wants to look, and `/dev:triage` grounds what it takes on.
  A handed-over triage checks whether a claim still holds today, nothing more.
- When a disposition asks about the claim ("this says we built the wrong thing, right?"), answer
  from the entry's own body and `Provenance:` — quote what supports or fails to support the
  operator's reading, and say plainly when the entry does not settle it. Agreeing is not an
  answer; neither is re-deriving.
- Present, record, file, edit — no planning, no design here; that is `/dev:triage` →
  `/dev:plan-slice`.
- Steps that do not apply are skipped silently: an operator who wrote every disposition into
  the file gets step 4 straight away.
