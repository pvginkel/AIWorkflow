# Pilot — a stage of the workflow as a work item

Pilot, the project manager, runs the workflow's stages, `/dev:plan-slice` and `/dev:run-slice`,
each as a work item of a Pilot project. Pilot starts a headless session with a brief whose first
line is the stage's command. The skill does the stage's work, puts every ask it has into a
document it registers with Pilot, and ends its turn. Pilot's pass pre-rules what it can, the
operator answers the rest in the app, Pilot writes the answers back into the files, and the
session is continued with a message naming them. Triage is no stage: in Pilot it is the project's
definition chat, and `/dev:triage` stays the operator's own chat skill, as `/dev:arch-design`,
`/dev:inbox` and `/dev:onboard` do.

This page is the one home of that contract. Every stage skill follows it and cites it rather than
restating it. Pilot's side is PilotApp's `docs/round-trip.md` (the read at the turn's end, the
write-back, the continuation, the clarification run) and `docs/mcp.md` (the tools); where this
page and those differ, Pilot's docs are right and this page is the defect.

## The turns

Only Pilot speaks to a stage's session, and every turn opens in one of four ways:

| The turn opens with | It is | The skill |
|---|---|---|
| `/dev:<stage> <slice>` | the start, the brief its arguments | works the stage up to its first documents, its end or a halt |
| "Your documents were answered and written back in place: …" | the continuation | reads the answers back, acts on them, goes on |
| "Pilot asks about <path>:" | a clarification | answers the questions; registers nothing, starts nothing |
| anything else | a nudge | carries on from where the session stood |

Every turn ends with no tool call pending and nothing left running that the session waits for.
Its last message is one line saying where the stage stands — the documents it waits on, by path,
or planned, delivered, done, halted, stopped — except a clarification's, which is the answers
alone. That line is the whole message: it retells no document, sums up no work, reports no
finding, and offers and asks nothing, since what the operator needs from a turn is in its
documents.

## A turn's end is the run's end

To Pilot, the `result` that ends a turn makes the work item done. Pilot then reads every document
the turn registered, runs its pre-ruling pass, and once every one of them is closed writes the
answers back and places the continuation: a new work item that resumes the same conversation in
the same environment, the tree as the turn left it. Between turns the session's Pilot tools
refuse it: "Cannot call pilot-work because session <id> has no turn running".

So a stage ends its turn only when the turn's work is done: its documents registered, the stage
over, or a halt. It never ends a turn to wait for work of its own. A loop it launched is waited
on inside the turn, in the foreground, and so is a sub-agent it dispatches: the Agent tool's
`run_in_background: false`, whose report is the tool's result. A turn that a backgrounded task's
notification starts, a sub-agent's included, is one Pilot never sent and does not count as the
work item's, and its `register_document` is refused.

## The brief

The start's message is the work item's brief, which Pilot's brain writes and Pilot extends:

1. The stage's command and the slice as the first line, `/dev:run-slice 031`, so that the skill
   loads with the rest of the message as its arguments.
2. The brain's own text: the task in a line, the project's ticket on a line of its own as
   `Ticket: <id>`, and the grants text that Pilot's switch selects.
3. Pilot's `From Pilot:` lines: the plan task the work item serves, whose id every document
   registered carries as `step`; whether Auto pilot is on; and the project's handbook, verbatim.

The skill reads the slice from the first line, the ticket and the step from the brief, and the
spec repo from the cwd's `.aiworkflowrc`, as everywhere else. A brief without a ticket files no
parented card, and the document whose answers would file one says so; one without a plan task
leaves `step` out.
The grants bind the session as they bind any work item, and the handbook's standing preferences
are applied in every ask.

**The spec repo is pushed at the stage's end**, where the grants pre-approve a push of the spec
repository, as both of Pilot's texts do: once the stage is over — planned, done, or stopped
where it stood — and after its last commit, a plain `git push` of the spec repo's branch, never
forced. A refused push is named in the turn's last message and left as it is. Without that
grant, nothing is pushed.

## The documents

Every ask is a document in the slice's folder in the spec repo, rendered from a store by
`${CLAUDE_PLUGIN_ROOT}/tools/asks.py`; nobody writes a block by hand. The format is
`/dev:document-format`'s, which the renderer keeps, and the words are `/dev:writing`'s.

- **Where.** `asks/<n>-<slug>.md`, numbered from 1 in the order written over the slice's life,
  its store `asks/<n>-<slug>.json` beside it. The close-out is `close-out.md` at the folder's
  root, rendered from `close-out.json` ([close-out.md](close-out.md)).
- **Registered, then backed.** `register_document(path)`, the path absolute. Pilot reads the file
  at once and refuses one with faults, each with its line: the skill fixes the store, renders
  again and registers again in the same turn. Then `attach_file(path, to=<the id it answered>)`
  for what backs the asks: the material, the plan, the diffs, the record. A folder attaches every
  file under it, and an attachment is a copy taken at the call, never refreshed.
