# The run loop — the Markdown plan is the queue, the driver is its bookkeeper

`${CLAUDE_PLUGIN_ROOT}/tools/run_loop.py` drives a slice end to end from one operator-legible
phased plan (`<slice>/plan.md`). It owns the whole flow — every phase's dev round, the completion
consult, the test phase, the doc phase — and bails only on **errors** (exit 3) and **operator
questions** (exit 4); the `/dev:run-slice` session that launches it has exactly four jobs and never
drives. What the loop records is [runner-state.md](runner-state.md); session mechanics and models
are [agent-dispatch.md](agent-dispatch.md); the plan's authoring is [plan-loop.md](plan-loop.md).

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
component; `kc project test` from the sibling's own root when it carries a manifest; no
deterministic gate otherwise (the reviewer is told the state is unverified).

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

Fresh **code-writer** session per phase (prompt: *"Execute P\<n\> of \<plan path\>"* plus the
standing contract — it reads the whole plan, works its phase against the live repo, runs the gate
itself, appends the done-record, commits on the phase branch `phase/<slice>-P<id>`). Then:

- **Fetch** — before the session, the driver fetches the target repo's `origin` (and every repo
  the run has touched before the test phase). Nothing else in a run fetches: the driver branches
  off the **local** base and ff-merges back into it, so a repo cloned days ago keeps the
  `origin/<base>` that came with the clone, and an agent reading that ref reads the day of the
  clone — one run's executor called a sibling-repo commit that had been on `origin/main` for a
  day "absent from origin" and raised a Blocker over it. Refs only: no local branch moves, so a base
  sitting behind its origin stays the operator's call. Agents carry the other half of the rule —
  never conclude a commit is missing from a tree you have not fetched yourself.
- **Gate** — the driver runs the target's deterministic gate itself; green is recorded
  commit+log and stated in the reviewer's dispatch so the review never re-runs the suite. A red
  gate spawns a **fresh executor fix round** (cap 3, then `gate_red` bails); there is no
  separate fixer in the phase loop.
- **Review** — fresh **code-reviewer** per round against the phase's outcome, the acceptance
  criteria (`verification.json`) and repo conventions. Round 1 full branch diff; rounds 2+ are
  delta-scoped to the fix range. A `blocking` tag needs an anchor from the closed list in the
  reviewer's contract (no anchor is advisory by construction), and the verdict reports every
  finding machine-readably — severity, impact, category, anchor — which the driver persists
  into `state.json`'s history. A fix round resolves the findings tagged **blocking** and
  nothing else — advisory findings are carded at close-out (the residue rider mops up the
  mechanical ones), never fixed mid-loop, so each re-review stays the size of the blocking
  fixes rather than everything the writer chose to touch. Fix rounds are **failure-first**:
  a finding with an executable anchor is witnessed — the failing test written, the claimed
  repro run — before any code changes. Witnessed, the test rides the fix as its regression
  test; unable to fail, the finding is **refuted** — no code change, carded with the
  refutation evidence, the record appended to the round's review file, never relitigated. A
  fix round that changes no code and refutes every blocking finding settles the review; no
  further round is spawned. Round 1's fix is automatic; from
  round 2 on (and on any `critical`) a fresh consult judges the findings against a **funding
  bar that rises per round** — blocking-only, then Blocker-only, then critical-only; a
  prose-only fix range applies the next step early — before an executor round is spent.
  Backstop cap 5. Findings that merge unresolved are carded, never lost.
- **Merge** — worktree clean, gate green on HEAD (re-run if it moved; red cannot merge),
  ff-merge into the base branch, branch deleted, stamp.
- Executor terminals: `question` pauses the run for the operator (exit 4 — the answer lands in
  the plan's rulings section and the run resumes); `blocked` is an error bail.

## After the last phase

- **The loop-tail gate sweep** — before any loop-tail dispatch, the driver itself runs
  `kc project lint` + `build` + `test`, per component so every red is visible, across every repo
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
  doc (resolved through `CLAUDE.md`'s `Slice testing strategy:` pointer) and execute it. **The
  driver holds the devlock** across the test and doc phases (a `flock` on the spec repo's lease
  inode; it releases on crash); under that hold pushing and rolling dev for verification is
  pre-authorized — the lock *is* the coordination. prd stays operator-gated. Blocking findings
  come back as appended phases; sub-bar findings as cards; `verification.json` is checked off.
- **The push check** — nothing in the driver pushes a code phase (`_run_phase` ff-merges into the
  base branch locally, primary repo and siblings alike), so pushing what the slice committed is
  the test phase's job. Before the doc phase the driver verifies it happened: for every repo in
  `state.json`'s `bases` — the run's own record of what the slice touched, the spec repo excluded
  — it fetches and compares `origin/<base>..<base>`. A repo left behind nudges the test agent's
  session (cap 2), then bails `unpushed`. The driver **checks rather than pushes**: a multi-repo
  slice may need an order only the agent running the verification knows. A reviewed-but-unpushed
  sibling commit otherwise never reaches the deploy it was meant for — one run's dev roll
  crash-looped exactly that way, its sibling's half of the change still local.
- **Doc phase** — after test-complete: one `doc-writer` session told to read the slice-doc-plan
  doc (`CLAUDE.md`'s `Slice doc plan:` pointer) and execute it — diff-based over the whole
  slice, single pass, manual + dev docs together, on its own branch, **never pushing**. The
  driver then runs the full gate sweep — `kc project lint` + `build` + `test`, fail-fast (red
  is nudged back to the writer's session) — rebase-merges the branch onto the base branch and
  pushes; the dev roll that push triggers is left to land on its own, untracked.

**The generation bar** terminates the append loop: the first follow-up generation absorbs small
in-scope touch-ups (absorbed beats carded), the second appends blocking work only, a third
pending generation bails to the operator. Advisory leftovers become cards at close-out — recorded
in `state.json` as findings land, so the card list is a mechanical read, not a memory. One rider
holds at every generation: mechanical residue — comment or formatting fixes with no behaviour
change, in files the slice's diff already touched — is neither carded nor appended; the finder
fixes it in place and commits, and the driver's full-sweep gate covers it. A card must never
cost the operator more to triage than the fix costs to make.

## Protocol invariants

Every spawned agent ends by writing the verdict JSON named in its dispatch and leaves the
worktree committed; one resume-nudge covers a miss, then a missing verdict counts `blocked` and
an uncommitted tree bails. A session killed by the account's session-limit window is not an
agent outcome: the driver waits out the stated reset and redispatches the same round — nothing
counted. The driver asserts its agent definitions resolve before dispatching anything
(`kc session create-headless --agent` does not validate names).
