---
issue: AIWF-113
status: proposal, unruled
---

# Phases per slice and cost on Opus 5.5 (read, 2026-10-27)

**Recommendation.** Move triage's target from "about seven" to **about ten to twelve**, and the
ceiling from ten to **fourteen**. On Opus 5.5, a slice's cost per changed line keeps falling as
the slice grows, all the way to fourteen phases, which is as far as the data reaches. At a
matched phase size, a 12–14-phase slice costs 6–13 % less per phase than a 7-phase one,
depending on the fit. That is $0.45–1.00 a phase: roughly $300–600 over the era's 627 phases,
had they all been grouped at twelve. The era's spend was $5,493.

The "seven" came from the 2026-09-18 measurement on Opus 5.1. Even the 5.1 data does not show a
minimum at seven. It shows a flat stretch from 5 to 10 phases, on thin data past that. Opus 5.5
cut every cost term, by 37 % per phase, 53 % per line and about two-thirds per slice. That made
every slice cheaper rather than moving where the cost bottoms out. Because the per-slice term
fell the most, bundling saves fewer dollars than it did under 5.1, though it still saves.

## Method

The unit is the slice: every completed run (doc phase `done`) in every spec repo with run
records. That is KubeCoder, Ansible, PilotApp, FieldnotesApp, Notifications and DHCPApp; the
5.1 era adds Architecture and YouTrackMCPServer.

- **Eras.** The 5.5 era is runs created 2026-09-22 → 2026-10-26: 81 slices, with ≤ 5 % of spend
  on `claude-opus-5`. The 5.1 era is runs created 2026-07-31 → 2026-09-21: 118 slices, ≥ 80 %
  on `claude-opus-5`.
- **Cost.** `slice_cost.collect` gives every recorded session plus its sub-agents and the two
  orchestrators, put in buckets by their top-level session.
  - *Phase work:* code-writer and code-reviewer rounds, and appended phases.
  - *Fixed:* the plan loop (including the interactive `/dev:plan-slice` session), consult,
    test phase, doc phase, wrap-up and the run orchestrator.
- **Work.** The lines changed by each phase come from the `--stat` summary line its round-1
  code-reviewer reads first. This covers 80 of 82 slices fully. It matches `git diff
  --shortstat` of the landed range on the 39 slices whose phase commits survived the push:
  median ratio 0.99. Phase heads are rewritten on push, so git alone measures only half.
- **Phase count.** The planned phases (`state.json` phases minus `appended_phases`).

## Results

**Opus 5.5, 81 slices**

| phases | slices | lines/phase | median $/slice | $/100 lines (median) | (pooled) | fixed $/100 lines |
|---|---|---|---|---|---|---|
| 1–4 | 11 | 196 | 23 | 3.26 | 2.50 | 1.59 |
| 5–7 | 32 | 398 | 47 | 2.22 | 1.90 | 0.93 |
| 8–10 | 21 | 556 | 81 | 1.60 | 1.14 | 0.41 |
| 11–14 | 16 | 698 | 100 | 1.27 | 1.12 | 0.34 |
| 15+ | 1 | 141 | 111 | 4.35 | 4.35 | 1.54 |

**Opus 5.1, 118 slices**

| phases | slices | lines/phase | median $/slice | $/100 lines (median) | (pooled) | fixed $/100 lines |
|---|---|---|---|---|---|---|
| 1–4 | 53 | 226 | 50 | 8.27 | 6.34 | 3.90 |
| 5–7 | 47 | 254 | 82 | 5.63 | 4.03 | 2.09 |
| 8–10 | 12 | 248 | 124 | 5.50 | 4.77 | 2.24 |
| 11–14 | 6 | 394 | 176 | 4.08 | 2.73 | 0.97 |

The plateau between 5–7 and 8–10 in the 5.1 table is the only shape in either era that could
read as a sweet spot near seven.

**Separating phase count from phase size.** In the 5.5 era bigger slices also have bigger
phases, and per line a big phase is cheaper by itself
([session-size-read-2026-10-27.md](session-size-read-2026-10-27.md)). So the per-line figures
above mix two effects. A least-squares fit of slice cost on phases, phases² and kLOC separates
them (slices ≤ 14 phases):

- **5.5:** $0.3 per slice + $7.02 per phase − $0.144 per phase² + $4.59 per kLOC. The
  linear-only fit gives $7.1 per slice + $4.89 per phase + $4.51 per kLOC, R² 0.85.
- **5.1:** $21.8 per slice + $7.85 per phase − $0.011 per phase² + $9.58 per kLOC. The
  linear-only fit gives $22.2 + $7.72 + $9.56, R² 0.73.

The phase² term is not distinguishable from zero in either era (bootstrap 95 % CIs straddle it
widely). Nothing in the data turns cost back up as slices grow. At each era's median phase size,
the modelled cost per phase is:

| phases | 4 | 7 | 10 | 12 | 14 |
|---|---|---|---|---|---|
| Opus 5.5 (441 lines/phase) | 8.53–8.70 | 7.88–8.07 | 7.56–7.62 | 7.33–7.43 | 7.04–7.34 |
| Opus 5.1 (240 lines/phase) | 15.6 | 13.2 | 12.2 | 11.8 | 11.6 |

Each 5.5 cell is the quadratic fit's figure and the linear fit's. Going from 7 to 10 phases
saves 4–6 %, and from 10 to 14 a further 3–8 %, depending on the fit.

**What a bigger slice does to the fixed roles (5.5).** Each fixed role costs less per phase as
the slice grows:

- the plan loop: $2.84 per phase at 1–4 phases, $2.43 at 5–7, $1.81 at 8–10, $1.47 at 11–14;
- the doc phase: $0.80, $0.74, $0.72, $0.45;
- the test phase: $0.45, $0.35, $0.20, $0.12.

Only the wrap-up rises ($0.14 to $0.35 per phase), because bigger slices leave more close-out
entries. Session sizes grow without running away. The doc-writer's median peak is 171k at 5–7
phases, 250k at 8–10 and 206k at 11–14; the largest is 488k. The plan-writer's median peak is
142k, 205k and 182k. The consult's is 92k, 105k and 112k.

## What to change

- **`plugins/dev/skills/triage/SKILL.md` step 6:** "about seven is the sweet spot" becomes about
  ten to twelve, and "Ten is the ceiling" becomes fourteen. The reason given stays the same: the
  fixed overhead per phase.
- **The residual sweep's ten-phase refusal** (`residual-sweep.md`, `sweep_slice.py` and its
  suite) moves to fourteen with it, since "a sweep is a slice and sized like one".
- **`CHANGELOG-workflow.md`:** an entry citing this read.

## Caveats

- **Beyond fourteen there is no evidence.** One 18-phase slice (Ansible 026, 141 lines a phase)
  is the only case, and it is the most expensive per line of the era.
- **Projects are not controlled for.** In the 5.5 era the 11–14 band is 11 Ansible slices, 4
  PilotApp and 1 FieldnotesApp. The 5–7 band holds most of KubeCoder. The fit's kLOC term
  absorbs phase size, not the project.
- **Operator time is not counted.** The plan interview grows with a slice, and only its
  session's tokens are in the plan-loop figure. A slice of twelve also holds its lane longer
  before anything merges.
- **The fits are noisy.** The per-slice intercept's 95 % CI is −16 to +19 in the 5.5
  quadratic. The band tables are the sturdier evidence, and they point the same way.

Scripts: `/work/scratch/phase-count/` (`measure.py`, `review_stat.py`, `report2.py`, `fit.py`;
uncommitted). They gather and price every slice, read the review stats, and produce the tables
and fits above.
