"""Tests for grounding_dispatch — how the workflow scripts reach the checker.

Two seams, both mechanical: turning a request into a grounding_check.py
invocation (and its exit code into a report or None), and committing the
ledger the checker rewrote without touching anything else in a shared working
tree. The checker's own behavior is test_grounding_check.py's subject; here it
is a stub, plus one live call to pin the real CLI wiring.

Run: `python3 plugins/dev/tools/test_grounding_dispatch.py` or via pytest.
"""

import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "grounding_dispatch", Path(__file__).resolve().parent / "grounding_dispatch.py"
)
grounding_dispatch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grounding_dispatch)
run_check = grounding_dispatch.run_check
commit_ledger = grounding_dispatch.commit_ledger


class patched:
    """Swap module attributes for a `with` block (this file also runs
    standalone, so no fixtures)."""

    def __init__(self, module, **attrs):
        self.module = module
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        for name, value in self.attrs.items():
            self.saved[name] = getattr(self.module, name)
            setattr(self.module, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.module, name, value)
        return False


def stub_checker(tmp, body):
    """A stand-in grounding_check.py — `body` is python run with sys.argv."""
    script = Path(tmp) / "stub_check.py"
    script.write_text("import json, sys\n" + body)
    return script


ECHO_ARGV = "print(json.dumps({'legacy': False, 'argv': sys.argv[1:]}))\n"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def make_repo(tmp) -> Path:
    """A git repo holding a slice folder with a committed grounding.md."""
    repo = Path(tmp) / "specs"
    (repo / "slices" / "074_x").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    slice_dir = repo / "slices" / "074_x"
    (slice_dir / "grounding.md").write_text("- G-001: claim\n")
    (slice_dir / "slice.md").write_text("# slice\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    return slice_dir


# -- run_check ---------------------------------------------------------------

def test_run_check_builds_the_invocation_from_its_arguments():
    with tempfile.TemporaryDirectory() as tmp:
        with patched(grounding_dispatch,
                     GROUNDING_CHECK=stub_checker(tmp, ECHO_ARGV)):
            plain = run_check(Path(tmp))
            scoped = run_check(Path(tmp), task="04a", repair=True)
            pruned = run_check(Path(tmp), prune=True)
        assert plain["argv"] == [str(Path(tmp).resolve()), "--json"]
        assert scoped["argv"][1:] == ["--json", "--task", "04a", "--repair"]
        assert pruned["argv"][1:] == ["--json", "--prune"]


def test_run_check_reads_a_relative_slice_dir_against_the_caller_cwd():
    """The child runs with the repo root as cwd, so the slice path is resolved
    here — a caller passing `../KubeCoderSpecs/slices/NNN` still works."""
    with tempfile.TemporaryDirectory() as tmp:
        with patched(grounding_dispatch,
                     GROUNDING_CHECK=stub_checker(tmp, ECHO_ARGV)):
            report = run_check(Path(tmp) / "sub" / "..")
        assert report["argv"][0] == str(Path(tmp).resolve())


def test_run_check_runs_the_checker_at_the_repo_root():
    """The checker resolves citations against the repo it runs in, and the
    plugin's scripts sit outside that repo — so the dispatch names the cwd."""
    with tempfile.TemporaryDirectory() as tmp:
        echo_cwd = stub_checker(
            tmp, "import os\nprint(json.dumps({'cwd': os.getcwd()}))\n")
        root = Path(tmp).resolve()
        with patched(grounding_dispatch, GROUNDING_CHECK=echo_cwd,
                     repo_root=lambda: root):
            assert run_check(Path(tmp))["cwd"] == str(root)


def test_repo_root_is_the_callers_git_toplevel():
    """Derived from the caller's cwd, not from this script's location: the
    plugin's tools live under ~/.claude. Outside a repo it degrades to the cwd,
    where the checker's own precondition turns it into "no report"."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_repo(tmp)
        repo = slice_dir.parents[1].resolve()
        saved = Path.cwd()
        try:
            os.chdir(slice_dir)  # a subdirectory of the repo, not its root
            assert grounding_dispatch.repo_root() == repo
            os.chdir("/")  # no git repo anywhere up the tree
            assert grounding_dispatch.repo_root() == Path("/")
        finally:
            os.chdir(saved)


def test_run_check_treats_exit_3_as_a_report_and_other_failures_as_none():
    """Exit 3 is tier 2 — drift is a normal outcome that rides the dispatch.
    Exit 2 (usage), exit 1 (unexpected), unparseable output and a checker that
    cannot run at all are all 'no report', never an exception."""
    with tempfile.TemporaryDirectory() as tmp:
        drift = stub_checker(tmp, ECHO_ARGV + "sys.exit(3)\n")
        with patched(grounding_dispatch, GROUNDING_CHECK=drift):
            assert run_check(Path(tmp))["legacy"] is False
        for code in (1, 2):
            failed = stub_checker(tmp, ECHO_ARGV + f"sys.exit({code})\n")
            with patched(grounding_dispatch, GROUNDING_CHECK=failed):
                assert run_check(Path(tmp)) is None
        garbage = stub_checker(tmp, "print('not json at all')\n")
        with patched(grounding_dispatch, GROUNDING_CHECK=garbage):
            assert run_check(Path(tmp)) is None
        not_a_dict = stub_checker(tmp, "print(json.dumps([1, 2]))\n")
        with patched(grounding_dispatch, GROUNDING_CHECK=not_a_dict):
            assert run_check(Path(tmp)) is None
        with patched(grounding_dispatch,
                     GROUNDING_CHECK=Path(tmp) / "does_not_exist.py"):
            assert run_check(Path(tmp)) is None


def test_run_check_gives_up_on_a_checker_that_hangs():
    with tempfile.TemporaryDirectory() as tmp:
        slow = stub_checker(tmp, "import time\ntime.sleep(30)\n")
        with patched(grounding_dispatch, GROUNDING_CHECK=slow,
                     CHECK_TIMEOUT=0.3):
            assert run_check(Path(tmp)) is None


def test_run_check_against_the_real_checker():
    """One live call, so the wiring (path, --json, exit code) is pinned to the
    actual CLI and not only to a stub: a slice with no ledger is `legacy`."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "074_x"
        slice_dir.mkdir()
        report = run_check(slice_dir)
        assert report["legacy"] is True
        assert report["summary"].startswith("grounding:")
        assert run_check(Path(tmp) / "no_such_slice") is None


# -- commit_ledger -----------------------------------------------------------

def test_commit_ledger_commits_the_ledger_and_nothing_else():
    """The specs tree is shared with parallel sessions: a bare `git commit -m`
    would sweep up whatever they had staged. The commit names its path, so a
    neighbour's staged file stays staged and uncommitted."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_repo(tmp)
        repo = slice_dir.parents[1]
        (slice_dir / "grounding.md").write_text("- G-001: claim (repaired)\n")
        # a parallel session's work: one file staged, one merely modified
        (slice_dir / "neighbour.md").write_text("someone else's work\n")
        git(repo, "add", "--", "slices/074_x/neighbour.md")
        (slice_dir / "slice.md").write_text("# slice, edited elsewhere\n")

        assert commit_ledger(slice_dir, "grounding: repair drifted citations")

        assert git(repo, "log", "-1", "--pretty=%s") == \
            "grounding: repair drifted citations"
        assert git(repo, "show", "--name-only", "--pretty=", "HEAD") == \
            "slices/074_x/grounding.md"
        staged = git(repo, "diff", "--cached", "--name-only")
        assert staged == "slices/074_x/neighbour.md", (
            "a parallel session's staged file must survive uncommitted")
        assert "slices/074_x/slice.md" in git(repo, "diff", "--name-only")


def test_commit_ledger_survives_a_git_that_refuses():
    with tempfile.TemporaryDirectory() as tmp:
        # nothing to commit: the ledger is unchanged since the last commit
        slice_dir = make_repo(tmp)
        assert commit_ledger(slice_dir, "grounding: nothing to do") is False
        # not a git repo at all
        assert commit_ledger(Path(tmp), "grounding: nowhere") is False


def test_commit_ledger_commits_a_ledger_that_was_never_tracked():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_repo(tmp)
        repo = slice_dir.parents[1]
        git(repo, "rm", "-q", "--cached", "slices/074_x/grounding.md")
        git(repo, "commit", "-q", "-m", "drop the ledger")
        assert commit_ledger(slice_dir, "grounding: first commit")
        assert git(repo, "show", "--name-only", "--pretty=", "HEAD") == \
            "slices/074_x/grounding.md"


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
