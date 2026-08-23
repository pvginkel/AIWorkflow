#!/usr/bin/env python3
"""Profile what a dev-loop session's context is made of, turn by turn.

Research tooling for docs/research/research-2.md (context economics). For every
session the run loop and plan loop recorded for a slice (enumerated exactly as
slice_cost.py does, so the two agree on what a slice is), the session's Claude
Code transcript is replayed into a per-turn trajectory:

  ctx[t]      = input + cache_read + cache_creation  — the prompt the model saw
  growth      = ctx[t] - ctx[t-1]                    — what the turn added
  prefix break: cache_read[t] < cache_read[t-1] + cache_creation[t-1] - slack
                (the previous prompt did not come back from cache; it was
                re-written at 1.25x instead of read at 0.1x)
  thinking    = usage.output_tokens_details.thinking_tokens — per turn, so the
                "is prior thinking retained in later prompts?" question can be
                answered from growth on turns whose tool results were tiny.

Per session it reports the fixed prefix (ctx at turn 1), growth, the cache-tier
cost split, the cost of the last quartile of turns, prefix breaks and the gaps
that precede them, the tool mix with per-file re-read counts, and the orientation
span (turns before the first edit). Per role it aggregates medians across
sessions; per slice it lists the files the most sessions re-read.

Every turn is also placed in one class — what that turn *did* — since the bill is
charged per turn: dispatch, edit, gate, commit, record, retry, fumble, wait,
git-inspect, orient-read, work-read, think, other. Reads chained inside one Bash
command are counted as separate reads, edits made through the shell (a heredoc'd
python rewrite, `sed -i`, a redirection) are visible as edits, and runs of
consecutive read-only turns are marked batchable, so §13 of --breakdown can say
what a slice's turns do and how many of them are avoidable.

Usage:
    context_profile.py <slice-dir>... [--json OUT] [--sessions] [--role R]
                       [--what-if] [--breakdown] [--report OUT.md]

--breakdown adds the aggregate analyses (cost by tier and role, what the
processed tokens are made of, prefix breaks, thinking retention, the tool and
read mix, orientation, cross-session re-reads, sub-agent overlap, artefact
sizes, the turn taxonomy) as Markdown; --report writes everything printed to
one file.

Stdlib-only like the rest of tools/, though nothing here ships in the plugin.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
_spec = importlib.util.spec_from_file_location(
    "slice_cost", REPO / "plugins" / "dev" / "tools" / "slice_cost.py")
slice_cost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slice_cost)  # type: ignore[union-attr]

PRICES = slice_cost.PRICES
CACHE_WRITE_MULT = slice_cost.CACHE_WRITE_MULT
CACHE_READ_MULT = slice_cost.CACHE_READ_MULT
TTL_S = 300           # the loop forces the 5-minute cache TTL
BREAK_SLACK = 2_000   # tokens of cache_read shortfall tolerated before we call a break
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GATE_MARKERS = ("kc project test", "kc project lint", "kc project build",
                "uv run --with pytest", "pytest", "go test", "npm test",
                "ruff check", "golangci-lint")


# ---------------------------------------------------------------------------
# Tool-call classification. Every field these add to a profile is new; nothing
# the tool already printed or wrote is computed from them.
# ---------------------------------------------------------------------------

BASH_CLASSES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"git (diff|show|log|status|blame)"), "git-inspect"),
    (re.compile(r"git (add|commit|rebase|merge|checkout|push|fetch|pull|stash|cherry)"),
     "git-mutate"),
    (re.compile(r"kc project (test|lint|build)|pytest|go test|ruff|golangci|npm test"
                r"|uv run --with pytest"), "gate"),
    (re.compile(r"\bkc (session|env|project)\b"), "kc-other"),
    (re.compile(r"^(cat|sed -n|head|tail|less)\b|\bcat\b|\bsed -n\b"), "cat/sed(read)"),
    (re.compile(r"\b(grep|rg|ag)\b"), "grep"),
    (re.compile(r"\b(ls|find|tree|wc|stat)\b"), "ls/find"),
    (re.compile(r"close_out\.py"), "close_out.py"),
    (re.compile(r"python3? "), "python-other"),
    (re.compile(r"\bcexec\b"), "cexec-other"),
]
SIZED_CLASSES = ("Read", "cat/sed(read)", "grep", "gate")   # classes whose per-call sizes we keep
READ_SUFFIXES = ("py", "go", "md", "ts", "yaml", "json")
BASH_READ_RE = re.compile(r"\bcat\b|\bsed -n\b")
BASH_PATH_RE = re.compile(r"[\w./@~+-]+\.(?:" + "|".join(READ_SUFFIXES) + r")\b")
SLICE_PATH_RE = re.compile(r"/slices/(?:completed/|backlog/)?(?=[^/]*[0-9])[^/]+/")
PHASE_PATH_RE = re.compile(r"/phases/P[^/]*/")
TOOL_RESULT_RE = re.compile(r"tool-results/.*$")


def tool_class(name: str, cmd: str) -> str:
    """One tool call's class: Bash by what it runs, every other tool by its name."""
    if name != "Bash":
        return name
    for rx, cls in BASH_CLASSES:
        if rx.search(cmd):
            return cls
    return "other"


def bash_read_paths(cmd: str) -> list[str]:
    """The source-ish paths a `cat` / `sed -n` command read."""
    if not cmd or not BASH_READ_RE.search(cmd):
        return []
    return [m.group(0) for m in BASH_PATH_RE.finditer(cmd)]


def generalise_path(path: str) -> str:
    """One slice's paths -> the shape they share across slices, so the same
    artefact read in 30 slices counts as one file."""
    p = SLICE_PATH_RE.sub("/slices/<slice>/", path)
    p = PHASE_PATH_RE.sub("/phases/P*/", p)
    return TOOL_RESULT_RE.sub("tool-results/<persisted>", p)


def _orient_bash_key(cmd: str) -> str:
    """A Bash command as one orientation step — what kind of thing it read."""
    c = " ".join(cmd.split())
    if "close_out.py" in c:
        return "close_out.py"
    if re.search(r"\bcat\b", c):
        for marker in ("plan.md", "slice.md", "verification.json",
                       "CLAUDE.md", "close-out.md"):
            if marker in c:
                return f"cat <{marker}>"
        for suffix, label in ((".md", "other .md"), (".py", ".py"), (".go", ".go")):
            if suffix in c:
                return f"cat <{label}>"
        return "cat <other>"
    if re.search(r"\bsed -n\b", c):
        return "sed -n <range>"
    if re.search(r"\b(grep|rg|ag)\b", c):
        return "grep/rg"
    if re.search(r"kc project (test|lint)", c):
        return "kc project test/lint"
    m = re.search(r"\bgit ([a-z-]+)", c)
    if m:
        return f"git {m.group(1)}"
    if re.search(r"\b(ls|find|wc)\b", c):
        return "ls/find/wc"
    return c[:60]


def _orient_key(rec: dict) -> str:
    """One pre-first-edit tool call, generalised enough to count across sessions."""
    if rec["name"] == "Read":
        return generalise_path(rec["key"])
    if rec["name"] == "Bash":
        return _orient_bash_key(rec.get("cmd") or rec["key"])
    return rec["name"]


# ---------------------------------------------------------------------------
# Per-turn classification (T1 of docs/research/turns-plan.md). The bill is
# charged per turn — one model invocation, ≈ $0.086 whatever the role — so the
# question this answers is what a slice's ≈ 880 turns actually *do*, and how
# many of them a change to the loop could remove. Everything below reads the
# turn dicts replay() already builds; the sections above are untouched.
#
# A turn is one op-set: every tool call it made, and — because a headless
# session is told to work through Bash — every `;`/`&&`/`||`-separated step
# inside each Bash command. Heredoc bodies are data, not shell, so they are
# stripped before a command is split (a python script that rewrites a file is
# one edit, not five steps).
# ---------------------------------------------------------------------------

HEREDOC_RE = re.compile(r"<<-?\s*[\"']?(\w+)[\"']?[^\n]*\n.*?^\s*\1\s*$", re.S | re.M)
HEREDOC_OPEN_RE = re.compile(r"<<-?\s*[\"']?\w+[\"']?[^\n]*\n")
ENV_PREFIX_RE = re.compile(r"^(?:\w+=\S*\s+)+")
WRAPPER_RE = re.compile(r"^(?:sudo|time|nohup|command|exec|timeout\s+\S+)\s+")
BLOCK_PREFIX_RE = re.compile(r"^(?:do|then|else|elif|fi|done|!)\s+|^[({})\\\s]+")

# op labels, in the vocabulary the turn classes are built from
READ_PROGS = {"cat", "head", "tail", "less", "more", "nl", "sed -n", "grep", "rg",
              "ag", "find", "ls", "tree", "wc", "stat", "du", "jq", "diff", "column"}
GIT_READ = {"git diff", "git show", "git log", "git status", "git blame",
            "git branch", "git ls-files", "git rev-parse", "git remote", "git tag"}
NOOP_PROGS = {"echo", "cd", "true", "false", "export", "set", "mkdir", "printf",
              "source", "unset", "pwd", "which", "type", "date", "sort", "uniq",
              "cut", "awk", "tr", "xargs", "seq", "test", "[",
              "for", "while", "do", "done", "if", "then", "else", "elif", "fi",
              "case", "esac", "read", "sleep"}
GATE_SEG_RE = re.compile(r"kc project (test|lint|build)|\bpytest\b|\bgo test\b|\bruff\b"
                         r"|golangci|npm (test|run (test|lint|build))|uv run --with pytest"
                         r"|\bmypy\b|\btsc\b|ansible-lint|molecule")
GIT_MUTATE_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?"
                           r"(add|commit|rebase|merge|checkout|switch|push|stash|cherry-pick|"
                           r"reset|revert|restore|am)\b")
WAIT_RE = re.compile(r"\bsleep\s+\d|kubectl\s+wait\b|\btrack_build(\.py)?\b|\bkill\s+-0\b"
                     r"|kubectl\s+[^|;]*\bget\b[^|;]*\s-w\b|\bwatch\s+-n")
HELP_RE = re.compile(r"--help\b|(?:\.py|\bkc|\bcexec|\bkaniko|\btrack_build)\S*\s+"
                     r"(?:[a-z-]+\s+)*-h(?:\s|$)")
FAIL_RE = re.compile(r"^usage:|^error:|^\s*usage:\s|\berror: (unrecognized|invalid|"
                     r"argument|the following)|command not found|No such file or directory"
                     r"|not recognized|invalid choice|unrecognized (option|arguments)"
                     r"|Traceback \(most recent call last\)|Permission denied", re.M)