- **Then the turn ends.** Pilot publishes the text it reads at the turn's end, so nothing touches
  a registered file meanwhile.
- **Never edited again.** A registered file takes one write after its registration: Pilot's
  write-back, which overwrites it with the published text and the answers in it. A revised ask is
  a new document.
- **The folder stays put.** The write-back writes to the path the file was registered from, and
  creates it if it is gone. A stage moves its slice's folder, out of `slices/backlog/` or into
  `slices/completed/`, only while none of its documents is open.

## The continuation

Its first message is Pilot's, verbatim: "Your documents were answered and written back in place:
<path>, <path>. Read the answers and continue." Where a document's read failed, a second line
follows: "Could not be read: <path>, <path>."

The skill reads each answered document back into its store (`asks.py absorb`, the close-out's
through `close_out.py`), acts on every ruling as the stage says, into `plan.md`, a card, a fold,
a strike or a slice folder, and goes on with the stage. Three readings are fixed:

- **The operator's words travel verbatim.** `answer` and `note` are quoted wherever the ruling is
  restated, never paraphrased or completed.
- **An answer `by: agent` is Pilot's**, a ruling delegated to it, and everything it produces is
  marked so: "chosen by Pilot: '<note>'; the operator did not decide this".
- **`answer: deferred` is terminal.** With its `to`, the block is Pilot's to bring back. The entry
  closes as deferred, and the workflow keeps nothing to revive it.

A document that could not be read was put to no one: its asks go again, in a new document. A
ruling the skill cannot carry out as given is a new document too, its alternatives a decision,
never a quiet substitute.

## The clarification

A turn opening "Pilot asks about <path>:" is Pilot's pass asking the writer about blocks it could
not read: a line `- <local id>: <question>` per block, grouped by document, closing with "Answer
each under a heading per block id (`## D2`, `## D4`); register nothing, start nothing; then end
your turn." The skill has a fresh sub-agent, pointed at the slice's folder, answer each question
from what the folder holds; the session never answers from its own reading. The operator reads
the answers beside their blocks, so the sub-agent loads `/dev:writing` first: each answer opens
on the answer, in the operator's terms, with the words that support it quoted and not the file
or the section they sit in as the argument, and what it leaves open carries what its writer
would do about it. The turn's last message is the answers and nothing else, each under `## <local id>`,
or `## <path> <local id>` where two asked documents share an id: Pilot splits that message by its
headings and shows each part beside its block.

## The nudge and the halt

A turn that opens any other way is a nudge: `continue`, which a Resume sends after a Stop or a
failure, or Pilot's message once a usage halt or the project's pause lifts ("… This is a nudge to
allow you to complete any outstanding work, if any."). The skill carries on from where the
session stood. A loop that exited `halted` is resumed, and one still running is waited on again.
A document still unanswered is left as it is, and the turn ends. A document answered in place is
read back as the continuation reads it.

Pilot writes `/work/.quota-limit-halt-requested` into the environment while a usage halt or the
project's pause holds, and deletes it when neither does. Present, it means stop at the next safe
point: the loops check it at theirs and exit `halted`, code 7 ([run-loop.md](run-loop.md)
§ Protocol invariants has the safe points), and the skill ends its turn saying where the stage
stopped. Present at a stage's start, the stage does not start, and the turn says so.
The nudge after the halt lifts carries on.

## Cards

The tracker is spoken of in the workflow's vocabulary
([project-contract.md](project-contract.md) §3), which the host convention realises; the skill
loads that convention before its first tracker call. Every card a stage files, a slice card or a
card a ruling asks for, is parented to the brief's ticket. The slice card's moves are the
skills': planned at planning's end, in progress at the run's start, delivered once merged, and
done by the run's continuation once it has carried out the close-out's answers, which are the
operator's review of the slice.

## Without Pilot

When `mcp__pilot__register_document` is not among the session's tools, the skill renders each
document as it would for Pilot, prints its path, and ends its turn. The operator writes the
answer lines into the file as Pilot would and says "continue", which the skill takes as a nudge:
the documents answered in place are read back as the continuation reads them. Nothing else is
kept for it: no walkthrough, no agree-or-comment, no ruling read from a chat line. A question the
operator asks in chat is answered as a clarification is, by a sub-agent pointed at the folder.

## What a stage never does

- Put an ask in chat, or end a turn on a question.
- Offer a word that accepts everything.
- Read a ruling from prose.
- Edit a registered or rendered file, or ask anyone to. The fallback's answer lines are Pilot's
  write, taken by hand.
- Poll a loop: a wait it re-arms reads nothing in between.
- Tell "the operator" anything that is not in a document.
