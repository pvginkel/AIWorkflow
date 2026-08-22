---
source: web-cognition-dont-build-multi-agents.md, web-cognition-multi-agents-followup-2026.md
paper: "Don't Build Multi-Agents" — Walden Yan (Cognition) 2025-06-12 — https://cognition.ai/blog/dont-build-multi-agents; and the follow-up "Multi-Agents: What's Actually Working" — Walden Yan (Cognition) 2026-04-22 — https://cognition.com/blog/multi-agents-working
read: full (both posts, end to end)
extracted_by: Claude Opus 5, 2026-08-22
---

**Practitioner position pieces, not research.** The 2025 post contains **zero measurements** —
argument, one hypothetical (a Flappy Bird clone), three worked examples. The 2026 follow-up
contains **three production numbers**, no baseline, no A/B, no cost or token accounting.
Cognition sells the product described (Devin). Every "we found that" is an unreported internal
comparison. **The follow-up was located and mirrored** to
`articles/web-cognition-multi-agents-followup-2026.md`; the briefing's paraphrase of it is
accurate (see *Briefing check*). Note the blog now serves from cognition.com.

## Core results

1. **The two principles (2025).** Design rules, not findings.
   - *Principle 1: "Share context, and share full agent traces, not just individual messages."*
     Copying the top-level task down to subagents is explicitly called insufficient: the
     conversation is multi-turn, the parent made tool calls to decide the decomposition, and "any
     number of details could have consequences on the interpretation of the task."
   - *Principle 2: "Actions carry implicit decisions, and conflicting decisions carry bad
     results."* Two subagents sharing the full trace still produce a bird and a background in
     different visual styles, because each action encodes unstated choices.
   - Strength claim: these are "so critical, and so rarely worth violating, that you should by
     default rule out any agent architectures that don't abide by them."

