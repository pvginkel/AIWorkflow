# The triage status document, read — 2026-09-29

The operator: "I feel like the triage reports have little value … what's really decided in the
documents? I hardly read them. … My theory is that a QA in the session plus a proposed slice
scheme should cover any decision making I currently do." This is the read that tested the theory,
and what was ruled on it.

**Ruled 2026-09-29/30:** the status document is replaced by one chat message — every item on one
line under its proposed fate, the questions numbered, the proposed slices — and nothing else in
the process changes. Built as 0.9.60. The operator's scoping, when a route change was folded in:
"The only thing I'm requesting is to change the format of the triage document. The triage
process stays unmodified (you're still bundling slices and putting the high level asks to me)."

## Corpus and method

The last 20 `/dev:triage` runs, 2026-09-02 → 09-28: 14 KubeCoder, 6 Ansible, 181 items, 67.7k
words of status document. The documents are deleted at close-out, so each run was read from the
spec repo's git history — the first committed version (as presented) against the last (as
ruled) — beside the operator's side of the interactive session that made the run's commits:
their messages, the dialogs and their answers, the timing. Every ruling was classified by hand
into one of six classes; the classification is `data/triage-rulings-2026-09-29.json`, the tool is
`tools/triage_readout.py` (`runs | rulings | sessions | cost`).

## What the operator did with 181 items

| Class | Items | |
|---|---|---|
| `agree` | 80 | assent with no content ("Agree", "The rest is agreed", "Go") |
| `answer` | 44 | answered a question the session put |
| `cull` | 23 | closed, parked, or moved off the slice route |
| `none` | 17 | no ruling at all (16 in the run where they said "I don't need to review the rubrication") |
| `bounce` | 11 | handed back: "please advise", "I don't know", a counter-question |
| `steer` | 6 | content on an item that carried no question |

By whether the item carried a `Question:` or `Collides:` line:

| | Items | agree | answer | cull | bounce | steer | none |
|---|---|---|---|---|---|---|---|
| asked | 72 | 8 | 41 | 13 | 10 | — | — |
| not asked | 109 | 72 | 3 | 10 | 1 | 6 | 17 |

So the substantive input — 44 answers, 23 culls, 6 steers — came from three places, none of
which needs the document:

- **The questions.** 70 items carried one; 33 of those were collisions with a standing decision
  (the 0.9.24 check), and those produced the real rulings: overrule, the record stands, a
  redesign. The collision check is a question generator; it survives any format.
- **The culls.** 23 items. A proposed fate per item covers them.
- **The slice scheme.** Proposed and ruled in chat in every run; written into the document once
  (the 37-item run, at the end). The operator corrected it in 10 of 20 runs.

## What the document's own machinery contributed

- **The labels predicted nothing.** Culled: 2 of 12 nit picks, 2 of 12 majors, 3 of 69 minors,
  5 of 46 improvements. 8 nit picks went ahead. Seven labels changed after the operator's pass,
  one by an override ("It's not a nit"). Nothing downstream reads the category: `slice.md`'s
  headline and the README line carried it, nothing consumed it. Asked to pick a headline
  category on 09-06: "I don't know. Does it matter?"
- **The card text** was 56 % of the words. The 12.7k-word Ansible document (37 items) was ruled
  within 28 minutes of its commit; the 7.8k-word one within 18. At reading speed those are 51
  and 31 minutes.
- **The `Note:` lines** — for the exception where a label hides stakes — sat on 105 of 181 items
  and drew three reactions.
- **The seam** (adjudicate now, dispose later) was used once, on 09-08.
- **`triage_verbatim.py`** (663 lines, 946 of tests) existed to repair what the operator's editor
  did to the document on save.

## Where the operator ruled

In the document in 10 runs — nearly every full-queue run of eight or more items — in chat in 9,
skipped in 1. Where they ruled in the document, half of what they typed was the word "Agree", 58
times. The 18-item run of 09-02 and the second pass of the 37-item run were ruled by numbered
chat reply. The last five runs (09-25 → 09-28) were all ruled in chat. Nine of the 20 runs were
discussion-born — triage invoked mid-conversation to file what the chat had just decided — and
there the document transcribed rulings already made; only the collision check added anything.

Dialogs (`AskUserQuestion`) worked for grouping picks; on design questions the operator typed
free text or dismissed the dialog (8 of 19 questions). The message's questions are numbered
prose, answered in the operator's words.

## Cost

About $5.50 and 14 machine-minutes a run (the triage window of the session, sub-agents
included; $111 over the 20). The case for the change is the operator's attention, not cost.

## What the read did not change — observations, not rulings

The operator still steers the scheme, and since the seven-phase rule (0.9.37) the corrections
are about other things: a Solution Known card left waiting for the five-card sweep floor
("I'd prefer we progress everything in this run", 09-28; "Fold into the kc project slice" over
the recommended wait, 09-24); a handover of straightforward changes worked outside a slice, asked
for on 09-14, 09-23 and 09-24; and "unrelated asks are never bundled to reach a number",
overruled once ("It's a sweep", 09-28). None of these is part of the format change. The handover
was put to the operator as a collision with the settled "no lanes" ruling and withdrawn from the
build at their scoping; the lanes ruling stands, and the operator asks for a handover directly
when they want one.
