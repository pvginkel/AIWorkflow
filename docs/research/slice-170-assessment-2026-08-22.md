# Slice 170 (SSH transport) — run assessment, and where the intervention catalogue stands

Written 2026-08-22 from: `state.json`/`history` fields (I1), `slice_cost.py` (I2), the phase
files, `close-out.md`, a full read of `log.txt` (2757 lines), the plan-loop files, git in
KubeCoder/KubeCoderSpecs/HelmCharts, and the same fields across slices 155–169. Planned on
plugin 0.9.2 (09:15–09:55), run on 0.9.3 (installed 10:35, run 10:37–16:28).

## 1. The slice in numbers

| | |
|---|---|
| Shape | 12 phases, 4 repos (KubeCoder root/worker/manual, `../KubeCoderSpecs`, `../HelmCharts`), `cross-cutting` declared (honestly — second time after 159), two attached design docs (426 + 311 lines), 25 ACs |
| Diff | P1 252 · P2 140 (specs) · P3 536 · P4 241 · P5 1654 · P6 1319 · P7 484 · P8 252 · P9 105 · P10 404 · P11 192 · P12 18 lines; docs +928/−196 over 55 files. ≈5.6k product lines, ≈1.1k doc lines |
| Cost | $212.78 priced (state: $211.18) **+ ≈$8.27 unpriced** (test-phase r1, see §3) ≈ **$221**. planner 13 % ($27.02 = $14.3 in-loop + $12.7 interactive refinement), research 4 % ($8.40, all plan-loop Explore), rework **2.9 %** ($6.05) |
| Tokens | 277M: cache-read 269M (63 % of $), cache-write 6.4M (19 %), output 1.53M (18 %) — 82 % of spend is context, not thinking |
| Wall | 8.0 h incl. planning; run 5h52 (10:37→16:28); 44 sessions, 2110 billed turns |
| Reviews | 13 reviews, 25 findings: **1 blocking** (P2 F1, Major, `contradiction`, confirmed real, fixed in 2 min + 5 min review = $2.45), 24 advisory (3 Major among them, each with a stated why-advisory), 8 comment-prose (32 %), 17 `none`-anchored advisories, **0 refuted** |
| Rounds | 12/13 phases signed off r1; P2 r2 only; 0 gate-fix rounds; 0 appended phases; generation 0; 0 operator questions |
| Bail-outs | 2 `protocol_failure` at P2's merge (11:19, 11:21) — **not agent failures**: slice 168's `close-out.md` was dirty in the shared specs worktree; driver blamed "an agent". ~4 min wall, no work lost |
| Test phase | r1 **vanished** (§3); r2 25/25 ACs live on dev (throwaway env, real ssh/sftp, pod recreate, extension auto-install), 21 min, $6.29 |
| Doc phase | 192 turns, 32 min, **$33.28 (16 %)** — costliest session; 55 files; 290k tokens/turn (2× a writer) |
| Close-out | 30 entries (A2 N1 B22 Q0 S5); 2 struck in-run (doc phase B20/B21), consult noted B6/B7; operator in one sitting: 6 cards, 7 fix-now (all comment/contract-prose nits), 15 closed, A1/A2 done ("everything works as expected" on prd) |

### Why this is the strongest run on record

- Over 140–157, phases above 230 changed lines drew a blocking finding **65 %** of the time
  (11/17). 170 had **nine** such phases (P3–P8, P10, P1/P4 borderline) and drew **0/9**;
  P5 (1654 lines) and P6 (1319) both signed off r1 with advisories only.
- Reviewers were not lenient: 11/13 executed something — mutations (P1, P6, P9, P10), a kaniko
  build (P1), contract regeneration + diff (P3), `sshd -t`/`-T` on a rendered config (P5), live
  CA + provisioner (P6), `helm template` → controller parser → live cluster (P12). P7 executed
  nothing; P11 greps + two spot checks. The 3 advisory Majors (P3 F1 sequencing window, P6 F1
  narrow fallback → carded as B10) state why they are not blocking; the operator agreed with
  each.
