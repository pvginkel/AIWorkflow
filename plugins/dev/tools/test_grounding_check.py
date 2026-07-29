"""Tests for grounding_check — the deterministic grounding drift checker.

The workspace is faked: a tmp `MyApp` root (the module's repo_root() is patched
onto it) with a sibling `SharedLib` checkout, real files for the anchors to hit
or miss, and a real git repo where the stamp's freshness math is under test. No
agent and no network.

Stdlib only, like the plugin's other suites — `@with_workspace` stands in for
the fixture, so each test still takes `ws` and still collects under pytest.

Run: `python3 plugins/dev/tools/test_grounding_check.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "grounding_check", Path(__file__).resolve().parent / "grounding_check.py"
)
grounding_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grounding_check)
check = grounding_check.check
Precondition = grounding_check.Precondition


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def with_workspace(fn):
    """A faked workspace: <tmp>/MyApp (the repo root) + <tmp>/SharedLib.

    The checker takes its root from `git rev-parse --show-toplevel`, so the
    workspace is installed by patching repo_root() rather than by faking git.
    The wrapper takes no arguments, so pytest collects it as a plain test —
    hence no functools.wraps, which would expose the wrapped signature and
    have pytest demand a `ws` fixture this suite does not define.
    """
    def wrapper():
        saved = grounding_check.repo_root
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            root = ws / "MyApp"
            root.mkdir(parents=True)
            (ws / "SharedLib").mkdir()
            (ws / "specs" / "slices").mkdir(parents=True)
            grounding_check.repo_root = lambda: root
            try:
                fn(ws)
            finally:
                grounding_check.repo_root = saved
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@contextlib.contextmanager
def raises(exc):
    try:
        yield
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def run_cli(*argv):
    """main() with its streams captured — (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = grounding_check.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def write_source(ws, rel, lines):
    path = ws / "MyApp" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def make_slice(ws, ledger, tasks=None):
    """A slice folder with grounding.md and optional tasks/<name>/plan.md."""
    slice_dir = ws / "specs" / "slices" / "099_test_slice"
    slice_dir.mkdir(parents=True, exist_ok=True)
    (slice_dir / "grounding.md").write_text(ledger)
    for name, plan in (tasks or {}).items():
        task_dir = slice_dir / "tasks" / name
        task_dir.mkdir(parents=True)
        (task_dir / "plan.md").write_text(plan)
    return slice_dir


def ledger(*entries, stamp="verified: MyApp@1a2b3c4d5e6f — 2026-07-24"):
    body = "\n".join(entries)
    return f"# Grounding — slice 099\n\n{stamp}\n\n## Facts\n\n{body}\n"


def entry(gid, claim, citation, anchor):
    return f'- {gid}: {claim} — `{citation}` — "{anchor}"'


def by_id(report):
    return {e["id"]: e for e in report["entries"]}


def git_repo(path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", key, value],
                       check=True)


def git_commit(path, message):
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", message],
                   check=True)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_parses_single_lines_ranges_and_sweeps():
    text = ledger(
        entry("G-001", "the overlay list is exactly four",
              "app/podcomposer.py:186", "OVERLAY_DIRS = ["),
        entry("G-002", "the catalog declares toolchains",
              "../SharedLib/values.yaml:204-217", "toolchains:"),
        '- G-014 (sweep): rg "corepack" over both repos — exactly 3 hits: a, b, c',
    )
    lines = text.splitlines()
    assert grounding_check.parse_stamp(lines) == {"MyApp": "1a2b3c4d5e6f"}
    entries = grounding_check.parse_entries(lines)
    assert [e.id for e in entries] == ["G-001", "G-002", "G-014"]

    one, ranged, sweep = entries
    assert one.file == "app/podcomposer.py"
    assert (one.cited_start, one.cited_end) == (186, 186)
    assert one.anchor == "OVERLAY_DIRS = ["
    assert one.claim == "the overlay list is exactly four"
    assert ranged.file == "../SharedLib/values.yaml"
    assert (ranged.cited_start, ranged.cited_end) == (204, 217)
    assert sweep.sweep and sweep.file is None and sweep.anchor is None


