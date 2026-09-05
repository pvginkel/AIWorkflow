# How the research literature was used

This doc explains how academic papers and practitioner sources entered the workflow: two research
runs, each a briefing that named the problems, a mirrored corpus, one extraction report per source,
and a catalogue in which every candidate change cites the specific finding behind it. It covers the
pipeline that built the corpus, the paper-to-rule pairs that actually landed, what the reading said
*not* to do, and the one menu of ideas drawn from outside the agent literature. What the runs
measured in the workflow's own transcripts — and the method of bars, baselines and kill rules the
catalogues were judged by — is [`measurement.md`](measurement.md); the changes themselves are
catalogued in [`improvements.md`](improvements.md) and the close-out report's design in
[`reporting.md`](reporting.md).

## Two research runs

| | Run 1 — overthinking and review economics | Run 2 — context economics |
|---|---|---|
| Briefing | [`research.md`](../research/research.md) (undated in the file; the catalogue it produced is dated 2026-08-14, plugin 0.4.2) | [`research-2.md`](../research/research-2.md), every entry resolved 2026-08-22, written from [`research-2-prompt.md`](../research/research-2-prompt.md) |
| Problems | A planner always deep-dives · B comment churn · C work amplification | P1 context is the cost · P2 sessions grow, the longest dominate · P3 every session rebuilds the same picture · P4 grounding cost of smaller reads unknown |
| Reading list | S1–S8: 18 arXiv papers (6 ★) plus the Opus effort documentation | S1–S8: 19 arXiv papers (6 ★) plus 22 web pages — the Chroma context-rot report (the seventh ★), vendor docs, engineering posts |
| Corpus | `docs/research/archive/run-1/articles/` (18 mirrors), extracts beside them; frozen | `docs/research/articles/` (41 mirrors), `docs/research/extracts/` (19 paper extracts + 6 consolidated web extracts) |
| Who read what | Six ★ papers and the effort docs read in full by the session lead; twelve papers extracted by Sonnet sub-agents against a fixed brief (`archive/run-1/extracts/README.md`) | Every source extracted by an Opus agent reading the full mirror; the seven ★ extracts checked by the session lead against the article (`extracts/README.md`) |
| Outcome | [`interventions.md`](../research/interventions.md): 25 catalogued interventions in lanes I/A/B/C/D, a W lane added 2026-08-22 from the run record | [`interventions-2.md`](../research/interventions-2.md), then the operator's action plan [`turns-plan.md`](../research/turns-plan.md) (T1–T7) |
| Shipped | v0.4.3 (I1, I2, C1, C2, A1, A2 — six entries, the same day as the catalogue), v0.4.5 (B1, B4), v0.5.0 (C7, the close-out report), v0.7.0 → withdrawn v0.7.3 (A3) | v0.9.5 (T2), v0.9.6 (T3a, T3b), v0.9.7 (T4, the phase digest), v0.9.8 (T3a's kc half), v0.9.9 (doc-phase plan, phase 1) |
| Closed | 2026-08-22 on a 16-slice read (`interventions.md` § 12): I1, I2, I3, A1, A2, B1, B2, B4, C1, C2, D2 accepted; A5, B3, C4, C5, C8, I5 rejected; I4, C6, D3 moot | T3/T4 still `validating` at the last `status.md` entry (2026-08-23) |

**The shape of a briefing.** Both briefings have the same six sections — Purpose · Workflow
context · Observed problems · Subjects and reading list · Questions to answer · Deliverable — and
the second was commissioned in that shape on purpose. The prompt for run 2 says why: "the briefing
did three things well: it named subjects with the *specific result* we needed from each, it stated
our observed problems with numbers, and it asked questions instead of prescribing answers"
(`research-2-prompt.md`). Each subject carries a one-line *Relevance* note — the result the reading
session must extract and the problem it bears on — and the reader is told not to trust it: "do not
rely on the one-line relevance notes in this document, which exist only to orient you… you may
disagree with the framing given here" (`research.md` § Purpose). Both catalogues accordingly open
with a section titled *Where the briefing is wrong*: six corrections in run 1 (`interventions.md`
§ 2 — for instance, the S2 note on "error accumulation in long chains" cited Chen et al. 2412.21187,
whose result is redundancy, not compounding error; the claim is supported by 2502.18080 instead) and
nine in run 2 (`interventions-2.md` § 2 — for instance, "effort reaches only the output share" was
wrong: retained thinking puts effort's reach at ≈ 25 % of spend, not 18 %). The standing
constraint is in both: "Nothing gets actioned before we decide together."

Run 2 also separated the two jobs. The briefing was written by a web session with search enabled
and no repository access — "you are selecting and framing the reading and asking the questions; you
are not reading the papers in full and not proposing interventions" — and a Claude Code session
with the repo, the transcripts and the cost tooling then read the papers and wrote the memo
(`research-2-prompt.md`, its opening "How to use" note). The prompt calibrates the second author on the first run's
outcome: "the cost of our loop is context, not thinking" (`research-2-prompt.md`; repeated as the
thesis of `research-2.md` § Purpose).

## The corpus pipeline

The papers are read as Markdown mirrors, not PDFs, so that sub-agents can read full text, `grep`
works across the whole corpus, and a later reader cites the same text the catalogue cited. The
tooling lives in [`docs/research/tools/`](../research/tools/) and is research tooling — it uses
`httpx` and `python-slugify` (`tools/pyproject.toml`), which the repo's `CLAUDE.md` permits: "All
workflow code is stdlib-only. That limitation does however not apply to that written purely for
analysis and research."

- [`arxiv_to_md.py`](../research/tools/arxiv_to_md.py) converts one paper: arXiv API for title,
  authors and abstract; `/e-print/<id>` for the submitter's LaTeX tarball; `latexpand` to flatten
  `\input`/`\include` and inline the `.bbl`; `pandoc` to GitHub-flavoured Markdown through
  [`cleanup.lua`](../research/tools/cleanup.lua). References survive because the `.bbl` is inlined
  (or citeproc renders the `.bib`) — "which a default conversion does not manage." Output is
  `<arxiv-id>-<title-slug>.md`; PDF-only and non-LaTeX submissions "are reported and skipped rather
  than faked."
- `cleanup.lua` trades LaTeX structure for grep-able prose: a figure that cannot survive the trip
  becomes `*Figure: <caption>*` — "a link to a file we never copied is worse than no link at all."
- [`fetch_articles.sh`](../research/tools/fetch_articles.sh) runs the converter over every arXiv
  paper cited in `research-2.md`, keyed by briefing section (S1–S7 — S1's Chroma report, S7's vendor
  docs and S8's practitioner posts are web pages, `fetch_pages.sh`'s), skipping already-converted
  ids; `--force` rebuilds. It needs `uv`, `pandoc` and `latexpand`, the last two dropped onto `PATH`
  by hand because the toolchain container no longer ships them. Run 1's corpus is frozen under
  `archive/run-1/` and deliberately not re-fetched.
- [`fetch_pages.sh`](../research/tools/fetch_pages.sh) mirrors the non-arXiv sources as
  `web-<slug>.md` in two modes: `md` for pages that serve raw Markdown at a `.md` URL (the
  `platform.claude.com` and `code.claude.com` docs, whose HTML "is JS-rendered and empty to curl"),
  `html` through pandoc for the rest.

**Extraction.** One report per source, same basename as the mirror, written to a fixed brief.
Run 1's brief: **Core results**, **Relevance to A/B/C**, **Supported interventions**,
**Applicability caveats**, **Briefing check**. Run 2's: **Core results** (effect sizes, models,
table and section citations), **Method and setting**, **Relevance to P1–P4** "with the transfer
gap to our loop stated", **Interventions this paper supports**, **Applicability caveats**,
**Briefing check** — "whether the paper supports the one-line relevance note research-2.md filed
it under" (`extracts/README.md`). The Briefing check is where the corrections in the catalogues'
§ 2 came from. Front matter records provenance: run 1's `starred: true` / `extractor: "session
lead, full in-context read"`; run 2's `read: full` or `read: partial` (SWE-agent and
Context-Folding were read only in the sections the briefing named) and `extracted_by`. Both READMEs
carry the same warning: "Extracts compress; when a claim is load-bearing, verify it against the
mirror" (run 1's says "the article mirror").

