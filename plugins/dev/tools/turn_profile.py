#!/usr/bin/env python3
"""Replay one session transcript into per-turn facts: what each turn cost and did.

The bill is charged per turn — one model invocation, and because every role
sits at 50–145 k of context and re-reads it at the cache rate, at nearly the
same price whatever the role. So what a run costs is mostly what its turns
*did*, and this module is what says so: it parses a Claude Code stream-json
transcript into ordered turns (usage, tool calls, the results they got), puts
every turn in exactly one class by what its calls did, counts the read ops
chained inside one Bash command, and marks the read turns a perfect batcher
would have folded into the one before them.

The classes, first match in this order when a turn mixes calls:

    dispatch · edit · gate · commit · record · retry · fumble · wait ·
    git-inspect · orient-read · work-read · think · other

`edit` and `record` are the same op split by what it wrote (plan.md, a
done-record, a verdict, a review round, an ask or a close-out entry is a
`record`; a turn that writes both is an `edit`); `orient-read` and `work-read`
are the same op split at the session's first edit — counting the edits made
through the shell (a heredoc'd python rewrite, `sed -i`, a `>` redirection
into anything but a scratch file), which is how a session spawned with
--dangerously-skip-permissions is told to work, and which no tool name reveals.

A Bash step is classed by the program it runs once its wrappers are peeled off
(`timeout`, `cexec <tool>`, `sh -c '…'`, …): a program that only reads is a
read whatever its quoted arguments say, the workflow's own scripts
(close_out.py, asks.py, run_loop.py, …) go by their verb, and only the rest
is tested for a gate, a wait or a git mutation in its text. A tool other than
Bash goes by its name, an MCP tool by the verb in its name.

`retry` and `fumble` are lower bounds: the order means a retried edit counts as
an `edit` and a re-run gate as a `gate`. Failure is read from a result's text
(`usage:`, or `command not found` on a line shaped like a diagnostic) as well
as its `is_error` flag, since the loop's commands end in `2>&1` and fail with
exit 0 — but a grep that matched nothing, a probe answered `No such file`, a
loop wait's exit code and an operator's refusal are no failures. A turn with no
tool call is `think`, except the session's last, its hand-back (`record`), and
one that waits on work it left running in the background (`wait`).

`analyse(replay(path), cost_for)` is the whole interface: it returns the turns,
their classes, their per-turn cost and one `metrics` dict — the per-session
figures [slice_cost.py](slice_cost.py) aggregates per role into a run's turn
table. Nothing here reads a slice directory or knows what a role is; the caller
supplies the transcript and the pricing function, so this module prices nothing
itself and duplicates no price, and says what the session's role makes of its
turns through two flags, both off by default: `reads_are_work` (no
orientation — every read is the work, as a reviewer's are) and `plan_is_edit`
(plan.md is the work, not a record, as a plan author's is).

Read by `slice_cost.py` (the `turns` table and the `turns` block it writes into
state.json) and by `docs/research/tools/context_profile.py`, which builds the
research-only analyses on top of the same replay. Stdlib-only, and not a
command: it has no `main()`.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

TTL_S = 300           # the loop forces the 5-minute cache TTL
BREAK_SLACK = 2_000   # tokens of cache_read shortfall tolerated before we call a break
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TURN_CLASSES = ("dispatch", "edit", "gate", "commit", "record", "retry",
                "fumble", "wait", "git-inspect", "orient-read", "work-read",
                "think", "other")


# ---------------------------------------------------------------------------
# Shell parsing. A headless session is told to work through Bash, so one call
# is many steps: split on `;` `&&` `||` `&` and newlines — never inside quotes,
# `$(…)` or backticks, and with comments dropped. Heredoc bodies are data, not
# shell, so they are cut out first (a python script that rewrites a file is one
# step, not five). Each step is then resolved to the command it runs: its
# `NAME=value` words recorded and substituted into later steps, its wrappers
# (`timeout`, `env`, `xargs`, `uv run`, `cexec <tool>`, …) unwrapped, an
# `sh -c '<script>'` walked as the script's own steps, and every `$(…)` it
# holds walked too — what a substitution ran, the turn did.
# ---------------------------------------------------------------------------

HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*[\"']?(\w+)[\"']?([^\n]*)\n(.*?)^\s*\1\s*$",
                        re.S | re.M)
HEREDOC_OPEN_RE = re.compile(r"(?<!<)<<(?!<)-?\s*[\"']?\w+[\"']?([^\n]*)\n")
HEREDOC_MARK = "<<@BODY"       # `@` is no word: HEREDOC_OPEN_RE never matches it again
ENV_PREFIX_RE = re.compile(r"^(?:\w+=\S*\s+)+")
WRAPPER_RE = re.compile(
    r"^(?:sudo|time|nohup|exec|command(?!\s+-[vV])|nice(?:\s+-n\s*-?\d+)?"
    r"|stdbuf(?:\s+-\S+)+"
    r"|timeout(?:\s+(?:-[ks]\s*\S+|--[\w-]+(?:=\S+)?))*\s+\d[\d.]*[smhd]?"
    r"|env(?:\s+(?:-u\s*\S+|-i|\w+=\S*))+"
    r"|xargs(?:\s+(?:-[0rt]+|-[InPLdE]\s*\S+|--[\w-]+(?:=\S+)?))*"
    r"|uv\s+run(?:\s+(?:--(?:with|project|directory|python|extra|group|package)\s+\S+"
    r"|--[\w-]+(?:=\S+)?))*"
    r"|poetry\s+run|cexec(?:\s+-\S+)*\s+\w[\w.-]*)\s+")
BLOCK_PREFIX_RE = re.compile(r"^(?:do|then|else|elif|fi|done|if|while|until|!)\s+"
                             r"|^[({})\\\s]+")
SH_C_RE = re.compile(r"^(?:\S*/)?(?:ba|z)?sh\s+(?:--?[\w-]+\s+)*?-[a-z]*c[a-z]*\s+")
ASSIGN_RE = re.compile(r"(?:(?:export|local|declare|readonly|typeset)(?:\s+-\w+)*\s+)?"
                       r"([A-Za-z_]\w*)\+?=")
FUNC_DEF_RE = re.compile(r"^(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{?(.*)$", re.S)
VAR_RE = re.compile(r"'[^']*'|\$\{(\w+)\}|\$(\w+)")
PROG_RE = re.compile(r"[\"']?(\$\{?\w+\}?|\[\[?|[\w./~+:@-]+)")
REDIR_PREFIX_RE = re.compile(r"^(?:\d*(?:>>?|<|&>)&?\s*\S+\s*)+")  # `done 2>/dev/null | head`
GIT_OPTS = r"(?:(?:-C|-c)\s+\S+\s+|--no-pager\s+|--(?:git-dir|work-tree)=\S+\s+)*"
GIT_SUB_RE = re.compile(r"git\s+" + GIT_OPTS + r"([a-z][a-z-]*)(.*)", re.S)
MAX_DEPTH = 4                  # nested `sh -c` / `$(…)` / function bodies walked


def _skip(s: str, i: int) -> int:
    """The index just past the quoted string, `$(…)` or backtick span that
    opens at s[i] — nested ones included, `$((…))` arithmetic too."""
    n = len(s)
    c = s[i]
    if c == "'":
        j = s.find("'", i + 1)
        return n if j < 0 else j + 1
    if c == "`":
        j = i + 1
        while j < n and s[j] != "`":
            j += 2 if s[j] == "\\" else 1
        return min(j + 1, n)
    if c == '"':
        j = i + 1
        while j < n and s[j] != '"':
            if s[j] == "\\":
                j += 2
            elif s[j] == "`" or s.startswith("$(", j):
                j = _skip(s, j)
            else:
                j += 1
        return min(j + 1, n)
    j, depth = i + 2, 1                # `$(`
    while j < n:
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch in "'\"`" or s.startswith("$(", j):
            j = _skip(s, j)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _split(s: str, pipes: bool = False) -> list[str]:
    """`s` cut at its top-level step separators (`;` `&&` `||` `&` newline) —
    or, with `pipes`, at its pipe symbols — outside quotes, `$(…)` and
    backticks, with `#` comments dropped."""
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            buf.append(s[i:i + 2])
            i += 2
            continue
        if c in "'\"`" or s.startswith("$(", i):
            j = _skip(s, i)
            buf.append(s[i:j])
            i = j
            continue
        if c == "#" and (i == 0 or s[i - 1] in " \t\n;&|()"):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        cut = 0
        if pipes:
            if c == "|" and not s.startswith("||", i):
                cut = 2 if s.startswith("|&", i) else 1
        elif s.startswith(("&&", "||"), i):
            cut = 2
        elif c in ";\n":
            cut = 1
        elif c == "&" and s[i - 1:i] not in ("<", ">", "|") and s[i + 1:i + 2] != ">":
            cut = 1
        if cut:
            parts.append("".join(buf))
            buf = []
            i += cut
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [x.strip() for x in parts if x.strip()]


def _word_end(s: str, i: int) -> int:
    """The index where the shell word starting at s[i] ends."""
    n = len(s)
    while i < n and not s[i].isspace():
        if s[i] == "\\":
            i += 2
        elif s[i] in "'\"`" or s.startswith("$(", i):
            i = _skip(s, i)
        else:
            i += 1
    return min(i, n)


def _unquote(w: str) -> str:
    """A shell word with its quoting removed."""
    out: list[str] = []
    q = ""
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        if q == "'":
            if c == "'":
                q = ""
            else:
                out.append(c)
            i += 1
        elif q == '"':
            if c == "\\" and i + 1 < n and w[i + 1] in '"\\$`':
                out.append(w[i + 1])
                i += 2
            elif c == '"':
                q = ""
                i += 1
            else:
                out.append(c)
                i += 1
        elif c in "'\"":
            q = c
            i += 1
        elif c == "\\" and i + 1 < n:
            out.append(w[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _blank(s: str) -> str:
    """`s` with every quoted string emptied and every `$(…)` or backtick span
    replaced by `$_`, so a text test sees the shell and not its arguments —
    except a quoted redirect target, which is kept, unquoted."""
    out: list[str] = []
    last = ""
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            out.append(s[i:i + 2])
            last = "\\"
            i += 2
            continue
        if c in "'\"`" or s.startswith("$(", i):
            j = _skip(s, i)
            if last == ">":
                out.append(_unquote(s[i:j]))
            else:
                out.append("''" if c in "'\"" else "$_")
            last = "_"
            i = j
            continue
        out.append(c)
        if not c.isspace():
            last = c
        i += 1
    return "".join(out)


def _substitutions(s: str) -> list[str]:
    """The commands inside the `$(…)` and backtick spans of `s` — not inside
    single quotes, not `$((…))` arithmetic, not an escaped backtick."""
    out: list[str] = []
    dq = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
        elif c == '"':
            dq = not dq
            i += 1
        elif c == "'" and not dq:
            i = _skip(s, i)
        elif s.startswith("$((", i):
            i = _skip(s, i)
        elif s.startswith("$(", i) or c == "`":
            j = _skip(s, i)
            out.append(s[i + (2 if c == "$" else 1):j - 1])
            i = j
        else:
            i += 1
    return out


def _split_heredocs(cmd: str) -> tuple[str, str]:
    """(shell, bodies): the command with each heredoc body cut out — its
    opening left as HEREDOC_MARK, the rest of the opening line kept — and the
    bodies themselves."""
    bodies: list[str] = []

    def cut(m: re.Match) -> str:
        bodies.append(m.group(3))
        return f" {HEREDOC_MARK} {m.group(2)}"

    out = HEREDOC_RE.sub(cut, cmd)
    m = HEREDOC_OPEN_RE.search(out)       # unterminated (truncated transcript)
    if m:
        bodies.append(out[m.end():])
        out = f"{out[:m.start()]} {HEREDOC_MARK} {m.group(1)}"
    return out, "\n".join(bodies)


def _strip_heredocs(cmd: str) -> str:
    """The shell part of a command: heredoc bodies cut out."""
    return _split_heredocs(cmd)[0]


def bash_segments(cmd: str) -> list[str]:
    """One Bash command -> its shell steps, split on `;` `&&` `||` `&` and
    newlines but not inside quotes (a close-out `--headline "…"` spans lines),
    `$(…)`, backticks or a heredoc. Pipes are not steps: `grep x | head` is one
    read, `cat a; cat b` is two."""
    return _split(_strip_heredocs(cmd))


def _expand(s: str, env: dict[str, str]) -> str:
    """`$NAME` and `${NAME}` replaced by what the command assigned them —
    outside single quotes, and only a value that is no command substitution."""
    if not env:
        return s

    def sub(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        v = env.get(name) if name else None
        if v is None or "$(" in v or "`" in v:
            return m.group(0)
        return v

    return VAR_RE.sub(sub, s)


def _unwrap(s: str) -> str:
    """A step's command with what only runs it stripped: block keywords,
    `NAME=value` prefixes and wrappers — `timeout`, `env`, `xargs`, `uv run`,
    `cexec <tool>` and the like."""
    for _ in range(8):
        prev = s
        s = WRAPPER_RE.sub("", ENV_PREFIX_RE.sub("", BLOCK_PREFIX_RE.sub("", s.strip())))
        if s == prev:
            break
    return s


def _seg_prog(seg: str) -> str:
    """The program a shell step runs, normalised (`sed -n` and `git <sub>` are
    their own programs — one reads, the other may not)."""
    s = REDIR_PREFIX_RE.sub("", _unwrap(seg))
    m = PROG_RE.match(s)
    if not m:
        return ""
    prog = m.group(1).rsplit("/", 1)[-1]
    if prog == "sed":
        return "sed -n" if re.search(r"\bsed\s+-n\b", s) else "sed"
    if prog == "git":
        m2 = GIT_SUB_RE.match(s)
        return f"git {m2.group(1)}" if m2 else "git"
    return prog


# ---------------------------------------------------------------------------
# Tool-call classification — one call at a time, Bash by what it runs.
# ---------------------------------------------------------------------------

BASH_CLASSES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bgit\s+" + GIT_OPTS + r"(diff|show|log|status|blame|grep|ls-tree|rev-list"
                r"|cat-file|reflog|merge-base|describe|fetch)(?![\w-])"), "git-inspect"),
    (re.compile(r"\bgit\s+" + GIT_OPTS + r"(add|commit|rebase|merge|checkout|switch|push|pull"
                r"|stash|cherry-pick|reset|revert|restore|mv|rm|clone)(?![\w-])"), "git-mutate"),
    (re.compile(r"\bkc (session|env|project)\b"), "kc-other"),
    (re.compile(r"^(cat|sed -n|head|tail|less)\b|\bcat\b|\bsed -n\b"), "cat/sed(read)"),
    (re.compile(r"\b(grep|rg|ag)\b"), "grep"),
    (re.compile(r"\b(ls|find|tree|wc|stat)\b"), "ls/find"),
    (re.compile(r"close_out\.py"), "close_out.py"),
    (re.compile(r"python3? "), "python-other"),
    (re.compile(r"\bcexec\b"), "cexec-other"),
]
READ_SUFFIXES = ("py", "go", "md", "ts", "yaml", "json")
BASH_READ_RE = re.compile(r"\bcat\b|\bsed -n\b")
BASH_PATH_RE = re.compile(r"[\w./@~+-]+\.(?:" + "|".join(READ_SUFFIXES) + r")\b")


def tool_class(name: str, cmd: str) -> str:
    """One tool call's class: Bash by what it runs — a gate by the turn
    classifier's own reading, the rest by the first BASH_CLASSES pattern its
    text matches — every other tool by its name."""
    if name != "Bash":
        return name
    if "gate" in bash_ops(cmd):
        return "gate"
    for rx, cls in BASH_CLASSES:
        if rx.search(cmd):
            return cls
    return "other"


def bash_read_paths(cmd: str) -> list[str]:
    """The source-ish paths a `cat` / `sed -n` command read."""
    if not cmd or not BASH_READ_RE.search(cmd):
        return []
    return [m.group(0) for m in BASH_PATH_RE.finditer(cmd)]


# ---------------------------------------------------------------------------
# Per-step ops. A step is classed by its program first: one that only reads
# or does nothing (READ_PROGS, GIT_READ, NOOP_PROGS) is that, whatever its
# arguments say — `grep -n "go test" Jenkinsfile` is a read, not a gate —
# unless it also writes a file through `>` or `tee` (a scratch file — /tmp,
# /dev, a mktemp — does not count). Any other program is tested in turn as
# one of the workflow's own scripts or a `kc` verb, then a gate, a wait, an
# edit, a git mutation, an external read probe and an inline script that
# only reads; its text tests run with quoted strings blanked, so a
# `--did "… kc project lint …"` argument gates nothing.
# ---------------------------------------------------------------------------

READ_PROGS = {"cat", "head", "tail", "less", "more", "nl", "sed -n", "grep", "rg",
              "ag", "find", "ls", "tree", "wc", "stat", "du", "jq", "diff", "column",
              "awk", "sort", "uniq", "cut", "md5sum", "sha256sum", "cmp", "file",
              "readlink", "od", "yq", "ps", "pgrep", "env", "id", "openssl"}
GIT_READ = {f"git {x}" for x in (
    "diff", "show", "log", "status", "blame", "branch", "ls-files", "rev-parse", "remote",
    "tag", "grep", "ls-tree", "rev-list", "cat-file", "reflog", "check-ignore",
    "ls-remote", "describe", "merge-base", "fetch")}
NOOP_PROGS = {"echo", "cd", "true", "false", "export", "set", "mkdir", "printf",
              "source", "unset", "pwd", "which", "type", "command", "date", "tr",
              "xargs", "seq", "test", "[", "[[", "for", "while", "do", "done", "if",
              "then", "else", "elif", "fi", "case", "esac", "read", "sleep",
              "continue", "break", "return", "exit", "local", "shift", "trap", ":",
              ".", "eval", "mktemp", "basename", "dirname"}
QUIET_EXIT_PROGS = {"grep", "egrep", "fgrep", "rg", "ag", "git grep", "diff", "cmp",
                    "test", "[", "[[", "ls", "git diff"}
GATE_SEG_RE = re.compile(r"kc project (test|lint|build)|\bpytest\b|\bgo test\b|\bruff\b"
                         r"|golangci|npm (test|run (test|lint|build))|uv run --with pytest"
                         r"|\bmypy\b|\btsc\b|ansible-lint|molecule")
GATE_PROG_RE = re.compile(          # matched at the program, after unwrapping
    r"(?:(?:pnpm|npm|npx|yarn)\s+(?:(?:-C|--dir|--filter|--prefix|-F)\s+\S+\s+"
    r"|(?:exec|run|dlx)\s+|-\S+\s+)*"
    r"(?:test|lint|build|typecheck|tsc|playwright\s+test|eslint|vitest|knip)(?![\w-])"
    r"|(?:\S*/)?(?:playwright\s+test|eslint|vitest|knip|shellcheck)(?![\w-])"
    r"|go\s+vet\b|gofmt\s+-l\b|(?:ba)?sh\s+-n\b|node\s+--test\b|helm\s+lint\b"
    r"|terraform\s+validate\b|(?:\S*/)?ansible-playbook\b.*\s--syntax-check\b"
    r"|(?:\S*/)?python3?(?:\.\d+)?\s+(?:-[A-Za-z]+\s+)*(?:-m\s+(?:unittest|pytest)\b"
    r"|[\"']?\S*\b(?:test_\w+|spec_check)\.py\b)"
    r"|[\"']?\S*\b(?:test_\w+|spec_check)\.py[\"']?(?=\s|$))")
GIT_MUTATE_RE = re.compile(
    r"\bgit\s+" + GIT_OPTS
    + r"(add|commit|rebase|merge|checkout|switch|push|stash(?!\s+(?:list|show)\b)"
    r"|cherry-pick|reset|revert|restore|am|pull|mv|rm|clone"
    r"|worktree\s+(?:add|remove|prune|move)|branch\s+(?:-[dDf]|--delete|--force))(?![\w-])")
BRANCH_WRITE_RE = re.compile(r"\s(?:-[dDf]|--delete|--force)(?![\w-])")
WAIT_RE = re.compile(r"\bsleep\s+\d|kubectl\s+wait\b|\btrack_build(\.py)?\b|\bkill\s+-0\b"
                     r"|kubectl\s+[^|;]*\bget\b[^|;]*\s-w\b|\bwatch\s+-n"
                     r"|(?:run_loop|plan_loop|long_run)\.py[\"']?\s+wait\b")
HELP_RE = re.compile(r"--help\b|(?:\.py|\bkc|\bcexec|\bkaniko|\btrack_build)\S*\s+"
                     r"(?:[a-z-]+\s+)*-h(?:\s|$)")
KC_RE = re.compile(r"kc\s+(?:-\S+\s+)*([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")
KC_READ_RE = re.compile(r"\bkc\s+(?:project|env|session|config|timer)\s+"
                        r"(info|list|describe|status|show|get|logs)\b")
WORKFLOW_RE = re.compile(
    r"(?:(?:\S*/)?python3?(?:\.\d+)?\s+(?:-[A-Za-z]+\s+)*)?[\"']?(?:[^\s\"']*/)?"
    r"(?:(close_out|asks|run_loop|plan_loop|long_run|preflight|slice_cards|checks|slice_cost"
    r"|close_slice)\.py|(allocate-next-slice)\.sh)[\"']?(?=\s|$)")
WORKFLOW_READ_VERBS = {
    "close_out": {"list", "show", "worklist", "labels", "counts", "render"},
    "asks": {"list", "show"},
}
VERB_RE = re.compile(r"[a-z][a-z-]*")
KUBECTL_READS = {"get", "describe", "logs", "top", "auth", "explain", "api-resources",
                 "version"}
KUBECTL_VALUED = {"-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user",
                  "-l", "--selector", "-o", "--output"}
CURL_METHOD_RE = re.compile(r"(?:-X\s*|--request[\s=]+)[\"']?(?:POST|PUT|PATCH|DELETE)\b")
CURL_SEND_RE = re.compile(r"\s(?:-d|--data[\w-]*|-F|--form|-T|--upload-file|--json)(?=[\s=]|$)")
GH_READ_RE = re.compile(r"gh\s+(?:api\b|(?:repo|pr|run|issue)\s+(?:view|list)\b)")
GH_WRITE_RE = re.compile(r"(?:-X\s*|--method[\s=]+)[\"']?(?:POST|PUT|PATCH|DELETE)\b"
                         r"|\s(?:-f|-F|--field|--raw-field|--input)(?=[\s=]|$)")
PROBE_READS = {
    "helm": {"template", "show", "get", "list", "ls", "status"},
    "terraform": {"show", "output"},
    "docker": {"inspect", "ls", "manifest"},
    "crane": {"inspect", "ls", "manifest"},
    "skopeo": {"inspect", "ls", "manifest"},
}
VAULT_READ_RE = re.compile(r"(?:bao|vault)\s+(?:-\S+\s+)*kv\s+(?:-\S+\s+)*"
                           r"(?:get|list|metadata\s+(?:-\S+\s+)*get)\b")
INLINE_RE = re.compile(r"(?:\S*/)?(?:python3?(?:\.\d+)?|node)(?:\s+-[A-Za-z]+)*"
                       r"(?:\s+-[ce]\b|\s+-(?=\s|$)|\s*$)")
INLINE_READ_RE = re.compile(r"\bopen\(|json\.load|safe_load|read_text|sys\.stdin|\bPath\("
                            r"|readFileSync|\bglob\b|urlopen")
FAIL_RE = re.compile(r"^usage:|^error:|^\s*usage:\s|\berror: (unrecognized|invalid|"
                     r"argument|the following)|command not found|No such file or directory"
                     r"|not recognized|invalid choice|unrecognized (option|arguments)"
                     r"|Traceback \(most recent call last\)|Permission denied", re.M)
FAIL_MARK_RE = re.compile(r"\berror: (?:unrecognized|invalid|argument|the following)"
                          r"|command not found|No such file or directory|not recognized"
                          r"|invalid choice|unrecognized (?:option|arguments)|Permission denied")
DIAG_LINE_RE = re.compile(r"^(?:[\w./+-]+: |\s*[\w.]*Error\b|ERROR\b)")
GREP_LINE_RE = re.compile(r"^[\w./+-]+[:-]\d+[:-]")
EXIT_RE = re.compile(r"^Exit code (\d+)")
WAIT_EXIT_RE = re.compile(r"(?:run_loop|plan_loop|long_run)\.py[\"']?\s+"
                          r"(?:wait\b|gate\b[^;&|\n]*\s--wait\b)|\btrack_build")
REJECTED_RE = re.compile(r"^The user doesn't want to proceed")
DISPATCH_TOOLS = {"Agent", "Task"}
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch"}
TOOL_OPS = {"ToolSearch": "read", "Skill": "read", "ListAgents": "read",
            "SendMessage": "dispatch",
            "Monitor": "wait", "ScheduleWakeup": "wait", "TaskOutput": "wait",
            "BashOutput": "wait",
            "TodoWrite": "noop", "TodoRead": "noop", "TaskCreate": "noop",
            "TaskUpdate": "noop", "TaskList": "noop", "TaskGet": "noop",
            "TaskStop": "noop", "KillShell": "noop"}
MCP_DISPATCH = {"start_headless_session", "start_session", "run_prompt",
                "send_session_message"}
MCP_RECORD_WORDS = {"create", "add", "update", "post", "react", "set", "move", "archive",
                    "register", "mark", "answer", "attach", "delete", "comment", "close",
                    "send", "notify", "notification", "upload"}
MCP_READ_WORDS = {"get", "list", "search", "find", "read", "query", "fetch", "describe",
                  "show", "status", "view", "whoami"}
ASYNC_RE = re.compile(r"Async agent launched|running in the background")
LAUNCH_RE = re.compile(r"--detach\b|long_run\.py[\"']?\s+start\b")

# an edit done through the shell — invisible to WRITE_TOOLS
SED_I_RE = re.compile(r"\bsed\s+-i\b")
GIT_APPLY_RE = re.compile(r"\bgit\s+apply\b")
PATCH_RE = re.compile(r"\bpatch\s+-p\d")
TEE_RE = re.compile(r"\btee\s+(?:-a\s+)?([^\s|;&<>]+)")
SHELL_EDIT_RES_BASE = [SED_I_RE, re.compile(r"\btee\b(?!\s+/dev/null)"), GIT_APPLY_RE, PATCH_RE]
BODY_EDIT_RES = [                      # a heredoc'd python script that writes
    re.compile(r"\.write_text\s*\(|\.write_bytes\s*\("),
    re.compile(r"\bopen\s*\([^)]*['\"][wa]\+?['\"]"),
    re.compile(r"\.writelines\s*\(|json\.dump\s*\(|yaml\.(safe_)?dump\s*\("),
    re.compile(r"shutil\.(copy|move|copyfile)"),
]
REDIRECT_RE = re.compile(
    r"(?<![0-9<>&-])>>?\s*(?!/dev/null|&)((?=[\w./~${}-]*[./])[\w./~${}-]+)")
SCRATCH_RE = re.compile(r"^(?:/tmp/|/dev/|/var/tmp/|\$\{?(?:TMPDIR|tmp)\b|\$\(mktemp)")
PY_PATH_RE = re.compile(r"(?:Path|open)\s*\(\s*[\"']([^\"']+)[\"']")
RECORD_NAME_RE = re.compile(r"(^|/)plan\.md$|result(_r\d+)?\.json$|(^|/)close-out\.(md|json)$"
                            r"|(^|/)(code|plan)_review_r\d+\.(md|json)$|(^|/)verification\.json$"
                            r"|(^|/)asks/[^/]+\.(json|md)$")
PLAN_MD_RE = re.compile(r"(^|/)plan\.md$")
DONE_RECORD_RE = re.compile(r"\*\*Done \(P")
RESULT_PATH_CAP = 400      # paths kept per tool result, for the batching test
FAIL_HEAD = 600            # chars of a result inspected for a failure marker
RESULT_SCAN_CHARS = 40_000  # chars of a result scanned for the paths it revealed


SHELL_EDIT_RES = SHELL_EDIT_RES_BASE + [REDIRECT_RE]


class _Shell:
    """What one Bash command has set up so far, as its steps are walked: the
    variables and functions it defined, its heredoc bodies, the files its
    edits wrote and every simple command it ran."""

    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.funcs: dict[str, str] = {}
        self.bodies = ""
        self.targets: list[str] = []
        self.commands: list[str] = []


def _is_scratch(path: str, env: dict[str, str], depth: int = 0) -> bool:
    """A write that leaves no trace in a repo: /tmp, /dev, a mktemp file —
    or under a variable the command set to one."""
    path = path.strip("'\"")
    if SCRATCH_RE.match(path):
        return True
    m = re.match(r"\$\{?(\w+)", path)
    val = env.get(m.group(1), "") if m else ""
    return "mktemp" in val or (bool(val) and depth < 4 and _is_scratch(val, env, depth + 1))


def _args(bl: str) -> list[str]:
    """A blanked step's arguments: its words after the program, less options,
    redirections and their targets, and heredoc marks."""
    out: list[str] = []
    words = bl.split()[1:]
    skip = False
    for w in words:
        if skip:
            skip = False
        elif re.fullmatch(r"\d*(?:>>?|<|&>)", w):
            skip = True
        elif not (w.startswith(("-", "<", ">")) or re.match(r"\d*[<>&]", w) or w == "''"):
            out.append(w)
    return out


def _shell_write(sh: _Shell, bl: str) -> tuple[str | None, list[str]]:
    """(kind, targets) of what a blanked step wrote: `edit` if it changed a
    file that is no scratch file, `scratch` if it only wrote those, None."""
    if any(rx.search(bl) for rx in (SED_I_RE, GIT_APPLY_RE, PATCH_RE)):
        m = re.search(r"\bsed\s+-i\b[^;&|]*?([\w./~-]+\.\w+)\s*$", bl)
        return "edit", [m.group(1)] if m else []
    tgts = [m.group(1) for m in REDIRECT_RE.finditer(bl)]
    tgts += [m.group(1) for m in TEE_RE.finditer(bl) if m.group(1) != "/dev/null"]
    if not tgts:
        return None, []
    real = [t for t in tgts if not _is_scratch(t, sh.env)]
    return ("edit" if real else "scratch"), [t for t in real if t != "''"]


def _verb(rest: str) -> str:
    """The first word of a script's arguments that names a verb."""
    for w in _blank(rest).split():
        if VERB_RE.fullmatch(w):
            return w
    return ""


