# Opus 5.5 against 5.1, and `high` against `xhigh` — the run phases, read 2026-10-03

**Ruling (operator, 2026-10-03, same day):** back to `xhigh`. "Every time I try this (lower
model / lower effort), I get bitten. It really matters and top model + xhigh is the sweet spot,
if you have the tokens. And I don't have to use xhigh because of the cost, since that's half
already." The revert is 0.9.72, built by the operator the same afternoon; 0.9.71's flip to `high`
stood for one morning and four slices. The settled ruling in `CLAUDE.md` — one uniform effort for
every Opus role, no tiering — is unchanged in substance; its effort word is `xhigh` again.

**The question.** Opus 5.5 replaced 5.1 on 2026-09-22 in every environment. On 2026-10-03 the
operator moved every Opus role from `xhigh` to `high` (0.9.71) and ran four slices on it —
Ansible 038, 040, 041 and KubeCoder 240 — then asked for a subjective read of the run phases
only: is 5.5 different from 5.1, and is `high` different from `xhigh`.

## 1. Corpus and method

Run phases only (code-writer and code-reviewer, every round), slices run on plugin ≥ 0.9.12.
The cohort of a session is read from its transcript, not from the date: every assistant record
carries `"effort":"high|xhigh"` at the top level and the model id in `message.model`
(`claude-opus-5` is 5.1, `claude-opus-5-5` is 5.5).

| cohort | runs | phases |
|---|---|---|
| Opus 5.1 / `xhigh` | KubeCoder 190–229, Ansible 010–024 (through 09-21) | 247 |
| Opus 5.5 / `xhigh` | Ansible 025–037, KubeCoder 230–239, Fieldnotes 001–002 (09-22 → 10-03 01:22) | 173 |
| Opus 5.5 / `high` | Ansible 038, 040, 041, KubeCoder 240 (10-03 morning, 0.9.71) | 26 |

Two lenses:

- **Numbers** from `state.json` histories, the transcripts and the review files, normalised by
  the phase's diff size (lines changed, read from the reviewer's `git diff --stat`). The
  normalisation matters: today's Ansible phases were small (median 61 lines against 197 under
  `xhigh`), and raw per-phase figures flatter `high` by about 2×.
- **Seven blind pairwise reads** by Opus sub-agents. Each got two same-repo slices labelled X
  and Y, the rendered transcripts of every run-phase session, the review files and the plan, and
  the two role contracts — and was told the pair might differ in model, effort, both or neither,
  and to compare rather than guess. Pairs: 037 vs 020, 040 vs 037, 035 vs 038+041, 239 vs 228,
  017 vs 040, 240 vs 237, 229 vs 240. Plus my own read of 240 P3 (the heaviest `high` phase) and
  the four blocking reviews written at `high`.

Tooling (research only, not plugin): `/work/scratch/model-read/render.py` renders a transcript
readable (thinking is redacted in the jsonl; `[thinking]` renders empty), `render_slice.py`
renders a slice's run-phase sessions and review files to a folder, `cohorts.py` tables the
cohorts. 240's run record was not pushed when this was read; a Haiku headless session in the
KubeCoder environment copied it into the shared home.

## 2. Opus 5.1 → 5.5, both at `xhigh`

Per 100 diff lines, round-1 writer and reviewer plus any fix rounds:

| | writer output tokens | writer minutes | all-in $ | r1 blocking (pooled) | review words |
|---|---|---|---|---|---|
| Ansible, 5.1 → 5.5 | 24.7k → 16.1k | 4.7 → 3.2 | 3.27 → 1.72 | 18 % → 11 % | 658 → 430 |
| KubeCoder, 5.1 → 5.5 | 13.7k → 11.0k | 3.2 → 2.2 | 2.59 → 1.14 | | |

About half the cost per line of shipped diff. The price cut ($5/$25 → $4/$20, cache reads at
0.05×) is part of it; 5.5 also writes 20–35 % fewer output tokens per line and reads in bigger
batches. Fix rounds fell from 21 % to 16 % of phases, advisories per review from 1.2 to 0.7, and
the reviews got a third shorter without the readers seeing substance go.

The 5.1 signature in a transcript is long one-call-per-turn reading with 8–12k-token deliberation
turns (228 P6: eleven minutes before its first edit). 5.5 reaches the first edit sooner.

**Readers (037 vs 020, 239 vs 228): no decisive quality gap.**

- Slight edge to the 5.5 writer on claim hygiene and permissions. 5.1's 020 recorded log and
  exit-code claims it had not witnessed (the reviewer disproved them), printed the vault password
  with `env | grep`, and switched to the write kubeconfig for a fact the phase did not need. 5.5's
  037 had no contradicted claim, and its P3 reviewer explicitly declined cluster-admin.
- Slight edge to the 5.5 reviewer on live checking: 239 P4's reviewer fetched Argo CD's source
  and probed Keycloak's token endpoint to prove the runbook procedure the writer had just written
  could not work.
- Slight edge to the 5.1 writer on mutating its own tests every phase (228, 229).

5.5 at `xhigh` is the best cohort in the corpus by every number here, and the readers found
nothing it does worse.

## 3. `xhigh` → `high`, both Opus 5.5

