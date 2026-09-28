"""Tests for github_target — `Target: github:<owner>/<repo>`, cloned into the
scratch root and handled as a sibling repo path from then on.

Real git throughout: local bare repos stand in for GitHub through a patched
clone-URL template, and the scratch root is a tmp dir whose parent plays the
work root. The subject is what `ensure_clone` does with each state of the
clone path (absent, clean and behind, dirty, ahead, on a phase branch, another
repo, not a checkout), the owned case a resuming run hits, the refusal of a
repo the environment already checks out, the URL forms that refusal matches,
the target's own form, the mark `scratch_clones` reads, and the per-process
cache.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_github_target.py` or via pytest.
"""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "github_target", Path(__file__).resolve().parent / "github_target.py"
)
github_target = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(github_target)

TARGET = "github:acme/Widget"


def git(*args, cwd=None):
    """git with an identity and no signing, whatever the host's config says."""
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class world:
    """A tmp work root with a scratch root inside it and a directory of bare
    "GitHub" repos beside it; the module is pointed at both for the block and
    its cache is cleared on the way in and out."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.work = tmp / "work"
        self.work.mkdir()
        self.scratch = self.work / "scratch"
        self.remotes = tmp / "remotes"
        self.saved = (github_target.SCRATCH_ROOT, github_target.CLONE_URL)
        github_target.SCRATCH_ROOT = self.scratch
        github_target.CLONE_URL = f"file://{self.remotes}/{{owner}}/{{repo}}.git"
        github_target.reset_cache()
        return self

    def __exit__(self, *exc):
        github_target.SCRATCH_ROOT, github_target.CLONE_URL = self.saved
        github_target.reset_cache()
        self._tmp.cleanup()
        return False

    def url(self, owner="acme", repo="Widget"):
        return f"file://{self.remotes}/{owner}/{repo}.git"

    def remote(self, owner="acme", repo="Widget"):
        """A bare repo with one commit on main, and a seed checkout of it
        to push further commits from."""
        bare = self.remotes / owner / f"{repo}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        git("init", "-q", "--bare", "-b", "main", str(bare))
        seed = self.remotes / f"seed-{owner}-{repo}"
        git("clone", "-q", str(bare), str(seed))
        git("checkout", "-q", "-b", "main", cwd=seed)
        (seed / "README").write_text("one\n")
        git("add", "README", cwd=seed)
        git("commit", "-qm", "one", cwd=seed)
        git("push", "-q", "origin", "main", cwd=seed)
        return seed

    def advance(self, seed, text="two\n"):
        """One more commit on origin's main."""
        (seed / "README").write_text(text)
        git("commit", "-qam", text.strip(), cwd=seed)
        git("push", "-q", "origin", "main", cwd=seed)
        return git("rev-parse", "HEAD", cwd=seed)

    def hand_clone(self, url=None, repo="Widget"):
        """A clone at the scratch path someone made by hand (no mark)."""
        self.scratch.mkdir(exist_ok=True)
        path = self.scratch / repo
        git("clone", "-q", url or self.url(), str(path))
        return path


def refuses(fragments, target=TARGET, **kw):
    try:
        github_target.ensure_clone(target, **kw)
    except ValueError as e:
        for fragment in fragments:
            assert fragment in str(e), f"{fragment!r} not in {e}"
        return str(e)
    raise AssertionError(f"ensure_clone accepted {target}")


def mark(path):
    return subprocess.run(
        ["git", "-C", str(path), "config", "--get", github_target.MARK_KEY],
        capture_output=True, text=True).stdout.strip()


# -- the target's form ---------------------------------------------------------

def test_parse_reads_owner_and_repo_and_drops_a_dot_git():
    assert github_target.parse("github:pvginkel/RegistryDeploy") == (
        "pvginkel", "RegistryDeploy")
    assert github_target.parse("github:a.b/c_d-e.git") == ("a.b", "c_d-e")
    assert github_target.is_github("github:x/y")
    assert not github_target.is_github("../Repo")
    assert not github_target.is_github(None)


def test_a_malformed_target_is_refused_with_the_form():
    for bad in ("github:", "github:owner", "github:o/r/extra", "github:o/..",
                "github:o/.", "github:o w/r", "github:/r", "github:o/"):
        try:
            github_target.parse(bad)
        except ValueError as e:
            assert "`github:<owner>/<repo>`" in str(e), e
            continue
        raise AssertionError(f"parse accepted {bad!r}")


def test_clone_path_is_the_repo_under_the_scratch_root_and_touches_nothing():
    with world() as w:
        assert github_target.clone_path(TARGET) == w.scratch / "Widget"
        assert not w.scratch.exists()


def test_github_urls_match_in_every_form_and_any_case():
    for url in ("https://github.com/Acme/widget",
                "https://github.com/acme/Widget.git",
                "https://token@github.com/acme/Widget/",
                "git@github.com:ACME/widget.git",
                "git@github.com:acme/Widget",
                "ssh://git@github.com/acme/Widget.git",
                "ssh://git@github.com:22/acme/Widget"):
        assert github_target.origin_matches(url, "acme", "Widget"), url
    for url in ("https://github.com/acme/Widget2",
                "https://gitlab.com/acme/Widget",
                "git@github.com:other/Widget.git", ""):
        assert not github_target.origin_matches(url, "acme", "Widget"), url


# -- ensure_clone ------------------------------------------------------------

