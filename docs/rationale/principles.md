# The design rules, each with the incident that produced it

The rules the plugin holds every agent, script and author to, stated once each with where the
rule now lives and the incident or measurement that put it there. This is the "why" behind
sentences the contract docs state as flat fact; the mechanics stay in those docs. The flow they
add up to is [`overview.md`](overview.md); the narrative of how they arrived is
[`history.md`](history.md); the fuller case for each change, with its readout, is
[`improvements.md`](improvements.md). Labels: **measured** (a number from the record), **ruled**
(an operator decision without a measurement), **untested** (built, not yet read).

## Structure

**The plan is the queue; document order is authoritative; ids are labels.** One `plan.md` per
slice, phases as `### P<id> — <title>` headings, re-parsed before every phase so work appended
mid-run is picked up next iteration.
*Origin:* the task-folder model it replaced ran unbounded plan/review loops — one slice went
through 6 plan-writer, 6 plan-reviewer, 9 code-writer and 8 code-reviewer rounds
(`workflow-improvements/ANALYSIS.md` § 4, slice 052; **measured**). The phased plan shipped as
v0.4.0 after four pilot slices ran it end to end.
*Stated in:* [`run-loop.md`](../../plugins/dev/docs/run-loop.md) § The plan is the queue,
[`plan-template.md`](../../plugins/dev/docs/plan-template.md).

**Every agent may edit the plan; only the driver stamps `✅ DONE`.** Executors append
done-records and edit later phases their work changes; consults and the test agent append phases;
the operator edits at will. The stamp is mechanical, after review passed and the merge landed.
*Origin:* the shared, writable plan is what lets work grow without an orchestrator; the
driver-only stamp is what keeps a self-declared "done" from ever counting. Both are design
decisions of v0.4.0, not incident responses (**ruled**).
*Stated in:* `run-loop.md`, `plan-template.md`, `agents/code-writer.md` rule 2.

**Files are durable, sessions are ephemeral.** No long-lived session drives anything; every agent
is a fresh context reading its inputs from the slice folder and leaving its outputs there.
*Origin:* the pre-plugin orchestrator session was 53 % of all spend over 1,338 conversations; on
slice 038 it re-entered repeatedly and carried 70 % of the slice's cost re-priming context
(`workflow-improvements/ANALYSIS.md`; **measured**). The redesign's first validation cut its share
to about 13 % (`workflow-improvements/PLAN.md`, slice 072).
*Stated in:* the repo's `CLAUDE.md` § Architecture; `workflow-improvements/PLAN.md` is where the
sentence was coined.

