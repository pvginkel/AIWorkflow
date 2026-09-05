# History — how the workflow got its shape

How the `dev` plugin went from a copied template to a script-driven pipeline between April and
September 2026, told as eras: what the workflow looked like in each, what broke or was measured,
and what that forced. The rules the eras produced are in [`principles.md`](principles.md); the
change-by-change catalogue with each incident's numbers is [`improvements.md`](improvements.md);
the close-out report's own story is [`reporting.md`](reporting.md); the measurement tooling and the
research method are [`measurement.md`](measurement.md) and [`literature.md`](literature.md). The
primary record is [`CHANGELOG-workflow.md`](../../CHANGELOG-workflow.md) (41 entries, v0.1.0 →
v0.9.13), the git log (165 commits through v0.9.13), and [`workflow-improvements/`](../../workflow-improvements/) —
the frozen July 2026 investigation that started the rebuild.

| Era | Dates (2026) | Versions | Shape | What forced the next era |
|---|---|---|---|---|
| The template | 04-11 → 07-09 | — | Copy-and-fill `orchestrator/` + `project/` trees mirrored from a sibling project; a long-lived orchestrator session drives everything | The #175 cost read: the orchestrator session was 53 % of all spend |
| #175 and the task runner | 07-09 → 07-12 | — (in KubeCoder) | `task_runner.py` drives `tasks/NN_slug/` folders; fresh sessions per role; verdict files | Syncing the result back into templates was the wrong destination |
| The plugin | 07-12 → 07-29 | v0.1.0 → v0.3.1 | Installable `dev` plugin; `kc` replaces every hardcoded seam; project describes itself | KubeCoder rebuilt the pipeline against a different plan shape |
| The phased plan | 08-11 | v0.4.0 – v0.4.1 | `run_loop.py` drives one `plan.md` of phases; "the plan is the queue" | Three observed problems (planner deep-dives, comment churn, work amplification) |
| Research run 1 and its batches | 08-13 → 08-14 | v0.4.2 → v0.4.5 | Same loop, with instrumented reviews, anchored findings, a filtering triage | Per-finding tracker cards did not scale |
| The close-out report | 08-15 → 08-17 | v0.5.0 → v0.6.0 | One report per slice replaces cards; tool-written | Cost: every Opus dispatch ran at `xhigh` |
| The effort detour and the push hold | 08-18 → 08-20 | v0.7.0 → v0.8.0 | An effort step-down trial, withdrawn; `## Push holds` after a production incident | A second project (Ansible) needed phases to be optional |
| The project contract | 08-21 | v0.9.0 → v0.9.2 | `.aiworkflowrc` replaces the `CLAUDE.md` contract lines; phases are switches | Research run 2: "the cost of our loop is context, not thinking" |
| Context economics | 08-22 → 08-27 | v0.9.3 → v0.9.9 | Turn taxonomy in every run; prefix trimmed; the plan digested per phase | Production defects on the second project |
| Two projects in production | 08-31 → 09-01 | v0.9.10 → v0.9.13 | Facts the driver held reach every dispatch; the manifest is re-read; preflight pulls | — |
| The unpushed tail | 09-01 → | 0.9.14 → 0.9.20 | Done-records in two parts; a written refinement doc replaces the planning dialog | **Not in this checkout** — see below |

## The template (2026-04-11 → 2026-07-09)

The repo begins as a copy. The second commit (2026-04-12) generalizes the AI workflow of a sibling
project, DesignAssistant — its own subject line says so — lifted out and
turned into a template. The README of the time says it plainly — "This repository is a
**template**, not a library. Copy its contents into a real project and fill in the marked
sections" — with Jinja2 syntax (`{{ variables }}`, `{% block %}`) used only as a visual marker
for what to hand-edit (README at commit `de0fa96`, 2026-06-26). The tree: `orchestrator/` (the
root `CLAUDE.md`, the slice skills `run-slice`, `write-slice`, `triage`, `arch-design`,
`update-docs`, `ux-design`, `quality-improver`, `quality-issue-finder`, `refactor-audit`, the
`/major-change` and `/minor-change` commands, two orchestrator agents), `project/` (a per-subproject
`CLAUDE.md` and the four dev agents `plan-writer`, `plan-reviewer`, `code-writer`, `code-reviewer`,
copied once per subproject), `tools/ai_workflow/` (`claude_session.py`, the session manager the
orchestrator dispatched dev sessions through), `tools/code_health/` (a grader, now under
[`archive/quality/`](../../archive/quality/)), and `specs/` (the slice-number allocator).

