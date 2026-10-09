"""Tests for spec_commit — committing an agent's own change to a shared spec
file while another writer's uncommitted edit in it stays where it is.

A throwaway spec repo is built per test (real `git init`, a DAG-like file
committed), and the tool runs in-process against git itself: the merge, the
temporary index, the guard hook, the lease and the compare-and-swap are all
git's or the kernel's, never a fake. Every refusal test asserts that HEAD,
the real index and the working tree are exactly as they were.

Stdlib only, like the workflow's other suites — `@with_workspace` stands in for
the fixture, so each test still takes `ws` and still collects under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_spec_commit.py` or via pytest.
"""

import contextlib
import fcntl
import importlib.util
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("spec_commit", TOOLS / "spec_commit.py")
spec_commit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spec_commit)

# Line 3 is the operator's checkbox, line 4 sits right next to it, line 5 one
# further, line 8 well away.
DAG_LINES = [
    "# Slice DAG",
    "",
    "- [ ] 101 — store hardening",
    "- [ ] 102 — toolchain sweep",
    "- [ ] 103 — describe fields",
    "",
    "## Lane B",
    "- [ ] 201 — worker port",
    "- [ ] 202 — wire contracts",
]
DAG = "\n".join(DAG_LINES) + "\n"


def edit_line(text, number, new):
    """`text` with its 1-based line `number` replaced."""
    lines = text.split("\n")
    lines[number - 1] = new
    return "\n".join(lines)


