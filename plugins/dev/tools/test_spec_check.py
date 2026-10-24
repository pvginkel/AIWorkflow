"""Tests for spec_check — the shape of what changed in a spec repo since a
base commit: whitespace and conflict markers, Markdown pipe tables and code
fences, JSON syntax.

The repos are git's own: a throwaway repo per test (real `git init`, the
user's and the system's git config held out of both the commits and the
tool's run), a base commit, and then the change the check reads — commits
on top of it, staged and unstaged edits, untracked files. The CLI runs as a
subprocess, as the run loop runs it; the Markdown rules are also read
straight off `markdown_problems` and `table_cells`.

Stdlib only, like the workflow's other suites.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_spec_check.py` or via pytest.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "spec_check.py"
_spec = importlib.util.spec_from_file_location("spec_check", TOOL)
spec_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spec_check)
markdown_problems = spec_check.markdown_problems
table_cells = spec_check.table_cells

# git as the suite runs it, the tool's runs included: none of the machine's
# own config (a whitespace rule, a colour setting) reaches the checks.
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}

TABLE = "| a | b |\n|---|:-:|\n| 1 | 2 |\n"


class Repo:
    """A throwaway git repo with a base commit: write, commit, check."""

    def __init__(self, root, files=None):
        self.root = Path(root)
        self.git("init", "-q", "-b", "main")
        self.write(files or {"README.md": "# specs\n"})
        self.base = self.commit("base")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=GIT_ENV,
                              capture_output=True, text=True,
                              check=True).stdout.strip()

    def write(self, files):
        """Write (or, for None, delete) each path."""
        for path, text in files.items():
            target = self.root / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(text, bytes):
                target.write_bytes(text)
            else:
                target.write_text(text)

    def commit(self, message, files=None):
        if files:
            self.write(files)
        self.git("add", "-A")
        self.git("commit", "-qm", message, "--allow-empty")
        return self.git("rev-parse", "HEAD")

    def check(self, *args, base=None, cwd=None):
        """The CLI's (exit code, stdout lines, stderr) over this repo."""
        argv = [sys.executable, str(TOOL), "--base", base or self.base, *args]
        if not args and cwd is None:
            argv.append(str(self.root))
        result = subprocess.run(argv, cwd=cwd or self.root, env=GIT_ENV,
                                capture_output=True, text=True)
        return result.returncode, result.stdout.splitlines(), result.stderr


def repo(files=None):
    tmp = tempfile.TemporaryDirectory()
    return Repo(tmp.name, files), tmp


def summary(repo_, problems, files, changed):
    since = (f"{changed} file{'s' if changed != 1 else ''} changed since "
             f"{repo_.base[:12]}")
    if not problems:
        return f"spec_check: clean — {since}"
    return (f"spec_check: {problems} problem{'s' if problems != 1 else ''} in "
            f"{files} file{'s' if files != 1 else ''}, of {since}")


# -- the CLI over a real repo -------------------------------------------------

def test_a_clean_change_passes():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"docs/page.md": "# Page\n\n" + TABLE,
                        "data/thing.json": '{"a": [1, 2]}\n'})
        r.write({"README.md": "# specs\n\nMore.\n"})
        code, out, err = r.check()
        assert (code, err) == (0, "")
        assert out == [summary(r, 0, 0, 3)]


def test_nothing_changed_is_clean():
    r, tmp = repo()
    with tmp:
        assert r.check()[:2] == (0, [summary(r, 0, 0, 0)])


def test_a_ragged_table_is_a_problem_at_its_row():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"docs/page.md": "# Page\n\n| a | b |\n|---|---|\n"
                                        "| 1 | 2 | 3 |\n| 4 | 5 |\n| 6 |\n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == [
            "docs/page.md:5: a table row with 3 cells, its header 2",
            "docs/page.md:7: a table row with 1 cell, its header 2",
            summary(r, 2, 1, 1)]


def test_a_pipe_in_a_code_span_or_escaped_is_no_cell_separator():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"page.md": "| cmd | what |\n|---|---|\n"
                                   "| `a | b` | piped |\n"
                                   "| a \\| b | escaped |\n"
                                   "| ``x ` | y`` | a span of two |\n"})
        assert r.check()[:2] == (0, [summary(r, 0, 0, 1)])


