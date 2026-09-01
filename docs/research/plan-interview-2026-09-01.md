# The plan-slice interview — how the operator actually answered (readout, 2026-09-01)

The operator's brief: the planning Q&A is uncomfortable. Multiple-choice dialogs corner the
reader, cut code off, assume the slice is fresh in memory when it may be a week old, and pad the
recommendation with alternatives that are not real; the session drifts back into dialogs even
after being asked to just talk; the recommendation is deviated from about one time in five; and
the second round — the questions relayed after the plan-writer or plan-reviewer came back — is
so specific that the operator sometimes bails and says "you pick". The ask: read the plan-slice
sessions of at least the last 25 slices, and turn what they show into a recommendation.

Everything below is read from the interactive transcripts by
[tools/plan_qa_readout.py](tools/plan_qa_readout.py) (`table` / `stats` / `dump`), plus a
per-question grading of every dialog by four readers on a fixed rubric
([plan-interview-rubric-2026-09-01.md](plan-interview-rubric-2026-09-01.md)).

## 1. Corpus

Every interactive session that invoked `/dev:plan-slice` in the KubeCoder and Ansible projects,
2026-07-30 → 2026-09-01, plugin 0.3.1 → 0.9.13:

| | |
|---|---|
| sessions / slices | 58 / 49 (KubeCoder 126, 143–195 incl. 182b; Ansible 006–009, 013, 015, 016) |
| dialogs (AskUserQuestion calls) | 137 — 80 interview, 21 writer-question relays, 36 review adjudications |
| questions | 317 (1–4 per dialog; 2 options: 121, 3 options: 172, 4 options: 24) |
| operator free-text messages | 179 |

The last 25 slices alone carry 154 of the 317 questions. The pre-plugin `/plan-slice` era
(43 sessions, slices ~127–142, 2026-07-31 → 08-13) is not in the corpus; it precedes the ask.

The skill's text has said "Q&A with the operator" unchanged since 2026-07-16; no plugin file
names the dialog tool. The multiple-choice shape is the model's own reading of that line, with
the tool's rules on top: 2–4 options per question, a `(Recommended)` suffix convention, and a
one-line label plus a description per option.

## 2. What the numbers say

**Deviation is exactly what the operator estimated.** Of the 231 questions that carried a
recommendation, 177 took it (77 %), 18 took a listed alternative (8 %), 27 got a typed answer
(12 %), 7 were left unanswered. Deviation 19 %, the same in the interview (19 %) and the
adjudication (18 %), and highest on relayed writer questions (31 %).

**The alternatives are almost never what the operator wants.** When the operator did not take
the recommendation, the typed answer beat the listed alternatives 27 to 18. Across all 317
questions, 55 answers were typed (17 %); 19 of those asked the session a question back through
the answer box, and 16 said outright that context or knowledge was missing ("I don't know",
"what's the self action token?", "I need background for this also", "I'm missing context").

**A quarter of the questions offered no recommendation at all** — 86 of 317. Slice 194 is the
limit case: four dense questions, none marked, and the operator's reply after reading them all:
"I read all your options and I don't know. I want to follow your recommendations."

**Nine dialogs were dismissed unanswered** (17 questions). What the operator wrote next, in
their words: "I said I wanted to talk about this" (145); "I'd prefer we follow the established
patterns in iac" (Ansible 007); "Can you give me an url to #606?" (160); "I'm doing this from
(bad) memory. Please walk me through this … this isn't really productive" (173); "I stopped the
planner. Let's bottom this out" (182, twice); "I'm stepping out of question mode. Let's talk"
(189); "Are we just over complicating this?" (192); "I read all your options and I don't know"
(194).

**Asked to talk, the session re-asked.** Ten moments where the operator asked to talk, be
walked through, or reframed the question. In eight the session's next move was another dialog
(145, Ansible 007, Ansible 008, 158, 165, 173, 182, 192); three of those re-asks worked because
a page of prose came first (Ansible 008, 158, 165), five were dismissed or answered with a
second "I said …". Only 160 and 189 were honoured in prose. In 182 the operator sent the same
design message twice around a dialog that ignored it.

