"""Load .gitignore and .codehealthignore patterns for file exclusion."""

from __future__ import annotations

from pathlib import Path

import pathspec

IGNORE_FILENAMES = (".gitignore", ".codehealthignore")


def _read_ignore_lines(ignore_path: Path) -> list[str]:
    """Read non-empty, non-comment lines from an ignore file."""
    if not ignore_path.is_file():
        return []
    try:
        text = ignore_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def _prefix_pattern(prefix: str, pattern: str) -> list[str]:
    """Prefix a gitignore pattern so it matches relative to the project root.

    Returns the (0, 1 or 2) root-relative patterns the nested one expands to.
    Git's anchoring rule decides which:

    - A separator at the START (``/foo``) or in the MIDDLE (``a/foo``) anchors the
      pattern to the ignore file's own directory, so one prefixed pattern says it all.
    - No separator (``foo``, or a directory pattern like ``build/``) matches at ANY
      depth below that directory. Prefixing alone would silently ANCHOR it — the
      prefix introduces the separator that changes git's reading — so ``sub/foo``
      would stop matching ``sub/a/foo``. Emit the ``**/`` form alongside it to keep
      the any-depth reach.

    Negation patterns (!) are preserved on every form.
    """
    negated = pattern.startswith("!")
    if negated:
        pattern = pattern[1:]

    pattern = pattern.strip()
    if not pattern:
        return []

    if pattern.startswith("/"):
        # Root-anchored in the sub-directory -> anchor under prefix
        results = [f"{prefix}{pattern}"]
    elif "/" in pattern.rstrip("/"):
        # An interior separator already anchors it to the ignore file's directory.
        # (A TRAILING slash is a directory marker, not an anchor, so it is stripped
        # before the test: `build/` is unanchored, `a/build/` is anchored.)
        results = [f"{prefix}/{pattern}"]
    else:
        # Unanchored -> match at every depth under the prefix subtree
        results = [f"{prefix}/{pattern}", f"{prefix}/**/{pattern}"]

    return [f"!{result}" if negated else result for result in results]


def load_ignore_patterns(project_root: Path) -> pathspec.PathSpec | None:
    """Load ignore patterns from .gitignore and .codehealthignore files.

    Loads both file types from the project root and all subdirectories.
    Patterns from nested files are prefixed so they match paths relative
    to the project root, mirroring git's own scoping behaviour.

    Returns a PathSpec matcher, or None if no patterns are found.
    """
    all_patterns: list[str] = []

    for filename in IGNORE_FILENAMES:
        # Root ignore file -- patterns apply as-is
        all_patterns.extend(_read_ignore_lines(project_root / filename))

        # Nested ignore files -- prefix patterns with their relative directory
        for gi_path in sorted(project_root.rglob(filename)):
            if gi_path.parent == project_root:
                continue  # already handled above
            rel_dir = str(gi_path.parent.relative_to(project_root))
            for line in _read_ignore_lines(gi_path):
                all_patterns.extend(_prefix_pattern(rel_dir, line))

    if not all_patterns:
        return None

    return pathspec.PathSpec.from_lines("gitignore", all_patterns)