def _workflow_op(sh: _Shell, s: str, depth: int) -> list[str] | None:
    """The op of a step that runs one of the workflow's own scripts."""
    m = WORKFLOW_RE.match(s)
    if not m:
        return None
    script = m.group(1) or m.group(2)
    rest = s[m.end():]
    verb = _verb(rest)
    if script in WORKFLOW_READ_VERBS:
        return ["read" if not verb or verb in WORKFLOW_READ_VERBS[script] else "record"]
    if script in ("run_loop", "plan_loop"):
        if verb in ("gate", "wait"):
            return [verb]
        if verb == "status":
            return ["read"]
        if verb == "run":
            return ["read" if "--dry-run" in rest else
                    "dispatch" if "--detach" in rest else "wait"]
        return ["other"]
    if script == "long_run":
        if verb == "wait":
            return ["wait"]
        cmd = re.split(r"\s--\s", rest, maxsplit=1)
        if verb == "start" and len(cmd) == 2 and depth < MAX_DEPTH:
            return [op for op in _walk(sh, cmd[1], depth + 1) if op != "noop"] or ["other"]
        return ["other"]
    if script == "slice_cost":
        return ["record" if "--write-state" in rest else "read"]
    if script == "close_slice":
        return ["git-mutate"]
    if script == "allocate-next-slice":
        return ["record"]
    return ["read"]                    # preflight, slice_cards, checks


