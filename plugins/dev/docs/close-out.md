# The close-out report — one document per slice for everything out of the loops' scope

`<slice>/close-out.md` is where every plan and run agent puts what it notices but the loops
will not act on: a bug it will not fix, a keystroke only the operator can make, an event that
deviated from an uneventful run, a question the run did not need answered to proceed, an idea.
One document, one fixed shape ([close-out-template.md](close-out-template.md)), written as it
happens; the operator reads it when the slice is done and writes a disposition under each entry;
the `close-out` skill executes the dispositions; what remains is `/dev:triage`'s input. Nothing
from a run is carded per finding — the loops' only tracker output is one card per slice pointing
at the report. `${CLAUDE_PLUGIN_ROOT}/tools/close_out.py` creates the file and is the one pen
that writes to it — every author's entries (`append`), notes (`note`) and strikes (`strike`) —
lists it for triage, renders it into reading order, stamps the run header, and counts entries;
both loops import it, and every dispatch names it beside the report's path — which the tool takes
as its positional, the slice directory or the report itself, so the first call works; the
doc-writer's dispatch also carries the verbs it uses with their argument shapes, rendered from
the tool's own parser (`close_out.verb_usage`), so no `--help` turn is spent. The shape is
mechanical, the content is judgment: no agent edits the file by hand — the `Disposition:` line,
the operator's, is the one thing written into it in words rather than through the tool.

## What it is — and is not

**Only for what is out of scope of the plan and run loops' own action.** Anything in scope
already has a home: the plan (phases, rulings, done-records), `verification.json`, the review
files, a `question` verdict that pauses the loop. The report is not a thinking scratchpad, not a
substitute for asking the operator when the run needs an answer (a `question` verdict pauses; a
report entry never does), and not a place to restate the plan. It is the release valve for
everything an agent would otherwise have to decide what to do with — the destination is fixed
(put it in the report), the shape is fixed (the entry), and the operator routes.

