"""The labeller's file classes (docs/labeller.md § File classes): the class of
a File from its repository's name and its path alone.

A project's own rules (`projects/<repo>.json`'s `file_classes`, its
`.aiworkflowrc`'s `[[file_classes]]` in their order) go first, then the
starting list; the first rule that matches wins. Each rule is compiled to one
regular expression over the repository-relative path, so a File costs one
match per rule.

    rules = load_rules(data_dir, version)
    classify([["PilotApp", "backend/app/x.py"], ...], rules)  # -> ["code", ...]
    rules.digest                                              # `file_rules`
"""

import json
import os
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The classes a file may take, as `file_class` declares them.
CLASSES = ("code", "test", "docs", "spec", "generated", "record")

# The starting list, in its order (dispatch-work.md §7 with AIWorkflow's rule
# added, t17 D2). Each entry is (class, patterns, repository or None); None is
# every repository. The spec-repo rule (§ 2) stands in its place as SPEC_RULE.
SPEC_RULE = "spec-repo"
STARTING_LIST = (
    ("generated", ("*.lock", "pnpm-lock.yaml", "package-lock.json", "*.snap",
                   "**/generated/**", "*.gen.*"), None),
    SPEC_RULE,
    ("test", ("**/tests/**", "**/test/**", "*.spec.ts", "*.test.ts", "*.test.tsx",
              "test_*.py", "*_test.py", "*_test.go", "conftest.py"), None),
    # O7, ruled: after the tests, so the plugin's suites stay `test`, and
    # before the docs, so its skills and agents are `code`.
    ("code", ("plugins/**",), "AIWorkflow"),
    ("docs", ("*.md", "README*", "CHANGELOG*"), None),
    ("code", ("**",), None),
)

# A slice folder of a spec repo: a segment directly under `slices/`, or under
# one of its status folders.
SLICE_STATUSES = ("backlog", "active", "completed", "archive", "cancelled", "deferred")
SLICE_FOLDER = r"\d{3}[a-z]?_[a-z0-9_]+"
_IN_SLICE = (r"slices/(?:(?:" + "|".join(SLICE_STATUSES) + r")/)?"
             + SLICE_FOLDER + r"/.+")
# The spec-repo rule as three compiled rules: a slice folder's Markdown, the
# rest of a slice folder, anywhere else.
_SPEC_RULES = (
    ("spec", re.compile(_IN_SLICE + r"\.md")),
    ("record", re.compile(_IN_SLICE)),
    ("spec", re.compile(r".*", re.S)),
)


def pattern_regex(pattern: str) -> str:
    """One pattern of the grammar (project-contract.md § File classes) as a
    regular expression to fullmatch a repository-relative path: `*` matches
    within one segment, `**` any number of segments (`**/` zero or more), and
    a pattern with no `/` matches the basename anywhere. Every other
    character is literal."""
    pattern = pattern.strip().lstrip("/")
    anywhere = "/" not in pattern
    parts = pattern.split("/")
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:.*/)?")
            continue
        seg = "".join("[^/]*" if chunk == "*" else re.escape(chunk)
                      for chunk in re.split(r"(\*)", part.replace("**", "*")) if chunk)
        out.append(seg if last else seg + "/")
    body = "".join(out)
    return "(?:.*/)?" + body if anywhere else body


def compile_patterns(patterns) -> re.Pattern:
    """One rule's patterns as one regular expression."""
    return re.compile("|".join(f"(?:{pattern_regex(p)})" for p in patterns), re.S)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _project_rules(data_dir: Path | None) -> dict[str, list[dict]]:
    """Every `projects/<repo>.json`'s rules, by repository name, each rule
    `{"class", "paths"}`. A rule of an unknown class or with no pattern is
    left out; so is a file that does not read."""
    found: dict[str, list[dict]] = {}
    folder = data_dir / "projects" if data_dir else None
    try:
        names = sorted(os.listdir(folder)) if folder else []
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".json"):
            continue
        data = _read_json(folder / name)
        if not isinstance(data, dict):
            continue
        repo = data.get("repo") if isinstance(data.get("repo"), str) else name[:-5]
        rules = []
        for rule in data.get("file_classes") or []:
            if not isinstance(rule, dict) or rule.get("class") not in CLASSES:
                continue
            paths = [p for p in rule.get("paths") or [] if isinstance(p, str) and p.strip()]
            if paths:
                rules.append({"class": rule["class"], "paths": paths})
        found[repo] = rules
    return found


def spec_repos(data_dir: Path | None) -> set[str]:
    """The spec repos: the run records' `runs/<spec-repo>/` folders and the
    groups' `spec_repo`."""
    repos: set[str] = set()
    if not data_dir:
        return repos
    try:
        with os.scandir(data_dir / "runs") as it:
            repos.update(e.name for e in it if e.is_dir())
    except OSError:
        pass
    try:
        groups = sorted((data_dir / "groups").glob("*.toml"))
    except OSError:
        groups = []
    for path in groups:
        try:
            spec = tomllib.loads(path.read_text()).get("spec_repo")
        except (OSError, ValueError):
            continue
        if isinstance(spec, str) and spec:
            repos.add(spec)
    return repos


class FileRules:
    """The effective rules: every project's own, the spec repos and the
    starting list, compiled per repository on first use."""

    def __init__(self, version: str, projects: dict[str, list[dict]],
                 specs: set[str]):
        self.version = version
        self.projects = projects
        self.spec_repos = frozenset(specs)
        self.digest = _digest({"version": version, "projects": projects,
                               "spec_repos": sorted(specs)})
        self._compiled: dict[str, tuple] = {}
        self._starting: dict[tuple, re.Pattern] = {}

    def for_repo(self, repo: str) -> tuple:
        """(class, compiled regex) per rule for `repo`, in the order tried."""
        compiled = self._compiled.get(repo)
        if compiled is None:
            compiled = self._compiled[repo] = self._compile(repo)
        return compiled

    def _compile(self, repo: str) -> tuple:
        rules = [(r["class"], compile_patterns(r["paths"]))
                 for r in self.projects.get(repo, [])]
        for entry in STARTING_LIST:
            if entry == SPEC_RULE:
                if repo in self.spec_repos:
                    rules.extend(_SPEC_RULES)
                continue
            cls, patterns, only = entry
            if only is not None and only != repo:
                continue
            key = (cls, patterns)
            if key not in self._starting:
                self._starting[key] = compile_patterns(patterns)
            rules.append((cls, self._starting[key]))
        return tuple(rules)

    def classify(self, repo: str, path: str) -> str:
        path = path.lstrip("/")
        for cls, regex in self.for_repo(repo):
            if regex.fullmatch(path):
                return cls
        return "code"


def _digest(value) -> str:
    import labeller_vocab
    return labeller_vocab.digest(value)


def load_rules(data_dir: Path | None, version: str) -> FileRules:
    """The effective rules from the run records' `projects/` and run
    folders: a stat and a few small reads."""
    return FileRules(version, _project_rules(data_dir), spec_repos(data_dir))


def classify(files, rules: FileRules) -> list[str]:
    """The class of each `[repo, path]` in `files`, in their order."""
    cls_of = rules.classify
    return [cls_of(repo, path) for repo, path in files]
