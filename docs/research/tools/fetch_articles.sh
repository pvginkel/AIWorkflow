#!/usr/bin/env bash
#
# Converts every arXiv paper cited in ../research.md into Markdown under
# ../articles/. Already-converted papers are left alone, so re-running this
# after adding a link to the list only fetches what is new; pass --force to
# rebuild everything.
#
# Needs uv, pandoc and latexpand, which live in the python toolchain container:
#
#     cexec python docs/research/tools/fetch_articles.sh
#
set -euo pipefail

cd "$(dirname "$0")"

# Keyed by the section of research.md the paper is cited under.
PAPERS=(
  # S1 — Overthinking in agentic settings
  https://arxiv.org/abs/2502.08235  # Cuadron et al. 2025, The Danger of Overthinking

  # S2 — Limits of test-time compute scaling
  https://arxiv.org/abs/2507.14417  # Gema et al. 2025, Inverse Scaling in Test-Time Compute
  https://arxiv.org/abs/2412.21187  # Chen et al. 2024, Do NOT Think That Much for 2+3=?
  https://arxiv.org/abs/2502.18080  # Towards Thinking-Optimal Scaling of Test-Time Compute
  https://arxiv.org/abs/2412.18547  # Han et al. 2024, Token-Budget-Aware LLM Reasoning

  # S3 — Underspecification as an overthinking trigger
  https://arxiv.org/abs/2504.06514  # Fan et al. 2025, Missing Premise Exacerbates Overthinking

  # S4 — Difficulty routing vs. escalation cascades
  https://arxiv.org/abs/2305.05176  # Chen, Zaharia, Zou 2023, FrugalGPT

  # S5 — Limits of intrinsic self-correction; grounded review
  https://arxiv.org/abs/2310.01798  # Huang et al. 2024, LLMs Cannot Self-Correct Reasoning Yet
  https://arxiv.org/abs/2405.14092  # Wu et al. 2024, Self-Correct with Key Condition Verification
  https://arxiv.org/abs/2310.13548  # Sharma et al. 2023, Towards Understanding Sycophancy

  # S6 — Evaluator biases
  https://arxiv.org/abs/2404.13076  # Panickssery et al. 2024, LLM Evaluators Favor Own Generations
  https://arxiv.org/abs/2410.21819  # Wataoka et al. 2024, Self-Preference Bias in LLM-as-a-Judge
  https://arxiv.org/abs/2402.11436  # Xu et al. 2024, Pride and Prejudice
  https://arxiv.org/abs/2310.10076  # Saito et al. 2023, Verbosity Bias in Preference Labeling

  # S7 — Reviewer overcorrection and false-positive economics
  https://arxiv.org/abs/2603.00539  # Are LLMs Reliable Code Reviewers?
  https://arxiv.org/abs/2601.22952  # Xiong, Zhang et al., Sifting the Noise
  https://arxiv.org/abs/2411.03079  # LLM4FPM
)
# Two entries in research.md are deliberately absent: S8 is a vendor
# documentation page rather than an arXiv paper, and the Shi et al. position-bias
# paper is listed there as a title to search for, without a link.

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
