# Labelling brief — close-out entries, how the problem is met

Your batch file holds entries taken from close-out reports: what the agents that did a piece
of work (a "slice") noticed and did not act on. Each entry is preceded by a comment
`<!-- entry <report> <id> -->` and followed by `---`. Every entry describes a problem — one
that exists today, or one that a missing test or a proposed improvement would prevent.

Your labels are research data. They will be compared with what the operator later decided
about each entry, which you cannot see. Label what the entry says, not what you think should
be done with it. You have the text and nothing else: open no repository and no other file.
Where the entry does not let you tell, the answer is `unknown`; a forced guess spoils the data.

## The question

Suppose the problem the entry describes happens. **Does whoever meets it know, at that moment
and without looking for it, that something went wrong?**

## The two attributes

**1. `signal`** — how the problem is met when it happens. One of:

- `loud` — it announces itself: an error, a crash, a refused request or deploy, a red gate, a
  failed build or test run, a flow that visibly stops or hangs in front of the one waiting for
  it. Whoever is there knows that something went wrong and has a place to start looking. A
  wrong or garbled message counts as loud when it sits on a failure that is itself plain to
  see.
- `silent` — nothing says so: a wrong result is taken for a right one; a protection — a limit,
  a guard, a check, a validation, a retention rule — does not protect and nobody is told; data
  is lost, overwritten or drifts without a message; a step is skipped and reported as done;
  something reports healthy, complete or green that is not; a message or status states
  something false and reads as true. It is found later, from its consequences or by accident,
  if at all.
- `unknown` — the entry does not let you tell.

What decides is the moment the problem happens, not how bad it is and not how likely. A
failure that destroys data with a stack trace is `loud`; a harmless wrong number that nobody
questions is `silent`. A problem that is silent when it happens and shows only through what
follows from it later — a disk that fills, a certificate that was never renewed — is `silent`.

Two kinds of entry describe a problem that does not exist today:

- **A missing or hollow test** (the code is right today): every such entry is about a gate
  that would stay green, so that alone says nothing. Label the fault the test would have
  caught, as it would be met *in use* once it is in the product: a regression that makes a
  command fail is `loud`, one that makes it return the wrong value is `silent`. If the entry
  names no fault the test would catch, `unknown`.
- **A proposed improvement** (a guard, a check, a cleanup): label the problem it would
  prevent, the same way. If it prevents nothing that could be met, `unknown`.

**2. `basis`** — where your label comes from. One of:

- `stated` — the entry itself says how the problem is met (usually on its `Consequence:`
  line): "fails with …", "silently …", "the deploy is refused", "nobody is told".
- `inferred` — you derived it from what the entry describes.

## Output

One file, named in your task: an object keyed by `"<report> <id>"` exactly as in the entry's
comment, each value an object with the two attributes. Use exactly the values listed above.
Nothing else in the file.

```json
{
  "KubeCoder-154 B6": {"signal": "silent", "basis": "stated"},
  "Ansible-012 S7": {"signal": "loud", "basis": "inferred"}
}
```

Read the entries in portions of about twenty-five, whole — the body and the Consequence line
are what the label rests on, not the headline — and write the file after each portion so
nothing is lost if you stop early. When every entry of your batch is labelled, validate with
one command: the file parses, every value is in its vocabulary, the keys are exactly the entry
comments of your batch file.

## Your final message

Under 150 words: how many entries you labelled, and the two or three kinds of entry where the
line between `loud` and `silent` was hardest to draw from the text — they tell us where the
definition is not sharp enough. Your labels will be reviewed and scored; say plainly where you
were unsure.
