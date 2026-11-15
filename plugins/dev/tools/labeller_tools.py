"""The labeller's rules of one Tool Call: what a command is, what it changed outside its
transcript, which host rule it breached, the Test Runs its result shows, the CI Builds a
`track_build.py` summary names, and the sections of a dispatch's orientation digest.

The contract is `docs/labeller.md` (§ The labels, by entity, *Tool Call*, *Event* and *Context
Part*; § Test Runs and CI Builds). This module is its Part 3: pure functions of one call, its
result and a little context (`ToolCtx`). It knows nothing of transcripts, Launches or the run
records; the engine (`labeller_engine.py`) calls it once per Tool Call and keeps what spans calls
— a background wait's stretch, the tasks still running — itself.

    tool_labels(name, input, result, ctx)  -> the call's labels, a dict (below)
    digest_sections(prompt_text)           -> [{"name", "characters"}]
    ci_builds(wait, summary, returned_at)  -> the CI Build rows a matched summary gives
    parse_track_summary(text)              -> every `track_build.py` summary in a text
    parse_test_summaries(text)             -> every test runner summary in a text

A Bash command is read through `turn_profile`'s shell reading (`_bash`, `_unwrap`, `_split`), so
`cexec`, `timeout`, `sh -c` and `cd … &&` hide no program, and a program named inside quoted text
or a heredoc body counts for nothing. Stdlib only.
"""

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import turn_profile as tp  # noqa: E402

# ---------------------------------------------------------------------------
# The codes, as Part 1's vocabularies declare them (labeller.md § The vocabularies).
# ---------------------------------------------------------------------------

TEST_SUITE, GATE, CI_WAIT, CHUNKED_WAIT, SLEEP_POLL, GIT = (
    "test_suite", "gate", "ci_wait", "chunked_wait", "sleep_poll", "git")
CARD_CREATED, CARD_UPDATED, FIELDNOTE_POSTED, DOCUMENT_REGISTERED, PUSH = (
    "card_created", "card_updated", "fieldnote_posted", "document_registered", "push")
NO_SLEEP_POLL, NO_GIT_ADD_ALL, NO_TAIL_ON_BACKGROUND_LOG = (
    "no_sleep_poll", "no_git_add_all", "no_tail_on_background_log")
GATE_RED = "gate_red"
DIGEST_SECTION = "digest_section"
BUILD_RESULTS = ("SUCCESS", "FAILURE", "ABORTED", "UNSTABLE", "NOT_BUILT")

# O9 (labeller.md § Open points): whether `no_git_add_all` counts in any tree or only in a spec
# repo's. Until it is ruled, any tree. `_add_all_counts` is the one place that reads it.
ADD_ALL_ONLY_IN_SPEC_REPO = False


@dataclass(frozen=True)
class ToolCtx:
    """The little a rule needs beyond the call and its result, all of it the engine's.

    - `cwd`: the transcript's working directory at the call (its line's `cwd`).
    - `requested_at`, `result_at`: the asking assistant line's time and the result line's.
    - `is_error`: the tool result's `is_error`.
    - `background_writes`: the files a background task of the same Launch is still writing — the
      output file its notification will name, and the `>` / `tee` targets of its command — for
      the tasks not yet notified as ended (`no_tail_on_background_log`).
    - `spec_repos`: the spec repos' names, read only where O9 rules a spec repo alone.
    """

    cwd: str | None = None
    requested_at: str | None = None
    result_at: str | None = None
    is_error: bool = False
    background_writes: frozenset[str] = field(default_factory=frozenset)
    spec_repos: frozenset[str] = field(default_factory=frozenset)


def _ctx(ctx: ToolCtx | Mapping | None) -> ToolCtx:
    if ctx is None:
        return ToolCtx()
    if isinstance(ctx, ToolCtx):
        return ctx
    d = dict(ctx)
    for k in ("background_writes", "spec_repos"):
        if k in d:
            d[k] = frozenset(d[k] or ())
    return ToolCtx(**d)


# ---------------------------------------------------------------------------
# The shell: a Bash command's steps, resolved, each with the directory it ran in.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Stage:
    text: str          # one pipeline stage, unwrapped (`timeout`, `cexec`, `uv run` … peeled)
    cwd: str | None    # the directory it ran in, as the command's `cd`s leave it
    blank: str         # `text` with its quoted strings emptied (`turn_profile._blank`)