def test_stamp_accepts_multiple_repos_and_a_plain_hyphen():
    text = ledger(entry("G-001", "c", "a.py:1", "x"),
                  stamp="verified: MyApp@abc1234, SharedLib@def5678 "
                        "- 2026-07-24")
    assert grounding_check.parse_stamp(text.splitlines()) == {
        "MyApp": "abc1234", "SharedLib": "def5678"}


@with_workspace
def test_repo_for_citation_reaches_siblings(ws):
    assert grounding_check.repo_for_citation("app/x.py") == (
        "MyApp", "app/x.py")
    assert grounding_check.repo_for_citation("../SharedLib/values.yaml") == (
        "SharedLib", "values.yaml")


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

@with_workspace
def test_every_status(ws):
    write_source(ws, "app/a.py", ["one", "TARGET_OK", "three", "four"])
    write_source(ws, "app/b.py", ["one", "two", "MOVED_HERE", "four"])
    write_source(ws, "app/c.py", ["one", "two"])
    (ws / "SharedLib" / "values.yaml").write_text("a\nb\nc\nRANGE_HIT\ne\n")
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "ok", "app/a.py:2", "TARGET_OK"),
        entry("G-002", "range", "../SharedLib/values.yaml:2-5", "RANGE_HIT"),
        entry("G-003", "moved", "app/b.py:1", "MOVED_HERE"),
        entry("G-004", "missing", "app/c.py:1", "NOT_THERE"),
        entry("G-005", "gone", "app/deleted.py:9", "ANY"),
        "- G-006 (sweep): rg over the tree — 2 hits",
    ))

    report = check(slice_dir)
    entries = by_id(report)
    assert entries["G-001"]["status"] == "OK"
    assert entries["G-002"]["status"] == "OK"          # anywhere in the range
    assert entries["G-003"]["status"] == "MOVED"
    assert entries["G-003"]["new_line"] == 3
    assert entries["G-004"]["status"] == "MISSING"
    assert entries["G-005"]["status"] == "GONE"
    assert entries["G-006"]["status"] == "UNCHECKED"
    assert report["tier"] == 2
    assert report["legacy"] is False


@with_workspace
def test_anchor_matches_a_substring_of_the_cited_line(ws):
    write_source(ws, "app/a.py",
                 ["SYSTEM_PERSISTENT_OVERLAY_DIRS = [  # the deciding list"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "the list", "app/a.py:1",
              "SYSTEM_PERSISTENT_OVERLAY_DIRS = [")))
    assert by_id(check(slice_dir))["G-001"]["status"] == "OK"


@with_workspace
def test_ambiguous_anchor_is_missing_not_moved(ws):
    """Two candidate lines and neither is the cited one: nothing can be
    repaired safely, so the entry escalates instead of guessing."""
    write_source(ws, "app/a.py", ["x", "DUP", "y", "DUP"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "dup", "app/a.py:1", "DUP")))
    report = check(slice_dir)
    assert by_id(report)["G-001"]["status"] == "MISSING"
    assert by_id(report)["G-001"]["new_line"] is None
    assert report["tier"] == 2


@with_workspace
def test_duplicate_anchor_still_ok_when_one_hit_is_the_cited_line(ws):
    write_source(ws, "app/a.py", ["DUP", "y", "DUP"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "dup", "app/a.py:3", "DUP")))
    assert by_id(check(slice_dir))["G-001"]["status"] == "OK"


@with_workspace
def test_unparseable_citation_is_unchecked_never_escalated(ws):
    """A `path + symbol` citation (legal in the per-task ledger) cannot be
    grep-verified mechanically; the checker must not report drift over it."""
    write_source(ws, "app/a.py", ["def foo():"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "symbol cite", "app/a.py:foo", "def foo(")))
    report = check(slice_dir)
    assert by_id(report)["G-001"]["status"] == "UNCHECKED"
    assert report["tier"] == 0