def _kc_op(s: str) -> str | None:
    m = KC_RE.match(s)
    if not m:
        return None
    noun, verb = m.group(1), m.group(2)
    if noun == "project" and verb in ("test", "lint", "build"):
        return "gate"
    if noun == "session" and verb in ("create-headless", "send"):
        return "dispatch"
    if noun == "catalog" or KC_READ_RE.match(s):
        return "read"
    return None


def _first_word(bl: str, valued: set[str] = frozenset()) -> str:
    """The first non-option word after a program."""
    words = bl.split()[1:]
    i = 0
    while i < len(words):
        w = words[i]
        if w.startswith("-"):
            i += 2 if w in valued else 1
            continue
        return w
    return ""


def _probe_op(prog: str, s: str, bl: str) -> str | None:
    """An external read probe — kubectl get, curl GET, gh view, helm template … —
    is a read; `gh run watch` is a wait."""
    if prog == "kubectl":
        verb = _first_word(bl, KUBECTL_VALUED)
        if verb in KUBECTL_READS or (verb == "config" and re.search(r"\bconfig\s+view\b", bl)):
            return "read"
        return None
    if prog in ("curl", "wget"):
        return None if CURL_METHOD_RE.search(s) or CURL_SEND_RE.search(bl) else "read"
    if prog == "gh":
        if re.match(r"gh\s+run\s+watch\b", bl):
            return "wait"
        return "read" if GH_READ_RE.match(bl) and not GH_WRITE_RE.search(s) else None
    if prog in ("bao", "vault"):
        return "read" if VAULT_READ_RE.match(bl) else None
    if prog in PROBE_READS:
        words = [w for w in bl.split()[1:] if not w.startswith("-")][:2]
        return "read" if PROBE_READS[prog] & set(words) else None
    return None