**Reading load.** A median dialog puts 2.3 KB of questions and options in front of the
operator (p90 3.8 KB), after a median 1.8 KB of prose (p90 3.3 KB). Median time to answer a
dialog 4.9 min, p90 20.6 min; one single-question adjudication held the loop for 524 min
overnight (182b) to record the recommended option.

**Half the questions are not readable cold.** Graded against "could someone who has not
looked at this slice for a week judge it from the question and options alone": 153
self-contained, 145 leaning on unexplained handles (R1, F2, V12, D191, #724, a `file:line`, a
function name), 19 readable only with the earlier chat. The rate of confused, reframed,
dismissed or delegated answers climbs with the deficit: 11 % on self-contained questions, 16 %
on handle-dependent ones, 21 % on chat-dependent ones. The relayed writer questions are the
worst: 22 of 27 not self-contained.

**The accept/reject round is ceremony.** 13 reviewer findings were put as Accept / Reject;
zero were rejected. The 9 questions the graders called padded (an alternative no engineer would
pick — "Reject — leave the plan wrong", "Something else", "Leave it alone" after the question
has shown it must be fixed) were accepted 9 of 9. Several adjudications were graded as minutes
spent for one real decision (171: 12.9 min, one live fork among two settled accept/rejects and
four advisories).

**The recommendation is not safe to follow blind.** The graders listed 17 questions in 15
slices where taking the recommendation would have shipped something the operator did not want:
pinning Terraform against the standing "as iac does it" (Ansible 007), putting Argo CD on the
public internet (Ansible 009, which became slice 015), a force-rebuild parameter (013),
"records only" title derivation when the operator wanted Claude Code's whole algorithm (126),
click-moves-cursor (157), a Starlette handler plus decoder gate later unwound to a docs fix
(158), a named surface in a user-facing error (161), a timing-sensitive flap criterion (163),
push holds and a base-image cert (165), measure-and-record instead of fixing the two over-budget
producers (168), a close-out note for what the reaper already handles (171), a constructor split
the operator wanted left to the executor (175), a "full live pass" no agent can run (180), a
`181b` slice id right after the operator ruled against `b` suffixes (181), mint/revoke in 182b
(182b), an inline submenu on a docs-only ask (188), and unknown-vs-none where the operator
wanted a third design (189).

**The premise is often wrong, and the format hides it.** 15 questions rested on a premise
the operator or the reviewer overturned: SSH "isn't live on prd yet" — "Testing complete. I'm
connected using SSH right now" (171); "who performs the AppRole login" asked before anyone
checked the iac pattern (Ansible 007); a PATH mechanism that is impossible in a pod spec (169);
a job path recommended because the session "could not see an IaC folder" that exists
(Ansible 006); Ansible repos needing a config change and pod restart when a clone would do
(165); storage "on the environment's Kubernetes object" when the operator had metadata.json in
mind all along (189); restart-reason fields that were already on the record (182); "two facts
wrong" about requirement 2's window, caught only by the reviewer (191); an activation-timing
claim that reversed at adjudication (155); a self-action token the operator had never heard of
(182b). A dialog states its premises inside option descriptions, where they read as
background rather than as claims to check.

**Where it cost nothing.** 174, 179, 184, 186, 187, 190, 195, 164, 144 and Ansible 013 ran
clean: narrow forks local to a file, the evidence quoted in the option, the operator inside the
slice, answers in a minute or two. The format is not universally bad; it fails on structural
forks, on week-old slices, on unverified premises, and whenever the operator wants to think out
loud.

**What free text carried.** The slice-shaping content of these sessions mostly arrived
outside the choices: the bounded-retry rule for restarts (163, in reply to a yes/no fact
question), the hover feedback on a row (157), the GitHub-secrets requirement (Ansible 015),
"HelmCharts will go. We can manage in the mean time" (Ansible 008), the Argo CD relay design
(Ansible 009), the approve/deny bootstrap (181), the whole two-function SSE model (182),
"Cut R2, R5 and R6" (145). Twice the operator's first post-dialog question was the one that
decided the slice: "How big is this slice taking the answers into account?" (183, back to
triage) and "Are we just over complicating this?" (192, the coordination design deleted).

## 3. The two hypotheses, checked