Per 100 diff lines: output tokens −29 % (Ansible) / −32 % (KubeCoder); writer minutes −37 % /
−16 %; all-in $ −23 % / −25 % (1.72 → 1.32, 1.14 → 0.86). The thinking bursts halved — median
largest turn 4.4k → 2.3k output tokens, turns over 2k output 11 % → 4–7 %. Reviewer cost on
KubeCoder nearly halved (0.43 → 0.25 $/100 lines), on Ansible it stayed flat. Done-records moved
toward the cap (26 → 22 lines), reviews shorter again (430 → 338 words). Round-1 blocking 15 % (4
of 26) against 11 % — not distinguishable at this n. Batching is the same in every cohort (one
tool call per turn, four to five shell commands inside it).

**Readers.** Every pair with a `high` slice in it leaned to the other side on *writer care*, and
to `high` or even on *reviewer catches*:

- **040 vs 037** — 037 "marginally stronger on judgment and depth" at 2× the tokens; 040
  "leaner, same rigour", and its reviewers made the two most consequential catches in the pair
  (P2 F1: the MetalLB guard silences the critical alert in exactly the failure it exists for;
  P7 F1: a runbook query that silently drops the newest attempt, sized with live hook-pod
  counts). 040's writer left a false `> 0` mutation claim in its done-record even after the fix
  round, narrated history in a rule comment, and wrote a junk command into a README.
- **017 (5.1) vs 040** — "writers: 017 stronger; reviewers: 040 equal or stronger". Two
  first-round blocking defects in eight phases against none in six (017's gate ran nothing, so
  its reviewers had less to catch with).
- **240 vs 237** and **229 (5.1) vs 240** — both preferred the `xhigh` side. 240 P4's writer wrote
  the quarantine rule into its done-record and skipped it in its own startup pass (caught,
  witnessed with a throwaway test — the best finding in the corpus). 240 P5's writer and reviewer
  both declared the FIFO test stable after 7 and 15 isolated runs; the tail sweep went red and an
  extra phase P9 was needed. 240's writers mutated their own tests in 2 of 9 phases; 229's and
  237's did in every phase.
- **035 vs 038+041** — no clear difference; `high`'s reviewers 2–3× faster at matched depth; a
  few small unbacked statements (038 P4 wrote "about ten minutes later" for a one-minute wait
  and corrected itself; 038 P5's "no parent commit's gate was red" was an inference).

**The reviewer at `high` is uneven.** Deep where it dug — 240 P4 F1, 240 P5 F1 (a surviving
mutation with its sibling as control), 040 P2 F1, 040 P7 F1, all real and witnessed — but it
signed off 240 P1 (348 lines) in 90 s and P2 (278 lines) in 84 s on reading alone, P1 asserting
"the obvious mutations would fail" without running one. 237's reviewer mutated every phase,
seven of them in an isolated worktree.

**My own read of 240 P3** (693 lines, 29 files, 11.5 min): competent and well-structured — eight
batched orientation turns, a one-sentence design, heredoc edits, fixtures repaired, the
done-record drafted while the gate ran, the turn ended to wait for the notification. Nothing in
it reads as a weaker model. The four blocking reviews at `high` read as well as any at `xhigh`.

**Not effort-related**, because `xhigh` does it too: the `kubectl`-not-on-PATH fumble; operator
decisions left in the final chat message instead of a close-out entry (037 P3 under `xhigh`,
240 P2 and P7 under `high`); done-records over the ~25-line cap; sleep-polling the gate.

## 4. Reading

- 5.5 is a straight win over 5.1: same or better output at half the cost per line. The one
  thing 5.1 did more of (self-mutation every phase) did not translate into fewer defects reaching
  review.
- `high` buys about a quarter off per line — not the 60 % the raw per-phase numbers suggest — and
  pays with thinner writer care: an unchecked claim, a self-inconsistency, fewer self-mutations,
  one racy test waved through by both roles. Nothing wrong shipped; the reviewer and the sweep
  absorbed it. But the margin thinned on both sides at once, because the reviewer that is meant
  to catch a cheaper writer's slips also read large diffs without running anything.
- The sample is 26 phases, three of the four slices small-phase Ansible work. I had asked for
  ~20 more `high` phases before calling it. The operator called it the same day: the pattern
  matches every earlier step-down (0.7.0–0.7.2's effort tiering, `docs/research/status.md`
  § A3; the Sonnet proposals of 2026-09-09), the cost case is gone because 5.5 already halved
  the bill, and the quality case never materialised. `xhigh` it is.

## 5. What this closes

- **No effort step-down for the Opus roles, on any model**, now with three readings behind it
  (0.7.x, 2026-09-09, this one). The `CLAUDE.md` settled ruling keeps its shape; only the effort
  word reverts.
- The reviewer-at-a-different-effort experiment that § 3 points at is tiering, which the same
  ruling excludes; it is noted here as the observation that would have motivated it, not as a
  proposal.
- 0.9.72 carries the revert (`MODELS` in both loops, `agent-dispatch.md`, `principles.md`, the
  `CLAUDE.md` line, the changelog); it reaches runs after the marketplace update in each
  environment.