def test_an_unclosed_fence_is_a_problem_and_fenced_lines_are_no_table():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"page.md": "```text\n| a | b |\n| 1 |\n```\n\n"
                                   "~~~~\n```\n| x |\n~~~~\n\n"
                                   "Prose.\n\n````md\n```\nnever closed\n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == ["page.md:13: the code fence opened here (````) is "
                       "never closed", summary(r, 1, 1, 1)]


def test_bad_json_is_a_problem_at_its_line():
    r, tmp = repo({"README.md": "# specs\n", "old.json": "{}\n"})
    with tmp:
        r.commit("P1", {"state.json": '{\n  "a": 1\n  "b": 2\n}\n',
                        "latin.json": b'{"a": "\xe9"}\n', "old.json": None})
        code, out, _ = r.check()
        assert code == 1
        assert out[0] == "latin.json:1: not UTF-8 text, so no JSON"
        assert out[1] == "state.json:3: invalid JSON: Expecting ',' delimiter"
        # a deleted file is changed, and has nothing to check
        assert out[2:] == [summary(r, 2, 2, 3)]


def test_whitespace_errors_and_conflict_markers_are_gits_own_findings():
    r, tmp = repo({"README.md": "# specs\n", "tool.py": "x = 1\n"})
    with tmp:
        r.commit("P1", {"page.md": "Line one.  \nLine two.\n",
                        "tool.py": "x = 1\ny = 2 \n"})
        # uncommitted, as a writer's unresolved merge leaves it
        r.write({"README.md": "# specs\n<<<<<<< HEAD\nours\n=======\n"
                              "theirs\n>>>>>>> other\n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == ["README.md:2: leftover conflict marker",
                       "README.md:4: leftover conflict marker",
                       "README.md:6: leftover conflict marker",
                       "page.md:1: trailing whitespace.",
                       "tool.py:2: trailing whitespace.",
                       summary(r, 5, 3, 3)]


def test_untracked_files_are_checked_and_ignored_ones_are_not():
    r, tmp = repo({"README.md": "# specs\n", ".gitignore": "scratch/\n"})
    with tmp:
        r.write({"new/page.md": "| a | b |\n| 1 | 2 |\n",
                 "new/notes.txt": "tail \n",
                 "new/data.json": "[1,\n",
                 "scratch/junk.md": "| a |\n|---|\n| 1 | 2 |\n  \n"})
        code, out, _ = r.check()
        assert code == 1
        assert out[0].startswith("new/data.json:2: invalid JSON: ")
        assert out[1:] == [
            "new/notes.txt:1: trailing whitespace.",
            "new/page.md:1: a table header row with no delimiter row under "
            "it",
            summary(r, 3, 3, 3)]


def test_debt_in_an_unchanged_file_or_line_never_reds():
    r, tmp = repo({"old.md": "| a | b |\n|---|---|\n| 1 |\n",
                   "old.json": "{,}\n",
                   "page.md": "Old line.  \n\nText.\n"})
    with tmp:
        r.commit("P1", {"page.md": "Old line.  \n\nText, changed.\n",
                        "fresh.md": "# Fresh\n"})
        assert r.check()[:2] == (0, [summary(r, 0, 0, 2)])


RAGGED = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 |\n"


def test_an_old_ragged_table_in_a_touched_file_stays_green():
    """PilotAppSpecs' design/database.md carries a ragged table: a phase
    editing one line elsewhere in it is not held to fixing that table."""
    r, tmp = repo({"page.md": "# Page\n\nIntro.\n\n" + RAGGED
                              + "\nOutro.\n"})
    with tmp:
        r.commit("P1", {"page.md": "# Page\n\nIntro, edited.\n\n" + RAGGED
                                   + "\nOutro, edited.\n"})
        assert r.check()[:2] == (0, [summary(r, 0, 0, 1)])
        # nor a line added right after it, past the blank that ends it
        r.write({"page.md": "# Page\n\nIntro, edited.\n\n" + RAGGED
                            + "\nNew line.\nOutro, edited.\n"})
        assert r.check()[0] == 0


def test_a_table_the_phase_edits_is_checked_whole():
    r, tmp = repo({"page.md": "# Page\n\n" + RAGGED + "\nText.\n\n"
                              + RAGGED})
    with tmp:
        # a fine row of the first table changed: its old ragged row is the
        # phase's now; the second table, untouched, is not
        r.commit("P1", {"page.md": "# Page\n\n" + RAGGED.replace("1 | 2",
                                                                 "1 | 22")
                                   + "\nText.\n\n" + RAGGED})
        code, out, _ = r.check()
        assert code == 1
        assert out == ["page.md:6: a table row with 1 cell, its header 2",
                       summary(r, 1, 1, 1)]
    r, tmp = repo({"page.md": "# Page\n\n" + TABLE})
    with tmp:
        r.commit("P1", {"page.md": "# Page\n\n" + TABLE + "| 3 | 4 | 5 |\n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == ["page.md:6: a table row with 3 cells, its header 2",
                       summary(r, 1, 1, 1)]


def test_an_old_unclosed_fence_stays_green_and_a_new_one_reds():
    r, tmp = repo({"old.md": "# Old\n\n```\nnever closed\n",
                   "fine.md": "# Fine\n\n```\ncode\n```\n"})
    with tmp:
        r.commit("P1", {"old.md": "# Old, edited\n\n```\nnever closed\n",
                        "fine.md": "# Fine\n\n```\ncode\n```\n\n~~~\nopen\n",
                        "new.md": "````\nopen\n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == [
            "fine.md:7: the code fence opened here (~~~) is never closed",
            "new.md:1: the code fence opened here (````) is never closed",
            summary(r, 2, 2, 3)]


def test_json_that_did_not_parse_at_the_base_stays_green_and_new_breaks_red():
    r, tmp = repo({"old.json": '{"a": 1,}\n', "fine.json": '{"a": 1}\n'})
    with tmp:
        r.commit("P1", {"old.json": '{"a": 2,}\n',
                        "fine.json": '{"a": 1\n',
                        "new.json": "[\n"})
        code, out, _ = r.check()
        assert code == 1
        assert [line.split(": invalid JSON")[0] for line in out[:2]] \
            == ["fine.json:2", "new.json:2"]
        assert out[2:] == [summary(r, 2, 2, 3)]


def test_only_a_tables_added_lines_make_it_the_changes():
    lines = RAGGED.splitlines()
    text = "Intro.\n\n" + RAGGED
    found = [(6, "a table row with 1 cell, its header 2")]
    assert markdown_problems(text, base=text, added=set()) == []
    assert markdown_problems(text, base=text, added={1}) == []
    for n in range(3, 3 + len(lines)):
        assert markdown_problems(text, base=text, added={n}) == found, n
    assert markdown_problems(text) == found


def test_committed_staged_and_unstaged_changes_are_all_the_change():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"a.md": "a \n"})
        r.write({"b.md": "b \n"})
        r.git("add", "b.md")
        r.write({"README.md": "# specs \n"})
        code, out, _ = r.check()
        assert code == 1
        assert out == ["README.md:1: trailing whitespace.",
                       "a.md:1: trailing whitespace.",
                       "b.md:1: trailing whitespace.", summary(r, 3, 3, 3)]


def test_it_writes_nothing_to_the_tree_or_the_index():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"a.md": "| a |\n| 1 |\n"})
        r.write({"b.md": "b \n", "README.md": "changed\n", "c.md": "c\n"})
        r.git("add", "b.md")
        # files older than the index, so no git rewrites it to settle a
        # racily clean entry, then the index settled once
        for path in ("a.md", "b.md", "README.md", "c.md"):
            os.utime(r.root / path, (1_000_000_000, 1_000_000_000))
        status = r.git("status", "--porcelain")
        index = (r.root / ".git" / "index").read_bytes()
        assert r.check()[0] == 1
        assert (r.root / ".git" / "index").read_bytes() == index
        assert r.git("status", "--porcelain") == status


