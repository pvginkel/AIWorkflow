"""Tests for checks — an action's checks: the vocabulary, its refusals and
their evaluation against a tree, a pod's environment and a spec repo.

Stdlib only; runs standalone and under pytest. The `origin` check runs real
git against a bare repo made in a temp directory.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_checks.py` or via pytest.
"""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "checks", Path(__file__).resolve().parent / "checks.py"
)
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)


def test_the_vocabulary_reads_each_check():
    parsed = checks.parse(
        "env PILOT_DEV_TOKEN; file ../PilotApp:.kubecoder/config.yaml; "
        "origin ../PilotApp main:.kubecoder/config.yaml contains use: go; "
        "slice 7 completed")
    assert [(c.kind, c.fields) for c in parsed] == [
        ("env", ("PILOT_DEV_TOKEN",)),
        ("file", ("../PilotApp", ".kubecoder/config.yaml")),
        ("origin", ("../PilotApp", "main", ".kubecoder/config.yaml", "use: go")),
        ("slice", ("7",))]
    assert [str(c) for c in parsed][0] == "env PILOT_DEV_TOKEN"
    assert checks.parse("origin . main:x contains `a b`")[0].fields[3] == "a b"
    assert checks.is_manual(checks.parse("manual"))
    assert checks.join(["env A", " slice 3 completed ", ""]) == \
        "env A; slice 3 completed"


def test_the_vocabulary_refuses_what_it_does_not_read():
    for text, said in (
            ("the job runs", "is no check"),
            ("", "the check is empty"),
            ("env A;; env B", "an empty check"),
            ("manual; env A", "`manual` stands alone"),
            ("cmd kubectl get pods", "is no check"),
            ("restart once 45a9ab3 is on main", "45a9ab3, a commit"),
            ("env A; origin . main:x contains e91fc82d", "e91fc82d, a commit"),
            ("restart pvginkel-pilotapp-addac6", "pvginkel-pilotapp-addac6, an "
                                                 "environment")):
        found = checks.problems(text)
        assert any(said in f for f in found), (text, found)
        try:
            checks.parse(text)
            raise AssertionError(f"{text!r} must be refused")
        except checks.CheckError as e:
            assert said in str(e)
    # a number, a word of hex letters and a slug are none of those
    for text in ("origin . main:x contains 1234567", "origin . main:x contains release1",
                 "origin . main:x contains facade", "file ../my-app-decade:x"):
        assert not [f for f in checks.problems(text) if "commit" in f or "environment" in f], text


def _evaluate(text, **kw):
    return [checks.evaluate(c, **kw) for c in checks.parse(text)]


def test_env_file_and_slice_are_read_where_the_run_runs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo, sibling, spec = root / "App", root / "Sibling", root / "Specs"
        for d in (repo, sibling, spec / "slices" / "completed" / "007_auth"):
            d.mkdir(parents=True)
        (sibling / "config.yaml").write_text("x")
        kw = {"repo_root": repo, "spec_root": spec, "env": {"SET": "1", "EMPTY": " "}}
        said = _evaluate("env SET; env EMPTY; env ABSENT", **kw)
        assert [ok for ok, _ in said] == [True, False, False]
        assert said[1][1] == "EMPTY is not set in this pod"
        said = _evaluate("file ../Sibling:config.yaml; file ../Sibling:nope; "
                         "file .:../Sibling/config.yaml", **kw)
        assert [ok for ok, _ in said] == [True, False, True]
        said = _evaluate("slice 7 completed; slice 007 completed; slice 8 completed", **kw)
        assert [ok for ok, _ in said] == [True, True, False]
        assert checks.evaluate(checks.parse("manual")[0], **kw)[0] is None


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_origin_is_read_after_a_fetch():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bare, work, other = root / "remote.git", root / "App", root / "Other"
        _git("init", "--bare", "-b", "main", str(bare), cwd=root)
        _git("clone", str(bare), str(work), cwd=root)
        _git("clone", str(bare), str(other), cwd=root)
        for d in (work, other):
            _git("config", "user.email", "t@t", cwd=d)
            _git("config", "user.name", "t", cwd=d)
        (work / "config.yaml").write_text("tools:\n  - use: python\n")
        _git("add", ".", cwd=work)
        _git("commit", "-m", "c", cwd=work)
        _git("push", "origin", "HEAD:main", cwd=work)
        kw = {"repo_root": root / "Other", "spec_root": root, "env": {}}
        text = ("origin . main:config.yaml contains use: python; "
                "origin . main:config.yaml contains use: go; "
                "origin . main:absent.yaml contains x; "
                "origin ../NotARepo main:x contains y")
        said = _evaluate(text, **kw)
        # `Other` never pulled: the check fetches before it reads
        assert [ok for ok, _ in said] == [True, False, False, False], said
        assert said[1][1] == "origin/main:config.yaml does not hold `use: go`"
        assert "has no absent.yaml" in said[2][1]
        assert "is not a git checkout" in said[3][1]


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
            print(f"FAIL {_fn.__name__}: {e!r}")
    print(f"\n{len(_tests) - failures} passed, {failures} failed")
    if failures:
        sys.exit(1)
