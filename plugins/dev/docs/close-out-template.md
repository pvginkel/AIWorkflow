# The close-out template — close-out.md, mechanically

The concrete shape of a slice's `close-out.md`: the fixed sections, the one entry shape, the
struck-entry form, the rendered order, and the run header. Both loops create the file from this
template (`close_out.py init` lifts the first fenced block below, substituting the slice's
number and slug into the title), and `${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` writes every
entry, note and strike in the shape shown — no author types it, and the file carries the shape
in its own head comment for whoever reads the file raw. Semantics — what the report is for, who
writes what and when, the entry rules, the lifecycle — are [close-out.md](close-out.md); this
doc is the shape.

## close-out.md

```markdown
# Close-out — slice NNN <slug>

<!-- Run header: stamped by the driver at close-out from state.json. Agents never edit it. -->
Run: <not yet stamped>

<!-- Every entry, in every section, has exactly this shape — written by `close_out.py append`
     (the tool named in your dispatch; by hand only if the tool is unavailable, in exactly this
     shape). The id is the section's letter (A · N · B · Q · S) and the next number — struck
     headings count. Severity (major | minor | nit | cosmetic) sits in the heading of Bugs only.
     Three bold labels close every entry, in this order; `**Disposition:**` is the operator's
     line: leave it blank.

     ### B2 — <headline: one line, the claim itself> · minor · <repo or component>

     <What: the thing itself, quoted where it is text or output — the sentence, the command and
     what it printed, the file and lines. Lead with the symptom; a cause only where it was shown.
     How it was found. As many paragraphs as it takes.>

     **Consequence:** <what an operator or user actually experiences if this stays as it is —
     unfixed, undone, unanswered — in the deployed shape and in plain words, with what has to
     happen for it to be reached; or "none", said plainly. Not what changed relative to before,
     not "none to behaviour" when a human would notice something. The operator triages on this
     line.>

     **Provenance:** <witnessed | read — witnessed: you ran, measured, reproduced or mutated it
     and the evidence is in the body; read: inferred from reading code or text — then role, phase,
     round; the artifact that holds the full record>
     **Disposition:**

     A later note about an entry — its premise moved, it was re-checked, a phase resolved it — is
     `close_out.py note`: a dated paragraph `<who>, <date> — <text>` at the end of that entry's
     body, above its **Consequence:** line, never a new entry. An entry is never deleted. Struck
     (`close_out.py strike`), it keeps its heading, with the reason appended — and a strike is a
     claim like any other: resolved, refuted or does-not-reproduce names the commit and what was
     re-run, not just who decided:

     ### ~~S3 — <headline>~~ — absorbed by P11 (97b5313); struck by consult 1
     ### ~~B1 — <headline>~~ — resolved by P2 r2 (1d7bfe7): repro re-run, one chevron; struck by consult 2
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

Focus: <!-- doc-writer: the worst one first — ranked on the Consequence lines and the evidence
     class (witnessed before read), never on length; how many are witnessed; which are in this
     slice's repos, which elsewhere -->

<!-- Defects the run will not fix. Severity in the headline: major | minor | nit | cosmetic. -->

## Open questions and rulings

Focus: <!-- doc-writer: what most turns on an answer, from the Consequence lines -->

<!-- Questions the operator should settle that the run did not need answered to proceed. What
     turned on it, what the run did meanwhile. A question the run DOES need answered is a
     `question` verdict, not an entry here. -->

## Suggestions

Focus: <!-- doc-writer: which change a decision or another slice, from the Consequence lines;
     which are witnessed -->

<!-- Ideas, improvements, inputs for other slices, fix proposals for the bugs above. -->
```

## The entry

The head comment above is the whole shape — the same in every section, ids by section letter in
order of arrival, and under every body the three bold labels in one order: `**Consequence:**` (a
short paragraph of its own — the operator scans for it and triages on it), `**Provenance:**`
(opening with the evidence class, `witnessed` or `read`), then a blank `**Disposition:**`. The
labels are bold so the eye finds them in a long report. `close_out.py append` mints exactly that
shape for every author, the driver included; `close_out.py note` adds the dated paragraph
(`<who>, <date> — <text>`) above the Consequence line — on an entry from before the Consequence
label existed, above its `Provenance:` line instead; `close_out.py strike` rewrites the heading
to the struck form (`~~<id> — <headline>~~ — <reason>; struck by <who>`) and leaves the body
where it is; and `close_out.py list` shows the sections' ids, headlines and Consequence lines
without the bodies. No agent edits the file by hand. What the comment leaves to this doc:
Outstanding actions read as imperatives ("Create the `IaC/ArgoCDTools` Jenkins job"); the
severity grades' meanings and what a `Consequence:` is written for are in
[close-out.md](close-out.md); the head comment and the section charters are the file's, never
edited or removed. `close_out.py counts` reads entries off the `###` headings and says, next to
the per-section counts, how many headings in the entry sections are not in the entry shape and
how many live entries lack a `Consequence:` or a `Provenance:` line — the smoke checks, so an
author that drifted from the shape shows in the run's completion line instead of as a report
that counts zero.

## The rendered order

Entries arrive in the order agents wrote them; the operator reads them in the order that
matters. `close_out.py render` puts every entry section in reading order, in place: the
section's preamble (its `Focus:` line and charter comment) as it was; then the **live entries** —
in Bugs sorted by severity (`major`, `minor`, `nit`, `cosmetic`, then any without a grade), in
every other section by id; then any `###` heading not in the entry shape, in its original order;
then the **struck entries**, by id, each with its body folded once so the live ones lead and the
record is kept:

```markdown
### ~~B5 — <headline> · minor~~ — resolved by P4 (19640d9): suite re-run; struck by consult 1

<details><summary>struck — body kept for the record</summary>

<the entry's body, its Consequence, Provenance and Disposition lines included, verbatim>

</details>
```

Nothing outside the entry sections moves — not the title, the run header, the head comment or
the Summary — and a second render is a no-op: a struck entry that already carries the fold is
not wrapped again. The driver renders before it dispatches the doc phase (so the doc-writer's
`Focus:` lines are written over the order the operator will see) and again at completion,
before it stamps the header; the `close-out` skill renders after the operator's dispositions
have been executed. A struck entry needs no disposition — its fate is in its heading.

## The run header

One block of plain lines replacing `Run: <not yet stamped>`, written by `close_out.py stamp`
from `state.json` — every piece present in the state, nothing guessed for the pieces that are
not:

```markdown
Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended) · shape pre-settled ·
writer high (fuse tripped) · 2 bail-outs · 1 test round · doc phase done · $118.41 (planner 18
%, research 4 %, rework 14 %)
```

`shape` is the plan's declared task shape (`undeclared` when the plan carries none) and `writer`
the tier the code-writer's round 1 actually ran at — the run's `--writer-effort` only when the
shape buys the step-down, `xhigh` otherwise, so a `cross-cutting` run launched with `high` reads
`writer xhigh` (`(fuse tripped)` when two phases needed a redo and the rest ran at `xhigh`; not
said when there was no lower tier to leave) — the arm of the effort trial this report belongs to;
absent on runs before 0.7.0.
