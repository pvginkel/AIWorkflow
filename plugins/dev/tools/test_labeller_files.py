"""Tests for labeller_files — the file classes (docs/labeller.md § File
classes): the grammar, the starting list, the spec repos and `file_rules`.

Every data folder is a temp dir; nothing reads the real home.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_labeller_files.py` or via pytest.
"""

import contextlib
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "labeller_files", Path(__file__).resolve().parent / "labeller_files.py")
files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(files)


@contextlib.contextmanager
def data_dir(projects=None, runs=(), groups=None):
    """A data folder: `projects/<repo>.json` per {repo: rules}, a
    `runs/<spec-repo>/` per name, and `groups/<name>.toml` per {name: text}."""
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        for repo, rules in (projects or {}).items():
            (data / "projects").mkdir(exist_ok=True)
            (data / "projects" / f"{repo}.json").write_text(json.dumps(
                {"repo": repo, "file_classes": rules, "updated_at": "x",
                 "plugin_version": "0"}))
        for spec in runs:
            (data / "runs" / spec / "001_one").mkdir(parents=True)
        for name, text in (groups or {}).items():
            (data / "groups").mkdir(exist_ok=True)
            (data / "groups" / f"{name}.toml").write_text(text)
        yield data


def classes(rules, repo, *paths):
    return files.classify([[repo, p] for p in paths], rules)


def matches(pattern, path):
    return re.fullmatch(files.pattern_regex(pattern), path) is not None


def test_a_star_matches_within_one_segment_and_a_double_star_any_number():
    assert matches("src/*.py", "src/a.py")
    assert not matches("src/*.py", "src/sub/a.py")
    assert matches("src/**/*.py", "src/a.py")
    assert matches("src/**/*.py", "src/sub/deep/a.py")
    assert matches("backend/openapi-cache/**", "backend/openapi-cache/openapi.json")
    assert not matches("backend/openapi-cache/**", "frontend/backend/openapi-cache/x")


def test_a_leading_double_star_matches_zero_segments():
    assert matches("**/generated/**", "generated/x.ts")
    assert matches("**/generated/**", "a/b/generated/c/x.ts")
    assert not matches("**/generated/**", "a/generatedx/c.ts")


def test_a_pattern_with_no_slash_matches_the_basename_anywhere():
    assert matches("*.lock", "uv.lock")
    assert matches("*.lock", "backend/uv.lock")
    assert matches("conftest.py", "backend/tests/conftest.py")
    assert not matches("conftest.py", "backend/myconftest.py")
    assert not matches("*.lock", "a.lock/b.py")


def test_every_other_character_is_literal():
    assert matches("a+b.[x]", "a+b.[x]")
    assert not matches("a.b", "axb")
    assert matches("/root.txt", "root.txt")


def test_the_starting_list_classes_a_product_repository():
    with data_dir() as data:
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "Foo",
                       "uv.lock", "frontend/pnpm-lock.yaml", "x/package-lock.json",
                       "a/__snapshots__/b.snap", "src/generated/api.ts", "api.gen.go",
                       "backend/tests/test_a.py", "test/x.go", "src/a.spec.ts",
                       "src/a.test.ts", "src/a.test.tsx", "tools/test_x.py", "x_test.py",
                       "pkg/a_test.go", "conftest.py",
                       "docs/ui.md", "README", "README.rst", "CHANGELOG.txt",
                       "backend/app/x.py", "Jenkinsfile", "plugins/dev/x.md") == [
            "generated"] * 6 + ["test"] * 9 + ["docs"] * 4 + ["code", "code", "docs"]


def test_a_generated_rule_goes_before_the_tests():
    with data_dir() as data:
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "Foo", "tests/generated/x.py", "tests/a.snap") == [
            "generated", "generated"]


def test_aiworkflows_plugins_are_code_after_the_tests_and_before_the_docs():
    with data_dir() as data:
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "AIWorkflow",
                       "plugins/dev/tools/test_labeller.py",
                       "plugins/dev/skills/triage/SKILL.md",
                       "plugins/dev/agents/code-writer.md",
                       "plugins/dev/tools/labeller.py",
                       "docs/AUTHORING.md", "README.md") == [
            "test", "code", "code", "code", "docs", "docs"]
        # The rule is AIWorkflow's alone.
        assert classes(rules, "Other", "plugins/x/SKILL.md") == ["docs"]


def test_a_spec_repo_is_a_run_records_folder_or_a_groups_spec_repo():
    groups = {"BarSpecs": 'spec_repo = "BarSpecs"\nrepo = "Bar"\n'}
    with data_dir(runs=["FooSpecs"], groups=groups) as data:
        assert files.spec_repos(data) == {"FooSpecs", "BarSpecs"}
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "BarSpecs", "design/README.md", "tools/x.py") == [
            "spec", "spec"]
        assert classes(rules, "Foo", "tools/x.py") == ["code"]