CLOSE_OUT_WRITE_RE = re.compile(r"close_out\.py\s+(?:\S+\s+)*?(append|note|strike|init|stamp)\b")
KC_READ_RE = re.compile(r"\bkc\s+(?:project|env|session|config)\s+"
                        r"(info|list|describe|status|show|get|logs)\b")
CLOSE_OUT_READ_RE = re.compile(r"close_out\.py\s+(?:\S+\s+)*?(list|render|counts)\b")
DISPATCH_TOOLS = {"Agent", "Task"}
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch"}

# an edit done through the shell — invisible to WRITE_TOOLS
SHELL_EDIT_RES_BASE = [
    re.compile(r"\bsed\s+-i\b"),
    re.compile(r"\btee\b(?!\s+/dev/null)"),
    re.compile(r"\bgit\s+apply\b"),
    re.compile(r"\bpatch\s+-p\d"),
]
BODY_EDIT_RES = [                      # a heredoc'd python script that writes
    re.compile(r"\.write_text\s*\(|\.write_bytes\s*\("),
    re.compile(r"\bopen\s*\([^)]*['\"][wa]\+?['\"]"),
    re.compile(r"\.writelines\s*\(|json\.dump\s*\(|yaml\.(safe_)?dump\s*\("),
    re.compile(r"shutil\.(copy|move|copyfile)"),
]
REDIRECT_RE = re.compile(
    r"(?<![0-9<>&-])>>?\s*(?!/dev/null|&)((?=[\w./~$-]*[./])[\w./~$-]+)")
PY_PATH_RE = re.compile(r"(?:Path|open)\s*\(\s*[\"']([^\"']+)[\"']")
RECORD_NAME_RE = re.compile(r"(^|/)plan\.md$|result(_r\d+)?\.json$|(^|/)close-out\.md$")
RESULT_PATH_CAP = 400      # paths kept per tool result, for the batching test
FAIL_HEAD = 600            # chars of a result inspected for a failure marker
RESULT_SCAN_CHARS = 40_000  # chars of a result scanned for the paths it revealed


SHELL_EDIT_RES = SHELL_EDIT_RES_BASE + [REDIRECT_RE]


def _strip_heredocs(cmd: str) -> str:
    """The shell part of a command: heredoc bodies replaced by a placeholder."""
    out = HEREDOC_RE.sub(" <<BODY ", cmd)
    m = HEREDOC_OPEN_RE.search(out)       # unterminated (truncated transcript)
    return out[:m.start()] + " <<BODY " if m else out


def bash_segments(cmd: str) -> list[str]:
    """One Bash command -> its shell steps, split on `;` `&&` `||` and newlines
    but not inside quotes (a close-out `--headline "…"` spans lines) and not
    inside a heredoc. Pipes are not steps: `grep x | head` is one read,
    `cat a; cat b` is two."""
    s = _strip_heredocs(cmd)
    segs: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(s):
        ch = s[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            i += 1
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
        elif ch == "\\" and i + 1 < len(s):
            buf.append(s[i:i + 2])
            i += 2
        elif s.startswith("&&", i) or s.startswith("||", i):
            segs.append("".join(buf))
            buf = []
            i += 2
        elif ch in ";\n":
            segs.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    segs.append("".join(buf))
    return [x.strip() for x in segs if x.strip()]


def _seg_prog(seg: str) -> str:
    """The program a shell step runs, normalised (`sed -n` and `git <sub>` are
    their own programs — one reads, the other may not)."""
    s = BLOCK_PREFIX_RE.sub("", seg.strip())
    s = ENV_PREFIX_RE.sub("", s)
    s = WRAPPER_RE.sub("", s)
    m = re.match(r"(\$\w+|[\w./~-]+)", s)
    if not m:
        return ""
    prog = m.group(1).rsplit("/", 1)[-1]
    if prog == "sed":
        return "sed -n" if re.search(r"\bsed\s+-n\b", s) else "sed"
    if prog == "git":
        m2 = re.match(r"git\s+(?:-C\s+\S+\s+)?([a-z-]+)", s)
        return f"git {m2.group(1)}" if m2 else "git"
    return prog


def _seg_op(seg: str) -> str:
    """One shell step -> its op class. Tested as text, not by program name, so
    `cexec python sh -c 'uv run pytest'` is a gate and not a `cexec`."""
    if GATE_SEG_RE.search(seg):
        return "gate"
    if WAIT_RE.search(seg):
        return "wait"
    if any(rx.search(seg) for rx in SHELL_EDIT_RES):
        return "edit"
    if GIT_MUTATE_RE.search(seg):
        return "git-mutate"
    if CLOSE_OUT_WRITE_RE.search(seg):
        return "record"
    if CLOSE_OUT_READ_RE.search(seg):
        return "read"
    if KC_READ_RE.search(seg):
        return "read"
    prog = _seg_prog(seg)
    if prog in GIT_READ:
        return "git-read"
    if prog in READ_PROGS:
        return "read"
    if prog in NOOP_PROGS or not prog:
        return "noop"      # a shell fragment: a closing brace, a stray quote
    return "other"


def bash_ops(cmd: str) -> list[str]:
    """Every op one Bash call performed. The heredoc body is inspected once,
    for the python-writes-a-file case the shell part cannot see."""
    ops = [_seg_op(s) for s in bash_segments(cmd)]
    if "edit" not in ops and any(rx.search(cmd) for rx in BODY_EDIT_RES):
        ops.append("edit")
    return ops


def _bash_edit_targets(cmd: str) -> list[str]:
    """What a shell edit wrote, as far as the command reveals it."""
    shell = _strip_heredocs(cmd)
    out = [m.group(1) for m in REDIRECT_RE.finditer(shell)]
    m = re.search(r"\bsed\s+-i\b[^;&|]*?([\w./~-]+\.\w+)\s*$", shell)
    if m:
        out.append(m.group(1))
    m = re.search(r"\btee\s+(?:-a\s+)?([\w./~-]+)", shell)
    if m:
        out.append(m.group(1))
    if any(rx.search(cmd) for rx in BODY_EDIT_RES):
        out += PY_PATH_RE.findall(cmd)
    return out


def _is_record_path(path: str) -> bool:
    return bool(RECORD_NAME_RE.search(path.strip().rstrip("'\"")))


def bash_read_count(cmd: str) -> int:
    return sum(1 for op in bash_ops(cmd) if op in ("read", "git-read"))


def turn_ops(t: dict) -> tuple[list[str], list[str], int]:
    """(ops, write targets, read count) for one turn, over all its tool calls."""
    ops: list[str] = []
    targets: list[str] = []
    reads = 0
    for rec in t["tools"]:
        name = rec["name"]
        if name in DISPATCH_TOOLS:
            ops.append("dispatch")
        elif name in WRITE_TOOLS:
            ops.append("edit")
            targets.append(rec["key"])
        elif name in READ_TOOLS:
            ops.append("read")
            reads += 1
        elif name == "Bash":
            cmd = rec.get("cmd") or ""
            bops = bash_ops(cmd)
            ops += bops
            reads += sum(1 for op in bops if op in ("read", "git-read"))
            if "edit" in bops:
                targets += _bash_edit_targets(cmd)
        else:
            ops.append("other")
    return ops, targets, reads


def _read_targets(t: dict) -> tuple[list[str], bool]:
    """The concrete files a read turn opened, and whether every read it did
    resolved to one (a `grep -rn pat .` or an `ls` does not)."""
    paths: list[str] = []
    resolved = True
    for rec in t["tools"]:
        if rec["name"] == "Read":
            paths.append(str(Path(rec["key"])))
        elif rec["name"] in ("Grep", "Glob"):
            resolved = False
        elif rec["name"] == "Bash":
            cmd = rec.get("cmd") or ""
            got = bash_read_paths(cmd)
            paths += [str(Path(p)) for p in got]
            n_reads = bash_read_count(cmd)
            if len(got) < n_reads:
                resolved = False
    return paths, (resolved and bool(paths))


def _failed(rec: dict) -> bool:
    return bool(rec.get("is_error")) or bool(FAIL_RE.search(rec.get("res_head", "")))


def _sigs(rec: dict) -> set[str]:
    """What a retry has to repeat. A compound command's programs are separate
    signatures — `close_out.py … ; git status` is retried by re-running
    close_out.py alone — and a python invocation signs as its script, since
    `python3 <plugin>/close_out.py` is close_out.py and not python3."""
    if rec["name"] != "Bash":
        return {f"{rec['name']}:{rec['key']}"}
    out = set()
    for seg in bash_segments(rec.get("cmd") or ""):
        prog = _seg_prog(seg)
        if prog.startswith("python"):
            m = re.search(r"([\w.-]+\.py)\b", seg)
            prog = m.group(1) if m else prog
        if prog and prog not in NOOP_PROGS:
            out.add(prog)
    return out


def _fumble_key(rec: dict) -> str:
    """A fumble, generalised to the interface that was fumbled."""
    if rec["name"] != "Bash":
        return rec["name"]
    cmd = " ".join((rec.get("cmd") or "").split())
    cmd = re.sub(r"\S*/([\w.-]+\.py)", r"\1", cmd)
    segs = [x.strip() for x in re.split(r"[;&|]+", cmd) if x.strip()]
    seg = (next((x for x in segs if HELP_RE.search(x)), None)
           or next((x for x in segs if _seg_prog(x) and _seg_prog(x) not in NOOP_PROGS),
                   segs[0] if segs else cmd))
    seg = ENV_PREFIX_RE.sub("", WRAPPER_RE.sub("", seg))
    m = re.match(r"(?:python3?\s+)?([\w.-]+)\s*([a-z][\w-]*)?", seg)
    if not m:
        return seg[:40]
    return f"{m.group(1)} {m.group(2) or ''}".strip()


def classify_turns(turns: list[dict], first_edit_turn: int | None) -> list[dict]:
    """One class and one read count per turn.

    Classes, first match in this order when a turn mixes calls: dispatch · edit ·
    gate · commit · record · retry · fumble · wait · git-inspect · orient-read ·
    work-read · think · other. `edit` and `record` are the same op split by what
    it wrote (a done-record or verdict is a record; a turn that writes both is an
    edit), and the order means retry/fumble are lower bounds — a retried edit or
    a re-run gate is counted as the work it did.
    """
    out: list[dict] = []
    known: set[str] = set()          # paths in context, lagged one turn
    pending: list[set[str]] = []     # result paths not yet 'known'
    for i, t in enumerate(turns):
        ops, targets, reads = turn_ops(t)
        opset = set(ops)
        record_write = ("record" in opset
                        or (targets and all(_is_record_path(p) for p in targets)))
        sigs_before: set[str] = set()
        for pt in turns[max(0, i - 2):i]:
            for r in pt["tools"]:
                if _failed(r):
                    sigs_before |= _sigs(r)
        is_retry = bool(sigs_before) and any(_sigs(r) & sigs_before for r in t["tools"])
        is_fumble = any(HELP_RE.search(r.get("cmd") or "") for r in t["tools"]) or \
            any(_failed(r) for r in t["tools"])

        if not t["tools"]:
            cls = "think"
        elif "dispatch" in opset:
            cls = "dispatch"
        elif "edit" in opset and not record_write:
            cls = "edit"
        elif "gate" in opset:
            cls = "gate"
        elif "git-mutate" in opset:
            cls = "commit"
        elif record_write:
            cls = "record"
        elif is_retry:
            cls = "retry"
        elif is_fumble:
            cls = "fumble"
        elif "wait" in opset:
            cls = "wait"
        elif opset <= {"git-read", "noop"} and "git-read" in opset:
            cls = "git-inspect"
        elif opset <= {"read", "git-read", "noop"} and opset & {"read", "git-read"}:
            cls = ("orient-read" if first_edit_turn is None or t["i"] < first_edit_turn
                   else "work-read")
        else:
            cls = "other"

        rec = {"i": t["i"], "cls": cls, "reads": reads}
        if cls in ("retry", "fumble"):
            bad = next((r for r in t["tools"]
                        if HELP_RE.search(r.get("cmd") or "") or _failed(r)), None)
            rec["fumble_key"] = _fumble_key(bad) if bad else ""
        if cls in ("orient-read", "work-read", "git-inspect"):
            paths, resolved = _read_targets(t)
            rec["independent"] = bool(resolved and all(p in known for p in paths))
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
    # each run into its first turn.
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

def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError, AttributeError):
        return None