# ---------------------------------------------------------------------------
# Legacy
# ---------------------------------------------------------------------------

@with_workspace
def test_legacy_without_a_stamp(ws):
    slice_dir = make_slice(ws, "# Grounding\n\n"
                               + entry("G-001", "c", "a.py:1", "x") + "\n")
    report = check(slice_dir)
    assert report["legacy"] is True
    assert report["summary"] == "grounding: legacy ledger — no mechanical check"
    assert report["tier"] == 0


@with_workspace
def test_legacy_without_entries(ws):
    slice_dir = make_slice(
        ws, "# Grounding\n\nverified: MyApp@abc1234 — 2026-07-24\n\n"
            "Prose-only ledger, pre-format.\n")
    assert check(slice_dir)["legacy"] is True


@with_workspace
def test_missing_ledger_is_legacy_not_a_crash(ws):
    slice_dir = ws / "specs" / "slices" / "099_no_ledger"
    slice_dir.mkdir(parents=True)
    report = check(slice_dir)
    assert report["legacy"] is True
    assert "no ledger" in report["summary"]


@with_workspace
def test_missing_slice_dir_is_a_precondition(ws):
    with raises(Precondition):
        check(ws / "specs" / "slices" / "nope")


# ---------------------------------------------------------------------------
# --repair
# ---------------------------------------------------------------------------

@with_workspace
def test_repair_rewrites_single_lines_and_keeps_range_spans(ws):
    write_source(ws, "app/a.py", ["pad", "pad", "MOVED_ONE"])
    (ws / "SharedLib" / "values.yaml").write_text(
        "pad\npad\npad\npad\nRANGE_START\nb\nc\n")
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "single", "app/a.py:1", "MOVED_ONE"),
        entry("G-002", "range", "../SharedLib/values.yaml:2-4",
              "RANGE_START"),
    ))
    report = check(slice_dir, repair=True)
    assert all(e["repaired"] for e in report["entries"])
    assert report["tier"] == 1

    text = (slice_dir / "grounding.md").read_text()
    assert "`app/a.py:3`" in text
    # the span length (3 lines) is preserved, anchored at the new start
    assert "`../SharedLib/values.yaml:5-7`" in text
    assert "verified: MyApp@1a2b3c4d5e6f — 2026-07-24" in text
    assert "(repaired)" in report["summary"]

    # a second pass over the repaired ledger is clean
    again = check(slice_dir)
    assert {e["status"] for e in again["entries"]} == {"OK"}
    assert again["tier"] == 0


@with_workspace
def test_repair_leaves_missing_and_gone_alone(ws):
    write_source(ws, "app/a.py", ["nothing here"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "missing", "app/a.py:1", "ABSENT"),
        entry("G-002", "gone", "app/deleted.py:1", "ABSENT"),
    ))
    before = (slice_dir / "grounding.md").read_text()
    report = check(slice_dir, repair=True)
    assert (slice_dir / "grounding.md").read_text() == before
    assert not any(e["repaired"] for e in report["entries"])
    assert report["tier"] == 2


# ---------------------------------------------------------------------------
# --task scoping + plan citations
# ---------------------------------------------------------------------------

TASKS = {
    "04_first": "Implement per [G-001] and [G-002].\n",
    "04a_inserted": "Only [G-003] matters here.\n",
    "05_second": "Nothing cited.\n",
}


def _scoping_slice(ws):
    write_source(ws, "app/a.py", ["A1", "A2", "A3"])
    return make_slice(ws, ledger(
        entry("G-001", "one", "app/a.py:1", "A1"),
        entry("G-002", "two", "app/a.py:2", "A2"),
        entry("G-003", "three", "app/a.py:3", "A3"),
    ), tasks=TASKS)


@with_workspace
def test_task_scoping_selects_only_the_plan_cited_entries(ws):
    slice_dir = _scoping_slice(ws)
    report = check(slice_dir, task="04")
    assert sorted(by_id(report)) == ["G-001", "G-002"]
    assert "cited by task 04" in report["summary"]


