"""Tests for the code-health ignore-file loader.

The interesting behaviour is NESTED ignore files: their patterns have to be rewritten
to be project-root-relative, and that rewrite must not change git's anchoring reading
of the pattern (R-054).
"""

from __future__ import annotations

import pytest

from tools.code_health.gitignore import _prefix_pattern, load_ignore_patterns


@pytest.fixture
def tree(tmp_path):
    """A project root with a nested ignore file, written by the test body."""

    def _build(nested_lines: list[str], *, root_lines: list[str] | None = None):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".gitignore").write_text("\n".join(nested_lines) + "\n")
        if root_lines:
            (tmp_path / ".gitignore").write_text("\n".join(root_lines) + "\n")
        return load_ignore_patterns(tmp_path)

    return _build


class TestPrefixPattern:
    def test_unanchored_pattern_gets_both_the_direct_and_any_depth_form(self):
        # Without the **/ form, prefixing would anchor `foo` to `sub/foo` only.
        assert _prefix_pattern("sub", "foo") == ["sub/foo", "sub/**/foo"]

    def test_leading_slash_anchors_to_the_ignore_file_directory(self):
        assert _prefix_pattern("sub", "/foo") == ["sub/foo"]

    def test_interior_separator_anchors_to_the_ignore_file_directory(self):
        assert _prefix_pattern("sub", "a/foo") == ["sub/a/foo"]

    def test_trailing_slash_is_a_directory_marker_not_an_anchor(self):
        # `build/` still matches at any depth; both forms keep the directory marker.
        assert _prefix_pattern("sub", "build/") == ["sub/build/", "sub/**/build/"]

    def test_negation_is_preserved_on_every_emitted_form(self):
        assert _prefix_pattern("sub", "!keep.py") == ["!sub/keep.py", "!sub/**/keep.py"]

    def test_blank_pattern_yields_nothing(self):
        assert _prefix_pattern("sub", "   ") == []


class TestNestedIgnoreMatching:
    def test_unanchored_nested_pattern_matches_at_every_depth(self, tree):
        spec = tree(["foo"])
        assert spec.match_file("sub/foo")
        assert spec.match_file("sub/a/foo")
        assert spec.match_file("sub/a/b/foo")

    def test_nested_pattern_does_not_leak_outside_its_own_subtree(self, tree):
        spec = tree(["foo"])
        assert not spec.match_file("foo")
        assert not spec.match_file("other/foo")

    def test_anchored_nested_pattern_stays_anchored(self, tree):
        spec = tree(["/foo"])
        assert spec.match_file("sub/foo")
        assert not spec.match_file("sub/a/foo")

    def test_interior_separator_pattern_stays_anchored(self, tree):
        spec = tree(["a/foo"])
        assert spec.match_file("sub/a/foo")
        assert not spec.match_file("sub/b/a/foo")

    def test_directory_pattern_matches_at_every_depth(self, tree):
        spec = tree(["build/"])
        assert spec.match_file("sub/build/out.py")
        assert spec.match_file("sub/a/build/out.py")

    def test_root_patterns_are_loaded_verbatim_alongside_nested_ones(self, tree):
        spec = tree(["foo"], root_lines=["bar"])
        assert spec.match_file("bar")
        assert spec.match_file("anywhere/bar")
        assert spec.match_file("sub/a/foo")

    def test_no_ignore_files_yields_no_spec(self, tmp_path):
        assert load_ignore_patterns(tmp_path) is None