def _words(s: str) -> list[str]:
    """`s` cut into shell words, each unquoted."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        j = tp._word_end(s, i)
        out.append(tp._unquote(s[i:j]))
        i = j
    return out


def _join(cwd: str | None, path: str) -> str | None:
    """`path` made absolute against `cwd`; None for one the shell would expand first."""
    if not path or path.startswith(("~", "$", "-")):
        return None
    if path.startswith("/"):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(cwd, path)) if cwd else path


def _stages(cmd: str, cwd: str | None) -> list[_Stage]:
    """Every pipeline stage a Bash command ran, in order, with the directory each ran in."""
    out: list[_Stage] = []
    for c in tp._bash(cmd).commands:
        for raw in tp._split(c, pipes=True):
            s = tp.REDIR_PREFIX_RE.sub("", tp._unwrap(raw))
            if not s:
                continue
            words = _words(s)
            if words and words[0] in ("cd", "pushd"):
                args = [w for w in words[1:] if not w.startswith("-")]
                if args:
                    cwd = _join(cwd, args[0]) or cwd
                continue
            out.append(_Stage(s, cwd, tp._blank(s)))
    return out


# The program patterns, matched at a stage's start once its wrappers are peeled.
_PY = r"(?:\S*/)?python3?(?:\.\d+)?(?:\s+-[A-Za-z]+)*\s+"
_SCRIPT = r"[\"']?(?:[^\s\"']*/)?"
_PM = (r"(?:npx|pnpm|npm|yarn)(?:\s+(?:(?:-C|--dir|--filter|--prefix|-F|-w|--workspace)\s+\S+"
       r"|--?[\w-]+(?:=\S+)?))*(?:\s+(?:exec|dlx|x))?\s+")
TRACK_BUILD_RE = re.compile(rf"^(?:{_PY})?{_SCRIPT}track_build(?:\.py)?[\"']?(?=\s|$)")
SPEC_CHECK_RE = re.compile(rf"^(?:{_PY})?{_SCRIPT}spec_check\.py[\"']?(?=\s|$)")
KC_PROJECT_RE = re.compile(r"^kc\s+(?:-\S+\s+)*project\s+(test|lint|build)(?![\w-])")
UV_WITH_PYTEST_RE = re.compile(r"\buv\s+run\b[^;&|\n]*?\s--with[=\s]+[\"']?pytest\b")

# (rule, pattern, detail): the program patterns of command_class's rules 4 and 5 — the rest
# are tested by the workflow's own script reading (`_workflow`) or by program name.
_TEST_PROGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:\S*/)?(?:pytest|py\.test)(?![\w.-])"), "pytest"),
    (re.compile(rf"^{_PY}(?:-\S+\s+)*-m\s+pytest(?![\w.-])"), "pytest"),
    (re.compile(r"^(?:\S*/)?go\s+test(?![\w-])"), "go test"),
    (re.compile(rf"^(?:{_PM})?(?:\S*/)?playwright\s+test(?![\w-])"), "playwright test"),
    (re.compile(r"^npm(?:\s+(?:(?:-C|--prefix|-w|--workspace)\s+\S+|--?[\w-]+(?:=\S+)?))*"
                r"\s+(?:run(?:-script)?\s+)?test(?::\S+)?(?=\s|$)"), "npm test"),
    (re.compile(r"^pnpm(?:\s+(?:(?:-C|--dir|--filter|-F|-w)\s+\S+|--?[\w-]+(?:=\S+)?))*"
                r"\s+(?:run\s+)?test(?::\S+)?(?=\s|$)"), "pnpm test"),
]
_GATE_PROGS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"^(?:(?:{_PY})-m\s+|{_PM})?(?:\S*/)?ruff(?![\w-])"), "ruff"),
    (re.compile(rf"^(?:(?:{_PY})-m\s+|{_PM})?(?:\S*/)?mypy(?![\w-])"), "mypy"),
    (re.compile(rf"^(?:{_PM})?(?:\S*/)?tsc(?![\w-])"), "tsc"),
    (re.compile(r"^(?:\S*/)?golangci-lint(?![\w-])"), "golangci-lint"),
    (re.compile(r"^(?:\S*/)?ansible-lint(?![\w-])"), "ansible-lint"),
]
_GIT_GLOBAL_VALUED = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def _workflow(stage: _Stage) -> tuple[str, str] | None:
    """(script, verb) of a stage that runs one of the workflow's own scripts."""
    m = tp.WORKFLOW_RE.match(stage.text)
    if not m:
        return None
    return (m.group(1) or m.group(2)), tp._verb(stage.text[m.end():])


def _kc_project(stage: _Stage) -> tuple[str, str | None] | None:
    """(verb, component or None) of a `kc project test|lint|build` stage."""
    m = KC_PROJECT_RE.match(stage.blank)
    if not m:
        return None
    words = _words(stage.text)
    comp = None
    for i, w in enumerate(words):
        if w in ("--project", "-p") and i + 1 < len(words):
            comp = words[i + 1]
        elif w.startswith("--project="):
            comp = w.split("=", 1)[1]
    return m.group(1), comp


def _git(stage: _Stage) -> tuple[str, list[str], str | None] | None:
    """(subcommand, its arguments, the tree it ran in) of a git stage."""
    words = _words(stage.text)
    if not words or words[0].rsplit("/", 1)[-1] != "git":
        return None
    i, tree = 1, stage.cwd
    while i < len(words) and words[i].startswith("-"):
        w = words[i]
        if w in _GIT_GLOBAL_VALUED:
            if w == "-C" and i + 1 < len(words):
                tree = _join(tree, words[i + 1]) or tree
            i += 2
        else:
            i += 1
    if i >= len(words):
        return "", [], tree
    return words[i], words[i + 1:], tree


def _stage_rule(stage: _Stage) -> tuple[int, str, str] | None:
    """(rule number, command class, detail) of the first of command_class's rules a stage
    meets on its own; rule 4's `uv run --with pytest` is the command's, tested apart."""
    if TRACK_BUILD_RE.match(stage.text):
        return 1, CI_WAIT, "track_build.py"
    wf = _workflow(stage)
    if wf and wf[0] in ("run_loop", "plan_loop", "long_run") and wf[1] == "wait":
        return 2, CHUNKED_WAIT, f"{wf[0]}.py wait"
    if wf and wf[0] == "run_loop" and wf[1] == "gate":
        return 3, GATE, "run_loop.py gate"
    if SPEC_CHECK_RE.match(stage.text):
        return 3, GATE, "spec_check.py"
    kc = _kc_project(stage)
    if kc:
        verb, comp = kc
        detail = f"{comp} {verb}" if comp else verb
        return (4, TEST_SUITE, detail) if verb == "test" else (5, GATE, detail)
    for rx, detail in _TEST_PROGS:
        if rx.match(stage.blank):
            return 4, TEST_SUITE, detail
    for rx, detail in _GATE_PROGS:
        if rx.match(stage.blank):
            return 5, GATE, detail
    if re.match(r"^sleep\s+\d", stage.blank):
        return 6, SLEEP_POLL, "sleep"
    if _git(stage):
        return 7, GIT, "git"
    return None


def _command_class(cmd: str, stages: list[_Stage]) -> tuple[str | None, str | None]:
    """(command class, detail): the first rule of labeller.md's list that any step meets."""
    best: tuple[int, str, str] | None = None
    for st in stages:
        r = _stage_rule(st)
        if r and (best is None or r[0] < best[0]):
            best = r
    if (best is None or best[0] > 4) and UV_WITH_PYTEST_RE.search(
            tp._blank(tp._strip_heredocs(cmd))):
        best = (4, TEST_SUITE, "pytest")
    return (best[1], best[2]) if best else (None, None)


def command_class(cmd: str, cwd: str | None = None) -> str | None:
    """The command class of one Bash command, or None."""
    return _command_class(cmd, _stages(cmd, cwd))[0]