The sections, in the template's order — Summary, Outstanding actions, Notable events, Bugs, Open
questions and rulings, Suggestions — each carry their own charter as a comment in the file, and
the file's head comment names the tool that writes entries and the three labels (the shape itself
is [the template's](close-out-template.md#the-entry)); every section may be empty, and empty is
the normal state of most. Two things the comments do not spell out: **Notable events** takes
workflow deviations as much as product ones (its charter names both kinds — a bail-out, an
appended phase, a blocked proof re-routed, a tool missing from the sidecar, a wait that hit a
cap) so plugin defects surface there instead of living only in `log.txt`; and **Suggestions** is
where a fix idea may go — the reviewer's "describe the problem, never the fix" governs review
files, not this section.

## Reading aids

The report is written for the operator. Prose is not limited; it is made easy to read: a
**Focus** line at the head of every entry section (one or two lines: what to look at first,
why), an id on every entry so a disposition can name it in one line ("card B1, close B6, fold S1
into 009"), the run's shape stamped at the top, and three **bold labels** closing every entry in
one order — `**Consequence:**`, `**Provenance:**`, a blank `**Disposition:**` — so a reader
scanning a long report finds, under each heading, what it costs, where it came from, and where to
write. The Consequence line is the one the operator triages on; it is what makes a dense entry
decidable without reading its body. And the report is read in **rendered order**
([the template](close-out-template.md#the-rendered-order)): live entries first — Bugs by
severity — and struck entries last, folded, so what still needs a decision leads and what was
settled in-run stays on record without being read past. `close_out.py list` is the same view
without the bodies: ids, headlines, Consequence lines.

## Who writes what, when

Both loops create the file from the template if it does not exist — the plan loop first, so
planning can already write to it — and commit it. All agents may append, through
`close_out.py append` (its path is in every dispatch; `list` first shows what is already
there); the file is committed live with each agent's own commit (staged by name, like every
other slice-folder artifact).

- **plan-writer / plan-reviewer** — out-of-scope observations about the spec or the estate;
  events during planning. Their in-scope findings and questions keep their existing routes (the
  review file, the `questions` verdict, the interactive session).
- **code-writer** — anything out of the phase's scope it noticed; notable events in its session.
- **code-reviewer** — its advisory findings, as Bug or Suggestion entries, in the report's shape;
  the review file keeps the full finding and stays the evidence trail.
- **consults** — sub-bar findings. The **completion consult is the only agent that reconciles**,
  and only through `close_out.py strike` and `note`: it strikes an entry it absorbed into an
  appended phase (the reason names the phase and commit), duplicates it is sure of, and what a
  later phase resolved (the reason names the commit and what was re-run); anything else it has
  to say about an entry is a `note`. It edits nobody's text.
- **test-agent** — below-bar findings; live-check events.
- **doc-writer** — doc debt; and, **as its last act before a `done` verdict, the Summary and
  every `Focus:` line** — it has the whole shipped diff in view. A Focus line ranks on the
  entries' Consequence lines and evidence class (witnessed before read), never on their length,
  and says how many are witnessed. If the run ends before the doc
  phase, or the doc phase reports `blocked`/`question`, the operator reads the report raw.
- **the driver** — deterministic entries only: a refuted finding and a funding-consult merge
  each become a Notable event; the report is **rendered** (`close_out.py render` — live first,
  Bugs by severity, struck folded last; idempotent) immediately before the doc phase is
  dispatched, so the doc-writer's Focus lines are written over the order the operator will
  read, and again when the run completes, before the run header is stamped from `state.json`
  (run window, phases planned/appended, bail-outs, test rounds, doc phase outcome); the header
  is re-stamped by `/dev:run-slice` once `slice_cost.py --write-state` has added the `cost`
  block — the stamp is idempotent.

**Reading the report is never a license to act on it.** Phase agents append only — otherwise
the report becomes a new source of scope bleed, a writer "fixing while here" what an earlier
phase reported. Reconcile is the completion consult's; render and stamp are the driver's;
dispose is the operator's.

## Entry rules

- **Write for a reader who has only this document.** The operator must be able to make sense of
  an entry — at least at a high level — without chasing anything down. Quote liberally: the
  sentence that is wrong, the command and its output, the file and lines. Provenance ids
  (`P3 r1 F3`, `V10`) belong on the `Provenance:` line, not in the body as load-bearing
  references.
- **`Consequence:` is a line of its own, written for triage.** What an operator or user actually
  experiences if the entry stays as it is — unfixed, undone, unanswered — in the deployed shape,
  in plain words, with what has to happen for it to be reached; or `none`, said plainly. It is the
  stated consequence `/dev:triage` rules on, and the operator reads it the same way, so it is not
  "better than before", not "none to behaviour" when a human would notice something, and not a
  restatement of the mechanism the body already gave. A body that leaves the reader asking "what
  is the risk in a real environment?" has an entry without a consequence, however long it is.
- **Every claim carries its evidence class.** `**Provenance:**` opens with `witnessed` (the author
  ran, measured, reproduced or mutated it — the command, the output, the probe are in the body)
  or `read` (inferred from reading code or text). The body leads with the symptom and states a
  cause only where it was shown: symptom claims hold up, cause attributions are the half that does
  not, and a reader deciding what to trust needs the class before the body. The same holds for
  a strike — resolved, refuted, does-not-reproduce names the commit and what was re-run.
- **No limit on prose, no limit on count.** Long sections are fine; a cap produces more, not
  less.
- **One entry per thing, not per turn.** A later observation about an entry that already exists —
  its premise moved, its symptom was re-tested, a phase resolved it, a reviewer refuted it — is
  `close_out.py note <id>`: a dated paragraph at the end of that entry's body, never a new entry.
  The reader who decides on B1 finds everything about B1 under B1, and only the completion
  consult strikes.
- **In doubt, add it.** Nobody pre-dedups: every agent runs `list` before it writes, the
  completion consult strikes duplicates it is sure of, the operator merges the rest by reading.
- **Severity vocabulary** for Bugs: `major` (a wrong result or a broken flow, unfixed) · `minor`
  (a real defect with a contained consequence) · `nit` (true, no practical consequence today) ·
  `cosmetic` (no behavioural or informational consequence — a stale line pointer). The
  reviewer's own Blocker/Major/Minor never reaches the report: a Blocker gets fixed.
- **`Disposition:` is the operator's line.** Free form; a suggested vocabulary is `card [board]`
  · `fix now` · `fold into <slice>` · `close` · `defer`. Agents leave it blank; the session that
  executes it may rewrite the entry's fate (struck, moved) and records what it did after the
  operator's words on the same line — a card id, a commit, the slice folded into — but never
  edits those words. A struck entry needs no disposition: its fate is the reason on its heading.

## Lifecycle

1. The plan loop creates `close-out.md` at its first dispatch; planning agents append.
2. The run loop creates it if planning did not (a slice planned before this report existed),
   appends throughout; the completion consult reconciles; the driver renders; the doc-writer
   writes Summary and Focus lines; the driver renders again and stamps the header when the run
   completes, and `/dev:run-slice` re-stamps it after the cost block lands (`close_out.py
   stamp`).
3. `/dev:run-slice` files **one** tracker card — `[NNN] close-out: <slice title>`, in the intake
   queue — whose body is the report's Summary, its `Focus:` lines, its entry counts, and its
   path. That card is the "a report is waiting" marker, never an ask (`/dev:triage` reads the
   report it names, not the card); nothing else from the run is carded.
4. The operator reads the report and writes dispositions in place. The `close-out` skill (or an
   ad hoc session following it) executes them: `card` files a tracker card with the entry as its
   body, `fix now` does the small thing or bails to a slice, `fold into` appends the entry to
   that slice's `slice.md`, `close` strikes (`close_out.py strike`), `defer` leaves it — then
   renders. Git in the spec repo holds the history of the operator's remarks; the close-out card
   is archived when no live entry has a blank `Disposition:`.
5. What remains — `defer`, or no disposition yet — is a `/dev:triage` source, one item per entry.

Deliberately absent: any validation beyond "the section heading exists" and the smoke counts —
`close_out.py counts` says how many `###` headings in the entry sections are not in the entry
shape and how many live entries lack a `Consequence:` or `Provenance:` line, so an author that
drifted from the shape shows in the run's completion line and the close-out card instead of as a
report that counts zero — dedup tooling (`render` orders, it never merges), disposition parsing,
and — for now — an automated triage pass over the report; the shape is meant not to change when
that comes.
