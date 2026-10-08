---
name: inbox
description: Sort the tracker's inbox with the operator, across every project at once — the new cards nobody has judged, the cards the host's unattended pass handed back, and the operator's own action queue — and put them to the operator in one chat message, each on a line under where it goes next (left for the pass, pre-filtered for a slice, theirs, closed, deferred), with the one act or answer each held-back card waits on; then record their rulings on the cards. Tracker-only — no spec repo, no slices filed, no code opened; the project's /dev:triage takes the pre-filtered batch from here. Invoke it whenever the operator asks to go through, clean up or sort the inbox, the new cards, their action queue, or what the pass handed back — they will not necessarily name this skill.
argument-hint: "[project keys or card ids to scope the sitting]"
---

# Inbox

Two things empty a project's intake queue without the operator reading every card: the host's
**unattended pass**, which takes from the queue whatever is in its lane and hands the rest back
under a **hand-back mark** that stands until the operator acts, and `/dev:triage`, which takes
one project's batch — pre-filtered by the operator when they have — and files slices. Between
them the inbox fills: new cards neither has judged, and hand-backs waiting on something only the
operator can give, named in a comment nobody re-reads. Beside it sits the operator's own action
queue, where what they have delayed waits for a free hour. This sitting is how the operator reads
all of it — every project at once, from whatever environment they are in — with the cards sorted
for them: where each goes next, what each held-back card needs from them before it can go
anywhere, and their own actions in the same message, so the time they give the inbox is time
they can action them. It writes rulings to the tracker and nothing else.

**Nothing here needs a project.** No preflight, no spec repo, no `.aiworkflowrc`: the tracker is
the only thing read or written, and the sitting runs from any environment. The tracker — how one
project's cards are told from another's; how the intake queue, the pre-filtered batch, the action
queue, the dispositions and the pass's marks are written; where the pass's lane is written —
comes from your host convention (`${CLAUDE_PLUGIN_ROOT}/docs/project-contract.md`, section 3).
**Load it before the first tracker call** — where the host ships it as a skill, invoke the skill:
nothing in the pipeline loads it for you.

**The clerk's bar is `/dev:triage`'s**, and it is not restated here: you read each ask as its
author wrote it and recommend; the operator decides — no card is closed, deferred or moved on
your judgment alone; a card's diagnosis is a claim; a fate that turns on a fact only a repository
can show is fetched by a read-only sub-agent asked that one question, with *cannot determine* an
allowed answer. Two things triage does and this sitting does not: the standing-decisions check,
which is a project's and waits for its triage, and the Solution Known litmus — the mark and the
sweep are triage's (its step 8), and the inbox leaves them alone.

## Where a card goes

- **Left for the pass** — the card stays in the intake queue, its mark (if any) off, the ruling
  on it. The pass reads the queue nightly and takes what is in its lane; a card it hands back
  comes back here under its mark, with the pass's reason.
- **Pre-filtered for a slice** — the card moves to the pre-filtered state, its project's
  `/dev:triage` batch. The pass does not read that state; triage does, and reads the card afresh.
- **The operator's** — the card waits on an act only they can perform, or is an action of theirs
  they keep (*yours*, below). A kept action sits in their action queue.
- **Closed** (resolved when they did it, rejected otherwise) and **deferred** — the dispositions
  the convention names.

## Procedure

### 1. Collect

Pull, across every project — or the projects or cards the operator scoped the sitting to — the
**intake queue**, **every open card carrying a hand-back mark**, whatever its state or type (a
mark means *waits for the operator*, and this sitting is them), and **the operator's action
queue**, every open card in it whatever its state. Read what you pull in full, project by
project, in the batches the tracker tool allows. Two kinds of card are not items: the slice
cards, and the close-out marker cards (`[NNN] close-out: …`), which say a report is waiting —
count them per project for the message and leave them to `/dev:close-out`. Nothing is dumped to
disk: the tracker is the record, a sitting that stops leaves what it did not reach as it was,
and the next one reads it.

Before judging, **read the pass's lane** from where the convention says it is written — what it
takes, what it hands back, what it never touches — so that *pass* is proposed only for a card the
pass will take. A hand-back comment names the item of that lane the card failed on and what has
to happen first; on a held-back card that comment is the first thing you read.

### 2. Judge — where each card goes next

One fate per card, from its text and comments alone:

- **Pass** — in the pass's lane as written; or in it once the operator gives here what the
  hand-back asked for — an answer to the pass's question, a guess confirmed, a choice made —
  which becomes the ruling on the card; or in it already, because what it waited on has
  happened: a blocker card since closed (one tracker query — check it yourself), an act the
  operator's own comment says they did. A card the lane excludes by nature — the pass's own
  repository's, a project it is told to keep off, a card marked as crossing repositories — never
  takes this fate, whatever its size.