def _inline_op(sh: _Shell, head: str, s: str) -> str | None:
    """A `python3 -c`, `python3 -`, python heredoc or `node -e` script that
    reads a file and writes none is a read."""
    if not INLINE_RE.match(head) and not (HEREDOC_MARK in s
                                          and re.match(r"(?:\S*/)?python3?\b", head)):
        return None
    body = s + ("\n" + sh.bodies if HEREDOC_MARK in s else "")
    if any(rx.search(body) for rx in BODY_EDIT_RES) or "writeFileSync" in body:
        return None
    return "read" if INLINE_READ_RE.search(body) else None


def _git_read(prog: str, rest: str) -> str | None:
    """`git-read` for a git command that only looks."""
    if prog in GIT_READ:
        return None if prog == "git branch" and BRANCH_WRITE_RE.search(rest) else "git-read"
    if prog == "git stash" and re.match(r"\s*(?:list|show)\b", rest):
        return "git-read"
    if prog == "git worktree" and re.match(r"\s*list\b", rest):
        return "git-read"
    if prog == "git config":
        args = [w for w in rest.split() if not w.startswith("-")]
        if re.search(r"\s(?:--get[\w-]*|--list|-l)\b", rest) or len(args) <= 1:
            return "git-read"
    return None


def _git_write(prog: str, rest: str, bl: str) -> str | None:
    """A git command that changes the tree: a path checkout or restore is an
    edit, a commit, merge, push, … a git mutation."""
    if prog == "git checkout" and re.search(r"\s--(?:\s|$)", rest):
        return "edit"
    if prog == "git restore":
        staged = re.search(r"\s(?:--staged|-S)\b", rest)
        return "git-mutate" if staged and not re.search(r"\s(?:--worktree|-W)\b", rest) \
            else "edit"
    return "git-mutate" if GIT_MUTATE_RE.match(bl) else None


def _pipe_head(s: str) -> str:
    """The command a pipeline's data goes to, when its first stage only
    produces text — `cat <<EOF | python3 -`, `echo … | jq .` — else `s`."""
    stages = _split(s, pipes=True)
    if len(stages) < 2 or _seg_prog(stages[1]) == "tee":
        return s
    first = _seg_prog(stages[0])
    if first in ("echo", "printf") or (first == "cat" and not _args(_blank(stages[0]))):
        return _unwrap(" | ".join(stages[1:]))
    return s


