# Risk-based review — what the review record says, 2026-08-27

Research for Trello **#715 "Implement risk based review"**: before the plugin classifies changes
by path risk and skips the review of low-risk phases, the operator asked what the last slices'
reviews actually found and whether any of it would have fallen through. Every number here
regenerates from `tools/risk_readout.py` (`extract` reads the spec repo and git, `report` scores
the corpus against the candidate map; `--tests low|medium` prices both assignments of test files).

**Corpus.** Every completed KubeCoder slice with a run record — 63 slices, 063–186 (2026-07-24
→ 2026-08-25), **300 phases, 375 review sessions, 649 findings**. Impact tags (`blocking` /
`advisory`) exist from 144 on; before that an `issues` round fixed every finding, so a Blocker or
Major in an `issues` round is counted as blocking. Dispositions are read from the 16 close-out
reports the operator has processed (158–179); 182 onward are still blank. The reviewer's own
per-session price is $2.38 mean / $2.41 median (145 sessions over the 28 close-out-era slices).

**One repair worth knowing about.** 114 of the 300 `reviewed_head` shas no longer exist — the
test phase rebases the slice onto `origin/main` when lanes diverged, and the branch heads go with
it. Author dates survive a rebase, and `state.json`'s history rows give every writer session's
window, so those phases' files are recovered from the commits authored inside the window that
touch a file the round-1 review cites (the reviewer names what it read; parallel lanes commit in
the same window and are excluded by that filter). Spot-checked on 184 (three lanes that afternoon)
and 173; the two Ansible phases of 165 stay empty (no checkout here).

## 1. The candidate map

The operator's shape, made concrete for KubeCoder: repo base **medium**; documentation (`docs/`,
`*/docs/`, `manual/`, `CLAUDE.md`, `README.md`) and tools/scripts **low**; configuration and every
dotfile (`.claude/`, `.kubecoder/`, `.aiworkflowrc`, `Jenkinsfile*`, `Dockerfile`,
`controller/ingress/`) **high**; HelmCharts, KubeCoderConfig and Ansible base **high** (GitOps);
the spec repos **low**; tests a bucket of their own so both readings can be priced. A phase's
level is the max over the files it touched — "fully low" is the skip case the card describes.

| level (tests = medium) | phases | r1 `issues` | 2nd round | blocking findings |
|---|---:|---:|---:|---:|
| low | 38 | 14 (37 %) | 14 | 20 |
| medium | 225 | 47 (21 %) | 49 | 49 |
| high | 35 | 8 (23 %) | 8 | 9 |

With tests read as low, 60 phases are low, 17 `issues`, 25 blocking findings — the 20 test-only
phases add two `issues` rounds and four blocking findings (184 P1's Blocker: the new leak guard's
join window equalled the leak's lifetime, so it caught nothing; 063 P4: the modelled teardown was
atomic, the real one resurrects the env).

## 2. The headline: "documentation is low risk" is false of this pipeline

The 38 fully-low phases are 21 `../KubeCoderSpecs` phases, 8 `manual` phases, 8 root doc phases
and one extension doc phase — 53 review sessions in all. **They carry the highest `issues` rate
in the corpus (37 % against 21 % for code), and zero of their 20 blocking findings was refuted**
(nothing in the whole record is: the `refuted` lists are empty). What the reviewer blocked on:

- **Wire-contract text stating what the code does not do** — `api/controller-api.md` /
  `api/worker-api.md` in the spec repo: a `url: null` rule the projection can never emit (117 P2);
  a hoisted `404 iff the env is unknown` false for two routes it governs (117 P4); the mint rule
  still naming "the first create" as the gate (117 P8); a "same shapes, no extra fields" claim
  false as widened (117 P6); the projection rationale that only a file edit can produce a
  divergence when a catalog removal does (153 P2, and two more in its round 2); the status-changed
  poke enumerated as four parties after the diff added a fifth (170 P2); "exactly two departures
  from problem+json" when there are three (158 P1); the "every refusal lands before any mutation"
  invariant with an undocumented exception (152 P4). Fourteen blocking findings against 18
  phase-touches of `api/` — **78 per 100**, the highest yield of any path in the estate.
- **The manual describing behaviour the product does not have** — four `repro-trace` Majors on
  one page (156 P1: Ctrl-C handling, backgrounded processes, the env-var claim, `-t` in a pipe —
  each one run and shown false); a table telling the reader `KUBECODER_ENV_TOKEN` authenticates to
  the in-pod agent when it authenticates to the controller (109 P7); a page still counting a
  deleted `--mode` completion (152 P7). Seven blocking over 24 phase-touches of `manual/docs`.