@with_workspace
def test_task_scoping_accepts_a_letter_suffix(ws):
    slice_dir = _scoping_slice(ws)
    assert sorted(by_id(check(slice_dir, task="04a"))) == ["G-003"]
    # ...and the plain number must not sweep the suffixed sibling in
    assert sorted(by_id(check(slice_dir, task="04"))) == ["G-001", "G-002"]


@with_workspace
def test_task_scoping_accepts_the_full_task_dir_name(ws):
    slice_dir = _scoping_slice(ws)
    assert sorted(by_id(check(slice_dir, task="04a_inserted"))) == ["G-003"]


@with_workspace
def test_unknown_task_is_a_precondition(ws):
    slice_dir = _scoping_slice(ws)
    with raises(Precondition):
        check(slice_dir, task="77")


@with_workspace
def test_plan_citations_report_invalid_and_touched_counts(ws):
    root = ws / "MyApp"
    write_source(ws, "app/a.py", ["A1", "A2", "A3"])
    write_source(ws, "app/stable.py", ["S1", "S2"])
    git_repo(root)
    sha = git_commit(root, "base")
    # one cited file moves after the stamp, the other does not
    write_source(ws, "app/a.py", ["A1", "A2", "A3", "A4"])
    git_commit(root, "touch a.py")

    plan = (
        "Edit `app/a.py:2` and `app/stable.py:1-2`.\n"
        "Stale pointer: `app/a.py:900`.\n"
        "Deleted: `app/gone.py:1`.\n"
        "Not a citation: `env-id:1` and `--task NN`.\n"
    )
    slice_dir = make_slice(
        ws,
        ledger(entry("G-001", "one", "app/a.py:1", "A1"),
               stamp=f"verified: MyApp@{sha} — 2026-07-24"),
        tasks={"01_only": "[G-001]\n" + plan},
    )
    report = check(slice_dir)
    plans = report["plan_citations"]
    assert plans["total"] == 4
    assert len(plans["invalid"]) == 2
    assert any("line beyond EOF" in i for i in plans["invalid"])
    assert any("file not found" in i for i in plans["invalid"])
    assert all(i.startswith("tasks/01_only/plan.md:") for i in plans["invalid"])
    assert plans["files_touched_since_stamp"] == 1
    assert report["commits_since"] == {"MyApp": 1}
    assert "1 commit since" in report["summary"]


@with_workspace
def test_unresolvable_stamp_sha_reports_null_commits(ws):
    write_source(ws, "app/a.py", ["A1"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "one", "app/a.py:1", "A1"),
        stamp="verified: MyApp@deadbeef — 2026-07-24"))
    report = check(slice_dir)
    assert report["commits_since"] == {"MyApp": None}
    assert "commits since unknown" in report["summary"]


# ---------------------------------------------------------------------------
# --prune
# ---------------------------------------------------------------------------

@with_workspace
def test_prune_drops_entries_no_plan_cites(ws):
    slice_dir = _scoping_slice(ws)
    report = check(slice_dir, prune=True)
    # 04 cites G-001/G-002, 04a cites G-003 — nothing is dead yet
    assert report["pruned"] == []

    # drop the citation of G-003 and re-run
    (slice_dir / "tasks" / "04a_inserted" / "plan.md").write_text("no ids\n")
    report = check(slice_dir, prune=True)
    assert report["pruned"] == ["G-003"]
    assert sorted(by_id(report)) == ["G-001", "G-002"]
    text = (slice_dir / "grounding.md").read_text()
    assert "G-003" not in text
    assert "G-001" in text and "G-002" in text
    assert "verified: MyApp@1a2b3c4d5e6f — 2026-07-24" in text


@with_workspace
def test_prune_rejects_task_scoping(ws):
    slice_dir = _scoping_slice(ws)
    with raises(Precondition):
        check(slice_dir, task="04", prune=True)


