---
name: document-format
description: The format of a document Pilot, the project manager, reads — its front matter, its decision, question and action blocks and their answer lines, an ask written with the lead first and one ask to a section, and what Pilot refuses as a fault. Load it before you write or revise a document you will register with Pilot through its `register_document` tool, and before you write an item, a document or an answer line in Pilot's store. Not for a document nothing registers with Pilot.
argument-hint: "[the document to write or check]"
---

# Document format

Pilot reads Markdown. A document it reads — a decision document a work item writes and registers
with Pilot, an item or a document in Pilot's store — is prose for a person around fenced blocks,
the asks. Pilot's record reads the front matter and the blocks, and nothing else: the prose is the
writer's and is never parsed. This skill is that grammar as a writer needs it, and how an ask is
written so that the person answering reads it once. The grammar whole, as Pilot's engine reads
and writes it, is PilotApp's `docs/block-dsl.md`. Argument (optional): the document to write or
check against this page.

## An ask

**The lead, then the evidence.** The first screen of an ask says what is asked, what you
recommend, what changes for the person and what happens once they answer. The diagnosis, the
endpoints and the fuller comparison stay right under it, or behind the document in an attachment.
The lead fits what the reader has to do:

- *decide*: the choice, the recommendation, and the consequences that tell the options apart;
- *do*: the exact step, where, and what result to report back;
- *judge a look*: a working preview or a real capture, the change pointed out;
- *verify*: the real entry point and one concrete case to try, Works or Doesn't;
- *understand*: the result, and what still qualifies it.

Write the smallest form that is enough: these are not five templates. Keep designed, implemented,
deployed and verified apart, and say who checked what against what. A link or a capture is real,
its version and its access named; one that is stale or out of reach is said to be so, never
replaced by a confident description. `for` goes to whoever can judge — the reporter checks the
fix, the operator picks the mechanism — not to whoever is a member or wrote it.

**The ask's shape.**

- The need first, in one line: what has to be possible, for whom, by when.
- Then the tool that exists already: the capability, grant or mechanism in place that answers the
  need, named plainly. Building something is the deviation, and an ask that proposes building
  says why the existing tool is not enough.
- Options with their consequences, the recommendation marked, what it optimises for and how sure
  you are of it.
- The operator's standing preferences applied, those you know of: the project's handbook, which a
  work item's brief carries, and the project's own docs. An ask that runs against a known
  preference is reframed before it is written, never put as it stands.
- One ask per block. A routing — card it, fold it, fix it now — is never bundled with a
  substantive recommendation.

## A document of more than one ask

Pilot shows an ask it has settled as one line, so a document of several blocks is written section
by section:

- One ask per heading section, its block last in it.
- The context the asks share goes before the first ask's heading.
- No heading inside an ask: its sub-structure is run-in heads (`**Cost.** …`) and lists.
- The heading names the ask in one line. Once Pilot has answered or deferred the block, the
  section collapses to that heading, the answer and the answer's note, which is the whole of what
  the operator reads of it.

A block's section starts at the nearest ATX heading (`#` to `######`) before the block, outside
any fence, the title's own heading counting as none, and runs to the line before the next heading
of the same or a higher level, else to the end. It is the block's own only when it holds no other
block, one under a sub-heading included; no heading further out is tried. A setext heading, an
empty `##`, `#tag` and a line indented four spaces are no heading, and open or end no section. A
document that departs from this loses only the collapse: no fault, no gate.

## The front matter

Optional, and first: a line `---`, a YAML mapping, a line `---`. A first line `---` with no
closing `---` opens no front matter. The keys Pilot reads, any other ignored:

- `title`. Without it the title is the text of the first ATX heading outside a fence, else there is
  none. Give one either way: a registered document is shown by its file's name until it has one,
  and a save Pilot makes of an item without one is held.
- `summary`: on a document of more than one ask, what it is about, in one line and with no
  counts. None on a document of one ask.
- `step`: the id of the plan task the document serves. A work item's brief names it; in Pilot's
  store the task ids are `plan.json`'s.