TICK = "- [x] 101 — store hardening"
TICKED = edit_line(DAG, 3, TICK)
AGENT = "- [ ] 201 — worker port (blocked on 101)"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def with_workspace(fn):
    """A throwaway directory per test, handed in as `ws`.

    The wrapper takes no arguments, so pytest collects it as a plain test —
    hence no functools.wraps, which would expose the wrapped signature and
    have pytest demand a `ws` fixture this suite does not define.
    """
    def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            fn(Path(tmp).resolve())
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def make_repo(ws, name="spec", files=None):
    """A spec repo with DAG.md and README.md committed on `main`."""
    repo = ws / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t"), ("user.name", "t"),
                       ("commit.gpgsign", "false")):
        git(repo, "config", key, value)
    for rel, text in (files or {"DAG.md": DAG, "README.md": "# specs\n"}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    return repo


@contextlib.contextmanager
def phase_branch(value):
    """DEV_PHASE_BRANCH as given (None: unset) for the call, restored after —
    a suite run inside a phase session must not leak the driver's value."""
    saved = os.environ.pop("DEV_PHASE_BRANCH", None)
    if value is not None:
        os.environ["DEV_PHASE_BRANCH"] = value
    try:
        yield
    finally:
        os.environ.pop("DEV_PHASE_BRANCH", None)
        if saved is not None:
            os.environ["DEV_PHASE_BRANCH"] = saved


def run_cli(*argv, phase=None):
    """main() with its streams captured — (exit code, stdout, stderr).

    argparse leaves through SystemExit on a usage error; that is a CLI result
    like any other here, so it comes back as a code too.
    """
    out, err = io.StringIO(), io.StringIO()
    with phase_branch(phase), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            code = spec_commit.main([str(arg) for arg in argv])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def snap(path):
    """The token `snap` prints for one path."""
    code, out, err = run_cli("snap", path)
    assert code == 0, err
    return out.split()[0]


def state(repo):
    """Everything a refused commit must leave alone: HEAD, the real index,
    and the working tree (tracked diffs and untracked files)."""
    return (git(repo, "rev-parse", "HEAD"), git(repo, "ls-files", "-s"),
            git(repo, "diff"),
            git(repo, "status", "--porcelain", "--untracked-files=all"))


def head_file(repo, rel, rev="HEAD"):
    return git(repo, "show", f"{rev}:{rel}")


@contextlib.contextmanager
def patched(name, value):
    original = getattr(spec_commit, name)
    setattr(spec_commit, name, value)
    try:
        yield original
    finally:
        setattr(spec_commit, name, original)


# ---------------------------------------------------------------------------
# snap
# ---------------------------------------------------------------------------

@with_workspace
def test_snap_of_a_clean_tracked_file_says_there_is_no_edit_in_it(ws):
    repo = make_repo(ws)
    code, out, _ = run_cli("snap", repo / "DAG.md")
    assert code == 0
    token, rest = out.strip().split("  ", 1)
    path, sha = token.rsplit("@", 1)
    assert path == str(repo / "DAG.md")
    assert len(sha) == 12 and int(sha, 16) >= 0
    assert git(repo, "rev-parse", "HEAD:DAG.md").startswith(sha)
    assert rest == "— no uncommitted edit in it"


@with_workspace
def test_snap_of_a_dirty_file_stores_it_and_says_the_edit_is_not_yours(ws):
    repo = make_repo(ws)
    (repo / "DAG.md").write_text(TICKED)
    code, out, _ = run_cli("snap", repo / "DAG.md")
    assert code == 0
    token = out.split()[0]
    sha = token.rsplit("@", 1)[1]
    assert git(repo, "cat-file", "blob", sha) == TICKED
    assert "holds an uncommitted edit that is not yours" in out
    assert "your commit leaves it out" in out


@with_workspace
def test_snap_of_a_new_path_or_an_untracked_file_gives_the_plain_path(ws):
    repo = make_repo(ws)
    (repo / "notes.md").write_text("someone's notes\n")
    new, untracked = repo / "slices" / "123_x" / "plan.md", repo / "notes.md"
    code, out, _ = run_cli("snap", new, untracked)
    assert code == 0
    first, second = out.strip().splitlines()
    assert first.split()[0] == str(new)
    assert "does not exist yet" in first and "plain path" in first
    assert second.split()[0] == str(untracked)
    assert "a file you created is yours" in second
    assert "someone else created is theirs" in second


@with_workspace
def test_snap_takes_relative_paths_against_the_cwd(ws):
    repo = make_repo(ws, files={"slices/DAG.md": DAG})
    saved = os.getcwd()
    os.chdir(repo / "slices")
    try:
        code, out, _ = run_cli("snap", "DAG.md")
    finally:
        os.chdir(saved)
    assert code == 0
    assert out.split()[0].startswith("DAG.md@")


@with_workspace
def test_snap_refuses_a_directory_and_snapshots_nothing(ws):
    repo = make_repo(ws)
    (repo / "DAG.md").write_text(TICKED)
    (repo / "slices").mkdir()
    blob = git(repo, "hash-object", "DAG.md").strip()
    code, out, err = run_cli("snap", repo / "DAG.md", repo / "slices")
    assert code == 2
    assert "directory" in err and out == ""
    # Every path is checked before any is stored.
    missing = subprocess.run(["git", "cat-file", "-e", blob], cwd=repo)
    assert missing.returncode != 0


@with_workspace
def test_snap_refuses_a_symlink_and_a_tracked_file_missing_from_the_tree(ws):
    repo = make_repo(ws)
    (repo / "link.md").symlink_to("DAG.md")
    code, _, err = run_cli("snap", repo / "link.md")
    assert code == 2 and "symlink" in err
    (repo / "README.md").unlink()
    code, _, err = run_cli("snap", repo / "README.md")
    assert code == 2 and "missing from the working tree" in err


@with_workspace
def test_snap_refuses_paths_in_two_repos(ws):
    one, two = make_repo(ws, "one"), make_repo(ws, "two")
    code, out, err = run_cli("snap", one / "DAG.md", two / "DAG.md")
    assert code == 2
    assert "more than one git work tree" in err and out == ""


# ---------------------------------------------------------------------------
# commit — the merge
# ---------------------------------------------------------------------------

@with_workspace
def test_commit_takes_only_the_agents_edit_and_leaves_theirs_uncommitted(ws):
    """The case the tool exists for: the operator's tick on line 3 stays in
    the working tree, the agent's edit on line 8 goes into HEAD."""
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 8, AGENT))

    code, out, err = run_cli("commit", "-m", "dag: 201 waits on 101", token)
    assert code == 0, err
    assert head_file(repo, "DAG.md") == edit_line(DAG, 8, AGENT)
    assert dag.read_bytes() == edit_line(TICKED, 8, AGENT).encode()
    assert git(repo, "diff", "--cached") == ""
    diff = git(repo, "diff", "-U0")
    assert f"+{TICK}" in diff and AGENT not in diff
    assert "committed " in out and "on main: dag: 201 waits on 101" in out
    assert "still in the working tree, uncommitted" in out
    assert git(repo, "log", "-1", "--format=%s") == "dag: 201 waits on 101\n"


@with_workspace
def test_an_edit_on_the_line_next_to_theirs_is_refused(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 4, "- [ ] 102 — toolchain sweep (split)"))
    before = state(repo)

    code, out, err = run_cli("commit", "-m", "dag: split 102", token)
    assert code == 3
    assert out == ""
    assert "touches the lines of an uncommitted edit that is not yours" in err
    assert f"+{TICK}" in err and "+- [ ] 102 — toolchain sweep (split)" in err
    assert "Take your change back out" in err and "Nothing committed" in err
    assert state(repo) == before


