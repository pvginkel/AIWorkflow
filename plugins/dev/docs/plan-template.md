# The plan template — plan.md and verification.json, mechanically

The concrete shape of a slice's `plan.md` and `verification.json`, settled so every author —
the interactive `/dev:plan-slice` session seeding the header, the plan-writer completing it, agents
appending phases mid-run, the operator editing at will — produces a doc `run_loop.py`'s parser
drives without nudges. Semantics (who writes which section, review charter, loop mechanics) are
[plan-loop.md](plan-loop.md) and [run-loop.md](run-loop.md); this doc is the shape. Sanity-check
a plan with `run_loop.py run <slice-dir> --dry-run` — it parses, resolves every `Target:`, and
prints the gates without touching anything. Run from the spec repo, it resolves the Targets in
the one code repo whose `.aiworkflowrc` names that spec repo, and stops with "run from the code
repo" when none or several do.

## plan.md

```markdown
# Slice NNN — <one-liner: what ships when this slice is done>

## Requirements / rulings

<!-- Seeded by /dev:plan-slice, in the operator's words; authoritative on intent.
     /dev:run-slice appends mid-run operator answers here. A ruling that corrects
     an earlier one REPLACES it in place — no correction-chains; the round
     history lives in plan_review_r*.md. -->

- R1. …
- Ruling (YYYY-MM-DD): …

## Task shape

<!-- Declared by the plan-writer BEFORE it investigates; checked by the plan
     review against slice.md. One of pre-settled | localized | cross-cutting,
     justified in one line from slice.md facts. -->

pre-settled — slice.md's design section fixes the mechanism; planning is transcription.

## Ordering constraints

<!-- Only what is genuinely ordered beyond "producers before consumers". Often empty. -->

## Push holds

<!-- Optional; almost always absent — omit the heading unless a ruling holds a push. One
     bullet per held repo, `- ../SiblingRepo — <why this run must not push it>`, target
     written as a phase writes its `Target:`. The driver leaves it out of the push check
     and reports it held instead. -->

## Driver rulings

<!-- Optional; almost always absent — omit the heading unless a ruling bends one of the
     driver's fixed rules. The machine-readable half of a ruling whose words stand in
     Requirements / rulings:
       - gate <target> — <substitute, or none> — <why>
       - accept <target> <lint|build|test> — <why>
       - prd <target> — <why> -->

### P1 — <title>

Target: <component>

<The phase: outcome, the few constraints the executor cannot figure out from the repo,
pointers into attachments/. Self-sufficient by reference — no inlined designs.>

### P2 — <title>

Target: ../<SiblingRepo>

<…>

## Not in scope

- …
```

The mechanical rules the parser holds every author to:

- **Every `###` heading is a phase heading** — `### P<id> — <title>` (em dash), id
  `[A-Za-z0-9]+`. Any other `###` line is a structure error the driver nudges back. All
  non-phase sections use `##`, and the driver reads exactly two of them — `## Push holds` and
  `## Driver rulings`; the rest it ignores.
- **Ids are free-form labels; document order is authoritative.** `P3a` inserted between `P3`
  and `P4` runs between them because of *where it sits*, not its name. Ids must be unique.
- **`## Task shape` is the plan-writer's declaration** — `pre-settled`, `localized`, or
  `cross-cutting`, one line of justification anchored in slice.md facts. It binds the writer's
  investigation and the plan review checks it (semantics: [plan-loop.md](plan-loop.md)); the
  run loop's parser ignores it, as it does every `##` section but the next one.
- **`## Push holds` names the repos this run must not push** — one `- <target> — <why>`
  bullet each (em dash), target in the same vocabulary as `Target:` — a scratch clone no phase
  targets, such as a ledger phase's, works as `github:<owner>/<repo>` and as its path
  `../scratch/<Repo>` alike, and the driver never syncs a held clone. The plan loop enters one
  action per held repo in the close-out report at its exit 0; the driver skips
  held repos in its push check, names them in the test phase's dispatch, and notes that entry
  (or writes it, for a hold added after planning). The doc landing merges locally and does not
  push a held primary repo. A
  bullet in that section the parser cannot read is a structure error, not a skip — a hold
  missed silently is a repo the driver pushes. The section is absent from almost every plan.
- **`## Driver rulings` bends a fixed rule of the driver.** Each bullet has a fixed kind, then a
  target written as in `Target:`, with em-dash-separated fields: `- gate <target> —
  <substitute> — <why>` waives the driver's test gate for that target (`none` for no
  substitute); `- accept <target> <verb> — <why>` makes that red sweep row non-blocking (verb
  `lint`, `build` or `test`); `- prd <target> — <why>` authorizes the test phase to run the
  promotion pipeline for it (a push needs no ruling, production included). A sibling path or a
  `github:` target covers every component of that repo; a component name covers that component. What each does in the run is [run-loop.md](run-loop.md) § After the last phase.
  A bullet the parser can't read (unknown kind, missing field, duplicate) or whose target
  doesn't resolve is a structure error, as with holds: a ruling missed silently is a gate the
  driver runs anyway. The prose ruling still goes in Requirements / rulings, in the operator's
  words; this is only its machine-readable half.
