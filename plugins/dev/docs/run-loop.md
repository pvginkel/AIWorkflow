# The run loop — the Markdown plan is the queue, the driver is its bookkeeper

`${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py` drives a slice end to end from one operator-legible
phased plan (`<slice>/plan.md`). It owns the whole flow — every phase's dev round, the completion
consult, the test phase, the doc phase — and bails only on **errors** (exit 3) and **operator
questions** (exit 4); the `/dev:run-slice` session that launches it has exactly four jobs and never
drives. What the loop records is [runner-state.md](runner-state.md); session mechanics and models
are [agent-dispatch.md](agent-dispatch.md); the plan's authoring is [plan-loop.md](plan-loop.md);
where every agent puts what the loop will not act on is [close-out.md](close-out.md).

```
while phase := next_unfinished_phase(plan.md):   # re-parsed every iteration, document order
    executor session → gate → reviewer rounds → merge → driver stamps ✅ DONE
loop-tail gate sweep → driver runs lint+build+test per component; report rides the dispatches
completion consult  → outstanding work? phases appended (rising bar), loop again
test phase          → "read the slice-testing-strategy doc and execute"; findings gated the same
doc phase           → "read the slice-doc-plan doc and execute"; diff-based; a coordinator packages, doc-unit sub-agents author
```

## The plan is the queue

Phases are `### P<id> — <title>` headings, id free-form `[A-Za-z0-9]+` — `P3a` inserts between
`P3` and `P4`. **Document order is authoritative; ids are labels.** Each phase opens with a
one-line **`Target:`** naming where it lands — a `kc project list` component, or a sibling repo
path (`../SiblingRepo`) — from which the driver roots its git operations (branch, merge,
dirty-checks in that repo) and picks the gate: `kc project test --project <name>` for a
component; `kc project test` from the sibling's own root when it carries a manifest; no
deterministic gate otherwise (the reviewer is told the state is unverified). The component
set is re-read at every plan parse, so a component a phase registers — declared by a `Creates:`
line under its `Target:` ([plan-template.md](plan-template.md)) — is a valid target from the
moment the creating phase merges, and may be named before that on the declaration's word.

**The spec repo is a legal `Target:`** — a slice whose whole deliverable is the wire contracts
names it, and the driver then branches and merges the tree that also holds its own run record.
The **whole `slices/` tree stays out of the driver's git queries in that repo**: its
dirty-checks (after every session, at merge), and the resume reset, which becomes a scoped
`git restore` so an agent's uncommitted plan.md edit survives it. That is not a special case so
much as the existing rule stated: the workflow's bookkeeping — this run's `log.txt`,
`state.json` and `phases/**`, and every parallel session's — is never a phase's deliverable, and
the driver has never checked it when the target was a code repo. Two guards keep the record
intact: every executor prompt fences it off (stage by name, never `git add -A`), and a run
record found *committed* onto the phase branch bails before the merge's `git checkout <base>`
would unlink the file the live log handle is writing to.

**The plan doc is writable by every agent in the loop — deliberately; this is load-bearing.**
Executors append their done-record and edit later phases their work changes; consult and test
sessions append phases; the operator edits at will. The driver's mechanical bookkeeping is what
keeps the shared doc parseable:

- **Only the driver stamps `✅ DONE <date>`** on a phase heading — mechanically, after review
  passed and the merge landed. Agents never stamp.
- Known phase ids live in `state.json`. A parse error, a vanished phase, or a missing/unknown
  `Target:` is **nudged back to the session that produced it** ("fix the plan doc" — the same
  resume mechanism as the verdict nudge), never treated as fatal while a session can fix it;
  broken with nobody to nudge, it is an operator question.
- New phases appearing mid-run (consult, test findings, operator edits) are picked up on the
  next iteration — the plan is re-parsed before every phase.

## The per-phase round

