# Rationale — the explanation layer

Why the `dev` plugin is the way it is, with the evidence. The contract docs under
[`plugins/dev/docs/`](../../plugins/dev/docs/) say *what* the loops do; [`ADOPTING.md`](../ADOPTING.md)
says how to use them; [`AUTHORING.md`](../AUTHORING.md) how to change them. These docs say *why*, and
what the record shows. They link to the contract docs and never restate them — the single-source
rule applies here too. Every number carries its source (a version, a slice, a research file), and
claims a reader could confuse are labelled **measured** (a number from the record), **ruled** (an
operator decision) or **untested** (built or proposed, not yet read).

| Doc | Question it answers |
|---|---|
| [`overview.md`](overview.md) | What does the workflow do, who acts where, and what does one real slice look like end to end? |
| [`principles.md`](principles.md) | What are the design rules, and which incident produced each one? |
| [`history.md`](history.md) | How did the workflow get its shape — the eras, and what was tried and withdrawn? |
| [`improvements.md`](improvements.md) | What specifically changed, on what evidence, and what did the readout show? A catalogue by theme. |
| [`measurement.md`](measurement.md) | How are the conversations mined — the tools, the definitions, the findings, today's corpus numbers, and the research method? |
| [`literature.md`](literature.md) | How were the research papers used — the corpus pipeline, the paper-to-rule pairs, what did not transfer? |
| [`reporting.md`](reporting.md) | Why one close-out report per slice instead of a tracker card per finding, and what do the reports show? |
| [`plan-refinement.md`](plan-refinement.md) | What was wrong with the planning interview, and what replaces it? The one untested change in the set. |

Written 2026-09-02 at plugin 0.9.13. Slice ids are KubeCoderSpecs unless marked Ansible; runs are
priced at API sticker prices from token counts, as [`measurement.md`](measurement.md) explains.