- **`Target:` is the first line of every phase body** — a `kc project list` component name, a
  sibling repo path (`../SiblingRepo`), or `github:<owner>/<repo>` for a repo the environment
  does not check out: the driver clones it into `/work/scratch/<repo>` and from there it is a
  sibling path ([run-loop.md](run-loop.md) § The plan is the queue). A repo the environment
  checks out is refused in that form — name it `../Repo`. A `github:` repo without a
  `.kubecoder/project.yaml` has no gate, so its phases need a `gate` line under
  `## Driver rulings` — unless a phase declares that it adds the manifest (`Creates:`, below).
  A component name resolves in the repo the run starts
  from first, and there it shadows any sibling's same name (`root` is this repo's). A name this
  repo lacks is looked up in the sibling repos' own `kc project list`. A component of exactly one
  sibling lands in that repo and is gated there per component; one that several siblings have
  is a structure error, and the phase names the repo path instead. The Target roots the
  executor's cwd, the driver's git operations, and the gate. Markdown decoration is tolerated
  (`**Target:**` with a backticked value), but the line carries nothing else. A phase without a
  resolvable Target is a structure error.
- **`Creates: <component>` declares that a phase registers a new component** — an optional
  line under `Target:` for a phase that adds a `kc project list` entry to the manifest. The
  driver re-reads the component set at every plan parse, so the component is a valid `Target:`
  from the moment the creating phase merges; the declaration is what lets a *later* phase — or
  the creating phase itself — target the name before that: validation and `--dry-run` accept it
  on the declaration's word instead of failing against a manifest that does not hold it yet. A
  declarer stamped done whose component never appeared in the manifest is a structure error. A
  component registered in a sibling repo is declared on the phase that targets that repo
  (`Target: ../Repo` + `Creates: <name>`); later phases may name it the same way. A phase that
  gives a whole-repo Target (a sibling path or a `github:` clone) its first
  `.kubecoder/project.yaml` declares a component that manifest registers (`root` at least). The
  driver reads such a repo's gate from the phase's own tree at gate time, so the phase is gated
  by the manifest it adds whether it declares one or not. The declaration is what lets
  `--dry-run` print `gated once P<n> adds the manifest` for that phase and the later ones on the
  repo, and what lets a `github:` phase run without a `gate` ruling.
- **`Review: <file>` declares a phase's review set outside its Target** — an optional line
  under `Target:` for a phase whose work lands where its Target's diff cannot show it, such as
  unpushed commits in `/work/scratch/<Repo>` clones kept in a ledger. The value is a path
  relative to the slice folder, to a file the phase writes as it commits: one clone and commit
  pair per line, the clone's absolute path and the commit's sha on the same line (a Markdown
  table row does), any other line ignored. **One sha per line:** a parent or base commit beside
  the phase's own makes the line ambiguous, and the driver hands neither on — it shows the line
  to the reviewer to sort out. The reviewer is handed the pairs the phase added or
  changed as its review range, and is told that the driver gated the Target alone
  ([run-loop.md](run-loop.md) § The per-phase round). The name is the plan's; the driver knows
  no ledger file of its own.
- **`Never print: <paths>` marks material that never reaches a transcript** — an optional line
  under `Target:` for a phase whose diff carries what the slice or a ruling says is never printed:
  a key file, an encrypted key, a Secret holding the password to one. The value is one or more
  paths relative to the Target's root, comma- or space-separated. The driver holds them out of the
  review diffs it writes, and the reviewer's dispatch gives it the command shape that prints none
  of them: `git diff --stat` first, then the diff with those paths held out, piped through
  `tools/redact_secrets.py`. A `kind: Secret`'s data needs no line: the driver stubs it in every
  diff it hands an agent ([run-loop.md](run-loop.md) § The per-phase round).
- **A skill the work keeps is named, never restated.** Where a convention a phase must keep is
  a skill's — a host style guide such as `kubecoder:jenkins-pipelines` — the phase names it as
  `` `<plugin>:<skill>` ``, or the requirements/rulings do for every phase. The roles have no
  skill listing; the driver hands the phase's writer and reviewer, and the plan loop the
  planners, the installed file for a name the plan carries
  ([agent-dispatch.md](agent-dispatch.md) § Spawning). A paraphrase of its rules drifts from it.
- **`✅ DONE <date>` on the heading is the driver's stamp.** Only the driver writes it, after
  review passes and the merge lands. No agent ever stamps, and a done phase is skipped on every
  re-parse.