# ---------------------------------------------------------------------------
# Results: their text, their failure.
# ---------------------------------------------------------------------------

def result_text(result) -> str:
    """A tool result's text: a string as is, a list of content blocks their text joined."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        if "content" in result and "type" not in result:
            return result_text(result["content"])
        return str(result.get("text") or "")
    if isinstance(result, list):
        return "\n".join(result_text(b) for b in result if isinstance(b, (Mapping, str)))
    return str(result)


def _json(text: str):
    try:
        return json.loads(text.strip())
    except (ValueError, TypeError):
        return None


EXIT_CODE_RE = re.compile(r"\AExit code (\d+)")


def _failed(text: str, ctx: ToolCtx) -> bool:
    """A non-zero exit (Claude Code's `Exit code <n>` head) or the result's `is_error`."""
    m = EXIT_CODE_RE.match(text)
    return ctx.is_error or bool(m and m.group(1) != "0")


# ---------------------------------------------------------------------------
# Effects: what a successful call changed outside its transcript.
# ---------------------------------------------------------------------------

PUSH_FAILED_RE = re.compile(r"!\s+\[(?:rejected|remote rejected)\]|error: failed to push"
                            r"|^fatal:", re.M)


def _mcp_id(text: str) -> str | None:
    d = _json(text)
    if isinstance(d, Mapping) and isinstance(d.get("id"), str) and d["id"] and not d.get("error"):
        return d["id"]
    return None


def _effect(name: str, inp: Mapping, text: str, stages: list[_Stage],
            ctx: ToolCtx) -> tuple[str | None, str | None]:
    if _failed(text, ctx):
        return None, None
    tool = name.rsplit("__", 1)[-1] if name.startswith("mcp__") else None
    if tool == "create_issue":
        sid = _mcp_id(text)
        return (CARD_CREATED, sid) if sid else (None, None)
    if tool in ("update_issue", "add_comment"):
        d = _json(text)
        if isinstance(d, Mapping) and d.get("error"):
            return None, None
        card = inp.get("id") or inp.get("issue_id") or inp.get("issue")
        return CARD_UPDATED, (str(card) if card else None)
    if tool == "post":
        sid = _mcp_id(text)       # a post that matched a fieldnote held answers `"id": null`
        return (FIELDNOTE_POSTED, sid) if sid else (None, None)
    if tool == "register_document":
        d = _json(text)
        if isinstance(d, Mapping) and d.get("error"):
            return None, None
        path = inp.get("path")
        return DOCUMENT_REGISTERED, (str(path) if path else None)
    if name == "Bash" and not PUSH_FAILED_RE.search(text):
        for st in stages:
            g = _git(st)
            if g and g[0] == "push" and not {"-n", "--dry-run"} & set(g[1]):
                return PUSH, None
    return None, None


# ---------------------------------------------------------------------------
# Rule breaches.
# ---------------------------------------------------------------------------

_COMMIT_VALUED = set("mFCcte")      # a short option of `git commit` that takes the rest as value


def _adds_all(sub: str, args: list[str]) -> bool:
    if sub == "add":
        return any(a in ("-A", "--all", ".") or re.fullmatch(r"-[a-zA-Z]*A[a-zA-Z]*", a)
                   for a in args)
    if sub == "commit":
        for a in args:
            if a == "--all":
                return True
            if re.fullmatch(r"-[a-zA-Z]+", a):
                for ch in a[1:]:
                    if ch == "a":
                        return True
                    if ch in _COMMIT_VALUED:
                        break
    return False


def repo_of(path: str | None) -> str | None:
    """The checkout a path lies in: `/work/<Repo>`, `/work/scratch/<Repo>`, a linked worktree
    `/work/scratch/worktrees/<Repo>/<name>`, or an older machine's `~/source/<Repo>[-n]`."""
    if not path:
        return None
    m = re.match(r"^/work/scratch/worktrees/([^/]+)", path) or \
        re.match(r"^/work/scratch/([^/]+)", path) or re.match(r"^/work/([^/]+)", path)
    if m and m.group(1) not in ("scratch", "worktrees"):
        return m.group(1)
    m = re.match(r"^/home/[^/]+/source/([^/]+)", path)
    if m:
        return re.sub(r"-\d+$", "", m.group(1))
    return Path(path).name or None


def _add_all_counts(tree: str | None, ctx: ToolCtx) -> bool:
    """O9's one place: whether a `git add -A` in this tree is a breach."""
    return not ADD_ALL_ONLY_IN_SPEC_REPO or repo_of(tree) in ctx.spec_repos


def _tails(stages: list[_Stage]) -> list[str]:
    """The files the `tail` steps read, as paths."""
    out: list[str] = []
    for st in stages:
        words = _words(st.text)
        if not words or words[0].rsplit("/", 1)[-1] != "tail":
            continue
        skip = False
        for w in words[1:]:
            if skip:
                skip = False
            elif w in ("-n", "-c", "--lines", "--bytes", "-s", "--pid"):
                skip = True
            elif not w.startswith(("-", "+")) and not re.fullmatch(r"\d*(?:>>?|<|&>)\S*", w):
                p = _join(st.cwd, w)
                if p:
                    out.append(p)
    return out


def _rules(cls: str | None, stages: list[_Stage], ctx: ToolCtx) -> list[str]:
    out: list[str] = []
    if cls == SLEEP_POLL:
        out.append(NO_SLEEP_POLL)
    for st in stages:
        g = _git(st)
        if g and _adds_all(g[0], g[1]) and _add_all_counts(g[2], ctx):
            out.append(NO_GIT_ADD_ALL)
            break
    writing = {os.path.normpath(p) for p in ctx.background_writes}
    if writing and any(os.path.normpath(p) in writing for p in _tails(stages)):
        out.append(NO_TAIL_ON_BACKGROUND_LOG)
    return out


# ---------------------------------------------------------------------------
# Background tasks and what a call read: the engine's matter for a background CI wait.
# ---------------------------------------------------------------------------

BACKGROUND_RE = re.compile(r"running in background with ID: (?P<id>[\w-]+)")
OUTPUT_FILE_RE = re.compile(r"Output is being written to: (?P<path>\S+?)\.?(?=\s|$)")
READ_PROG_NAMES = {"cat", "tail", "head", "less", "more", "nl", "sed", "grep", "awk"}


def _background(inp: Mapping, cmd: str, text: str, cwd: str | None) -> dict | None:
    """A `run_in_background` Bash call's task: its id, the output file its notification will
    name, and every file it writes (that file and its command's `>` / `tee` targets)."""
    if not inp.get("run_in_background"):
        return None
    m = BACKGROUND_RE.search(text)
    f = OUTPUT_FILE_RE.search(text)
    output = f.group("path") if f else None
    writes = [output] if output else []
    for st in _stages(cmd, cwd):
        for t in [m2.group(1) for m2 in tp.REDIRECT_RE.finditer(st.blank)] + \
                 [m2.group(1) for m2 in tp.TEE_RE.finditer(st.blank)]:
            p = _join(st.cwd, t)
            if p and p != "/dev/null" and p not in writes:
                writes.append(p)
    return {"task_id": m.group("id") if m else None, "output_file": output, "writes": writes}


def _reads(name: str, inp: Mapping, stages: list[_Stage]) -> dict:
    """The files and background tasks a call read."""
    paths: list[str] = []
    tasks: list[str] = []
    if name == "Read" and inp.get("file_path"):
        paths.append(str(inp["file_path"]))
    elif name in ("TaskOutput", "BashOutput"):
        tid = inp.get("task_id") or inp.get("bash_id") or inp.get("shell_id")
        if tid:
            tasks.append(str(tid))
    elif name == "Bash":
        for st in stages:
            words = _words(st.text)
            if not words or words[0].rsplit("/", 1)[-1] not in READ_PROG_NAMES:
                continue
            for w in words[1:]:
                if not w.startswith(("-", "+")) and ("/" in w or "." in w):
                    p = _join(st.cwd, w)
                    if p:
                        paths.append(p)
    return {"paths": paths, "task_ids": tasks}


# ---------------------------------------------------------------------------
# track_build.py's summary.
# ---------------------------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")      # a terminal's colours
SUMMARY_HEAD = "=== Build tracking summary ==="
FOLLOW_HEAD = "=== Argo CD follow ==="
LINE_NO_RE = re.compile(r"^\s*\d+(?:\t|→)")
ROW_RE = re.compile(r"^(?P<job>\S+)\s+#(?P<number>\d+)\s+(?P<result>\S+)\s+"
                    r"(?P<duration>\d+m\d{2}s)(?:\s+(?P<url>\S+))?\s*$")
TIMES_RE = re.compile(r"^\s+↳ queued (?P<queued>\S+)\s+started (?P<started>\S+)"
                      r"\s+ended (?P<ended>\S+)\s*$")
HANDOFF_RE = re.compile(r"^(?P<repo>\S+) (?P<what>.+) \((?P<job>\S+) #(?P<number>\d+)\)\s*$")
APP_RE = re.compile(r"^  (?P<app>\S+)\s{2,}(?P<state>.+?)\s{2,}(?P<detail>.*)$")
ROLL_RE = re.compile(r"^\s+↳ (?:sync (?P<sync_start>\S+)–(?P<sync_end>\S+), )?"
                     r"roll ended (?P<roll_ended>\S+)\s*$")
SUPERSEDED_RE = re.compile(r"^\s+- (?:(?P<job>\S+) )?#(?P<old>\d+) superseded by #(?P<new>\d+)")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _iso(s: str | None) -> str | None:
    return s if s and ISO_RE.match(s) else None


def parse_track_summary(text: str) -> list[dict]:
    """Every `track_build.py` summary in a text, in order. Each is

        {"job": the first row's job,
         "builds": [{"job", "number", "result", "queued_at", "started_at", "ended_at"}],
         "superseded": [{"job", "old", "new"}],     # job None: the tracked build's own
         "result": the build section's `Result:` line,
         "follow": None or {"handoffs": [{"repo", "pushed", "job", "number",
                                          "apps": [{"app", "state", "sync_started_at",
                                                    "sync_ended_at", "roll_ended_at"}]}],
                            "result": its first `Result:` line, "rolled": bool}}

    A summary from before DI-42 has no `↳ queued` line, so its times are None, as is a `?`.
    Lines a Read tool numbered (`  12→…`) are read without their numbers."""
    lines = ANSI_RE.sub("", text).splitlines()
    if any(LINE_NO_RE.match(ln) and ln.endswith(SUMMARY_HEAD) for ln in lines):
        lines = [LINE_NO_RE.sub("", ln, count=1) for ln in lines]
    heads = [i for i, ln in enumerate(lines) if ln.strip() == SUMMARY_HEAD]
    out: list[dict] = []
    for k, h in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        out.append(_parse_one_summary(lines[h + 1:end]))
    return [s for s in out if s["builds"]]


def _parse_one_summary(lines: list[str]) -> dict:
    builds: list[dict] = []
    superseded: list[dict] = []
    result = None
    i = 0
    while i < len(lines) and lines[i].strip():
        m = ROW_RE.match(lines[i])
        if m:
            word = m.group("result")
            builds.append({"job": m.group("job"), "number": int(m.group("number")),
                           "result": word if word in BUILD_RESULTS else None,
                           "queued_at": None, "started_at": None, "ended_at": None})
        elif builds and (t := TIMES_RE.match(lines[i])):
            builds[-1].update(queued_at=_iso(t.group("queued")),
                              started_at=_iso(t.group("started")),
                              ended_at=_iso(t.group("ended")))
        i += 1
    follow_at = None
    for j in range(i, len(lines)):
        ln = lines[j]
        if (s := SUPERSEDED_RE.match(ln)):
            superseded.append({"job": s.group("job"), "old": int(s.group("old")),
                               "new": int(s.group("new"))})
        elif ln.startswith("Result: ") and result is None:
            result = ln[len("Result: "):].strip()
        elif ln.strip() == FOLLOW_HEAD:
            follow_at = j
            break
    follow = _parse_follow(lines[follow_at + 1:]) if follow_at is not None else None
    return {"job": builds[0]["job"] if builds else None, "builds": builds,
            "superseded": superseded, "result": result, "follow": follow}


def _parse_follow(lines: list[str]) -> dict:
    handoffs: list[dict] = []
    result = None
    for ln in lines:
        if not ln.strip():
            continue
        if ln.startswith("Result: "):
            result = result or ln[len("Result: "):].strip()
            continue
        if result is not None:
            continue                      # past the section's results: the clone hints, …
        if not ln.startswith(" ") and (h := HANDOFF_RE.match(ln)):
            what = h.group("what")
            pushed = " pushed to " in f" {what} " and "nothing pushed" not in what
            handoffs.append({"repo": h.group("repo"), "pushed": pushed,
                             "job": h.group("job"), "number": int(h.group("number")),
                             "apps": []})
        elif handoffs and (r := ROLL_RE.match(ln)) and handoffs[-1]["apps"]:
            handoffs[-1]["apps"][-1].update(sync_started_at=_iso(r.group("sync_start")),
                                            sync_ended_at=_iso(r.group("sync_end")),
                                            roll_ended_at=_iso(r.group("roll_ended")))
        elif handoffs and not ln.lstrip().startswith("↳") and (a := APP_RE.match(ln)):
            handoffs[-1]["apps"].append({"app": a.group("app"), "state": a.group("state").strip(),
                                         "sync_started_at": None, "sync_ended_at": None,
                                         "roll_ended_at": None})
    return {"handoffs": handoffs, "result": result,
            "rolled": bool(result and result.startswith("rolled"))}


def deployed_at(returned_at: str | None, roll_ended_at: str | None) -> str | None:
    """O5's one place, ruled 2026-11-15: the moment the wait returned, as the record has it.
    DI-42's `roll ended` time is parsed and handed here unused."""
    del roll_ended_at
    return returned_at


HASH_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")
_TB_VALUED = {"--hash", "--buildnr", "--url", "--user", "--token-env", "--poll-interval",
              "--appear-timeout", "--trigger-timeout", "--pickup-timeout", "--roll-timeout",
              "--log-dir"}


def _track_build_args(stage: _Stage) -> dict:
    """The job (the positional) and the commit (`--hash`) a `track_build.py` step names."""
    m = TRACK_BUILD_RE.match(stage.text)
    words = _words(stage.text[m.end():]) if m else []
    job = commit = None
    deploy = False
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--deploy":
            deploy = True
            i += 4
            continue
        key, eq, val = w.partition("=")
        if key in _TB_VALUED:
            if not eq:
                val = words[i + 1] if i + 1 < len(words) else ""
                i += 1
            if key == "--hash":
                commit = val if HASH_RE.match(val) else None
        elif not w.startswith("-") and job is None and not re.fullmatch(r"\d*(?:>>?|<|&>)\S*", w):
            job = w
        elif re.fullmatch(r"\d*(?:>>?|&>)", w):
            i += 1                        # a redirection and its target
        i += 1
    return {"job": None if deploy else job, "commit": None if deploy else commit}


def ci_builds(wait: Mapping, summary: Mapping, returned_at: str | None) -> list[dict]:
    """The CI Build rows a summary gives the wait it is matched to: one per table row, the
    pipelines the build triggered included. `commit` is the `--hash` on the row whose job the
    command named; `deployed_at` sits on each build a handoff heading names as pushed, where the
    follow's `Result:` opens `rolled` (O5: `deployed_at`). `returned_at` is when the wait
    returned: its result's time, or for a background wait its task notification's."""
    named = {n["job"]: n["commit"] for n in wait.get("named") or [] if n.get("job")}
    follow = summary.get("follow") or {}
    rolled: dict[tuple[str, int], str | None] = {}
    if follow.get("rolled"):
        for h in follow.get("handoffs") or []:
            if h["pushed"]:
                ends = [a["roll_ended_at"] for a in h["apps"] if a.get("roll_ended_at")]
                rolled[(h["job"], h["number"])] = max(ends) if ends else None
    out: list[dict] = []
    for b in summary.get("builds") or []:
        key = (b["job"], b["number"])
        out.append({"job": b["job"], "number": b["number"], "result": b["result"],
                    "queued_at": b["queued_at"], "started_at": b["started_at"],
                    "ended_at": b["ended_at"], "commit": named.get(b["job"]),
                    "deployed_at": deployed_at(returned_at, rolled[key])
                    if key in rolled else None})
    return out


# ---------------------------------------------------------------------------
# Test runner summaries.
# ---------------------------------------------------------------------------

# pytest's last line, plain (`-q`) or between `=` rules, xdist's the same.
PYTEST_LINE_RE = re.compile(
    r"^\s*=*\s*(?P<counts>(?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|warnings?"
    r"|deselected|rerun)(?:, )?)+|no tests ran)(?: in [\d.]+s(?: \([\d:]+\))?)\s*=*\s*$")
PYTEST_COUNT_RE = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|rerun)\b")
PYTEST_FAIL_RES = [
    re.compile(r"^\s*(?P<kind>FAILED|ERROR) (?P<name>\S+::\S+|\S+\.py)(?: - (?P<why>.*))?$"),
    re.compile(r"^\s*(?:\[gw\d+\]\s+)?(?:\[\s*\d+%\]\s+)?(?P<kind>FAILED|ERROR)"
               r" (?P<name>\S+::\S+)"),
    re.compile(r"^\s*(?P<name>\S+::\S+) (?P<kind>FAILED|ERROR)\b"),
]
PYTEST_FLAKY_RE = re.compile(r"^\s*FLAKY (?P<name>\S+)")
PYTEST_NOT_RERUN_RE = re.compile(r"^\s*NOT RERUN (?P<name>\S+)")
PYTEST_RERUN_RES = [
    re.compile(r"^\s*(?:\[gw\d+\]\s+)?(?:\[\s*\d+%\]\s+)?RERUN (?P<name>\S+::\S+)"),
    re.compile(r"^\s*(?P<name>\S+::\S+) RERUN\b"),
]
PW_COUNT_RE = re.compile(r"^(?P<indent>\s*)(?P<n>\d+) (?P<what>passed|failed|flaky|skipped"
                         r"|did not run|interrupted)(?: \([^)]*\))?\s*$")
