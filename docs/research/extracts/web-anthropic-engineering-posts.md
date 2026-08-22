---
source: web-anthropic-eng-multi-agent-research-system.md, web-anthropic-eng-effective-context-engineering.md, web-anthropic-eng-effective-harnesses-long-running-agents.md
paper: Anthropic engineering posts — "How we built our multi-agent research system" (Jun 2025), "Effective context engineering for AI agents" (Sep 2025), "Effective harnesses for long-running agents" (Nov 2025) — https://www.anthropic.com/engineering/
read: full (all three)
extracted_by: session lead (Claude Fable 5), 2026-08-22
---

Practitioner sources, not research: what is argued and the few numbers given. Weighted
accordingly in interventions-2.md.

## Core results / claims

1. **Multi-agent research system.** Multi-agent (Opus 4 lead + Sonnet 4 sub-agents) beat
   single-agent Opus 4 by **90.2 %** on an internal research eval — a breadth-first search task.
   "Token usage by itself explains 80 % of the variance" on BrowseComp; agents use ≈ 4× the tokens
   of chat, **multi-agent systems ≈ 15×**. Explicit limit: "some domains that require all agents to
   share the same context or involve many dependencies between agents are not a good fit … most
   coding tasks involve fewer truly parallelizable tasks." Sub-agents "return only a condensed,
   distilled summary (often 1,000–2,000 tokens)". Parallel tool calling (3–5 sub-agents at once,
   3+ tools per sub-agent turn) "cut research time by up to 90 %". Effort-scaling rules are
   prompted ("simple fact-finding requires just 1 agent with 3–10 tool calls"). Appendix: "Subagent
   output to a filesystem to minimize the 'game of telephone'" — store artefacts, pass references;
   "summarize completed work phases and store essential information in external memory before
   proceeding … spawn fresh subagents with clean contexts while maintaining continuity through
   careful handoffs".
2. **Effective context engineering.** "Find the smallest possible set of high-signal tokens that
   maximize the likelihood of some desired outcome"; context rot cited from Chroma as gradual, not a
   cliff. Just-in-time retrieval via lightweight identifiers (paths, queries) and `head`/`tail`
   over large data rather than loading it; Claude Code as the hybrid (CLAUDE.md dropped in up
   front, glob/grep just-in-time). Long-horizon techniques: **compaction** (Claude Code's passes the
   history to the model to "preserve architectural decisions, unresolved bugs, and implementation
   details while discarding redundant tool outputs", then continues "with this compressed context
   plus the five most recently accessed files"; "start by maximizing recall … then iterate to
   improve precision"); **tool-result clearing** is "one of the safest lightest touch forms of
   compaction"; **structured note-taking** (NOTES.md, memory tool); **sub-agent architectures**
   (deep work in clean contexts, 1–2 k-token returns). Guidance: compaction for back-and-forth,
   note-taking for milestone-driven iterative work, multi-agent for parallel exploration.
3. **Effective harnesses for long-running agents.** Two failure patterns across context windows:
   trying to one-shot the task (runs out of context mid-feature, the next session "has to guess at
   what had happened"), and declaring the project done early. Fix: an **initializer** session that
   writes a feature list (JSON, all "failing"), `init.sh`, a `claude-progress.txt` log, an initial
   commit; every later session reads git log + progress file, picks one feature, verifies
   end-to-end, commits with a descriptive message, updates the progress file. JSON chosen over
   Markdown because the model is less likely to corrupt it. "Compaction isn't sufficient … doesn't
   always pass perfectly clear instructions to the next agent." Open question stated: one general
   coding agent vs specialised agents per sub-task. No measurements.

## Relevance to P1–P4

- **P1/P2**: the harness post is the vendor's own statement that the unit of work should be one
  feature per session with a clean state left behind — our per-phase dispatch is that shape; the
  doc-writer is the one role that still "one-shots". Tool-result clearing as the safest compaction
  is API-side and not reachable from our headless sessions (see web-claude-code-docs-harness).
- **P3**: "read the git logs and progress files to get up to speed" is the orientation pattern;
  our done-records are the progress file but the writer reads the whole plan to find them.
- **Q3**: the 15× token figure and "coding has fewer parallelizable parts" are the cost side of
  sub-agents; sub-agent returns of 1–2 k tokens and filesystem artefacts are the contract side.

## Interventions these posts support

- A script-built orientation hand-off (progress + git log equivalent) per dispatch — P3.1.
- Sub-agents writing full findings to a file and returning a reference plus a short conclusion —
  P3.3.
- Batched/parallel tool calls as a turn-count lever — P1.1.
- Bounding the doc phase into units with a progress artefact — P2.1.

## Applicability caveats

Vendor-authored; one measured number (90.2 % on an internal eval of a search task); the harness
post's setting is a web app built from a one-line prompt, not a planned slice with a gate; nothing
on prompt-caching economics; "compaction keeps the five most recently accessed files" describes
Claude Code's behaviour at the time of writing (Sep 2025).

## Briefing check

The briefing's notes ("≈ 15× tokens; most coding tasks have fewer parallelizable parts"; "what
crosses a context-window cut") are accurate quotes. The harness post's answer to "what crosses
the cut" is: a feature list with pass/fail state, a progress log, git history, and an init script —
artefacts, not a summary.