The design happened elsewhere. May and June are a stream of "Mirror DesignAssistant Phase N.M"
commits — preflight gates, `verification.py`, `checkpoint.py`, five single-purpose agents, the
major/minor change commands — tracking the sibling project's evolution rather than this repo's own.
Three things from the era survive: the slice-number allocator (2026-06-26, now
`plugins/dev/tools/allocate-next-slice.sh`), the two-board issue model (as the host convention the
plugin's [`project-contract.md`](../../plugins/dev/docs/project-contract.md) § 3 maps its roles
onto, since v0.4.1 took tracker vocabulary out of the plugin's prose), and the rule that an agent
without a `description` is silently not registered (commit `05686df`, 2026-06-19 — now
[`docs/AUTHORING.md`](../AUTHORING.md)). The single-source rule predates the pipeline too: the June
README already sends readers to a writing guide for "what to duplicate (nothing)".

How it ran, from the record that ended it
([`workflow-improvements/ANALYSIS.md`](../../workflow-improvements/ANALYSIS.md) § 1–2, **measured**
over 1,338 conversations): a long-lived root orchestrator session running `/run-slice`, per-project
manager sessions started and resumed through `claude_session.py`, and dev agents as their
sub-agents. The orchestrator re-primed `CLAUDE.md` and the slice context on every resume, held
200–330 k-token contexts for hours, and ran the full test suite and the live-deploy verification
itself.

## #175 and the task runner (2026-07-09 → 2026-07-12)

Trello card #175, "Workflow improvements", opened with a cost read of every KubeCoder slice run to
date. The headline (`ANALYSIS.md` § 2, deduplicated by `message.id`): **≈ $5,223 total, of which the
root orchestrator sessions were $2,763 — 53 % — and all manager sessions together 68 %**; the
sub-agents everyone had been looking at were 32 %. Three slices were deep-read as exhibits: 052
($273, 57 conversations; 6 plan-writers, 6 plan-reviewers, 9 code-writers, 8 code-reviewers on one
slice), 038 ($163, the root session 70 % of it, re-entered about twelve times), and 044 ($171, one
code-writer implementing a four-phase plan in 167 turns with its context grown from 4 k to 330 k
and re-read on every turn). The companion
[`ORCHESTRATOR-COST.md`](../../workflow-improvements/ORCHESTRATOR-COST.md) put inline live/E2E
verification at 30–53 % of an orchestrator session.

The design that answered it is written down in
[`workflow-improvements/PLAN.md`](../../workflow-improvements/PLAN.md) under the sentence the whole
pipeline still rests on: **"Files are durable, sessions are ephemeral.** No long-lived LLM session
drives execution; a Python state machine does." `/triage` → `/plan-slice` → `/run-slice`, with
`task_runner.py` taking each `tasks/NN_slug/` folder through branch → fresh `code-writer` → fresh
Sonnet `code-tester` (cap 3) → `code-reviewer` (cap 2) → ff-merge → checkpoint consult, every
outcome a verdict file, `state.json` the resume point, and bail-outs instead of conversation. The
lesson from slice 038's twelve re-entries became contract: "scream, don't adapt" — an agent never
works around an environmental problem, it reports `blocked` and stops.

It was built and validated in `../KubeCoder`, not here; the changelog entry of 2026-07-10 is titled
"developed in KubeCoder, not yet synced here". The validation is in `PLAN.md` (**measured**):
slice 072 ran all-in at ≈ $137 and ≈ 5 active hours against the old workflow's size-comparable
majors at $150–283 and 15–42 hours, with the orchestrator share falling 53 % → ≈ 13 %; slices
074–078 followed at ≈ $402 for the batch, 19 of 19 tasks merged, zero bail-outs, no round cap ever
hit, orchestrator share holding ≈ 15 %. The same review found the residual cost was "turn count ×
context size (cache reads ~40× output tokens)" and that sessions rarely batched tool calls — the
first appearance of the theme research run 2 would return to in August.

## The plugin (v0.1.0, 2026-07-12 → v0.3.1, 2026-07-29)

The plan had said the validated design would be synced back into the templates. Two days later
[`plugin-plan.md`](../../plugin-plan.md) reversed that: "instead of copy-and-fill templates, the
workflow becomes an installable Claude Code plugin named `dev`, and this repo becomes its home."
v0.1.0 (2026-07-12) collapsed the three project-specific seams into `kc` — `PROJECT_DIRS` →
`kc project list --output=json`, `claude_session.py` → `kc session create-headless|send|status|end`,
the cache-TTL environment variable → `-e` on `create-headless` — and replaced every Jinja blank with
either a `kc` call or a machine-checkable `CLAUDE.md` line (`Spec repo:`, `Slice testing strategy:`,
`Design philosophy:`), enforced by a new `preflight.py`. The `orchestrator/` and `project/` trees
were deleted in the same change. It shipped "not yet live-tested against `kc`"; the operator
validated on real slices.

Four days later (2026-07-16) the first post-plugin sync from KubeCoder brought the change that
names idea two of the current `CLAUDE.md`: **"the runner runs the gate; the tester becomes a
fixer."** The `code-tester` agent — a session spawned to learn whether the suite was green — went;
"detecting green is deterministic … only fixing red needs a model", so a `test-fixer` spawns only on
red and its `clean` is confirmed by a gate re-run, never trusted. The same day the six commands
became skills (Claude Code had tagged `commands/` deprecated), `/dev:onboard` arrived, the allocator
moved into the plugin, and the merge runbook became `/dev:merge-repos`.

v0.3.0 (2026-07-29), "the last KubeCoder sync", ported 35 KubeCoder commits and deleted KubeCoder's
copy: "the plugin is the workflow's only home". It carried the review economics the loop still runs
— round 1's fix automatic, every later `issues` verdict to a funding consult against a bar that
rises each round, the old cap surviving only as a backstop of 5 — and three things the next era
would retire: a grounding ledger with mechanical drift checking, a graded writer lane (`task.json`'s
`grade` picking round 1's model), and a plan loop with a review budget of 4. v0.3.1 added `kc
status` to preflight. Then KubeCoder, still the proving ground, "vendored 0.3.1 back onto its `main`
on 2026-07-31 and rebuilt the pipeline there … against a design that replaces the task-folder model
with a phased plan" (v0.4.0).

## The phased plan (v0.4.0, 2026-08-11)

v0.4.0 is the architecture the plugin runs today, ported home from KubeCoder's rebuild with
KubeCoder's copy deleted in the same change. **"The plan is the queue."** `task_runner.py` became
`run_loop.py`, driving one `plan.md` of `### P<id>` phases instead of task folders; each phase opens
with a `Target:` line naming a component or a sibling repo (cross-repo phases first-class);
document order is authoritative; only the driver stamps `✅ DONE`; every agent may edit the plan,
and appending a phase is how work grows, bounded by a generation bar. The loop took over the whole
slice: a loop-tail lint+build+test sweep, a completion consult, a test phase and a doc phase, with
two new agents (`doc-writer`, `rebase-agent`). The plan loop stopped iterating — one writer pass,
one reviewer pass, exit; findings to the operator. The grounding ledger and four agents
(`plan-briefer`, `plan-scribe`, `slice-grounder`, `slice-verifier`) were retired outright, and the
residual-sweep lane (`sweep_slice.py`) was added for card-described work that needs no planning.
Four pilot slices — 114, 125 and the parallel pair 104/107 — ran it end to end at $56–164 each
(**measured**, changelog v0.4.0).

The repo itself changed character here: `kc project test|lint` now ran the plugin's ~4,700-line
suite (159 tests) from this repo — "before, nothing in AIWorkflow could run them, which was
survivable only while KubeCoder held a copy" — and `slice_cost.py` shipped inside the plugin,
pricing a run from its own state records rather than from regex over transcripts. v0.4.1 the same
day stripped tracker vocabulary (Trello, board and list names) out of the plugin's prose for the
workflow's own roles and states (commit `ba49d3f`; its changelog entry was added on 2026-09-02).

## Research run 1 and its batches (v0.4.2 → v0.4.5, 2026-08-13 → 08-14)

With the loop stable, the operator wrote down three observed problems
([`docs/research/research.md`](../research/research.md) § Observed problems): **A**, the planner
"performs an extensive investigation" regardless of task size, after "an earlier attempt to grade
tasks by complexity upfront and route them to different models/effort levels produced poor
results"; **B**, comment churn — reviewers weakening comment claims "will" → "may" at real cost and
no functional value; **C**, work amplification — "more work comes out of the loop than goes in".
Eighteen papers were fetched as Markdown (2026-08-14), read against the loop, and turned into a
catalogue of 25 interventions ([`interventions.md`](../research/interventions.md)); six shipped the
same day as v0.4.3 (findings telemetry, the anchoring taxonomy, demonstrate-failure-first fix
rounds, the cost readout, the task-shape declaration with question-gated research), preceded by
v0.4.2's fix-rounds-resolve-blocking-only (Ansible slice 013: "$45, 3h wall for a small slice",
two of three phases spending round 2 on comment wording) and followed by v0.4.4's filtering triage
and v0.4.5's comment rules (comments must state a witnessable condition; a prose finding must show
the text is wrong, not merely different). The grounding case for A1/A2: slice 153 "spent $27.72
before any code existed on a slice whose slice.md said 'you are not designing anything'". This is
also when the repo got its own `CLAUDE.md` (commit `cc488f1`) and the stdlib-only rule was relaxed
for research tooling (`f11a980`). How the papers were read is in [`literature.md`](literature.md).