@with_workspace
def test_prune_refuses_when_there_are_no_plans(ws):
    """An empty tasks/ would otherwise prune the whole ledger away."""
    write_source(ws, "app/a.py", ["A1"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "one", "app/a.py:1", "A1")))
    with raises(Precondition):
        check(slice_dir, prune=True)
    assert "G-001" in (slice_dir / "grounding.md").read_text()


@with_workspace
def test_prune_and_repair_compose(ws):
    write_source(ws, "app/a.py", ["pad", "A1"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "kept", "app/a.py:1", "A1"),
        entry("G-002", "dead", "app/a.py:1", "GONE_ANCHOR"),
    ), tasks={"01_only": "cites [G-001]\n"})
    report = check(slice_dir, repair=True, prune=True)
    text = (slice_dir / "grounding.md").read_text()
    assert report["pruned"] == ["G-002"] and "G-002" not in text
    assert "`app/a.py:2`" in text
    # the pruned entry's MISSING status must not escalate the surviving ledger
    assert report["tier"] == 1


# ---------------------------------------------------------------------------
# CLI: exit codes + output shapes
# ---------------------------------------------------------------------------

@with_workspace
def test_cli_exit_codes_and_summary_shape(ws):
    write_source(ws, "app/a.py", ["pad", "A1"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "moved", "app/a.py:1", "A1")))

    code, out, _ = run_cli(str(slice_dir), "--repair")
    assert code == 0
    assert out.startswith("grounding: verified at MyApp@1a2b3c4d5e6f")
    assert "1 entry: 1 MOVED (repaired)" in out
    assert "plans: 0 citations (0 invalid)" in out
    assert "G-001 MOVED  app/a.py:1 → 2 (repaired)" in out


@with_workspace
def test_cli_tier_two_exits_three_and_prints_json(ws):
    write_source(ws, "app/a.py", ["nothing"])
    slice_dir = make_slice(ws, ledger(
        entry("G-001", "missing", "app/a.py:1", "ABSENT")))

    code, out, _ = run_cli(str(slice_dir))
    assert code == 3
    assert "G-001 MISSING" in out

    code, out, _ = run_cli(str(slice_dir), "--json")
    assert code == 3
    payload = json.loads(out)
    assert payload["tier"] == 2
    assert payload["stamp"] == {"MyApp": "1a2b3c4d5e6f"}
    assert payload["entries"][0] == {
        "id": "G-001", "claim": "missing", "file": "app/a.py",
        "cited_line": 1, "cited_end": 1, "anchor": "ABSENT",
        "status": "MISSING", "new_line": None, "repaired": False,
    }
    assert payload["summary"].startswith("grounding: ")


@with_workspace
def test_cli_legacy_exits_zero(ws):
    slice_dir = make_slice(ws, "# Grounding\n\nprose only\n")
    code, out, _ = run_cli(str(slice_dir))
    assert code == 0
    assert out.strip() == "grounding: legacy ledger — no mechanical check"


@with_workspace
def test_cli_precondition_exits_two(ws):
    code, _, err = run_cli(str(ws / "nope"))
    assert code == 2
    assert "Error:" in err


def test_cli_outside_a_git_repo_is_a_precondition():
    """The root is the caller's git toplevel, not this script's location: run
    from nowhere in particular, the checker fails its precondition (exit 2)
    rather than resolving citations against the plugin's own directory."""
    saved_fn = grounding_check.repo_root
    saved_cache = grounding_check._REPO_ROOT
    saved_cwd = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "099_x"
        slice_dir.mkdir()
        (slice_dir / "grounding.md").write_text(
            ledger(entry("G-001", "one", "app/a.py:1", "A1")))
        try:
            grounding_check._REPO_ROOT = None
            os.chdir("/")  # no git repo anywhere up the tree
            code, _, err = run_cli(str(slice_dir))
        finally:
            os.chdir(saved_cwd)
            grounding_check.repo_root = saved_fn
            grounding_check._REPO_ROOT = saved_cache
    assert code == 2
    assert "not inside a git repository" in err


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