def test_the_repo_defaults_to_the_current_directory_and_its_toplevel():
    r, tmp = repo()
    with tmp:
        r.commit("P1", {"docs/deep/page.md": "x \n"})
        code, out, _ = r.check(cwd=r.root / "docs" / "deep")
        assert code == 1
        assert out == ["docs/deep/page.md:1: trailing whitespace.",
                       summary(r, 1, 1, 1)]
        # a subdirectory named is its repo's toplevel, too
        assert r.check(str(r.root / "docs"))[1] == out


def test_a_bad_base_or_a_directory_outside_git_is_a_usage_error():
    r, tmp = repo()
    with tmp, tempfile.TemporaryDirectory() as bare:
        top = r.git("rev-parse", "--show-toplevel")
        code, out, err = r.check(base="no-such-ref")
        assert (code, out) == (2, [])
        assert err == f"spec_check: --base no-such-ref is not a commit in " \
                      f"{top}\n"
        blob = r.git("rev-parse", "HEAD:README.md")
        assert r.check(base=blob)[0] == 2, "a blob is no commit"
        code, out, err = r.check(bare, base="HEAD")
        assert (code, out) == (2, [])
        assert err == f"spec_check: {bare} is not in a git repository\n"
        result = subprocess.run([sys.executable, str(TOOL), str(r.root)],
                                env=GIT_ENV, capture_output=True, text=True)
        assert result.returncode == 2 and "--base" in result.stderr