def _tier_cost(model: str, input_=0, cr=0, cw=0, out=0) -> dict[str, float]:
    base = PRICES.get(model)
    if not base:
        return {"input": 0.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0}
    return {
        "input": input_ / 1e6 * base["input"],
        "cache_read": cr / 1e6 * base["input"] * CACHE_READ_MULT,
        "cache_write": cw / 1e6 * base["input"] * CACHE_WRITE_MULT,
        "output": out / 1e6 * base["output"],
    }


def _result_text(block) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def _result_chars(block) -> int:
    return len(_result_text(block))


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


def replay(path: Path) -> dict:
    """One transcript -> ordered turns with usage, tool calls and their results."""
    turns: list[dict] = []
    by_id: dict[str, dict] = {}
    pending: dict[str, dict] = {}   # tool_use_id -> turn (awaiting its result)
    user_prompts = 0
    injected_chars = 0               # text blocks in user messages that are not tool results
    with path.open(errors="replace") as fh:
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
                        "out": usage.get("output_tokens", 0) or 0,
                        "think": ((usage.get("output_tokens_details") or {})
                                  .get("thinking_tokens", 0) or 0),
                        "tools": [],       # [{name, key, id, result_chars, is_error}]
                        "text_chars": 0,
                        "result_chars": 0,  # tool results that followed this turn
                        "res_paths": set(),  # paths those results put into context
                    }
                    turn["ctx"] = turn["input"] + turn["cr"] + turn["cw"]
                    by_id[mid] = turn
                    turns.append(turn)
                turn = by_id[mid]
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
                               "result_chars": 0, "is_error": False, "res_head": ""}
                        turn["tools"].append(rec)
                        if tid:
                            pending[tid] = rec
                    elif bt == "text":
                        turn["text_chars"] += len(blk.get("text", ""))
            elif t == "user":
                c = msg.get("content")
                if isinstance(c, str):
                    user_prompts += 1
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
                            user_prompts += 1
    return {"turns": turns, "user_prompts": user_prompts,
            "injected_chars": injected_chars}


def profile(conv, rep: dict) -> dict:
    turns = rep["turns"]
    n = len(turns)
    if n == 0:
        return {}
    model = Counter(t["model"] for t in turns).most_common(1)[0][0]
    effort = next((t["effort"] for t in turns if t.get("effort")), None)

    # --- cost by tier, by turn ---
    tier = Counter()
    per_turn_cost = []
    for t in turns:
        c = _tier_cost(t["model"], t["input"], t["cr"], t["cw"], t["out"])
        tier.update(c)
        per_turn_cost.append(sum(c.values()))
    total = sum(per_turn_cost)
    q = max(1, n // 4)
    last_q_cost = sum(per_turn_cost[-q:])

    # --- context trajectory ---
    ctx = [t["ctx"] for t in turns]
    ctx_first = ctx[0]
    growth = [ctx[i] - ctx[i - 1] for i in range(1, n)]
    processed = sum(ctx)                    # tokens the model was shown, summed over turns
    fixed_processed = ctx_first * n         # the fixed prefix, shown every turn

    # --- prefix breaks and gaps ---
    breaks = []
    gaps_over_ttl = 0
    for i in range(1, n):
        prev, cur = turns[i - 1], turns[i]
        expected = prev["cr"] + prev["cw"]
        shortfall = expected - cur["cr"]
        gap = (cur["ts"] - prev["ts"]).total_seconds() if cur["ts"] and prev["ts"] else 0.0
        if gap > TTL_S:
            gaps_over_ttl += 1
        if shortfall > BREAK_SLACK:
            base = PRICES.get(cur["model"], {}).get("input", 0.0)
            breaks.append({
                "turn": cur["i"], "shortfall": shortfall, "gap_s": round(gap),
                "extra_cost": shortfall / 1e6 * base * (CACHE_WRITE_MULT - CACHE_READ_MULT),
            })
    break_extra = sum(b["extra_cost"] for b in breaks)
    breaks_after_gap = sum(1 for b in breaks if b["gap_s"] > TTL_S)

    # --- what accumulated context is made of ---
    # own output (text + tool_use json + thinking, if retained) vs tool results.
    cum_out = 0
    cum_think = 0
    own_processed = 0       # sum over turns of the prior output tokens in ctx
    think_processed = 0     # sum over turns of the prior thinking tokens in ctx
    for t in turns:
        own_processed += cum_out
        think_processed += cum_think
        cum_out += t["out"]
        cum_think += t["think"]
    accumulated_processed = processed - fixed_processed
    base_in = PRICES.get(model, {}).get("input", 0.0)
    think_read_cost = think_processed / 1e6 * base_in * CACHE_READ_MULT

    # --- thinking-retention probe: growth on turns whose results were tiny ---
    probe = []
    for i in range(1, n):
        prev, cur = turns[i - 1], turns[i]
        if prev["think"] >= 800 and prev["result_chars"] < 400 and cur["cr"] >= prev["cr"]:
            g = ctx[i] - ctx[i - 1]
            probe.append({"turn": cur["i"], "growth": g, "prev_out": prev["out"],
                          "prev_think": prev["think"],
                          "ratio_out": round(g / prev["out"], 2) if prev["out"] else None,
                          "ratio_out_minus_think": (round(g / (prev["out"] - prev["think"]), 2)
                                                    if prev["out"] - prev["think"] > 0 else None)})

    # --- tokens by model (a session is normally one model, but not always) ---
    tok_by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0})
    for t in turns:
        bucket = tok_by_model[t["model"]]
        bucket["input"] += t["input"]
        bucket["cache_read"] += t["cr"]
        bucket["cache_write"] += t["cw"]
        bucket["output"] += t["out"]

    # --- tools ---
    tool_counts = Counter()
    tool_chars = Counter()
    reads = Counter()
    read_chars = Counter()
    gate_runs = 0
    gate_chars = 0
    subagents = 0
    subagent_chars = 0
    persisted_reads = 0
    first_write_turn = None
    classes: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # cls -> [calls, chars]
    class_sizes: dict[str, list[int]] = defaultdict(list)         # per-call result sizes
    orient_calls: list[str] = []      # every tool call before the first edit
    orient_gate = False
    read_paths: set[str] = set()
    reads_after_dispatch: list[str] = []
    seen_agent = False
    for t in turns:
        for rec in t["tools"]:
            tool_counts[rec["name"]] += 1
            tool_chars[rec["name"]] += rec["result_chars"]
            if rec["name"] == "Read":
                reads[rec["key"]] += 1
                read_chars[rec["key"]] += rec["result_chars"]
                if "/tool-results/" in rec["key"]:
                    persisted_reads += 1
            if rec["name"] == "Bash" and any(m in rec["key"] for m in GATE_MARKERS):
                gate_runs += 1
                gate_chars += rec["result_chars"]
            if rec["name"] in ("Agent", "Task"):
                subagents += 1
                subagent_chars += rec["result_chars"]
            if rec["name"] in WRITE_TOOLS and first_write_turn is None:
                first_write_turn = t["i"]
            cls = tool_class(rec["name"], rec.get("cmd", ""))
            classes[cls][0] += 1
            classes[cls][1] += rec["result_chars"]
            if cls in SIZED_CLASSES:
                class_sizes[cls].append(rec["result_chars"])
            paths = ([rec["key"]] if rec["name"] == "Read"
                     else bash_read_paths(rec.get("cmd", "")))
            read_paths.update(str(Path(p)) for p in paths)
            if seen_agent:
                reads_after_dispatch.extend(paths)
            if first_write_turn is None:
                orient_calls.append(_orient_key(rec))
                orient_gate = orient_gate or cls == "gate"
            if rec["name"] in ("Agent", "Task"):
                seen_agent = True
    unique_files = len(reads)
    total_reads = sum(reads.values())

    # --- turn taxonomy (T1) --------------------------------------------------
    # first_write_turn above sees only WRITE_TOOLS; first_edit_turn also sees
    # the edits done through Bash (a heredoc'd python rewrite, `sed -i`, a
    # redirection), which is most of them for some roles.
    first_edit_turn = None
    for t in turns:
        ops, targets, _ = turn_ops(t)
        if "edit" in ops and not (targets and all(_is_record_path(x) for x in targets)):
            first_edit_turn = t["i"]
            break
    tcls = classify_turns(turns, first_edit_turn)
    cls_turns: Counter = Counter(r["cls"] for r in tcls)
    cls_cost: dict[str, float] = defaultdict(float)
    for r, c in zip(tcls, per_turn_cost, strict=True):
        cls_cost[r["cls"]] += c
    reads_per_turn = [r["reads"] for r in tcls]
    batchable = sum(1 for r in tcls if r.get("batchable"))
    batchable_strict = sum(1 for r in tcls if r.get("batchable_strict"))
    fumble_keys = Counter(r["fumble_key"] for r in tcls if r.get("fumble_key"))
    other_ops: Counter = Counter()
    for t, r in zip(turns, tcls, strict=True):
        if r["cls"] != "other":
            continue
        for rec in t["tools"]:
            if rec["name"] != "Bash":
                other_ops[rec["name"]] += 1
            else:
                for seg in bash_segments(rec.get("cmd") or ""):
                    if _seg_op(seg) == "other":
                        other_ops["$ " + (_seg_prog(seg) or "?")] += 1
    avoidable = cls_turns["retry"] + cls_turns["fumble"] + batchable_strict

    orient_turns = (first_write_turn - 1) if first_write_turn else n
    orient_cost = sum(per_turn_cost[:orient_turns])
    orient_ctx = ctx[orient_turns - 1] if orient_turns >= 1 else ctx_first

    dur = conv.duration_s()
    return {
        "slice": None,  # filled by caller
        "session": conv.session, "role": conv.role, "phase": conv.phase,
        "round": conv.round, "kind": conv.kind, "loop": conv.loop,
        "model": model, "effort": effort, "turns": n,
        "duration_s": round(dur), "user_prompts": rep["user_prompts"],
        "tok": {"input": sum(t["input"] for t in turns),
                "cache_read": sum(t["cr"] for t in turns),
                "cache_write": sum(t["cw"] for t in turns),
                "cache_write_1h": sum(t["cw1h"] for t in turns),
                "output": sum(t["out"] for t in turns),
                "thinking": sum(t["think"] for t in turns)},
        "cost": round(total, 4),
        "cost_tier": {k: round(v, 4) for k, v in tier.items()},
        "cost_last_quartile_share": round(last_q_cost / total, 3) if total else 0,
        "ctx_first": ctx_first, "ctx_max": max(ctx), "ctx_last": ctx[-1],
        "ctx_mean": round(statistics.fmean(ctx)),
        "growth_median": round(statistics.median(growth)) if growth else 0,
        "growth_mean": round(statistics.fmean(growth)) if growth else 0,
        "processed_tokens": processed,
        "fixed_share": round(fixed_processed / processed, 3) if processed else 0,
        "own_output_share_of_accumulated": (round(own_processed / accumulated_processed, 3)
                                            if accumulated_processed > 0 else None),
        "thinking_share_of_processed": round(think_processed / processed, 3) if processed else 0,
        "thinking_read_cost": round(think_read_cost, 4),
        "thinking_read_cost_share": round(think_read_cost / total, 3) if total else 0,
        "breaks": len(breaks), "breaks_after_gap": breaks_after_gap,
        "break_tokens": sum(b["shortfall"] for b in breaks),
        "break_extra_cost": round(break_extra, 4),
        "break_extra_share": round(break_extra / total, 3) if total else 0,
        "break_detail": breaks[:12],
        "gaps_over_ttl": gaps_over_ttl,
        "retention_probe": probe[:20],
        "tools": dict(tool_counts),
        "tool_result_chars": dict(tool_chars),
        "reads_total": total_reads, "reads_unique": unique_files,
        "reread_ratio": round(total_reads / unique_files, 2) if unique_files else 0,
        "top_reread": [{"file": f, "n": c, "chars": read_chars[f]}
                       for f, c in reads.most_common(8) if c > 1],
        "persisted_output_reads": persisted_reads,
        "gate_runs": gate_runs, "gate_result_chars": gate_chars,
        "subagents": subagents, "subagent_result_chars": subagent_chars,
        "first_write_turn": first_write_turn, "orient_turns": orient_turns,
        "orient_cost": round(orient_cost, 4), "orient_ctx": orient_ctx,
        "orient_cost_share": round(orient_cost / total, 3) if total else 0,
        "injected_chars": rep["injected_chars"],
        "trajectory": [{"i": t["i"], "ctx": t["ctx"], "cr": t["cr"], "cw": t["cw"],
                        "out": t["out"], "think": t["think"],
                        "res": t["result_chars"],
                        "cls": c["cls"], "reads": c["reads"],
                        "tools": [r["name"] for r in t["tools"]]}
                       for t, c in zip(turns, tcls, strict=True)],
        # --- turn taxonomy (T1) ---
        "first_edit_turn": first_edit_turn,
        "orient_turns_edit": (first_edit_turn - 1) if first_edit_turn else n,
        "turn_class_turns": dict(cls_turns),
        "turn_class_cost": {k: round(v, 4) for k, v in cls_cost.items()},
        "read_ops": sum(reads_per_turn),
        "reads_per_turn": round(sum(reads_per_turn) / n, 2),
        "reads_per_read_turn": (round(sum(r for r in reads_per_turn if r) /
                                      sum(1 for r in reads_per_turn if r), 2)
                                if any(reads_per_turn) else 0),
        "tools_per_turn": round(sum(len(t["tools"]) for t in turns) / n, 2),
        "retry_turns": cls_turns["retry"], "fumble_turns": cls_turns["fumble"],
        "batchable_turns": batchable, "batchable_strict_turns": batchable_strict,
        "avoidable_turns": avoidable,
        "fumble_keys": dict(fumble_keys),
        "other_ops": dict(other_ops),
        "files_read": dict(reads),
        # --- fields only --breakdown reads ---
        "parent_session": conv.parent.session if conv.parent else None,
        "tok_by_model": {m: dict(v) for m, v in tok_by_model.items()},
        "tool_classes": {c: list(v) for c, v in classes.items()},
        "class_sizes": dict(class_sizes),
        "orient_calls": orient_calls,
        "orient_gate": orient_gate,
        "ctx_at_first_write": ctx[first_write_turn - 1] if first_write_turn else None,
        "files_read_chars": dict(read_chars),
        "read_paths": sorted(read_paths),
        "reads_after_dispatch": reads_after_dispatch,
    }