Both are documentation in the map's sense and both are the places where a false sentence reaches
a user or a client implementer. The consequence class is not an outage — it is a reader acting on
a wrong contract — and the reviewer catches it at the same rate it catches code defects. Where the
map's "low" holds is a narrower set: **process and dev docs** — `KubeCoderSpecs:slices/` (45
files over 21 phases), `docs/operations`, `docs/conventions`, `controller/docs`, `bot/docs`,
`docs/platform` — **0 blocking findings across ~40 phase-touches**, only comment-prose
advisories. `worker/docs` has one (a doc-truth claim, 148).

**What skipping would buy.** All 53 low-phase review sessions at $2.41 ≈ **$128 over 63
slices — about $2 a slice, 2–3 % of a typical $80 run** — against 14 phases that shipped a false
contract or manual sentence unreviewed. Restricting "low" to the process-doc set above skips
nine sessions (nine phases, ≈ $22) and loses nothing on record. The saving is real but it is not the
lever: the reviewer is 17 % of a slice's spend and its sessions are among the cheapest.

## 3. The map the record confirms

Blocking findings by the files they cite, against how often a phase touched the path
(`per 100` = blocking findings per 100 phase-touches; `op-actioned` = close-out entries from that
path the operator carded, fixed or folded):

| path | phases | blocking | per 100 | advisory | op-actioned |
|---|---:|---:|---:|---:|---:|
| KubeCoderSpecs `api/` (wire contracts) | 18 | 14 | 78 | 40 | 2 |
| KubeCoder `manual/docs` | 24 | 7 | 29 | 22 | 2 |
| `controller/tests` | 98 | 24 | 24 | 95 | 4 |
| `controller/src` | 91 | 21 | 23 | 168 | 7 |
| `worker/internal` | 86 | 16 | 19 | 124 | 9 |
| `bot/src` | 27 | 5 | 19 | 36 | 0 |
| KubeCoderSpecs `slices/` | 21 | 4¹ | 19 | 12 | 2 |
| HelmCharts `configs/` | 6 | 1 | 17 | 2 | 0 |
| `worker/docs` | 6 | 1 | 17 | 15 | 0 |
| `bot/tests` | 36 | 5 | 14 | 25 | 1 |
| `vscode-extension/` (root files) | 23 | 3 | 13 | 25 | 0 |
| HelmCharts `charts/` | 15 | 2 | 13 | 10 | 0 |
| `controller/docs` | 13 | 1 | 8 | 13 | 1 |
| `tools/contracts_codegen` | 12 | 1 | 8 | 4 | 0 |
| `worker/cmd` | 35 | 2 | 6 | 29 | 2 |
| `packages/kubecoder-contracts` | 28 | 1 | 4 | 21 | 0 |
| `vscode-extension/test` | 24 | 1 | 4 | 9 | 0 |
| `vscode-extension/lib` | 21 | 0 | 0 | 8 | 0 |
| `.kubecoder/` | 6 | 0 | 0 | 7 | 2 |
| `docs/operations` · `docs/conventions` · `docs/platform` · `bot/docs` | 21 | 0 | 0 | 21 | 4 |
| `mcp-server/*` · `contracts_fixtures` · root files | 28 | 0 | 0 | 13 | 0 |

¹ all four are the slice's own `plan.md` cited beside an `api/` finding — the plan is never the
defect.

Three groupings, and they are not the map's three:

1. **Statements of truth about the product** — wire contracts, the manual, and (the same thing in
   code form) the controller's tests — are where the reviewer blocks most. The reviewer's method
   explains it: it runs the claim. A contract sentence, a manual paragraph and a test assertion
   are all claims that can be witnessed false; a config line mostly cannot be, in a sandbox.
2. **Mechanism code** (`controller/src`, `worker/internal`, `bot/src`) sits at 19–23 per 100 and
   generates most of the advisory volume — the medium the map already assumes.
3. **Generated, mechanical and process surfaces** — codegen, contracts package, extension lib,
   process docs, `mcp-server`, root files — are near zero. This is the only set the record lets
   "skip the review" touch.

