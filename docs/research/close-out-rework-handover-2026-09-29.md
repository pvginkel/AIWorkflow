# Close-out rework — hand-over (2026-09-29)

**Status: superseded in part on 2026-09-29.** The plan this hand-over serves was replaced, before
it was ruled, by [close-out-triage-plan-2026-09-29.md](close-out-triage-plan-2026-09-29.md);
read that one in place of item 2 below. § 3, and what § 1, § 2, § 4 and § 9 say of 0.9.57,
0.9.58 and D1–D4, describe the sorter plan and are no longer the next work. § 5 to § 8 hold:
where the code is, the scratch data, the corpus check, the rules of the house.

For the session that picks this work up. It says where the work stands, what the operator has
and has not ruled, and what the session that wrote the plan knew and did not put in it. It does
not restate the plan or the read. Read in this order:

1. this document;
2. [close-out-rework-plan-2026-09-29.md](close-out-rework-plan-2026-09-29.md) — the design
   (§ 2), the decisions that are the operator's (§ 4), the build (§ 5);
3. [close-out-read-2026-09-28.md](close-out-read-2026-09-28.md) § 6–8 and the appendix — the
   evidence and the sorting rules that were tested;
4. `docs/AUTHORING.md`, then the files of § 5 below.

## 1. Where it stands

| commit | what | pushed |
|---|---|---|
| `52e7f95` | the read, its tool and its data | no |
| `5f3be47` | 0.9.55, another session's (`/dev:close-out` leaves the slice card alone) | no |
| `2cdf7db` | the rework plan; `close_out_readout.py order` | no |
| `3d3c4a0` | **0.9.56** — R2 and the author side of R3 | no |
| this commit | this hand-over; the replayed sorting brief under `docs/research/data/` | no |
| `b36ed3c` | the label data of the discussion of 2026-09-29 and its brief | no |
| the commit after it | the triage plan; the status lines here, in the read and in the superseded plan | no |

`origin/main` stood at 0.9.54 (`18d047b`) on 2026-09-29. Fetch before trusting that: the
operator pushes from the pod between sessions.

**Built (0.9.56).** The doc-writer strikes an entry its own commit resolved whole and notes one
it resolved in part; its dispatch carries `strike`; a round that passed is not a Notable event
(test-agent register, section charter); `close-out.md` no longer says only the completion
consult strikes. `kc project test` and `kc project lint` were green at the commit.

**Not built.** 0.9.57 (the new shape, the sorter, the skill, the Focus lines gone) and 0.9.58
(the driver dispatches the sorter). No file of either has been touched. *Superseded: they will
not be built as described; the versions and their content are the triage plan's § 6.*

## 2. What the operator has said, and what they have not

Their words, in order:

> If I ask for a fast close out, or advise during close out, I get quite different rulings from
> what's suggested in the close out report. Why is this, and can this be leveraged to trim it
> down, possibly using a post processing step? … I find the reports laborious to go through, so
> if we can improve them, all the better.

> I like the changes that are suggested here, and I would like this session to actually deliver
> them.

> If we do this, I think the format of the close out report should change also. It goes from
> important -> not important -> important -> not important -> important, etc. A's, N's, major
> B's, minor B's, nit B's, and then S's are just unsorted. Can you also design a more radical
> rework of the close out report so that it structures the information better? I would like you
> to design a plan that includes the recommendations you made (all of them), and this new one.

**Ruled:** the four recommendations of the read are wanted, all of them. 0.9.56 was built on
that.

**Not ruled:** the plan itself, and its decisions D1–D4 (plan § 4). The plan was presented with
"say go to build with the defaults"; the operator's next message asked for this hand-over. Do
not read that as a go. Open with the four decisions and their defaults, and build on the answer.
*Superseded: the operator discussed the read instead; what they said and ruled on 2026-09-29 is
the triage plan's § 2, and the decisions to open with are its § 5.*

## 3. The order of work for 0.9.57 and 0.9.58

*Superseded with the plan it orders. What carries over to the triage plan's build: fetch first,
the contract before the code, one Opus sub-agent briefed from text that exists, the corpus
check among its verify commands.*

The plan's § 5 lists the files. The order that keeps the code sub-agent briefed from text that
exists:

1. `git fetch origin`; take the version from `origin/main` and the local commits above it.
2. Write the contract first: `docs/close-out-template.md` (skeleton, entry, rendered order,
   sheet), then `docs/close-out.md`. The tool's brief quotes them.
3. Brief one Opus sub-agent for `tools/close_out.py` and `test_close_out.py` (§ 4 and § 5 here,
   plan § 2.6), with the corpus check of § 7 as one of its verify commands. Review its diff.
4. Write `agents/close-out-sorter.md` and rewrite `skills/close-out/SKILL.md`.
5. The Focus lines leave `agents/doc-writer.md`, the doc phase's prompt and
   `skills/run-slice/SKILL.md` Job 4; the code half (prompt text, two tests) goes to the
   sub-agent.
6. Run the sorter against the replay (§ 7). If it keeps clearly less than the replay did, the
   definition lost something the brief had: compare the two texts before changing a rule.
7. Changelog, `plugin.json` (version, and "Ships 10 agents" in its description), `README.md`,
   `CLAUDE.md`, `docs/rationale/overview.md` (the agent count), `docs/rationale/reporting.md`.
   Commit as 0.9.57.
8. 0.9.58: the driver. Contract docs (`run-loop.md`, `runner-state.md`, `agent-dispatch.md`)
   and the brief together, then the sub-agent on `run_loop.py` and `test_run_loop.py`.

## 4. Settled in the session, not written in the plan

**Buckets.** Eight, fixed in the tool. The read and its data call two of them by other names:
`moot` is *already done*, `needs-eyes` is *needs your eyes*. Precedence when sorting (the first
that fits): already done, action, fold, fix now, test gap, card, needs your eyes, close. Order
when reading: your actions, needs your eyes, card, fix now, fold, test gaps, close, already
done.

**The `Proposed:` line.** `**Proposed:** <bucket> — <why>[; by <who>]`, between `Provenance:`
and `Disposition:`. A second proposal for the same entry replaces the first — it is the
sorter's line, not a history; the close-out session uses that after its check of what moved.
`fold` names its slice in the why-clause.

**`propose`.** One call, lines on stdin, `<id> | <bucket> | <why>`. Every id and bucket is
checked before anything is written; an error names the line, so the sorter corrects in one
turn. It validates its input, not the report.

**The fold.** It wraps everything between the heading and the first label, dated notes
included, in `<details><summary>body</summary>`. The three labels, the proposal and the
`Disposition:` line stay outside. `render` takes the fold off an entry that moved to a bucket
read in full, and puts it on again where it belongs: unfold every live entry, then fold. A note
added after a render lands above `Consequence:`, outside the fold, and is folded in by the next
render. The struck fold (`FOLD_OPEN`) stays as it is and is never taken off.