# ---------------------------------------------------------------------------
# What-if models: computable from the trajectories alone, before any trial.
# ---------------------------------------------------------------------------

def what_if_cut(prof: dict, reorient_tokens: int, handoff_out: int = 4_000) -> dict:
    """Best single cut of this session: at which turn k would restarting in a
    fresh session (fixed prefix + a hand-off of `handoff_out` output tokens,
    read back as input + `reorient_tokens` of re-read files) have cost less
    than continuing, and by how much. The restarted session is assumed to add
    exactly what the original added from k on (same growth), so the saving is
    the history it no longer drags: (ctx[k] - ctx_first - handoff - reorient)
    tokens per later turn at the cache-read rate, minus the restart's writes.
    Ignores prefix breaks and any quality effect."""
    tr = prof["trajectory"]
    n = len(tr)
    if n < 4:
        return {"best_k": None, "saving": 0.0, "saving_share": 0.0}
    base_in = PRICES.get(prof["model"], {}).get("input", 0.0)
    base_out = PRICES.get(prof["model"], {}).get("output", 0.0)
    first = prof["ctx_first"]
    best = (0.0, None)
    for k in range(2, n - 1):
        carried = tr[k - 1]["ctx"] - first          # history the cut drops
        new_prefix = handoff_out + reorient_tokens   # what the restart reads instead
        per_turn_gain = (carried - new_prefix) / 1e6 * base_in * CACHE_READ_MULT
        later_turns = n - k
        restart_cost = (new_prefix / 1e6 * base_in * CACHE_WRITE_MULT   # written once
                        + handoff_out / 1e6 * base_out                    # hand-off authored
                        # half the prefix is session-specific:
                        + first / 1e6 * base_in * CACHE_WRITE_MULT * 0.5)
        saving = per_turn_gain * later_turns - restart_cost
        if saving > best[0]:
            best = (saving, k)
    return {"best_k": best[1], "saving": round(best[0], 3),
            "saving_share": round(best[0] / prof["cost"], 3) if prof["cost"] else 0.0}


def what_if_clear(prof: dict, keep_last: int = 20, chars_per_token: float = 4.0) -> dict:
    """Upper bound on what AgentDiet-style expiry of tool results would save:
    every tool result older than `keep_last` turns stops being re-read. Counts
    only the cache-read tokens avoided; ignores the cache invalidation each
    clearing causes (the docs say it does), so this is optimistic."""
    tr = prof["trajectory"]
    base_in = PRICES.get(prof["model"], {}).get("input", 0.0)
    avoided = 0
    for i in range(len(tr)):
        # results produced at turn j are in ctx from turn j+1 on; cleared at turn j+1+keep_last
        for j in range(0, i - keep_last):
            avoided += tr[j]["res"] / chars_per_token
    saving = avoided / 1e6 * base_in * CACHE_READ_MULT
    return {"tokens_avoided": int(avoided), "saving": round(saving, 3),
            "saving_share": round(saving / prof["cost"], 3) if prof["cost"] else 0.0}