**Scripts drive, agents judge.** Gates, git, caps, stamping, parsing, rendering are Python;
judgment is a dispatched agent with a bounded job and a verdict file.
*Origin:* two applications made the rule. The runner started running the test gate itself
(2026-07-16 entry, [`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md)): "detecting green is
deterministic — no session is spawned to learn the gate's color", so the `code-tester` agent went
and a `test-fixer` spawns only on red. Then the close-out report became tool-written (v0.6.0)
after hand-typed entries drifted from the template and, on slice 154, 10 of the 16 Bugs sat
struck but full-bodied ahead of the six the operator had to decide on (**measured**).
*Stated in:* `CLAUDE.md` § Architecture; `run-loop.md`; `close-out.md`.

**The loops bail, they don't chat.** Exit 3 is an error, exit 4 a question only the operator can
answer; loop stdout never reaches the launching session, whose four jobs are start, error,
question, close-out.
*Origin:* the same orchestrator finding — a session that watches a run pays for every line it
watches. The run-slice skill's "escalate, don't absorb" is the operator-side half.
*Stated in:* `run-loop.md`, [`runner-state.md`](../../plugins/dev/docs/runner-state.md),
`skills/run-slice/SKILL.md`.

## Review

**Fix rounds resolve blocking findings only; an advisory finding is reported once and never
relitigated.** Delta reviews verify the blocking fixes and stop re-deriving the world.
*Origin:* Ansible slice 013 ($45, 3 h wall for a small slice) spent the second rounds of two of
its three phases on comment wording: the reviewer's advisory prose findings were pulled into the
fix round, the comment fixes became the delta review's subject and bred new comment findings
(v0.4.2; **measured**).
*Stated in:* `run-loop.md` § The per-phase round; `agents/code-reviewer.md` rule 4.

**A `blocking` tag needs an anchor; no anchor is advisory by construction.** Five anchors —
failing test, repro trace, analyzer output, requirement-to-code contradiction, coverage gap
against a named criterion; readability, taste and hypothetical performance can never anchor.
*Origin:* the research corpus's false-rejection study: 87 % of wrongly rejected code came with a
claim carrying no falsifiable counterexample (v0.4.3 shipped the taxonomy, v0.5.4 quotes the
figure; see [`literature.md`](literature.md)). The finding rate per anchor is telemetry in
`state.json` since v0.4.3 (**measured**).
*Stated in:* `agents/code-reviewer.md` rule 6.

**Fix rounds are failure-first.** A finding with an executable anchor is witnessed — the failing
test written, the repro run — before any code changes; one that cannot be made to fail is
refuted, recorded, and never raised again.
*Origin:* the self-correction literature (Huang et al.: models cannot reliably judge unverifiable
claims) translated into a protocol — v0.4.3's C2. Slice 190's P1 shows it working: the fix round
wrote two tests that each fail under their own mutation, and the round-2 review "re-derived, not
taken on the executor's word" ([`overview.md`](overview.md)).
*Stated in:* `run-loop.md` § The per-phase round.

**Describe the problem, never the fix.** A review finding states what is wrong, the failure it
produces and the evidence; a finding that carries its own fix is invalid output. The one place a
reviewer's fix idea may go is the close-out report's Suggestions section.
*Origin:* the #175 redesign's agent trims — "Reviewers describe, never fix"
(`workflow-improvements/PLAN.md`, workstream G; **ruled**) — on the reasoning that the fix design
belongs to the executor who has the code open, and a prescribed fix invites a round about the
prescription.
*Stated in:* `agents/code-reviewer.md` rule 2, `agents/plan-reviewer.md`.

**Comments state verifiable invariants; a prose finding must show the text is wrong.** Predictions
and strength-graded claims ("will/may/should …") are deleted, not hedged; wording drift that
preserves meaning is not a finding.
*Origin:* research run 1's problem B — reviewers weakening "will" to "may" at a cost and to no
functional effect (`docs/research/research.md`); comment and prose findings were about 49 % of all
findings in the grounding sample (`docs/research/interventions.md`; **measured**). Shipped as
v0.4.5's pair B1 + B4.
*Stated in:* `agents/code-writer.md` rule 6; `agents/code-reviewer.md` rule 4.

**From round 2 a consult funds the next round against a bar that rises.** Round 1's fix is
automatic; later rounds are bought by a fresh consult judging the findings blocking-only, then
Blocker-only, then critical-only; backstop cap 5.
*Origin:* the previous scheme — a cap of 3 extendable by two grants — came from slice 082, where a
finding raised in the final round had its fix written but never re-reviewed and 4 of the slice's
11 tasks shipped a real defect (2026-07-16 entry; **measured**). v0.3.0 replaced the grants with
the consult so the decision to spend is made against the findings, not a counter.
*Stated in:* `run-loop.md` § The per-phase round.

**The generation bar.** The completion consult's first follow-up generation appends only work the
plan owes and no phase delivered; the second, blocking work only; a third pending generation
bails to the operator. A touch-up the slice ships without is a close-out entry — one operator
word — not a phase.
*Origin:* named in v0.4.0; re-priced in v0.5.1 after slice 146's consult appended a phase for a
test nit — $4.02 with the consult it forced — reasoning "cheaper to fix than to card" against a
card cost that no longer existed (**measured**).
*Stated in:* `run-loop.md` § The generation bar.

## Reporting

**Everything out of the loops' scope goes to one close-out report per slice — never a tracker card
per finding.** The run's only tracker output is one card pointing at the report.
*Origin:* Ansible slice 007 produced eleven entries from five uncoordinated write paths, merged
by the operator into ten cards of which one was a must-act (`docs/research/close-out-report.md`;
**measured**). v0.5.0 replaced the cards; [`reporting.md`](reporting.md) has the full case.
*Stated in:* [`close-out.md`](../../plugins/dev/docs/close-out.md).

**Every claim carries its evidence class.** An entry's `Provenance:` opens `witnessed` or `read`;
the body leads with the symptom and states a cause only where it was shown.
*Origin:* the same false-rejection study — symptom claims held at 93–100 %, cause attributions at
44–75 % (v0.5.4; **measured** in the literature, adopted as a rule here).
*Stated in:* `close-out.md` § Entry rules.

**Reading the report is never a license to act on it.** Phase agents append only; the completion
consult is the one reconciler, and only through `strike` and `note`; the operator dispositions.
*Origin:* the scope-bleed argument — a writer "fixing while here" what an earlier phase reported
turns the report into a second work queue (**ruled**, `close-out.md` § Who writes what).
*Stated in:* `close-out.md`.

## Git and gates

**The per-phase gate is test-only; lint, build and test run per component at loop tail; a branch
whose gates are red is not pushed.** The sweep runs before any loop-tail dispatch and rides those
dispatches as deterministic fact.
*Origin:* slice 152 reached the completion consult with a known-red manual build "owed to the doc
phase"; the consult answered `complete`, the test phase pushed, and CI failed a build the tree
could never pass (comment above `_sweep_targets` in `run_loop.py`; **measured**). The
per-phase gate stayed test-only by ruling on Triage #399 (v0.7.5): a per-phase lint taxes every
phase to save the one that fixes it.
*Stated in:* `run-loop.md` § After the last phase.

**The driver checks pushes, it does not push, when a test phase exists; a plan can hold a repo's
push.** `## Push holds` in `plan.md` is the one `##` section the run loop reads.
*Origin:* slice 135 held `../HelmCharts` by ruling (a push there deploys dev and prd together);
the test agent honoured it, was nudged twice, the driver bailed `unpushed`, and the run session
pushed 38 seconds later — `IaC/HelmCharts` #5668 deployed both stages and `kubecoder@prd`
crash-looped (v0.8.0, Triage #445; **measured**).
*Stated in:* `run-loop.md`, `plan-template.md`, `skills/run-slice/SKILL.md` Job 3.

**One driver per slice; a phase branch is reconciled against its record.** A `flock` on the slice
folder; every commit the record vouches for must still be on the branch, or the base decides, or
the run bails `lost_work`.
*Origin:* slice 148's P2 gated green on commit `6373316` and round 2 started from a tree with none
of that work — two drivers were running the slice at once in two environments sharing the spec
repo but not the code checkout (v0.9.1, Triage #610; **measured**).
*Stated in:* `runner-state.md`.

**Never call a commit missing from a tree you have not fetched; the driver fetches refs only.**
Preflight pulls once before a run; nothing in a run moves a local branch but the driver's own
merges.
*Origin:* one run's executor called a sibling-repo commit that had been on `origin/main` for a
day "absent from origin" and raised a Blocker over it (`run-loop.md` § Fetch; the executor's rule
9 quotes the same case). Preflight owning the pull is v0.9.13.
*Stated in:* `run-loop.md`, `agents/code-writer.md` rule 9,
[`preflight.md`](../../plugins/dev/docs/preflight.md).

**Never work around an environmental problem — report `blocked`.** A missing tool, a dead
service, a broken harness is the operator's, and an agent that improvises past it hides the fault.
*Origin:* a standing bound of every agent definition since the #175 trims (**ruled**).
*Stated in:* `agents/code-writer.md` rule 8, `docs/AUTHORING.md` § Agent definitions.

## Dispatch and delegation

**The dispatch carries the deterministic facts; the agent reads what they point at.** The
code-writer gets a rendered digest of the plan for its phase, not "read the plan"; the doc-writer
gets the slice's diff on disk, the plan digested whole and the close-out verbs with their argument
shapes.
*Origin:* code-writer sessions read the whole plan in 182 of 184 corpus sessions and then spent a
median 14 turns before the first edit re-deriving what the driver already held (v0.9.7;
**measured**). The digest is 30 KB at the median phase against a 45 KB plan. Doc-writer sessions
round-tripped a 26 k-character diff through a file three times and spent turns on `--help`
(v0.9.9; **measured**).
*Stated in:* `run-loop.md` § The per-phase round and § Doc phase.

**Delegate the reading, keep the judgment; receipts and conclusions, never evidence; delegate,
then yield.** A sub-agent returns a conclusion, not the material; every verdict stays with the
dispatcher; a role that dispatches ends its turn with nothing else in flight.
*Origin:* evidence handed upward sits in the caller's context for the rest of the session — the
cost the delegation existed to avoid. The yield rule came from the doc-writer sessions read for
the doc-phase rework: every survey report landed 18–49 turns after dispatch, past the writer's
first edit, at 15–21 % of the session (`docs/research/doc-phase-plan.md` § 1; **measured**).
*Stated in:* [`agent-dispatch.md`](../../plugins/dev/docs/agent-dispatch.md) § Nested delegation.

**No per-task model routing: Opus at `xhigh` everywhere, three roles pinned to Sonnet.**
*Origin:* two measured failures. The graded writer lane of v0.3.0, retired with the task folders in
v0.4.0, "bought nothing on an inflated base, and 'mechanical' routing produced Opus redos whenever
mechanical turned out to mean judgment" (`agent-dispatch.md`). The plugin's own trial — stepping the code-writer's first round
down to `high` on small-shape plans — moved only output tokens, about 20 % of a round's cost, for
a saving of at most 1 % of a slice against one witnessed 4 % rework strike, and was withdrawn
(v0.7.0 → v0.7.3; **measured**, then **ruled**).
*Stated in:* `agent-dispatch.md` § Models.

**A timeout is a bail, not a retry; a session-limit kill is not an agent outcome.** A stuck agent
is surfaced; an account-limit notice is slept out and the same round redispatched, nothing
counted.
*Origin:* masking a stuck agent hides the problem; counting a killed session as a redo would trip
caps and fuses on an event that was not the agent's (**ruled**).
*Stated in:* `agent-dispatch.md` § Timeouts and § Account session limits.

## Text, authorship and portability

**State every claim once.** Before adding prose, search for what already says it; two copies
diverge, and agents reading different copies behave differently.
*Origin:* the 2026-07-10 docs diet ("state every fact exactly once; no recap sentences"), then
applied to configuration in v0.9.0: adding a second file beside the `CLAUDE.md` contract lines
"would have left two places a project says how its pipeline behaves, and the first bug is a repo
whose two answers disagree" (**ruled**).
*Stated in:* [`docs/AUTHORING.md`](../AUTHORING.md) § Single source of truth.

**Rulings are living text; no correction chains.** A ruling that corrects an earlier one replaces
it in place; git and the review files hold the history. The same "delete, don't tombstone" the
code follows.
*Origin:* a superseded ruling kept alive with a correction after it is read by every downstream
session as two rulings (**ruled**; the plan reviewer flags it, item 7).
*Stated in:* `plan-template.md`, `agents/plan-reviewer.md`.

**An agent without a `description` is silently not registered.** Dispatches fall back to
`general-purpose` with no error.
*Origin:* the dev agents once shipped with only a `name`, on the theory that name-dispatched
agents need no description, and every run silently fell back to `general-purpose` — the files
were present and valid (2026-06-19 commit "agents require a description to register";
**measured** the hard way).
*Stated in:* `docs/AUTHORING.md` § `description` is mandatory.

**Never hardcode a project; never parse the manifest — only `kc` reads it.** Each project
describes itself through `.kubecoder/project.yaml` and `.aiworkflowrc`, both enforced by
preflight.
*Origin:* the plugin rework's decision (`plugin-plan.md` § 1): every Jinja blank and per-repo
constant of the template era became either a `kc` call or a line in the project's own contract.
Onboarding a second project (Ansible) then showed the test, doc and devlock phases had to be
switches, not KubeCoder-shaped defaults (v0.9.0, Triage #579).
*Stated in:* `CLAUDE.md` § Portability;
[`project-contract.md`](../../plugins/dev/docs/project-contract.md).

**No item is ever closed by machine judgment alone; the operator's words are recorded verbatim.**
Triage recommends and the operator closes; requirements land in `slice.md` and rulings in
`plan.md` in the operator's own words; dispositions are written as said, never paraphrased or
completed.
*Origin:* triage's rubric was honed against the research corpus's judge-mode bias and sycophancy
findings (v0.4.4); the plan reviewer names a dropped, softened or substituted requirement "the
worst defect this review exists to catch", because nobody downstream reads `slice.md` again
(**ruled**).
*Stated in:* `skills/triage/SKILL.md`, `skills/plan-slice/SKILL.md` § Your role,
`skills/close-out/SKILL.md` § Bounds, `agents/plan-reviewer.md`.