PW_TEST_RE = re.compile(r"^\s+(?:\[[^\]]+\] › )?(?P<file>[^\s›]+?):\d+:\d+ › (?P<title>.+?)\s*$")
PW_RESULT_RE = re.compile(r"^\s*(?:✘|✓|×|✔|-|ok|x)\s+\d+\s+(?:\[[^\]]+\] › )?"
                          r"(?P<file>[^\s›]+?):\d+:\d+ › (?P<title>.+?)"
                          r"(?: \(retry #(?P<retry>\d+)\))?(?: \([\d.]+m?s\))?\s*$")
VITEST_TESTS_RE = re.compile(r"^\s*Tests\s+(?P<body>\d+ \w+(?: \| \d+ \w+)*)\s+\((?P<total>\d+)\)"
                             r"\s*$")
VITEST_FAIL_RE = re.compile(r"^\s*FAIL\s+(?P<file>\S+\.(?:test|spec)\.[cm]?[jt]sx?)"
                            r"(?:\s+>\s+(?P<title>.+?))?(?:\s+\[[^\]]*\])?\s*$")
GO_PKG_RE = re.compile(r"^\s*(?P<status>ok|FAIL)\s+(?P<pkg>\S+)\s+"
                       r"(?:[\d.]+s|\(cached\)|\[[^\]]+\])")
