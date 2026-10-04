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
doc phase           → "read the slice-doc-plan doc and execute"; diff-based, single writer
```

## The plan is the queue

Phases are `### P<id> — <title>` headings, id free-form `[A-Za-z0-9]+` — `P3a` inserts between
`P3` and `P4`. **Document order is authoritative; ids are labels.** Each phase opens with a
one-line **`Target:`** naming where it lands — a `kc project list` component, or a sibling repo
path (`../SiblingRepo`) — from which the driver roots its git operations (branch, merge,
dirty-checks in that repo) and picks the gate: `kc project test --project <name>` for a
component, run from the root of the repo that lists it; `kc project test` from the sibling's own
root when it carries a manifest; no
deterministic gate otherwise (the reviewer is told the state is unverified). **`Target: root` is
the repo as a whole**: its gate is `--project root` first, and when that ran nothing — kc's exit
3, a root that declares no `test:` — bare `kc project test`, every component once. Root's own
`test:` is what a manifest's author made the whole-repo gate (KubeCoder's `root` is the uv
workspace; the Go and TypeScript components are disjoint suites, and running bare there would
run them all for a Python-only phase), and a root without one (FieldnotesApp, on purpose — its
CI runner would run both suites again) was never gated at all; either way no suite runs twice.
Every dispatch that names a `kc project … --project <component>` gate says that exit 3 is kc's
"nothing ran", not red — the component declares no statement for the verb — and the agent says
what it checked instead. A component is the
invoking repo's first. A name it lacks resolves in the one sibling repo whose `kc project list`
has it (read lazily, only for such a name), and several owners ask for the repo path; the
environment's repos sit side by side, the layout `../` Targets already assume. The component
set is re-read at every plan parse, so a component a phase registers — declared by a `Creates:`
line under its `Target:` ([plan-template.md](plan-template.md)) — is a valid target from the
moment the creating phase merges, and may be named before that on the declaration's word.

**`Target: github:<owner>/<repo>` names a repo the environment does not check out.** A sibling
path must exist under `/work`, and putting it there took a `repos:` entry in the project's
`.kubecoder/config.yaml` — the repo in every environment of the project for one slice's sake.
KubeCoder puts a task's repo in `/work/scratch/<repo>`, so the driver clones it there, hard-coded,
and from then on it is a sibling path: branched, merged and pushed in that clone, gated by `kc
project test` from its root when it carries a manifest. The first resolution in a process clones
it, or adopts a clone already there: origin must be that repo, and a dirty clone, a detached HEAD, a
`phase/` branch, no upstream or commits ahead of origin are refused; otherwise it is fetched and
fast-forwarded. A clone the run has already recorded as one of its repos (a resume over its own
merged phases) is only checked, never synced. Every resolution calls the one helper
(`tools/github_target.py`) — the phase, the dry run (which is where planning clones it), the plan
loop's held-repo name — and preflight's sync covers the clones it made
([preflight.md](preflight.md) § Notes on the sync). Refused outright, before any clone: a repo
some checkout under `/work` already has as its origin — the environment's own, named `../Repo`
instead. A `github:` repo without a manifest has no gate, and its phase needs a `gate` line under
`## Driver rulings` ([plan-template.md](plan-template.md)): without one the dry run lists a plan
problem and the run refuses the phase. The first phase a run resolves on a clone leaves an
action in the close-out report suggesting the operator delete it once the slice's commits are
on origin.