2. **The proposed alternatives (2025).** Default: **"just use a single-threaded linear agent"** —
   "the context is continuous." On overflow: **"a new LLM model whose key purpose is to compress a
   history of actions & conversation into key details, events, and decisions." This is "*hard to
   get right*", and "depending on the domain, you might even consider fine-tuning a smaller model
   (this is in fact something we've done at Cognition)." Gain is qualitative — "an agent that is
   effective at longer contexts. You will still eventually hit a limit though." No number attached
   to either.

3. **Against parallel sub-agents for writing (2025).** Multi-agent collaboration "only results in
   fragile systems. The decision-making ends up being too dispersed and context isn't able to be
   shared thoroughly enough between the agents." Blocker named as communication efficiency, which
   Yan conjectures "will come for free as we make our single-threaded agents even better at
   communicating with humans." Two cases: **Claude Code subagents** — as of June 2025 it "never
   does work in parallel with the subtask agent, and the subtask agent is usually only tasked with
   answering a question, not writing any code"; the stated benefit is that "all the subagent's
   investigative work does not need to remain in the history of the main agent, allowing for longer
   traces before running out of context." And **edit-apply models** — the 2024 large-writes-markdown
   / small-rewrites-file split was faulty because "the small model would misinterpret the
   instructions … due to the most slight ambiguities"; by 2025 edit decision and application are
   "done by a single model in one action."

4. **How the 2026 follow-up narrows it.** Headline: **"multi-agent systems work best today when
   writes stay single-threaded and the additional agents contribute intelligence rather than
   actions."** The 2025 verdict is *retained* for its target case — "Our original observations still
   hold today for parallel-writer swarms." New is a narrower admitted class: "setups where multiple
   agents contribute intelligence to a task while writes stay single-threaded." Unstructured swarms
   are "mostly a distraction"; the working shape is "map-reduce-and-manage: a manager splits work,
   children execute, the manager synthesizes and reports back."

5. **Clean-context reviewer (2026, experiment 1) — the only measured result in either post.** On
   PRs written by Devin, Devin Review "catches an average of **2 bugs per PR**, of which roughly
   **58% are severe** (logic errors, missing edge cases, security vulnerabilities)." No baseline
   arm. The design claim is **unmeasured**: "we found this technique to work best when the coding
   and review agents **do not share any context beforehand**." Reasons: same-model agents are not
   self-correlated the way one human doing both jobs would be ("They don't have egos"); the clean
   reviewer "is forced to reason backward from the implementation without the spec, and can openly
   question things which the original agent might have overlooked due to errors in user
   instruction"; and "having a clean context makes the agent smarter because of the math of
   attention" — Context Rot cited by name, the coder who "has been working for hours … quickly
   builds up a large context" while "the dedicated review agent gets to skip this extraneous
   context, only look at the diff, and re-discover any context it needs as it reads the code from
   scratch." The named failure mode is the **return path**: the coder must "properly use its
   broader context of user instructions, decisions, etc. to filter the bugs that come back", which
   "is key to preventing looping, disobeying the user, doing work that is out of scope." Verbatim
   takeaway: "clean context leads to a notable improvement in capabilities when using a
   generator-verifier loop. But clear communication and synthesis with the overall context is
   important for a cohesive experience."

6. **"Smart friend" consult (2026, experiment 2) — a reported failure plus two hand-off rules.** A
   weaker/faster primary (SWE-1.5, "950 tok/sec") calls a stronger model as a tool. Verdict:
   **"SWE 1.5 was not good enough at being the primary model for this setup to really work"** — the
   gap to Sonnet 4.5 was "too wide in exactly the places that mattered … knowing when to escalate,
   knowing what to ask", and "the quality ceiling was set by the primary." SWE-1.6 "closes enough of
   that gap that the pattern starts to pay off, but it's still not where we want it." It *did* work
   "across frontier models" (Claude and GPT in production), where "the delegation logic becomes a
   capability router rather than a difficulty escalator." Two unquantified rules: **"a reasonable
   80/20 solution is to just share a fork of the full context of the primary model"** (a curated
   subset lost more than it saved); and ask **broad** questions ("what should I do?"), letting the
   consult decide what matters — an "over-scoped" smart friend that volunteers unasked guidance
   "generally lead[s] to more interesting interactions." When the asker's context lacks a needed
   file, the correct reply "is not to make up some theories (which is often the default behavior),
   but to specifically instruct the primary model to investigate this file and ask again later."

7. **Read-only subagents are the mainstream safe class (2026).** "As a consequence of principle 2,
   most multi-agent setups in the world are limited to 'readonly' subagents … But these types of
   subagents mostly resemble tool calls rather than true multi-agent collaboration."

8. **Background (2026, unmeasured).** Devin enterprise usage grew "~8x" in 6 months; the cost
   explosion is named as the "pull" toward multi-agents — but **no cost comparison is given**. Swarm
   demos (200k-LOC browser, 100k-LOC C compiler, 10k+-iteration training-script optimisation) are
   dismissed for sharing "a property most real software doesn't: a simple, verifiable success
   criterion."

## Method and setting