*The dialogs corner me and assume I know the slice.* Confirmed, and measurable: 52 % of
questions are not readable cold, the confusion rate tracks that deficit, and every dismissal
is the operator asking for context, a link, or a conversation. The tool's shape adds to it:
2–4 options are mandatory, so a single-answer question must invent an alternative; a label is
one line, so the code goes in the description and gets cut; the answer box is a ruling slot,
so 19 questions asked back through it were answered late or not at all.

*The alternatives are padding.* Half right. Read strictly (would a competent engineer ever
pick it?) 284 of 317 forks were genuine — the alternatives are mostly defensible. Read by
value, they are padding: of 231 recommended questions the listed alternative won 18 times
(8 %); the typed answer won 27. The operator's instinct that "the model poses alternatives
because it feels it has to" is right about the tool (it has to) and about the outcome (they are
not chosen), and wrong only about the reason the recommendation deserves scrutiny: it is not
that the alternatives are fake, it is that the recommendation itself was wrong 17 times and
built on a false premise 15 times. What the operator needs from the session is not a menu, it
is the recommendation with its grounds stated as claims they can refute — which is what the
19 % deviation has been doing by hand.

## 4. Recommendation

The operator has set the direction: no dialogs; a document that walks through the decisions
with the recommended shape and its trade-offs; and, where there is one decent choice with
impact, a plain in-session explanation asking for agreement or comment. The evidence supports
all three and adds four constraints. This is the contract to ship as the next `dev` version.

### 4.1 Remove the dialog tool, structurally

The session MUST NOT use the dialog tool in `/dev:plan-slice`. That instruction alone is not
enough: eight of ten "let's talk" moments relapsed, and Claude Code's permission docs are
explicit that prompt instructions shape what the model tries, not what the harness allows.
The backstop is the operator's own settings — a bare-name deny removes the tool from the
model's context entirely:

```json
{ "permissions": { "deny": ["AskUserQuestion"] } }
```

in `~/.claude/settings.json` (user level: this is the operator's preference, not a project's).
A skill-level `disallowed-tools` will not do — it clears on the operator's next message, so it
cannot carry a multi-turn interview. Collateral is small: plan-slice accounts for over 90 % of
all dialogs in both projects; triage, run-slice and onboard used ten between them, and those
belong in prose too.

### 4.2 The refinement doc — `refinement.md` in the slice folder

