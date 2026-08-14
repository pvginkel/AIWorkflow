---
paper: "Effort (Claude platform documentation)"
source_url: "https://platform.claude.com/docs/en/build-with-claude/effort"
briefing_section: S8
starred: true
extracted: 2026-08-14
extractor: "session lead, full fetch and read (page as of 2026-08-14)"
---

## Core facts (vendor documentation, not research)

- Levels `low | medium | high | xhigh | max`; **`high` is the API default and identical to
  omitting the parameter**. `xhigh`/`max` availability varies by model; Opus 5 supports all five.
- Effort affects **all tokens in the response** — text, tool calls/arguments, and thinking. Lower
  effort ⇒ fewer tool calls, combined operations, terse confirmations; higher effort ⇒ more tool
  calls, plans before action, more comprehensive code comments.
- **"Effort is a behavioral signal, not a strict token budget."** At low effort the model still
  thinks on genuinely hard problems, just less.
- **Opus 5 specifics:** effort controls *thinking volume, not visible response length* — "changing
  effort does not reliably shorten responses, so prompt for length instead." Thinking cannot be
  disabled at `xhigh`/`max` (400 error). Guidance: start `high`; `xhigh` for demanding
  coding/agentic work; "use low and medium liberally as your primary control for token cost and
  response time wherever your evals show quality holds"; re-run effort sweeps rather than carrying
  settings over from earlier models. Large `max_tokens` (≥64k) advised at `xhigh`/`max`.
- **Opus 4.7/4.8 note** (carried for contrast): those models "respect effort levels more
  strictly", and at low effort "the model scopes its work to what was asked rather than doing
  more than requested"; `max` "can lead to overthinking" on structured-output tasks.
- **Caching interaction:** effort shapes the rendered prompt — changing it between requests
  invalidates cached prefixes. Hold effort constant within a conversation; vary it across
  workloads/dispatches. (Each of our loop agents is a fresh `kc session`, so per-dispatch tiering
  is cache-safe.)
- Effort vs thinking: `effort` ≠ `thinking` parameter; in adaptive-thinking mode effort governs
  how often/deeply the model thinks. A separate "task budgets" feature exists for advisory
  whole-loop token budgets.

## Relevance to the catalogue

- **A3 (effort step-down)** mechanics come from here: `high` is already one step below our
  current `xhigh`; step-downs are legitimate primary cost controls on Opus 5 *conditional on
  evals* — which is exactly what the A3 trial provides.
- **Problem B caution:** comment volume is *response* behavior; on Opus 5, effort does not
  reliably shorten responses — so lowering effort is **not** a comment-churn fix; register rules
  (B1) are. Conversely, the docs note higher effort produces "more comprehensive code comments" —
  our xhigh-everywhere setting plausibly contributes to comment volume; the A3 trial can check
  this as a side measurement.
- **A4 context:** the docs' own recommendation is behavioral ("test your use case", "consider
  dynamic effort" by task) — but supplies no mechanism for prediction; consistent with
  escalate-on-outcome rather than grade-upfront.

## Caveats

Vendor documentation: describes intended behavior, not measured guarantees; wording changes over
time (this extract reflects the page as fetched 2026-08-14); the "scopes work to what was asked"
claim is written for Opus 4.7/4.8, not Opus 5.
