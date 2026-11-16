"""Tests for seed_run_records — the old slices' state files and the history's
groups copied into the plugin's run records.

Spec repos are faked under a temp dir (`git init` and an `origin` URL, which
`spec_repo_name` reads); the data folder is a temp dir passed as `--data-dir`.
The installed plugin's data folder is stubbed as one that cannot be told, so
nothing is ever written under the real home.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_seed_run_records.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "seed_run_records", Path(__file__).resolve().parent / "seed_run_records.py"
)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)
run_loop = seed.run_loop

# No test reaches the operator's own data folder: without --data-dir the
# script finds none.
run_loop.plugin_data_dir = lambda tools_dir=None: None

GROUPS = b"""# hand-edited
spec_repo = "FooSpecs"
repo = "Foo"
environment = "someone-foo"

[[project]]
name = "First"
summary = "the first group"
slices = ["001_one", "002_two"]
"""


def make_repo(base: Path, name: str = "FooSpecs") -> Path:
    repo = base / "checkout"
    (repo / "slices").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    f"git@github.com:owner/{name}.git"], check=True)
    return repo


def add_slice(repo: Path, status: str, slug: str, **files) -> Path:
    folder = repo / "slices" / status / slug
    folder.mkdir(parents=True, exist_ok=True)
    for fname, content in files.items():
        text = content if isinstance(content, str) else json.dumps(content)
        (folder / f"{fname}.json").write_text(text)
    return folder


def run(*argv) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = seed.main([str(a) for a in argv])
    return code, out.getvalue()


@contextlib.contextmanager
def workspace():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        yield base, make_repo(base), base / "data"


def records(data: Path, slug: str, spec: str = "FooSpecs") -> Path:
    return data / "runs" / spec / slug


def test_copies_both_state_files_to_the_records():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_one",
                  state={"phase": "done"}, plan_state={"round": 2})
        add_slice(repo, "backlog", "002_two", plan_state={"round": 1})
        add_slice(repo, "backlog", "003_none")      # no state files: not seen
        src = repo / "slices/completed/001_one/state.json"
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        assert (records(data, "001_one") / "state.json").read_bytes() == src.read_bytes()
        assert json.loads((records(data, "001_one") / "plan_state.json").read_text()) \
            == {"round": 2}
        assert json.loads((records(data, "002_two") / "plan_state.json").read_text()) \
            == {"round": 1}
        assert not (records(data, "002_two") / "state.json").exists()
        assert not records(data, "003_none").exists()
        assert "FooSpecs (" in out and "2 slices seen, 3 files copied, 0 kept" in out
        # The place is the one a live run keeps them in.
        assert run_loop.run_records_dir(repo / "slices/completed/001_one", data) \
            == records(data, "001_one")
        assert not list(records(data, "001_one").glob(".*.tmp"))


def test_a_second_run_keeps_and_adds_only_the_new():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_one", state={"v": 1})
        assert run("--data-dir", data, repo)[0] == 0
        add_slice(repo, "completed", "002_two", state={"v": 2})
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        assert "2 slices seen, 1 files copied, 1 kept" in out
        assert json.loads((records(data, "002_two") / "state.json").read_text()) == {"v": 2}


def test_never_replaces_an_existing_record():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_one", state={"v": "old"})
        live = records(data, "001_one")
        live.mkdir(parents=True)
        (live / "state.json").write_text('{"v": "live"}')
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        assert (live / "state.json").read_text() == '{"v": "live"}'
        assert "0 files copied, 1 kept" in out


def test_never_replaces_a_record_written_between_scan_and_write():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_one", state={"v": "old"})
        dest = records(data, "001_one") / "state.json"
        real_link = os.link

        def driver_first(src, dst, *a, **kw):
            if Path(dst) == dest:
                dest.write_text('{"v": "driver"}')
            return real_link(src, dst, *a, **kw)

        os.link = driver_first
        try:
            code, out = run("--data-dir", data, repo)
        finally:
            os.link = real_link
        assert code == 0, out
        assert dest.read_text() == '{"v": "driver"}'
        assert "0 files copied, 1 kept" in out
        assert not list(dest.parent.glob(".*.tmp"))


def test_place_new_refuses_an_existing_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state.json"
        assert seed.place_new(path, b"{}") is True
        assert seed.place_new(path, b'{"x": 1}') is False
        assert path.read_bytes() == b"{}"
        assert sorted(p.name for p in Path(tmp).iterdir()) == ["state.json"]


def test_bad_json_is_skipped_and_reported():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_one", state="{not json", plan_state={"ok": 1})
        add_slice(repo, "completed", "002_two", state="[1, 2]")
        code, out = run("--data-dir", data, repo)
        assert code == 1, out
        assert not (records(data, "001_one") / "state.json").exists()
        assert (records(data, "001_one") / "plan_state.json").exists()
        assert not (records(data, "002_two") / "state.json").exists()
        assert "completed/001_one/state.json: not JSON" in out
        assert "completed/002_two/state.json: not a JSON object" in out
        assert "1 files copied, 0 kept (already there), 2 skipped" in out


def test_a_slice_under_two_status_folders_copies_completed_first():
    with workspace() as (_, repo, data):
        add_slice(repo, "active", "001_one", state={"from": "active"})
        add_slice(repo, "completed", "001_one", state={"from": "completed"})
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        assert json.loads((records(data, "001_one") / "state.json").read_text()) \
            == {"from": "completed"}
        assert "001_one is in both completed/ and active/: copied completed/'s" in out


def test_groups_are_checked_copied_and_replaced():
    with workspace() as (base, repo, data):
        groups = base / "adopted"
        groups.mkdir()
        (groups / "FooSpecs.toml").write_bytes(GROUPS)
        (groups / "notes.txt").write_text("not a group")
        code, out = run("--data-dir", data, "--groups", groups, repo)
        assert code == 0, out
        assert (data / "groups" / "FooSpecs.toml").read_bytes() == GROUPS
        assert not (data / "groups" / "notes.txt").exists()
        assert "1 files, 1 copied, 0 refused" in out
        edited = GROUPS.replace(b"the first group", b"an edited summary")
        (groups / "FooSpecs.toml").write_bytes(edited)
        assert run("--data-dir", data, "--groups", groups, repo)[0] == 0
        assert (data / "groups" / "FooSpecs.toml").read_bytes() == edited


def test_a_malformed_group_is_refused():
    with workspace() as (base, repo, data):
        groups = base / "adopted"
        groups.mkdir()
        (groups / "Good.toml").write_bytes(GROUPS)
        (groups / "BadToml.toml").write_text("spec_repo = \n")
        (groups / "NoSlices.toml").write_text(
            'spec_repo = "X"\n[[project]]\nname = "a"\nsummary = "b"\nslices = "c"\n')
        (groups / "NoRepo.toml").write_text('[[project]]\nname = "a"\n')
        (groups / "IntSlices.toml").write_text(
            'spec_repo = "X"\n[[project]]\nname = "a"\nsummary = "b"\nslices = [1]\n')
        code, out = run("--data-dir", data, "--groups", groups, repo)
        assert code == 1, out
        assert sorted(p.name for p in (data / "groups").iterdir()) == ["Good.toml"]
        assert "BadToml.toml: not TOML" in out
        assert "NoSlices.toml: project 1 (a) has no `slices` list of strings" in out
        assert "NoRepo.toml: no string `spec_repo`" in out
        assert "IntSlices.toml: project 1 (a)" in out
        assert "5 files, 1 copied, 4 refused" in out


def test_dry_run_writes_nothing():
    with workspace() as (base, repo, data):
        add_slice(repo, "completed", "001_one", state={"v": 1}, plan_state={"r": 1})
        groups = base / "adopted"
        groups.mkdir()
        (groups / "FooSpecs.toml").write_bytes(GROUPS)
        code, out = run("--dry-run", "--data-dir", data, "--groups", groups, repo)
        assert code == 0, out
        assert not data.exists()
        assert "1 slices seen, 2 files to copy, 0 kept" in out
        assert "1 files, 1 to copy, 0 refused" in out
        assert "would be in" in out


def test_no_data_folder_is_exit_2_before_anything_is_read():
    with workspace() as (_, repo, _data):
        add_slice(repo, "completed", "001_one", state={"v": 1})
        code, out = run(repo)
        assert code == 2, out
        assert "data folder cannot be told" in out
        assert "FooSpecs" not in out


def test_a_repo_without_slices_fails_and_the_others_go_on():
    with workspace() as (base, repo, data):
        add_slice(repo, "completed", "001_one", state={"v": 1})
        bare = base / "not-a-spec-repo"
        bare.mkdir()
        code, out = run("--data-dir", data, bare, repo)
        assert code == 1, out
        assert "not a spec repo (no slices/ folder)" in out
        assert (records(data, "001_one") / "state.json").exists()



# -- slice.json: the facts a live run's records hold, from the slice folder -----

PLAN = """# A slice — plan