GO_TEST_RE = re.compile(r"^\s*--- (?P<status>PASS|FAIL|SKIP): (?P<name>[^\s/]+) \(")
GO_VERBOSE_RE = re.compile(r"^\s*(?:=== RUN|--- PASS:)")
NODE_COUNT_RE = re.compile(r"^\s*ℹ (?P<what>tests|fail) (?P<n>\d+)\s*$")
RED_MARK = "🔁 The run is red"
GREP_N_RE = re.compile(r"^\d+[:-](?=\S)")     # a `grep -n` of a log: `336:===== 3 failed …`
RETRY_FLAGS = {"pytest": r"--reruns", "playwright": r"--retries", "vitest": r"--retry"}


@dataclass
class Summary:
    """One test runner's summary in a result: `line` is where it ends, for kc's grouping."""

    runner: str
    line: int
    tests: int
    failed: bool
    failures: list[dict]                # {"test", "attempts", "flaky"}
    retries: int | None = None          # the most retries the output shows a test taking


def parse_test_summaries(text: str) -> list[Summary]:
    """Every test runner summary in a text: pytest (plain and xdist, the detect-flakes mode's
    section with it), Playwright's list reporter, vitest, `go test` and `node --test`. A line a
    `grep -n` numbered is read without its number, and the text without its colours."""
    text = ANSI_RE.sub("", text)
    lines = [GREP_N_RE.sub("", ln, count=1) for ln in text.splitlines()]
    red = RED_MARK in text
    return sorted(_pytest(lines, red) + _playwright(lines, red) + _vitest(lines) + _go(lines)
                  + _node(lines), key=lambda s: s.line)