- The win was front-loaded: the plan-reviewer's one round caught the host private key landing
  on a disk-backed emptyDir read-only-mounted by every sidecar (a real exposure) plus four AC
  defects, and the plan-writer's r2 fixed them (memory-backed dev-container-only volume, V25)
  before any code. The plan corrected three spec assumptions against the repo. The run then had
  little to relitigate.

### Against the 155–170 population (16 slices, all from I1/I2 fields)

| | 140–157 baseline | 155–170 | 170 |
|---|---|---|---|
| reviewer r1 `issues` rate | 24 % (19/80) | 17 % (12/71) | 8 % (1/12) |
| blocking findings / refuted | — | 15 / 0 | 1 / 0 |
| comment-prose share of findings | ≈49 % (≤153) | 38 % (43/114), all advisory, $0 rework | 32 % |
| rework share | 9–16 % band | 2–19 %, median ≈7 % | 2.9 % |
| planner $ | $11–19 | $14–27 | $27 (12.7 interactive) |
| doc-writer share | — | 8–21 %, median ≈15 % | 16 % |
| appended phases | — | 0 in 16 | 0 |

## 2. What the report does not know (workflow findings)

1. **Test-phase r1 vanished.** Session `d7d321bf` (Sonnet) ran 15:11→~15:31: dispatched
   `dev:rebase-agent` (408 s, rebase onto `origin/main`, four conflicts + a mechanical gate
   fix = commit `0b03267`), swept, pushed KubeCoder and HelmCharts, started `track_build.py`
   in the foreground — **killed by Bash's 2-minute default timeout** (L2135) — re-ran it
   backgrounded, then **"waited by ending its turn"** (L2137–2142), exactly as the in-pod
   preamble's `## Waiting on work` says ("launch it, then … or stop"). The kc session was
   re-woken by the notification (L2144), pushed HelmCharts, backgrounded the second waiter and
   stopped again (L2155). The log printed `[result] Done` twice while the session was merely
   waiting; 3m45 later the operator restarted the loop with `--resume` (15:34:38). No
   `history` row, no bail-out, no close-out entry: **≈$8.27 and 23 min invisible** in
   `state.json`, `slice_cost` and the report. r2 redid only the live checks (r1's pushes were
   durable).
2. **The Summary and the Notable-events Focus say "no bail-out"** under a header that says
   `2 bail-outs` (same as 161). Cause: the driver records bail-outs in the header only, the
   header is stamped *after* the doc phase, and the doc-writer writes from the file.
3. **~50 turns/run re-learning `close_out.py`**: the dispatch line names the *report file*;
   `list` takes the *slice directory*; every session's first `list` fails, reads `--help`,
   retries (20 sessions × 3 turns; e.g. L130–132, L1997–1998). ≈$3–5 and minutes per run.
4. **Seven operator fix-nows that the rider licenses the consult to fix**: B2, B3, B5, B11,
   B12, B19, B22 — comment/contract-prose enumerations the slice's own change moved past, in
   files the diff touched. The report's own Bugs Focus line said "one disposition could cover
   the set"; the consult read "mechanical residue" as its own TODO/gofmt scan and left them.
   Other slices: 0–3 such fix-nows (158: 3, 156: 2); consult strikes have been 0 in 163–168.
