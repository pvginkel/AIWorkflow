# The refinement doc — how the interview reaches the operator

`/dev:plan-slice` pins a slice's requirements with the operator before the plan loop runs. The
operator reads a **document** and talks; the session never puts a multiple-choice dialog in
front of them. Read on 49 slices (`docs/research/plan-interview-2026-09-01.md`): the dialogs
were dismissed, answered "I don't know", and re-posed after "let's talk"; the listed
alternatives were chosen 8 % of the time; and the recommendation itself was wrong or built on a
stale premise in a fifth of the questions — the operator needs its grounds, not a menu.

Three parties, one artifact:

- **The interactive session** (whatever model the operator runs the skill at) grounds the
  slice, forms its recommendations, and collects the **material** below. It talks with the
  operator, records every ruling in `plan.md`'s requirements/rulings section in the operator's
  words, and seeds the plan. It writes no decision prose of its own.
- **The `refinement-writer`** (Fable, a sub-agent of the session) turns the material into
  `refinement.md` — the one operator-facing document — and returns a receipt. It writes only
  what the material supports; it does no research and repairs no gap.
- **The operator** reads `refinement.md`, comments under each decision or replies in chat by
  number, and rules.

Two forms, one test between them. **The doc** carries every decision where the recommendation
gives something up the operator might weigh differently. **Agree-or-comment**, in chat, carries
the single decent choice that has impact — if the honest alternative would read "reject — leave
the plan wrong", it is not a decision, it is a consequence to explain and confirm.

## The material

What the session hands the writer, in the dispatch prompt (files are pointed to, quoted lines
are quoted — the writer has `Read` and will pull what it cites):

- **The ask** — `slice.md`'s path; what is already settled and by what (a ruling, a decision
  record, a prior slice); what this doc decides.
- **Size** — the phases this comes to and the repos it touches. Slice 183 ran a clean
  interview and went back to triage on a number the interview never surfaced.
- **Per decision** — where it comes from (the requirement, card or finding, so the writer can
  quote it); **what the session found**: each premise as a claim with its evidence — a
  `file:line`, a command and its output, a card's text — or marked unverified; the
  recommendation and its trade-off (what it gives up, why that is acceptable); the alternatives
  the session considers live, or none; the impact if the recommendation is wrong (data loss,
  breakage, extra work, nothing).
- **Open facts** — what only the operator knows: a preference, a history, whether an archive
  was deliberate (with the card's link).
- **On a second round** — the loop's questions file, `plan.md`, and what settled since the
  first doc.

A claim the session did not verify goes into the material as unverified; the writer will say
so in the doc. The session's targeted exploration ("who reads the session title" — one focused
sub-agent per question, never a fan-out) is where verification happens, before the writer is
dispatched, not after the operator has read a premise as fact.

## The doc

`<slice>/refinement.md`, written by the writer, committed with the slice as the interview's
record — the same role `plan_review_r*.md` plays for the review round. The rulings live in
`plan.md`; the doc holds what was put to the operator and their comments on it. Shape:

```markdown
# Slice NNN — refinement

## Where we are
<the ask in the operator's words; what is already settled and by what; what this doc decides;
the size in phases and the repos touched>

## D1 — <the decision, as one sentence a cold reader can parse>
**Where this comes from.** <the requirement, card or finding — quoted or expanded; never a
bare R2, #724, D191 or file:line>
**What I found.** <the premises, each a checkable claim with its evidence; a claim the
material left unverified says "Unverified:" in front of it>
**Recommendation.** <the shape; then the trade-off — the sentence the operator disagrees with
when they disagree>
**Alternatives.** <only if one is live: one line each with the trade-off that makes it lose;
otherwise "none worth the read">
**If this is wrong.** <one line>
**Operator.** _agree, or comment here_

## Open facts
<plain questions, no options>
```

Writing rules — the reader has not looked at the slice for a week:

- **Recommendation first; one page per decision at most.** Context, not volume: a dialog
  already cost 2–4 KB per read. Alternatives that do not add value are omitted, not listed.
- **Premises are claims.** They sit under *What I found* where they can be refuted, never
  inside a recommendation as background.
- **No bare handles.** Requirement numbers, card numbers, decision ids and `file:line` are
  expanded or quoted at the point of use.
- **Code in full**, in fenced blocks — nothing is cut to fit a label.
- **Fact questions are plain questions.** No options on "do you ever kill an env pod by
  hand?".
- **Second round appends.** New decisions are new `D` entries after the existing ones,
  opening with where the plan now stands; a settled entry is not rewritten. A reversed ruling
  is recorded in `plan.md`, not by editing the doc.

## The walkthrough

The writer's receipt is the walkthrough: the session posts it in chat as it came back — one
line per decision (title, recommendation, impact), the open facts, the doc's path, and how to
answer: comment in the file under each *Operator* line and say so, or reply here by number;
"agree" takes every recommendation. The session then reads the comments back, records each
ruling in `plan.md` (in place — a ruling that corrects an earlier one replaces it), and confirms
a ruling that changed a decision in one line — "D3 is now …; agree?" — never as a new fork.

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