Fresh **code-writer** session per phase (prompt: *"Execute P\<n\> of slice \<name\>"* plus the
standing contract and **the phase digest** — it works its phase against the live repo from the
digest, runs the gate itself, appends the done-record, commits on the phase branch
`phase/<slice>-P<id>`). The digest is the driver's rendering of what it already holds, appended to
every executor round's prompt (first round and fix rounds alike, rebuilt per round because rulings
and done-records land mid-run): the slice's intent paragraph (slice.md's first) and the plan's
title, the `## Requirements / rulings` and `## Not in scope` sections verbatim, **this phase's
section whole**, earlier phases' done-records (from their `**Done (…)**` opener — not their
phase text, which is the distractor), later phases' headings and `Target:` lines, every
acceptance criterion, and `git diff --stat` of what each earlier phase changed, over the phase's
own landed range in its repo (`landed` in `state.json`, recorded at its ff-merge) — never the
base branch since the slice began, which in parallel lanes carries the other lanes' merges.
The writer reads that instead of the whole plan; the plan stays the file it edits and the file it
opens for what the digest points at. The reviewer's dispatch is unchanged — its re-read of the
whole plan is a feature of the review, not a cost. Then:

- **Branch** — `phase/<slice>-P<id>`, cut from the target repo's base branch and reused for
  every round of that phase. The driver reconciles it against the record before it resets or
  recreates it and again after every executor round: a commit the record vouches for that the
  branch no longer carries is a `lost_work` bail, not a branch to rebuild from base
  ([runner-state.md](runner-state.md), which also carries the one-driver-per-slice lock the
  first such loss came from).
- **Fetch** — before the session, the driver fetches the target repo's `origin` (and every repo
  the run has touched before the test phase). Nothing else in a run fetches: the driver branches
  off the **local** base and ff-merges back into it, so a repo cloned days ago keeps the
  `origin/<base>` that came with the clone, and an agent reading that ref reads the day of the
  clone — one run's executor called a sibling-repo commit that had been on `origin/main` for a
  day "absent from origin" and raised a Blocker over it. Refs only: no local branch moves — the
  pull that brings a base up to its origin is preflight's, made once before the run
  ([`preflight.md`](preflight.md) § Notes on the sync), and a base that moves on origin mid-run
  stays the operator's call. Agents carry the other half of the rule — never conclude a commit is
  missing from a tree you have not fetched yourself.
- **Gate** — the driver runs the target's deterministic gate itself, and that gate is **test
  only**: the executor runs the linter once itself before handing back, and lint or build
  breakage is caught deterministically by the loop-tail sweep and the doc gate — so a per-phase
  lint would tax every phase to save the one that fixes it. Green is recorded
  commit+log and stated in the reviewer's dispatch so the review never re-runs the suite. A red
  gate spawns a **fresh executor fix round** (cap 3, then `gate_red` bails); there is no
  separate fixer in the phase loop.
- **Review** — fresh **code-reviewer** per round against the phase's outcome, the acceptance
  criteria (`verification.json`) and repo conventions. Round 1 full branch diff; rounds 2+ are
  delta-scoped to the fix range. A `blocking` tag needs an anchor from the closed list in the
  reviewer's contract (no anchor is advisory by construction), and the verdict reports every
  finding machine-readably — severity, impact, category, anchor — which the driver persists
  into `state.json`'s history. A fix round resolves the findings tagged **blocking** and
  nothing else — advisory findings stay in the review file and the close-out report (the
  residue rider mops up the mechanical ones), never fixed mid-loop, so each re-review stays the
  size of the blocking fixes rather than everything the writer chose to touch. Fix rounds are
  **failure-first**: a finding with an executable anchor is witnessed — the failing test
  written, the claimed repro run — before any code changes. Witnessed, the test rides the fix as
  its regression test; unable to fail, the finding is **refuted** — no code change, the record
  appended to the round's review file and a Notable-events entry with the refutation evidence
  written to the close-out report by the driver, never relitigated. A fix round that changes no
  code and refutes every blocking finding settles the review; no further round is spawned.
  Round 1's fix is automatic; from round 2 on (and on any `critical`) a fresh consult judges
  the findings against a **funding bar that rises per round** — blocking-only, then
  Blocker-only, then critical-only; a prose-only fix range applies the next step early — before
  an executor round is spent. Backstop cap 5. Findings that merge unresolved are never lost:
  they stay in the review file, and the driver records the merge in the close-out report.
- **Merge** — worktree clean, gate green on HEAD (re-run if it moved; red cannot merge),
  ff-merge into the base branch, branch deleted, stamp.
