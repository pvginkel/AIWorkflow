# The close-out template — the store, the document and the record, mechanically

The concrete shapes of a slice's close-out report: the store `close-out.json`, which is the
record, and the two files `${CLAUDE_PLUGIN_ROOT}/tools/close_out.py render` writes from it —
`close-out.md`, the document Pilot reads, and `close-out-record.md`, attached to it. No author
types any of them: the tool writes every entry, note, strike and ruling, and its verbs are
listed [below](#the-verbs). Semantics — what the report is for, the labels and the routes, who
writes what and when, the continuation and the lifecycle — are [close-out.md](close-out.md), and
an entry's words are `/dev:writing`'s; this doc is the shape.

## The store

```json
{
  "store": 2,
  "slice": "NNN_<slug>",
  "closed": null,
  "step": "T7",
  "entries": [
    {
      "id": "D1",
      "kind": "decision",
      "grade": null,
      "headline": "a component that declares no tests: keep kc's exit 3, or add an exit 8?",
      "body": ["<the body, one string per line>"],
      "consequence": "<what is experienced, and what has to happen for it to be reached>",
      "proposal": null,
      "evidence": "read",
      "author": "code-writer, P3",
      "by": "code-writer P3",
      "labels": {"trigger": "ordinary-condition", "impact": "degraded", "signal": "silent"},
      "notes": [{"by": "consult 1", "date": "2026-09-30", "text": ["<one string per line>"]}],
      "wrap_up": null,
      "strike": null,
      "ruling": null,
      "options": [{"label": "Exit 3", "line": "in effect; nothing changes"},
                  {"label": "Exit 8", "line": "a kc release and every caller on 3"}],
      "recommend": "Exit 3"
    }
  ]
}
```

- **Entries stand in order of arrival**, and an id is never reused: the next number under a
  kind's letter counts every entry that carries the letter, struck ones included.
- **Text is kept as lines** — `body`, and the `text` of a note — so that a diff of the store
  reads like a diff of text.
- **`labels`** holds the labels of the entry's kind, by the names and values of
  [close-out.md](close-out.md#the-labels); `null` on an entry that has none yet. A correction
  (`relabel`) changes them in place and leaves a note that says what changed and why.
- **`proposal`** is what its author would do about the entry and why, in a sentence or two.
  `append --proposal` writes it; `propose` replaces it, the one before kept as
  a history note. `null` on an entry that has none, and on a decision, which carries its
  options in its place.
- **`options`**, **`recommend`**, **`check`** and **`due`** are there only where given: a
  decision's options (`{label, line?}`, two or more) and the label it recommends; an action's
  options, the answers it asks for, and its check; any entry's `due` — `merge`, `test`, `push`
  or `close`, what it must land before, which the document never shows.
- **`by`** is the `--by` the entry was appended with, or `amend --by`'s; `author` is the
  provenance's own text. Neither is matched.
- **`wrap_up`** is what the wrap-up did with an entry it did not strike: `{"outcome", "by",
  "date", "text"}`, the outcome being `card` (it asks for a card), `word` (it asks for the
  operator's word on an edit) or `left` (it looked and changed nothing). A second mark replaces
  the first, which stays as a history note.
- **`strike`** is `{"reason", "by", "date", "commit"}`, the commit where a fix resolved the
  entry; **`ruling`** is `{"answer_lines", "did", "date"}` — the answer lines Pilot wrote,
  verbatim (`answer`, `by`, `at`, `note`, `via`, `to`, `done`), and what the continuation did on
  them. A report from before 0.10 holds `{"words", "did", "date"}` instead.
- **`closed`**, on the report, is `{"date", "by"}` once the continuation has closed it.
- **`step`**, **`summary`** and **`context`**, on the report, are the document's own fields,
  there where `render` was given them.
- **The route is not in the store**, and neither is the run header: the first is computed from
  the labels at every render, the second is `state.json`'s.

## The document

`close-out.md`, in `/dev:document-format`'s grammar, rendered by
`${CLAUDE_PLUGIN_ROOT}/tools/asks.py` from the asks `close_out.py` projects out of the store:

````markdown
---
title: Close-out of slice NNN — <the slice's name>
summary: "Slice NNN's close-out: what is yours to rule or to do and the cards asked for"
step: T7
---

**The run.** 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9, P10, P11 appended) · ….

**What shipped.** P1 <title>; P2 <title>.

**The wrap-up** fixed B3 and P2, a commit each.

**The record**, `close-out-record.md`, attached, holds the rest: what the table closed, the run's events, and every entry struck.

## a component that declares no tests: keep kc's exit 3, or add an exit 8?

Shipped in P3 (4f1c2a9): `kc project test --project <component>` on a component without
`test:` statements exits 3, kc's "nothing ran" — the status a missing component gives too.

**Consequence:** a component whose tests were removed by mistake passes its gate until a
reviewer notices.

**Provenance:** read — code-writer, P3

**consult 1, 2026-09-30.** <a note, in full>

```decision id=D1
options:
  - Exit 3: in effect; nothing changes
  - Exit 8: a kc release and every caller on 3
recommend: Exit 3
```
````

| the entry | its block |
|---|---|
| an action | `action`, its `options` and `check` |
| a decision with options | `decision`, its `options` and `recommend` |
| a card request the table made, the fix in a repo the slice did not touch | `decision`, `proposal: Card it for <repo>: …` where its author gave none |
| one for a slice planned or running | `decision`, `proposal: Add a phase to slice <N>'s plan, or rule on its run.` where its author gave none |
| one for a slice not created yet | `decision`, `proposal: Hold it for slice <N>, which is not created yet.`, the author's proposal after it |
| any other with a proposal | `decision`, its `proposal` |
| any other without | `question` |

The asks stand in the order of their places — what comes to the operator, the card requests,
what no wrap-up reached (opening **Not reached.**), what nobody labelled (opening
**Unlabelled.**) — and inside a place by grade (`major`, `minor`, ungraded, `nit`, `cosmetic`),
then the kind in the order of [its table](close-out.md#the-labels), then the id. The heading is
the headline, without the id or the grade; an action the plan loop seeded for a criterion owed
after an operator's step is headed `Settle <Vnn> (<its area>) after <owed_after>`, both from
`verification.json`, the wait in full, and its stock proposal and consequence, the same on every
one, are left off. A line of an entry's text Markdown would read as a heading, outside a fence,
is escaped. The notes stand under the body, a history note — a replaced proposal, an earlier
mark — left to the record; the wrap-up's `left` mark is a note. Answered, the block carries
Pilot's answer lines after its keys.

## The record

```markdown
# Close-out record — slice NNN <the slice's name>

Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended) · 2 bail-outs ·
1 test round · doc phase done · wrap-up landed · $118.41 (planner 18 %, research 4 %,
rework 14 %)

Closed: 2026-10-30 — by run-slice

## Ruled

### ~~D1 — a component that declares no tests: keep kc's exit 3, or add an exit 8?~~ — kept exit 3; struck by the operator's ruling

**Ruling:** answer: Exit 3 · by pvginkel · at 2026-10-30T12:00:00Z — kept exit 3

## Asked

### B4 — <headline> · minor

## Closed

### B7 — <headline> · nit

**Consequence:** <what goes wrong, and for whom>

**Triage:** defect · needs a fault · degrades · silent · fix is one edit · in KubeCoder
**Provenance:** witnessed — code-reviewer, P5 r1
**Route:** closed — it needs a fault

## Record

### E2 — The run stopped at P4 r2: the session hit its cap

### ~~B5 — <headline> · minor~~ — resolved by P4 (19640d9): suite re-run; struck by consult 1
```

The run header is one block of plain lines written from `state.json` when the slice folder
holds one — every piece present in the state, nothing guessed for the pieces that are not;
`Run: <not yet stamped>` without it. **Ruled** is every entry with a ruling, its heading struck
once it is carried out, the ruling on one line, never wrapped: the answer lines, then ` — ` and
what was done. **Asked** is the headings of what the document asks and nobody has answered.
**Closed** is what the table closed, with the ground of the close. **Record** is the run's
events that describe no problem, then what was struck and not ruled on, each by id, a struck
one's reason up to its first `; ` (`show` has it whole). A section with nothing in it is left
out.

## The verbs

Every verb takes the slice directory or the report's path as its first argument.

| verb | whose | what it does |
|---|---|---|
| `init` | the loops | creates the store; an existing store is never touched |
| `labels` | an author | prints [the labels](close-out.md#the-labels) |
| `append` | an author | adds one entry with its labels and what its kind owes — a proposal, or a decision's options and the one it recommends; `--check`, `--due`; prints its id |
| `list` | an author | ids, headlines and Consequence lines by kind, struck entries marked |
| `show` | the wrap-up, the continuation | one or more entries in full — body, notes, fields, labels, marks, ruling; without an id, every live entry |
| `note` | anyone | adds a dated paragraph to one entry; `--left` is the wrap-up's mark that it looked and changed nothing |
| `strike` | whoever resolved the entry | strikes it, with the reason and the commit |
| `amend` | anyone, until the render | corrects a live entry: each field given replaces the entry's, checked as `append` checks it; no note is left, and the id and the kind stay |
| `relabel` | the wrap-up, a role offered it | gives an entry its labels or corrects them, with a note of what it found; `--for none` clears a `for`; `--dry-run` prints the note and the route, and writes nothing |
| `propose` | the wrap-up, an author | gives an entry its proposal, or replaces it — the one before is kept as a note; `--card` makes it a card request, `--word` a request for the operator's word on an edit, which brings the entry to them |
| `fold` | the wrap-up, the continuation | appends an entry verbatim — its `show`, quoted, under a line naming the slice, the entry and the report — to the `slice.md` of the slice it is `for` (or `--into`), which has to be still to run and unplanned, and stages that file; prints the strike that follows the commit. Refused on a struck entry, on the report's own slice and on a fold `slice.md` holds already; writes neither the store nor the report |
| `worklist` | the wrap-up | what waits for the wrap-up, entry by entry, with what is asked of each |
| `render` | the loops, `/dev:run-slice` | writes the record, and the document unless Pilot wrote it back; `--step`, `--summary` and `--context` set the document's own fields |
| `absorb` | the continuation | reads `close-out.md`, as Pilot wrote it back, into the store: each block's answer lines into its entry's ruling; `deferred` and an action's `done` close the entry; refused on a document whose blocks are no entries of the store |
| `rule` | the continuation | records what was done on an entry's ruling, which strikes it |
| `settle` | the continuation | settles a criterion owed after an operator's action: writes its `pass` or `fail`, rationale and evidence into `verification.json` in the file's own escaping, `owed_after` kept ([plan-template.md](plan-template.md) § verification.json), and strikes the action that waited on it — a push hold's action listing several criteria takes a note until the last of them is settled; refused on a criterion without `owed_after` or already settled |
| `close` | the continuation | closes the report: every entry still live is struck, but one whose ruling nobody carried out — that one stays, and the report stays open over it |

No verb renders: the store changes, and the files follow at the next `render`.
