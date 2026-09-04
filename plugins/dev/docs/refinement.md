# The refinement doc — how the interview reaches the operator

`/dev:plan-slice` pins a slice's requirements with the operator before the plan loop runs. The
operator reads a **document** and talks; the session never puts a multiple-choice dialog in
front of them. Read on 49 slices (`docs/research/plan-interview-2026-09-01.md`): the dialogs
were dismissed, answered "I don't know", and re-posed after "let's talk"; the listed
alternatives were chosen 8 % of the time; and the recommendation itself was wrong or built on a
stale premise in a fifth of the questions — the operator needs its grounds checked, not a menu.

The document is **the PO's page, not the planner's notebook.** The first five docs written to
this contract (`docs/research/refinement-read-2026-09-03.md`) were 27–35 KB grounding logs —
functions quoted whole, a `file:line` per claim, half of each doc a premise-by-premise
verification — and the operator, reading them cold the next morning, could not follow them:
three were agreed in one line, two were delegated ("I trust you get this right"), and the
verdict was "a wall of text I can't make heads or tails of … I really don't believe it has
value." The grounding is the session's work and the plan's input; the operator sees its
conclusions, never its evidence.

Three parties, one artifact:

- **The interactive session** (whatever model the operator runs the skill at) grounds the
  slice, forms its recommendations, decides what is a decision and what it settles itself, and
  collects the **material** below. It talks with the operator, records every ruling in
  `plan.md`'s requirements/rulings section in the operator's words, and carries the grounding
  that binds the plan into that same section for the plan-writer. It writes no decision prose
  of its own.
- **The `refinement-writer`** (Fable, a sub-agent of the session) writes `refinement.md` — the
  one operator-facing document — **from** the material, selecting what the operator needs to
  rule and leaving the evidence behind. It writes only what the material supports; it does no
  research and repairs no gap.
- **The operator** reads a page, comments under a decision or replies in chat by number, and
  rules.

## What is a decision

A decision is put to the operator only where they could plausibly rule the other way: the
choice changes something a user sees (the line `/ls` prints, the message a Windows desktop
shows), an outage window or a procedure the operator runs (which repo is pushed first, a
controller down for minutes on each stage), a risk they carry (a homelab literal surviving one
more release), or a preference the material cannot settle. The test is the alternative — if the
writer's own alternative line would read "loses" or "not worth it", it is not a decision. The
first five docs put twelve decisions and the operator engaged with four; the other eight were
engineering choices the session could rank on its own grounds — strict versus lenient argument
parsing in a test stub, a capture script versus attached fixtures, a request header versus a
process lookup, a new boolean versus reusing an old one, a flat map versus a nested one, an
environment variable versus a config key — and drew "I don't have the faintest about the other
one. I assume you know what you're doing." Those are **settled by the session**: made, stated
in one sentence with their grounds where the operator could care, and corrected by the operator
if they disagree on reading. Most slices have one or two decisions; a slice with none gets a
doc that says so.

Neither form carries what the slice does not leave open. A decision is what its numbered
requirements — their own "open for the planner" items included — genuinely leave undecided. A
matter the slice merely touches (the estate-wide sweep a change would make possible, which
phase owns a rewrite) is settled by the session; three questions at once about surfaces the
slice touches read as scope creep and cost the operator a discussion they never asked for ("I
have no idea what we're discussing. I thought we were just removing duplication between
images."). A call the operator delegated in so many words ("if you feel a few would be nice, do
move them") is executed and shown — the list, the one item the session would argue about —
never converted back into a question. A prose nit (a comment or doc sentence that restates or
misstates) is grounded and, where the project classes the edit as ad hoc work, made now and
reported; otherwise it rides as a requirement whose ruling reads **culled, not reworded**, so
the writer deletes or narrows the clause instead of negotiating with it. Nine doc nits
presented as a decision matrix is the shape the operator stopped: that slice went from nine
requirements to no phases once five edits shipped in-session and three closed on the evidence.

**Agree-or-comment**, in chat, carries the single decent choice that has impact — if the
honest alternative would read "reject — leave the plan wrong", it is not a decision, it is a
consequence to explain and confirm (its form is below).

## The material

What the session hands the writer, in the dispatch prompt. The material is where the evidence
lives — the writer reads it to select, and the doc carries none of it:

- **The ask** — `slice.md`'s path; the slice in two or three sentences for someone who last saw
  it a week ago; what is already settled and by what (a ruling, a decision record, a prior
  slice); and every requirement whose premise no longer holds (the sentence it targets removed
  by an earlier slice, the file it names never existed), each with what changes as a result —
  the doc opens with those as settled by the facts, for the operator to confirm.
- **Size** — the phases this comes to and the repos it touches. Slice 183 ran a clean
  interview and went back to triage on a number the interview never surfaced.
- **Per decision** — why it is the operator's (the test above); where it comes from (the
  requirement, card or finding); what the session found, as claims — each verified, with its
  evidence kept here, or marked unverified; the recommendation and its trade-off (what it gives
  up, why that is acceptable); the one alternative the operator could plausibly pick, with the
  trade-off that makes it lose; the impact if the recommendation is wrong (data loss, breakage,
  extra work, nothing).
- **Settled by the session** — each engineering call it made, one line with its grounds, and
  whether the operator could care: it changes something a user sees, moves a file between
  repos, changes a default the operator set, or changes a procedure the operator runs. The rest
  is routine, and the operator learns it from the plan.
- **Open facts** — what only the operator knows: a preference, a history, whether an archive
  was deliberate.
- **On a second round** — the loop's questions file, `plan.md`, and what settled since the
  first doc.