def _pytest(lines: list[str], red: bool) -> list[Summary]:
    out: list[Summary] = []
    start = 0
    for i, ln in enumerate(lines):
        m = PYTEST_LINE_RE.match(ln)
        if not m:
            continue
        counts: dict[str, int] = {}
        for n, word in PYTEST_COUNT_RE.findall(m.group("counts")):
            word = "errors" if word == "error" else word
            counts[word] = counts.get(word, 0) + int(n)
        region = lines[start:i]
        start = i + 1
        failed: dict[str, None] = {}
        flaky: dict[str, None] = {}
        not_rerun: set[str] = set()
        reruns: dict[str, int] = {}
        for r in region:
            if (f := PYTEST_FLAKY_RE.match(r)):
                flaky[f.group("name")] = None
                continue
            if (f := PYTEST_NOT_RERUN_RE.match(r)):
                not_rerun.add(f.group("name"))
                failed[f.group("name")] = None
                continue
            for rx in PYTEST_RERUN_RES:
                if (f := rx.match(r)):
                    reruns[f.group("name")] = reruns.get(f.group("name"), 0) + 1
                    break
            else:
                for rx in PYTEST_FAIL_RES:
                    if (f := rx.match(r)):
                        failed[f.group("name")] = None
                        break
        for name in flaky:
            failed.pop(name, None)
        total_reruns = counts.get("rerun", 0)
        retries = max(reruns.values()) if reruns else None
        every = [n for n in failed if n not in not_rerun]
        if retries is None and total_reruns and every and not flaky:
            # Every rerun went to a test that failed every attempt: they took one count each.
            retries = total_reruns // len(every) if total_reruns % len(every) == 0 else None
        failures = [{"test": n, "flaky": False,
                     "attempts": 1 if n in not_rerun else reruns[n] + 1 if n in reruns
                     else retries + 1 if retries else 1} for n in failed]
        failures += [{"test": n, "flaky": True,
                      "attempts": reruns[n] + 1 if n in reruns else 2} for n in flaky]
        tests = sum(counts.get(k, 0) for k in ("passed", "failed", "errors", "skipped",
                                               "xfailed", "xpassed"))
        bad = counts.get("failed", 0) + counts.get("errors", 0) > 0 or bool(flaky and red)
        out.append(Summary("pytest", i, tests, bad, failures, retries))
    return out


def _pw_name(file: str, title: str) -> str:
    return f"{file} › {title.strip()}"


