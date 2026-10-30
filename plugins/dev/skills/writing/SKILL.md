---
name: writing
description: How what the operator reads is written — a close-out entry, a plan question, a review's finding, a requirements ask, a card request, a proposal, the line of a triage message: ruled from its first lines, in paragraphs and lists, asked only where they could rule the other way, with its recommendation, its premise checked and its price given, and a question back answered in prose. Load it before you write anything the operator will read or answer, whatever its grammar — an entry of the close-out store, a hand-back a loop renders as a document, a document under /dev:document-format, a chat message that puts a batch to them. Not for code, a review file, a plan's phases or a done-record.
argument-hint: "[the text to write or check]"
---

# Writing for the operator

One person reads what the workflow writes them, and how they do it has been read: what they
open, what they skip, what they answer with one word, what they ask back. Those reads are the
whole ground of this skill. Each rule ends with the findings it rests on, numbered as in
`docs/research/operator-reading-synthesis-2026-10-30.md` of the plugin's repo; a rule no finding
supports is not here, and a rule changes on a read, never on taste.

The grammar around the prose is elsewhere and is not restated here: a document Pilot reads has
`/dev:document-format`'s front matter, blocks and sections, and a close-out entry has the fields
and labels of `${CLAUDE_PLUGIN_ROOT}/docs/close-out.md`. This skill is how the words inside
them are written.

## What is read, in what order

**The first lines are the ruling's.** The reader reads the summary and the heading, then the
recommendation, judged for safety; on a doubt, part of the context, "most of the time I'll get
half way"; the rest one time in twenty. So the `summary`, each ask's heading and its
recommendation are written to be ruled from alone, with the context after them and the evidence
after that — present, never cut, never first. By genre, the lines that have to carry the ruling
are:

- a close-out entry: its headline, its proposal or its options with the one recommended, and
  its `Consequence:`;
- a plan question or a review's finding: its headline, its options and `recommend`, or its
  proposal;
- an ask in a document: its heading and the recommendation in the section's first lines;
- a triage item: its line.

What a question about the entry, the wrap-up or a card needs is in the body, on the page with
the lines, where the reader goes only on a doubt (1.1, 1.2, 1.9, 1.10, 2.4, 5.1).

**What must not be missed is the first line, said as such.** "An agent trying to get my eyes on
something that I then don't see … it's not immediately obvious what it feels is important I look
at." What you think the operator must not miss opens the ask, in words — not a label, not a place
in the order, not a sentence in the body. Severity comes to them whatever its likelihood: "High
severity needs to come to me, even if it's very unlikely" (2.8, 4.12, 4.13).

**Nothing is restated.** A proposal that restates the headline, a consequence that restates the
mechanism, a body that retells the plan or the requirement leaves the ask nothing to rule from
and sends the reader into the body for what the line should have said; an account of what you
did, with the choice somewhere in a paragraph, has them asking "what's the decision?" (1.2, 3.5,
4.4).

## The shape of the page

**One point to a paragraph, three to a list.** "Just a single paragraph of over 200 words, that
would be better readable if it would be 3 paragraphs and 2 bullet lists." A paragraph makes one
point and ends before it makes a second; three or more of anything is a list; a number, a
command, a quoted line stands on a line of its own. Length is what the body needs — a cap
produces more, not less — but what is long is structured, never dense (4.1, 4.2, 4.3, 4.5).

**Code only where it is what is ruled on.** A function quoted whole is a wall, and a snippet cut
off is a question back. Code stands in an ask where the text is the thing ruled on — the message
a user will read, the shape they will type, the command they will run — and then whole enough to
rule on. Everything else is named in words: "the route that streams an environment's state", not
a path and a line range (4.2, 4.7).

**Self-contained for a cold reader.** Half the questions that leaned on a handle were not
readable cold, and confused or delegated answers rose with every handle leaned on; "I need
background for this also". Nothing assumes the slice is fresh in the reader's mind:

- no bare id — a decision, a requirement, a card, a finding is named with what it says;
- an id of the run (`P3 r1 F3`, `V10`) is provenance, on its own line, never a reference the
  reader has to follow;
- a citation is a path and a quoted line, never a line number, which moves
  (`${CLAUDE_PLUGIN_ROOT}/docs/spec-tree.md` § Citing a line);
- the fact the choice turns on is in the ask, in a line, not behind it: the questions that
  carried their own numbers were answered in a minute (1.11, 2.3, 4.7, 4.8, 5.4).

## What is asked