**The record.** A live Notable event whose Consequence text opens with "none" (`^none\b`,
case-insensitive — the read's `consequence_none`) goes to the record as its heading with the
body folded. It gets no sheet line and the sorter is not asked about it; the sheet counts them
in one sentence. It is not struck: the operator can still rule on it, and closing the card
closes it like any blank entry. The driver's own entries open with "none the loop acts on" or
"none in this run", so they land there. The rule is for kind N only: an Outstanding action
whose Consequence says "none in this run" (the push-hold entries) stays an action.

**Unsorted.** The section `append` writes to, created when absent, standing directly under the
sheet. Before the sort it holds everything live, in the mechanical order. After it, what
arrived late — which the skill has sorted when it opens.

**Grades apply to every kind.** `append --severity` was never limited to Bugs and authors use
it: 420 of 522 Suggestions and 75 of 140 Notable events carry one. Inside a bucket: major,
minor, ungraded, nit, cosmetic; then kind; then id.

**The five names stay.** `append_entry`, `live_entries` and `find_by_headline` keep taking
"Outstanding actions", "Notable events" and so on, now as the kind. Both loops call them by
those strings, and the pre-run check (`assert_no_prerun_actions`) depends on it.

**The sorter.** `agents/close-out-sorter.md`, with a `description` (without one it is not
registered) and `model: opus`: dispatched from a close-out session that runs on another model
it must not inherit it — "no Fable for any role beyond the refinement-writer" is a settled
ruling. Its verdict: `{"outcome": "sorted | blocked", "summary": "…"}`. It reads the whole
report, for the groups ("one card with S4"), and proposes only where no proposal stands.

**The driver's dispatch must not go through `_spawn` as it is.** `_spawn` ends in
`_rule_on_round`, which bails the run on a protocol failure. The sort is never a reason to
stop a run: it needs a path that logs and goes on, and still leaves the `history` row
`slice_cost.py` prices a role from.

**What D2 turns over in the tests.** `test_run_loop.py`
`test_doc_phase_prompt_states_diff_files_digest_verbs_and_doc` asserts the Focus sentence of
the prompt, and a test near line 1539 that the report is rendered before the doc phase — keep
that render, a run that stalls in the doc phase then leaves an ordered report.
`test_close_out.py` asserts section preambles with their Focus placeholders around lines 742
and 785.

**Not decided.** The name of the head section (`## Sheet` in the plan) and the exact wording of
the line `render` puts under a folded bucket's heading. Neither is worth a question to the
operator.

## 5. Where the code is

Line numbers are of 0.9.56 and say where to look.

| what | where |
|---|---|
| kinds, severities, the fold constants, the entry regexes | `tools/close_out.py` 103–145 |
| what every dispatch says about the report (`DISPATCH_LINE`) | `close_out.py` 103 |
| `append_entry`; `entry_counts`, `counts_line` | `close_out.py` 304; 347, 370 |
| blocks, `find_by_headline`, `live_entries`, `_find_entry` | `close_out.py` 391–495 |
| `add_note`, `strike_entry`, `list_view` | `close_out.py` 532, 565, 609 |
| `_fold`, `_render_section`, `render_report` | `close_out.py` 642–702 |
| the CLI and `verb_usage` | `close_out.py` 807–882 |
| role tables: `MODELS`, `REQUIRED_AGENTS`, `TIMEOUTS`, `VERDICTS` | `tools/run_loop.py` 127–157, 366 |
| `BAIL_STAGES`; the pre-run action check | `run_loop.py` 204; 511 |
| the completion consult's and the doc phase's prompts | `run_loop.py` 2100, 2223 |
| `_spawn`, `_dispatch_rounds` | `run_loop.py` 3383, 3413 |
| the doc phase: render, then dispatch | `run_loop.py` 5288–5320 |
| `_run`: the stage ladder, where a resume re-enters, the end of the run | `run_loop.py` 5737–5833 |
| `_render_report`, `_stamp_report`, `_summary` | `run_loop.py` 5905, 5914, 6011 |
| the plan loop's seeding of Outstanding actions | `tools/plan_loop.py` 135, 832 |
| the card's body | `skills/run-slice/SKILL.md` Job 4, step 4 |
| what triage takes from a report | `skills/triage/SKILL.md` § 1 |
| `run_phase` and its values | `docs/runner-state.md` |

Every file that names the Focus lines:
`grep -rn "Focus" plugins/dev --include=*.md --include=*.py`.

## 6. The evidence, and the scratch data it was computed from

Committed: the read, the plan, `docs/research/tools/close_out_readout.py`,
`docs/research/data/close-out-read-2026-09-28.json` (the sorts and the session coding, as ids
and buckets; the arm `heldout-v2` is the 30 reports and the revised rules), and
`docs/research/data/close-out-sort-brief-2026-09-28.md` (the brief that arm was run on).

Not committed, and gone with the pod's `/tmp`: the entries with their text
(`/tmp/close-out-entries.json`), the 99 reports as handed over (`/tmp/co/snapshots/`), the
session digests. They hold entry text from the spec repos and stay out of this repository. To
make them again:

```bash
git clone https://github.com/pvginkel/KubeCoderSpecs /work/scratch/KubeCoderSpecs
git clone https://github.com/pvginkel/AnsibleSpecs   /work/scratch/AnsibleSpecs
cd /work/AIWorkflow
python3 docs/research/tools/close_out_readout.py extract \
    /work/scratch/KubeCoderSpecs /work/scratch/AnsibleSpecs -o /tmp/close-out-entries.json
python3 docs/research/tools/close_out_readout.py snapshots -o /tmp/co/snapshots
python3 -c "import json; d = json.load(open('docs/research/data/close-out-read-2026-09-28.json')); \
json.dump(d['report_mode'], open('/tmp/co/report-mode.json', 'w'))"
python3 docs/research/tools/close_out_readout.py report   # the read's tables
python3 docs/research/tools/close_out_readout.py order    # the plan's § 1
```

The read was made at `KubeCoderSpecs` `9a3c102a` and `AnsibleSpecs` `c90d65c`. On later heads
the operator has ruled more reports and the shares move by a little; check those commits out
to get the read's numbers exactly. The session digests need the transcripts of the pods the
close-outs were held in (`close_out_readout.py sessions`); nothing in the build needs them.

## 7. Verification, as commands

**The corpus through the new tool** — the check that no entry is lost. Per snapshot, in a
scratch slice directory holding it as `close-out.md`: feed `propose` the buckets of the data
file's arms where the report has them (`moot` → already done, `needs-eyes` → needs your eyes),
`render`, `render` again. Assert: the set of entry ids is the same before and after, each once;
every body line is still there; the second render changes nothing; `counts` gives the per-kind
numbers the 0.9.56 tool gives on the untouched snapshot. The snapshots include reports from
before the entry shape held (slice 146 has headings without ids) and entries that quote
`## Bugs` inside a fence.

**The sorter against the replay.** Dispatch the agent on the 30 snapshots the arm `heldout-v2`
names, turn its proposals into one `<project>-<slice>.json` per report in the shape the brief
shows, and score them:

```bash
python3 docs/research/tools/close_out_readout.py score /tmp/co/sorter-check \
    --modes /tmp/co/report-mode.json
```

`score` knows the read's bucket names, so write `moot` and `needs-eyes` in those files. The
replay kept 93 of 104 progressed entries (89 %), 87 % on the reports ruled by the operator's own
reading, and closed 36 %. Twelve reports sorted twice landed 138 of 146 entries in the same
bucket; a difference of that size between the agent and the replay is the sort's own noise.

**One report end to end**, on a copy: `AnsibleSpecs` 029 and 032 were unprocessed on
2026-09-28 — if the operator has not ruled them since, they are the two real reports to open
the rewritten skill on. Never on the spec repo itself without the operator in the session.

## 8. Rules of the house that bite here

- **No push without the operator's word**, asked again each time. Everything above is local.
- **The version comes from `origin/main` after a fetch**, plus the local commits above it.
- **Prose is the session's own; code goes to one Opus sub-agent** on disjoint files, briefed
  with the files and the verify commands, its diff read before the commit. In 0.9.56 the brief
  described a usage line wrongly and the sub-agent corrected it from the parser: have it assert
  on what the tool renders.
- **State every claim once.** The sorting rules live in the sorter's definition and nowhere
  else; the skill says when the sorter runs, not how it sorts.
- **This repository is public.** No hostnames, tracker URLs or entry text from the spec repos.
  Eleven of the 99 reports name hosts; the plan's example is slice 202 because it names none.
- **Settled rulings this work passes close to** (`CLAUDE.md`): no hand-over stage or prose
  sub-agent in the doc phase — the sorter runs after it and reads one file; no Fable beyond the
  refinement-writer; fix rounds and wording are not relitigated.
- **The constraint of 2026-08-17 holds in every version**: the sort ranks and pre-fills, it
  never closes. Nothing is struck, filed or fixed before the operator's ruling.
- **Plugin code is stdlib-only**; the research tools need not be, and this one is.
- **What runs is the installed copy.** Nothing here reaches a run before a push and a
  marketplace update — and a slice planned on 0.9.57 cannot run on an older copy (plan § 6).

## 9. If the operator changes a default

- **D1, no fold.** `render` folds the record only. Buckets, sheet and order stay. Less code,
  the same contract but for one paragraph.
- **D2, the Focus lines stay.** They have no section to stand over once the kind sections are
  gone. The nearest form is one paragraph under the Summary; put that to the operator rather
  than choosing it. R3's "`Focus: none` over an empty section" is then owed again.
- **D3, the sort at the end of the run waits.** Stop after 0.9.57. The skill sorts when it
  opens, and the readout of plan § 7 is taken on reports sorted that way.
- **D4, needs-your-eyes leads.** One constant in the tool and the order of two paragraphs.
