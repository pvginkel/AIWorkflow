# The close-out report — one document per slice replaces per-finding cards (C7)

Design note, written 2026-08-15 at plugin 0.4.5, from an operator + assessment session over
Ansible slice 007's ten cards. Catalogue entry: [interventions.md](interventions.md) §6 C7;
state: [status.md](status.md) C7; implementation: [close-out-plan.md](close-out-plan.md). This
note stands on its own — a fresh session can implement from it plus the plan without the
conversation that produced it. **Revisions since (2026-08-17, plugin 0.5.3 → 0.6.0; see
`CHANGELOG-workflow.md`):** every entry closes with three bold labels — `**Consequence:**` (a line
of its own, written for triage), `**Provenance:**` (opening `witnessed` or `read`),
`**Disposition:**`; a strike names the commit and what was re-run; and the report is
**tool-written and rendered** — `close_out.py append | note | strike | list | render`, no agent
edits the file by hand, the driver renders live-first / Bugs-by-severity / struck-folded before
the doc phase and at completion. §4 below is the 0.5.0 shape as decided; the template doc is
current.

**The change in one paragraph.** Every observation a plan or run agent has that is *out of scope
of the loops' own action* — a bug it will not fix, a thing the operator must do, an event that
deviated from an uneventful run, a question it does not need answered to proceed, an idea — goes
into one document in the slice folder, `close-out.md`, in one fixed shape, as it happens. Nothing
from a run is carded per finding any more; the loop's only tracker output is one card per slice
pointing at the report. The operator reads the report when the slice is done, writes a disposition
under each entry, and an interactive session executes those (card, fix, fold into a slice, close,
defer). What is left is triage's input. End game, not now: an automated triage pass over the
report after the run.

---

## 1. The problem, on the evidence

### 1.1 Ansible slice 007 — ten cards (615–624) from one run

The run collected eleven entries in `state.json["cards"]` from five sources — code-writer P2, P3
(×2), P7 (×2), consult ×4, test-agent ×1, doc-writer ×1 — and `/dev:run-slice`'s close-out step
merged two and filed ten Trello cards. Dispositioned by hand against the sections proposed
below:

- **621** (operator prerequisites: Jenkins job, PAT, `bao kv put`, `site-openbao.yml`) — the one
  item that must not be lost: an operator runbook. Its body says *"full detail in the slice's
  `attachments/credential-inventory.md`"* — it does not stand on its own.
- **615** (KubeCoder `terraform-backend-git` sidecar answers every LOCK with 500 `user: unknown
  userid 1000`) — a genuine cross-project bug; would still become a card, on the KubeCoder board.