**Conversion caveats, recorded rather than hidden.** The LaTeX→Markdown path "drops some tables
silently"; `extracts/README.md` names five affected papers (2505.06120, 2512.24601, 2601.16746,
2605.14563, 2606.29718) whose numbers the agents recovered from arXiv's HTML rendering where
load-bearing, and two (2509.23586, 2510.00615) converted from the HTML rendering outright. The
PEEK extract's own front matter records the same loss for 2605.19932 — "every figure below is
quoted from prose" — so the README's list is one short. Run 1 had one paper the briefing could
not pin to a URL (Shi et al., position bias); the reading session located and mirrored it as
2406.07791 (`interventions.md` header).

## Paper → rule

Each row is a finding the catalogues cite and the rule it grounded. Versions are where the rule
landed in the plugin (`../../CHANGELOG-workflow.md`); catalogue ids (I1, C2, P3.1, T4) are the
entries in `interventions.md`, `interventions-2.md` and `turns-plan.md`. Rows marked *rejected*
or *parked* are grounded proposals the record closed; they are here because the paper was read
and its finding used to decide against.

| Paper (arXiv) | Finding used | Rule or change | Where it landed |
|---|---|---|---|
| Huang et al., *LLMs Cannot Self-Correct Reasoning Yet* (2310.01798) ★ | Intrinsic self-correction flips correct answers to incorrect more often than the reverse; external feedback — test execution — is the only setting where correction reliably works | **C2** a fix round witnesses the failure before changing code; a finding it cannot make fail is refuted. **B1** comments may state only what code, a test or a gate can witness — "models cannot reliably judge unverifiable claims — verdicts on them are noise". **C3** round caps kept, not loosened. Left-field sets aside author self-review on the same result | C2 v0.4.3; B1 v0.4.5; C3 decision record; v0.5.4 makes the consult "the one in-run judge of other agents' entries" |
| Wu et al., ProCo (2405.14092) | Verification against a specific, checkable condition cut wrongly-overturned correct answers from 9.1 % to 2.5 % while keeping true-error fixes; exact-match checking misclassifies correct-but-differently-worded answers | **C1** closed anchor list for a `blocking` finding; **B4** a prose finding must show the text is *wrong*, not differently worded; **C7** a fixed entry shape — "a masked slot with a reconstructable answer" — for the close-out report | C1 v0.4.3; B4 v0.4.5; C7 v0.5.0 (`close-out-report.md` § 2) |
| Sharma et al., sycophancy (2310.13548) | Models wrongly admit a mistake on 42–98 % of answers they had right when challenged confidently; a preference model preferred convincingly argued wrong answers 95 % of the time | **C2** turns producer–reviewer disagreement "from a sycophancy contest into an executable dispute"; **D2** the reviewer and consult see the artifact and the acceptance criteria, never the coder's narration; the close-out skill answers a disposition from the entry's own Provenance "instead of agreeing" | C2 v0.4.3; D2 accepted; v0.5.4 |
| Wataoka et al., self-preference (2410.21819) | Judge preference tracks how familiar the text is *to the judge*, nearly identically whether or not the judge wrote it | **D1** register/session separation does not neutralise stylistic bias between an Opus writer and an Opus reviewer — so wording findings are structurally low-information (**B4**), and the answer is the strongest model grounded in external evidence, not a weaker-but-different reviewer; Focus lines rank "never on length" | B4 v0.4.5; D1 insight; v0.5.4 |
| Xu et al., *Pride and Prejudice* (2402.11436) | Perceived quality rises for ten self-refinement iterations while human-rated quality stays flat; bias grows with candidate-pool size | **C3** the round caps and rising funding bar recorded as endorsed "so the caps aren't loosened in a future 'more review = better' mood"; cautions any best-of-k | Decision record (`interventions.md` § 6 C3) |
| Shi et al., position bias (2406.07791) | Position consistency collapses as the quality gap between candidates → 0 (consistency scores ≈ 0.23–0.89 across judges in the extract) | **A4** an upfront difficulty grader "lives entirely in that regime" — keep rejecting complexity routing; **D3** order swap and majority vote for any future selection step | A4 decision record; D3 rejected (dormant, "no selection step will be built") |
| Saito et al., verbosity bias (2310.10076) | Direction is task-dependent — treat as "length distorts judgment", not "longer always wins" | Length normalisation in D3; the doc-writer's Focus lines rank on Consequence and evidence class, never on length | v0.5.4 |
| *Are LLMs Reliable Code Reviewers?* — overcorrection (2603.00539) ★ | 48.2 % of wrong rejections are unfalsifiable "logic error" claims, 14.1 % hallucinated requirements, 13.2 % asserted boundary errors — 87 % would fail an anchoring bar; a fix-guided verification filter cut false rejection by 30–67 points at ≤ 2.5 points added false acceptance; more elaborate review instructions moved GPT-4o's false-negative rate from 26 % to 73 % | **C1** anchoring taxonomy; **C2** demonstrate-failure-first; **D2** keep the reviewer register lean — every addition A/B-checked against finding precision; the close-out **evidence class**: symptom claims hold (93–100 %), cause attributions are the half that does not (44–75 %), so `Provenance:` opens `witnessed` or `read` | C1, C2 v0.4.3; D2 accepted; v0.5.4 |
| *Sifting the Noise* (2601.22952) | An agentic validator with repo access cut residual false positives 98.3 % → 6.3 % while static prompting with oracle context did nothing; judgment/policy finding classes suffered 50–85 % true-positive suppression | **C5** validator before fix rounds, gated to mechanically checkable anchors only — *rejected* once blocking precision read 15/15 (`status.md` I3); **B2**'s narrowing carve-out; "an automated triage pass over the report ranks and never closes" | C5 rejected 2026-08-22; v0.5.4 (constraint, not built) |
| LLM4FPM (2411.03079), via Johnson et al. 2013 and Christakis & Bird 2016 | Practitioners abandon analysis tools past roughly a 20 % false-positive rate | **I1/I3** blocking precision as the tracked number, target ≥ 80 % | I1 v0.4.3; I3 accepted, answered by C2's refute path |
| Fan et al., *Missing Premise Exacerbates Overthinking* (2504.06514) ★ | On questions it cannot close the model suspects early and then keeps re-visiting instead of abstaining — "detection exists; the act is missing" | **A1** the plan-writer declares its task shape in a contract slot *before* investigating — the slot is the licensed act; **C7** one destination and one fixed entry shape remove the routing and the completion decision an agent otherwise re-litigates | A1 v0.4.3; C7 v0.5.0 |
| Han et al., TALE (2412.18547) | A 10-token budget produced more tokens than a 50-token one — numeric caps backfire | **A2** research is gated on a *named* open question, "deliberately no token cap"; the close-out report's limits are "structural, never numeric" | A2 v0.4.3; C7 v0.5.0 |
| Cuadron et al., *The Danger of Overthinking* (2502.08235) ★ | Two low-effort samples plus selection matched one high-effort run at 57 % of cost — but o1-*low* scored 35 % *higher* on overthinking than o1-high in agentic settings | **A3** the effort step-down trial, with the counter-finding as its pre-registered kill criterion: "if `high` sessions run longer or spend more than `xhigh` ones, the trial self-refutes early" (`a3-plan.md` § 5); **A5** best-of-k plans | A3 v0.7.0 → withdrawn v0.7.3 (saving ≤ 1 % against a witnessed ≈ 4 % rework strike); A5 rejected |
| Gema et al., *Inverse Scaling in Test-Time Compute* (2507.14417) ★ | Models misjudge difficulty from surface framing; Claude models degrade with irrelevant material in scope | **A1**'s declaration must rest on checkable slice.md facts, not felt complexity; **A4**; **D2** context hygiene; run 2's **P4** — curated context "may *improve* judgment, not just cost" | A1 v0.4.3; `research-2.md` P4 |
| FrugalGPT (2305.05176) | Cascades stop on a learned confidence proxy, not verified failure; cost/quality rankings invert across datasets | **A4** difficulty is not a stable property of the request; any cascade here conditions on real outcomes (gates, verdicts) | A4 decision record |
| Chen et al., *Do NOT Think That Much* (2412.21187); *Thinking-Optimal Scaling* (2502.18080) | Later rounds are redundant, not wrong (> 92 % of the time the first solution was already right); erroneous rounds grow with chain length; excess effort hurts on easy tasks | The briefing's S2 note corrected; **I2**'s cost readout modelled on Chen's outcome-efficiency diagnostic; A3 evidence | `interventions.md` § 2; I2 v0.4.3 |
| Opus effort documentation (S8, vendor) | "use low and medium liberally … wherever your evals show quality holds"; `high` is the default | A3's premise — read, weighed, and the trial built with kill criteria rather than adopted | A3 v0.7.0 / v0.7.3 |
| PEEK (2605.19932) ★ | A constant-size, prompt-resident context map lifts success +6–20 % with iterations at or below baseline; a frozen map still wins; "presence matters more than size"; a retrieval-built map gained only +4.9 and mid-run regeneration lost 14.9 | **P3.1 → T4** the driver renders a phase-scoped **digest** into every code-writer dispatch instead of "read the whole plan". The memo also corrects the briefing: PEEK never mapped a context that mutates between runs, so the digest is *derived* per dispatch, never an authored per-repo map | v0.9.7 |
| Agent Workflow Memory (2409.07429) | Seven tiny, verified workflow items per site cut steps 25 % at higher success; unverified items degrade | **P3.2** deliver known frictions at the point of use, small and verified, never in the prefix | T3b (`close_out.py` accepts the report path) v0.9.6 |
| Laban et al., *LLMs Get Lost in Multi-Turn Conversation* (2505.06120) | A single consolidated instruction retains 95 % of full performance; the same information split across turns loses 39 % | The hand-off — digest or compaction — "must be a consolidated restatement, not a delta" | T4 v0.9.7 (one rendered block); P2.2 (not taken) |
| MemDocAgent (2605.14563) | Per-unit documentation work in script-computed order with an external consistency check: cross-document inconsistency 13 % → 3 %, read time −41 % | **P2.1** a bounded doc phase of units plus a reconcile pass — "the consistency check MemDocAgent puts outside the model". The memo notes the paper's "one trajectory" framing is rhetoric: each unit is a refreshed ≤ 10-step sub-task, so it is evidence *for* the split | Phase 1 v0.9.9; the coordinator-and-units split built as v0.9.14, read on nine slices — ≈ 2x per phase of shipped work at matched size — and reverted as v0.9.29; the reconcile pass survives in the single writer (`doc-phase-read-2026-09-04.md` § 5–6) |
| SWE-Pruner (2601.16746) ★; SWE-agent (2405.15793); Context-Folding (2510.11967) | Every untrained read-shaper lost resolve rate with Claude Sonnet 4.5 (RAG 50, summarise 56, LongCodeZip 54, LLMLingua2 54 vs 62 unshaped; only the trained goal-hinted skimmer won, 64 at −31 % tokens); SWE-agent's window ablation is two-sided (30 lines 14.3, 100 lines 18.0, whole file 12.7); at 10× smaller context truncation loses −19/−12 points, summarisation −9/−6, folding −6/−6 | "Curated and smaller are different treatments, and the only safe mechanical cut is of *irrelevant* material"; **P4.3** shaped tool output "evaluate, do not assume"; compaction of writer/reviewer history is *deliberately not in the memo* | `interventions-2.md` § 2 item 3, § 6 |
| ACON (2510.00615) | The learned compression guideline, as the memo condenses it: "keep every endpoint, parameter list, raw rows, all positive matches; never replace machine-readable data with prose"; omissions found from full-succeeds/compressed-fails pairs | What a hand-off must carry — settlements and `file:line` evidence in machine-readable form; the failure-pair method proposed as the offline check for the digest | `interventions-2.md` § 3 P2.2, § 6 |
| Kim et al., *Towards a Science of Scaling Agent Systems* (2512.08296) ★ | Coordination goes net-negative once a single agent already exceeds ≈ 45 %; on SWE-bench Verified every multi-agent variant loses; 1.6–6.2× tokens; orchestrator synthesis cuts context omission 67 % versus concatenation | No orientation sub-agents for the code-writer (a gate-verified, high-baseline role — the digest is the cheaper form); per-surface units plus a verifying pass are the supported shape; "sub-agents everywhere" not supported as framed | `interventions-2.md` § 2 item 5, § 3 P3.3, § 4 Q3 |
| MAST, *Why Do Multi-Agent LLM Systems Fail?* (2503.13657) | Information withholding (0 % in successful traces), derailment, premature termination; a return should carry the constraints the parent's next action depends on, marked verified-vs-asserted | **P3.3** the sub-agent return contract — the evidence behind "delegate the reading, keep the judgment": sub-agents "hand back receipts and conclusions, never evidence" (`agent-dispatch.md` § Nested delegation); the Explore model pin **parked** on size, $1.60 a slice | `agent-dispatch.md`; T7 parked (`turns-plan.md`) |
| Kapoor et al., *AI Agents That Matter* (2407.01502) ★ | A mis-measured baseline (75.0 that reproduced at 89.6) exceeded every agent's claimed gain; compare on the quality/dollars Pareto, ≥ 5 runs, hold out what you tuned on | **P4.2** the A/B protocol and kill signal for any smaller-or-curated read — one variable per trial, fixed plugin version, model, effort and prices, quality instruments outside the baseline range on two consecutive slices kills it | `turns-plan.md` protocol; `t4-read-2026-08-23.md` |
| Chroma, *Context Rot* (technical report) ★; Xia et al. (2606.29718) | Claude's overload failure is abstention — the focused-vs-full gap on LongMemEval is largest for Claude; a cheap judge classifies give-ups at 98.7 % agreement | A new quality instrument: count "cannot determine" verdicts. The baseline read found **0 hard and 4 soft abstentions across 4 of 32 slices** — "Abstention is essentially not a thing in this corpus" | `abstention-baseline-2026-08-23.md`; T4's quality check |
| Sinha et al., *Illusion of Diminishing Returns* (2509.09677) ★ | A fresh context pays for what the old one *contains*, not its length (self-conditioning on earlier errors) | Session cuts evaluated on growth alone, on the real trajectories (`--what-if`): pays only for the doc-writer (≈ 20 %) and the writer/test tail, ≈ 0 for reviewers | `interventions-2.md` § 2, caveat 3 |
| Li Z. et al. (2407.16833), Li X. et al. (2501.01880) — RAG vs long context | Long context beats retrieval by 4–13 pp on QA; 63 % identical predictions, errors included — agreement with the full read proves nothing | No retrieval layer over plans or diffs: "our agents already *are* the retriever (grep + sed windows)" | `interventions-2.md` § 4 Q4, § 6 |
| SWE-Effi (2509.09853); Majgaonkar et al. (2511.00197) | Trajectory length separates failure from success weakly; variance and wrong-file edits are the sharper signals; SWE-agent's most expensive failures ran under a hard cap | No turn or token caps as early stops (**P2.3**); trajectory-length *variance* as the early A/B signal | `interventions-2.md` § 3 P2.3 (both papers), P4.2 (Majgaonkar) |
| Anthropic engineering posts; Claude Code docs; Cognition's *Don't Build Multi-Agents* and its 2026 follow-up (practitioner, S8) | The research harness cut wall-time up to 90 % with 3+ tools per turn; Cognition's single-threaded rule concerns writes, not reads; `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and the costs page's "disable unused servers"; the harness post's progress-file hand-off | **P1.1** batched reads (folded into T4 when `batchable(strict)` read 8.1 % against a 15 % bar); **P1.2** trim the fixed prefix — ≈ 23 KB of listings headless roles never use; the progress-file hand-off is **P3.1**'s practitioner precedent for the digest — "a progress file + git log is how a fresh session gets its bearings" | T3a v0.9.6 (env vars), v0.9.8 (`--disable-slash-commands`, `--strict-mcp-config`); P3.1 → T4 v0.9.7 |