- `urgent`: `true` or `false`.
- `for`: the handle of the person who should answer, whoever can judge (above).
- `slug`, read in the draft only: the slug the project takes when it is created. Lower-case
  letters, digits and hyphens, not starting with `draft-`, and no other project's. A draft without
  one is no fault.

## Blocks

A block is a fence whose info string is the block's kind and its local id:

````markdown
```decision id=D1
options:
  - Nightly: one run at 02:00
  - Hourly
recommend: Nightly
```
````

- **The fence** is a line of three or more backticks or tildes, indented up to three spaces. A line
  of the same character, at least as long, indented up to three spaces and with nothing but
  whitespace after it, closes it.
- **The kind** is `decision`, `question` or `action`, in lower case. A fence whose info string
  starts with any other word is a code block the record passes over, unless it carries `id=`,
  which is a fault. To show a block as an example, quote it inside a longer fence, as above.
- **The local id** follows `id=`, with nothing after it, and is unique within the document: `D1`,
  `Q2`, `A1` and the like. The block's id is `<item id>/<local id>`.
- **The body** is a YAML mapping in block style, one key to a line: never a flow mapping (`{…}`),
  never a key twice.

| Kind | Takes |
|---|---|
| `decision` | `options` with an optional `recommend`, or `proposal`; `type: confirmation` with `because`; `check` |
| `question` | `default` |
| `action` | `options`, `check` |

- `options`: a list, each entry a bare label (`- Yes`) or a label with one line of text
  (`- Nightly: one run at 02:00`). A label holding a colon is quoted
  (`- "Plan B: hourly": one run an hour`). No two options share a label, compared trimmed and case
  kept.
- `recommend`: the label of the option recommended.
- `proposal`: what is proposed, in place of options; never beside `options` or `recommend`.
- `type: confirmation`: a decision asking the operator's go on its `proposal`, on the grounds
  `because` names: a confirmation reason's code, from `reference.json` (below). Only Pilot writes a
  confirmation; a work item that wants a go writes a decision with a `proposal`.
- `default`: a question's suggested answer.
- `check`: read and kept, never acted on.

An action asks a person to do something with their own hands: its section says the step, where,
and what to report back, and its `options` are what they can report, such as `Works` and
`Doesn't`.

**Values are read as written.** A body is YAML read with no implicit typing, so every scalar is the
string written — `answer: Yes` matches the option `- Yes`, and `answer: 2` is `"2"` — trimmed, and
an empty one is absent. A list or a mapping where one value is wanted is a fault. Quote a value
YAML would read as something else: one holding `: ` or ` #`, or opening with a quote, `- `, `[`,
`{`, `&`, `*`, `!`, `|`, `>`, `%`, `@` or a backtick. A value of several lines is a literal block
(`|`). A raw carriage return, U+0085, U+2028 or U+2029 within a line of a body or the front matter
is a fault, since YAML breaks a line there: write it as its escape, `\r`, `\x85`, `\u2028` or
`\u2029`, in a double-quoted value.

### The answer lines

Every kind also takes the answer lines, which the record and Pilot write:

- `answer`: an option's label, `Agree` to a proposal, `Yes` or `No` to a confirmation, free words,
  or `deferred`;
- `by`: who answered, a handle; `agent` is Pilot. A block whose `by` names a person holds the
  record's answer; one with `by: agent`, or with no `by`, holds the agent's;
- `at`: when it was answered; `done`: when an action was done. Each is an ISO 8601 date and time,
  one without a zone read as UTC, and is written in UTC to the second (`2026-10-12T09:40:00Z`);
- `note`: words that go with the answer, or what was pasted back on an action's Done;
- `via`: how a person's answer came, the record's to write;
- `to`: with `answer: deferred` only, and required with it: a task of the plan by its id, or `plan`
  for the plan itself.

**A work item writes none of them.** Its asks reach the person through Pilot, and once every one
is answered the answered file comes back in place, its answer lines written in.