A claim the session did not verify goes into the material as unverified; if a recommendation
rests on it, the writer says so in the doc, in words. The session's targeted exploration ("who
reads the session title" — one focused sub-agent per question, never a fan-out) is where
verification happens, before the writer is dispatched, not after the operator has read a
premise as fact. The evidence that binds the plan — a premise correction with what it changes,
a verified fact a ruling rests on — goes into `plan.md`'s rulings section when the session
seeds it; that is the only place the plan-writer reads it. Nobody downstream reads
`refinement.md`.

## The doc

`<slice>/refinement.md`, written by the writer, committed with the slice as the interview's
record — the same role `plan_review_r*.md` plays for the review round. The rulings live in
`plan.md` for the planner; the doc holds what was put to the operator and, under each
*Operator* line, how they ruled — in their words, whether they wrote it there or said it in
chat. Slice 199's doc went to the record with one decision still reading *agree, or comment
here* beside a plan that recorded the agreement, and another still recommending what the plan's
rulings had reversed; a reader checking a ruling against the refinement that produced it found
the opposite advice and no sign it had been overruled. Shape:

```markdown
# Slice NNN — refinement

<one to three paragraphs: what the slice is and why, for a reader a week away; what is already
settled and by what; a premise that no longer holds, one sentence each with what changes; what
this doc asks, or that it asks nothing; the size in phases and the repos touched>

## D1 — <the decision, as one sentence a cold reader can parse>
<why this is the operator's call and where it comes from — a sentence or two>
<what the session found, as prose: the two or three facts the choice turns on, said in words>
**Recommendation.** <the shape; then the trade-off — the sentence the operator disagrees with
when they disagree>
**The other way.** <the alternative the operator could plausibly pick, one line, with what it
costs>
**If this is wrong.** <one line>
**Operator.** _agree, or comment here_

## Settled by the session
<one sentence per item, only those the operator could care about; the routine ones are absent>

## Open facts — questions only you can answer
**F1.** <the question, plain, no options; in a few words, what the answer settles>
**Operator.** _answer here_
```

Writing rules — the reader is the PO, a week away from the slice, deciding from the page:

- **No code, no handles.** No fenced blocks, no `file:line`, no card numbers, decision ids or
  requirement numbers: things are named in words ("the route that streams an environment's
  state", "the card that reported the Windows share"). The one exception is text the operator
  is ruling on verbatim — a message a user will read on screen, a config shape they will type.
- **Short.** The introduction is one to three paragraphs; a decision is a few paragraphs, about
  250 words; a settled item is one sentence; the whole doc reads in five minutes. Context, not
  volume — what the operator needs to judge, not what the session did to get there.
- **Recommendation first, one alternative at most.** The trade-off is the sentence the operator
  disagrees with when they disagree — write it so it can be. An alternative that loses on the
  material is not listed; a decision with no live alternative is a settled item.
- **A claim a recommendation rests on that the session did not verify is said so** in the
  decision's prose ("not verified: …") — never smoothed into a fact, never dropped.
- **Fact questions are plain questions, each with its own answer line.** No options on "do you
  ever kill an env pod by hand?"; numbered like the decisions, an *Operator* line under each — a
  fact that sits as a bullet reads as a remark: slice 197's operator answered both decisions and
  neither fact, and asked whether the bullets were questions at all.
- **Second round appends.** New decisions are new `D` entries after the existing ones, opening
  with where the plan now stands; an earlier entry's body is not rewritten. The writer never
  fills an *Operator* line — a ruling, and a ruling that moves, is written there by the session
  (below).

## The walkthrough

The writer's receipt is the walkthrough: the session posts it in chat as it came back — one
line per decision (title, recommendation, impact), the settled items the doc carries, the open
facts, the doc's path, and how to answer: comment in the file under each *Operator* line and
say so, or reply here by number; "agree" takes every recommendation. The session then reads the
comments back, records each ruling in `plan.md` (in place — a ruling that corrects an earlier
one replaces it), and confirms a ruling that changed a decision in one line — "D3 is now …;
agree?" — never as a new fork. A ruling given in chat is written under its *Operator* line in
the doc as well, in the operator's words, so no placeholder outlives a ruled decision or an
answered fact; the recommendation above it stands as it was put, and that line is where a later
reader learns the doc was overruled and by what. A ruling that moves later — a second-round
answer, a review adjudication that reverses a decision — replaces the line. A blanket "agree"
or "agree to everything" in chat is a ruling on every decision, and the session writes it under
each *Operator* line itself — the operator never edits the file to make the record match what
they said in chat; an open fact has no default and stays open until it is answered.

## Agree-or-comment

In chat, for the single decent choice with impact (a push order that cannot be otherwise; a
removal that goes dark on both stages): what is going on, what the session will do, the
consequence if that is wrong, and "Agree?". No options, no accept/reject pair. The same form
carries:

- **Review adjudication.** Every blocking finding of a review round in one message, each with
  its default disposition and what it changes in the plan; the operator's "agree", or a comment
  on the ones they object to, is the ruling. The findings are shown with their grounds — of 13
  accept/reject findings none was rejected, but eleven adjudication answers were typed — never
  applied unseen. The `--fixes-applied` mechanics ([plan-loop.md](plan-loop.md)) are unchanged.
- **A premise correction.** When grounding or the review overturns something the operator was
  told — stated first, with what it changes, before anything is re-asked.

## Talking

- A reframe ("can't we just …", "are we over-complicating this?") or "walk me through this" is
  answered in prose that re-grounds the decision. The decision is not re-posed until the
  operator has said what they think.
- A question in the operator's answer is a question; it is answered before anything else is
  asked.
- What the operator says in chat is the ruling in their words; the session records it, it does
  not reshape it.