def test_an_absent_clone_is_cloned_and_marked():
    with world() as w:
        w.remote()
        path = github_target.ensure_clone(TARGET)
        assert path == w.scratch / "Widget"
        assert (path / "README").read_text() == "one\n"
        assert mark(path) == "acme/Widget"


def test_a_clone_that_fails_carries_gits_output():
    with world() as w:
        refuses(["`git clone", "failed", "reachable", "fatal:"])
        assert not (w.scratch / "Widget").exists()


def test_a_clean_clone_behind_origin_is_adopted_and_fast_forwarded():
    with world() as w:
        seed = w.remote()
        path = w.hand_clone()
        head = w.advance(seed)
        assert github_target.ensure_clone(TARGET) == path
        assert git("rev-parse", "HEAD", cwd=path) == head
        assert mark(path) == "acme/Widget"


def test_a_dirty_clone_is_refused():
    with world() as w:
        w.remote()
        path = w.hand_clone()
        (path / "README").write_text("local edit\n")
        refuses([str(path), "uncommitted changes", "README"])


def test_a_clone_ahead_of_origin_is_refused():
    with world() as w:
        w.remote()
        path = w.hand_clone()
        (path / "README").write_text("local\n")
        git("commit", "-qam", "local", cwd=path)
        refuses([str(path), "1 commit(s) on `main`", "origin/main",
                 "Push them, or delete the clone"])


def test_a_clone_on_a_phase_branch_is_refused():
    with world() as w:
        w.remote()
        path = w.hand_clone()
        git("checkout", "-q", "-b", "phase/074-P1", cwd=path)
        refuses(["`phase/074-P1`", "phase branch", "check the base branch "
                 "back out"])


def test_a_clone_of_another_repo_is_refused():
    with world() as w:
        w.remote(repo="Other")
        path = w.hand_clone(url=w.url(repo="Other"))
        refuses([str(path), "Other", "not acme/Widget", "Move it away"])


def test_a_directory_that_is_not_a_checkout_is_refused():
    with world() as w:
        (w.scratch / "Widget").mkdir(parents=True)
        refuses(["is not a git checkout"])


def test_an_owned_clone_is_checked_but_never_synced_or_refused_for_ahead():
    """A resume over the run's own clone: its base carries the merged,
    unpushed phases, and syncing or refusing it would fight the run."""
    with world() as w:
        seed = w.remote()
        path = w.hand_clone()
        (path / "README").write_text("merged phase\n")
        git("commit", "-qam", "merged phase", cwd=path)
        local = git("rev-parse", "HEAD", cwd=path)
        w.advance(seed, "origin moved\n")
        assert github_target.ensure_clone(TARGET, owned=True) == path
        assert git("rev-parse", "HEAD", cwd=path) == local
        assert mark(path) == "acme/Widget"


def test_an_owned_clone_that_is_gone_is_refused_not_recloned():
    with world() as w:
        w.remote()
        refuses(["is gone", "merged its phases into"], owned=True)
        assert not (w.scratch / "Widget").exists()


def test_a_repo_the_environment_already_checks_out_is_refused():
    """The sibling form addresses it; a second clone would split the slice's
    commits across two trees. The scratch clone itself is not a declared
    checkout."""
    with world() as w:
        w.remote()
        declared = w.work / "WidgetRepo"
        git("clone", "-q", w.url(), str(declared))
        refuses([str(declared), "use the sibling `../WidgetRepo` form"])
        assert not (w.scratch / "Widget").exists()
        assert github_target.declared_checkout("acme", "Widget") == declared


def test_a_declared_checkout_is_matched_on_a_github_origin_in_any_form():
    with world() as w:
        declared = w.work / "Widget"
        git("init", "-q", str(declared))
        git("remote", "add", "origin", "git@github.com:ACME/widget.git",
            cwd=declared)
        assert github_target.declared_checkout("acme", "Widget") == declared
        assert github_target.declared_checkout("acme", "Other") is None


def test_the_scratch_clone_is_never_its_own_declared_checkout():
    with world() as w:
        w.remote()
        github_target.ensure_clone(TARGET)
        assert github_target.declared_checkout("acme", "Widget") is None


def test_a_process_ensures_a_target_once():
    with world() as w:
        seed = w.remote()
        path = github_target.ensure_clone(TARGET)
        first = git("rev-parse", "HEAD", cwd=path)
        w.advance(seed)
        assert github_target.ensure_clone(TARGET) == path
        assert git("rev-parse", "HEAD", cwd=path) == first, "synced twice"
        github_target.reset_cache()
        github_target.ensure_clone(TARGET)
        assert git("rev-parse", "HEAD", cwd=path) != first


# -- scratch_clones ------------------------------------------------------------

def test_scratch_clones_lists_the_marked_clones_only():
    with world() as w:
        assert github_target.scratch_clones() == []
        w.remote()
        w.remote(repo="Hand")
        w.hand_clone(url=w.url(repo="Hand"), repo="Hand")
        (w.scratch / "notes").mkdir()
        path = github_target.ensure_clone(TARGET)
        assert github_target.scratch_clones() == [path]


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    failures = 0
    for _fn in _tests:
        try:
            _fn()
            print(f"ok  {_fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {_fn.__name__}: {e}")
    print(f"\n{len(_tests) - failures} passed, {failures} failed")
    if failures:
        sys.exit(1)