## Phases

### P1 — First

Target: app

Outcome: one.

### P2 — Second

Target: app

Outcome: two.

### P3 — Appended by the run

Target: app

Outcome: three.
"""
FINDING = {"id": "F1", "severity": "Major", "impact": "blocking", "summary": "x"}


def write(folder: Path, name: str, content) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


def facts_of(data: Path, slug: str) -> dict:
    return json.loads((records(data, slug) / "slice.json").read_text())


def test_each_seeded_slice_gets_its_slice_json_with_every_fact_its_folder_holds():
    with workspace() as (_, repo, data):
        folder = add_slice(repo, "completed", "001_one", state={
            "appended_phases": ["3"],
            "history": [{"role": "code-reviewer", "phase": "1", "round": 1,
                         "findings": [FINDING]},
                        {"role": "code-reviewer", "phase": "2", "round": 1}]},
            plan_state={"history": [{"role": "plan-reviewer", "round": 1},
                                    {"role": "plan-reviewer", "round": 2}]})
        write(folder, "slice.md", "---\nissue: P-371\n---\n\n# The first slice\n")
        write(folder, "plan.md", PLAN)
        write(folder, "verification.json", {"items": [{"id": "V01"}, {"id": "V02"}]})
        write(folder, "plan_review_r1.json", {"findings": [
            {"class": "blocking", "headline": "A gap", "proposal": "close it"},
            {"class": "operator", "headline": "A choice", "options": [{"label": "a"}]}]})
        write(folder, "phases/P1/review_result_r1.json", {"findings": [FINDING]})
        write(folder, "phases/P2/review_result_r1.json", {"findings": [FINDING]})
        write(folder, "phases/P2/review_result_r2.json", {"findings": []})
        write(folder, "close-out.json", {"closed": {"date": "2026-11-01"}, "entries": [
            {"id": "B1", "strike": {"reason": "fixed", "commit": "abc1234"}},
            {"id": "B2", "strike": {"reason": "carded as P-9"},
             "ruling": {"did": "carded as P-9"}},
            {"id": "B3", "strike": {"reason": "closed with the report, 2026-11-01"}}]})
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        facts = facts_of(data, "001_one")
        assert facts.pop("plugin_version") == run_loop.plugin_version()
        assert facts.pop("updated_at")
        assert facts == {
            "slice": "001_one", "card": "P-371", "title": "The first slice",
            "plan": {"phases": 2, "acceptance_criteria": 2},
            # rounds whose rows carry no findings, by round and by phase and round
            "plan_review_findings": {"1": [
                {"class": "blocking", "headline": "A gap", "gap": True},
                {"class": "operator", "headline": "A choice", "gap": False}]},
            "code_review_findings": {"2": {"1": [FINDING]}},
            "close_out": {"entries": 3, "fixed": 1, "carded": 1, "closed": 1}}
        assert "1 slice.json copied (1 naming a card, 0 its filing commit), 0 kept" in out


def test_a_fact_the_folder_does_not_hold_is_left_out():
    with workspace() as (_, repo, data):
        add_slice(repo, "completed", "001_old", state={"history": []})   # no slice.md
        bare = add_slice(repo, "completed", "002_bare", plan_state={})
        write(bare, "slice.md", "# Only a title\n")
        write(bare, "plan.md", "# no phases here\n")
        write(bare, "verification.json", {"items": []})
        # a report still open over a live entry tells no fates
        write(bare, "close-out.json", {"entries": [{"id": "B1", "strike": None}]})
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        old = facts_of(data, "001_old")
        assert set(old) == {"slice", "updated_at", "plugin_version"}
        assert {k: v for k, v in facts_of(data, "002_bare").items()
                if k not in ("updated_at", "plugin_version")} == {
            "slice": "002_bare", "card": None, "title": "Only a title"}
        assert "2 slice.json copied (0 naming a card, 0 its filing commit), 0 kept" in out


def test_a_slice_json_that_is_there_is_never_replaced_and_a_dry_run_counts_it():
    with workspace() as (_, repo, data):
        folder = add_slice(repo, "completed", "001_one", state={})
        write(folder, "slice.md", "---\nissue: P-1\n---\n# One\n")
        live = records(data, "001_one")
        live.mkdir(parents=True)
        (live / "slice.json").write_text('{"card": "P-live"}')
        add_slice(repo, "completed", "002_two", state={})
        code, out = run("--dry-run", "--data-dir", data, repo)
        assert code == 0, out
        assert "1 slice.json to copy (0 naming a card, 0 its filing commit), 1 kept" in out
        assert not records(data, "002_two").exists()
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        assert (live / "slice.json").read_text() == '{"card": "P-live"}'
        assert "1 slice.json copied (0 naming a card, 0 its filing commit), 1 kept" in out


def commit(repo: Path, message: str, when: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org",
           "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.org"}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True, env=env)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True, env=env).stdout.strip()


def test_each_slice_json_notes_the_commit_that_filed_its_slice():
    """D8: the first commit that added the slice's slice.md, moved folders included; an
    earlier seed's slice.json gains that key alone."""
    with workspace() as (_, repo, data):
        one = add_slice(repo, "backlog", "001_one", state={})
        write(one, "slice.md", "# One\n")
        two = add_slice(repo, "backlog", "002_two", state={})
        write(two, "slice.md", "# Two\n")
        filed = commit(repo, "Triage: file slices 001 and 002", "2026-10-01T09:00:00+00:00")
        write(one, "slice.md", "# One, reworded\n")
        commit(repo, "Reword 001", "2026-10-02T09:00:00+00:00")
        (repo / "slices" / "completed").mkdir(exist_ok=True)
        os.rename(one, repo / "slices" / "completed" / "001_one")
        commit(repo, "Complete 001", "2026-10-05T09:00:00+00:00")
        assert run_loop.SLICE_FACTS == "slice.json"
        live = records(data, "002_two")
        live.mkdir(parents=True)
        (live / "slice.json").write_text('{"card": "P-live"}')
        code, out = run("--dry-run", "--data-dir", data, repo)
        assert code == 0, out
        assert "1 slice.json to copy (0 naming a card, 1 its filing commit), " \
               "1 kept (1 its filing commit to add)" in out
        assert json.loads((live / "slice.json").read_text()) == {"card": "P-live"}
        code, out = run("--data-dir", data, repo)
        assert code == 0, out
        got = facts_of(data, "001_one")["filing_commit"]
        assert datetime.fromisoformat(got["authored_at"]) == \
            datetime.fromisoformat("2026-10-01T09:00:00+00:00")
        want = {"hash": filed, "subject": "Triage: file slices 001 and 002",
                "authored_at": got["authored_at"]}
        assert got == want
        assert json.loads((live / "slice.json").read_text()) == {"card": "P-live",
                                                                 "filing_commit": want}
        code, out = run("--data-dir", data, repo)
        assert "0 kept (0 its filing commit added)" not in out
        assert "2 kept (0 its filing commit added)" in out


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