- Executor terminals: `question` pauses the run for the operator (exit 4 — the answer lands in
  the plan's rulings section and the run resumes); `blocked` is an error bail.

## After the last phase

- **The loop-tail gate sweep** — before any loop-tail dispatch, the driver itself runs
  `kc project lint` + `build` + `test`, per component so every red is visible (component sets
  re-read at sweep time), across every repo
  in `state.json`'s `bases` that carries a kc manifest (spec repo excluded). Full logs land in
  `<slice>/sweeps/r<N>/`; the record is commit-stamped in `state.json` and reused only while
  every swept HEAD is exactly the swept commit — any movement (a consult committing mechanical
  residue, an appended phase merging) re-runs it, so the report a dispatch carries always
  describes the tree that dispatch sees. The completion consult and the test phase both receive
  it as deterministic fact — green suites are not re-run by agents — under one principle, stated
  in both dispatches with no special cases: **a branch whose gates are red is not pushed**. A
  red sweep is the consult's to act on — append a fixing phase, or bail with the question — and
  deliberately not driver-enforced. The incident this front-loads: a known-red docs build
  "owed to the doc phase" was answered `complete`, pushed by the test phase, and failed
  in CI — a spent test session and a failed build for a fact knowable at loop-tail entry. The
  sweep runs before the devlock is taken, so its minute never extends the hold.
- **Completion consult** — one fresh bare session: *"does the plan describe outstanding work?"*,
  judged against both the plan and the repo. It appends phases (or answers `complete`) through
  the generation bar below.
- **Test phase** — a fresh `test-agent` session told to read the project's slice-testing-strategy
  doc (`.aiworkflowrc`'s `test_phase.strategy`) and execute it. **The driver holds the devlock**
  from this phase to the end of the run (a `flock` on the inode `devlock.lease` names; it releases
  on crash); under that hold pushing and rolling dev for verification is pre-authorized — the lock
  *is* the coordination. prd stays operator-gated. Blocking findings come back as appended phases;
  sub-bar findings go in the close-out report; `verification.json` is checked off.
- **The phase is optional** (`test_phase.enabled = false`), as is the doc phase below and the
  devlock — see [project-contract.md](project-contract.md). A project with nothing deployed to
  verify runs neither, and the loop ends when the completion consult answers `complete`. What the
  test phase alone does is checked off `verification.json`: with the phase off, the acceptance
  criteria are still what `code-reviewer` reviews each phase against, but nothing marks them
  verified.
- **The push check** — nothing in the driver pushes a code phase (`_run_phase` ff-merges into the
  base branch locally, primary repo and siblings alike), so pushing what the slice committed is
  the test phase's job **when there is one**. Before the doc phase the driver verifies it
  happened: for every repo in `state.json`'s `bases` — the run's own record of what the slice
  touched, the spec repo excluded — it fetches and compares `origin/<base>..<base>`. A repo left
  behind nudges the test agent's session (cap 2), then bails `unpushed`. The driver **checks
  rather than pushes**: a multi-repo slice may need an order only the agent running the
  verification knows. A reviewed-but-unpushed sibling commit otherwise never reaches the deploy it
  was meant for — one run's dev roll crash-looped exactly that way, its sibling's half of the
  change still local.
- **With no test phase the driver pushes**, at the same point the check would have run — there is
  no other pusher, and without it a slice's siblings never reach origin and a project running no
  doc phase either ends with every commit in the pod. `push.enabled = false` switches the whole
  concern off: no push, no check, and the doc branch lands against the local base. That is a
  standing mode, not an outstanding action, so unlike a plan hold it is logged and not reported.
- **A repo the plan holds is exempt from all of that.** `plan.md`'s `## Push holds` section
  ([plan-template.md](plan-template.md)) names repos this slice must not push. The driver leaves
  them out of the check, states them in the test phase's dispatch — whose procedure doc says
  *push*, so a held repo has to be named as a deterministic fact or the agent is left choosing
  between two instructions — and writes one Outstanding-actions entry per held repo instead of
  nudging and bailing. Before this, a plan's hold was invisible to the driver and the run had two
  exits: violate the ruling or bail. One slice held `../HelmCharts` (a push there deploys dev and
  prd together and rolls both controllers); the test agent honoured the ruling, was nudged twice,
  the driver bailed `unpushed` — and the run session pushed 38 seconds later, crash-looping prd.
- **Doc phase** — after test-complete: auto docs. One `doc-writer` session — the phase's
  **coordinator** — told to read the slice-doc-plan doc (`.aiworkflowrc`'s `doc_phase.plan`) and
  execute it: the doc surfaces that already describe the changed behavior, brought up to date
  from the whole slice's diff, manual + dev docs together, on its own branch, **never pushing**.
  The coordinator walks the diff and surveys the doc tree, writes `<slice>/doc_phase/units.json`
  — one work package per doc scope the project's doc plan defines, each entry a unit's whole
  brief (`agents/doc-writer.md` holds the shape) — dispatches one `dev:doc-unit` sub-agent per
  entry in one message and yields until every unit has reported, then reconciles across scopes
  as the single writer of indexes and decision ids, gates once and commits; a unit authors its
  pages under `agents/doc-unit.md`, commits nothing, and hands back a receipt. The driver reads
  `units.json` back at the hand-back and records each unit's id and page count as
  `doc_phase.units` in `state.json` — recorded, never enforced — and drops a stale file when it
  recreates the doc branch. The phase carries no
  slice task and owes no acceptance criterion: a doc change a requirement names is a phase of the
  plan ([plan-template.md](plan-template.md)), merged before this point like any other. Its
  dispatch carries the driver's deterministic facts, in the phase digest's spirit: the slice's
  diff **on disk**, one `<slice>/doc_phase/<repo>.diff` per repo a phase merged into, a section
  per merged phase (`git diff --stat` on top, then the diff, over the phase's landed range — the
  sha its branch was cut from to the head that fast-forwarded the base — with the spec repo's
  `slices/` tree held out; never the base branch since the slice began, which in parallel lanes
  carried the other lanes' merges and the slice's own run record, and never HEAD, which is the
  doc branch, so a redispatched writer's own commits never read as shipped work; a phase merged
  with no range on record is named in the dispatch as missing from the files), read by path
  instead of re-running `git diff`, which past the tool's output limit round-trips through a
  persisted file; the plan **digested whole** — title, rulings sections, every phase's
  done-record — so the plan is opened only where a record points and slice.md not at all; and
  the close-out verbs the phase uses (`list`, `append`, `note`) with their argument shapes,
  rendered from `close_out.py`'s own parser, plus where the Summary and `Focus:` lines go and
  the `units.json` path — the `--help` round trips and the previous-slice style reads go with
  them. The
  driver then runs the full gate sweep — `kc project lint` + `build` + `test`, fail-fast (red
  is nudged back to the writer's session) — checks local `<base>` against `origin/<base>` (the
  branch rebases onto origin but ff-merges into local, so a local-ahead base bails `blocked`
  before anything is mutated), rebase-merges the branch onto the base branch and pushes; the dev
  roll that push triggers is left to land on its own, untracked. This is the only push the driver
  makes itself, so it is where a hold on the *primary* repo lands: the branch rebases onto the
  local base instead (a held repo's origin is behind by everything the slice did, which is what
  the local-ahead check exists to catch) and the landing stops at the merge.

**The generation bar** terminates the append loop: the first follow-up generation appends only
work the plan *owes* and no phase delivered — a requirement, ruling or acceptance criterion left
undelivered; a touch-up the slice ships without is a close-out entry (one operator word), not a
phase (an executor round, a review round and the consult the generation forces) — the second
appends blocking work only, a third pending generation bails to the operator. Advisory leftovers
go in the close-out report as they are found. One rider holds at every generation: mechanical
residue — comment or formatting fixes with no behaviour change, in files the slice's diff already
touched — is neither reported nor appended; the finder fixes it in place and commits, and the
driver's sweep re-runs on any commit it has not seen, which gates the fix before the loop closes
but never before a push the test phase's own procedure doc orders.

**Close-out.** Nothing from a run is carded per finding: everything an agent noticed but the
loop did not act on is in the slice's `close-out.md` — who writes what there is
[close-out.md](close-out.md). The driver's own part is deterministic: it creates the report at
run start when planning left none, names the report and `close_out.py` (the only way to write to
it) in every dispatch, enters refuted findings and funding-consult merges, renders the report
into reading order before the doc phase and again at completion, and stamps the run header from
`state.json` when the run completes; the launching session re-stamps it once the cost block has
landed and files **one** tracker card pointing at the report.

## Protocol invariants

Every spawned agent ends by writing the verdict JSON named in its dispatch and leaves the
worktree committed; one resume-nudge covers a miss, then a missing verdict counts `blocked` and
an uncommitted tree bails. A session killed by the account's session-limit window is not an
agent outcome: the driver waits out the stated reset and redispatches the same round — nothing
counted. The driver asserts its agent definitions resolve before dispatching anything
(`kc session create-headless --agent` does not validate names).
