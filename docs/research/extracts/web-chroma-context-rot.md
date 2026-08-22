---
source: web-chroma-context-rot.md
paper: Context Rot: How Increasing Input Tokens Impacts LLM Performance — Kelly Hong, Anton Troynikov, Jeff Huber 2025 (Chroma technical report, July 14 2025) — https://research.trychroma.com/context-rot
read: full
extracted_by: Claude Opus 5, 2026-08-22
---

> **Source note — read before trusting any effect size below.** Every quantitative result lives in a
> *plot image* (`/img/context_rot/...`); the mirror preserves prose and figure captions, not the
> images or their axis values. The headline curves (accuracy vs input length, per model) are
> therefore **directional only** here; every number printed below is one the authors stated in
> running text. Plots at the URL above; code at https://github.com/chroma-core/context-rot.

## Core results

1. **Degradation with input length is universal, gradual, and non-uniform — no cliff is named.**
   "Across all experiments, model performance consistently degrades with increasing input length"
   (NIAH Extension §Details, repeated in the Conclusion). Performance "grows increasingly unreliable"
   rather than falling off at a threshold; **at no point does the text name a context length at which
   a Claude model breaks**. Task complexity is held constant while only input length varies, so the
   decline is attributable to length alone. Each NIAH configuration is swept over 8 input lengths ×
   11 needle positions per model.

2. **Needle–question similarity sets the *rate* of degradation.** Lower-similarity (semantically
   ambiguous) needle–question pairs degrade faster with input length than high-similarity pairs
   (§Needle-Question Similarity, Results; figure splits blue = upper-50 % similarity, red =
   lower-50 %, "high performance" = upper-33 % of models). Similarity is cosine similarity averaged
   over five embedding models: PG-essay needles span **0.445–0.775**, arXiv needles **0.521–0.829**,
   both with **< 0.1 SD** across embedding models. Crucially, *"at short input lengths, the models
   perform well even on low-similarity pairs"* — the pairing is not intrinsically hard; length is
   what breaks it.

3. **Distractors: one hurts, four compound, and the harm grows with input length.** "Even a single
   distractor reduces performance relative to the baseline (needle only), and adding four distractors
   compounds this degradation further" (§Impact of Distractors, Results). The distractors are
   near-misses hand-written against the *second-highest*-similarity needle — deliberately the easy
   case, to isolate distractor effect. Non-uniform *per distractor*: distractor 3 caused the largest
   decline in the arXiv-haystack/PG-needle condition, and distractors 2 and 3 dominate the
   hallucinated answers. **Size: no percentage in text — magnitudes are in `distractors_num.png` /
   `distractors_ind.png` only.**

4. **Claude's distractor failure mode is abstention, not hallucination.** "Claude models consistently
   exhibit the lowest hallucination rates. Specifically, Claude Sonnet 4 and Opus 4 are particularly
   conservative and tend to abstain when uncertain, explicitly stating that no answer can be found.
   In contrast, GPT models show the highest rates of hallucination, often generating confident but
   incorrect responses when distractors are present" (§Impact of Distractors, Results — failure
   analysis). Separately, refusals across the whole NIAH sweep were **69 of 194,480 LLM calls
   (0.035 %)**, e.g. Claude Opus 4 emitting empty output with `stop_reason="refusal"`.

5. **Haystack structure: logical coherence *hurts*, shuffling helps — across all 18 models.**
   "Across all 18 models and needle-haystack configurations, we observe a consistent pattern that
   models perform better on shuffled haystacks than on logically structured ones" (§Haystack
   Structure, Results). Original = essays with their natural flow of ideas; Shuffled = the same
   sentences randomly reordered, same topic, no local continuity. The authors call this
   "counterintuitive" and offer only a **conjecture** — that structural patterns of the input may
   change how attention is applied as length grows — explicitly flagging mechanism as out of scope.
   The paper's broadest structural finding (all models, all configurations) and its least explained.

6. **Needle–haystack similarity is non-uniform and under-determined.** In the PG-essay haystack,
   arXiv needles (avg needle–haystack similarity **0.368**, var 0.111) perform "significantly better"
   than PG needles (**0.529**, var 0.101) — i.e. a needle that does *not* blend in is easier. But in
   the arXiv haystack, arXiv needles (**0.654**, var 0.0858) vs PG needles (**0.394**, var 0.105)
   show "only minimal performance differences". The authors state outright that two topics are
   insufficient to conclude that blending-in hurts (§Needle-Haystack Similarity, Results).