- **Slice** — slice-sized, a design to make, work across environments, a boundary the pass never
  crosses: pre-filtered for its project's triage. A card in a project the pipeline is not
  onboarded on says so on its line; the route is still the operator's.
- **Yours** — an act only the operator can perform before anything can take the card: a secret
  minted or vaulted, a production switch, a change on a repository no environment holds, a
  decision that is theirs alone. Its line names the act in one clause. The operator may do it in
  the sitting and say so — the card then takes *pass* or *slice*, with the result written on it
  — send it to their action queue, or leave it held: the mark stays, or goes on, with the act
  named, and the next sitting asks again.
- **Close** — a duplicate (name the card), moot, or ruled out. Guarded as triage guards it: the
  source's own words, an operator ruling, or a checked fact — never your belief about the system.
- **Later** — deferred, with the reason.
- **Question** — a card vague *as a request*: the one question the operator can answer from
  memory, numbered, with your recommendation; its fate follows the answer. A question only code
  can answer is not asked here — it is the planner's, and the card is a *slice*.

A card the pass handed back as **needing clarification** carries the pass's question: that is the
question on its line, and the operator's answer, written on the card with the mark taken off, is
what sends it back to the pass.

An **operator action** is theirs by type, and its line says how long it has waited and what, if
anything, a session could do of it. The words are the same: *done* when they do it in the sitting
(it closes resolved); *pass* when it turns out a session can do it after all — the card becomes a
task and is left for the pass; *slice*; *close* when it is no longer needed; *later*; and *yours*
— kept, which for an action is the default and costs them a word.

### 3. Check — only what a fate turns on

A tracker fact — a blocker's state, whether the card a duplicate names is open — you check
yourself. A fact only a repository can show — whether the thing is already done, whether the
claim still reproduces — goes to one read-only sub-agent per card, in parallel, briefed with the
one question quoting the card and nothing else: never "assess this card". Fold the verdict into
the card's line, and write it on the card as a dated comment marked as inbox research, so it
outlives the sitting.

### 4. The message

One chat message, however long the inbox — never a dialog, never a document — by project:

```
<project> (N new, M held back, A of your actions; K close-out reports wait — /dev:close-out there)
  Pass:   <id>  <the ask, on one line>
          <id>  <the ask> — held back <date>, waited on <card>, closed since: mark off
  Slice:  <id>  <the ask>                                                        (Q1)
  Yours:  <id>  <the ask> — <the act: mint the token, name its path on the card>
          <id>  <the ask> — your action since <date>; a session could <the mechanical part>
  Close:  <id>  <the ask> — duplicate of <id>
  Later:  <id>  <the ask> — <why>
<project> (…)
  …

Q1 (<id>). <What the card asks.> <The question?> I'd <recommendation>.
```

Every card exactly once, on one line: its id, the ask in the card's words shortened to a line
(the title is part of the ask), and for a held-back card what it waits on; no card text, no
label, no note — the operator opens a card when they want it. The questions numbered, each with
the fact it turns on and your recommendation. The operator answers in chat, in their own words:
**go** approves the scheme as it stands; **pass**, **slice**, **close**, **later** and **yours** on
a card move it; **done: <what they did>** on a *yours* card is the act performed, and the card
takes the fate that follows — for an action of theirs, that is closed resolved; an answer to a
question is the ruling as given, never your proposal. **close** and **later** are binding, as at
triage. One pass per operator message; re-present only what moved.

### 5. Record

When nothing is open, write the rulings — to the tracker, and nowhere else. Every card that moves
gets one dated comment, `Inbox <date>: <the ruling, in the operator's words>`, in the same write
as its move:

- *pass* — the card stays in the intake queue; its hand-back mark, if any, comes off; an
  operator action is retyped to a task. The comment is what the pass reads as the settled ask.
- *slice* — to the pre-filtered state, as a task; a mark comes off.
- *yours* — to the operator's action queue when they said so, and a kept action stays there (a
  new one moves into it); otherwise the mark stays, or goes on, and the comment names the act.
- *done* — the result on the card (the path, the account, the answer), then the fate that
  follows; an action they performed closes resolved, the comment saying what they did.
- *close* — the rejected disposition; *later* — deferred.

A card the operator filed is theirs in their words: never rewrite its description — the comment
carries the ruling. A session-authored card's text is yours to tighten only where a ruling
rewrote the ask, with the original kept below a rule, as triage does. Delegated writes run on
disjoint card sets and are verified on the tracker by spot check, never from the agent's report.

### 6. Close the sitting

Notify per the host convention — `Inbox <date>: N cards — K left for the pass, M pre-filtered
for slices (<projects>), J closed, L deferred, P wait on you (<ids>), A actions kept.` — name
each project whose pre-filtered batch grew ("run /dev:triage in <project> when ready"), and
stop. The pass's next run, a project's triage and the operator's own acts are their moves, in
their own time.