def test_in_a_spec_repo_a_slice_folders_markdown_is_spec_and_the_rest_record():
    with data_dir(runs=["FooSpecs"]) as data:
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "FooSpecs",
                       "slices/completed/044_web_push/plan.md",
                       "slices/completed/044_web_push/state.json",
                       "slices/completed/044_web_push/phases/P1/review_r1.json",
                       "slices/044a_x/log.txt",
                       "slices/backlog/012_y/slice.md",
                       "slices/deferred/012_y/asks/1-requirements.md",
                       "slices/README.md",
                       "slices/other/012_y/state.json",
                       "slices/completed/44_short/state.json",
                       "design/features.md",
                       "tools/cost-dashboard/collect.py",
                       "tests/test_x.py",
                       "uv.lock") == [
            "spec", "record", "record", "record", "spec", "spec", "spec", "spec",
            "spec", "spec", "spec", "spec", "generated"]


def test_a_projects_own_rules_go_first_in_their_order():
    projects = {"PilotApp": [
        {"class": "generated", "paths": ["backend/openapi-cache/**"]},
        {"class": "docs", "paths": ["backend/openapi-cache/README.md", "notes/*.txt"]},
        {"class": "test", "paths": ["*.md"]},
    ]}
    with data_dir(projects=projects) as data:
        rules = files.load_rules(data, "0.1.0")
        assert classes(rules, "PilotApp",
                       "backend/openapi-cache/README.md", "notes/a.txt",
                       "docs/ui.md", "uv.lock", "backend/app/x.py") == [
            "generated", "docs", "test", "generated", "code"]
        assert classes(rules, "Other", "docs/ui.md") == ["docs"]


def test_a_rule_that_does_not_read_is_left_out_and_a_file_that_does_not_parse_too():
    projects = {"Foo": [{"class": "nonsense", "paths": ["*"]},
                        {"class": "test", "paths": []},
                        {"class": "record", "paths": ["", 3, "out/**"]}]}
    with data_dir(projects=projects) as data:
        (data / "projects" / "Bad.json").write_text("{not json")
        rules = files.load_rules(data, "0.1.0")
        assert rules.projects["Foo"] == [{"class": "record", "paths": ["out/**"]}]
        assert "Bad" not in rules.projects
        assert classes(rules, "Foo", "out/a.py", "x.py") == ["record", "code"]


def test_the_classes_come_back_in_request_order():
    with data_dir() as data:
        rules = files.load_rules(data, "0.1.0")
        req = [["A", "x.md"], ["B", "y.py"], ["A", "uv.lock"], ["B", "x.md"]]
        assert files.classify(req, rules) == ["docs", "code", "generated", "docs"]


def test_file_rules_changes_with_the_version_the_rules_and_the_spec_repos_alone():
    rule = [{"class": "generated", "paths": ["out/**"]}]
    with data_dir(projects={"Foo": rule}, runs=["FooSpecs"]) as data:
        a = files.load_rules(data, "0.1.0").digest
        assert re.fullmatch(r"[A-Za-z0-9_-]{22}", a)
        assert a == files.load_rules(data, "0.1.0").digest
        assert a != files.load_rules(data, "0.1.1").digest
        (data / "runs" / "BarSpecs").mkdir()
        b = files.load_rules(data, "0.1.0").digest
        assert b != a
        (data / "runs" / "FooSpecs" / "002_two").mkdir()  # a new slice changes nothing
        assert files.load_rules(data, "0.1.0").digest == b
        (data / "projects" / "Foo.json").write_text(json.dumps(
            {"repo": "Foo", "file_classes": [], "updated_at": "later"}))
        assert files.load_rules(data, "0.1.0").digest != b
    with data_dir(projects={"Foo": rule}, runs=["FooSpecs"]) as data:
        (data / "projects" / "Foo.json").write_text(json.dumps(
            {"repo": "Foo", "file_classes": rule, "updated_at": "another time"}))
        assert files.load_rules(data, "0.1.0").digest == a


def test_no_data_folder_is_no_rules_beyond_the_starting_list():
    rules = files.load_rules(None, "0.1.0")
    assert classes(rules, "Foo", "a.md", "b.py") == ["docs", "code"]
    with tempfile.TemporaryDirectory() as tmp:
        rules = files.load_rules(Path(tmp) / "missing", "0.1.0")
        assert rules.spec_repos == frozenset() and rules.projects == {}


def test_every_class_a_rule_gives_is_one_the_labeller_declares():
    gives = {entry[0] for entry in files.STARTING_LIST if entry != files.SPEC_RULE}
    gives |= {cls for cls, _ in files._SPEC_RULES}
    assert gives <= set(files.CLASSES)


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
