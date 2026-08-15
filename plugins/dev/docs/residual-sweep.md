# The residual sweep — Solution Known cards to a run-ready slice

Slice runs shed residuals: small advisory findings the generation bar routes to the close-out
report instead of fixing mid-run (consult trivia, doc drift, test hygiene), which the operator
then cards at disposition. Most are real work but far too small to justify a planning session
each — yet fixing them ad hoc would lose every gate the workflow exists to provide. The sweep is
the lane between: `/dev:triage` marks qualifying cards **Solution Known** by writing their
acceptance criteria onto the card, and `${CLAUDE_PLUGIN_ROOT}/tools/sweep_slice.py` batches them
into a mechanically generated slice that skips `/dev:plan-slice` and executes through the
ordinary run loop, gates intact.

## The mark, and the litmus

**Solution Known** means a senior dev could take the card, as written, and deliver quality work
with no preparation: **what to change** is fully decided — no choice with consequences left to
the implementer — and **the impact** is plain from the card — what the change touches and what
breaks if it goes wrong. Moderate size is fine; an open decision is not. Operationally: the
card's acceptance criteria can be written from its text alone — outcome-level, no code opened.
Triage grounds nothing itself — its only code reads are dispatched fact-checks that settle a
category label, never acceptance criteria — and this litmus is what makes the lane safe anyway:
the cards that qualify are close-out entries the run loop's own agents wrote, which already did
the grounding (file:line, expected behaviour, the review's advisory marker), carded verbatim at
the operator's disposition. If the criteria would need research, the card goes the normal
triage → plan route.

Categorically excluded regardless of how known the fix looks: concurrency or timing behaviour,
storage-layout or wire-contract changes, any card that leaves something open ("investigate",
"decide", "confirm"), and any fix that **adds behaviour** — a new code path, process, or piece
of state — rather than correcting what exists in place. Added behaviour carries design surface —
failure policy, bounds, collisions with documented rulings — that a card cannot prove is
settled, however completely it argues its diagnosis. The calibration case was a root-caused
resource-leak bug with a measured, empirically verified fix mechanism — yet implementing it
meant composing an argv no card sentence had decided, bounding a daemon-owned child against a
documented ruling, and picking a failure policy — three design calls, each with teeth.
Mechanism-verified is not change-decided; when in doubt, the normal route.

The criteria are appended to the card description under an `## Acceptance criteria` heading —
that section is the card's only mark, persisting across triage sessions until a sweep archives
the card; the Solution Known set is confirmed with the operator like every other sort outcome.

## The generator

`sweep_slice.py` (docstring holds the payload schema) is filesystem + git only — the triage
session keeps the tracker half. From a payload of one item per card (title, target, verbatim card
body, criteria) it allocates a slice number, writes `slices/NNN_<slug>/` with `slice.md` (the
record: every card quoted), `plan.md` (one phase per item, card bodies blockquoted — which is
also what neutralises stray `###`/`Target:` lines for the parser), and `verification.json` (one
item per criterion), validates with `run_loop.py run <dir> --dry-run`, appends the spec README's
**Pending** line, and stages by name — never a commit, never `git add -A` in the shared tree. It
refuses fewer than five distinct cards without `--force` (a sweep amortises the run's fixed
consult/test/doc overhead; small sets accumulate) and refuses a spec repo that is off `main` (a
parallel run may hold the shared tree on its phase branch).

## Why the run loop needs no changes

The driver executes whatever drivable phase queue `plan.md` contains — it checks no provenance
and never reads `slice.md` — so a generated plan is a first-class citizen; `--dry-run` is the
acceptance gate. A mislabelled card has a safety net without new machinery: per-phase review
still runs, and a writer that finds concurrency, storage, or contract work under a
"known" fix bails with a question — the plan's standing ruling says so — pausing the run instead
of shipping unreviewed risk. Consult, test phase, and doc phase run as for any slice. Two
designs were considered and rejected on exactly this ground — a review-free per-card fixer and a
triage-and-fix-inline session both trade the gates for speed; don't re-propose them.

## Card lifecycle

Criteria onto the card at triage → swept cards archived with a comment naming the slice folder
when the slice files → one triaged slice card `[NNN] Residual sweep` → `/dev:run-slice`, launched by the
operator like any other slice, closes out through the normal `close_slice.py` path.