7. **Needle position: no effect in NIAH; an early-position advantage in the replication task.**
   "Testing across 11 needle positions, we find no notable variation in performance for this specific
   NIAH task" (§Needle-Question Similarity, Results) — i.e. this report does *not* reproduce a
   lost-in-the-middle effect. In the Repeated Words task the picture differs: "Accuracy is highest
   when the unique word is placed near the beginning of the sequence, especially as input length
   increases" (§Repeated Words, Results; Claude, GPT, Gemini, Qwen position-accuracy figures).

8. **LongMemEval focused vs full is the paper's headline curation result — and Claude has the
   largest gap.** Same question, same reasoning required; the only difference is whether irrelevant
   history is present. Focused prompts average **~300 tokens**; full prompts average **~113k tokens**
   (306 prompts after cleaning). "Across all models, we see significantly higher performance on
   focused prompts compared to full prompts." And: "The Claude models exhibit the most pronounced gap
   between focused and full prompt performance. This discrepancy is largely driven by abstentions
   that arise with ambiguity... most evident in Claude Opus 4 and Sonnet 4, which appear to be
   particularly conservative under ambiguity, leading to lower performance on full prompts relative
   to that of the older Claude models." The worked failure is a Sonnet 4 (non-thinking) answer on a
   full prompt *that contained the dates*: "I cannot determine the number of days... because the
   specific dates for these events are not provided in the chat history." **Gap size: percentages are
   in `longmemeval/claude.png` only; the text says "significantly" and gives no number.** Thinking
   mode lifts both focused and full but does not close the gap. Question-type ordering: non-thinking
   = knowledge-update > multi-session > temporal-reasoning; thinking = knowledge-update >
   temporal-reasoning > multi-session.

9. **Repeated Words — output is part of input, and both degrade together.** Because models are
   autoregressive, "a model's output also belongs to its input". On a trivial replicate-this-text
   task where output length scales with input, "performance consistently degrades across all models".
   Claude family (§Repeated Words, Results): **Sonnet 3.5 outperforms the newer Claude models** up to
   its 8192 max-output-token ceiling; **Opus 4 has the slowest degradation rate but is the only
   Claude to refuse (2.89 % of attempts)**, typically after first making an observation about the
   input — a behaviour that "typically arises starting from 2500 words", with refusals grounded in
   copyright risk or in the inconsistency it noticed in the sequence. Cross-family:
   GPT-4.1 refusal **2.55 %** (also starting ~2500 words); GPT-3.5 Turbo excluded entirely
   (**60.29 %** content-filter refusals); Qwen3-8B non-attempts **4.21 %**, random output from ~5000
   words; Gemini family emits words not in the input starting ~**500–750 words** (2.5 Pro most
   variable, then 2.0 Flash, then 2.5 Flash); GPT-4 Turbo has a local accuracy peak at 500 words,
   over-generating between 50 and 250 words and under-generating beyond 500. A general late-context
   failure: "models often generate the repeated word until reaching the output token limit."

## Method and setting (what was actually built/tested)

Four evaluations, all **single-call, no tools, no multi-turn agent loop, no training** — prompting
off-the-shelf models at temperature 0 (except where incompatible, e.g. o3, or discouraged, e.g. Qwen
thinking mode). Qwen extended 32,768 → 131,072 tokens with YaRN. Thinking and non-thinking modes of
the same model are scored as separate models.

- **NIAH extension** (needle–question similarity, distractors, needle–haystack similarity, haystack
  structure): haystacks from Paul Graham essays and arXiv papers; 8 needles per topic hand-written
  against a cluster theme (HDBSCAN/UMAP over `text-embedding-3-large` chunks) and verified absent
  from the haystack, so wrong answers are hallucinations rather than alternative correct answers.
  8 input lengths × 11 positions per configuration; each model run across its full context window.
- **LongMemEval_s**, filtered to knowledge-update / temporal-reasoning / multi-session, manually
  cleaned (38 prompts dropped) → 306 prompts; full ≈113k tokens, focused ≈300 tokens.
