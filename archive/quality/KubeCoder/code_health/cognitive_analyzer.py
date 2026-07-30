"""Cognitive complexity analysis via the complexipy library.

Replaces the upstream template's TypeScript cognitive-complexity sidecar with
complexipy — a Rust-backed implementation of the same SonarSource cognitive
complexity algorithm — so the grader stays pure-Python (no Node/tsx).
"""

from __future__ import annotations

from pathlib import Path

from .models import FileReport, Finding
from .suppressions import parse_suppressions

# Threshold and weight for the cognitive complexity rule. The threshold matches
# complexipy's own default ceiling (and SonarSource's recommended maximum).
COGNITIVE_THRESHOLD = 15
COGNITIVE_WEIGHT = 0.8


def run_cognitive_analysis(root: Path, reports: list[FileReport]) -> None:
    """Compute per-function cognitive complexity and merge findings into reports.

    Fails soft: if complexipy is unavailable or a file can't be analyzed, the
    cognitive findings for it are simply skipped (the rest of the grade stands).
    """
    if not reports:
        return

    try:
        from complexipy import file_complexity
    except ImportError:
        return

    for report in reports:
        suppressed = parse_suppressions(Path(report.path))
        if "cognitive_complexity" in suppressed or "*" in suppressed:
            continue

        try:
            result = file_complexity(report.path)
        except Exception:
            continue

        for fn in getattr(result, "functions", None) or []:
            complexity = getattr(fn, "complexity", 0)
            excess = complexity - COGNITIVE_THRESHOLD
            if excess <= 0:
                continue
            name = getattr(fn, "name", "?")
            report.findings.append(Finding(
                rule="cognitive_complexity",
                detail=(
                    f"{name}(): cognitive complexity {complexity} "
                    f"(threshold {COGNITIVE_THRESHOLD})"
                ),
                value=complexity,
                threshold=COGNITIVE_THRESHOLD,
                points=excess * COGNITIVE_WEIGHT,
            ))