def _prog_op(sh: _Shell, s: str, depth: int) -> list[str]:
    """The op of one resolved step (expanded, unwrapped), and the files it
    wrote if that op is an edit."""
    bl = _blank(s)
    wrote, targets = _shell_write(sh, bl)
    ops = _step_class(sh, s, bl, wrote, depth)
    if "edit" in ops:
        sh.targets += targets
    return ops


def _step_class(sh: _Shell, s: str, bl: str, wrote: str | None, depth: int) -> list[str]:
    """A resolved step's op: by its program first, then by the text tests."""
    if HELP_RE.search(bl):
        return ["read"]
    head = _pipe_head(s)
    hbl = _blank(head) if head is not s else bl
    prog = _seg_prog(head)
    gm = GIT_SUB_RE.match(hbl) if prog.startswith("git ") else None
    rest = gm.group(2) if gm else ""
    if prog == "sleep":
        return ["wait" if re.match(r"sleep\s+\d", head) else "noop"]
    plain = (_git_read(prog, rest) if prog.startswith("git ") else
             "read" if prog in READ_PROGS else
             "noop" if prog in NOOP_PROGS or not prog else None)
    if plain:
        if wrote == "edit":
            return ["edit"]
        if prog == "cat" and (wrote == "scratch" or (HEREDOC_MARK in head
                                                     and not _args(hbl))):
            return ["noop"]                # writes a scratch file, or prints a heredoc
        return [plain]
    ops = _workflow_op(sh, head, depth)
    if ops is None:
        op = _kc_op(head)
        ops = [op] if op else None
    if ops is not None:
        return ["edit"] if ops == ["read"] and wrote == "edit" else ops
    if GATE_PROG_RE.match(head) or GATE_SEG_RE.search(hbl):
        return ["gate"]
    if WAIT_RE.search(hbl):
        return ["wait"]
    if wrote == "edit":
        return ["edit"]
    if prog.startswith("git "):
        op = _git_write(prog, rest, hbl)
        if op:
            return [op]
    if GIT_MUTATE_RE.search(hbl):
        return ["git-mutate"]
    return [_probe_op(prog, head, hbl) or _inline_op(sh, head, s) or "other"]


def _subst_ops(sh: _Shell, s: str, depth: int) -> list[str]:
    """What the `$(…)` and backtick spans of `s` ran."""
    if depth >= MAX_DEPTH:
        return []
    ops: list[str] = []
    for inner in _substitutions(s):
        ops += [op for op in _walk(sh, inner, depth + 1) if op != "noop"]
    return ops


def _step_ops(sh: _Shell, step: str, depth: int) -> list[str]:
    """One shell step -> its ops: what its substitutions ran, then its own."""
    s = step
    for _ in range(4):
        s, prev = BLOCK_PREFIX_RE.sub("", s.strip()), s
        if s == prev:
            break
    m = FUNC_DEF_RE.match(s)
    if m:
        sh.funcs[m.group(1)] = m.group(2).strip().removesuffix("}").strip()
        return ["noop"]
    ops: list[str] = []
    i = 0
    while m := ASSIGN_RE.match(s, i):
        j = _word_end(s, m.end())
        raw = s[m.end():j]
        ops += _subst_ops(sh, raw, depth)
        val = _unquote(raw)
        sh.env[m.group(1)] = val if ("$(" in val or "`" in val) else _expand(val, sh.env)
        i = j
        while i < len(s) and s[i].isspace():
            i += 1
    s = s[i:]
    if not s:
        return ops or ["noop"]     # a NAME=value step
    s = _unwrap(_expand(s, sh.env))
    m = SH_C_RE.match(s)
    if m and depth < MAX_DEPTH:
        j = _word_end(s, m.end())
        inner = _walk(sh, _unquote(s[m.end():j]), depth + 1)
        wrote, targets = _shell_write(sh, _blank(s[j:]))
        if wrote == "edit" and "gate" not in inner:
            sh.targets += targets
            inner.append("edit")
        return ops + inner
    m = re.match(r"([\w-]+)(?=\s|$)", s)
    if m and m.group(1) in sh.funcs:
        body = sh.funcs[m.group(1)]
        return ops + (_walk(sh, body, depth + 1) if body and depth < MAX_DEPTH else ["noop"])
    ops += _subst_ops(sh, s, depth)
    sh.commands.append(s)
    return ops + _prog_op(sh, s, depth)


def _walk(sh: _Shell, text: str, depth: int = 0) -> list[str]:
    """Every op a piece of shell performed, step by step."""
    shell, bodies = _split_heredocs(text)
    if bodies:
        sh.bodies += "\n" + bodies
    ops: list[str] = []
    for step in _split(shell):
        ops += _step_ops(sh, step, depth)
    return ops


class _BashFacts(NamedTuple):
    ops: tuple[str, ...]
    targets: tuple[str, ...]        # the non-scratch files its edits wrote, where known
    commands: tuple[str, ...]       # every simple command it ran, resolved


@lru_cache(maxsize=16_384)
def _bash(cmd: str) -> _BashFacts:
    """One Bash command, walked once. The heredoc bodies are inspected once
    more, for the python-writes-a-file case the shell part cannot see — an
    edit unless every path it names is a scratch file."""
    sh = _Shell()
    ops = _walk(sh, cmd)
    if any(rx.search(cmd) for rx in BODY_EDIT_RES):
        paths = PY_PATH_RE.findall(cmd)
        real = [p for p in paths if not _is_scratch(p, sh.env)]
        if real or not paths:
            sh.targets += real
            if "edit" not in ops:
                ops.append("edit")
    return _BashFacts(tuple(ops), tuple(sh.targets), tuple(sh.commands))


def bash_ops(cmd: str) -> list[str]:
    """Every op one Bash call performed."""
    return list(_bash(cmd).ops)


def _seg_op(seg: str) -> str:
    """One shell step's own op, the step read on its own."""
    return _step_ops(_Shell(), seg, 0)[-1]


def _bash_edit_targets(cmd: str) -> list[str]:
    """What a shell edit wrote, as far as the command reveals it — scratch
    files left out."""
    return list(_bash(cmd).targets)


def _is_record_path(path: str, plan_is_edit: bool = False, done: bool = False) -> bool:
    """A file the workflow keeps as its record: plan.md, a done-record or
    verdict, a review round, the asks and close-out stores. With
    `plan_is_edit` plan.md is the session's work instead, unless what was
    written is a done-record."""
    path = path.strip().rstrip("'\"")
    if plan_is_edit and not done and PLAN_MD_RE.search(path):
        return False
    return bool(RECORD_NAME_RE.search(path))


def tool_op(name: str) -> str:
    """The op of a tool that is neither Bash nor a read, write or dispatch
    tool. An MCP tool `mcp__<server>__<name>` by the words of its name."""
    if name in TOOL_OPS:
        return TOOL_OPS[name]
    if name.startswith("mcp__"):
        tool = name.rsplit("__", 1)[-1]
        if tool in MCP_DISPATCH:
            return "dispatch"
        words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", tool)]
        if words and words[0] in MCP_RECORD_WORDS:
            return "record"
        if MCP_READ_WORDS & {*words, "".join(words)}:
            return "read"
    return "other"


def bash_read_count(cmd: str) -> int:
    return sum(1 for op in bash_ops(cmd) if op in ("read", "git-read"))


def turn_ops(t: dict, *, plan_is_edit: bool = False) -> tuple[list[str], list[str], int]:
    """(ops, write targets, read count) for one turn, over all its tool calls.
    A call whose every write target is a record path wrote a `record`, not an
    `edit`."""
    ops: list[str] = []
    targets: list[str] = []
    reads = 0
    for rec in t["tools"]:
        name = rec["name"]
        if name in DISPATCH_TOOLS:
            ops.append("dispatch")
        elif name in WRITE_TOOLS:
            rec_write = _is_record_path(rec["key"], plan_is_edit, bool(rec.get("done")))
            ops.append("record" if rec_write else "edit")
            targets.append(rec["key"])
        elif name in READ_TOOLS:
            ops.append("read")
            reads += 1
        elif name == "Bash":
            cmd = rec.get("cmd") or ""
            f = _bash(cmd)
            bops = list(f.ops)
            done = bool(DONE_RECORD_RE.search(cmd))
            if "edit" in bops and f.targets and all(
                    _is_record_path(p, plan_is_edit, done) for p in f.targets):
                bops = ["record" if op == "edit" else op for op in bops]
            ops += bops
            reads += sum(1 for op in bops if op in ("read", "git-read"))
            targets += f.targets
        else:
            op = tool_op(name)
            ops.append(op)
            reads += op == "read"
    return ops, targets, reads