## The close-out report (v0.5.0 → v0.6.0, 2026-08-15 → 08-17)

The loop's reporting surface had been a tracker card per finding. Ansible slice 007 produced ten
cards for one slice, of which one was a must-act
([`docs/research/close-out-report.md`](../research/close-out-report.md)). v0.5.0 replaced every
per-finding card with **one document per slice**, `close-out.md`, written by every agent as it goes
and dispositioned by the operator in one sitting; the run's only tracker output became one card
pointing at the report. Five entries in three days refined one document's contract — the entry
shape into the file and the generation bar re-priced against "one word" (v0.5.1), a durable seam
for triage after an 86-card run (v0.5.2), the `Consequence:` line as a bold label after reading six
finished reports (v0.5.3: 76 entries, 22 struck in-run, 7 tracker cards "against ten cards for one
slice under per-finding carding"), evidence classes `witnessed`/`read` on every claim (v0.5.4), and
finally `close_out.py` as the only pen (v0.6.0: in slice 154, "10 of the 16 Bugs were struck in-run
and sat, full-bodied, ahead of the six the operator had to decide on"). The design, its hypotheses
and the numbers are [`reporting.md`](reporting.md)'s subject.

## The effort detour and the push hold (v0.7.0 → v0.8.0, 2026-08-18 → 08-20)

Every Opus dispatch had run at `xhigh` since the graded lane was retired. v0.7.0 trialled one
rule at one site — the code-writer's round 1 steps down to `high` on a `pre-settled` or `localized`
plan, with a fuse and pre-committed kill criteria — and v0.7.1/v0.7.2 patched its bookkeeping. On
2026-08-19 v0.7.3 withdrew all three (§ Reversals below). v0.7.4 moved "wait by notification, never
by polling" out of the plugin's three copies into the KubeCoder pod preamble, and v0.7.5 settled
that the per-phase gate is `kc project test` and only test.

v0.8.0 came from a production incident (Triage #445): slice 135 held `../HelmCharts` by operator
ruling, the test agent honoured the hold, the driver's blanket push check nudged twice and bailed
`unpushed`, "and the run session pushed 38 seconds later — `IaC/HelmCharts` #5668 deployed both
stages and `kubecoder@prd` crash-looped." `plan.md` gained `## Push holds`, the one `##` section the
run loop reads, and a held repo became an outstanding action instead of a bail.

## The project contract (v0.9.0 → v0.9.2, 2026-08-21)

Onboarding a second real project, Ansible, exposed that the dev lock, the test phase and the doc
phase "have to be optional, because none of them (or only part) apply to an Ansible repo" (Triage
#579). Two of the switches half-existed as `CLAUDE.md` lines and the third was inferred from a
`scripts/` directory happening to exist in the spec repo — "a hardcoded convention in a plugin
whose first constraint is portability". v0.9.0 moved the whole contract into `.aiworkflowrc`
(TOML, stdlib `tomllib`), deleted the four `CLAUDE.md` lines, made every phase an opt-out switch
that defaults on (devlock defaults off), refused unknown keys, and gave the driver its own push
when there is no test phase to do it. The reasoning against a second file is the single-source
rule applied to configuration: "the first bug is a repo whose two answers disagree".

v0.9.1 answered a forensic finding (Triage #610): slice 148's P2 "gated green on commit `6373316`,
and round 2 started from a tree with none of that work" — two drivers had been running the same
slice in two environments, sharing the slice folder on the spec repo but not the checkout. A
`run.lock` and a branch-reconciled-against-its-record check followed. v0.9.2 ruled that the doc
phase is "auto docs" and carries no slice task, after fourteen `owed_to_doc_phase` acceptance
verdicts were found sitting unverified in `slices/completed/`.

## Context economics (v0.9.3 → v0.9.9, 2026-08-22 → 08-27)

The withdrawn effort trial had exposed what the second research run made its subject: "the cost
of our loop is context, not thinking"
([`research-2-prompt.md`](../research/research-2-prompt.md)). A profiler replayed 809 sessions
across 32 slices and the second briefing was answered on 2026-08-22; the follow-through is
[`turns-plan.md`](../research/turns-plan.md) and every entry of this era cites a read from it.
v0.9.5 lifted the turn taxonomy into the plugin (`turn_profile.py`), so every run records what its
turns did, not only what they cost. v0.9.6 switched the operator's auto-memory and Claude Code's
bundled skills off in every dispatched session — "in 809 corpus sessions no dispatched role read
or wrote a memory file" — for a measured 3.3–4.0 k tokens off every turn's prefix; v0.9.8 finished
the trim with `--disable-slash-commands` and `--strict-mcp-config` once `kc` passed the flags
through, for `ctx1` of 24–25.5 k against the corpus's 31–34 k. v0.9.7 replaced "read the whole
plan" — "15–74 KB of it, the top orientation read in the corpus", a median 14 turns before the
first edit — with a phase digest the driver renders into every executor round, measured at 30 KB
(≈ 7.7 k tokens) at the median phase over 296 phases. v0.9.9 did the same for the doc-writer after
three sessions were read turn by turn: survey sub-agents whose reports "arrived 18–49 turns after
dispatch, past the writer's first edit", a diff round-tripped through disk, and tail mechanics
rediscovered each time. The tooling and what it found are [`measurement.md`](measurement.md).

## Two projects in production (v0.9.10 → v0.9.13, 2026-08-31 → 09-01)

Four entries in two days, three of them the same class of defect — a fact the driver held but did
not hand to every dispatch that needed it, or read once and never again. The change-discipline
pointer rode every run-loop dispatch but never a planning one, and slices 142, 179 and 184 "each
had to rediscover that by hand" (v0.9.10, Triage #738). `close_slice.py` read a letter-suffixed
folder as its numeric prefix and could not parse AnsibleSpecs' README (v0.9.11; the operator ruled
the id scheme — whole numbers only — rather than the regex). `run_loop.py` snapshotted `kc project
list` once at run start, so slice 181's new component "stayed invalid for the whole run" and its
plan had to fake every desktop phase onto an existing component (v0.9.12, #746) — the component set
is now re-read at every plan load, and `Creates:` declares a new one. v0.9.13 absorbed the one
pre-step the pipeline did not own, the operator's pull-every-repo script, into `preflight.py`.

A caveat for anyone reading runs from this period: the installed marketplace copy is what
actually runs, and its reflog shows it sat on the 2026-08-23 build (0.9.8) until 2026-09-01 07:59
— so 0.9.9–0.9.11 never ran alone, and slices 190–196 are the only runs on 0.9.12/0.9.13 in the
corpus (**measured**, `~/.claude/plugins/marketplaces/aiworkflow` reflog on this pod).

## The unpushed tail (0.9.14 → 0.9.20, 2026-09-01 →) — not in this checkout

This pod's checkout, `origin/main` and the installed marketplace are all at 0.9.13. The versions
below exist as local commits in another environment, known here only from session notes; verify
each against the changelog once they are pushed.

- **0.9.14** — the doc phase in two stages (reverted in 0.9.29, § Reversals). **0.9.15** — the completion consult priced apart in
  the cost readout. **0.9.16** — the shipped diff the doc-writer reads is the slice's own landed
  ranges; a second half ("yield boundary") was reversed the same evening (§ Reversals).
- **0.9.17** — done-records in two parts: a `**Done (P<id>).**` summary paragraph plus a `Later
  phases:` list, then the record, so the phase digest carries the summary rather than the whole
  record. The operator's call after seeing slice 181's P8 record: "we're polluting the start of
  the context". (0.9.18 is not in the notes.)
- **0.9.19** — the planning dialog is gone. A read of 49 slices and 317 `AskUserQuestion` dialogs
  found the operator deviating from the recommendation 19 % of the time and 8 of 10 "let's talk"
  moments re-asked as dialogs; the ruling is no dialogs in `/dev:plan-slice`, a `refinement.md`
  per slice written by a sub-agent from what the session collects, agree-or-comment in chat.
  **Untested** — the first four slices on it are the read. [`plan-refinement.md`](plan-refinement.md).
- **0.9.20** — the KubeCoder memory handover (#785): a bail restores bases only from the run's own
  `phase/<slice>-` branches, the spec repo is asserted on its base before every dispatch and driver
  commit, a merge rebases onto a moved base, `triage_verbatim.py check|restore`.

## Reversals and dead ends

### The `code-tester` agent (2026-07-10 → 2026-07-16)

Born in the task-runner design as a "fresh Sonnet code-tester per round (cap 3), fixes-and-closes
trivial issues" (`PLAN.md`). Retired six days later: "Detecting green is deterministic — no session
is spawned to learn the gate's color — and only fixing red needs a model, so a `test-fixer` spawns
on red and its `clean` is confirmed by a gate re-run, never trusted" (changelog 2026-07-16). The
bullet names no slice; the same sync cites slice 084 for the grounding ledger ("each fix round
minted new false claims") and slice 082 for the review budget below. What survived: the gate as the
driver's own act, and `test-fixer` on Sonnet.

### The review cap plus grants (2026-07-16 → v0.3.0)

The same 2026-07-16 sync made the review cap "a budget (2 → 3, extendable by 2 grants to 5)" after
slice 082, where a finding raised in the final round had its fix written but never re-reviewed —
"4 of 11 tasks, every one a real defect". Thirteen days later v0.3.0 replaced it: round 1's fix automatic, every later `issues` verdict to a
funding consult "that judges the findings against a bar that rises each round, and the old cap
survives only as a backstop (5) at which funding is withheld". The rising bar is what the loop
runs today (`plugins/dev/docs/run-loop.md`).

### The grounding ledger (v0.3.0 → v0.4.0)

Claim→source ledgers with mechanical drift checking — `grounding_check.py`, `grounding_dispatch.py`,
a `slice-grounder` agent, `--repair` for moved anchors, tiered re-grounding — arrived in v0.3.0
(after slice 084's "vague sentence sharpened into a precisely false one") and left in v0.4.0:
"Grounding survives as evidence citations in `verification.json`, whose acceptance criteria are
outcome-level." The record gives no failure of the ledger itself; it fell with the design it was
attached to.

### The task-folder model (2026-07-10 → v0.4.0)

`tasks/NN_slug/` folders, "3–6 ordered, project-local tasks" with ten the hard limit, a letter suffix to insert
one mid-run, `/write-task` to author one — the unit of the whole #175 design. v0.4.0 replaced them
with `plan.md` phases ("a plan phase is a heading, not a folder to author"). The changelog says the
pilots ran "with the pathologies the redesign targeted staying dead all four times" without naming
them; the redesign's own execution plan named four, with per-pilot receipts
(`KubeCoderSpecs/ai-workflow-redesign/execution-plan.md`, retired 2026-09-03 — in that repo's git
history). **Orchestrator context growth**: slice 126's orchestrator cost $54–69 on its own, against
$2.20 / $4.76 / $1.27 / $1.32 across the four pilots once the four-job charter bounded it. **The
doc-truth cascade** ($52 on 126) and **the verifier fan-out** ($32) — the follow-up tail the
generation bar replaced with $6.71 of absorbed touch-up phases plus cards. And **grading**, retired
outright (the section below). What stays unwritten is the task-folder model's *own* failure mode:
`ANALYSIS.md`'s exhibit for the template era, slice 052's 6+6+9+8 rounds, is the closest the record
comes to what unbounded per-task loops looked like.

### The graded writer lane (v0.3.0 → v0.4.0) and the effort step-down (v0.7.0 → v0.7.3)

Two attempts to spend less on the writer, both withdrawn. v0.3.0's graded routing picked round
1's model from a `grade` in `task.json` (`mechanical` → Sonnet, `standard` → Opus, `gnarly` →
Fable); it went with the task folders, and `research.md` records the verdict — "an earlier
attempt to grade tasks by complexity upfront and route them to different models/effort levels
produced poor results". The operator's later ruling on Sonnet as the writer, in
[`status.md`](../research/status.md) A3: "it really did not pan out".

v0.7.0 tried effort instead of model: the code-writer's round 1 at `high` rather than `xhigh` on
small-shape plans, with a fuse and kill criteria pre-committed in
[`a3-plan.md`](../research/a3-plan.md). v0.7.3 withdrew it after four slices, on the operator's
decision rather than the kill rule — the last read (commit `c206e74`) is titled "no kill event and
no power", and the v0.7.3 entry gives the reasoning: "the seven `high` round-1s on slices 160
and 161 all signed off on round 1 — but every `high` round the trial ever ran sat in the
small-phase band where `xhigh` draws a blocking finding only 5–10 % of the time, so the trial could
not gain power; and effort moves output tokens, which are ≈ 20 % of a writer round's cost (context
is the rest), so the saving was ≤ 1 % of a slice against one witnessed ≈ 4 % rework strike (158
P2). The operator's ruling: additional complexity, dead weight — whoever wants the knob in this
loop can build it for themselves." Everything the trial added to state, headers and `slice_cost.py`
came out; the research record stands as written. The trial's real product was the next research
run: if effort reaches only 20 % of a round, context is the lever.

### Per-finding tracker cards (2026-07-10 → v0.5.0)

The loop's reporting surface for its first five weeks. Replaced by the close-out report when one
Ansible slice produced ten cards with one must-act among them; the gates whose purpose had been to
limit carding — "worth a card", "no fix proposals", "a card must never cost the operator more to
triage than the fix costs to make" — came out with it (v0.5.0). [`reporting.md`](reporting.md).

### The `upkeep` plugin (2026-07-12 → 2026-08-03)

v0.1.0 parked the template's auxiliary commands (`update-docs`, `refactor-audit`, `quality-*`) and
the documentation-model doc under `plugins/upkeep/` as "backlog for a planned second plugin".
Never built; deleted on 2026-08-03 (commit `e4e7e55`). The quality capability sits in
`archive/quality/`, parked "while the tool is rebuilt".

### The "yield boundary" half of 0.9.16 (2026-09-01) — not in this checkout

From session notes: 0.9.16 shipped a rule that a headless session which backgrounds a command is
not resumed when the command completes, diagnosed from slice 192's P3. The diagnosis was wrong — 71
corpus cases showed a session *is* resumed on completion; 192 P3's command had hung, and a
backgrounded command has no deadline. The rule was reversed the same evening; the fix (an outer
`timeout(1)` on anything that can hang) lives in KubeCoder's managed `CLAUDE.md`, not in the plugin.
A one-slice read producing a wrong rule is the failure mode
[`left-field.md`](../research/left-field.md) § 8 proposes process-behaviour charts against.

### The two-stage doc phase (v0.9.14 → v0.9.29, 2026-09-01 → 09-05)

0.9.14 split the doc phase: the doc-writer became a coordinator that surveyed the doc tree, wrote
`units.json` — one work package per documentation scope — dispatched a `doc-unit` sub-agent per
package, yielded until all had reported, and reconciled across scopes. The proposal's case was
MemDocAgent's per-unit work plus an external consistency check
([`literature.md`](literature.md)). Nine slices later the operator's measure — the doc phase as a
share of the slice's round-1 code-writer spend, a base that scales with the shipped work — put the
single-stage phase at 64 % of the writer on 5+-phase slices and the two-stage one at 128 %: about
twice per phase of shipped work, ≈ 1.5x per file, with 22 % of its spend lost to waiting gone wrong
(three rounds killed by the engine race with surveys in flight; one coordinator spinning 354 no-op
`true` calls while writing "ending the turn", $21.49 of a $32.17 phase). The unit *was* the
hand-over-document design measured: a fresh session re-orients on its own account whatever the
brief says, ≈ 4 turns a page against the single writer's 2.5. Reverted 2026-09-05 as 0.9.29 —
"we should revert the changes" — keeping what the split taught: the reconcile as a named step, a
claim left unverified named in the verdict, a two-agent survey cap, and one line in
`agent-dispatch.md` that ending the turn is a reply with no tool call
([`doc-phase-read-2026-09-04.md`](../research/doc-phase-read-2026-09-04.md) § 5–6) — **measured**.

### The MCP-schema-bloat claim (July 2026, research-side)

Early drafts of the orchestrator deep-dives attributed ≈ $7.76 of a session's fixed context floor
to MCP server schemas. Retracted in `ORCHESTRATOR-COST.md` after verification: "These sessions load
MCP tools **lazily** via `ToolSearch` … there is nothing to gain by trimming the MCP surface". The
two deep-dive files behind the claim carry a correction banner; the ranked-actions table strikes
the action and marks it "**none — rejected** (lazy-loaded)". A different, verified version of the idea shipped a month later: the
*listing* of MCP tool names and skill descriptions — not the schemas — was ≈ 3.6 k tokens of every
dispatched prefix, and v0.9.8 removed it.

## What stayed constant

- **Files are durable, sessions are ephemeral.** The title sentence of `PLAN.md` (2026-07-10); idea
  two of the repo's [`CLAUDE.md`](../../CLAUDE.md) today, with "scripts drive, agents judge" beside
  it — already paired with it in `plugin-plan.md` § 2 (2026-07-12), applied since the 2026-07-16
  gate rework, and spelled out again in v0.6.0 ("the shape is mechanical, the content is judgment").
- **Measure, then change.** The pipeline began with a cost read (`ANALYSIS.md`) and every era since
  has carried its own instrument: `slice_costs.py` → `slice_cost.py` (v0.4.0; its derived ratios v0.4.3) → `turn_profile.py`
  (v0.9.5), with the research runs' readouts in [`docs/research/`](../research/).
- **State every claim once.** The template-era writing guide's "what to duplicate (nothing)", the
  2026-07-10 docs diet ("state every fact exactly once"), and [`docs/AUTHORING.md`](../AUTHORING.md)
  now; applied to configuration in v0.9.0 and to the report's head comment in v0.9.3.
- **Never work around an environmental problem.** "Scream, don't adapt", contract since `PLAN.md`;
  a bound in every agent definition today.
- **The operator decides; the loop asks by bailing.** Exit 4 as the operator question from
  `task_runner.py` onward; the plan loop's one round with rulings edited into `plan.md` (v0.4.0);
  dispositions in the operator's own words on the close-out report (v0.5.0).