def test_a_base_given_as_a_ref_is_checked_as_its_sha():
    r, tmp = repo()
    with tmp:
        r.git("branch", "spec-base")
        r.commit("P1", {"a.md": "a\n"})
        code, out, _ = r.check(base="spec-base")
        assert (code, out) == (0, [summary(r, 0, 0, 1)])


# -- the Markdown rules --------------------------------------------------------

def test_a_table_needs_its_delimiter_row_with_the_headers_cell_count():
    assert markdown_problems(TABLE) == []
    assert markdown_problems("| a | b |\n| 1 | 2 |\n| 3 | 4 |\n") == [
        (1, "a table header row with no delimiter row under it")]
    assert markdown_problems("| a | b |\n|---|---|---|\n| 1 | 2 |\n") == [
        (2, "the table's delimiter row has 3 cells, its header 2")]
    assert markdown_problems("Text.\n\n|---|---|\n| 1 | 2 |\n") == [
        (3, "a table delimiter row with no header row above it")]
    # a table split by a blank line: the second half has no header
    assert markdown_problems(TABLE + "\n| 3 | 4 |\n| 5 | 6 |\n") == [
        (5, "a table header row with no delimiter row under it")]


def test_a_table_without_edge_pipes_is_a_table_and_a_heading_is_not():
    assert markdown_problems("a | b\n--|--\n1 | 2\n") == []
    assert markdown_problems("a | b\n--|--\n1 | 2 | 3\n") == [
        (3, "a table row with 3 cells, its header 2")]
    # a pipe in a setext heading's text, a pipe in prose: no table
    assert markdown_problems("Either a | b\n---\n\nSay x | y here.\n") == []
    # a table in a list item is indented
    assert markdown_problems("- item\n\n  | a | b |\n  |---|---|\n  | 1 |\n"
                             ) == [(5, "a table row with 1 cell, its header 2")]


def test_a_row_ends_the_table_at_the_first_line_without_a_pipe():
    assert markdown_problems(TABLE + "After the table.\n| x |\n") == [
        (5, "a table header row with no delimiter row under it")]


def test_table_cells_split_on_unescaped_pipes_outside_code_spans():
    assert table_cells("| a | b |") == ["a", "b"]
    assert table_cells("a | b") == ["a", "b"]
    assert table_cells("| a |  |") == ["a", ""]
    assert table_cells("| `x|y` | \\| |") == ["`x|y`", "\\|"]
    # a backtick run with no closing run of its length is literal
    assert table_cells("| `x | y |") == ["`x", "y"]
    assert table_cells("| ``a`|`b`` | c |") == ["``a`|`b``", "c"]
    assert table_cells("no pipe here") is None
    assert table_cells("`a|b`") is None


def test_fences_close_on_their_own_character_and_length():
    text = "~~~\n```\n| a |\n~~~\n````\n```\n````\n``` not a close ```\n"
    # the last line opens no fence: its info string holds backticks
    assert markdown_problems(text) == []
    assert markdown_problems("   ```python\ncode\n") == [
        (1, "the code fence opened here (```) is never closed")]


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