def _read_targets(t: dict) -> tuple[list[str], bool]:
    """The concrete files a read turn opened, and whether every read it did
    resolved to one (a `grep -rn pat .`, an `ls` or a tool search does not)."""
    paths: list[str] = []
    resolved = True
    for rec in t["tools"]:
        if rec["name"] == "Read":
            paths.append(str(Path(rec["key"])))
        elif rec["name"] == "Bash":
            cmd = rec.get("cmd") or ""
            got = bash_read_paths(cmd)
            paths += [str(Path(p)) for p in got]
            n_reads = bash_read_count(cmd)
            if len(got) < n_reads:
                resolved = False
        elif rec["name"] in READ_TOOLS or tool_op(rec["name"]) == "read":
            resolved = False
    return paths, (resolved and bool(paths))


def _touched_files(t: dict) -> list[str]:
    """The files a read turn read or searched: its read targets, the source-ish
    paths its Bash commands name (a `grep -n pat file` too, which
    `bash_read_paths` leaves out), and the path after a Grep or Glob key's last
    ` in ` when it names a file (`.` and a directory without an extension do
    not)."""
    paths, _ = _read_targets(t)
    for rec in t["tools"]:
        if rec["name"] == "Bash":
            paths += [str(Path(m.group(0)))
                      for m in BASH_PATH_RE.finditer(rec.get("cmd") or "")]
        elif rec["name"] in ("Grep", "Glob"):
            p = rec["key"].rpartition(" in ")[2]
            if Path(p).suffix:
                paths.append(str(Path(p)))
    return paths


def _same_file(a: str, b: str) -> bool:
    """Whether two normalised paths name one file: equal, or the same basename
    with one side relative — transcripts mix `/work/X/tests/a.py` and
    `tests/a.py` as the cwd varies."""
    pa, pb = Path(a), Path(b)
    return a == b or (pa.name == pb.name and not (pa.is_absolute() and pb.is_absolute()))


def _diagnosed(text: str, probe: bool = False, help_: bool = False) -> bool:
    """A failure marker on a line shaped like a diagnostic — `usage:`, a
    traceback, `error: …`, or `command not found` and the like after a
    `<prog>: ` or an `…Error` — never one inside content, such as a grep
    match's `path:NN:` line. A help call's `usage:` is its answer, and a
    probe's `No such file` is too: a call that only reads, or a read program
    (`ls: cannot access …`) inside one that does more."""
    for line in text.splitlines():
        if line.startswith(("Traceback (most recent call last)", "error:")):
            return True
        if not help_ and re.match(r"\s*usage:", line):
            return True
        if GREP_LINE_RE.match(line) or not (m := DIAG_LINE_RE.match(line)):
            continue
        reader = probe or m.group(0)[:-2] in READ_PROGS
        for mark in FAIL_MARK_RE.finditer(line):
            if not (reader and mark.group(0) == "No such file or directory"):
                return True
    return False


def _last_prog(f: _BashFacts) -> str:
    """The program at the end of the call's last pipeline: its exit status
    is the call's."""
    stages = _split(f.commands[-1], pipes=True) if f.commands else []
    return _seg_prog(stages[-1]) if stages else ""


@lru_cache(maxsize=16_384)
def _help_cmd(cmd: str) -> bool:
    return any(HELP_RE.search(_blank(c)) for c in _bash(cmd).commands)


def _is_help(rec: dict) -> bool:
    """Whether a call asked a program for its help text."""
    return rec["name"] == "Bash" and _help_cmd(rec.get("cmd") or "")


def _failed(rec: dict) -> bool:
    """Whether a call failed. An operator's refusal is no failure; nor is a
    grep or diff that found nothing, a loop wait reporting its exit code, or
    a probe that answered `No such file` — a call whose ops all read or do
    nothing ignores its `is_error` flag. Otherwise failure is the flag, or a
    marker on a diagnostic line of the result, since the loop's commands end
    in `2>&1` and fail with exit 0."""
    head = rec.get("res_head", "")
    if REJECTED_RE.match(head):
        return False
    if rec["name"] != "Bash":
        return bool(rec.get("is_error")) or _diagnosed(head)
    cmd = rec.get("cmd") or ""
    f = _bash(cmd)
    probe = all(op in ("read", "git-read", "noop") for op in f.ops)
    help_ = _is_help(rec)
    if rec.get("is_error"):
        m = EXIT_RE.match(head)
        code = int(m.group(1)) if m else None
        if code in (4, 5, 6, 7) and WAIT_EXIT_RE.search(cmd):
            return False
        if code in (1, 2) and _last_prog(f) in QUIET_EXIT_PROGS \
                and not _diagnosed(head[m.end():], help_=help_):
            return False
        if not probe:
            return True
    return _diagnosed(head, probe=probe, help_=help_)


def _progs(rec: dict) -> set[str]:
    """The programs a call ran — a python invocation as its script, since
    `python3 <plugin>/close_out.py` is close_out.py and not python3."""
    if rec["name"] != "Bash":
        return {rec["name"]}
    out = set()
    for c in _bash(rec.get("cmd") or "").commands:
        prog = _seg_prog(c)
        if prog.startswith("python"):
            m = re.search(r"([\w.-]+\.py)\b", c)
            prog = m.group(1) if m else prog
        if prog and prog not in NOOP_PROGS:
            out.add(prog)
    return out


def _sigs(rec: dict) -> set[str]:
    """What a retry has to repeat. A compound command's programs are separate
    signatures — `close_out.py … ; git status` is retried by re-running
    close_out.py alone; a python invocation signs as its script; and a read
    signs per file it named (`sed -n … a.ts` is not retried by reading
    b.ts), or as its whole command when it names none."""
    if rec["name"] != "Bash":
        return {f"{rec['name']}:{rec['key']}"}
    out = set()
    for c in _bash(rec.get("cmd") or "").commands:
        stages = _split(c, pipes=True)
        first = stages[0] if stages else c
        prog = _seg_prog(first)
        if prog.startswith("python"):
            m = re.search(r"([\w.-]+\.py)\b", first)
            prog = m.group(1) if m else prog
        if not prog or prog in NOOP_PROGS:
            continue
        if prog in READ_PROGS or prog in GIT_READ:
            paths = [w for w in _args(_blank(first)) if w not in (".", "..")
                     and ("/" in w or re.search(r"\.\w{1,6}$", w))]
            out |= ({f"{prog}:{p.rstrip('/').rsplit('/', 1)[-1]}" for p in paths}
                    or {f"{prog}:{' '.join(first.split())}"})
        else:
            out.add(prog)
    return out


def _fumble_key(rec: dict) -> str:
    """A fumble, generalised to the interface that was fumbled."""
    if rec["name"] != "Bash":
        return rec["name"]
    cmds = _bash(rec.get("cmd") or "").commands or (rec.get("cmd") or "",)
    cmd = (next((c for c in cmds if HELP_RE.search(_blank(c))), None)
           or next((c for c in cmds if _seg_prog(c) and _seg_prog(c) not in NOOP_PROGS),
                   cmds[0]))
    cmd = re.sub(r"\S*/([\w.-]+\.py)", r"\1", " ".join(cmd.split()))
    m = re.match(r"(?:python3?\s+)?([\w.-]+)\s*([a-z][\w-]*)?", cmd)
    if not m:
        return cmd[:40]
    return f"{m.group(1)} {m.group(2) or ''}".strip()


def _launched(t: dict) -> bool:
    """Whether a turn left work running in the background: a Bash call run
    in the background, an agent launched asynchronously, a `--detach` or
    long_run.py start."""
    for rec in t["tools"]:
        if rec.get("background"):
            return True
        if rec["name"] in DISPATCH_TOOLS and ASYNC_RE.search(rec.get("res_head", "")):
            return True
        if rec["name"] == "Bash" and LAUNCH_RE.search(rec.get("cmd") or ""):
            return True
    return False