**Config is high-consequence, not high-yield.** `.kubecoder/` and the dotfiles produced no
blocking finding in six touches, seven advisories, and two operator-actioned entries. The 20
pure-HelmCharts phases produced three `issues` rounds — and all three were deploy-breaking (070
P2: a `Recreate` switch the apply rejects, Blocker; 165 P3: the step-ca Secret applied without
rolling the pod, so the new CA never loads; 182b P2: a non-optional `secretKeyRef` to an unseeded
path that bricks the controller's own startup). That is Zalando's argument exactly — their rule
set is "built based on analysis of our production incidents", typos in config are high because
of what they did, not how often. The map's `high` for GitOps and dotfiles is right on consequence
grounds; the record neither confirms nor refutes it on frequency, and 6 touches is too few to.

## 4. The written-up findings the operator progressed

Of 282 close-out entries in the 28 reports, 153 carry a code-reviewer provenance: the operator
actioned 29 (card, fix now, fold), closed 60, 40 were resolved in-run (consult residue, doc phase,
a later phase), 24 are still blank. **Five of the 29 came out of a fully-low phase**, and all
five are prose nits the operator had fixed inline while closing the report: 156 B7 (the manual's
Ctrl-C paragraph reads as *your* terminal), 167 B1 and S4 (the `CLAUDE.md` toolchain-scope bullet
and a sample-key exception, both settled by the D217 ruling), 170 B2 and B3 (an ordinal and a
mis-stated redirect source in `api/controller-api.md`). Under the card's own rule — nits not
actioned do not count; nits fixed in a sentence barely do — the advisory side of low-phase reviews
is worth close to nothing, and the blocking side (§ 2) is worth all of it.

The 24 actioned entries from medium/high phases are the ones that became cards: untested
production wiring (171 B4, 170 S4, 173 S4, 169 S11, 162 S5), a retry that never gives up (170
B17), a degrade path that only one error class reaches (170 B10) — coverage gaps and lifecycle
edges in `controller/src` and `worker/internal`, which is where the medium base already puts them.

## 5. Late findings (the reach goal)

**Cross-phase.** Twelve blocking findings cite a file an earlier phase of the same slice changed
and the reviewed phase did not: 063 P4 (the teardown P1 made non-atomic), 092 P3, 125 P3 (twice,
a P1 CLI test), 143 P3 (a P1 `app.py` promise), 144 P2 (a P1 service), 152 P4 and P7, 159 P3 (a
P2 store change), 173 P2 (P1's events), and — the two doc cases — **109 P7 and 152 P7, where the
manual page was reviewed against code the same slice had changed two phases earlier**. The
pattern the card guessed at is there: a documentation phase that follows a code phase inherits
the code phase's risk, whatever folder it lives in. A path map cannot express that; a slice-level
rule can — *a doc phase in a slice that changed the code it documents is reviewed as the code
was*.

**Appended by the completion consult** (CO era): 146 (P1's test pinned the token but not the
refusal), 148 (three doc statements the slice's own edits left wrong), 149 (two acceptance claims
with nothing behind them), 152 (`GitClient.sync_repo` and a second helper left dead "in files no
phase touched — invisible to a per-phase review"), 153. **Second test rounds:** 152 (the manual's
`mkdocs --strict` red on links to a page P1 deleted), 173 (V14: one production `readEnvName` call
left, found live after a real merge conflict with the concurrent 174), 182 (confirmation only).
The late finds are not concentrated in a folder; they are concentrated in a *shape* — the thing a
phase deleted or changed is still referred to somewhere outside its diff. That is the consult's
job today and the record shows it doing it; a risk map does not move it either way.

## 6. The planning phase

The plan loop's review is not a candidate for risk-skipping, on the record: of the 30 plan reviews
in the close-out era, **3 signed off** (157, 164, 174), 11 returned `issues`, 16 returned
`questions` to the operator — including the doc-only slices 156 and 167. What the plan reviewer
blocks on is orthogonal to path risk: an acceptance criterion that contradicts a ruling, a
"verified — do not re-derive" claim that is wrong, a wire contract the plan falsifies without a
phase to correct it (184, 142, 179 — the recurrence 184's S2 records), a Target that leaves the
half that can break outside the gate. None of those are cheaper to find on a low-risk slice.

Nor can a phase's level be *predicted* at planning from its `Target:` — the one fact a plan
carries: `../KubeCoderSpecs` covers both the highest-yield path in the estate (`api/`) and the
lowest (`slices/`); `root` covers everything. A per-phase level set by the plan-writer would be a
guess about paths the writer has not touched yet, and self-graded, as the card already notes.

**The approach the record supports** needs no planning-side classification at all: the driver
classifies **after the executor commits**, from `git diff --name-only` of the phase branch against
the map — the same call the doc phase already makes for its diff files. Nothing is self-graded
(the writer cannot choose its level; the files it touched choose it), nothing is predicted, and
the review dispatch that follows carries the rendering the card describes ("base medium; `charts/`
high; `docs/operations` low"). The plan loop's only part is the cross-phase rule from § 5: a plan
whose doc phase follows a code phase says so, and the driver reviews it at the code phase's level.

## 7. What to build, and what not to

- **Do not ship "skip review when fully low" with documentation as low.** It saves ≈ $2 a slice
  and would have let 14 phases ship a false contract or manual sentence unreviewed — the exposure
  increase the card set out to avoid. If a skip is wanted, `low` has to mean the process-doc set
  (`slices/`, `docs/operations`, `docs/conventions`, `docs/platform`, `controller/docs`,
  `bot/docs`, `mcp-server/`, generated code and fixtures) — nine sessions over 63 slices, no
  finding lost on record. Wire contracts and the manual are **medium at least**; on the record
  they are the highest-yield paths there are.
- **The reviewer's dispatch line is where the map earns its keep**, not the skip. The card's own
  wording — lead with the majority level, name the deviating paths, only paths the diff touches —
  is a few lines in `run_loop.py`'s review dispatch, and it gives the reviewer the consequence
  class the record shows it does not otherwise weigh: config and GitOps are high because of what a
  typo does, and the three HelmCharts `issues` rounds were all of that kind. That is the part of
  the card that lowers exposure; it needs neither the consult awareness nor the map-maintenance
  bullet, which exist only to make skipping safe.
- **Test files are not low.** Two of the twenty test-only phases carried a Blocker or a
  cross-phase Major, and `controller/tests` is the single highest-volume blocking path. Tests are
  claims about the product; the reviewer treats them so.
- **The map lives in `.aiworkflowrc`, and cannot be added today.** `project_config.py` refuses
  unknown keys, so a `[risk]` table in KubeCoder's file breaks preflight until the plugin reads it
  — the card's "add the configuration already" has to ride the plugin change. A per-target rc file
  is not needed for KubeCoder (one map covers the repo; HelmCharts, DockerImages and the spec repo
  each get their own at their root, which the existing rc discovery already finds) — the
  operator's per-target file is the general case and costs nothing to allow.
- **Shape**, for when it is built — simple relative paths, no globs, longest prefix wins, dotfiles
  high by default:

  ```toml
  [risk]
  base = "medium"                       # repo default; "low" for a process-doc repo, "high" for GitOps
  paths = { "docs/operations" = "low", "docs/conventions" = "low", "manual/docs" = "medium",
            "charts" = "high", "configs" = "high", ".kubecoder" = "high" }
  ```

- **Re-read after twenty more slices** with the dispatch line in: does the reviewer's blocking
  rate on `charts/`/`configs/` move (it should not — those were caught), does `api/` stay at the
  top (it is a doc-truth problem the doc phase does not cover, 184 S2), and do the cross-phase doc
  Majors stop once a doc phase after a code phase is reviewed at the code phase's level.

## Caveats

Phase file sets come from git on two methods (`range` for 185 phases whose heads survive,
`author-window` for 115 rebased ones); the window method was checked on the parallel-lane
afternoon of 184/185/186 and is tight there, but a lane committing to the same file in the same
window would still leak in. Findings before 144 have no impact tag — every Blocker/Major in an
`issues` round counts as blocking, which is what the fix round of that era did with them. The
headline formats of 63 slices' review files are parsed by one regex family; every `issues` round
resolves to at least one finding, but cited files are what the reviewer wrote, so a finding that
names no file is charged to the phase's files. The operator's dispositions are classified by
keyword (card / fix / fold vs close / won't progress); the two entries the classifier could not
place are printed by the report and were read by hand (155 S2 — a reframed requirement, not a
review finding; 182b A2 — an operator action, done).

Sources for the Zalando practice: [Agentic Engineering at Zalando: a snapshot](https://engineering.zalando.com/posts/2026/08/agentic-engineering-at-zalando-a-snapshot.html)
(33 % of PRs auto-approved as low risk; the rule set derived from production-incident analysis;
lead time −20–40 %; documentation-only low, config typos high, backwards-compatibility breaks
medium).