**The spec repo is a legal `Target:`** — a slice whose whole deliverable is the wire contracts
names it, and the driver then branches and merges the tree that also holds its own run record.
The **whole `slices/` tree stays out of the driver's git queries in that repo**: its
dirty-checks (after every session, at merge), and the resume reset, which becomes a scoped
`git restore` so an agent's uncommitted plan.md edit survives it. That is not a special case so
much as the existing rule stated: the workflow's bookkeeping — this run's `log.txt`,
`state.json` and `phases/**`, and every parallel session's — is never a phase's deliverable, and
the driver has never checked it when the target was a code repo. Two guards keep the record
intact: every dispatch that commits into that tree — executor, reviewer, consult — carries the
fence (stage by name, never `git add -A`), and a run record found *committed* onto the phase
branch is taken back out by the driver before any `git checkout <base>` — at the merge and at a
bail — that would unlink the file the live log handle is writing to: `git rm --cached` of those
paths and one commit by pathspec on the branch, so every commit already there keeps its sha (a
rewrite orphans `reviewed_head`, and the next resume bails `lost_work` on it; slice 238 P5 paid
four bails and a hand rewrite for the reviewer's `git add -A`). The spec repo's history then
carries a snapshot of the record under that phase's merge, which is harmless — the folder is
committed whole when the slice closes. The same exclusion lets an edit to this
slice's own tracked files pass the dirty-checks uncommitted — a reviewer's `close_out.py append`
it did not commit — and `git checkout <base>` then refuses to overwrite it, leaving the shared tree
stranded on the phase branch. So before the driver checks the base out of that branch, at the
merge and at a bail, it commits those edits onto the branch itself: this slice's folder only,
tracked files only, the run record excluded. A head that moved only inside `slices/` keeps the
gate's green.

The tree is shared with parallel sessions — other runs, plan loops, the operator's own — so
where it sits matters past this run. **Its HEAD is leased.** Every session either loop runs
commits into that tree during its turn — a done-record, a close-out entry, the plan — and a
phase that targets the spec repo moves the tree's HEAD onto its branch; the two are held apart by a
reader/writer lease on the tree (`dev-spec-tree.lock` in the spec repo's git dir, a `flock` like
the devlock's). Every dispatch and every nudge, and every commit of the driver's own, holds it
shared for exactly the session's or the commit's duration; a phase whose `Target:` is the spec
repo holds it exclusive from its branch checkout to its stamp, and a bail lets it go once the
base is checked back out. A writer waits for the sessions in flight to end and its intent holds
new ones off — writers are preferred, so a stream of dispatches cannot starve one; a reader
waits for the phase to merge. A wait is logged once with the holder and announced once, and one
past `SPEC_TREE_MAX_WAIT` (four hours, the devlock's cap) bails `spec_tree_timeout`. Slice 224's
P1 executor committed its done-record onto `phase/223-P1` seconds after slice 223's driver
checked that branch out, and the assertion below caught it only after the round:
the assertion is the check, the lease is what makes it hold.

A bail (either exit) checks every repo the run touched back out onto its base branch when the
tree is clean and the branch is this run's own — a branch it did not create is a parallel
session's business, and a checkout under it would be the very bug this guards against (a resume
checks the run's branch out again itself) — so no parallel session commits onto this run's
branch by accident, and the run never adopts a foreign one: the base a run records for a repo is
the branch it finds there the first time it touches it, and a `phase/…` branch is refused at the
record. Before every dispatch and every commit of its own into the spec repo, inside the same
hold, the driver asserts that repo is on its base — or on the phase branch, for every dispatch
within a phase that targets it, its review-funding consult included — and bails `blocked`
otherwise, naming a branch of this run's own as the run's fault rather than a parallel
session's; the plan loop keeps the same hold and the same
assertion ([plan-loop.md](plan-loop.md)). What that guards: another slice's plan-loop commits
and stamps landing on a phase branch and surfacing as out-of-scope changes in its review, and
the doc-writer writing to the close-out report from a stale checkout.

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
section whole**, earlier phases' done-record **summaries** — the `**Done (…)**` paragraph and
the `Later phases:` list ([plan-template.md](plan-template.md)), never the record's narrative
nor the phase text, which is the distractor; a record without the list rides whole and the
driver's log says so — later phases' headings and `Target:` lines, every
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
  commit+log and stated in the reviewer's dispatch so the review never re-runs the suite; the
  claim is about tests, never lint. A red gate spawns a **fresh executor fix round** (cap 3,
  then `gate_red` bails); there is no separate fixer in the phase loop. A gate kc says **ran
  nothing** (exit 3: the target defines no tests) is neither: the phase proceeds as with no
  gate, no green is recorded, and the reviewer is told the target defines no tests, so the
  state is unverified. A `gate` ruling in the plan waives the gate outright (§ After the last
  phase, operator rulings).
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
- **Merge** — worktree clean; a base that moved under the branch (a parallel session's commits
  in a shared tree) has the branch rebased onto it first, the diff proven unchanged and the
  record's head repointed — an unclean rebase or a changed diff bails `blocked` with the branch
  left as it is and the rebase handed to the operator, and the resume takes the rebased branch
  as the one it asked for (review kept, gate re-run; [runner-state.md](runner-state.md)); then
  gate green on HEAD (re-run if it moved, the rebase included, unless the move is only inside the
  spec repo's `slices/`; red cannot merge), ff-merge into the base branch, branch deleted, stamp.
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
  describes the tree that dispatch sees. A command kc says ran nothing (exit 3, no statement
  for that verb) is its own row, `nothing ran`: it neither reds the sweep nor holds the push,
  and the green stance claims only the rows that ran. A sweep in which nothing ran at all is
  unverified, not green. Rows a `gate` or `accept` ruling covers are shown as waived or
  accepted and don't count as red (below). The completion consult and the test phase both receive
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
  for this phase (a `flock` on the inode `devlock.lease` names; it releases on crash): taken
  before the session, kept across a findings re-loop while the slice converges, released once the
  phase is clean and the push check below has passed. Under that hold pushing and rolling dev for
  verification is pre-authorized — the lock *is* the coordination — and so is pushing to
  production where the project's deploy path is a push: a slice is expected to reach production.
  What is operator-gated is running a promotion pipeline — assume a project has one wherever it
  has more than one stage, unless its deploy-operations doc says the stages are separate
  environments with nothing promoted between them — except for a target a `prd` ruling names
  (below).
  Blocking findings come back as appended phases; sub-bar findings go in the close-out report;
  `verification.json` is checked off.
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
  between two instructions — and, instead of nudging and bailing, notes the Outstanding-actions
  entry the plan loop seeded for each held repo, or writes one for a hold added after planning. Before this, a plan's hold was invisible to the driver and the run had two
  exits: violate the ruling or bail. One slice held `../HelmCharts` (a push there deploys dev and
  prd together and rolls both controllers); the test agent honoured the ruling, was nudged twice,
  the driver bailed `unpushed` — and the run session pushed 38 seconds later, crash-looping prd.
- **Operator rulings bend three of the rules above.** `plan.md`'s `## Driver rulings` section
  ([plan-template.md](plan-template.md) holds the bullet grammar) is re-read at every point of
  use, so a ruling written while the run sits at a bail holds from the resume on.
  - A **`gate`** ruling waives the driver's test gate for a target, keyed per target and not per
    phase, because "this environment can't run these suites" is a fact about the repo. A phase
    it covers runs no gate and so gets no fix round. The reviewer is told the driver did not
    verify the commit and which substitute the ruling names, and the executor is told a red
    suite there is not its to fix. The target's `test` rows drop out of the sweep (its lint and
    build rows still run), and so does its test verb in the doc gate. A phase whose Target is a
    whole repo is covered by any gate ruling in that repo, because its gate can't leave one
    component out.
  - An **`accept`** ruling turns one red sweep row (target plus verb) non-blocking. It is
    rendered as accepted and drops out of the stances' red, and the doc gate honours it too. It
    never covers the per-phase gate: a gate the environment can't pass needs a `gate` ruling.
  - A **`prd`** ruling authorizes the test phase to run the promotion pipeline for that target.
    Every target it doesn't name keeps its promotion operator-gated; a push needs no ruling,
    production included.

  The sweep's red is worked out when a dispatch renders it, against the rulings as they stand
  then, so a ruling added after the sweep ran still counts. The test phase's dispatch lists the
  gate rulings with their substitutes, whose results are its evidence. The driver never runs or
  polls a substitute: it is a name the driver passes on, and a phase branch isn't pushed at gate
  time anyway. The first time a ruling takes effect, the driver writes a Notable-events entry,
  so the report says what the run left unverified. The case behind this section: one slice's
  sibling needed Postgres and MinIO, which its environment doesn't declare. The operator ruled
  "the Jenkins build is the gate", and Jenkins went green. The driver's own gate still spent its
  three fix rounds, and the fixes could only answer `blocked`. Meanwhile the test phase's "a red
  row does not leave the machine" deadlocked against that same ruling.
- **Doc phase** — after test-complete: auto docs. One `doc-writer` session told to read the
  slice-doc-plan doc (`.aiworkflowrc`'s `doc_phase.plan`) and execute it — the doc surfaces that
  already describe the changed behavior, brought up to date from the whole slice's diff, single
  pass, manual + dev docs together, on its own branch, **never pushing**. The writer surveys the
  doc tree through sub-agents it yields for, grounds and writes every page itself, reconciles
  across scopes as a named last step, gates once and commits (`agents/doc-writer.md`). The phase
  carries no slice task and owes no acceptance criterion: a doc change a requirement names is a
  phase of the plan ([plan-template.md](plan-template.md)), merged before this point like any
  other. Its dispatch carries the driver's deterministic facts, in the phase digest's spirit: the
  slice's diff **on disk**, one `<slice>/doc_phase/<repo>.diff` per repo a phase merged into, a
  section per merged phase (`git diff --stat` on top, then the diff, over the phase's landed range
  — the sha its branch was cut from to the head that fast-forwarded the base — with the spec
  repo's `slices/` tree held out; never the base branch since the slice began, which in parallel
  lanes carried the other lanes' merges and the slice's own run record, and never HEAD, which is
  the doc branch, so a redispatched writer's own commits never read as shipped work; a phase
  merged with no range on record is named in the dispatch as missing from the files), read by
  path instead of re-running `git diff`, which past the tool's output limit round-trips through a
  persisted file; the plan **digested whole** — title, rulings sections, every phase's
  done-record — so the plan is opened only where a record points and slice.md not at all; and
  the close-out verbs the phase uses beside `append` (`list`, `note`, `strike`) with their
  argument shapes, rendered from `close_out.py`'s own parser — the `--help` round trips go with
  them. The driver then runs the
  full gate sweep — `kc project lint` + `build` + `test`, fail-fast (red is nudged back to the
  writer's session; a verb that ran nothing is not red; a verb a ruling touches in this repo runs
  per component, leaving out what the rulings cover) — checks local `<base>` against
  `origin/<base>` (the branch rebases onto
  origin but ff-merges into local, so a local-ahead base bails `blocked` before anything is
  mutated), rebase-merges the branch onto the base branch and pushes; the dev
  roll that push triggers is left to land on its own, untracked. **The doc branch exists in the
  primary repo only**: a doc edit in another repo the slice touched is committed on that repo's
  checked-out base branch, and once the primary has landed, the driver pushes each such repo
  whose base is ahead of its origin (its own `siblings` stage, so a resume after the landing
  pushes only these). A held repo is reported, not pushed; a base that has diverged from its
  origin bails `blocked` rather than being rebased. **The devlock is taken again here, for the
  pushes alone** — before the fetch, so nothing another driver pushes lands between the rebase
  target and the push, and let go once the last push is out. The writer's session and the
  gate sweep, the slow part of the phase, run outside it: after test-complete the slice's dev
  occupancy is over, and another slice's verification proceeds while this one's docs are written.
  With a test phase, this landing is the only place the driver pushes the primary repo, so it
  is where a hold on the *primary* repo lands: the branch rebases onto the local base instead
  (a held repo's origin is behind by everything the slice did, which is what the local-ahead
  check exists to catch) and the landing stops at the merge.
- **Wrap-up** — after the doc-writer's session and before the gate sweep, so that one landing
  carries both. One `dev:wrap-up` session works on what the close-out report's table gave the
  wrap-up ([close-out.md](close-out.md#the-wrap-up)): `close_out.py worklist` names it, and
  when it names nothing the stage is skipped. It has no switch, and a project that runs no doc
  phase still runs it: the ladder then starts here, after the test phase, and the gate and the
  landing below are the wrap-up's alone. **Its commits sit on a branch of their own**,
  `phase/<NNN>-wrap-up`, in every code repo the slice touched and the plan does not hold — in
  the primary repo cut from the doc branch, elsewhere from the base branch. In the spec repo it
  commits as every agent does, on the branch checked out there: the store, a fold into another
  slice, and prose of the spec repo where a phase targeted it. Its dispatch carries the report
  and the tool, and per repository the path, the branch and the gate it runs on its own fixes.
  When the session has ended the driver gates what it committed — the primary repo in the doc
  phase's sweep, run on the wrap-up branch; every other repo it committed to with the gate a
  phase in that repo gets. Green, the doc branch moves up to the wrap-up branch and the landing
  carries both; the other repos' branches are fast-forwarded into their base and pushed with
  the doc phase's siblings. The driver renders the report when the stage is over.

  **The wrap-up is never a reason to stop a run.** A timeout — whatever the session had
  written by then — a missing or invalid verdict, a `blocked`, changes it left uncommitted, a
  commit it made outside its branches, a gate that is red with its commits, or any error the
  driver itself meets in the stage is a *soft failure*: all of its commits are left out, in
  every code repo, the repos whose gate was green included — the branches stay, unmerged, for
  whoever wants to read them — the store goes back to what it was before the dispatch, the
  failure is entered in the report as an event that names the branches, and the run goes on
  with the doc phase's own gate and landing. What it committed in the spec repo beside the
  store — a fold, prose — stays where it is: that tree has no branch of the wrap-up's to leave
  behind. What the table gave the wrap-up then still waits, and the close-out session
  dispatches it. A repo it would branch that holds uncommitted work is a soft failure before
  anything is dispatched. A gate in the primary repo that is red with its commits is run once
  more without them: red there too, it is the doc phase's red and goes to the doc-writer as
  before — and in a project that runs no doc phase, which would have completed over that red
  without a wrap-up, the run completes. An account session limit is waited out and the session
  redispatched, as for every role; an interrupt is an interrupt, and the resume starts the
  stage again from a clean slate. The session leaves its `history` row whatever its outcome,
  which is what `slice_cost.py` prices the role from.

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
loop did not act on is in the slice's close-out report — who writes what there is
[close-out.md](close-out.md). The driver's own part is deterministic: it creates the report at
run start when planning left none, names the report and `close_out.py` (the only way to write to
it) in every dispatch, with `append`'s arguments, enters refuted findings, funding-consult
merges and every stop of the run (written by the resume that follows the stop, from
`state.json`'s `bailouts`, at that resume's first dispatch — once the spec tree is on the branch
the dispatch works on, so that in a phase targeting the spec repo the entry rides the phase
branch; written at startup it sat uncommitted on the base and refused the checkout of a branch
whose own `close-out.json` had moved, on every resume), dispatches the wrap-up, and renders the report — before the doc
phase, after the wrap-up, whenever the run stops, and when it completes, the run header from
`state.json` with it; the launching session
renders once more when the cost block has landed and files **one** tracker card pointing at the
report.

## Protocol invariants

Every spawned agent ends by writing the verdict JSON named in its dispatch and leaves the
worktree committed. A miss gets one resume-nudge each — the verdict nudge for a missing verdict,
the commit nudge for a dirty tree — and a verdict on disk after either counts: a session that
ended without one routinely writes it while committing on the commit nudge (slice 198 P6
committed its code, its done-record and a valid verdict there; the driver's earlier `blocked`
ruling stood, bailed the run, and `--resume` spent a fresh executor round on finished work).
Only after both nudges does a missing verdict count `blocked`, and a tree still dirty bails. A
nudge whose answer is the harness's synthetic no-op — no response, or "No response requested." —
never reached the model: the session's last turn ended with a background task whose completion
had landed mid-turn, and the first resume after that is the harness's stopped-task bookkeeping
([agent-dispatch.md](agent-dispatch.md) § Nested delegation). What the driver does with that
no-op depends on which nudge got it. The commit, push and doc-gate nudges are sent once more:
the session's work was done and only the nudge was lost. The verdict nudge is not — a session
that ended without its verdict *and* answers with the no-op was cut mid-wait, and the report it
was waiting on is gone, so "do not start new work" would leave it no legal move but `blocked`
(slice 209's doc-writer lost the fourth of four surveys, twice). The driver resumes it with the
recovery prompt instead: the report was lost, its transcript is saved, recover it — the
sub-agent resumed for its report, a command's output file, the tree for what already landed —
re-dispatch only what cannot be recovered, then finish and write the verdict. That resume runs
under the role's own timeout, not the nudge's, and is the same round — its number kept, its
duration added to the row — at most twice per round (the doc-writer yields twice); past that
the verdict nudge falls back to the same-prompt retry. A session killed by the account's
session-limit window is not an agent outcome: the driver waits out the stated reset and
redispatches the same round — nothing counted. The driver asserts its agent definitions resolve
before dispatching anything (`kc session create-headless --agent` does
not validate names).

**The loop runs only under the plugin version its agents load.** A loop keeps the version it was
launched from, while every session it spawns loads the installed plugin
(`~/.claude/plugins/installed_plugins.json`); a 0.9.43 plan loop drove a 0.9.47 plan-writer,
whose `owed_after` it ignored without a word (AIWF-16). So both loops compare their own
manifest's version with the installed one at startup and before every dispatch, and bail
`plugin_version` (exit 3) on a difference, naming the installed copy's `tools/` path to relaunch
from — the run loop with `--resume`, the plan loop by a plain rerun. A missing file or entry
passes: the check never holds a loop up on its own bookkeeping. The same points reject a
`verification.json` item key outside [plan-template.md](plan-template.md)'s schema as
`protocol_failure` — the second guard, for a newer agent's field the driver would otherwise drop.

**The loop does not start over an open pre-run action.** At startup, fresh or `--resume`, before
any dispatch, the run loop reads the slice's own close-out report and bails `prerun_action`
(exit 4) on any live action whose headline begins `Before /dev:run-slice`
([close-out.md](close-out.md) § Who writes what, when). Slice 027's first executor was dispatched
while its A1 — push two toolchain commits, restart the pod — was still open, failed its first
`cexec` and handed back `blocked`. The after-run actions the plan loop seeds (a held push, a
criterion owed after it) do not stop a run; they are what the run leaves behind. `--dry-run` lists
the open entries without failing.

**The loop does not start without the tool containers its Targets' manifests call.** At
startup, fresh or `--resume`, once the plan's Targets resolve and before any dispatch, the run
loop scans each Target repo's `.kubecoder/project.yaml` for `cexec <tool>` calls — a text scan,
never a parse of the manifest, and a call guarded by `! cexec … ||` or `if cexec …` does not
count — and holds them against the tool containers the environment runs (`kc env describe`). A
tool missing bails `missing_tools` (exit 4), naming each tool, the manifest that calls it and the
`- use: <tool>` line to add under `tools:` in the host's `.kubecoder/config.yaml` — or, where that
line is already there, that the pod predates it and `kc env restart` applies it. The run-slice
session can fix neither (the restart ends it), so the bail is the operator's. A repo whose gate
the plan's `## Driver rulings` waive for every verb the loop-tail sweep runs — `gate` for test,
`accept` for lint and build, on every component — is not held to it. The plan loop runs the same
check at GO ([plan-loop.md](plan-loop.md)), `--dry-run` lists it as a problem, and a run that
meets `cexec: tool "X" is not available` mid-run anyway — a component a phase registered, an
environment that changed — reads it the same way: a sweep row or a doc-gate verb is `unrunnable`,
not red, like a row that ran nothing; a phase gate bails `missing_tools` instead of spending fix
rounds against a tool that is not there. FieldnotesApp slice 001's P6 ran in an environment
without `aac-tools`: `kc project test` failed at `cexec aac-tools gen-architecture` after ten
minutes of writer work and handed back `blocked`, and the fix ended the session that would have
resumed it; Ansible slice 033 bailed at the sweep on KubeCoder's lint and build rows for the
same reason and needed `accept` rulings to get past them.

**The loop sets up its Target repos before the first dispatch.** At startup, fresh or `--resume`,
right after the tool check, the run loop runs a bare `kc project setup` once from the root of each
repo the tool check holds — every pending phase's Target repo and the code repos the run has
touched, each once, those with a `.kubecoder/project.yaml` only — with the output in the slice's
`setup/<repo>.log` and a `[setup]` line per repo in `log.txt`. A repo that defines no setup (exit 3)
passes. A red setup, or one still running after 900 s, is a warning and the run goes on: the gate
decides, and meets what setup could not fix exactly as it would have without the step. A gate that
fails on install state rather than on the change sends an executor into fix rounds on code that is
fine: Architecture slice 034's P11 met `No module named 'click'` in a sibling Target never set up,
KubeCoder slice 238's P1 `No module named 'croniter'` in a venv behind its lockfile, and `kc project
setup` fixed both in about a minute. `--dry-run` runs no setup.
