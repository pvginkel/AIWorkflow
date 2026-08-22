#!/usr/bin/env bash
#
# Mirrors the non-arXiv sources of ../research-2.md (the Chroma report, the
# vendor docs, the practitioner posts) into ../articles/ as web-<slug>.md, next
# to the arXiv papers fetch_articles.sh converts. Already-mirrored pages are left
# alone; pass --force to refetch everything.
#
# Two fetch modes: "md" pages serve Markdown directly at a .md URL (the
# platform.claude.com and code.claude.com docs do; their HTML is JS-rendered and
# empty to curl); "html" pages go through pandoc. Needs curl and pandoc on PATH —
# the dev container has curl; pandoc is the same static binary fetch_articles.sh
# needs, so run both with the same PATH.
#
set -euo pipefail

cd "$(dirname "$0")"
out=../articles
mkdir -p "$out"
force=0; [[ "${1:-}" == "--force" ]] && force=1

# slug|mode|url  — keyed by the section of research-2.md that cites the page.
PAGES=(
  # S1 — Long-context degradation
  "chroma-context-rot|html|https://research.trychroma.com/context-rot"
  # S7 — vendor docs
  "anthropic-docs-prompt-caching|md|https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md"
  "anthropic-docs-context-windows|md|https://platform.claude.com/docs/en/build-with-claude/context-windows.md"
  "anthropic-docs-extended-thinking|md|https://platform.claude.com/docs/en/build-with-claude/extended-thinking.md"
  "anthropic-docs-context-editing|md|https://platform.claude.com/docs/en/build-with-claude/context-editing.md"
  # S8 — practitioner references
  "anthropic-eng-multi-agent-research-system|html|https://www.anthropic.com/engineering/multi-agent-research-system"
  "anthropic-eng-effective-context-engineering|html|https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents"
  "anthropic-eng-effective-harnesses-long-running-agents|html|https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents"
  "cognition-dont-build-multi-agents|html|https://cognition.ai/blog/dont-build-multi-agents"
  # The 2026 follow-up that narrows the 2025 position: writes stay single-threaded,
  # extra agents contribute intelligence rather than actions. (Blog moved to cognition.com.)
  "cognition-multi-agents-followup-2026|html|https://cognition.com/blog/multi-agents-working"
  "claude-code-docs-sub-agents|md|https://code.claude.com/docs/en/sub-agents.md"
  # Claude Code harness pages that settle what a headless session's fixed prefix
  # carries, what compaction/caching the harness does on its own, and whether
  # API-side context editing is reachable from it (research-2.md Q1/Q2).
  "claude-code-docs-context-window|md|https://code.claude.com/docs/en/context-window.md"
  "claude-code-docs-prompt-caching|md|https://code.claude.com/docs/en/prompt-caching.md"
  "claude-code-docs-costs|md|https://code.claude.com/docs/en/costs.md"
  "claude-code-docs-model-config|md|https://code.claude.com/docs/en/model-config.md"
  "claude-code-docs-headless|md|https://code.claude.com/docs/en/headless.md"
  "claude-code-docs-memory|md|https://code.claude.com/docs/en/memory.md"
  "claude-code-docs-hooks|md|https://code.claude.com/docs/en/hooks.md"
  "claude-code-docs-agent-sdk-cost-tracking|md|https://code.claude.com/docs/en/agent-sdk/cost-tracking.md"
  "claude-code-docs-agent-sdk-agent-loop|md|https://code.claude.com/docs/en/agent-sdk/agent-loop.md"
  "aider-repomap-docs|html|https://aider.chat/docs/repomap.html"
  "aider-repomap-post-2023|html|https://aider.chat/2023/10/22/repomap.html"
)

failed=()
for entry in "${PAGES[@]}"; do
  IFS='|' read -r slug mode url <<<"$entry"
  dest="$out/web-$slug.md"
  if [[ -s "$dest" && $force -eq 0 ]]; then
    echo "skip   $dest (exists)"
    continue
  fi
  tmp=$(mktemp)
  if ! curl -sSL --fail -A "Mozilla/5.0 (AIWorkflow research mirror)" -o "$tmp" "$url"; then
    echo "FAILED $url" >&2; failed+=("$url"); rm -f "$tmp"; continue
  fi
  {
    printf -- '---\nsource: %s\nfetched: %s\nmode: %s\n---\n\n' "$url" "$(date -u +%F)" "$mode"
    if [[ $mode == md ]]; then
      cat "$tmp"
    else
      pandoc -f html -t gfm --wrap=none "$tmp" 2>/dev/null
    fi
  } >"$dest"
  rm -f "$tmp"
  words=$(wc -w <"$dest")
  if (( words < 300 )); then
    echo "THIN   $dest ($words words) — check the page renders without JS" >&2
    failed+=("$url (thin)")
  else
    echo "wrote  $dest ($words words)"
  fi
done

if (( ${#failed[@]} )); then
  echo; echo "${#failed[@]} of ${#PAGES[@]} pages need attention:" >&2
  printf '  %s\n' "${failed[@]}" >&2
  exit 1
fi
echo; echo "all ${#PAGES[@]} pages mirrored into $(cd "$out" && pwd)"
