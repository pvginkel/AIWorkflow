<!-- The brief the held-out replay of the 2026-09-28 close-out read was run on, as it was given
     to each Opus sub-agent with a batch of five to seven report paths — the arm `heldout-v2` of
     close-out-read-2026-09-28.json. Kept verbatim so the replay can be repeated and so the
     sorter's definition can be checked against the text that was tested. The `/tmp/co/` paths
     are the scratch layout of that session: `close_out_readout.py snapshots -o` writes the
     reports, `score` reads the folder of answers. -->

# Sorting brief — close-out reports

You sort the entries of close-out reports into proposed dispositions. Each report is the
`close-out.md` of one "slice" (a unit of work an automated pipeline ran): what the pipeline's
agents noticed during the run and did not act on. The human operator has to rule on every live
entry. They want to rule once, not entry by entry: a report runs to dozens of entries, and their
worry is missing the one that matters, not reading all of them. Your product is, per report, a
proposed disposition for every live entry, with the few entries that need the operator's eyes
pulled out of the rest.

Entry ids are a letter and a number; the letter is the section: A = Outstanding action (a
keystroke only the operator can make), N = Notable event, B = Bug, Q = Open question or ruling,
S = Suggestion. A heading written `### ~~…~~ — <reason>` is a struck entry, settled during the
run: skip it, it gets no row. Every other `### <id> — …` heading is a live entry and gets
exactly one row.

## The rules

Sort every live entry into one bucket. Take the buckets in this order — the first that fits
is the entry's bucket:

1. **`moot`** — the entry itself says the thing is already done: a dated note under it (or its
   own body) says it was fixed, resolved or closed during the run and names the commit or the
   phase. Nothing is owed; it only waits to be struck.
2. **`action`** — every Outstanding action (section A): they all go on one card in the
   operator's action queue, a list they work from.
3. **`fold`** — the entry is input for work that has not run yet: it names a slice or a phase
   still to come, or says what a later slice, migration or plan has to take into account. It
   is appended to that slice, whatever its size.
4. **`fix now`** — a small change whose content is already known: the entry says what the text
   or the line should be. Doc, comment, config and test text above all. **The size of the
   consequence does not move an entry out of this bucket**: a nit whose fix is one known edit
   is a `fix now`, not a `close` — the operator has such edits made on the spot because they
   cost less than deciding about them.
5. **`test gaps`** — the entry's whole claim is that a test is missing, pins nothing, or cannot
   fail, and the code it would guard is right today. All of a report's test gaps are one
   group, ruled on together: the operator cards the group as one card or closes it.
6. **`card`** — a bug with real impact that is not a `fix now`: its Consequence names something
   an operator or user will meet in the deployed shape. Entries that are one fix are one card.
7. **`needs-eyes`** — what the operator has to look at themselves: a bug whose impact the entry
   does not let you judge, an open question or ruling, an entry that proposes removing,
   simplifying or redesigning something (a product call is theirs), the suggestion that is
   clearly interesting, an entry two buckets both fit. Do not force these — this set is what
   the sheet is for — and keep it small: a set that is a third of the report means the sorting
   was not done.
8. **`close`** — everything else: edge cases that are real but remote, nits and cosmetics with
   no known one-edit fix, records of things that went right, and Suggestions by default — a
   suggestion is closed unless one of the buckets above took it.

## How to work

- Sort from the report alone. Do not open any other file, repository or URL; do not check
  whether a claim is true or still holds. You judge what the entry says, as written.
- Treat every report on its own. What you decided for one report is no precedent for the next.
- Read each report whole before sorting it.

## Output

For each report `/tmp/co/snapshots/<name>.md` write `/tmp/co/held-v2/<name>.json`:

```json
{
  "report": "<name>",
  "rows": [
    {"id": "B1", "bucket": "moot | action | fold | fix now | test gaps | card | needs-eyes | close",
     "why": "<one clause, max 20 words: why this bucket>"}
  ]
}
```

One row per live entry, none for struck entries, ids exactly as in the report. Validate each
file with `python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d['rows']))" <file>`.

Your final message: one line per report — name, live entries, count per bucket.