- **Repeated Words**: 1090 (length, unique-word-index) variations per word pair, word counts 25 / 50 /
  75 / 100 / 250 / 500 / 750 / 1000 / 2500 / 5000 / 7500 / 10000, over 7 word pairs; normalised
  Levenshtein distance; `max_output_tokens = 2 × input`; thinking budget 0 or minimum (128 for Gemini
  2.5 Pro); o3 excluded.
- **Judge**: GPT-4.1, iterated against ~500 human-labelled NIAH and ~600 LongMemEval outputs until
  >0.99 alignment.

**The 18 models** (Appendix, "Models Tested"; not all appear in every experiment, due to context
window or thinking-budget constraints):
**Anthropic (5) — Claude Opus 4, Claude Sonnet 4, Claude Sonnet 3.7, Claude Sonnet 3.5, Claude Haiku
3.5.** OpenAI (7) — o3, GPT-4.1, GPT-4.1 mini, GPT-4.1 nano, GPT-4o, GPT-4 Turbo, GPT-3.5 Turbo.
Google (3) — Gemini 2.5 Pro, 2.5 Flash, 2.0 Flash. Alibaba (3) — Qwen3-235B-A22B, Qwen3-32B, Qwen3-8B.
No Claude 4.5/5-generation model, no Opus 5; report predates them (July 2025).

## Relevance to P1–P4

**P4 (what smaller reads cost in grounding) — the paper's core contribution, and it points the
opposite way to the fear.** The focused-vs-full contrast (result 8) is the curated-vs-full comparison
with task difficulty held fixed: **~300 tokens beats ~113k tokens on the same question, for every
model family**, and the design — verify the models succeed on focused inputs, then observe consistent
degradation on full ones — means the loss is caused by the irrelevant material, not by anything
curation removed. The transfer gap: their "focused" input is *guaranteed sufficient* (labelled gold
evidence), whereas our curation is a guess about sufficiency. So the paper supports "smaller, if it
still contains what's needed" and says nothing about the cost of curating wrongly. Result 3 adds the
second half: the harm is not only bulk but *near-miss* content — superseded plan text, stale
done-records, a rejected design left in the plan are structurally distractors, and one is enough to
measure.

**P2 (sessions grow; the longest dominate).** Result 9 is the only result touching a session's own
output, and it is a weak instrument for us: output tokens re-enter the input and accuracy falls as
the two grow together — but on a single-call replication task, not over 100–200 tool turns. The
transferable part is the *failure signature* of a long Claude generation — observation before
attempt, hedging, refusal (Opus 4, 2.89 %, from ~2500 words) — the same conservatism that produces
the LongMemEval abstentions. For the doc-writer (≈145k median, 438k peak, 192 turns) the directional
prediction is degraded reliability with no cliff to design around, and abstention-flavoured failures
rather than confident wrong output.

**P3 (every session rebuilds the same picture).** Nothing on repeated re-reading across sessions,
caching, or hand-offs. It does bear on the *shape* of what is rebuilt: results 5 and 7 say assembling
material into a coherent narrative is not free, and that position within a long input did not matter
for NIAH retrieval.

**P1 (context is the cost).** Not addressed — the report measures no cost, latency or token spend; it
is purely an accuracy study.

## Interventions this paper supports

- **Give a role a curated evidence bundle rather than the full artefact set** — the largest supported
  effect in the paper (result 8: ~300-token focused vs ~113k full, all model families, Claude's gap
  widest). *Loses:* if curation drops the needed fact, the Claude failure mode is abstention, so the
  loop sees "cannot determine" verdicts rather than silently wrong work — a visible failure, but a
  failure.
- **Make sub-agent return contracts "focused-input"-shaped**: the sub-agent returns the evidence
  needed to decide and the parent does *not* re-read the corpus behind it (result 8). Today's pattern
  — a conclusion returning into a context that then re-reads the same files — recreates the full-input
  condition on top of the focused one, which the paper predicts is strictly worse for the same answer.
- **Actively strip near-misses from what a role reads** (result 3): superseded plan phases, resolved
  review rounds, stale done-records, rejected design options. One distractor is already measurable,
  and four compound. Cheap and directly supported; *loses* the history a reviewer might use to see why
  an option was rejected.