**Pilot's own answer** is `answer`, `by: agent` and `at`, then `note` and `to` where given, in that
order; an action's Done is `done` and `by`, then `note`, the paste-back: what was done and what was
seen. In Pilot's store the scripts its `CLAUDE.md` names write them, and are preferred to a hand
edit. **The note stands on its own**: it says why in words that need nothing around them, since a
section whose answer is Pilot's collapses to its heading, the answer and the note, the operator's
first read of it.

````markdown
```question id=Q1
default: The first Monday of the month
answer: deferred
by: agent
at: 2026-10-12T09:40:00Z
note: The send day is settled with the schedule task, once the first issue has gone out.
to: t6
```
````

**Reading an answer** that came back: a practical answer is steering. "Tomorrow" is not Done and
asks for no reminder; "I tried and it failed" is evidence to diagnose from, the checked build and
the original symptom kept; "show me where" is explained.

## Closed lists

Where a value comes from a closed list — a confirmation's `because` above all — the list is in
`reference.json` at the root of Pilot's store, each value's code with the line that says when it
applies. Read it there: this skill lists none of the values.

## Faults

Pilot reads a text before it takes it — a work item's at `register_document`, the store's at every
save — and a text with any fault is refused or held whole: nothing of it is taken until a save of
it is clean. Each fault comes with its line and a message written for you to act on, such as
``block D1: `recommend: Rack` names no option``: fix the file, then register or save it again, in
the same turn.

The text's own faults are the grammar above broken: a fence left open, where the reading stops; a
kind written with capitals; `id=` on a fence that is no block; a block without `id=<id>`, or with
more after it; two blocks with one id; a body or a front matter that is no YAML mapping; a body in
flow style; a key written twice; a key the block's kind does not take; an option that is no label
with at most one line; two options with one label; `options` or `recommend` beside `proposal`;
`recommend` naming no option; `type` other than `confirmation`; a confirmation without `proposal`
or `because`; `answer: deferred` without `to`, or `to` without it; a `via` outside its values; an
`at` or a `done` that is no time; `urgent` other than `true` or `false`.

The faults against the record: `step` naming no task of the project; `for` or `by` naming no
handle; `because` naming no confirmation reason; `to` naming neither `plan` nor a task in the plan,
unless the published text carries that same `to` on that block; a save Pilot makes of an item with
no title; in the draft, a `slug` that is malformed, starts with `draft-` or is another project's.

Never a fault: anything in the prose, an answer matching no option, an answer without `by`, `step`
naming a removed task, and a code block in a fence of any other kind.

**What a person answered is the record's.** Once a block carries an answer `by` a person — an
answer, an action's Done — its whole fence is: a save that changes it gets the published fence
back, with the fault `block D1 reverted: answered by a person`, and what you want changed goes
into a new block or a new item. With the first person's answer in a registered document, its body
prose is the record's too, every line outside the front matter and the blocks; the front matter
stays the writer's. A save that gives a block a person's answer the record does not hold loses
those lines, and a block a save dropped is put back. Pilot's own `by: agent` answers freeze
nothing. In the draft only a person's answer lines are the record's, and a block may go from it,
its answers with it.

## An example

A document of two asks, with the shared context first and each ask's block last in its section:

````markdown
---
title: Moving the newsletter to the new mail provider
summary: How the newsletter moves to the new mail provider before the old contract ends
step: t4
---

The old provider's contract ends on the 30th. The new provider already sends the password-reset
mails, so the newsletter is the last sender left on the old one.

## Which domain the newsletter sends from

The existing domain, `mail.example.org`, is recommended: nothing new to verify, and the newsletter
moves this week. Once this is answered, the move goes ahead on the chosen domain.

**What tells them apart.** A domain of its own keeps a bad campaign from hurting the reset mails'
delivery, at the cost of a second verification, about two days. The list is small and the
deadline near, so the shared domain is the one recommended; it has not been tried at the list's
full size.

```decision id=D1
options:
  - Existing domain: nothing to verify, shares the reset mails' reputation
  - Own domain: a second verification, delivery kept apart
recommend: Existing domain
```

## Confirm the sender address in the provider's console

In the provider's console, under Senders, confirm `news@mail.example.org` from the mail it sends
you, then report whether the confirmation went through.

```action id=A1
options:
  - Works
  - Doesn't
```
````