def _playwright(lines: list[str], red: bool) -> list[Summary]:
    out: list[Summary] = []
    tries: dict[str, int] = {}
    i = 0
    while i < len(lines):
        if (r := PW_RESULT_RE.match(lines[i])):
            name = _pw_name(r.group("file"), r.group("title"))
            tries[name] = max(tries.get(name, 0), int(r.group("retry") or 0) + 1)
            i += 1
            continue
        m = PW_COUNT_RE.match(lines[i])
        if not m:
            i += 1
            continue
        counts: dict[str, int] = {}
        listed: dict[str, list[str]] = {"failed": [], "flaky": [], "interrupted": []}
        heading = None
        indent = len(m.group("indent"))
        while i < len(lines):
            ln = lines[i]
            c = PW_COUNT_RE.match(ln)
            if c and len(c.group("indent")) == indent:
                heading = c.group("what")
                counts[heading] = counts.get(heading, 0) + int(c.group("n"))
            elif (t := PW_TEST_RE.match(ln)) and len(ln) - len(ln.lstrip()) > indent:
                if heading in listed:
                    listed[heading].append(_pw_name(t.group("file"), t.group("title")))
            else:
                break
            i += 1
        if "passed" not in counts and not listed["failed"] and not listed["flaky"]:
            continue                           # a lone count line, no summary
        # The retries shown: the most a test took, where a test failed or was retried at all.
        shown = max(tries.values()) - 1 if tries else None
        retries = shown if shown is not None and (shown > 0 or listed["failed"]) else None
        failures = [{"test": n, "flaky": False,
                     "attempts": tries.get(n) or ((retries or 0) + 1)}
                    for n in listed["failed"] + listed["interrupted"]]
        failures += [{"test": n, "flaky": True, "attempts": max(tries.get(n, 0), 2)}
                     for n in listed["flaky"]]
        bad = counts.get("failed", 0) + counts.get("interrupted", 0) > 0 or \
            bool(counts.get("flaky") and red)
        out.append(Summary("playwright", i - 1, sum(counts.values()), bad, failures, retries))
        tries = {}
    return out


def _vitest(lines: list[str]) -> list[Summary]:
    out: list[Summary] = []
    start = 0
    for i, ln in enumerate(lines):
        m = VITEST_TESTS_RE.match(ln)
        if not m:
            continue
        failed = sum(int(n) for n, w in re.findall(r"(\d+) (\w+)", m.group("body"))
                     if w == "failed")
        names: dict[str, None] = {}
        for r in lines[start:i]:
            if (f := VITEST_FAIL_RE.match(r)):
                title = f.group("title")
                names[f"{f.group('file')} > {title}" if title else f.group("file")] = None
        start = i + 1
        out.append(Summary("vitest", i, int(m.group("total")), failed > 0,
                           [{"test": n, "attempts": 1, "flaky": False} for n in names]))
    return out


def _go(lines: list[str]) -> list[Summary]:
    pkgs: list[tuple[str, str]] = []
    tests: list[tuple[str, str]] = []
    pending: list[str] = []
    failures: list[dict] = []
    verbose = False
    last = -1
    for i, ln in enumerate(lines):
        if GO_VERBOSE_RE.match(ln):
            verbose = True
        if (t := GO_TEST_RE.match(ln)):
            tests.append((t.group("status"), t.group("name")))
            if t.group("status") == "FAIL":
                pending.append(t.group("name"))
        elif (p := GO_PKG_RE.match(ln)):
            pkgs.append((p.group("status"), p.group("pkg")))
            last = i
            if p.group("status") == "FAIL":
                failures += [{"test": f"{p.group('pkg')}.{n}", "attempts": 1, "flaky": False}
                             for n in pending]
            pending = []
    if not pkgs:
        return []
    failures += [{"test": n, "attempts": 1, "flaky": False} for n in pending]
    # Plain `go test` prints no test count, only a line per package: that is the count then.
    count = len(tests) if verbose else len(pkgs)
    bad = any(s == "FAIL" for s, _ in pkgs) or any(s == "FAIL" for s, _ in tests)
    return [Summary("go", last, count, bad, failures)]


def _node(lines: list[str]) -> list[Summary]:
    out: list[Summary] = []
    tests = None
    for i, ln in enumerate(lines):
        if (m := NODE_COUNT_RE.match(ln)):
            if m.group("what") == "tests":
                tests = int(m.group("n"))
            elif tests is not None:
                out.append(Summary("node", i, tests, int(m.group("n")) > 0, []))
                tests = None
    return out


# ---------------------------------------------------------------------------
# Test Runs of a Tool Call.
# ---------------------------------------------------------------------------

KC_HEAD_RE = re.compile(r"^(?P<comp>[\w.-]+): (?P<cmd>.+?)\s{2,}\[\s*(?P<mark>[A-Z]+)\s*\]\s*$")
KC_FULL_RE = re.compile(r"^full output: \S*?/(?P<verb>test|lint|build|setup)-\d{8}T")


def _merge(suite: str, name: str, items: list[Summary], passed: bool, flag: int | None,
           ctx: ToolCtx) -> dict:
    failures: dict[str, dict] = {}
    for s in items:
        for f in s.failures:
            failures.setdefault(f["test"], f)
    seen = [s.retries for s in items if s.retries is not None]
    return {"suite": suite, "name": name, "passed": passed and not any(s.failed for s in items),
            "tests": sum(s.tests for s in items),
            "retries_allowed": flag if flag is not None else (max(seen) if seen else None),
            "started_at": ctx.requested_at, "ended_at": ctx.result_at,
            "failures": list(failures.values())}


def _retry_flag(cmd: str, runner: str) -> int | None:
    flag = RETRY_FLAGS.get(runner)
    m = re.search(rf"(?:^|\s){flag}(?:=|\s+)(\d+)\b", tp._strip_heredocs(cmd)) if flag else None
    return int(m.group(1)) if m else None


def _test_runs(cmd: str, stages: list[_Stage], text: str, ctx: ToolCtx) -> list[dict]:
    summaries = parse_test_summaries(text)
    if not summaries:
        return []
    kc = [(st, k) for st in stages if (k := _kc_project(st))]
    if kc:
        return _kc_runs(kc, summaries, text, ctx)
    ran = [st for st in stages if (r := _stage_rule(st)) and r[1] == TEST_SUITE]
    repo = (repo_of(ran[0].cwd) if ran else None) or repo_of(ctx.cwd) or "?"
    runs: list[dict] = []
    for runner in dict.fromkeys(s.runner for s in summaries):
        items = [s for s in summaries if s.runner == runner]
        runs.append(_merge(f"{repo}/{runner}", f"{repo} {runner}", items, True,
                           _retry_flag(cmd, runner), ctx))
    return runs