- **Instrument abstention as the context-overload signal** (results 4 and 8, plus the Sonnet 4 example
  where the dates *were present*). Count per session: "cannot determine / insufficient information"
  verdicts, non-attempts, hedged findings, empty `stop_reason="refusal"` outputs. A concrete new
  instrument for P4's missing measurement, and the metric this paper says Claude specifically will
  move on — unlike hallucination rate, which Claude keeps low.
- **Treat coherent narrative in long attachments as not automatically better** (result 5). Directional
  only, and the transfer is a stretch — coherent essays vs shuffled sentences for planted-fact
  retrieval, not instruction-following over structured docs. The weakest item here; it is not licence
  to shuffle docs.
- **Put the load-bearing instruction early in a dispatch prompt** (result 7, second half). Weak and
  narrow: the early-position advantage comes from the replication task, and NIAH found no position
  effect across 11 positions.
- **Do not expect a newer model to buy immunity** (result 8: Opus 4 and Sonnet 4 score *lower* on full
  prompts than older Claudes because they are more conservative; result 9: Sonnet 3.5 beats the newer
  Claudes up to its output cap). Relevant to any "use the strongest model and feed it everything"
  argument.

## Applicability caveats

- **No effect sizes recoverable from this mirror.** Distractor magnitude, the focused/full gap size
  and the shape of every degradation curve are image-only; only direction, ordering and the in-text
  numbers above can be quoted.
- **Task type is QA/retrieval/replication, not code.** No repository, no edits, no gate, no
  correctness oracle beyond an LLM judge. Nothing here measures whether a code-writer with less
  context writes worse code.
- **Single call, no tools, no multi-turn loop, no compaction.** The paper's inputs are static prompts;
  the 100–200-turn transfer is extrapolation. The authors' limitation section says only that they
  *expect* degradation to be "even more severe" in more complex real-world settings — conjecture, not
  measurement.
- **Model vintage.** Claude coverage is Opus 4, Sonnet 4, Sonnet 3.7, Sonnet 3.5, Haiku 3.5 as of July
  2025 — no Opus 5; and Repeated Words used thinking budgets of 0 or minimum, nowhere near xhigh
  effort. The one place thinking is properly exercised (LongMemEval) shows it helps both conditions
  without closing the gap.
- **Benchmark quirks:** needles are hand-written to blend into a cluster theme and verified absent
  from the haystack, so "hallucination" is well defined but the setting is adversarially clean;
  LongMemEval was hand-filtered (38 prompts dropped as ambiguous/unanswerable); needle–haystack
  similarity rests on two topics and the authors decline to generalise it.
- **Nothing is trained** — every result is prompt-level, so all of it is reachable in our surface.

## Briefing check

The note reads: *"extract the shape of degradation with input length for Claude models, the size of
the distractor effect, and the self-conditioning result, which concerns a session's own history and
so bears on 100–200-turn loops."* Two-and-a-half of three hold.

- **Shape of degradation — supported, but qualitative.** Degradation is consistent, gradual and
  non-uniform, with **no cliff length stated anywhere in the text** and per-model curves image-only.
  The only Claude-specific shape statements are "Opus 4... exhibiting the slowest degradation rate"
  (Repeated Words) and "The Claude models exhibit the most pronounced gap between focused and full
  prompt performance" (LongMemEval).
- **Size of the distractor effect — direction supported, size not.** One distractor degrades, four
  compound, the effect amplifies with length, and individual distractors differ (distractor 3 worst in
  one condition; 2 and 3 dominate hallucinations). The report **never states a numeric size in text**,
  so the note's "size" cannot be honoured from this source without reading the plots.
- **"The self-conditioning result" — the note misnames something.** This paper contains no result
  called self-conditioning. Its nearest analogue is **Repeated Words**, whose premise is that "a
  model's output also belongs to its input" — but that is single-call generation over up to 10,000
  words, not a session's turn history. The self-conditioning result proper (a model conditioning on
  its own *past errors* and becoming likelier to err) belongs to **Sinha et al. 2509.09677**, the next
  ★ in the same S1 section; expect it there, not here. The onward claim that this "bears on
  100–200-turn loops" is an inference the paper neither makes nor tests.
- **What the note omits matters more than what it gets wrong:** the focused-vs-full LongMemEval result
  is this paper's strongest evidence for curation (~300 vs ~113k tokens, identical task), and its
  Claude-specific twist — the newer, stronger Claudes lose *most* to irrelevant context because they
  abstain — is the single most decision-relevant sentence in the report for our loop.