@with_workspace
def test_an_edit_one_line_further_from_theirs_merges(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    edited = edit_line(TICKED, 5, "- [ ] 103 — describe fields (split)")
    dag.write_text(edited)
    code, _, err = run_cli("commit", "-m", "dag: split 103", token)
    assert code == 0, err
    assert head_file(repo, "DAG.md") == edit_line(DAG, 5, "- [ ] 103 — describe fields (split)")
    assert dag.read_text() == edited


@with_workspace
def test_an_edit_on_their_line_is_refused(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 3, "- [x] 101 — store hardening (done)"))
    before = state(repo)
    code, _, err = run_cli("commit", "-m", "dag: note 101", token)
    assert code == 3
    assert "touches the lines" in err
    assert state(repo) == before


@with_workspace
def test_refusal_is_all_or_nothing(ws):
    repo = make_repo(ws)
    dag, readme = repo / "DAG.md", repo / "README.md"
    dag.write_text(TICKED)
    tokens = [snap(dag), snap(readme)]
    dag.write_text(edit_line(TICKED, 4, "- [ ] 102 — mine"))
    readme.write_text("# specs\n\nA clean edit of mine.\n")
    (repo / "new.md").write_text("mine\n")
    before = state(repo)
    code, _, err = run_cli("commit", "-m", "mixed", *tokens, repo / "new.md")
    assert code == 3
    assert "DAG.md" in err and "README.md:" not in err
    assert state(repo) == before


@with_workspace
def test_plain_and_snapshot_paths_commit_together_and_leave_the_rest_alone(ws):
    """Another session's staged file stays staged and out of the commit; an
    unrelated dirty file stays dirty."""
    repo = make_repo(ws, files={"DAG.md": DAG, "README.md": "# specs\n",
                                "staged.md": "one\n", "dirty.md": "one\n"})
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 8, AGENT))
    plan = repo / "slices" / "123_x" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n")
    (repo / "staged.md").write_text("two, staged by another session\n")
    git(repo, "add", "staged.md")
    (repo / "dirty.md").write_text("two, someone's\n")

    code, _, err = run_cli("commit", "-m", "slice 123: plan", token, plan)
    assert code == 0, err
    files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == ["DAG.md", "slices/123_x/plan.md"]
    assert head_file(repo, "slices/123_x/plan.md") == "# plan\n"
    assert git(repo, "diff", "--cached", "--name-only").split() == ["staged.md"]
    assert sorted(git(repo, "diff", "--name-only").split()) == ["DAG.md", "dirty.md"]
    assert (repo / "dirty.md").read_text() == "two, someone's\n"
    assert git(repo, "status", "--porcelain", "--", "slices").strip() == ""


@with_workspace
def test_head_moved_since_the_snapshot_merges_onto_the_new_head(ws):
    """The operator commits the tick between the agent's snap and commit: the
    commit lands on top of it and the working file is then fully committed."""
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    git(repo, "commit", "-qam", "tick 101")
    edited = edit_line(TICKED, 4, "- [ ] 102 — mine, next to the tick")
    dag.write_text(edited)

    code, out, err = run_cli("commit", "-m", "dag: 102", token)
    assert code == 0, err
    assert head_file(repo, "DAG.md") == edited
    assert head_file(repo, "DAG.md", "HEAD~1") == TICKED
    assert "still in the working tree" not in out
    assert git(repo, "status", "--porcelain") == ""


@with_workspace
def test_deleting_a_file_with_no_edit_of_theirs_commits_the_deletion(ws):
    repo = make_repo(ws)
    token = snap(repo / "README.md")
    (repo / "README.md").unlink()
    code, _, err = run_cli("commit", "-m", "drop the readme", token)
    assert code == 0, err
    assert "README.md" not in git(repo, "ls-tree", "--name-only", "HEAD")
    assert git(repo, "status", "--porcelain") == ""


