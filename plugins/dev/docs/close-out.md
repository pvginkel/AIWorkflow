# The close-out report — one document per slice for everything out of the loops' scope

`<slice>/close-out.md` is where every plan and run agent puts what it notices but the loops
will not act on: a bug it will not fix, a keystroke only the operator can make, an event that
deviated from an uneventful run, a question the run did not need answered to proceed, an idea.
One document, one fixed shape ([close-out-template.md](close-out-template.md)), written as it
happens; the operator reads it when the slice is done and writes a disposition under each entry;
the `close-out` skill executes the dispositions; what remains is `/dev:triage`'s input. Nothing
from a run is carded per finding — the loops' only tracker output is one card per slice pointing
at the report. `${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` creates the file, appends the driver's
own entries, stamps the run header, and counts entries; both loops import it.

## What it is — and is not

**Only for what is out of scope of the plan and run loops' own action.** Anything in scope
already has a home: the plan (phases, rulings, done-records), `verification.json`, the review
files, a `question` verdict that pauses the loop. The report is not a thinking scratchpad, not a
substitute for asking the operator when the run needs an answer (a `question` verdict pauses; a
report entry never does), and not a place to restate the plan. It is the release valve for
everything an agent would otherwise have to decide what to do with — the destination is fixed
(put it in the report), the shape is fixed (the entry), and the operator routes.

The sections, in the template's order — Summary, Outstanding actions, Notable events, Bugs, Open
questions and rulings, Suggestions — each carry their own charter as a comment in the file; every
section may be empty, and empty is the normal state of most. Two things the comments do not
spell out: **Notable events** takes product *and* workflow deviations — bail-outs and what
resolved them, appended phases and why, blocked proofs and their re-routing, defects a live run
exposed that the suite hid, refuted findings, funding-consult merges, a session that hit
something odd — so plugin defects surface there instead of living only in `log.txt`; and
**Suggestions** is where a fix idea may go — the reviewer's "describe the problem, never the fix"
governs review files, not this section.

## Reading aids

The report is written for the operator. Prose is not limited; it is made easy to read: a
**Focus** line at the head of every entry section (one or two lines: what to look at first,
why), an id on every entry so a disposition can name it in one line ("card B1, close B6, fold S1
into 009"), the run's shape stamped at the top, and a blank `Disposition:` line under every
entry.

## Who writes what, when

Both loops create the file from the template if it does not exist — the plan loop first, so
planning can already write to it — and commit it. All agents may append; the file is committed
live with each agent's own commit (staged by name, like every other slice-folder artifact).

- **plan-writer / plan-reviewer** — out-of-scope observations about the spec or the estate;
  events during planning. Their in-scope findings and questions keep their existing routes (the
  review file, the `questions` verdict, the interactive session).
- **code-writer** — anything out of the phase's scope it noticed; notable events in its session.
- **code-reviewer** — its advisory findings, as Bug or Suggestion entries, in the report's shape;
  the review file keeps the full finding and stays the evidence trail.
- **consults** — sub-bar findings. The **completion consult is the only agent that reconciles**:
  it may strike an entry it absorbed into an appended phase (the struck headline names the phase
  and commit), merge duplicates it is sure of, and mark what a later phase resolved.
- **test-agent** — below-bar findings; live-check events.
- **doc-writer** — doc debt; and, **as its last act before a `done` verdict, the Summary and
  every `Focus:` line** — it has the whole shipped diff in view. If the run ends before the doc
  phase, or the doc phase reports `blocked`/`question`, the operator reads the report raw.
- **the driver** — deterministic entries only, through `close_out.py`: a refuted finding and a
  funding-consult merge each become a Notable event; the run header is stamped from
  `state.json` when the run completes (run window, phases planned/appended, bail-outs, test
  rounds, doc phase outcome) and re-stamped by `/dev:run-slice` once `slice_cost.py
  --write-state` has added the `cost` block — the stamp is idempotent.

**Reading the report is never a license to act on it.** Phase agents append only — otherwise
the report becomes a new source of scope bleed, a writer "fixing while here" what an earlier
phase reported. Reconcile is the completion consult's; stamp is the driver's; dispose is the
operator's.

## Entry rules

- **Write for a reader who has only this document.** The operator must be able to make sense of
  an entry — at least at a high level — without chasing anything down. Quote liberally: the
  sentence that is wrong, the command and its output, the file and lines. Provenance ids
  (`P3 r1 F3`, `V10`) belong on the `Provenance:` line, not in the body as load-bearing
  references.
- **No limit on prose, no limit on count.** Long sections are fine; a cap produces more, not
  less.
- **In doubt, add it.** Nobody pre-dedups: every agent reads the same file before it writes, the
  completion consult merges duplicates it is sure of, the operator merges the rest by reading.
- **Severity vocabulary** for Bugs: `major` (a wrong result or a broken flow, unfixed) · `minor`
  (a real defect with a contained consequence) · `nit` (true, no practical consequence today) ·
  `cosmetic` (no behavioural or informational consequence — a stale line pointer). The
  reviewer's own Blocker/Major/Minor never reaches the report: a Blocker gets fixed.
- **`Disposition:` is the operator's line.** Free form; a suggested vocabulary is `card [board]`
  · `fix now` · `fold into <slice>` · `close` · `defer`. Agents leave it blank; the session that
  executes it may rewrite the entry's fate (struck, moved) but never the operator's words.

## Lifecycle

1. The plan loop creates `close-out.md` at its first dispatch; planning agents append.
2. The run loop creates it if planning did not (a slice planned before this report existed),
   appends throughout; the completion consult reconciles; the doc-writer writes Summary and Focus
   lines; the driver stamps the header when the run completes, and `/dev:run-slice` re-stamps
   it after the cost block lands (`close_out.py stamp`).
3. `/dev:run-slice` files **one** tracker card — `[NNN] close-out: <slice title>`, in the intake
   queue — whose body is the report's Summary, its `Focus:` lines, its entry counts, and its
   path. That card is the "a report is waiting" marker, never an ask (`/dev:triage` reads the
   report it names, not the card); nothing else from the run is carded.
4. The operator reads the report and writes dispositions in place. The `close-out` skill (or an
   ad hoc session following it) executes them: `card` files a tracker card with the entry as its
   body, `fix now` does the small thing or bails to a slice, `fold into` appends the entry to
   that slice's `slice.md`, `close` strikes, `defer` leaves it. Git in the spec repo holds the
   history of the operator's remarks; the close-out card is archived when no blank
   `Disposition:` remains.
5. What remains — `defer`, or no disposition yet — is a `/dev:triage` source, one item per entry.

Deliberately absent: any validation beyond "the section heading exists", dedup tooling,
disposition parsing, and — for now — an automated triage pass over the report; the shape is
meant not to change when that comes.