def what_if_table(profiles: list[dict]) -> str:
    rows = ["role                     n    cut@20k%  cut@40k%  cut@60k%  "
            "sess>5%   clear20%  clear40%"]
    by_role: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        by_role[p["role"]].append(p)
    for role, ps in sorted(by_role.items()):
        cost = sum(p["cost"] for p in ps)
        cut = {}
        for r in (20_000, 40_000, 60_000):
            cut[r] = sum(what_if_cut(p, r)["saving"] for p in ps)
        sess5 = sum(1 for p in ps if what_if_cut(p, 40_000)["saving_share"] > 0.05)
        cl20 = sum(what_if_clear(p, 20)["saving"] for p in ps)
        cl40 = sum(what_if_clear(p, 40)["saving"] for p in ps)
        rows.append(f"{role[:24]:24s} {len(ps):4d} "
                    f"{cut[20_000] / cost * 100:8.1f}  {cut[40_000] / cost * 100:8.1f}  "
                    f"{cut[60_000] / cost * 100:8.1f}  {sess5:4d}/{len(ps):<4d} "
                    f"{cl20 / cost * 100:7.1f}  {cl40 / cost * 100:7.1f}")
    return "\n".join(rows)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def aggregate(profiles: list[dict]) -> dict:
    by_role: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        by_role[p["role"]].append(p)
    out = {}
    for role, ps in sorted(by_role.items()):
        cost = sum(p["cost"] for p in ps)
        tier = Counter()
        for p in ps:
            tier.update(p["cost_tier"])
        out[role] = {
            "sessions": len(ps),
            "cost_total": round(cost, 2),
            "tier_share": {k: round(v / cost, 3) for k, v in tier.items()} if cost else {},
            "turns_med": _med([p["turns"] for p in ps]),
            "turns_max": max(p["turns"] for p in ps),
            "ctx_first_med": _med([p["ctx_first"] for p in ps]),
            "ctx_mean_med": _med([p["ctx_mean"] for p in ps]),
            "ctx_max_med": _med([p["ctx_max"] for p in ps]),
            "ctx_max_max": max(p["ctx_max"] for p in ps),
            "growth_med": _med([p["growth_median"] for p in ps]),
            "fixed_share_med": _med([p["fixed_share"] for p in ps]),
            "own_output_share_med": _med([p["own_output_share_of_accumulated"] for p in ps]),
            "thinking_share_med": _med([p["thinking_share_of_processed"] for p in ps]),
            "thinking_read_cost_share_med": _med([p["thinking_read_cost_share"] for p in ps]),
            "thinking_read_cost_total": round(sum(p["thinking_read_cost"] for p in ps), 2),
            "last_quartile_share_med": _med([p["cost_last_quartile_share"] for p in ps]),
            "breaks_total": sum(p["breaks"] for p in ps),
            "breaks_after_gap_total": sum(p["breaks_after_gap"] for p in ps),
            "sessions_with_break": sum(1 for p in ps if p["breaks"]),
            "break_extra_cost_total": round(sum(p["break_extra_cost"] for p in ps), 2),
            "break_extra_share": (round(sum(p["break_extra_cost"] for p in ps) / cost, 3)
                                  if cost else 0),
            "gaps_over_ttl_total": sum(p["gaps_over_ttl"] for p in ps),
            "reread_ratio_med": _med([p["reread_ratio"] for p in ps]),
            "reads_med": _med([p["reads_total"] for p in ps]),
            "persisted_output_reads_total": sum(p["persisted_output_reads"] for p in ps),
            "gate_runs_med": _med([p["gate_runs"] for p in ps]),
            "gate_runs_total": sum(p["gate_runs"] for p in ps),
            "subagents_total": sum(p["subagents"] for p in ps),
            "orient_turns_med": _med([p["orient_turns"] for p in ps if p["first_write_turn"]]),
            "orient_cost_share_med": _med([p["orient_cost_share"] for p in ps
                                           if p["first_write_turn"]]),
            "tool_mix": dict(sum((Counter(p["tools"]) for p in ps), Counter())),
            "tool_chars": dict(sum((Counter(p["tool_result_chars"]) for p in ps), Counter())),
        }
    return out


def cross_session_reads(profiles: list[dict], top: int = 15) -> list[dict]:
    sessions_per_file = Counter()
    reads_per_file = Counter()
    for p in profiles:
        for f, c in p["files_read"].items():
            if "/tool-results/" in f:
                continue
            sessions_per_file[f] += 1
            reads_per_file[f] += c
    return [{"file": f, "sessions": s, "reads": reads_per_file[f]}
            for f, s in sessions_per_file.most_common(top)]