def _kc_runs(kc: list[tuple[_Stage, tuple[str, str | None]]], summaries: list[Summary],
             text: str, ctx: ToolCtx) -> list[dict]:
    """`kc project test`: one Test Run per component, from kc's own lines — a component's
    `<comp>: <command>    [  OK  ]` heads, the `full output: …/<verb>-<time>.log` that ends each
    verb's output — and the runner summaries inside them."""
    lines = text.splitlines()
    tests_only = all(k[0] == "test" for _, k in kc)
    projects = {k[1] for _, k in kc if k[0] == "test"}
    only = next(iter(projects)) if len(projects) == 1 else None
    repo = next((repo_of(st.cwd) for st, k in kc if k[0] == "test"), None) \
        or repo_of(ctx.cwd) or "?"
    groups: list[tuple[int, int, str | None]] = []   # (first line, last line, verb)
    begin = 0
    for i, ln in enumerate(lines):
        if (m := KC_FULL_RE.match(ln)):
            groups.append((begin, i, m.group("verb")))
            begin = i + 1
    groups.append((begin, len(lines) - 1, None))
    by_comp: dict[str, list[Summary]] = {}
    red: set[str] = set()
    for first, last, verb in groups:
        verb = verb or ("test" if tests_only else None)
        if verb != "test":
            continue
        comp = None
        for i in range(first, last + 1):
            if (h := KC_HEAD_RE.match(lines[i])):
                comp = h.group("comp")
                if h.group("mark") != "OK":
                    red.add(comp)
            for s in summaries:
                if s.line == i:
                    c = comp or only
                    if c:
                        by_comp.setdefault(c, []).append(s)
    return [_merge(f"{repo}/{c}/test", f"{repo} {c} test", items, c not in red, None, ctx)
            for c, items in by_comp.items()]


# ---------------------------------------------------------------------------
# The call's labels.
# ---------------------------------------------------------------------------

def tool_labels(name: str, input: Mapping | None, result, ctx: ToolCtx | Mapping | None = None
                ) -> dict:
    """The labels of one Tool Call: `name` and `input` its `tool_use` block's, `result` its
    `tool_result` content (text, or the content blocks), `ctx` the rest (`ToolCtx`). Gives

        {"command_class": code or None,
         "effect_kind": code or None, "effect_subject": text or None,
         "rules": [codes],
         "events": [{"kind": "gate_red", "at", "detail"}],
         "test_runs": [{"suite", "passed", "tests", "retries_allowed", "started_at",
                        "ended_at", "failures": [{"test", "attempts", "flaky"}]}],
         "test_suites": [{"code", "name"}],
         "ci_wait": None, or for a `ci_wait` call {"job", "named": [{"job", "commit"}],
                    "background": bool},
         "ci_builds": the CI Build rows of a foreground wait whose summary is in its own result,
         "ci_summaries": every `track_build.py` summary the result holds, whatever the call —
                         the read of a background wait's output among them,
         "background": None, or for a `run_in_background` Bash call {"task_id",
                       "output_file", "writes"},
         "reads": {"paths", "task_ids"}: the files and background tasks the call read}

    A Test Run's `name` beside its `suite` is the Test Suite's name. A background run, and a
    result with no summary, give no Test Run; nor does a summary that names no count."""
    inp = input or {}
    c = _ctx(ctx)
    text = result_text(result)
    cmd = str(inp.get("command") or "") if name == "Bash" else ""
    stages = _stages(cmd, c.cwd) if cmd else []
    cls, detail = _command_class(cmd, stages) if cmd else (None, None)
    effect, subject = _effect(name, inp, text, stages, c)
    background = _background(inp, cmd, text, c.cwd) if cmd else None
    out: dict = {
        "command_class": cls, "effect_kind": effect, "effect_subject": subject,
        "rules": _rules(cls, stages, c), "events": [], "test_runs": [], "test_suites": [],
        "ci_wait": None, "ci_builds": [], "ci_summaries": parse_track_summary(text),
        "background": background, "reads": _reads(name, inp, stages),
    }
    if cls in (GATE, TEST_SUITE) and _failed(text, c):
        out["events"].append(gate_red_event(detail, c))
    if cls == TEST_SUITE and background is None:
        runs = _test_runs(cmd, stages, text, c)
        out["test_suites"] = [{"code": r["suite"], "name": r.pop("name")} for r in runs]
        out["test_runs"] = runs
    if cls == CI_WAIT:
        named = [_track_build_args(st) for st in stages if TRACK_BUILD_RE.match(st.text)]
        out["ci_wait"] = {"job": next((n["job"] for n in named if n["job"]), None),
                          "named": named, "background": background is not None}
        if background is None:
            out["ci_builds"] = [b for s in out["ci_summaries"]
                                for b in ci_builds(out["ci_wait"], s, c.result_at)]
    return out


def gate_red_event(detail: str | None, ctx: ToolCtx) -> dict:
    """The `gate_red` Event of a gate or test suite whose result failed: at the result line's
    time, its detail the kc component and verb (`frontend test`), else the program."""
    return {"kind": GATE_RED, "at": ctx.result_at, "detail": detail}


# ---------------------------------------------------------------------------
# Context Parts: the orientation digest's sections.
# ---------------------------------------------------------------------------

DIGEST_HEAD_RE = re.compile(r"^# Orientation digest —", re.M)
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def digest_sections(prompt_text: str) -> list[dict]:
    """One `{"name", "characters"}` per `## ` section of the block that opens
    `# Orientation digest —` in a dispatch's opening prompt (`run_loop.build_phase_digest`,
    `build_slice_digest`): `name` the heading up to its first ` (`, `characters` the section's
    length with its heading. The block runs to the prompt's end; a `## ` line inside a fenced
    block is no heading. No digest, no sections."""
    m = DIGEST_HEAD_RE.search(prompt_text or "")
    if not m:
        return []
    block = prompt_text[m.start():]
    starts: list[tuple[int, str]] = []
    fenced = False
    pos = 0
    for line in block.splitlines(keepends=True):
        if FENCE_RE.match(line):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            starts.append((pos, line[3:].rstrip("\n").strip()))
        pos += len(line)
    out: list[dict] = []
    for k, (at, heading) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(block)
        body = block[at:end].rstrip("\n")
        out.append({"name": heading.split(" (", 1)[0].strip(), "characters": len(body)})
    return out
