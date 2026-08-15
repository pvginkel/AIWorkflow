# The close-out template — close-out.md, mechanically

The concrete shape of a slice's `close-out.md`: the fixed sections, the one entry shape, the
struck-entry form, and the run header. Both loops create the file from this template
(`close_out.py init` lifts the first fenced block below, substituting the slice's number and
slug into the title), and every agent that writes to it reads the shape off the file itself —
so what is settled here is what every author produces. Semantics — what the report is for, who
writes what and when, the entry rules, the lifecycle — are [close-out.md](close-out.md); this
doc is the shape.

## close-out.md

```markdown
# Close-out — slice NNN <slug>

<!-- Run header: stamped by the driver at close-out from state.json. Agents never edit it. -->
Run: <not yet stamped>

## Summary

<!-- Written by the doc-writer as its last act: a few lines on the slice and what shipped.
     Until then, blank. -->

## Outstanding actions

Focus: <!-- doc-writer: what the operator must do before the slice's outcome holds -->

<!-- The operator runbook. One entry per keystroke only the operator can make: what to do,
     why it is owed to the operator, what stays open until it is done. -->

## Notable events

Focus: <!-- doc-writer: the shape of the run — bail-outs, appended phases, surprises -->

<!-- Everything that deviated from a completely uneventful run — product and workflow. What
     happened, when, how it resolved, what it says. The driver appends refuted findings and
     funding-consult merges here itself. -->

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

The same shape in every section. The id prefix is the section's letter — `A` Outstanding
actions · `N` Notable events · `B` Bugs · `Q` Open questions and rulings · `S` Suggestions —
numbered in order of arrival (`close_out.py append` allocates the next number; an agent writing
by hand counts the section's `###` headings, struck ones included):

```markdown
### B2 — <headline: one line, the claim itself> · minor · <repo or component>

<What: the thing itself, quoted where it is text or output — the sentence, the command and what
it printed, the file and lines. Why it matters: the consequence, or "none" said plainly. How it
was found. As many paragraphs as it takes; as few as it takes.>

Provenance: <role, phase, round; the artifact that holds the full record — e.g. "P3 review r1 F3
(advisory); consult 1 judged it too small for a phase">
Disposition:
```

The severity slot appears on Bug entries only (the vocabulary and what each grade means:
[close-out.md](close-out.md)). Outstanding actions read as imperatives ("Create the
`IaC/ArgoCDTools` Jenkins job"). `Disposition:` is left blank by every agent — it is the
operator's line.

**A struck entry** keeps its heading, struck through, with the reason appended; the body may
stay or go:

```markdown
### ~~S3 — D31's image-contents list is stale~~ — absorbed by P11 (97b5313), struck by consult 1
```

## The run header

One block of plain lines replacing `Run: <not yet stamped>`, written by `close_out.py stamp`
from `state.json` — every piece present in the state, nothing guessed for the pieces that are
not:

```markdown
Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended) · 2 bail-outs ·
1 test round · doc phase done · $118.41 (planner 18 %, research 4 %, rework 14 %)
```