No method section, because there is no study. Setting: Cognition's production coding agent (Devin)
and Windsurf, on real PR-scale-to-week-scale software work, 2025-06 to 2026-04. Models: Devin's
harness over frontier models; a Sonnet-class → Opus-class shift; SWE-1.5/1.6 (Cognition's own);
Claude and GPT paired cross-frontier. Everything is **prompted, not trained**, except SWE-1.5/1.6
and the fine-tuned compressor mentioned in 2025. Nothing open source. No task counts, no horizons
in turns, no token accounting, no held-out evaluation; the one statistic (2 bugs/PR, 58% severe) is
an operational tally with no comparison arm. Hierarchical delegation — "a manager Devin can break a
larger task into pieces, spawn child Devins … coordinate their progress through an internal MCP" —
is **live but still being fixed**, with three named defects: managers "default to being overly
prescriptive" when lacking codebase context; "agents assume they share state with their children
when they don't"; and child→manager→sibling messaging "doesn't happen by default, because models
haven't been trained in environments where it needed to."

## Relevance to P1–P4

**P1 — Context is the cost.** Both posts agree with the diagnosis and supply no arithmetic. 2026's
"pull side" names our exact situation (usage growth becoming a cost problem, multi-agent structure
floated as the answer) with no number, so it sizes nothing. The one usable structural claim is
2025's Claude Code example: a read-only subagent's value is that "the subagent's investigative work
does not need to remain in the history of the main agent" — the only place either post links
architecture to spend. Transfer gap: neither post mentions prompt caching, so their cost intuitions
are for an uncached, compacting product, not our 1.25×-write / 0.1×-read economics where re-reading
a stable prefix is cheap and *novel* reads are what cost.

**P2 — Sessions grow; the longest dominate.** The sharpest transfer. 2026's clean-context reviewer
rationale is our reviewer contract restated — skip the extraneous context, "only look at the diff,
and re-discover any context it needs" — and is claimed to *raise* detection of nuanced issues. That
supports the settled "reviewer sees artefact + acceptance criteria, not narration", and argues
against softening it to save reads. For the doc-writer (145k median, one at 438k, 192 turns, $33),
2025's prescription is explicitly *not* "split into parallel writers" but compress-and-continue:
keep one writer, shorten its history. Transfer gap: their long sessions are hours of interactive
work in a product that compacts; ours are single no-compaction tool loops, and they quantify
nothing — degradation is outsourced to the Context Rot citation.

**P3 — Every session rebuilds the same picture.** Both posts push *against* fixing this by
pre-loading curated context, and this is the pair's most decision-relevant tension. 2025 Principle 1
calls the curated hand-off the failure mode. 2026 says re-derivation is a *feature* for a verifier,
and that for a consult "a fork of the full context" beat a curated subset. Reading them together:
rebuilding the picture is waste for a **writer** (nothing is being independently checked) and
load-bearing for a **judge**. Neither measures the writer half — exactly where our 14–65 orientation
turns (≈38% of a big code-writer's cost) sit. The one supported writer-side move is the read-only
subagent as context firewall (result 7 + the Claude Code example): orientation reads happen in a
fresh context, only the conclusion lands in the writer's history.

**P4 — What smaller reads cost in grounding.** Not closed, but 2026 is the closest thing to evidence
either way. It asserts (no comparison arm) that *less* context made the verifier better, and
simultaneously that the loss is real and must be repaired on the return path — the coder filters
findings "to prevent looping, disobeying the user, doing work that is out of scope"; the smart
friend must say "go read this file and ask again" rather than confabulate. Net: cutting a judge's
context is safe *if* something holding the full picture adjudicates its output. That maps onto
instruments we already have (refuted-finding rate, rework share) and is a testable hypothesis for
us, not a citable result.

## Interventions this paper supports

- **Keep the code-reviewer's context clean and diff-scoped; do not add the writer's trace or
  narration.** Rests on result 5. Direction: no cost increase, preserved-or-better blocking-finding
  rate. Loses: the reviewer will re-raise things the writer already decided — hence the next bullet.
- **Make the filter on review findings explicit and give the filtering role the fuller picture.**
  Cognition's named failure mode is the return path, not the review. Our run loop filters
  mechanically ("blocking only"); the post argues the filter needs plan intent and acceptance
  criteria as adjudication authority or you get looping and out-of-scope work. Dispatch-prompt-sized
  change; plausibly fewer fix rounds. Loses: a writer empowered to dismiss findings can dismiss
  correct ones — instrument with refuted-finding rate.
- **Let code-writers dispatch a read-only orientation sub-agent for the 14–65 pre-edit reads.**
  Rests on result 7 and the 2025 Claude Code example. Largest P2/P3 lever the pair supports, and
  squarely inside the class both posts endorse: reading, never writing. Direction: converts the
  ≈38% orientation share of big phases from full-file reads into a returned conclusion. Loses, per
  Principle 2: implicit detail the writer would have absorbed by reading the code itself — so the
  return contract must carry file/symbol citations the writer can re-open, not just prose.
- **Give every sub-agent / consult return contract an explicit "insufficient context — read X and
  re-ask" verdict.** Rests on result 6's smart-friend rule. Costs one round when it fires; prevents
  confidently ungrounded output.
- **For the completion consult, prefer "here is everything, what should I do?" over a narrow
  question.** Rests on result 6 (broad questions; the "over-scoped" smart friend). We cannot fork a
  context across fresh sessions, but we can point the consult at the same artefacts and leave its
  scope open rather than enumerating what to check.
- **Treat the doc-writer's 438k session as a compression problem, not a parallelism problem.**
  Rests on result 2. Since we cannot fine-tune, the available form is a cheap upstream artefact (a
  per-phase change summary the doc phase reads instead of re-deriving the whole diff). Loses:
  whatever the compressor drops, which 2025 warns is "*hard to get right*".
- **Do not parallelise writers across phases.** Rests on Principle 2 and on 2026 explicitly
  retaining the 2025 verdict for parallel-writer swarms. Confirms current design; no change.

## Applicability caveats

- **Evidence weight is very low.** One production tally with no baseline is the entire measured
  content of both posts. Every claim we would act on ("clean context works best", "full-context fork
  beats a curated subset") is an internal finding with no numbers, no arm, no task count. Nothing
  here sizes an effect for us; it motivates experiments.
- **Vendor interest.** Cognition sells Devin and Windsurf and trains SWE-1.5/1.6; the 2026 post is
  partly a product announcement and closes with a sales line.
- **Models partly match.** The results that worked are frontier-model results ("Claude and GPT
  together … produced real gains") — our regime. But the smart-friend headline *failure* is about a
  weak primary, a configuration the operator has already ruled out, so that negative is
  confirmation rather than new information.
- **Task type matches, harness does not.** Devin is a long-lived interactive agent that compacts and
  carries state across hours; our loop is a chain of fresh, non-compacting headless sessions with
  files as memory. Their "context grows over hours" framing describes a session shape we
  deliberately do not have, weakening the read-across of the Context Rot argument to our ≈80k-median
  sessions.
- **The compression prescription needs training we cannot do** (2025 reaches for a fine-tuned
  compressor), leaving only the prompted/artefact form.
- **Horizon evidence is thinnest where we need it most.** Hierarchical delegation — the pattern
  closest to our ≈30-session slice — is described as live but not yet coherent, with three unsolved
  defects, and is filed as "upcoming work in 2026".

## Briefing check

The note — that a 2026 follow-up "narrows this to 'writes single-threaded; extra agents add
intelligence, not actions'" — is **accurate and near-verbatim**. Found: *Multi-Agents: What's
Actually Working*, Walden Yan, 2026-04-22, https://cognition.com/blog/multi-agents-working, which
states: **"multi-agent systems work best today when writes stay single-threaded and the additional
agents contribute intelligence rather than actions."**

Two refinements the note does not carry:

1. **It is a narrowing of what is allowed, not a retraction.** The 2025 verdict is explicitly kept:
   "Our original observations still hold today for parallel-writer swarms."
2. **"Intelligence, not actions" covers three shapes, one of which is not read-only.** The
   clean-context reviewer and the smart-friend consult are non-writing, but the third — a **manager
   Devin spawning child Devins** that do write — is presented as live in production. So the
   follow-up does admit a hierarchy of writers, provided each write is single-threaded within its
   scope and a non-writing manager owns synthesis ("map-reduce-and-manage"). A briefing that reads
   "extra agents are read-only" would overstate the 2026 position; "one writer per scope, with a
   manager who does not write" is the accurate form.

Otherwise safe to use. Both posts are argument, not evidence: carry them as design precedent from a
large production deployment, and attribute no effect size beyond "2 bugs per PR, ~58% severe, no
baseline."