def classify_turns(turns: list[dict], first_edit_turn: int | None, *,
                   reads_are_work: bool = False, plan_is_edit: bool = False) -> list[dict]:
    """One class and one read count per turn.

    Classes, first match in this order when a turn mixes calls: dispatch · edit ·
    gate · commit · record · retry · fumble · wait · git-inspect · orient-read ·
    work-read · think · other. `edit` and `record` are the same op split by what
    it wrote (a done-record, verdict or close-out entry is a record; a turn that
    writes both is an edit — `plan_is_edit` makes plan.md an edit), and the
    order means retry/fumble are lower bounds — a retried edit or a re-run gate
    is counted as the work it did. With `reads_are_work` every read turn, a
    git-inspect one too, is a `work-read`. A turn with no tool call is the session's
    hand-back (`record`) when it is the last turn, a `wait` when the session
    had work running in the background (the turn before it launched some, or
    the next thing to arrive was a task notification), and `think` otherwise;
    so is a turn whose only tools do nothing (a todo list).
    """
    out: list[dict] = []
    known: set[str] = set()          # paths in context, lagged one turn
    pending: list[set[str]] = []     # result paths not yet 'known'
    last = len(turns) - 1
    for i, t in enumerate(turns):
        ops, targets, reads = turn_ops(t, plan_is_edit=plan_is_edit)
        opset = set(ops)
        failed_before = [r for pt in turns[max(0, i - 2):i] for r in pt["tools"]
                         if _failed(r)]
        sigs_before: set[str] = set().union(*(_sigs(r) for r in failed_before))
        progs_before: set[str] = set().union(*(_progs(r) for r in failed_before))
        is_retry = bool(sigs_before) and any(_sigs(r) & sigs_before for r in t["tools"])
        bad = next((r for r in t["tools"] if _failed(r)
                    or (progs_before and _is_help(r) and _progs(r) & progs_before)), None)

        if not t["tools"]:
            cls = ("record" if i == last else
                   "wait" if t.get("notified") or (i and _launched(turns[i - 1])) else
                   "think")
        elif "dispatch" in opset:
            cls = "dispatch"
        elif "edit" in opset:
            cls = "edit"
        elif "gate" in opset:
            cls = "gate"
        elif "git-mutate" in opset:
            cls = "commit"
        elif "record" in opset:
            cls = "record"
        elif is_retry:
            cls = "retry"
        elif bad is not None:
            cls = "fumble"
        elif "wait" in opset:
            cls = "wait"
        elif opset <= {"git-read", "noop"} and "git-read" in opset and not reads_are_work:
            cls = "git-inspect"
        elif opset <= {"read", "git-read", "noop"} and opset & {"read", "git-read"}:
            cls = ("orient-read" if not reads_are_work and (
                first_edit_turn is None or t["i"] < first_edit_turn) else "work-read")
        elif opset == {"noop"} and all(r["name"] != "Bash" for r in t["tools"]):
            cls = "think"
        else:
            cls = "other"

        rec = {"i": t["i"], "cls": cls, "reads": reads}
        if cls in ("retry", "fumble"):
            rec["fumble_key"] = _fumble_key(bad) if bad else ""
        if cls in ("orient-read", "work-read", "git-inspect"):
            paths, resolved = _read_targets(t)
            prev = _touched_files(turns[i - 1]) if i else []
            rec["independent"] = bool(
                resolved and all(p in known for p in paths)
                and not any(_same_file(p, q) for p in paths for q in prev))
        out.append(rec)

        # context lags by one turn: what turn i's result revealed is only
        # 'known' from turn i+2, so a read at i+1 that used it is not independent
        known.update(str(Path(p)) for p in (targets or []))
        for rr in t["tools"]:
            known.update(str(Path(p)) for p in bash_read_paths(rr.get("cmd") or ""))
            if rr["name"] in WRITE_TOOLS or rr["name"] == "Read":
                known.add(str(Path(rr["key"])))
        if pending:
            known.update(pending.pop(0))
        pending.append(t.get("res_paths") or set())

    # batchable runs: consecutive read-only turns. Perfect batching would fold
    # each run into its first turn. A strict one is also independent: every
    # file it opens was in context, and none is one the turn before it read or
    # searched, whose result may have shown it where to look.
    read_only = {"orient-read", "work-read", "git-inspect"}
    run: list[dict] = []
    for rec in out + [{"cls": "-"}]:
        if rec["cls"] in read_only:
            run.append(rec)
            continue
        for k, r in enumerate(run):
            r["batchable"] = k > 0
            r["batchable_strict"] = k > 0 and r.get("independent", False)
        run = []
    return out


# ---------------------------------------------------------------------------
# Transcript replay. The stream-json file logs each assistant message several
# times; a turn is one message id, with the tool results that followed it.
# ---------------------------------------------------------------------------

SYNTHETIC_MODEL = "<synthetic>"   # a message Claude Code wrote itself: no model call
NOT_A_PROMPT = ("<task-notification>", "<command-name>", "<local-command-caveat>",
                "<local-command-stdout>", "<local-command-stderr>", "[Request interrupted")


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        return None


def _result_text(block) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def _tool_key(name: str, inp: dict) -> str:
    """A short, comparable description of one tool call (what was read/run)."""
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        return inp.get("file_path") or inp.get("notebook_path") or "?"
    if name == "Bash":
        return (inp.get("command") or "")[:160]
    if name in ("Grep", "Glob"):
        return f"{inp.get('pattern', '')} in {inp.get('path', '.')}"
    if name in ("Agent", "Task"):
        return f"{inp.get('subagent_type', '?')}: {(inp.get('description') or '')[:80]}"
    return ""


def _wrote_done_record(name: str, inp: dict) -> bool:
    """Whether a write tool's text carries a plan's done-record."""
    if name not in WRITE_TOOLS:
        return False
    texts = [inp.get("new_string"), inp.get("content"), inp.get("new_source")]
    texts += [e.get("new_string") for e in inp.get("edits") or [] if isinstance(e, dict)]
    return any(isinstance(x, str) and DONE_RECORD_RE.search(x) for x in texts)


def _user_text_kind(o: dict, txt: str) -> str | None:
    """What one user text is: `prompt` (the operator's, or a skill they
    invoked), `notification` (a background task's report) or None — Claude
    Code's own bookkeeping: a meta record, a compact summary, a local command
    and its output, an interruption."""
    if o.get("isMeta") or o.get("isCompactSummary"):
        return None
    s = txt.lstrip()
    if s.startswith("<task-notification>"):
        return "notification"
    return None if s.startswith(NOT_A_PROMPT) else "prompt"