- **Done-records go under the phase's own heading** — appended below the phase text as plain
  paragraphs or lists, **never a new `###`** — in two parts, the summary first:
  1. a bold `**Done (P<id>).**` paragraph — what landed (the files and names that now exist)
     and the gate's result — then a `Later phases:` line and **one contiguous list** of what a
     later phase must know: what is settled beyond the plan's text, the seams and harness it can
     use, what is owed or unexercised. About ten lines together.
  2. the record — the narrative, the witnessed reds, the fix rounds, the gate lines — hard cap
     ~25 lines, settlements not narration.
  The run loop's phase digest hands later phases part 1 only; the doc phase's digest and the
  reviewer read the whole record. A record without the `Later phases:` list rides in later
  dispatches whole (the driver's log names it), and a phase without the opener hands over its
  whole section.
  A find that affects a later phase is edited *into that phase*, where its reader will trip
  over it, not left in the done-record.
- **Phases are roughly PR-sized and independently reviewable** — one branch, one gate run, one
  reviewable diff. A phase outgrowing that splits; a phase *section* outgrowing ~a page
  overflows into `attachments/` (referenced, never inlined). No end-to-end testing phase and
  no auto-doc phase — the loop owns those; a phase's own tests ride the phase.
- **A doc task is a phase.** The loop's doc phase is auto docs only — the doc surfaces that
  already describe the changed behavior, brought up to date from the shipped diff — and it
  carries no slice task. So a requirement that *is* a doc change — a decision to close, a
  design fact to record, a page to correct — is a phase like any other work, with its own
  `Target:` (the spec repo resolves as a sibling, `../<SpecRepo>`), reviewed and merged by the
  loop. A plan that hands such work to the doc phase is a defect the plan review flags — unless
  the project says otherwise: **where the project's slice-doc-plan doc (`.aiworkflowrc`'s
  `[doc_phase] plan`) gives a kind of doc work to the doc phase** — a decision ruled in the slice
  recorded as a row of the project's decision log, say — that kind is the doc phase's, as the doc
  plan says, and no phase writes it. The ruling that sends it there cites the doc plan's line, and
  the plan review does not flag it. The doc plan wins for the kinds it names and no others. When
  later phases cite a record's new id (a decision that supersedes another, cited by a
  supersession marker or a code comment), a phase targeting the spec repo, placed before every
  phase that cites the id, writes that record and allocates the id at append time. The later
  phases take the id from that phase's done-record, never from a number the plan names in
  advance.
- **The plan carries no auto-doc content.** The doc phase writes from the shipped diff and the
  requirements/rulings — the rulings, in the operator's words, are the only steering it gets.
  A doc-deliverable section, drafted prose, or a doc-content attachment for it is a defect the
  plan review flags.
- **Rulings are living text.** A ruling that corrects an earlier one replaces it in place —
  never a correction appended after superseded wording. The same no-tombstone rule the code
  follows; git and `plan_review_r*.md` hold the history.

## verification.json

```json
{
  "items": [
    {
      "id": "V01",
      "area": "<subsystem or requirement cluster>",
      "description": "<outcome-level criterion, in the operator's wording>",
      "owed_after": "<optional: what the run cannot do that settles it — e.g. ../HelmCharts>",
      "verdict": null,
      "rationale": "",
      "evidence": []
    }
  ]
}
```

- **Outcome-level, complete against slice.md's numbered requirements 1:1**, in the operator's
  wording. Add criteria freely; never drop or re-word a requirement without a ruling recorded
  in plan.md's rulings section.
- **`file:line` evidence citations** where a criterion rests on a code fact the author verified
  this pass — the surviving anti-hallucination discipline. A planning-time citation goes in the
  criterion's `description`; `evidence` is the test phase's.
- **Coverage-preservation criteria are allowed** ("no coverage is lost; every deleted test has
  a named successor" — phrased as an outcome, never an inventory of paths). **Doc-truth
  universals are banned** (a criterion asserting prose claims hold everywhere).
- **Every criterion is earned by the plan's phases.** One whose work no phase delivers — a doc
  change assigned to the loop's doc phase, which carries no slice task — is a planning defect
  the plan review flags, not a verdict the test phase can write. Doc work the project's doc plan
  gives the doc phase (above) earns no criterion at all: the test phase runs before the doc
  phase, and the ruling that sends the work there is its record.
- **`owed_after` marks a criterion the run cannot settle** because it waits on an action no role
  in the run may take: a push the plan holds (the hold's target exactly as `## Push holds`
  writes it, e.g. `../HelmCharts`), or, as free text, another operator action. Leave it out
  everywhere else; almost every criterion has none. The plan loop turns it into the close-out
  report's actions, listing the criterion in its hold's entry or giving it a
  `Settle <id> after …` entry of its own, so the operator's runbook carries it from planning on.
- **No other keys.** Both loops bail on an item key outside this schema.
- `verdict`/`rationale`/`evidence` stay empty at planning time — the run loop's test phase
  checks items off (`pass`/`fail` with rationale and evidence). A criterion marked `owed_after`
  whose offline half the test phase has earned takes `owed` — never null, which reads as untested,
  and never free text — until the action it waits on settles it `pass` or `fail`.
- **A settled criterion keeps its `owed_after`**: it is the record that the criterion was proven
  after the run, not in it. Its `rationale` names the action and the date it was settled
  (`Settled pass after ../HelmCharts, 2026-10-20.`), and its `evidence` carries, after the test
  phase's, the operator's words or what was observed once the action had happened. The close-out
  session settles it with `close_out.py settle`, which writes the item in the file's own
  escaping and strikes the action that waited on it ([close-out-template.md](close-out-template.md)
  § The verbs); it never edits the item by hand.
