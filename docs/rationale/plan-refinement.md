# Plan refinement — the interview, its readout, and the untested replacement

> *Written 2026-09-02 from session notes at plugin 0.9.13; the 0.9.19 contract and readout live in
> an unpushed checkout. Re-check every figure below against `plugins/dev/docs/refinement.md` and
> `docs/research/plan-interview-2026-09-01.md` once they are pushed.* Figures that come only from
> those notes are marked **from notes**.

This doc covers the interactive half of planning: how `/dev:plan-slice` pins a slice's requirements
with the operator today, what a read of 49 planning sessions found wrong with the way it asked, and
the ruling that replaced the question dialogs with a per-slice refinement document — the one change
in this set that is built but unmeasured. The mechanics of the plan loop that follows the interview
are [`plan-loop.md`](../../plugins/dev/docs/plan-loop.md); how a slice reaches planning is
[`overview.md`](overview.md); the reporting shape this ruling borrows from is
[`reporting.md`](reporting.md); the planner-effort experiments that preceded it are in
[`improvements.md`](improvements.md) and [`history.md`](history.md).

## Planning today (0.9.13)

`/dev:plan-slice` is the **refinement session** — in the skill's words, "the dev team going through
the idea with the PO" ([`skills/plan-slice/SKILL.md`](../../plugins/dev/skills/plan-slice/SKILL.md)
§ Your role). The session is "a coordinator and the PO's advocate, not the technical architect": it
captures every explicit request in the operator's words, rules every scope boundary in or out before
the loop launches, and surfaces feasibility concerns now. It reads exactly one input, the slice
folder's `slice.md`, and everything it settles has to land in one output, because "nobody downstream
reads slice.md or this chat: what reaches the executors is `plan.md`, nothing else."

The interview itself is the skill's § 2, "Pin the requirements with the operator": Q&A to bottom the
ask out, bringing "open choices, contradictions, and anything that changes the shape", never
relitigating settled input, with two guards — a hedged answer is not a ruling, and exploration is
one focused sub-agent per load-bearing question, never a fan-out. The skill names no mechanism for
the Q&A. In practice the sessions asked through Claude Code's question dialogs (`AskUserQuestion`:
a prompt, two to four options, one marked recommended), and the 2026-09-01 read counted 317 of them
(**from notes**).

What the session then authors is the plan's **header** — the one-liner, a `## Requirements /
rulings` section carrying every requirement and ruling in the operator's words, ordering
constraints, not-in-scope, and a `## Push holds` bullet for any repo a ruling forbids pushing
([`plan-template.md`](../../plugins/dev/docs/plan-template.md) § plan.md). Phases are not its to
write: every `###` heading is the plan-writer's. The header is authoritative on intent, the
plan-writer preserves it verbatim, the plan-reviewer treats it as "the operator's settled input",
and `/dev:run-slice` appends mid-run operator answers to it — so whatever the interview settles is
read by every later session through this section alone.

The hand-off is `plan_loop.py`: one fresh plan-writer pass completes the plan, one fresh
plan-reviewer pass judges it, and there is no review loop — "a writer pass, a reviewer pass, and
exit — findings go to the operator for adjudication, whose rulings land in `plan.md` and drive
exactly one fix pass" (v0.4.0, [`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md)). Exit 4 is
the loop's only way of talking to the operator: writer questions, or a review pending adjudication.
Rulings are edited in place, never chained; the round history lives in `plan_review_r*.md`. Nobody
re-reviews the fix pass: "the operator's read is the second look, and it is the cheapest review pass
there is" ([`plan-loop.md`](../../plugins/dev/docs/plan-loop.md)).

Two earlier decisions shaped what the interview has to settle:

- **Task shape and the research budget (v0.4.3, catalogue A1 + A2).** The plan-writer declares
  `pre-settled` / `localized` / `cross-cutting` before it investigates, justified in one line from
  `slice.md` facts; `pre-settled` forbids research sub-agents and repo sweeps, and any research
  dispatch must name the open question it settles. The grounding was slice 153, which "spent $27.72
  before any code existed on a slice whose slice.md said 'you are not designing anything'"
  (v0.4.3). A well-run interview is what makes `pre-settled` true: slice 190's task-shape line reads
  "pre-settled — the refinement rulings above fix the mechanism for each of the four requirements"
  (`slices/completed/190_fleet_state_under_faults/plan.md` § Task shape).
- **Upfront difficulty grading stays rejected (catalogue A4, a decision record).** The first
  research briefing opened with "Planner always deep-dives … An earlier attempt to grade tasks by
  complexity upfront and route them to different models/effort levels produced poor results"
  ([`research.md`](../research/research.md) § Observed problems). A4 records why not to retry it:
  difficulty is not a stable property of the request, models misjudge it from surface framing, and
  judges are least reliable on near-ties — with the scope note that a label a human adjudicates
  before anything acts on it is a different lane
  ([`interventions.md`](../research/interventions.md) § A4). The operator ruling in the interview is
  that human adjudication.

Two completed headers show what the interview produces. Slice 190 (four triaged cards) carries
one ruling per requirement, each quoting the operator and each followed by the same sentence
shape — "The two alternatives put to the operator and **not** chosen: …" — the residue of a
three-option dialog per decision (`190_fleet_state_under_faults/plan.md` § Rulings from refinement).
Slice 195 (raised in chat, no card) quotes the operator's typed messages in order — "I don't really
want the hacky solution from Trello … I was just hoping that it would be relatively simple to
support it natively" — and then a ruling per open point
(`195_mcp_adapter_oidc_north_auth/plan.md` § Requirements / rulings). Read side by side, the
difference is visible in the quoted "operator's words": typed sentences in 195, and in 190 prose
with the shape of a dialog option's description — "Smallest change; closes the witnessed incident."
That reading is the author's, not a measurement.