## What did not transfer, and what was set aside

**Settled, do not re-open** (`research-2-prompt.md` § What is settled — do not re-open, restated in `research-2.md` § Workflow context): no effort
tiering (A3: "tried, withdrawn — ≤ 1 % saving against a witnessed rework strike" — by ruling, not by
its kill rule, [`measurement.md`](measurement.md) § The research method); no upfront
difficulty routing ("a graded lane was built and retired" — A4's record explains why: difficulty is
not a stable property of the request and judges are least reliable on near-ties); no Sonnet or
weaker model as writer or reviewer ("judgment resists sway with model strength" — Sharma, Xu); no
weaker-but-different reviewer either (D1: same-model style bias is not the problem grounding in
evidence does not already solve); detection is never suppressed — findings are routed and
evidence-gated, never silenced; registers stay lean, every addition A/B'd against finding
precision (D2, from the overcorrection study's prompt-elaboration result); the reviewer sees the
artifact and the acceptance criteria, not the coder's narration; the loop stays generic; files are
the memory. Out of scope for any run: another serving stack, fine-tuning, non-Claude models,
"anything that amounts to 'think less'."

**Catalogue entries closed on the record**, each with a paper behind it and the measurement that
closed it (`status.md`, 2026-08-22):

| Entry | Grounded in | Why closed |
|---|---|---|
| A5 best-of-k cheap plans | Cuadron @k=2/3; Shi's selection protocol | Planner spend is a floor effect at $14–27 on slices 155–170; "doubling plan latency for a bounded saving has no case" |
| B3 explanatory prose moves to docs | Slice 152's 16 live comments describing a subsystem that no longer existed | Comment churn cost $0 of rework after v0.4.2; the doc phase was already 8–21 % of every slice — "moving prose there grows the costliest role to save nothing and loses locality" |
| C4 evidence-gated contest channel | Sharma (capitulation), Huang | "No capitulation event observable in 15 fix rounds… and precision reads 15/15 (I3); the channel has nothing to carry" |
| C5 agentic false-positive validator | *Sifting the Noise* | Conditional on C1+C2 under-delivering; I3's 15/15 read "is the sunset for C4 and C5" |
| C8 mutation-witnessed signoff | Slice 146 P1 F1; C1's `coverage-gap` anchor as clarified in v0.5.1 | Reviewers mutate unprompted (slice 170: P1, P6, P9, P10); "the test-only remainder the rule would bind has not shown up" |
| I5 witnessed-signoff field | Slice 146's reviews | "The behaviour is present without a field, I3 no longer needs the measurement, and a field is register prose (D2)" |
| I4 cards ledger, C6 card governance, D3 comparative-judgment toolkit | The practitioner trust-collapse literature (via LLM4FPM); Shi et al. and the S6 bias papers | Moot: the close-out report replaced per-finding cards (I4, C6); no selection step exists for D3 |

**Not proposed, with numbers** (`interventions-2.md` § 3 P1.3, P2.3, § 6): thinking clearing (4 %
of spend, and clearing breaks the cached prefix every turn); the 1-hour cache TTL (2× writes for 29
long gaps); tool-result expiry (≤ 11 % writer / 18 % doc-writer before the invalidation it causes,
and unreachable from a headless Claude Code session); cutting median writer or reviewer sessions
(≤ 8 % / ≈ 0 on the real trajectories); turn or token caps; compaction or summarisation of
writer/reviewer history; a retrieval layer; an authored per-repository map with a staleness rule;
parallel writer sub-agents (Cognition, Kim).

**Set aside inside the left-field menu itself** (`left-field.md` § Considered and set aside):
Ship/Show/Ask (the same skip-review family as #715, already answered); N-version writers ("doubles
the writer's spend; out by the selection rule"); author self-review (Huang et al.'s negative
self-correction evidence); property-based testing (a project's testing strategy, not the
pipeline's); Cleanroom ("the opposite bet to our gates, and the gates are right for us").

**The standing caveat.** The second briefing says it of its own numbers — "All numbers are one operator's
two projects over 27 slices — grounding, not law" (`research-2.md` § Observed problems) — and the
catalogues say it of the papers: every paper extract carries an *Applicability caveats* section, and the
run-2 memo's § 2 is nine items long largely because lab results, or the briefing's reading of them, moved when checked against the
corpus (P2's "50–70 turns of orientation" was the tail, max 64; the median was 14). Where the
paper's setting was far from the loop — SWE-agent's ablations on GPT-4 Turbo, whose Claude 3 Opus
sweep "did not reproduce the optimum"; the QA-only retrieval studies — the memo says so in the row
and lowers the weight rather than dropping the source.

## Outside the agent literature

[`left-field.md`](../research/left-field.md) (2026-08-29) is the one document whose sources were
not chosen to answer a named problem. Its premise: the risk-based-review question (#715) "came
from a Martin Fowler post, not from the reading list — and it was worth the research even though
the answer was no"; the pipeline "is a review-and-inspection process with a queue, and those have
been studied for fifty years." An idea qualifies if it "(a) comes from outside the LLM-agent
literature, (b) maps onto a specific role or seam of the pipeline, and (c) can be decided by a
measurement we can actually take." Each entry carries *Background*, *Here*, *Worth it because*,
*Decides it* and *Cost*.

| # | Practice and source | Where it lands |
|---|---|---|
| 1 | Seeded defects / bebugging (Mills, IBM 1970s); capture–recapture (Briand, El Emam, Freimut & Laitenberger 1997/2000; Petersson et al. 2004) | Plant k defects in shipped phase diffs, dispatch the code-reviewer offline, score catch rate by defect type — the first measurement of what the reviewer *misses*; the yardstick #4 and #5 need |
| 2 | Mutation testing (Petrović & Ivanković, Google, ICSE-SEIP 2018; *Practical Mutation Testing at Scale* 2021) | A mutation score on the slice's changed lines as the test phase's quality number and candidate gate; tooling stays the project's curated target, never the plugin's |
| 3 | Review-size ceiling (Cohen 2006, SmartBear/Cisco: defects per line fall past 200–400 LOC and ~60 minutes; Google's small-CLs guidance; Reinertsen 2009) | Two scatters on data already held — findings and blocking rate against phase diff size; writer turns against diff size — to find a knee that would give the plan-writer a numeric phase cap |
| 4 | Reading order (Baum, Schneider & Bacchelli, ICSME 2017; FSE 2022 *First come first served*) | Order the reviewer's diff contract-first rather than alphabetically; free at runtime; decided on #1's harness |
| 5 | Perspective-based reading (Basili et al., NASA SEL, 1996) | One reviewer, one assigned lens per phase derived from what the phase is, riding the T4 digest |
| 6 | Pre-mortem (Klein, HBR 2007; Mitchell, Russo & Pennington 1989, ~30 % more reasons identified) | One paragraph in the plan-reviewer: assume the slice bailed or asked a question — name the most likely reason; measured on bail-outs, exit-4s and appended phases already recorded per slice |
| 7 | Readme-driven development (Preston-Werner 2010); Amazon's Working Backwards | Draft the manual in the plan loop, reconcile it in the doc phase — a smaller doc-phase read and a specification check for free |
| 8 | Process behaviour (XmR) charts (Shewhart/Deming; Wheeler 1993) | Judge a plugin version when the chart shifts, not when "the next four slices look lower" — proposed against the A3 pattern of shipping on one read and withdrawing, and the T3/T4 read where "median vs pooled disagree by 32 points" |
| 9 | Poka-yoke (Shingo 1986); Orthogonal Defect Classification (Chillarege et al. 1992) | For each recurring finding category (comment-prose was 43/114 on the I1 read), ask whether a deterministic gate retires it from the reviewer's plate; add ODC's *trigger* to the I1 fields to say which gate |

All nine are **untested**: "A menu, not a plan — nothing here is scheduled." The document
suggests an order — #1 first as the yardstick, #3/#8/#9 as readouts on existing data, #2/#6/#7 as
pipeline changes one at a time — and defers per-entry status to `status.md`, whose last chapter
(T4, 2026-08-23) predates the menu; none of the nine has a chapter there.