The interview's output is a file, not a dialog and not a chat message. A file because: the
slices are planned across sessions and days (159–161 sat 8–20 h between first message and loop
launch; 182b's adjudication sat overnight); the operator's stated problem is reading a decision
a week after the slice was written; code must not be cut off; and comments need a place. It
lives beside `plan.md` and is committed with the slice as the interview's record — the same
role `plan_review_r*.md` plays for the review round. The plan's requirements/rulings section
stays what it is: the rulings, in the operator's words; the doc holds the grounds.

Shape — a head, then one section per decision, then the open facts:

```markdown
# Slice NNN — refinement

## Where we are
<the slice's ask in the operator's words (from slice.md); what is already settled and by
what; what this doc decides; the size this comes to in phases and the repos it touches>

## D1 — <the decision, as a sentence a cold reader can parse>
**Where this comes from.** <the requirement, card or finding — quoted or expanded, never a
bare R2 / #724 / D191>
**What I found.** <the premises, each a checkable claim with its evidence — the things the
operator can refute; nothing stated inside an option ever again>
**Recommendation.** <the shape, then the trade-off: what it gives up and why that is
acceptable — the sentence the operator disagrees with when they disagree>
**Alternatives.** <only if one is genuinely live: one line each with the trade-off that makes
it lose; otherwise "none worth the read">
**If this is wrong.** <one line: data loss / breakage / extra work / nothing>
**Operator.** _agree, or comment here_

## Open facts
<questions only the operator can answer, asked plainly with no options — "do you ever kill
an env pod by hand?", "was the archive of #606 deliberate? (link)">
```

Rules the evidence sets:

- **Recommendation first, one page per decision at most.** The operator asked for context,
  not volume; a dialog already cost 2–4 KB per read. Alternatives that do not add value are
  omitted, not listed — the 8 % hit rate says most will be.
- **Premises are claims, verified before they are written.** 15 stale-premise questions,
  several asked before grounding was done (155, 169, 180, 191: "structural questions before
  their costs were knowable"). The skill's "targeted exploration for load-bearing uncertainty"
  becomes "every claim under *What I found* was checked this session".
- **No bare handles.** A cold reader is the design target; R-numbers, card numbers,
  decision ids and file:line are expanded or quoted where they are used.
- **Size in the head.** 183 ran four clean accepts and was then sent back to triage on a
  number the interview never surfaced.
- **Fact questions are plain questions.** Ten were put as forks; the most consequential rule
  in 163 arrived as free text on a yes/no.

The walkthrough is the chat message that follows the write: the decision list, one line each
— title, recommendation, impact — the open facts, the path, and how to answer: comment in the
file under each *Operator* line and say so, or reply here by number; "agree" takes every
recommendation. The session reads the comments back, records each ruling in plan.md's
requirements/rulings section in the operator's words, and only then seeds the plan and runs
the loop.

### 4.3 Agree-or-comment — the in-session form

When there is one decent choice and it has impact, the session says so in chat and does not
invent a menu: what is going on, what it will do, the consequence if that is wrong, and
"Agree?". Never options; never an accept/reject pair. This is the form for:

- **A single-choice ruling with impact** (the HelmCharts-first push order in 171; the D191
  removal going dark on both stages).
- **Review adjudication.** Every blocking finding of a review round in one message, each
  with its default disposition and what it changes in the plan; the operator's "agree" or a
  comment on the ones they object to is the ruling. Zero of 13 accept/rejects were rejected —
  but 11 adjudication answers were typed, so the findings are still shown with their grounds,
  not applied silently. The `--fixes-applied` mechanics are unchanged.
- **A premise correction** ("I briefed you with two facts wrong" in 191) — stated, with what
  it changes, before anything is re-asked.

The test between 4.2 and 4.3: if the honest alternative would read "reject — leave the plan
wrong", it is 4.3; if the recommendation gives something up the operator might weigh
differently, it is a D-entry in 4.2.

### 4.4 The second round is rendered, not relayed

Writer questions (exit 4) arrive as decision / options / recommendation / grounds in the
loop's questions file, written for the session. They were relayed almost verbatim: 22 of 27
not readable cold, 31 % deviation, "I'm missing context", "I need background". Under this
contract the session appends them to `refinement.md` as new D-entries — re-grounded from the
plan (where we are now, what the writer settled, what this decides), premises as claims —
and walks the operator through them in chat the same way. The writer's and reviewer's own
output formats do not change; they are machine-facing.

### 4.5 Conversation rules

With the tool gone there is no "question mode" to step out of, but three habits still need
stating, because they are what the transcripts show working (146, 167, 170, 189):

- A reframe ("can't we just…", "are we over-complicating this?") or a "walk me through" is
  answered with prose that re-grounds the decision. The fork is not re-posed until the
  operator has said what they think.
- A question in the operator's answer is a question; it is answered before anything else is
  asked (19 cases went through the answer box).
- After a discussion, the D-entry is rewritten to the outcome and confirmed with one line —
  "D3 now reads: …; agree?" — not a new fork.

### 4.6 What does not change

The loop, the writer, the reviewer, `plan.md`'s shape, the rulings-in-place rule, the
`--fixes-applied` flag, verification.json. The change is confined to `/dev:plan-slice` §2–§3
and a new `docs/refinement.md` (the doc's shape and the 4.2 / 4.3 test), referenced from the
skill; `plan-loop.md`'s two lines on "the interactive session adjudicates the findings with the
operator" pick up the form.

### 4.7 How to know it worked

The same tool reads the new sessions: `plan_qa_readout.py stats` must show zero dialogs, and
the per-slice `dump` shows the operator messages. The signals to read after four slices, in
the operator's own words in the transcripts, are the ones this readout counted: dismissals and
"let's talk" (were nine, should be none), answers that ask back or say "I don't know" (were 35,
should be near zero because the doc pre-empts them), the time between the walkthrough and the
rulings, and whether the refinement docs are readable a week later — the operator is the
judge of that last one, and it is the point.
