---
name: close-out
description: Work through a slice's close-out report with the operator — bring them what the report asks of them (actions, decisions, risks, card requests), take their rulings in the session or from the report's Disposition lines, execute them (card / fix now / fold into a slice / close / defer), and close the report. Invoke it yourself whenever the operator opens, discusses, pastes from, or wants to process a slice's close-out report, or asks you to do a close-out for them — the operator will not necessarily name this skill.
argument-hint: "[slice number or slice dir]"
---

# Close-out

Bring the operator what one slice's close-out report asks of them, and execute what they rule.
The report is the record every plan and run agent wrote its out-of-scope observations to; the
author of each entry labelled it, and a table routed it from those labels
(`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md` has the labels and the routes,
`${CLAUDE_PLUGIN_ROOT}/docs/close-out-template.md` the shapes). What the table brings the
operator is theirs to decide and nobody else's; the rest it has closed, given to the wrap-up or
put in the record. The operator reads and rules; this session presents, records, files and
edits. `<spec-repo>` is the path in your `.aiworkflowrc`'s `spec_repo`; the tracker and the
notification wiring come from your host convention
(`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, section 3). **Load that convention before the
first tracker call** — where the host ships it as a skill, invoke the skill: nothing in the
pipeline loads it for you, and a convention that is not in context gets guessed at.

Below, `close_out.py` is `python3 ${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` and `<slice>` the
slice directory.

## Procedure

1. **Locate the report — and its card.** The argument names the report (a slice number or a slice
   dir); without one, the newest open `[NNN] close-out: <slice title>` card in this project's
   intake queue names it. The run filed one such card per report, and an open card is what makes
   a report pending. Find the card by that title now and keep its id for step 9; the operator
   should never have to point you at it. Say which report you opened, and say once if the card
   is not there, then carry on without it.
2. **Read back, then render.** `close_out.py rule <slice>` takes what the operator wrote on the
   report's `Disposition:` lines into the store and prints it; `close_out.py render <slice>`
   then writes the report as the table routes it today. A report from before the store existed
   is imported by the first call: its old Bugs and Suggestions carry no labels and stand under
   **Unlabelled**.
3. **Dispatch the wrap-up when entries wait for it.** `close_out.py worklist <slice>` names what
   the table gave the wrap-up and no run wrapped up: a run that stopped before its end, a
   wrap-up that failed, a report an older plugin wrote. When it names any, say so in a line and
   dispatch the `dev:wrap-up` agent as a sub-agent, in the background, with the slice directory
   and the report's path, the path of `close_out.py`, and for every repository the slice touched
   (`state.json`: the `root` of every phase) its path and the branch that is checked out there —
   where its commits go, as a `fix now` of yours would. Carry on with step 4 while it works,
   within two limits: you change nothing in a repository it works in until it has returned — a
   ruling is recorded at once and executed after — and the card requests are presented when it
   has returned, because most of them are its own. When it returns, render, and say in a line or
   two what it did: what it fixed, with the commits, what it asks a card for, what it left. A
   wrap-up that fails changes nothing else in this procedure: what waited for it comes to the
   operator with the rest, said as what it is — an entry nobody looked at.
4. **Check what can have moved.** A report ages: a later phase, slice or ad hoc commit may have
   fixed what an entry describes. Where the claim of an entry that comes to the operator turns
   on a fact a command or two settles — an id list, a page that "still contradicts", a script
   that may since have been fixed — check it before you present, and put what you found under
   the entry (`close_out.py note`). An entry already fixed is presented as that, with the
   commit. That is the whole of the checking: whether the claim still holds today, never whether
   it was right. An entry that comes to them with no `Proposal:` gets one from you
   (`close_out.py propose <slice> <id> --by "close-out session" --text "…"`): what you would do
   about it and why, in a ruling's words, from the entry and what you found. The same pass
   removes what the run left behind: the record's events name a scratch clone the driver left
   for a `github:` Target — when its tree is clean and level with its origin, delete it and say
   so under the event (`note`); otherwise say what you found and leave it.
5. **Present what comes to the operator — ask nothing yet.** Show the `Run:` header, then the
   entries under **Comes to you** and **Card requests** as the rendered report has them: in its
   order, each whole — its ask, its body, its newest note, its labels in words and its evidence
   (the template's § The entry has the shape) — with the ruling the operator already wrote on
   it, if any. Leave out nothing the report shows and summarise none of it. They rule from that,
   or ask; when they ask about an entry, `close_out.py show <slice> <id>` — every note, every
   mark — is what you answer from. Entries that still stand under **Unlabelled** or **For the
   wrap-up** come with them: nobody routed or handled those, so they are the operator's to see. Then
   one line for the rest, from `close_out.py counts <slice>`: how many entries the table closed, how
   many the wrap-up settled, how many are in the record. They are in the report under their
   headings; nothing is asked about them. The operator reads; you wait.
6. **Take the rulings.** The operator rules in the session ("card B1, close D2, fold I1 into
   009") or on the `Disposition:` lines of `close-out.md`, as it suits them, and both in one
   report. What they say you record at once, `close_out.py rule <slice> <id> --words "<their
   words>"` — **in the operator's words**, never paraphrased, never completed. What they wrote
   in the file, `close_out.py rule <slice>` reads back: run it again before you execute anything
   when they tell you they wrote there. Free form; the usual vocabulary is `card [project]` ·
   `fix now` · `fold into <slice>` · `close` · `defer`. A blanket ruling ("close the rest", "I'm
   not progressing anything else") is a `close` on every entry that came to them and has no
   ruling yet, each carrying those words. A ruling may name any entry of the report: "card B7"
   on an entry the table closed pulls it back, and is a ruling like any other. A word of assent
   on an entry — "agreed", "ok", "do it" — is a ruling for its `Proposal:`: record their word,
   execute what the proposal says, and what you record as done names it. When they ask what
   you would do with an entry beyond its proposal, say it in a clause, with the reason and from
   the entry's own text, and wait — the ruling stays theirs, and what you record as done on it
   opens `suggested <disposition>`.
7. **Execute each ruling**, then record what you did, `close_out.py rule <slice> <id> --did
   "<what was done>"` (`--commit <sha>` where there is one) — "carded as <card id>", "fixed in
   <commit>", "folded into <slice>", "closed by the operator, <date>". Recording it strikes the
   entry.
   - `card [project]` — one tracker card per entry (in the named project's intake queue, else this
     project's, per the host convention): title = the entry's headline without its ` · <grade>` —
     the grade ranks a finding inside its report, and on a card's title it reads as a claim about
     the card — body = the entry in full as `close_out.py show <slice> <id>` prints it, and the
     report's path. Entries that are one fix are one card. Actions the operator wants carded go
     together, on **one** card in their action queue: a list they work from, not a card each. A card
     request they say yes to is filed the same way.
   - `fix now` — do it here only if the project's `CLAUDE.md` classes the change as ad hoc
     work; otherwise say so and offer `fold into`.
   - `fold into <slice>` — append the entry verbatim as an ask to that slice's `slice.md` under
     `slices/backlog/`, snapshotted before you edit it
     (`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`); a slice that does not exist yet becomes a
     `/dev:triage` item instead.
   - `close` — there is nothing to do but record it; the operator's reason, if given, is part
     of their words.
   - `defer` — leave it, with their words recorded and nothing recorded as done: it stays live,
     and it is `/dev:triage`'s.
8. **Offer to close the report — don't wait to be asked.** The operator rules on what they care
   about and stops; the rest of the report is yours to finish, not theirs to work through. When
   their last message is settled — the rulings executed, the question answered, "fine", a
   shrug — and nothing else is pending, ask in one line whether to close the report: which
   entries that came to them are still without a ruling, by id, and how many the table closed
   stand with them. You raise it, unprompted; once, and again only after something has happened
   since. A yes is `close_out.py close <slice> --words "<their words>"`, which closes every
   entry still live but one that carries a ruling nobody executed: a `defer` stays, and the
   report stays open over it. An entry they pull back out of the close is a ruling like any
   other, executed first. A no is a `defer` on each entry that came to them and has no ruling
   — the card stays open for `/dev:triage` — and ends the asking.
9. **Render, commit and finish.** Run `close_out.py render <slice>`, then commit
   `close-out.json` and `close-out.md` (staged by name, `${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md`).
   Close the close-out card found in step 1 as resolved unless an entry is deferred or the
   question of step 8 went unanswered: the card's closure closes the report
   (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`), so nothing under a closed card is owed a ruling.
   Report short: rulings by kind, cards filed, what the wrap-up did, anything owed.

## Bounds

- **What the table brought the operator is decided by them and by nobody else.** You do not
  rule in their place, close on their behalf or act on a ruling you expect; a report is closed
  on their word.
- **The route is the table's.** An entry whose labels look wrong to you, you say so when you
  present it; you do not relabel it to move it.
- Never edit an operator's words, and never re-derive an entry's claim — the run's records are
  in the slice folder if the operator wants to look, and `/dev:triage` grounds what it takes on.
- When a ruling asks about the claim ("this says we built the wrong thing, right?"), answer from the
  entry's own body and `Provenance:` (`close_out.py show`) — quote what supports or fails to support
  the operator's reading, and say plainly when the entry does not settle it. Agreeing is not an
  answer; neither is re-deriving.
- Present, record, file, edit — no planning, no design here; that is `/dev:triage` →
  `/dev:plan-slice`.
- The slice's own card is not yours: it stays where the run left it, and moving it on is the
  operator's, after a review of their own. Leave it silently — don't move it, don't offer to,
  don't mention it.
- Steps that do not apply are skipped silently: an operator who wrote every ruling into the
  file gets step 7 straight away.