def replay(path: Path) -> dict:
    """One transcript -> ordered turns with usage, tool calls and their results.
    A record is one `\\n`-terminated line, so the file is read with
    newline="\\n": a line is cut nowhere else.

    A message logged several times is one turn, its input and cache tokens
    those of its first record; its output tokens are the most any record
    reports (a streamed message's count grows from record to record) and its
    stop reason the last one given. A `<synthetic>` message is no turn: no
    model was called. A turn is marked `notified` when the first user text
    after it was a background task's notification."""
    turns: list[dict] = []
    by_id: dict[str, dict] = {}
    pending: dict[str, dict] = {}   # tool_use_id -> turn (awaiting its result)
    user_prompts = 0
    injected_chars = 0               # text blocks in user messages that are not tool results
    awaiting: dict | None = None     # the last turn, until a user text follows it

    def user_text(o: dict, txt: str) -> int:
        nonlocal awaiting
        kind = _user_text_kind(o, txt)
        if kind and awaiting is not None:
            awaiting["notified"] = kind == "notification"
            awaiting = None
        return kind == "prompt"

    with path.open(errors="replace", newline="\n") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            msg = o.get("message") or {}
            if t == "assistant":
                mid = msg.get("id")
                usage = msg.get("usage") or {}
                if msg.get("model") == SYNTHETIC_MODEL:
                    continue
                out = usage.get("output_tokens", 0) or 0
                think = (usage.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0
                if mid not in by_id:
                    if not usage:
                        continue
                    cc = usage.get("cache_creation") or {}
                    turn = {
                        "i": len(turns) + 1,
                        "ts": _ts(o.get("timestamp")),
                        "model": msg.get("model", "unknown"),
                        "effort": o.get("effort"),
                        "stop": msg.get("stop_reason"),
                        "input": usage.get("input_tokens", 0) or 0,
                        "cr": usage.get("cache_read_input_tokens", 0) or 0,
                        "cw": usage.get("cache_creation_input_tokens", 0) or 0,
                        "cw5m": cc.get("ephemeral_5m_input_tokens", 0) or 0,
                        "cw1h": cc.get("ephemeral_1h_input_tokens", 0) or 0,
                        "out": out,
                        "think": think,
                        "tools": [],       # [{name, key, id, result_chars, is_error, …}]
                        "text_chars": 0,
                        "result_chars": 0,  # tool results that followed this turn
                        "res_paths": set(),  # paths those results put into context
                        "notified": False,  # the next user text was a task notification
                    }
                    turn["ctx"] = turn["input"] + turn["cr"] + turn["cw"]
                    by_id[mid] = turn
                    turns.append(turn)
                    awaiting = turn
                turn = by_id[mid]
                if usage:
                    turn["out"] = max(turn["out"], out)
                    turn["think"] = max(turn["think"], think)
                if msg.get("stop_reason"):
                    turn["stop"] = msg["stop_reason"]
                for blk in msg.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    bt = blk.get("type")
                    if bt == "tool_use":
                        tid = blk.get("id")
                        if any(x["id"] == tid for x in turn["tools"]):
                            continue
                        name = blk.get("name", "?")
                        inp = blk.get("input") or {}
                        rec = {"name": name, "key": _tool_key(name, inp), "id": tid,
                               "cmd": (inp.get("command") or "") if name == "Bash" else "",
                               "result_chars": 0, "is_error": False, "res_head": "",
                               "background": bool(inp.get("run_in_background")),
                               "done": _wrote_done_record(name, inp)}
                        turn["tools"].append(rec)
                        if tid:
                            pending[tid] = rec
                    elif bt == "text":
                        turn["text_chars"] += len(blk.get("text", ""))
            elif t == "user":
                c = msg.get("content")
                if isinstance(c, str):
                    user_prompts += user_text(o, c)
                    continue
                for blk in c or []:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_result":
                        txt = _result_text(blk)
                        n = len(txt)
                        rec = pending.pop(blk.get("tool_use_id"), None)
                        if rec is not None:
                            rec["result_chars"] += n
                            rec["is_error"] = bool(blk.get("is_error"))
                            if not rec["res_head"]:
                                rec["res_head"] = txt[:FAIL_HEAD]
                        # attribute to the last turn (results follow their turn)
                        if turns:
                            turns[-1]["result_chars"] += n
                            seen = turns[-1]["res_paths"]
                            if len(seen) < RESULT_PATH_CAP:
                                for m in BASH_PATH_RE.finditer(txt[:RESULT_SCAN_CHARS]):
                                    seen.add(str(Path(m.group(0))))
                                    if len(seen) >= RESULT_PATH_CAP:
                                        break
                    elif blk.get("type") == "text":
                        txt = blk.get("text", "")
                        if "<system-reminder>" in txt or "<attachment" in txt:
                            injected_chars += len(txt)
                        else:
                            user_prompts += user_text(o, txt)
    return {"turns": turns, "user_prompts": user_prompts,
            "injected_chars": injected_chars}


# ---------------------------------------------------------------------------
# Per-session metrics — what a caller aggregates.
# ---------------------------------------------------------------------------


def first_write_turn(turns: list[dict]) -> int | None:
    """The turn of the session's first write *tool* call."""
    for t in turns:
        if any(rec["name"] in WRITE_TOOLS for rec in t["tools"]):
            return t["i"]
    return None


def first_edit_turn(turns: list[dict], *, reads_are_work: bool = False,
                    plan_is_edit: bool = False) -> int | None:
    """The turn of the session's first edit — where orientation ends. Wider
    than first_write_turn: it also sees the edits done through the shell, which
    for some roles is most of them, and it ignores a call that only wrote a
    record (a done-record, a verdict, a close-out entry; with `plan_is_edit`
    plan.md is an edit). With `reads_are_work` there is no orientation: the
    first turn is where it ends."""
    if reads_are_work:
        return turns[0]["i"] if turns else None
    for t in turns:
        if "edit" in turn_ops(t, plan_is_edit=plan_is_edit)[0]:
            return t["i"]
    return None


def turn_tier_cost(t: dict, cost_for) -> dict[str, float]:
    """One turn's cost, split by the tier each token was billed at. `cost_for`
    is slice_cost.cost_for — prices live there, and only there; it is handed
    the turn's prompt size, which picks a model's long-prompt tier, and its
    cache writes split by TTL: the 1-hour ones as `cache_write_1h`, the rest
    as `cache_write`."""
    prompt = t["input"] + t["cr"] + t["cw"]
    hour = min(t.get("cw1h", 0), t["cw"])
    return {
        "input": cost_for(t["model"], {"input": t["input"]}, prompt_tokens=prompt),
        "cache_read": cost_for(t["model"], {"cache_read": t["cr"]}, prompt_tokens=prompt),
        "cache_write": cost_for(t["model"], {"cache_write": t["cw"] - hour,
                                             "cache_write_1h": hour}, prompt_tokens=prompt),
        "output": cost_for(t["model"], {"output": t["out"]}, prompt_tokens=prompt),
    }


def prefix_breaks(turns: list[dict], cost_for) -> tuple[list[dict], int]:
    """(breaks, gaps over the cache TTL). A break is a turn whose cache_read
    fell short of what the turn before it left cached: the prompt did not come
    back from cache, it was written again at the write rate instead of read at
    the read rate, and `extra_cost` is that difference."""
    breaks = []
    gaps_over_ttl = 0
    for i in range(1, len(turns)):
        prev, cur = turns[i - 1], turns[i]
        shortfall = prev["cr"] + prev["cw"] - cur["cr"]
        gap = (cur["ts"] - prev["ts"]).total_seconds() if cur["ts"] and prev["ts"] else 0.0
        if gap > TTL_S:
            gaps_over_ttl += 1
        if shortfall > BREAK_SLACK:
            prompt = cur["input"] + cur["cr"] + cur["cw"]
            breaks.append({
                "turn": cur["i"], "shortfall": shortfall, "gap_s": round(gap),
                "extra_cost": (cost_for(cur["model"], {"cache_write": shortfall},
                                        prompt_tokens=prompt)
                               - cost_for(cur["model"], {"cache_read": shortfall},
                                          prompt_tokens=prompt)),
            })
    return breaks, gaps_over_ttl


def analyse(rep: dict, cost_for, *, reads_are_work: bool = False,
            plan_is_edit: bool = False) -> dict:
    """One replayed transcript -> {turns, classes, turn_cost, breaks, metrics}.

    `classes` and `turn_cost` are per turn and index-aligned with `turns`;
    `metrics` is the per-session block a caller aggregates (and the research
    profiler extends). An empty transcript returns {}.

    The caller says what the session's role makes of its turns. With
    `reads_are_work` there is no orientation: every read turn is a
    `work-read` (a git-inspect one too), the first turn counts as the first
    edit and the orientation figures are 0. With `plan_is_edit` a write to
    plan.md is an `edit`, not a `record` — unless what it wrote is a
    done-record.
    """
    turns = rep["turns"]
    n = len(turns)
    if n == 0:
        return {}

    tier: Counter = Counter()
    turn_cost: list[float] = []
    for t in turns:
        c = turn_tier_cost(t, cost_for)
        tier.update(c)
        turn_cost.append(sum(c.values()))
    total = sum(turn_cost)

    ctx = [t["ctx"] for t in turns]
    breaks, gaps_over_ttl = prefix_breaks(turns, cost_for)
    break_extra = sum(b["extra_cost"] for b in breaks)

    fw = first_write_turn(turns)
    fe = first_edit_turn(turns, reads_are_work=reads_are_work, plan_is_edit=plan_is_edit)
    classes = classify_turns(turns, fe, reads_are_work=reads_are_work,
                             plan_is_edit=plan_is_edit)
    cls_turns: Counter = Counter(r["cls"] for r in classes)
    cls_cost: dict[str, float] = defaultdict(float)
    for r, c in zip(classes, turn_cost, strict=True):
        cls_cost[r["cls"]] += c
    reads = [r["reads"] for r in classes]
    batchable = sum(1 for r in classes if r.get("batchable"))
    batchable_strict = sum(1 for r in classes if r.get("batchable_strict"))
    avoidable = cls_turns["retry"] + cls_turns["fumble"] + batchable_strict

    orient_turns = 0 if reads_are_work else (fw - 1) if fw else n
    orient_cost = sum(turn_cost[:orient_turns])

    metrics = {
        "turns": n,
        "model": Counter(t["model"] for t in turns).most_common(1)[0][0],
        "effort": next((t["effort"] for t in turns if t.get("effort")), None),
        "user_prompts": rep["user_prompts"],
        "tok": {"input": sum(t["input"] for t in turns),
                "cache_read": sum(t["cr"] for t in turns),
                "cache_write": sum(t["cw"] for t in turns),
                "cache_write_1h": sum(t["cw1h"] for t in turns),
                "output": sum(t["out"] for t in turns),
                "thinking": sum(t["think"] for t in turns)},
        "cost": round(total, 4),
        "cost_tier": {k: round(v, 4) for k, v in tier.items()},
        "ctx_first": ctx[0], "ctx_max": max(ctx), "ctx_last": ctx[-1],
        "ctx_mean": round(sum(ctx) / n),
        # tools/turn is what the transcript shows; reads/turn counts the read
        # ops chained inside one Bash command, which is the honest batching
        # metric — a `sed -n … && sed -n …` is one tool call and two reads.
        "tool_calls": sum(len(t["tools"]) for t in turns),
        "tools_per_turn": round(sum(len(t["tools"]) for t in turns) / n, 2),
        "read_ops": sum(reads),
        "reads_per_turn": round(sum(reads) / n, 2),
        "reads_per_read_turn": (round(sum(r for r in reads if r)
                                      / sum(1 for r in reads if r), 2)
                                if any(reads) else 0),
        "first_write_turn": fw, "first_edit_turn": fe,
        "orient_turns": orient_turns,
        "orient_turns_edit": (fe - 1) if fe else n,
        "orient_cost": round(orient_cost, 4),
        "orient_cost_share": round(orient_cost / total, 3) if total else 0,
        "orient_ctx": ctx[orient_turns - 1] if orient_turns >= 1 else ctx[0],
        "turn_class_turns": dict(cls_turns),
        "turn_class_cost": {k: round(v, 4) for k, v in cls_cost.items()},
        "retry_turns": cls_turns["retry"], "fumble_turns": cls_turns["fumble"],
        "batchable_turns": batchable, "batchable_strict_turns": batchable_strict,
        "avoidable_turns": avoidable,
        "breaks": len(breaks),
        "breaks_after_gap": sum(1 for b in breaks if b["gap_s"] > TTL_S),
        "break_tokens": sum(b["shortfall"] for b in breaks),
        "break_extra_cost": round(break_extra, 4),
        "break_extra_share": round(break_extra / total, 3) if total else 0,
        "gaps_over_ttl": gaps_over_ttl,
    }
    return {"turns": turns, "classes": classes, "turn_cost": turn_cost,
            "breaks": breaks, "metrics": metrics}