def fmt_table(agg: dict) -> str:
    cols = [("role", 24), ("sessions", 8), ("cost_total", 10), ("turns_med", 9),
            ("ctx_first_med", 13), ("ctx_mean_med", 12), ("ctx_max_med", 11),
            ("growth_med", 10), ("fixed_share_med", 11), ("own_output_share_med", 10),
            ("thinking_share_med", 10), ("last_quartile_share_med", 9),
            ("breaks_total", 7), ("break_extra_share", 9), ("gaps_over_ttl_total", 8),
            ("reread_ratio_med", 8), ("orient_turns_med", 8), ("orient_cost_share_med", 9)]
    head = ["role", "n", "cost$", "turns", "ctx1", "ctxmean", "ctxmax", "grow/t",
            "fixed%", "own%", "think%", "lastQ%", "brks", "brk$%", "gaps>ttl",
            "reread", "orient", "orient$%"]
    lines = [" ".join(h.ljust(w) for h, (_, w) in zip(head, cols, strict=True))]
    for role, r in agg.items():
        row = []
        for (k, w) in cols:
            v = role if k == "role" else r.get(k)
            if isinstance(v, float) and k.endswith(("share", "share_med", "ratio_med")):
                v = f"{v * 100:.0f}" if "ratio" not in k else f"{v:.2f}"
            row.append(str(v if v is not None else "-")[:w].ljust(w))
        lines.append(" ".join(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --breakdown: the aggregate analyses, as Markdown.
# ---------------------------------------------------------------------------

BREAKDOWN_ROLES = ("code-writer", "code-reviewer", "doc-writer", "plan-writer",
                   "consult", "test-agent", "subagent:Explore")
WRITER_ROLES = ("code-writer", "code-reviewer", "doc-writer")
TURN_CLASSES = ("dispatch", "edit", "gate", "commit", "record", "retry",
                "fumble", "wait", "git-inspect", "orient-read", "work-read",
                "think", "other")
BIG_SESSION_TURNS = 80
BIG_READ_CHARS = 20_000


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def _pc(x: float, total: float) -> str:
    return f"{x / total * 100:.1f}%" if total else "-"


def _n(x) -> str:
    return f"{x:,.0f}" if x is not None else "-"


def _pctile(xs, p: float):
    """Linear-interpolated percentile; p in [0, 1]."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _table(head, rows, right=()) -> list[str]:
    sep = ["---:" if h in right else "---" for h in head]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return out


def _headless(profiles: list[dict]) -> list[dict]:
    return [p for p in profiles if not p["role"].startswith("orchestrator:")]


def _by_role(profiles: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        out[p["role"]].append(p)
    return out


def _roles_by_cost(profiles: list[dict]) -> list[tuple[str, list[dict]]]:
    return sorted(_by_role(profiles).items(),
                  key=lambda kv: -sum(p["cost"] for p in kv[1]))


def _bd_totals(profiles: list[dict]) -> list[str]:
    total = sum(p["cost"] for p in profiles)
    tier = Counter()
    for p in profiles:
        tier.update(p["cost_tier"])
    lines = ["## 1. Totals", "",
             f"**{_usd(total)}** over **{len(profiles)}** sessions.", ""]
    lines += _table(["tier", "cost", "share of cost"],
                    [[k, _usd(tier.get(k, 0.0)), _pc(tier.get(k, 0.0), total)]
                     for k in ("input", "cache_read", "cache_write", "output")],
                    right={"cost", "share of cost"})
    lines += ["", "### Cost by role", ""]
    lines += _table(["role", "sessions", "cost", "share of cost"],
                    [[role, len(ps), _usd(sum(p["cost"] for p in ps)),
                      _pc(sum(p["cost"] for p in ps), total)]
                     for role, ps in _roles_by_cost(profiles)],
                    right={"sessions", "cost", "share of cost"})
    big = [p for p in profiles if p["turns"] >= BIG_SESSION_TURNS]
    big_cost = sum(p["cost"] for p in big)
    weighted_lq = sum(p["cost_last_quartile_share"] * p["cost"] for p in profiles)
    lines += ["",
              f"- Sessions of ≥{BIG_SESSION_TURNS} turns: **{len(big)}** "
              f"({_pc(len(big), len(profiles))} of sessions) carrying "
              f"**{_usd(big_cost)}** ({_pc(big_cost, total)} of cost)",
              f"- Cost-weighted last-quartile share: **{_pc(weighted_lq, total)}** "
              "— what the final quarter of each session's turns cost, weighted by session cost",
              ""]
    return lines


def _bd_processed(profiles: list[dict]) -> list[str]:
    total = sum(p["cost"] for p in profiles)
    processed = sum(p["processed_tokens"] for p in profiles)
    fixed = sum(p["ctx_first"] * p["turns"] for p in profiles)
    acc = processed - fixed
    num = den = 0.0
    for p in profiles:
        a = p["processed_tokens"] - p["ctx_first"] * p["turns"]
        share = p["own_output_share_of_accumulated"]
        if share is not None and a > 0:
            num += share * a
            den += a
    own = num / den if den else 0.0
    think = (sum(p["thinking_share_of_processed"] * p["processed_tokens"]
                 for p in profiles) / processed) if processed else 0.0
    think_cost = sum(p["thinking_read_cost"] for p in profiles)
    out_cost = sum(p["cost_tier"].get("output", 0.0) for p in profiles)
    lines = ["## 2. Processed-token composition", "",
             "*Processed* = Σ over turns of the whole prompt the model was shown "
             "(input + cache read + cache write) — the tokens the bill is computed on.", ""]
    lines += _table(["component", "tokens", "share of processed"],
                    [["processed (Σ ctx over turns)", _n(processed), "100.0%"],
                     ["fixed prefix (ctx₁ × turns)", _n(fixed), _pc(fixed, processed)],
                     ["accumulated (processed − fixed)", _n(acc), _pc(acc, processed)]],
                    right={"tokens", "share of processed"})
    lines += ["",
              f"- Own output as a share of the accumulated tokens: **{own * 100:.1f}%** "
              "— the session re-reading what it itself wrote, not tool results",
              f"- Thinking as a share of processed tokens (token-weighted): "
              f"**{think * 100:.1f}%**",
              f"- Cost of re-reading retained thinking: **{_usd(think_cost)}** "
              f"({_pc(think_cost, total)} of total cost)",
              f"- Output tier: {_usd(out_cost)} ({_pc(out_cost, total)}) — so "
              f"**effort-reachable = {(out_cost + think_cost) / total * 100:.1f}%** "
              "of total cost (output tier + the re-reading of retained thinking)",
              ""]
    return lines


def _bd_breaks(profiles: list[dict]) -> list[str]:
    def row(label, ps):
        cost = sum(p["cost"] for p in ps)
        extra = sum(p["break_extra_cost"] for p in ps)
        return [label, sum(p["breaks"] for p in ps),
                f"{sum(1 for p in ps if p['breaks'])}/{len(ps)}",
                _usd(extra), _pc(extra, cost)]

    hl = _headless(profiles)
    lines = ["## 3. Prefix breaks", "",
             "A break is a turn whose `cache_read` falls short of the previous prompt "
             f"by more than {BREAK_SLACK:,} tokens: the prefix was re-written at "
             f"{CACHE_WRITE_MULT}× instead of read at {CACHE_READ_MULT}×.", ""]
    lines += _table(["scope", "breaks", "sessions with ≥1", "extra cost", "% of that scope's cost"],
                    [row("all sessions", profiles), row("headless only", hl)],
                    right={"breaks", "extra cost", "% of that scope's cost"})
    lines += ["",
              f"- Gaps over the {TTL_S}s cache TTL, headless sessions: "
              f"**{sum(p['gaps_over_ttl'] for p in hl):,}** "
              f"(of which {sum(p['breaks_after_gap'] for p in hl):,} preceded a break)",
              "", "### Breaks by role", ""]
    lines += _table(["role", "breaks", "sessions with ≥1", "extra cost"],
                    [[role, sum(p["breaks"] for p in ps),
                      f"{sum(1 for p in ps if p['breaks'])}/{len(ps)}",
                      _usd(sum(p["break_extra_cost"] for p in ps))]
                     for role, ps in _roles_by_cost(profiles)
                     if sum(p["breaks"] for p in ps)],
                    right={"breaks", "extra cost"})
    return lines + [""]


def _bd_retention(profiles: list[dict]) -> list[str]:
    ratios = [e["ratio_out"] for p in profiles for e in p["retention_probe"]
              if e["ratio_out"] is not None]
    minus = [e["ratio_out_minus_think"] for p in profiles for e in p["retention_probe"]
             if e["ratio_out_minus_think"] is not None]
    lines = ["## 4. Thinking-retention probe", "",
             "Turns that followed a thinking-heavy turn whose tool results were tiny "
             "(<400 chars): the prompt growth divided by what the previous turn produced. "
             "`ratio_out ≈ 1` means the whole previous output — thinking included — came "
             "back in the next prompt; `ratio_out_minus_think ≈ 1` would mean the thinking "
             "was dropped and only the visible output was retained.", ""]

    def row(label, xs):
        return [label, f"{len(xs):,}"] + [
            f"{_pctile(xs, q):.2f}" if xs else "-" for q in (0.25, 0.5, 0.75)]

    lines += _table(["measure", "n", "p25", "median", "p75"],
                    [row("growth / prev output (ratio_out)", ratios),
                     row("growth / (prev output − thinking)", minus)],
                    right={"n", "p25", "median", "p75"})
    return lines + [""]


def _bd_first_turn(profiles: list[dict]) -> list[str]:
    total = sum(p["cost"] for p in profiles)
    rows = []
    cw_tokens = 0
    cw_cost = 0.0
    for role, ps in _roles_by_cost(profiles):
        crs = [p["trajectory"][0]["cr"] for p in ps if p["trajectory"]]
        cws = [p["trajectory"][0]["cw"] for p in ps if p["trajectory"]]
        rows.append([role, len(ps), _n(statistics.median(crs)), _n(statistics.median(cws))])
    for p in profiles:
        if not p["trajectory"]:
            continue
        cw = p["trajectory"][0]["cw"]
        cw_tokens += cw
        cw_cost += cw / 1e6 * PRICES.get(p["model"], {}).get("input", 0.0) * CACHE_WRITE_MULT
    lines = ["## 5. First-turn cache split by role", "",
             "What the opening prompt of a session was: read from a warm cache (`cr`) "
             "versus written into it at 1.25× (`cw`).", ""]
    lines += _table(["role", "sessions", "median cache_read", "median cache_write"], rows,
                    right={"sessions", "median cache_read", "median cache_write"})
    lines += ["",
              f"- All first-turn cache writes: **{_n(cw_tokens)} tokens**, "
              f"**{_usd(cw_cost)}** — {_pc(cw_cost, total)} of total cost", ""]
    return lines


def _bd_tools_per_turn(profiles: list[dict]) -> list[str]:
    rows = []
    for role, ps in _roles_by_cost(profiles):
        turns = [t for p in ps for t in p["trajectory"]]
        if not turns:
            continue
        tools = sum(len(t["tools"]) for t in turns)
        zero = sum(1 for t in turns if not t["tools"])
        multi = sum(1 for t in turns if len(t["tools"]) >= 2)
        per_session = [sum(len(t["tools"]) for t in p["trajectory"]) for p in ps]
        rows.append([role, len(ps), f"{len(turns):,}", f"{tools / len(turns):.2f}",
                     _pc(zero, len(turns)), _pc(multi, len(turns)),
                     _n(statistics.median(per_session))])
    lines = ["## 6. Tools per turn by role", ""]
    lines += _table(["role", "sessions", "turns", "tools/turn", "turns with 0 tools",
                     "turns with ≥2 tools", "median tool calls/session"], rows,
                    right={"sessions", "turns", "tools/turn", "turns with 0 tools",
                           "turns with ≥2 tools", "median tool calls/session"})
    return lines + [""]


def _size_row(label: str, sizes: list[int]) -> list:
    big = [s for s in sizes if s > BIG_READ_CHARS]
    return [label, f"{len(sizes):,}", _n(_pctile(sizes, 0.5)), _n(_pctile(sizes, 0.75)),
            _n(_pctile(sizes, 0.9)), _n(_pctile(sizes, 0.99)),
            _pc(len(big), len(sizes)), _pc(sum(big), sum(sizes))]


def _bd_tool_volume(profiles: list[dict]) -> list[str]:
    lines = ["## 7. Tool-result volume by class and role", "",
             "Every tool call classified — Bash by the command it ran, other tools by "
             "name — and totalled by the characters their results put into the prompt.", ""]
    by_role = _by_role(profiles)
    for role in BREAKDOWN_ROLES:
        ps = by_role.get(role) or []
        if not ps:
            continue
        classes: Counter = Counter()
        counts: Counter = Counter()
        for p in ps:
            for cls, (n, chars) in p["tool_classes"].items():
                classes[cls] += chars
                counts[cls] += n
        total_chars = sum(classes.values())
        lines += [f"### {role} — {len(ps)} sessions, {_n(total_chars)} result chars", ""]
        lines += _table(["class", "calls", "result chars", "% of role's result chars"],
                        [[cls, f"{counts[cls]:,}", _n(chars), _pc(chars, total_chars)]
                         for cls, chars in classes.most_common(8)],
                        right={"calls", "result chars", "% of role's result chars"})
        lines += [""]

    writers = [p for p in profiles if p["role"] in WRITER_ROLES]
    lines += ["### Result sizes for the reading classes", "",
              f"Over {', '.join(WRITER_ROLES)} sessions "
              f"({len(writers)} of them).", ""]
    lines += _table(["class", "calls", "p50", "p75", "p90", "p99",
                     f"% calls >{BIG_READ_CHARS // 1000}k", "% chars in those"],
                    [_size_row(cls, [s for p in writers
                                     for s in p["class_sizes"].get(cls, [])])
                     for cls in ("Read", "cat/sed(read)", "grep")],
                    right={"calls", "p50", "p75", "p90", "p99",
                           f"% calls >{BIG_READ_CHARS // 1000}k", "% chars in those"})
    gate = [s for p in profiles for s in p["class_sizes"].get("gate", [])]
    lines += ["",
              f"- Gate output over every gate call in every session: n={len(gate):,}, "
              f"p50 **{_n(_pctile(gate, 0.5))}** chars, p90 **{_n(_pctile(gate, 0.9))}**, "
              f"max **{_n(max(gate) if gate else 0)}**", ""]
    return lines


def _bd_orientation(profiles: list[dict]) -> list[str]:
    all_cw = [p for p in profiles if p["role"] == "code-writer"]
    ps = [p for p in all_cw if p["first_write_turn"]]
    calls: Counter = Counter()
    sessions: Counter = Counter()
    for p in ps:
        calls.update(p["orient_calls"])
        sessions.update(set(p["orient_calls"]))
    turns = [p["orient_turns"] for p in ps]
    shares = [p["orient_cost_share"] for p in ps]
    ctxs = [p["ctx_at_first_write"] for p in ps if p["ctx_at_first_write"]]
    lines = ["## 8. Orientation-phase reads (code-writer)", "",
             f"Every tool call a code-writer made before its first edit, over the "
             f"{len(ps)} of {len(all_cw)} code-writer sessions that edited anything.", ""]
    lines += _table(["call (generalised)", "calls", "sessions"],
                    [[k, n, sessions[k]] for k, n in calls.most_common(25)],
                    right={"calls", "sessions"})
    lines += ["",
              f"- Orientation turns: median **{_n(_pctile(turns, 0.5))}**, "
              f"p75 **{_n(_pctile(turns, 0.75))}**",
              f"- Orientation share of session cost: median "
              f"**{(_pctile(shares, 0.5) or 0) * 100:.1f}%**",
              f"- Context at the first edit: median **{_n(_pctile(ctxs, 0.5))}** tokens",
              f"- Ran a gate command before the first edit: "
              f"**{sum(1 for p in ps if p['orient_gate'])}** of {len(ps)} sessions", ""]
    return lines


def _bd_turn_classes(profiles: list[dict]) -> list[str]:
    """§13 — what the turns do. The bill is per turn, so this is the table the
    cost model is short of: every turn placed in one class, cost-weighted."""
    hl = _headless(profiles)
    tot_turns = sum(p["turns"] for p in hl)
    tot_cost = sum(p["cost"] for p in hl)
    per_turn = tot_cost / tot_turns if tot_turns else 0
    lines = [
        "## 13. What the turns do", "",
        "A turn is one model invocation — the unit the bill is charged in, and at "
        f"**${per_turn:.3f}** each nearly flat across roles. Every turn is placed in "
        "exactly one class by what its tool calls did, first match in this order: "
        "`dispatch` · `edit` · `gate` · `commit` · `record` · `retry` · `fumble` · "
        "`wait` · `git-inspect` · `orient-read` · `work-read` · `think` · `other`. "
        "`edit` and `record` are the same op split by what it wrote (a done-record, "
        "a verdict or a close-out entry is a `record`; a turn that writes both is an "
        "`edit`); `orient-read` and `work-read` are the same op split at the first "
        "edit of the session.", "",
        "Three things this section sees that the ones above do not. **Bash edits**: a "
        "heredoc'd python rewrite, `sed -i` or a `>` redirection is an edit, so the "
        "orientation boundary is the first *edit*, not the first `Edit` tool call. "
        "**Ops inside one command**: `sed -n … && sed -n …` is two reads, so `reads/turn` "
        "counts the batching that `tools/turn` cannot see. **Failure**: the loop's "
        "commands end in `2>&1`, so a failed call is not flagged `is_error` — it is "
        "recognised from its output (`usage:`, `command not found`, `No such file`).", "",
        "`retry` and `fumble` are **lower bounds**: the class order means a retried "
        "edit counts as `edit` and a re-run gate as `gate`.", "",
    ]

    # --- 13.1 every headless session ---
    turns_by_cls: Counter = Counter()
    cost_by_cls: dict[str, float] = defaultdict(float)
    reads_by_cls: dict[str, list[int]] = defaultdict(list)
    for p in hl:
        for k, v in p["turn_class_turns"].items():
            turns_by_cls[k] += v
        for k, v in p["turn_class_cost"].items():
            cost_by_cls[k] += v
        for tr in p["trajectory"]:
            reads_by_cls[tr["cls"]].append(tr["reads"])
    lines += [f"### Every headless session — {len(hl)} sessions, {tot_turns:,} turns, "
              f"{_usd(tot_cost)}", "",
              "Orchestrator sessions (the operator's own, human-paced) are excluded "
              "here and included in the per-role tables below.", ""]
    lines += _table(["class", "turns", "% of turns", "cost", "% of cost", "reads/turn"],
                    [[c, f"{turns_by_cls[c]:,}", _pc(turns_by_cls[c], tot_turns),
                      _usd(cost_by_cls[c]), _pc(cost_by_cls[c], tot_cost),
                      f"{statistics.fmean(reads_by_cls[c]):.2f}" if reads_by_cls[c] else "-"]
                     for c in TURN_CLASSES if turns_by_cls[c]],
                    right={"turns", "% of turns", "cost", "% of cost", "reads/turn"})
    lines += [""]

    # --- 13.2 class by role ---
    lines += ["### Class by role", "",
              "Ordered by cost. Roles under 200 turns in this corpus "
              "(dev:rebase-agent, dev:test-fixer) are left out of this table and the "
              "next; they are in the totals above.", ""]
    by_role = _by_role(profiles)
    for role, _ps in _roles_by_cost(profiles):
        ps = by_role[role]
        rt = sum(p["turns"] for p in ps)
        rc = sum(p["cost"] for p in ps)
        if rt < 200:
            continue
        tc: Counter = Counter()
        cc: dict[str, float] = defaultdict(float)
        for p in ps:
            for k, v in p["turn_class_turns"].items():
                tc[k] += v
            for k, v in p["turn_class_cost"].items():
                cc[k] += v
        lines += [f"**{role}** — {len(ps)} sessions, {rt:,} turns, {_usd(rc)} "
                  f"(${rc / rt:.3f}/turn)", ""]
        lines += _table(["class", "turns", "% of role's turns", "cost",
                         "% of role's cost"],
                        [[c, f"{tc[c]:,}", _pc(tc[c], rt), _usd(cc[c]), _pc(cc[c], rc)]
                         for c in TURN_CLASSES if tc[c]],
                        right={"turns", "% of role's turns", "cost",
                               "% of role's cost"})
        lines += [""]

    # --- 13.3 per-session medians ---
    lines += ["### Per-session medians", "",
              "`reads/turn` counts read ops including the ones chained inside one "
              "Bash command; `reads/reading turn` is the same over the turns that read "
              "at all — the batching metric proper, 1.00 if every read is its own turn. "
              "`batchable` is the run-folding upper bound (consecutive read-only turns, "
              "Σ(run − 1)); `strict` keeps only those whose target file was already "
              "named in context before the previous turn's result, so the read cannot "
              "have depended on what it followed.", ""]
    rows = []
    for role, ps in _roles_by_cost(profiles):
        if sum(p["turns"] for p in ps) < 200:
            continue
        rows.append([
            role, len(ps), _n(_pctile([p["turns"] for p in ps], 0.5)),
            f"{_pctile([p['tools_per_turn'] for p in ps], 0.5):.2f}",
            f"{_pctile([p['reads_per_turn'] for p in ps], 0.5):.2f}",
            f"{_pctile([p['reads_per_read_turn'] for p in ps], 0.5):.2f}",
            _n(_pctile([p["retry_turns"] + p["fumble_turns"] for p in ps], 0.5)),
            _n(_pctile([p["batchable_turns"] for p in ps], 0.5)),
            _n(_pctile([p["batchable_strict_turns"] for p in ps], 0.5)),
        ])
    head = ["role", "sessions", "turns", "tools/turn", "reads/turn",
            "reads/reading turn", "retry+fumble", "batchable", "batchable (strict)"]
    lines += _table(head, rows, right=set(head[1:]))
    lines += [""]

    # --- 13.4 the fumbles, and what `other` is ---
    fk: Counter = Counter()
    for p in hl:
        fk.update(p["fumble_keys"])
    n_fumble = sum(p["turn_class_turns"].get("fumble", 0)
                   + p["turn_class_turns"].get("retry", 0) for p in hl)
    lines += ["### What is fumbled and retried", "",
              f"The interface each of the {n_fumble:,} `fumble` and `retry` turns was "
              "spent on — a `--help`, a rejected invocation, or the re-issue that "
              "followed one. This is T3b's work list.", ""]
    lines += _table(["interface", "turns"],
                    [[k, v] for k, v in fk.most_common(15)], right={"turns"})
    oo: Counter = Counter()
    for p in hl:
        oo.update(p["other_ops"])
    lines += ["", "`other` is the residual — a turn that neither read, edited, gated, "
              "committed, recorded nor waited. What those turns ran:", ""]
    lines += _table(["op", "calls"], [[k, v] for k, v in oo.most_common(12)],
                    right={"calls"})
    lines += [""]

    # --- 13.5 the avoidable share, per slice ---
    lines += ["### The avoidable share, per slice", "",
              "`avoidable = retry + fumble + batchable(strict)` — the turns a fix to "
              "the tooling or a batched read would remove, priced at the slice's own "
              "cost per turn. It is a floor, not a target: it counts no orientation "
              "turn a digest would remove (T4) and no doc-writer session a split would "
              "bound (T6).", ""]
    per_slice: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0, 0, 0])
    for p in profiles:
        r = per_slice[p["slice"]]
        r[0] += p["turns"]
        r[1] += p["cost"]
        r[2] += p["retry_turns"] + p["fumble_turns"]
        r[3] += p["batchable_strict_turns"]
        r[4] += p["batchable_turns"]
    rows = []
    for name, (t, c, rf, bs, _bu) in sorted(per_slice.items()):
        av = rf + bs
        rows.append([name, f"{t:,}", _usd(c), f"{rf:,}", f"{bs:,}",
                     f"{av:,}", _usd(av * c / t if t else 0), _pc(av, t)])
    tt = sum(v[0] for v in per_slice.values())
    tcst = sum(v[1] for v in per_slice.values())
    trf = sum(v[2] for v in per_slice.values())
    tbs = sum(v[3] for v in per_slice.values())
    tbu = sum(v[4] for v in per_slice.values())
    rows.append(["**all**", f"**{tt:,}**", f"**{_usd(tcst)}**", f"**{trf:,}**",
                 f"**{tbs:,}**", f"**{trf + tbs:,}**",
                 f"**{_usd((trf + tbs) * tcst / tt)}**", f"**{_pc(trf + tbs, tt)}**"])
    head = ["slice", "turns", "cost", "retry+fumble", "batchable (strict)",
            "avoidable turns", "avoidable $", "% of turns"]
    lines += _table(head, rows, right=set(head[1:]))
    lines += ["",
              f"- Perfect batching (the upper bound, every read-only run folded into "
              f"one turn) would remove **{tbu:,}** turns — {_pc(tbu, tt)} of them, "
              f"{_usd(tbu * tcst / tt)}. The strict count is {_pc(tbs, tbu)} of that.",
              f"- Per slice: median **{_n(_pctile([v[0] for v in per_slice.values()], 0.5))}** "
              f"turns, {_usd(_pctile([v[1] for v in per_slice.values()], 0.5))}, of which "
              f"**{_n(_pctile([v[2] + v[3] for v in per_slice.values()], 0.5))}** turns "
              "avoidable.", ""]

    # --- 13.6 orientation, re-measured ---
    cw = [p for p in profiles if p["role"] == "code-writer"]
    fw = [p for p in cw if p["first_write_turn"]]
    fe = [p for p in cw if p["first_edit_turn"]]
    gate_any = sum(1 for p in cw if p["gate_runs"])
    gate_first = sum(1 for p in fe if any(tr["cls"] == "gate" and tr["i"] < p["first_edit_turn"]
                                          for tr in p["trajectory"]))
    lines += ["### Orientation, re-measured against the first *edit*", "",
              f"§8 ends orientation at the first `Edit`/`Write` tool call, which "
              f"{len(fw)} of {len(cw)} code-writer sessions ever make; counting the "
              f"edits done through Bash, {len(fe)} of {len(cw)} do, and they reach the "
              "first one sooner.", "",
              f"- Turns before the first `Edit`/`Write`: median "
              f"**{_n(_pctile([p['first_write_turn'] for p in fw], 0.5))}** "
              f"(n={len(fw)}); before the first edit of any kind: median "
              f"**{_n(_pctile([p['first_edit_turn'] for p in fe], 0.5))}** (n={len(fe)}).",
              f"- Ran a gate at all: **{gate_any}** of {len(cw)} code-writer sessions. "
              f"Ran one *before* their first edit: **{gate_first}** of {len(fe)}. "
              "interventions-2.md §1's \"136/184 writers run the gate before editing\" "
              "matches neither and no other cut of this corpus — the line is wrong, and "
              "the two numbers here replace it.", ""]

    # --- 13.7 what it decides ---
    def _share(roles, field):
        ps = [p for p in profiles if p["role"] in roles]
        t = sum(p["turns"] for p in ps)
        return (sum(p[field] if isinstance(field, str) else field(p) for p in ps) / t
                if t else 0)
    w = WRITER_ROLES
    rf_share = _share(w, lambda p: p["retry_turns"] + p["fumble_turns"])
    or_share = _share(w, lambda p: p["turn_class_turns"].get("orient-read", 0))
    bs_share = _share(w, lambda p: p["batchable_strict_turns"])
    tops = []
    for role in BREAKDOWN_ROLES:
        ps = by_role.get(role) or []
        tc = Counter()
        for pr in ps:
            tc.update(pr["turn_class_turns"])
        if not tc:
            continue
        cls, k = tc.most_common(1)[0]
        tops.append(f"{role} {cls} {k / sum(tc.values()) * 100:.0f}%")
    n_or = sum(1 for x in tops if " orient-read " in x)
    lines += ["### What this decides (turns-plan.md T1)", "",
              f"Over {', '.join(w)} sessions, against the plan's bars:", "",
              f"- `fumble + retry` **{rf_share * 100:.1f}%** of writer turns "
              f"(bar: ≥ 5% → T3b carries weight) — {'above' if rf_share >= .05 else 'below'}.",
              f"- `orient-read` **{or_share * 100:.1f}%** of writer turns, and the largest "
              f"class in {n_or} of the {len(tops)} producer roles (bar: largest class → T4). "
              f"Largest class per role: {'; '.join(tops)}.",
              f"- `batchable(strict)` **{bs_share * 100:.1f}%** of writer turns "
              f"(bar: ≥ 15% → T5 earns its own A/B) — "
              f"{'above' if bs_share >= .15 else 'below'}.", ""]
    return lines

def _bd_cross_reads(profiles: list[dict], top: int = 20) -> list[str]:
    sessions: Counter = Counter()
    reads: Counter = Counter()
    chars: Counter = Counter()
    for p in profiles:
        seen = set()
        for f, c in p["files_read"].items():
            if "/tool-results/" in f:
                continue
            g = generalise_path(f)
            reads[g] += c
            chars[g] += p["files_read_chars"].get(f, 0)
            seen.add(g)
        for g in seen:
            sessions[g] += 1
    lines = ["## 9. Cross-session re-reads", "",
             f"The files the most sessions opened, over all {len(profiles)} sessions "
             "(slice-specific path segments generalised; persisted tool results skipped).", ""]
    lines += _table(["file", "sessions", "reads", "chars"],
                    [[f, s, reads[f], _n(chars[f])] for f, s in sessions.most_common(top)],
                    right={"sessions", "reads", "chars"})
    return lines + [""]


def _bd_subagent_overlap(profiles: list[dict]) -> list[str]:
    subs: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        if p.get("parent_session"):
            subs[p["parent_session"]].append(p)
    rows = []
    for role, ps in _roles_by_cost(profiles):
        parents = [p for p in ps if not p["role"].startswith("subagent:") and p["subagents"]]
        if not parents:
            continue
        overlap = after = 0
        counts = []
        for p in parents:
            names = set()
            for s in subs.get(p["session"], []):
                names.update(s["read_paths"])
            reads = [str(Path(x)) for x in p["reads_after_dispatch"]]
            counts.append(len(reads))
            after += len(reads)
            overlap += sum(1 for b in reads if b in names)
        rows.append([role, len(parents),
                     _n(statistics.median([p["subagents"] for p in parents])),
                     _n(statistics.median(counts)),
                     f"{overlap:,}/{after:,}", _pc(overlap, after)])
    lines = ["## 10. Sub-agent overlap", "",
             "For sessions that dispatched a sub-agent: the files the parent read *after* "
             "dispatching (Read, plus `cat`/`sed -n` of a source-ish path), and how many of "
             "those reads hit a file (same full path) one of its own sub-agents had already "
             "read.", ""]
    lines += _table(["parent role", "sessions with ≥1 sub-agent", "median sub-agents",
                     "median parent reads after dispatch", "overlap", "% overlap"], rows,
                    right={"sessions with ≥1 sub-agent", "median sub-agents",
                           "median parent reads after dispatch", "overlap", "% overlap"})
    return lines + [""]


def _bd_explore(profiles: list[dict]) -> list[str]:
    ex = [p for p in profiles if p["role"] == "subagent:Explore"]
    lines = ["## 11. Explore sub-agents", ""]
    if not ex:
        return lines + ["None in this corpus.", ""]
    cost = sum(p["cost"] for p in ex)
    out_cost = sum(p["cost_tier"].get("output", 0.0) for p in ex)
    total = sum(p["cost"] for p in profiles)
    sonnet = PRICES["claude-sonnet-5"]
    repriced = 0.0
    opus_tokens = 0
    for p in ex:
        for model, tok in p["tok_by_model"].items():
            base = sonnet if model.startswith("claude-opus") else PRICES.get(model, sonnet)
            if model.startswith("claude-opus"):
                opus_tokens += sum(tok.values())
            repriced += (tok["input"] / 1e6 * base["input"]
                         + tok["cache_read"] / 1e6 * base["input"] * CACHE_READ_MULT
                         + tok["cache_write"] / 1e6 * base["input"] * CACHE_WRITE_MULT
                         + tok["output"] / 1e6 * base["output"])
    models = Counter(p["model"] for p in ex)
    lines += [f"- **{len(ex)}** Explore sub-agents, **{_usd(cost)}** "
              f"({_pc(cost, total)} of total cost)",
              f"- Models: {', '.join(f'{m} ×{n}' for m, n in models.most_common())}",
              f"- Output tier: {_usd(out_cost)} ({_pc(out_cost, cost)} of their cost)",
              f"- Priced at Sonnet rates for the {_n(opus_tokens)} Opus tokens: "
              f"**{_usd(repriced)}** — {_usd(cost - repriced)} less", ""]
    return lines


def _bd_artefacts(slice_dirs: list[Path]) -> list[str]:
    names = ("plan.md", "slice.md", "verification.json", "close-out.md")
    sizes: dict[str, list[int]] = {n: [] for n in names}
    for sd in slice_dirs:
        for name in names:
            f = sd / name
            if f.is_file():
                sizes[name].append(f.stat().st_size)
    lines = ["## 12. Artefact sizes", "",
             f"Bytes on disk, over the {len(slice_dirs)} slice directories profiled.", ""]
    lines += _table(["file", "slices", "median", "p75", "max"],
                    [[name, len(v), _n(_pctile(v, 0.5)), _n(_pctile(v, 0.75)),
                      _n(max(v) if v else 0)] for name, v in sizes.items()],
                    right={"slices", "median", "p75", "max"})
    return lines + [""]


def breakdown(profiles: list[dict], slice_dirs: list[Path]) -> str:
    """Every aggregate analysis, as one Markdown document."""
    lines = ["# Breakdown", ""]
    lines += _bd_totals(profiles)
    lines += _bd_processed(profiles)
    lines += _bd_breaks(profiles)
    lines += _bd_retention(profiles)
    lines += _bd_first_turn(profiles)
    lines += _bd_tools_per_turn(profiles)
    lines += _bd_tool_volume(profiles)
    lines += _bd_orientation(profiles)
    lines += _bd_cross_reads(profiles)
    lines += _bd_subagent_overlap(profiles)
    lines += _bd_explore(profiles)
    lines += _bd_artefacts(slice_dirs)
    lines += _bd_turn_classes(profiles)
    return "\n".join(lines).rstrip()


def _report_header(argv: list[str], profiles: list[dict], slice_dirs: list[Path]) -> str:
    """The generated preamble: how this file was made, and over what."""
    groups: dict[str, list[str]] = defaultdict(list)
    flags: list[str] = []
    for a in argv:
        p = Path(a)
        if not a.startswith("-") and p.is_dir():
            groups[str(p.parent)].append(p.name)
        else:
            flags.append(a)
    cmd = ["python3 docs/research/tools/context_profile.py \\"]
    for parent, dirs in groups.items():
        nums = [d.split("_")[0] for d in dirs]
        if all(x.isdigit() for x in nums):
            glob = (f"{{{min(nums)}..{max(nums)}}}_*" if len(nums) > 8
                    else "{" + ",".join(nums) + "}_*")
        else:
            glob = "*"
        cmd.append(f"        {parent}/{glob} \\")
    cmd.append("        " + " ".join(flags))
    sources = ", ".join(f"{len(v)} from {Path(k).parents[1].name}"
                        for k, v in groups.items())
    return "\n".join([
        f"# Context profile — {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "Generated by `docs/research/tools/context_profile.py` — regenerate it, "
        "do not edit it.",
        "",
        "Command (the slice arguments are shown as globs, not expanded):",
        "",
        "```",
        *cmd,
        "```",
        "",
        f"**{len(profiles)} sessions** over **{len(slice_dirs)} slices** ({sources}).",
        "", "---", "",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slices", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, help="write every profile + aggregates here")
    ap.add_argument("--sessions", action="store_true", help="print one line per session")
    ap.add_argument("--role", help="restrict the session listing to one role")
    ap.add_argument("--what-if", action="store_true",
                    help="print the cut-the-session and expire-tool-results models per role")
    ap.add_argument("--breakdown", action="store_true",
                    help="print the aggregate analyses (cost, context, tools, reads) as Markdown")
    ap.add_argument("--report", type=Path,
                    help="write everything printed to this file, under a generated header")
    args = ap.parse_args(argv)

    out: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        out.append(line)

    profiles: list[dict] = []
    per_slice_reads: dict[str, list[dict]] = {}
    slice_dirs: list[Path] = []
    for sd in args.slices:
        try:
            convs, warnings = slice_cost.collect(sd)
        except FileNotFoundError as e:
            print(f"skip {sd}: {e}", file=sys.stderr)
            continue
        for w in warnings:
            print(f"[{sd.name}] {w}", file=sys.stderr)
        slice_profiles = []
        for c in convs:
            rep = replay(c.transcript)
            p = profile(c, rep)
            if not p:
                continue
            p["slice"] = sd.name
            slice_profiles.append(p)
        per_slice_reads[sd.name] = cross_session_reads(slice_profiles)
        slice_dirs.append(sd)
        profiles.extend(slice_profiles)

    agg = aggregate(profiles)
    emit(f"# {len(profiles)} sessions over {len(per_slice_reads)} slices\n")
    emit(fmt_table(agg))
    if args.sessions:
        emit()
        for p in sorted(profiles, key=lambda p: -p["cost"]):
            if args.role and p["role"] != args.role:
                continue
            emit(f"{p['slice'][:28]:28s} {p['role'][:22]:22s} P{str(p['phase']):4s} r{p['round']} "
                 f"${p['cost']:6.2f} turns={p['turns']:3d} ctx1={p['ctx_first']:6d} "
                 f"max={p['ctx_max']:7d} brk={p['breaks']} gaps={p['gaps_over_ttl']} "
                 f"reread={p['reread_ratio']:.2f} orient={p['orient_turns']} "
                 f"think%={p['thinking_share_of_processed'] * 100:.0f}")
    if args.what_if:
        emit("\n# what-if: best single cut (saving as % of role cost, at 20k/40k/60k "
             "re-orientation tokens;\n#   sess>5% = sessions where a cut at 40k saves >5%) "
             "and expiring tool results older than 20/40 turns\n")
        emit(what_if_table(profiles))
    if args.breakdown:
        emit()
        emit(breakdown(profiles, slice_dirs))
    if args.report:
        header = _report_header(sys.argv[1:] if argv is None else list(argv),
                                profiles, slice_dirs)
        args.report.write_text(header + "\n".join(out) + "\n")
        print(f"\nwrote {args.report}")
    if args.json:
        args.json.write_text(json.dumps({
            "profiles": profiles, "by_role": agg,
            "cross_session_reads": per_slice_reads}, indent=1, default=str))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