- **623** (should `argo-cd/phases.md` carry a shipped marker?) — a ruling request.
- **618** (D31's image-contents list is stale) — **already fixed inside the same run**: consult 1
  wrote *"absorbed beats carded"* and appended P11, which landed as AnsibleSpecs `97b5313`. The
  P7 writer's `cards` entry was already in `state.json`, and nothing struck it. Stale on arrival.
- **616, 619, 617** — two doc gaps and an input for slice 009's RBAC; one is a one-sentence edit
  the project's own `CLAUDE.md` classes as "just do it".
- **620, 622, 624** — a minor traceback-instead-of-named-cause, a nit unreachable in practice, and
  a residuals card whose second half is a stale line number in the done-record of a closed phase.

Tally: one must-act, one real cross-project bug, one ruling, one already fixed, six minor/nit/doc.
The card texts themselves were mostly competent; the cost was ten board items to open, order,
and relate to each other, with no severity and no whole-run context — where one document read in
one sitting covers it.

### 1.2 Not a 007 thing

`state.json["cards"]` counts across recent KubeCoderSpecs runs: 117 → 24 entries, 135 → 17,
107 → 16, 109 → 15, 125 → 13; the completion consult is the largest producer everywhere (117 and
107: 12 each). The research board already logs the pressure: status.md I4, 2026-08-14 —
*"slices 144+145 minted 8 advisory cards in one afternoon (2+6) … the cross-slice queue … is
visibly the active pressure point."*

### 1.3 The structural defect: five write paths, no reconciliation

Cards are decided in five places, each with its own phrasing of the rule and blind to the
others: the code-writer's verdict (`agents/code-writer.md:62` — *"out-of-scope findings worth an
issue-tracker card"*), the reviewer's advisories routed through the executor
(`docs/run-loop.md:79`), the consults' `cards` (`run_loop.py` `CONSULT_PROMPT`), the test agent
(`agents/test-agent.md:27`), the doc-writer (`agents/doc-writer.md:42`), plus driver-written
refutation and funding-merge cards (`run_loop.py` `_handle_refutations`,
`_review_funding_consult`). All funnel through `_card()` into `state.json`; the launching session
merges at the end (`skills/run-slice/SKILL.md:69-74`). The completion consult — the only agent
with the whole-slice view — makes decisions (absorb, strike, merge) that never feed back into
that list; hence 618. A small tell of the same disease: P3's writer emitted `cards` as
`[{"text": …}]`, `_card` did `str(item)`, and `{'text': "…"}` went into the record and onto card
616's source line. Side-channel schemas in five places drift.

### 1.4 What today's design loses entirely

Nothing records *what happened* in a run except `log.txt` (169 KB for 007). Uncaptured in any
card: the run bailed at 19:49 with `protocol_failure` because `git rev-parse HEAD` fails on a
fresh, commitless sibling repo — a **plugin** bug; P3 bailed `blocked` because the planned proof
venue (`srvk8sdev`) was off the wire, and the operator moved the venue to prd by ruling; P3's live
proof exposed a defect the test double was hiding (`VERIFY_X509_STRICT` on Python 3.13 against a
CA without `keyUsage`); P4 r1 blocked on a missing runtime dependency; consult 1 appended three
phases and overruled two agents' card routing. That is the R&D evidence trail, and it exists only
by reading the log.

---

## 2. Why one document with a fixed shape

Two different decisions are removed, and it matters to keep them apart.

**Routing removes the destination choice.** Today an agent that notices something out of scope
faces: card it? append a phase? fix it in place? leave it to the consult? say it in the summary?
Each is a judgment restated per agent. With the report there is one destination — *put it in the
report* — and the operator routes.

**The fixed shape removes the completion choice.** This is the nuance the routing rule alone
does not carry. An open-ended instruction ("card things worth carding") has no closure criterion:
is it worth it, how much to say, should I propose the fix, did I already say it, should I do it
instead. Fan et al. 2025 (*Missing Premise Exacerbates Overthinking*, `extracts/2504.06514`) is
the mechanism: on questions the model cannot close, it *suspects* early and then **keeps
re-visiting instead of abstaining — "detection exists; the act is missing."** Wu et al. 2024
(ProCo, `extracts/2405.14092`) is the shape of the remedy: verification against a **specific,
fill-in-the-blank condition** converges where open-ended "review and find mistakes" regresses —
the extract's sharpening is that the mechanism is *narrower than "be specific"*: it is a masked
slot with a reconstructable answer. A fixed entry shape — headline, where, what, why it matters,
provenance — turns "what do I do with this?" into a fill-in-the-blank whose completion is
visible. Writing the entry *is* the licensed act; the thought is closed. The plan-loop analogue
already validated on 144/145 is A1+A2: a forced-early checkable slot and research gated on a
*named* open question, both chosen as structural rather than numeric limits because Han et al.'s
TALE (`extracts/2412.18547`) shows numeric caps produce *more* output, not less.

**Detection is never suppressed** — the catalogue's hard constraint (`interventions.md` §8) —
and this design is that principle taken to its end. The operator's own read, 2026-08-15: *"I feel
like I've been trying to suppress this and I'm frustrated it doesn't work."* Rules whose purpose
was to limit reporting (the "worth a card" qualifiers, "a card must never cost the operator more
to triage than the fix costs to make", the test agent's "no fix proposals") come out; rules that
govern what *funds work* (B1/B2/B4, C1/C2, the generation bar, the mechanical-residue rider)
stay — they are review economics, not reporting limits (§6).

**Relation to the catalogue.** C6 (advisory-card lifecycle governance) and I4 (cards ledger)
both assume per-finding cards exist and ask how to govern and measure the queue. C7 moves the
queue off the board into a per-slice document processed at one sitting; the 0.4.4 triage rework
(intake filtering) keeps its role for what the operator defers. I4's measurement reframes as
entries-per-report and dispositions-per-report (§7).

---

## 3. The design

### 3.1 What the report is — and is not

`close-out.md` in the slice folder. **Only for what is out of scope of the plan and run loops'
own action.** If a thing is in scope it already has a home: the plan (phases, rulings,
done-records), `verification.json`, the review files, a `question` verdict that pauses the loop.
The report is not a thinking scratchpad, not a substitute for asking the operator when the run
needs an answer (a `question` verdict pauses; a report entry never does), and not a place to
restate the plan. It is the release valve for everything an agent would otherwise have to decide
what to do with.

### 3.2 Sections and what goes in each

In this order. Every entry has the same shape (§4). Every section may be empty — empty is the
normal state of most of them.

- **Summary** — a few lines: the slice and what shipped. Written last (§3.4).
- **Outstanding actions** — the operator runbook: keystrokes only the operator can make, with
  what stays open until each is done. Card 621's home.
- **Notable events** — everything that deviated from a completely uneventful run: bail-outs and
  what resolved them, appended phases and why, blocked proofs and their re-routing, defects a live
  run exposed that the suite hid, refuted findings, funding-consult merges, sessions that hit
  something odd (a `git checkout` discarding an uncommitted edit). Product *and* workflow: this is
  where plugin bugs surface.
- **Bugs** — defects the run will not fix, each with a severity: `major | minor | nit | cosmetic`.
- **Open questions and rulings** — questions for the operator that the run did not need answered
  to proceed; what turned on them; what the run did meanwhile.
- **Suggestions** — ideas, improvements, inputs for other slices, fix proposals for the bugs
  above. Anyone may propose here; the "describe the problem, never the fix" rule governs review
  files, not this section.

### 3.3 Reading aids — the operator is the reader

The report is written for the operator, first and for a while only. Prose is not limited; it is
made easy to read: a **Focus** line at the head of every section (one or two lines: what to look
at first, why it matters), ids on every entry so the operator can refer to them in one line
("card B1, close B6, fold S1 into 009"), the run's shape stamped at the top by the driver, and a
`Disposition:` line under every entry left blank for the operator's remark. Automated triage
over the report is the end game; the report's shape should not need to change for it, but that
step waits until the operator has lived with the document for a while.

### 3.4 Who writes what, when

Both loops create the file from the template at first dispatch if it does not exist (the plan
loop first, so planning can already write to it). All agents may append; the file is committed
live with each agent's own commit (staged by name, like every other slice-folder artifact).

- **plan-writer / plan-reviewer** — out-of-scope observations about the spec or the estate;
  events during planning. Not their in-scope findings and questions — those keep their current
  routes (the review file, the `questions` outcome, the interactive session).
- **code-writer** — anything out of the phase's scope it noticed; notable events in its session.
- **code-reviewer** — its advisory findings, as Bug or Suggestion entries; the review file keeps
  the full finding and stays the evidence trail. One hop fewer than today (reviewer → executor
  `cards` → state.json).
- **consults** — sub-bar findings; and the completion consult is the **only agent that
  reconciles**: it may strike an entry it absorbed into an appended phase (leaving the struck
  headline with the phase and commit named), merge duplicates it is sure of, and mark what a
  later phase resolved.
- **test-agent** — below-bar findings; live-check events.
- **doc-writer** — doc debt; and, as its last act, writes the **Summary** and each section's
  **Focus** line (it has the whole shipped diff in view; the operator had no strong preference,
  this is the assessment's pick). If the run ends before the doc phase, the operator reads it raw.
- **the driver** — deterministic entries only: refuted findings and funding-consult merges as
  Notable events, and the run header (phases planned/appended, bail-outs, rounds, test and doc
  outcomes, cost from I2's readout) stamped at close-out.

Reading the report is never a license to act on it: phase agents append only. Otherwise the
report becomes a new source of scope bleed — a writer "fixing while here" what an earlier phase
reported.

### 3.5 Lifecycle

1. Plan loop creates `close-out.md` from the template on first dispatch; planning agents append.
2. Run loop appends throughout; the completion consult reconciles; the doc-writer writes Summary
   and Focus lines; the driver stamps the header at close-out.
3. `/dev:run-slice` Job 4 files **one** tracker card — `[NNN] close-out: <slice title>` in the
   intake queue — whose body is the report's Summary, the Focus lines, and the report's path.
   That card is the "a report is waiting" marker; nothing else from the run is carded.
4. The operator reads the report and writes dispositions in place — free form; a suggested
   vocabulary is `card [board]` · `fix now` · `fold into <slice>` · `close` · `defer`. An
   interactive session — ad hoc, or the `close-out` skill (§3.6) — executes them: `card` files a
   card with the entry's text as body (already standing alone), `fix now` does the small thing or
   bails to a slice, `fold into` appends to that slice's `slice.md`, `close` strikes, `defer`
   leaves it. Git in the spec repo holds the history of the operator's remarks; the close-out card
   is archived when the report is processed.
5. What remains (`defer`, or no disposition yet) is a triage source — `/dev:triage` already
   accepts "a findings document" (`skills/triage/SKILL.md:9`); the report is one.
6. Later: an automated triage pass over the report after the session completes. Not designed
   here — one constraint set in advance (2026-08-17, from S7): it **ranks and pre-fills, never
   closes**. Sifting the Noise measured an agentic filter suppressing 0.4–2.4 % of true findings
   on mechanically checkable classes and 50–85 % on judgment/policy classes; this report is
   mostly the latter (doc drift, comment claims, anchoring questions). A cheap sort with the
   ties escalated (FrugalGPT's cascade; Shi: bias concentrates in near-ties) is the shape; the
   close stays the operator's.

### 3.6 The `close-out` skill

Small: the procedure for step 4. Its `description` is the trigger — it should say *when*: the
operator opens, discusses, or wants to work through a slice's `close-out.md`. The operator will
not necessarily invoke it by name; the description invites the session to invoke it itself. Not
`disable-model-invocation`.

---

## 4. The template

The concrete file, as the loops create it and agents extend it. Markdown with fixed headings and
one entry shape; no JSON, no YAML, no tables. Skeleton validation, if any, is a smoke check
(the section headings exist) — nothing more.

```markdown
# Close-out — slice NNN <slug>

<!-- Run header: stamped by the driver at close-out from state.json. Agents never edit it. -->
Run: <not yet stamped>

## Summary

<!-- Written by the doc-writer as its last act: a few lines on the slice and what shipped.
     Until then, blank. -->

## Outstanding actions

Focus: <!-- doc-writer: what the operator must do before the slice's outcome holds -->

<!-- The operator runbook. One entry per keystroke only the operator can make: what to do,
     why it is owed to the operator, what stays open until it is done. -->

## Notable events

Focus: <!-- doc-writer: the shape of the run — bail-outs, appended phases, surprises -->

<!-- Everything that deviated from a completely uneventful run — product and workflow. What
     happened, when, how it resolved, what it says. The driver appends refuted findings and
     funding-consult merges here itself. -->

## Bugs

Focus: <!-- doc-writer: the worst one first; which are in this slice's repos, which elsewhere -->

<!-- Defects the run will not fix. Severity in the headline: major | minor | nit | cosmetic. -->

## Open questions and rulings

Focus: <!-- doc-writer -->

<!-- Questions the operator should settle that the run did not need answered to proceed. What
     turned on it, what the run did meanwhile. A question the run DOES need answered is a
     `question` verdict, not an entry here. -->

## Suggestions

Focus: <!-- doc-writer -->

<!-- Ideas, improvements, inputs for other slices, fix proposals for the bugs above. -->
```

**Entry shape** — the same in every section; the id prefix is the section's letter (`A`, `N`,
`B`, `Q`, `S`), numbered in order of arrival:

```markdown
### B2 — <headline: one line, the claim itself> · minor · <repo or component>

<What: the thing itself, quoted where it is text or output — the sentence, the command and what
it printed, the file and lines. Why it matters: the consequence, or "none" said plainly. How it
was found. As many paragraphs as it takes; as few as it takes.>

Provenance: <role, phase, round; the artifact that holds the full record — e.g. "P3 review r1 F3
(advisory); consult 1 judged it too small for a phase">
Disposition:
```

The severity slot appears on Bug entries only. Outstanding actions read as imperatives ("Create
the `IaC/ArgoCDTools` Jenkins job"). Struck entries keep their heading, struck through, with the
reason appended: `### ~~S3 — D31's image-contents list is stale~~ — absorbed by P11 (97b5313)`.

**The header the driver stamps** (one block, plain lines):

```markdown
Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended) · 2 bail-outs ·
1 test round · doc phase done · $118.41 (planner 18 %, research 4 %, rework 14 %)
```

---

## 5. Rules for entries

- **Write for a reader who has only this document.** The operator must be able to make sense of
  an entry — at least at a high level — without chasing anything down. Quote liberally: the
  sentence that is wrong, the command and its output, the file and lines. Provenance ids
  (`P3 r1 F3`, `V10`) belong on the `Provenance:` line, not in the body as load-bearing
  references. This is a writing rule, not a validated one — left alone, the model gives enough
  context; the rule exists so it never decides to save words there.
- **No limit on prose, no limit on count.** Empty sections are normal; long sections are fine.
  No caps — TALE's elasticity: a tight cap produces more, not less.
- **In doubt, add it.** Nobody pre-dedups. The completion consult merges duplicates it is sure of;
  the operator merges the rest by reading. Fewer duplicates are expected simply because every
  agent reads the same file before it writes.
- **Severity vocabulary** for Bugs: `major` (a wrong result or a broken flow, unfixed) · `minor`
  (a real defect with a contained consequence) · `nit` (true, no practical consequence today) ·
  `cosmetic` (no behavioural or informational consequence — a stale line pointer). The reviewer's
  own `Blocker/Major/Minor` never reaches the report: a Blocker gets fixed.
- **`Disposition:` is the operator's line.** Free form. Agents leave it blank; the interactive
  session executes what it says and may rewrite the entry's fate (struck, moved) but not the
  operator's words.
- **Append only** for phase agents; **reconcile** is the completion consult's; **stamp** is the
  driver's; **dispose** is the operator's.

---

## 6. Gates removed, gates kept

Removed — their purpose was to limit reporting:

- `run-loop.md` — *"A card must never cost the operator more to triage than the fix costs to
  make."*
- `agents/code-writer.md` verdict — `cards: "out-of-scope findings **worth** an issue-tracker
  card"`; `agents/doc-writer.md` — `"doc debt **worth** a card"`. Everything out of scope goes in
  the report; worth is the operator's call.
- `agents/test-agent.md` rule 5 — *"No fix proposals."* Findings entries stay evidence-shaped
  (what ran, what happened, what should have); proposals go under Suggestions.
- `run_loop.py` consult carry-over — *"Already carded this run — settled, do not re-report"* →
  the report's path, read before writing, add if in doubt.
- `skills/run-slice/SKILL.md` Job 4 step 3 — the dedupe / one-per-finding / residuals-batch
  filing rules; replaced by the one close-out card.
- The `cards` field in every verdict schema, `_card()`, and `state.json["cards"]`.

Kept — they govern what funds work, not what may be said (and B1/B2/B4/C1/C2 are under
measurement; do not disturb the instrument):

- Fix rounds resolve blocking findings only; advisories are never fixed mid-loop
  (`EXECUTOR_REVIEW_FIX_PROMPT`, `run-loop.md:79`) — wording changes from "carded at close-out"
  to "in the review file and the close-out report".
- The generation bars and the mechanical-residue rider (fix in place; a fix is not a report).
- The reviewer's "describe the problem, never the fix" for the review file; C1 anchors; B2's
  one-sentence prose findings; C2 witness-first.
- `question` verdicts for in-scope questions — the loop pauses; that path is unchanged.

---

## 7. Hypotheses and how to read them

Stated as hypotheses; validated the way the 0.4.3 batch was (per-entry log in status.md, on the
next slices to run).

- **H1 — board load.** Cards per slice created by the run: 10 → 1. Trivially true by
  construction; the number that matters is cards the *operator* files at disposition
  (I4 reframed: entries per report by section, dispositions by kind).
- **H2 — less in-run rework.** Appended phases at generation 1 ("absorbed beats carded") and
  rework share (I2) go down, because agents stop resolving "what do I do with this?" by doing it.
  Baseline: 007 appended 3 phases, rework 13.8 %; the KubeCoder 149–153 sample's 9.3–15.7 %.
- **H3 — the operator can process a report in one sitting** without opening other files. Read
  off the operator's own dispositions: how often one is "need to look" rather than a decision.
- **H4 — workflow defects surface.** Notable-events entries about the plugin (like the empty-repo
  bail) appear, where today they live only in `log.txt`.

Kill signal: reports that are long *and* the operator stops reading them. The response is not a
cap but a better Focus line or a section split — the shape, not the volume.

---

## 8. Decisions taken (operator, 2026-08-15)

Recorded so a fresh session does not relitigate them.

- One document, one fixed shape, sections as in §3.2 plus **Outstanding actions** (added by the
  operator: "a runbook for the operator to complete").
- The report is the **only** thing carded; triage works off the document.
- **Do not limit prose or entry count**; make it easy to read (Focus lines, ids, dispositions).
- **No pre-dedup**; in doubt, add.
- Standing-alone is a writing rule; quote liberally; no link-chasing needed to understand an
  entry at a high level.
- **No JSON, no YAML, no tables**; a template document; do not go overboard validating.
- Reuse the reviewer's severity vocabulary (`major | minor | nit`), plus `cosmetic`.
- `Disposition:` is free form.
- One close-out card per slice; archived when processed.
- **Start at planning**, live-committed; but the report is *not* a scratchpad, only for what is
  out of the loops' scope, and *not* an alternative to asking questions during planning.
- Summary and Focus lines: doc-writer (operator: no strong opinion).
- A `close-out` skill exists for context, with a description that invites self-invocation; the
  operator will not necessarily invoke it.
- Funnel **all** out-of-scope findings here, including the driver's refutation and funding-merge
  entries.
- The end game is automated triage from the document; **not now** — first live with the report
  as the operator's reading surface.

---

## Appendix — what 007's report would have looked like

Reconstructed after the fact from `state.json`, `log.txt`, `consult_1/2.md`, the phase reviews
and cards 615–624 (Focus lines and header included as the doc-writer and driver would have
written them). Abridged: two Bug entries in full, the rest as headlines.

```markdown
# Close-out — slice 007 argocd_tools_presync_hook

Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9–P11 appended by consult 1) ·
2 bail-outs · 1 test round · doc phase done · $118.41 (planner 18 %, research 4 %, rework 14 %)

## Summary

ArgoCDTools is a new repo: a stdlib-Python `presync` entrypoint (`repo revision stage
namespace`) that clones the deploy repo at the SHA Argo is syncing, brings up
`terraform-backend-git`, mints an in-pod kubeconfig, applies with the clone's tfvars, then
reattaches `Released` PVs claimed by the argument namespace. Shipped with it: the `argocd-hook`
image + `IaC/ArgoCDTools` Jenkinsfile, `homelab-shared` 0.2.0 (fourth `hook.namespace`
argument), the prd `eso` AppRole's read on `kv/iac/tf-backend`, and the `argo-cd/` document set
updated to the four-argument, enumerated-leaves contract. Live-proven from this pod: apply on
three exit paths, reattach against a throwaway three-PV fixture on prd.

## Outstanding actions

Focus: three keystrokes; V10/V11/V17 stay open until they are done, and A1 gates the image tag.

### A1 — Create the `IaC/ArgoCDTools` Jenkins job
ArgoCDTools is pushed; no image can build until the job exists (jobs are hand-wired, not
declared in code). Until it builds, `homelab-shared`'s `imageTag: "1"` cannot be confirmed to
name the real first build — correcting it later costs a 0.3.0 publish (0.2.0's tarball is
immutable).
Disposition:

### A2 — Mint the fine-grained GitHub PAT and write it to OpenBao
Scope per D39/D41: state repo read-write, deploy repos read-only, `admin:repo_hook`. Then
`bao kv put -mount=kv eso/prd/argocd-hooks/git token=…`.
Disposition:

### A3 — Run `playbooks/site-openbao.yml`
Converges P6: grants the prd `eso` AppRole read on `kv/iac/tf-backend`
(`ansible/inventories/prd/group_vars/openbao.yml`, `openbao_eso_kv_paths`).
Disposition:

## Notable events

Focus: two bail-outs (one a plugin bug — N1), one blocker in review, a live proof that caught
what the suite hid (N4), and consult 1 appending three phases (N6).

### N1 — Bail-out at start: `git rev-parse HEAD` failed on the empty ArgoCDTools repo (19:49)
The sibling repo was brand new with no commits; the loop's base-taking assumed a HEAD and bailed
with `protocol_failure`. Resumed after the operator initialised the repo. Workflow defect.
Disposition:
### N2 — P2's live apply could not use the pod's `terraform-backend-git` sidecar (→ B1)
### N3 — P3 bailed `blocked` (20:45): the planned proof venue `srvk8sdev` was off the wire;
        operator ruling moved the venue to prd (throwaway fixture, cluster-scoped objects over SSH)
### N4 — P3's live proof exposed a defect the test double was hiding (`VERIFY_X509_STRICT`)
### N5 — P4 r1 blocked on a missing runtime dependency (`librados2`/`librbd1`)
### N6 — Consult 1 appended P9/P10/P11 and overruled two agents' card routing on D31
### N7 — P9's writer noted a `git checkout` discarded its own uncommitted edit mid-phase

## Bugs

Focus: B1 is the only major and lives in KubeCoder, not this slice's repos; the rest are minor
or below and all in ArgoCDTools/Charts/docs.

### B1 — KubeCoder `terraform-backend-git` sidecar cannot serve LOCK · major · KubeCoder
Every LOCK returns 500 `user: unknown userid 1000`: the sidecar image has no `/etc/passwd` entry
for uid 1000, which it runs as. No `terraform apply` can complete against it from a KubeCoder
pod — the HelmCharts deploy CLI included. Witnessed in P2; the phase fell back to an in-memory
backend to prove the flow.
Provenance: code-writer P2.
Disposition:

### B2 — presync: unparseable ServiceAccount `ca.crt` exits with a traceback, not a named cause · minor · ArgoCDTools
`kubeconfig.identity()` checks that `ca.crt` exists but not that it parses; an empty or
truncated file makes `ssl.create_default_context` raise `ssl.SSLError`
(`[X509: NO_CERTIFICATE_OR_CRL_FOUND]`, confirmed on the gate's interpreter), which is not a
`PresyncError` and escapes `__main__`'s handler. Exit is still non-zero, so the sync stays gated;
the Job log shows a Python traceback where every other input failure prints `presync: <cause>`.
Provenance: P3 review r1 F3 (advisory); consult 1: too small for a phase.
Disposition:

### B3 — presync exports an empty `stage`/`namespace` argument as an empty `TF_VAR_*` · nit · ArgoCDTools
### B4 — `docs/live-infra-access.md` understates the mounted kubeconfigs' limit · minor · Ansible (doc)
### B5 — Charts render gate binds its `args:` assertion to the render's first `args:` block · nit · Charts
### B6 — plan.md P5 done-record cites shifted line numbers · cosmetic · AnsibleSpecs

## Open questions and rulings

Focus: one ruling, on a doc convention.

### Q1 — Should `argo-cd/phases.md` carry a shipped marker?
…
Disposition:

## Suggestions

Focus: S1 is an input slice 009 needs; S2 a doc pointer; S3 was absorbed in-run.

### S1 — Slice 009's `tf-presync` ServiceAccount needs PV get/list/patch cluster-wide
### S2 — The argo-cd set names a credential inventory it gives no way to find
### ~~S3 — D31's image-contents list is stale~~ — absorbed by P11 (97b5313), struck by consult 1
```
