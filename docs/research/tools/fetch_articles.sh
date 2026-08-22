#!/usr/bin/env bash
#
# Converts every arXiv paper cited in ../research-2.md into Markdown under
# ../articles/. Already-converted papers are left alone, so re-running this
# after adding a link to the list only fetches what is new; pass --force to
# rebuild everything.
#
# Needs uv (in the python toolchain container) plus pandoc and latexpand, which
# the container no longer ships: drop a static pandoc and the latexpand perl
# script into any directory and put it on PATH for the run, e.g.
#
#     cexec python sh -c 'PATH=/path/to/bin:$PATH docs/research/tools/fetch_articles.sh'
#
set -euo pipefail

cd "$(dirname "$0")"

# Keyed by the section of research-2.md the paper is cited under. The first
# briefing's corpus (research.md) is frozen under ../archive/run-1/ and is not
# re-fetched; "cite only" entries are fetched only where the briefing asks for a
# specific section to be read.
PAPERS=(
  # S1 — Long-context degradation and irrelevant-context harm
  https://arxiv.org/abs/2509.09677  # Sinha et al. 2025, The Illusion of Diminishing Returns
  https://arxiv.org/abs/2606.29718  # Xia et al. 2026, Diagnosing and Mitigating Context Rot
  https://arxiv.org/abs/2505.06120  # Laban et al. 2025, LLMs Get Lost in Multi-Turn Conversation

  # S2 — Trajectory reduction, compression and compaction
  https://arxiv.org/abs/2509.23586  # Xiao et al. 2025, AgentDiet (trajectory reduction)
  https://arxiv.org/abs/2510.00615  # Kang et al. 2025, ACON
  https://arxiv.org/abs/2512.24601  # Zhang, Kraska, Khattab 2025, Recursive Language Models
  https://arxiv.org/abs/2510.11967  # Sun et al. 2025, Context-Folding (folding vs summarisation only)

  # S3 — Orientation, cross-session memory and the hand-off
  https://arxiv.org/abs/2605.19932  # Gu et al. 2026, PEEK
  https://arxiv.org/abs/2409.07429  # Wang et al. 2024, Agent Workflow Memory
  https://arxiv.org/abs/2605.14563  # Bae et al. 2026, MemDocAgent

  # S4 — Decomposition and sub-agents
  https://arxiv.org/abs/2512.08296  # Kim et al. 2025, Towards a Science of Scaling Agent Systems
  https://arxiv.org/abs/2503.13657  # Cemri et al. 2025, MAST

  # S5 — Agent–computer interface and tool-output hygiene
  https://arxiv.org/abs/2601.16746  # Wang, Shi et al. 2026, SWE-Pruner
  https://arxiv.org/abs/2511.00197  # Majgaonkar et al. 2025, Understanding Code Agent Behaviour
  https://arxiv.org/abs/2405.15793  # Yang et al. 2024, SWE-agent (ACI ablation only)

  # S6 — Retrieval versus reading
  https://arxiv.org/abs/2407.16833  # Li, Z. et al. 2024, RAG or Long-Context LLMs?
  https://arxiv.org/abs/2501.01880  # Li, X. et al. 2024, Long Context vs. RAG

  # S7 — Cost-controlled evaluation and token economics
  https://arxiv.org/abs/2407.01502  # Kapoor et al. 2024, AI Agents That Matter
  https://arxiv.org/abs/2509.09853  # Fan et al. 2025, SWE-Effi
)
# S1's Chroma report, S7's vendor docs and S8's practitioner posts are web pages,
# not arXiv papers: fetch_pages.sh mirrors those into ../articles/ as web-*.md.

failed=()
for url in "${PAPERS[@]}"; do
  if ! uv run arxiv_to_md.py "$url" "$@"; then
    failed+=("$url")
  fi
done

if (( ${#failed[@]} )); then
  echo
  echo "${#failed[@]} of ${#PAPERS[@]} papers failed:" >&2
  printf '  %s\n' "${failed[@]}" >&2
  exit 1
fi

echo
echo "all ${#PAPERS[@]} papers converted into $(cd ../articles && pwd)"
