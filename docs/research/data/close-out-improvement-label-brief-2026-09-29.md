# Labelling brief — potential improvements, six attributes

`/tmp/co/improve/entries.md` holds 89 entries taken from close-out reports: what the agents that
did a piece of work (a "slice") noticed and did not act on. These 89 were classed as potential
improvements: the product is not doing something wrong today; the entry proposes to make
something better, safer or simpler. Each entry is preceded by a comment
`<!-- entry <report> <id> -->` and followed by `---`.

Your labels are research data. They will be compared with what the operator later decided
about each entry, which you cannot see. Label what the entry says, not what you think should
be done with it. You have the text and nothing else: open no repository and no other file.
Where the entry does not let you tell, the answer is `unknown`; a forced guess spoils the data.

## The six attributes

**1. `benefit`** — who is better off when the improvement is made. One of:

- `user` — somebody using the product: what they see, can do, or have to do by hand.
- `operations` — whoever deploys, runs, upgrades or recovers the system.
- `workflow` — the development workflow itself: the agents that build slices, the test
  suites and gates, CI, the tools they run.
- `code` — whoever maintains the code or the documentation: less duplication, simpler
  structure, shorter pages, dead code gone.
- `unknown`

**2. `felt`** — when the benefit would be felt. One of:

- `every-use` — each time the thing is used, run or read; it is felt as things are today.
- `some-uses` — on some ordinary occasions, as things are today.
- `after-a-change` — only once somebody changes something, or something external changes
  (an upgrade, a rotation, a second consumer, a later slice).
- `after-an-incident` — only when something goes wrong first (a fault, an attack, a mistake).
- `not-observable` — nobody would notice the difference.
- `unknown`

**3. `ground`** — what the suggestion rests on. One of:

- `met-in-run` — the run itself ran into it: it lost time, failed, needed a workaround, or
  the author reproduced or measured it.
- `left-by-slice` — this slice's own change created it: it changed one place and left its
  siblings as they were, or left code, text or a test that its change made dead or
  inconsistent.
- `read-in-passing` — the author noticed it while reading; nothing in the run depended on it.
- `unknown`

**4. `change`** — what kind of change it is. One of:

- `remove` — it takes something away: code, a duplicate, a step, a file.
- `adjust` — it changes what exists, in place.
- `add` — it adds something: behaviour, a check, a gate, an alarm, a test harness, state, a
  process, a document.
- `unknown`

**5. `size`** — what is decided about the change. One of:

- `one-edit` — the entry states or plainly implies the exact change, in one place.
- `several-places` — known and mechanical, in several places.
- `design` — a choice with consequences is open.
- `investigate` — the entry asks for something to be looked into before anything is changed.
- `unknown`

**6. `product_call`** — `yes` if making the improvement changes what a user of the product
sees or can do, so that it is a decision about the product; `no` otherwise.

Plus one more, because it changes the route whatever the rest says:

**7. `prevents`** — the worst thing the improvement would prevent, if it prevents anything.
One of: `severe` (lost or corrupted data, an exposure, a failure that cannot be recovered
without repair) · `broken` (a flow fails or stays stuck until somebody intervenes) ·
`misleading` (a wrong or confusing message, status or document) · `nothing` (it prevents no
problem; it only makes something better) · `unknown`.

## Output

One file, `/tmp/co/improve/labels.json`: an object keyed by `"<report> <id>"` exactly as in
the entry's comment, each value an object with the seven attributes. Use exactly the values
listed above. Nothing else in the file.

```json
{
  "KubeCoder-154 S6": {"benefit": "user", "felt": "every-use", "ground": "left-by-slice",
                       "change": "adjust", "size": "several-places", "product_call": "yes",
                       "prevents": "nothing"}
}
```

Read the entries in portions of about twenty; write the file after each portion so nothing is
lost if you stop early. When all 89 are labelled, validate with one command: the file parses,
every value is in its vocabulary, the keys are exactly the 89 entry comments.

## Your final message

Under 150 words: how many entries you labelled, and the two or three attribute decisions you
found hardest to make from the text. Your labels will be reviewed and scored; say plainly
where you were unsure.