@with_workspace
def test_deleting_a_file_that_holds_their_edit_is_refused(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.unlink()
    before = state(repo)
    code, _, err = run_cli("commit", "-m", "drop the dag", token)
    assert code == 3
    assert "you deleted it" in err and "git cat-file blob" in err
    assert state(repo) == before


@with_workspace
def test_a_snapshot_taken_after_the_edit_commits_nothing(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(edit_line(DAG, 8, AGENT))
    token = snap(dag)
    before = state(repo)
    code, out, err = run_cli("commit", "-m", "dag", token)
    assert code == 0
    assert "no change of yours in" in err and "counts as not yours" in err
    assert "nothing committed" in out
    assert state(repo) == before


@with_workspace
def test_someone_staging_the_same_file_keeps_their_staged_version(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    git(repo, "add", "DAG.md")
    staged_blob = git(repo, "rev-parse", ":DAG.md").strip()
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 8, AGENT))
    code, _, err = run_cli("commit", "-m", "dag", token)
    assert code == 0, err
    assert head_file(repo, "DAG.md") == edit_line(DAG, 8, AGENT)
    assert git(repo, "rev-parse", ":DAG.md").strip() == staged_blob


@with_workspace
def test_two_messages_are_two_paragraphs(ws):
    repo = make_repo(ws)
    (repo / "new.md").write_text("mine\n")
    code, _, err = run_cli("commit", "-m", "subject", "-m", "the body", repo / "new.md")
    assert code == 0, err
    assert git(repo, "log", "-1", "--format=%B") == "subject\n\nthe body\n\n"


@with_workspace
def test_an_executable_file_keeps_its_mode(ws):
    repo = make_repo(ws, files={"run.sh": "#!/bin/sh\necho one\n\n\n\necho two\n"})
    script = repo / "run.sh"
    script.chmod(0o755)
    git(repo, "add", "run.sh")
    git(repo, "commit", "-qm", "exec")
    script.write_text("#!/bin/sh\necho ONE\n\n\n\necho two\n")
    token = snap(script)
    script.write_text("#!/bin/sh\necho ONE\n\n\n\necho TWO\n")
    code, _, err = run_cli("commit", "-m", "two", token)
    assert code == 0, err
    assert git(repo, "ls-tree", "HEAD", "run.sh").startswith("100755 ")
    assert head_file(repo, "run.sh") == "#!/bin/sh\necho one\n\n\n\necho TWO\n"


# ---------------------------------------------------------------------------
# commit — usage
# ---------------------------------------------------------------------------

@with_workspace
def test_usage_errors_exit_2_and_commit_nothing(ws):
    repo = make_repo(ws)
    (repo / "new.md").write_text("mine\n")
    before = state(repo)
    code, _, _ = run_cli("commit", repo / "new.md")
    assert code == 2
    code, _, _ = run_cli("commit", "-m", "nothing")
    assert code == 2
    code, _, err = run_cli("commit", "-m", "x", f"{repo / 'DAG.md'}@0123456789ab")
    assert code == 2 and "no such snapshot" in err
    code, _, err = run_cli("commit", "-m", "x", repo / "nowhere.md")
    assert code == 2 and "nowhere.md" in err
    # the work tree's root as a plain path would be `git add -- .`
    code, _, err = run_cli("commit", "-m", "x", repo)
    assert code == 2 and "whole work tree" in err
    assert state(repo) == before


@with_workspace
def test_items_in_two_repos_exit_2(ws):
    one, two = make_repo(ws, "one"), make_repo(ws, "two")
    (one / "a.md").write_text("a\n")
    (two / "b.md").write_text("b\n")
    code, _, err = run_cli("commit", "-m", "x", one / "a.md", two / "b.md")
    assert code == 2 and "more than one git work tree" in err


# ---------------------------------------------------------------------------
# commit — hooks, the lease, the compare-and-swap
# ---------------------------------------------------------------------------

def install_hook(repo, source=None, body="#!/bin/sh\necho 'hook says no' >&2\nexit 1\n"):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    if source:
        shutil.copy(source, hook)
    else:
        hook.write_text(body)
    hook.chmod(0o755)


@with_workspace
def test_a_refusing_pre_commit_hook_stops_the_commit(ws):
    repo = make_repo(ws)
    install_hook(repo)
    (repo / "new.md").write_text("mine\n")
    before = state(repo)
    code, _, err = run_cli("commit", "-m", "x", repo / "new.md")
    assert code == 4
    assert "hook says no" in err
    assert "flock -s" in err and str(repo / ".git" / "dev-spec-tree.lock") in err
    assert str(repo / "new.md") in err
    assert state(repo) == before


@with_workspace
def test_the_hook_sees_the_commit_being_made_not_the_real_index(ws):
    repo = make_repo(ws)
    install_hook(repo, body="#!/bin/sh\ngit diff --cached --name-only "
                            "> \"$(git rev-parse --git-dir)/seen\"\n")
    (repo / "other.md").write_text("staged by someone\n")
    git(repo, "add", "other.md")
    (repo / "new.md").write_text("mine\n")
    code, _, err = run_cli("commit", "-m", "x", repo / "new.md")
    assert code == 0, err
    assert (repo / ".git" / "seen").read_text().split() == ["new.md"]


@with_workspace
def test_the_spec_tree_guard_refuses_a_phase_branch_unless_it_is_yours(ws):
    repo = make_repo(ws)
    install_hook(repo, source=TOOLS / "spec-tree-guard.sh")
    git(repo, "checkout", "-q", "-b", "phase/x")
    (repo / "new.md").write_text("mine\n")
    before = state(repo)
    code, _, err = run_cli("commit", "-m", "x", repo / "new.md")
    assert code == 4
    assert "spec-tree guard: commit refused" in err
    assert "flock -s" in err
    assert state(repo) == before

    code, out, err = run_cli("commit", "-m", "x", repo / "new.md", phase="phase/x")
    assert code == 0, err
    assert "on phase/x: x" in out
    assert head_file(repo, "new.md") == "mine\n"


@contextlib.contextmanager
def lease_held_by_a_phase(repo, note):
    """The run loop's exclusive hold: a separate open file description, so
    it conflicts with the tool's own even inside this process."""
    git_dir = repo / ".git"
    (git_dir / "dev-spec-tree.holder").write_text(note)
    fd = os.open(git_dir / "dev-spec-tree.lock", os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield git_dir / "dev-spec-tree.lock"
    finally:
        os.close(fd)


@with_workspace
def test_a_held_lease_stops_the_commit_and_shows_the_holder(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 8, AGENT))
    before = state(repo)
    with lease_held_by_a_phase(repo, "slice 123 P2 — phase/123-p2\npid: 42\n") as lease:
        code, out, err = run_cli("commit", "-m", "dag", token)
    assert code == 4
    assert out == ""
    assert "    slice 123 P2 — phase/123-p2\n    pid: 42" in err
    assert f"flock -s {lease} python3 " in err
    assert str(TOOLS / "spec_commit.py") in err and token in err
    assert state(repo) == before


@with_workspace
def test_the_running_phases_own_session_commits_under_the_held_lease(ws):
    repo = make_repo(ws)
    (repo / "new.md").write_text("mine\n")
    with lease_held_by_a_phase(repo, "slice 123 P2\n"):
        code, out, err = run_cli("commit", "-m", "x", repo / "new.md", phase="main")
    assert code == 0, err
    assert head_file(repo, "new.md") == "mine\n"


@with_workspace
def test_a_commit_landing_mid_attempt_is_merged_against_not_reverted(ws):
    repo = make_repo(ws)
    dag = repo / "DAG.md"
    dag.write_text(TICKED)
    token = snap(dag)
    dag.write_text(edit_line(TICKED, 8, AGENT))
    landed = []

    with patched("move_head", None) as original:
        def racing(root, new, old, reason):
            if not landed:
                (repo / "README.md").write_text("# specs, by another session\n")
                git(repo, "commit", "-qm", "another session", "--", "README.md")
                landed.append(git(repo, "rev-parse", "HEAD").strip())
            return original(root, new, old, reason)
        spec_commit.move_head = racing
        code, _, err = run_cli("commit", "-m", "dag", token)

    assert code == 0, err
    assert git(repo, "rev-parse", "HEAD~1").strip() == landed[0]
    assert head_file(repo, "README.md") == "# specs, by another session\n"
    assert head_file(repo, "DAG.md") == edit_line(DAG, 8, AGENT)
    assert git(repo, "diff", "--cached") == ""


@with_workspace
def test_head_that_keeps_moving_gives_up_with_nothing_committed(ws):
    repo = make_repo(ws)
    (repo / "new.md").write_text("mine\n")
    before = state(repo)
    with patched("move_head", lambda *_: "cannot lock ref 'HEAD'"):
        code, _, err = run_cli("commit", "-m", "x", repo / "new.md")
    assert code == 1
    assert "HEAD kept moving" in err
    assert state(repo) == before


@with_workspace
def test_a_busy_index_after_the_commit_warns_and_the_commit_stands(ws):
    repo = make_repo(ws)
    (repo / "new.md").write_text("mine\n")
    lock = repo / ".git" / "index.lock"

    with patched("INDEX_LOCK_PAUSE", 0), patched("move_head", None) as original:
        def then_lock(*args):
            moved = original(*args)
            lock.write_text("")
            return moved
        spec_commit.move_head = then_lock
        code, out, err = run_cli("commit", "-m", "x", repo / "new.md")
    lock.unlink()

    assert code == 0, err
    assert head_file(repo, "new.md") == "mine\n"
    assert "the commit stands" in err and "git reset -q -- new.md" in err
    assert "committed " in out


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