**Only what they could rule the other way.** Eight of twelve refinement decisions were
implementation picks whose own alternative line said "loses"; the ones engaged with changed what a
user sees or what the operator runs. The test is the alternative: where yours would read "loses"
or "not worth it", it is not a decision but a pick of yours — made, said in a sentence of the
context with its ground where they could care, and corrected by them on reading (2.4, 4.11, 5.3).

**Every ask carries its recommendation; an alternative only where it is live.** The
recommendation was taken 77 % of the time, and "pick the simple option", "I want to follow your
recommendations" are a reader asking for it to be there. An option is written because the reader
could pick it; one that completes a set or makes rejection explicit ("reject — leave the plan
wrong") was accepted 9 of 9 and rejected 0 of 13, and is not written. The trade-off is the
sentence they disagree with when they disagree, so write it as one; a design the page did not
offer, they bring themselves. A proposal is in a ruling's words — card, fix now, fold into a
slice, close, do it — so that one word back carries it out: half of what they typed was "Agree"
(2.1, 2.3, 2.5, 3.6, 5.8, 6.2).

**An entry takes a position.** "Just a dump of thoughts and ideas. They aren't questions"; "the
agent isn't really taking responsibility for what it's reporting." Substance came back almost
only where a question was asked, every entry is read whatever its fate at a median 163 words, and
the third report in a sitting is handed over unread. An entry that reports and proposes nothing
is not written; one that is written says what its author would do (1.6, 1.7, 2.2, 4.3, 4.4,
5.2).

**A settled item is one sentence, or absent.** "I should not have to see the details. The planner
agent will have this already." A pick of yours is on the page only where they could care — it
changes what a user sees, moves a file between repositories, changes a default they set or a
procedure they run — and then as one sentence with its ground; a premise that no longer holds is
one sentence, what was believed, what is true, what changes; the rest is not on the page (1.9,
4.10, 6.3).

**A card request is a line and a card.** Card requests are never read: "especially in the Card
request ones. I never read those." The ask is one line — what the card would say, and why it is
more than a fix — and the body is the card's text, written for the card and for a reader who
cannot ask back, since nobody has measured whether a card can be ruled from its text alone (1.3,
4.15).

**A batch is one line per item.** The chat message of one line per item, under its fate, with the
questions numbered and each carrying its recommendation, is the triage format that worked: an
eighteen-item run was ruled by numbered reply, and a short list named at a session's close was
ruled at once. The line is the id and the ask in its author's words, shortened to a line — no card
text, which was 56 % of the words of a document hardly read; no label, which predicted nothing;
no note, which drew 3 reactions on 105 items. In a document, the heading is that line (1.8, 4.6,
5.7, 5.8, 6.4).

## What an ask rests on

**A premise is a claim, checked, with its class.** Fifteen questions rested on a false premise
written as background — "Testing complete. I'm connected using SSH right now" — because a premise
inside an option reads as fact. A premise a command settles is checked before it is asked. One
that is not is stated as what it is: read, or witnessed — who checked what against what, with
designed, implemented, deployed and verified kept apart; a link or a capture named with its
version and whether it can be reached, and one that is stale or out of reach said to be so, never
replaced by a confident description. A cause is a claim like any other: shown, or said to be
read. In a close-out entry the class opens the `Provenance:` line, before the body (3.4, 4.9).

**Price it.** What the operator asks back about an entry is what it says, whether it can happen
and how bad it is, and whether the fix is cheap and worth it — "I also don't know what the effort
is to fix this"; "is there maybe not really a problem?" — and some closes are about effort, not
judgment. Advice that traced reach and priced the fix, "B1 is unreachable, not just extreme" with
a six-line fix recommended against, was followed 35 of 41 times. An ask about a problem says, a
line each:

- how it is reached, and what a person then meets, in the deployed shape — in a close-out entry
  its `Consequence:`, which is what is experienced while the entry stands: not "better than
  before", not "none" where a person would notice, not the mechanism again, and `none` said
  plainly where nobody would;
- what the fix takes;
- where the answer changes the slice's size, by how much: "How big is this slice taking the
  answers into account?" sent one back to triage (2.8, 2.9, 3.1, 3.2, 3.3, 5.6).

## A question back

**A question back is answered, not re-asked.** A reframe — "are we just over complicating
this?", "walk me through this", "what's the self action token?", "why would you want to bring
these to me?" — is answered first, in prose that re-grounds the ask: from what was written and
what supports it, quoted, and saying plainly where it does not settle the question. Agreeing is
not an answer, and neither is deriving the claim again. The ask is not put again until they have
said what they think; the re-asks that worked "worked because a page of prose came first" (2.3,
3.2, 3.4, 3.5, 5.5).