5. Smaller: bail #1 blamed "an agent" for slice 168's dirty file (names the path only in
   bail #2); backgrounded Bash commands render in `log.txt` as `[subagent: <cmd>] [agent]
   completed` (57 lines) — indistinguishable from Agent dispatches; reviewers spend 2–4 turns
   per review re-deriving line citations (~25 turns); P7 writer spent ~10 turns on ruff line
   length; P6 writer ran the full suite 6× incl. a redundant triple; the doc-writer's two
   Explore surveys returned after it had begun writing; test r2 lost ~2 min to kubeconfig
   friction; B14 lacks a Provenance line; 3 rate-limit warnings 13:13–13:19, no 529.

## 3. Intervention catalogue — where it stands after 155–170

- **I1, I2** — 16 slices of fields; today's 16-slice table came from them alone → accept.
- **I3** — answered by C2's instrument rather than a sampled audit: 15 blocking findings on
  155–170, 0 refuted, all fixed and re-verified; 170's one carried a file:line contradiction
  trail → accept (≥80 % bar met); **C4, C5 → reject** (precondition — low precision after
  C1+C2 — did not occur).
- **I4 / C6** — the report is the ledger (170: 30 entries → 6 cards); C6's queue no longer
  exists in that form → close both.
- **I5 / C8** — 11/13 reviews in 170 executed something unprompted; a field/rule would add
  register prose (D2) for behaviour already present → close unbuilt.
- **A1, A2** — `cross-cutting` declared honestly on 159 and 170, `pre-settled` on the small
  ones; plan-writer research 0 on pre-settled, $6.76 on 170's cross-cutting → accept.
  **A5** → reject (doubles plan latency for a bounded saving; planner absolute holds $14–27).
- **B2, B4** — $0 prose rework for 27 slices since 0.4.2 → accept. **B1** — count 38 % vs
  49 %; cost zero; accept as-is. **B3** → reject: the doc phase is already the costliest
  session (8–21 %), and the surviving comment nits are a consult-rider problem (§2.4), not a
  relocation problem.
- **C1, C2** — holding (anchored ≠ blocking held in both directions on 170; refute path still
  unexercised after 15 firings — note it) → accept. C3, C7, D1 already accepted.
- **D2** — keep the lean-register rule as standing discipline; the dispatch audit is moot while
  precision is this high → accept as rule. **D3** → close dormant.

The research question is answered: within-run amplification is bounded and cheap, blocking
precision is high, prose churn costs $0, the planner floor holds. The one lesson with no entry —
**context volume per turn sets 80 %+ of cost** — is now measured (170: 82 %), and the doc-writer
is where it bites hardest.

## 4. What to try next (and what not to)

Tweaks grounded in 170, each S:

- **T1 — headless waiting.** A dispatched agent's turn end is ambiguous to the driver. Either the
  agent waits in the foreground (`track_build.py` with a ≥10-min Bash timeout; never "stop to
  wait") — a line in the in-pod preamble's `## Waiting on work` (KubeCoder repo, which the plugin
  has leaned on since 0.7.4) and/or `test-agent.md` — or the driver narrates "session waiting on
  N background tasks" instead of `[result] Done`. Evidence: §2.1.
- **T2 — `close_out.py` accepts the report path** (or the dispatch line names the slice dir).
  Evidence: §2.3.
- **T3 — the consult treats the report's live nit entries as residue candidates** (fix + strike
  under the existing rider, same bound: no behaviour change, files the diff touched). Measure:
  operator fix-now dispositions/slice → 0–1. Evidence: §2.4.
- **T4 — the driver appends a Notable event per bail-out (and per round that returns no
  verdict)**, naming the dirty paths; the header then cannot contradict the Summary (161, 170),
  and a vanished round exists in the record. Evidence: §2.1–2.2, §2.5.
- **M1 (optional) — a cross-slice trend command** (`slice_cost.py --trend <completed-dir>`): the
  table in §1 was a one-off script over the I1/I2 fields; make the next read one command.

Not now: no new reviewer/writer register rules, no effort or model changes (A3/A4 stand),
no B3. The doc-writer's cost shape (one session, whole diff, every surface, 290k tokens/turn)
is the only remaining structural lever; it is a design change (per-scope sessions), so
measure-first — record doc-writer $/share per slice from M1 before deciding.
