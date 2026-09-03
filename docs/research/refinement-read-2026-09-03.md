# The refinement doc, read on its first five slices (2026-09-03)

The pre-registered read of dev 0.9.19's replacement for the plan-slice dialogs
(`plan-interview-2026-09-01.md` § 7; `docs/rationale/plan-refinement.md`): the first slices
planned on it, checked for dialogs, for the operator's own messages, and for whether the doc
reads cold. Five slices were planned on 2026-09-02/03, all KubeCoder, all with the skill loaded
from the plugin's 0.9.20 cache.

## Corpus

| slice | doc | words | code / prose lines | opener words | decisions | operator's reply |
|---|---|---|---|---|---|---|
| 198 claude shim | 32.6 KB | 4 313 | 210 / 289 | 2 626 | 3 | "Accept all as-is. This I feel is a very technical slice and I trust you get this right." — 7 min after the walkthrough |
| 199 north-surface residuals | 33.5 KB | 4 531 | 259 / 237 | 2 054 | 2 | "I added one comment. The rest is agreed." — next morning; then "we're removing the explorer.exe prefix, right?", a design change of the operator's own the doc had not offered |
| 200 worker boot restore | 29.3 KB | 3 943 | 146 / 282 | 2 455 | 2 | "Everything is agreed." |
| 201 homelab literals | 26.8 KB | 3 666 | 34 / 291 | 870, plus 943 settled | 2 | a reframe question on D1; on D2 "I don't have the faintest about the other one. I assume you know what you're doing." |
| 202 kubeconfig grants | 34.4 KB | 4 480 | 165 / 292 | 1 910 | 3 | "Agreed on all decisions." |

"Opener" is the `## Where we are` section; "code / prose lines" counts non-blank lines inside
and outside fenced blocks. `plan_qa_readout.py table` rows 198–202: zero dialogs in all five,
four to five operator messages each. The four docs of 199–202 were posted between 22:09 and
22:25 and read between 05:37 and 06:01 the next morning, cold.

Twelve decisions. Deviations from the recommendation: 0. Comments in the file: 1 (199 D2, the
Windows SMB wait — a fact only the operator held). Questions back: 2 (201 D1, a reframe that left
the decision standing; 199, the `file://` revert). Explicit delegations: 2.

## What the read says

- **The dialog problem is gone.** No dialog, no relapse after a reframe, no dismissal. The one
  in-file comment and the two questions back are the interaction the ruling wanted.
- **The doc was not read the way the design assumed.** The ruling's premise was that the
  operator reads the recommendation's grounds and refutes them. The docs were 27–35 KB; in
  three of five more than half was the opener, a premise-by-premise verification at `file:line`
  altitude with functions quoted whole; 199 had more lines of code than prose. The operator's
  verdict, 2026-09-03: "this is just a wall of text I can't make heads or tails of … I should be
  able to understand and comprehend what's there, so I feel I must plow through. But I really
  don't believe it has value. It shouldn't be necessary." And: "Assume the low number of
  responses is to a large degree due to me not understanding the document."
- **Eight of twelve decisions were not the operator's.** Strict versus lenient argv parsing in
  a test stub (198 D1), a capture script versus attached fixtures (198 D2), the interactive
  shim's step list (198 D3), a request header versus a `/proc` lookup (200 D1), a new boolean
  versus reusing `wasWorking` (200 D2), an env var versus a config key for a CA path (201 D2),
  a flat versus nested grant map (202 D1), an explicit versus derived clone host (202 D2). The
  writer's own alternative lines say "Loses" and "not worth it". The four the operator engaged
  with are the four that change what a user sees or what the operator runs: the `/ls` line and
  the Windows message (199), the literal surviving one release against an outage window (201
  D1), the push holds (202 D3).
- **The grounding itself earned its keep**, just not on the operator's page: 198's six premise
  corrections (the handover paraphrased a seam that had moved), 202's fifth clone-host site and
  a decision record saying the opposite of the target, 200's header-expansion probe against the
  real binary. That is the "15 stale premises" class caught before planning. Its reader is the
  plan-writer, through `plan.md`; nobody downstream opens `refinement.md`.

## The ruling (2026-09-03)

The operator's, item by item, on the session's four findings:

1. Grounding detail out of the doc — "I should not have to see the details. The planner agent
   will have this already."
2. The "code in full" rule dropped outright — the code the dialog brief complained about being
   cut off was UI mock-ups in option text, not source; the rule was a misread of it.
3. The opener replaced by an introduction of one to three paragraphs — "Summary and decisions
   (with context) is what I'm looking for."
4. The decision bar raised to what the operator could plausibly rule the other way; the
   settled list one sentence per item and filtered — "mostly noise … A far more compacted
   version (one sentence per item) I may read, but even then I'm not sure."

Shipped as dev 0.9.21: `plugins/dev/docs/refinement.md` § What is a decision and § The doc,
`agents/refinement-writer.md`, `skills/plan-slice/SKILL.md` § 2–3. The next read is the first
four slices on 0.9.21: doc length (the target is under 1 200 words), decisions per slice (expect
one or two, some zero), whether the delegating replies stop, and whether a settled item ever
draws a correction — the filter's only test.
