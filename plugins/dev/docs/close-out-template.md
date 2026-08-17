# The close-out template — close-out.md, mechanically

The concrete shape of a slice's `close-out.md`: the fixed sections, the one entry shape, the
struck-entry form, and the run header. Both loops create the file from this template
(`close_out.py init` lifts the first fenced block below, substituting the slice's number and
slug into the title), and every agent that writes to it reads the shape off the file itself —
so what is settled here is what every author produces, and the file carries the entry shape in
its own head comment: no author has to open this doc. Semantics — what the report is for, who
writes what and when, the entry rules, the lifecycle — are [close-out.md](close-out.md); this
doc is the shape.

## close-out.md

```markdown
# Close-out — slice NNN <slug>

<!-- Run header: stamped by the driver at close-out from state.json. Agents never edit it. -->
Run: <not yet stamped>

<!-- Every entry, in every section, has exactly this shape. The id is the section's letter
     (A · N · B · Q · S) and the next number — count the section's `###` headings, struck ones
     included. Severity (major | minor | nit | cosmetic) sits in the heading of Bugs only. Three
     bold labels close every entry, in this order; `**Disposition:**` is the operator's line:
     leave it blank.

     ### B2 — <headline: one line, the claim itself> · minor · <repo or component>

     <What: the thing itself, quoted where it is text or output — the sentence, the command and
     what it printed, the file and lines. How it was found. As many paragraphs as it takes.>

     **Consequence:** <what an operator or user actually experiences if this stays as it is —
     unfixed, undone, unanswered — in the deployed shape and in plain words, with what has to
     happen for it to be reached; or "none", said plainly. Not what changed relative to before,
     not "none to behaviour" when a human would notice something. The operator triages on this
     line.>

     **Provenance:** <role, phase, round; the artifact that holds the full record>
     **Disposition:**

     A later note about an entry — its premise moved, it was re-checked, a phase resolved it — is
     a dated paragraph at the end of that entry's body, above its **Consequence:** line, never a
     new entry. An entry is never deleted. Struck, it keeps its heading, with the reason appended:

     ### ~~S3 — <headline>~~ — absorbed by P11 (97b5313), struck by consult 1
-->

## Summary

<!-- Written by the doc-writer as its last act: a few lines on the slice and what shipped.
     Until then, blank. -->

## Outstanding actions

Focus: <!-- doc-writer: what the operator must do before the slice's outcome holds -->

<!-- The operator runbook. One entry per keystroke only the operator can make: what to do,
     why it is owed to the operator, what stays open until it is done. -->

## Notable events

Focus: <!-- doc-writer: the shape of the run — bail-outs, appended phases, surprises -->

<!-- Everything that deviated from a completely uneventful run — product and workflow alike: a
     bail-out, an appended phase, a live run that exposed what the suite hid; a tool missing from
     the sidecar, a wait that hit a cap, a call the harness refused. What happened, when, how it
     resolved, what it says. The driver appends refuted findings and funding-consult merges here
     itself. -->

## Bugs

Focus: <!-- doc-writer: the worst one first; which are in this slice's repos, which elsewhere -->

<!-- Defects the run will not fix. Severity in the headline: major | minor | nit | cosmetic. -->

## Open questions and rulings

Focus: <!-- doc-writer -->

<!-- Questions the operator should settle that the run did not need answered to proceed. What
     turned on it, what the run did meanwhile. A question the run DOES need answered is a
     `question` verdict, not an entry here. -->

## Suggestions

Focus: <!-- doc-writer -->

<!-- Ideas, improvements, inputs for other slices, fix proposals for the bugs above. -->
```

## The entry

The head comment above is the whole shape — the same in every section, ids by section letter in
order of arrival, and under every body the three bold labels in one order: `**Consequence:**` (a
short paragraph of its own — the operator scans for it and triages on it), `**Provenance:**`,
then a blank `**Disposition:**`. The labels are bold so the eye finds them in a long report; the
paragraph before them is where a later note about the entry lands, dated. `close_out.py append`
mints exactly that shape for the driver's own entries; agents write it by hand. What the
comment leaves to this doc: Outstanding actions read as imperatives ("Create the
`IaC/ArgoCDTools` Jenkins job"); the severity grades' meanings and what a `Consequence:` is
written for are in [close-out.md](close-out.md); the head comment and the section charters are
the file's, never edited or removed. `close_out.py counts` reads entries off the `###` headings
and says, next to the per-section counts, how many headings in the entry sections are not in the
entry shape and how many live entries lack a `Consequence:` or a `Provenance:` line — the smoke
checks, so an author that drifted from the shape shows in the run's completion line instead of
as a report that counts zero.

## The run header

One block of plain lines replacing `Run: <not yet stamped>`, written by `close_out.py stamp`
from `state.json` — every piece present in the state, nothing guessed for the pieces that are
not:

```markdown
Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended) · 2 bail-outs ·
1 test round · doc phase done · $118.41 (planner 18 %, research 4 %, rework 14 %)
```