## The interview, read (2026-09-01)

**Measured, from notes.** On 2026-09-01 the operator asked for the dialogs to be read, with a brief
that they were uncomfortable: cornering, code cut off in the option text, questions that assumed the
slice was fresh, padded alternatives, the session relapsing into dialogs after being told "let's
talk", and second-round questions too specific to answer. The read (`plan_qa_readout.py` over both
projects' planning transcripts, against a written rubric) covered 49 slices and 317 dialog
questions — about six per slice.

| Figure (from notes) | What it says |
|---|---|
| 86 of 317 questions carried no recommendation | A quarter of the dialogs asked the operator to choose with nothing to react to. |
| 19 % deviation from the recommendation (45 of 231) | The operator's own prior estimate; four in five dialogs ended on the option the session already preferred. |
| Of the 45 deviations, 27 were typed answers, 18 a listed alternative | The listed alternatives were chosen 8 % of the time; when the operator disagreed, they mostly wrote rather than picked. |
| 17 recommendations would have been wrong; 15 questions rested on a stale premise | Following the recommendation blind is not safe, and the questions did not check what they assumed. |
| 0 of 13 Accept/Reject findings rejected | The accept-or-reject dialog over review findings carried no information; it always went one way. |
| 9 dialogs dismissed; 8 of 10 "let's talk" moments re-asked as dialogs | The operator's attempts to leave the dialog were overridden by the next turn. |
| 52 % not readable cold | Half the questions cannot be understood a week later without the transcript around them. |

Read together: the dialog was doing two jobs badly. As a decision device it offered options the
session composed, cut off the code the decision rested on, and in a quarter of cases offered no
view of its own; as a record it left nothing anyone could read afterwards, while the one durable
artifact — the `plan.md` header — had to be reconstructed from the chosen option's text.

## The ruling (2026-09-01)

**Ruled, from notes.** No dialogs in `/dev:plan-slice`, ever. In their place:

- A **`refinement.md` per slice**, written by a dedicated sub-agent (`dev:refinement-writer`,
  pinned through `model:` in its frontmatter to a stronger tier than the session's own; the
  per-call override outranks it) from the material the session collects — the grounding, the open
  choices with their grounds, the recommendation and what it rests on.
- The **session** (any model) grounds the slice, walks the operator through the writer's receipt,
  and records rulings in `plan.md` as before. Single-choice rulings, review adjudication and
  premise corrections are settled **agree-or-comment in chat**; the writer's own questions are
  rendered into the document as a second round rather than asked one by one.
- A **premise check** (#785, taken in a narrow form): one read-only sub-agent checks every
  requirement's premise before it is absorbed; a premise that has evaporated opens the refinement
  doc under "Where we are". Flagged to the operator as strikeable if it earns nothing.
- The user-level backstop `permissions.deny: ["AskUserQuestion"]` was **declined**: "I'll do this
  if I feel I need to." It is not to be re-proposed unless the record shows a relapse.

The stated reason, as recorded: the recommendation is not safe to follow blind (17 wrong, 15 stale
premises), so the document exists to expose the recommendation's grounds for refutation — and a
writer that only formats what it is handed flags an unverified premise instead of laundering it
into a confident option. Shipped as dev 0.9.19 in the other checkout; the contract is
`plugins/dev/docs/refinement.md` there.

## Why a document and not a better dialog

The shape is not new to the pipeline; it is the third time the same move was made, one stage
further upstream each time.

- **Close-out (v0.5.0).** Per-finding tracker cards were replaced by one document per slice that the
  operator reads in one sitting and dispositions in their own words under each entry — `card`,
  `fix now`, `fold into <slice>`, `close`, `defer`, free form — with a skill that executes the words
  ([`reporting.md`](reporting.md)).
- **Triage (v0.5.2).** The rubric verdict, "the one thing it never persisted", became a label on the
  card; the operator pass got a stated vocabulary of rulings and dispositions instead of one
  invented per run; a conditional ruling was declared "not an approval" and routed back as a
  research line (v0.5.2).
- **Refinement (0.9.19, untested).** The session's recommendation and its grounds become a document
  the operator reads, agrees with or comments on in chat, and that survives as the record the
  header's rulings point back to.

What the record on disk supports about the difference: a dialog forces a choice among options the
session composed, in a box that cuts off code (the brief) and that a quarter of the time offered no
recommendation (86 of 317, from notes); the answer is a click, so "the operator's words" in the
header are the option's description, and the reasoning that made the option preferable is gone
with the transcript (52 % not readable cold). The `plan.md` header already is the durable artifact
every downstream session reads; the plan loop already treats the operator's read as its second
review pass. A document puts the recommendation where that read happens and keeps what it rested
on, so a wrong recommendation can be refuted on its grounds rather than out-voted by a click. This
is the argument as the notes and the sources give it, not a measured effect.

## What will judge it

**Untested.** As of 2026-09-02 no slice has been planned on 0.9.19 (from notes). The read that
decides it is pre-registered in the notes:

- The first four slices planned on it, over both projects. `plan_qa_readout.py stats` must show
  **zero** dialogs — a single one is a relapse, and the declined deny-list backstop comes back on
  the table.
- The operator's own messages in those sessions, read for dismissals, "I don't know", questions
  asked back at the session, and comments that correct a premise — the signals the dialog era hid
  behind option clicks.
- Whether each slice's `refinement.md` still reads a week later without its transcript — the
  52 % figure is the baseline it has to beat.
- The premise check's first evaporated premise (#785): whether the "Where we are" opener earned its
  sub-agent, or the item is struck as flagged.
