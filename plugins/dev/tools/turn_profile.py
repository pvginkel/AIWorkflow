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

`edit` and `record` are the same op split by what it wrote (a done-record, a
verdict or a close-out entry is a `record`; a turn that writes both is an
`edit`); `orient-read` and `work-read` are the same op split at the session's
first edit — counting the edits made through the shell (a heredoc'd python
rewrite, `sed -i`, a `>` redirection), which is how a session spawned with
--dangerously-skip-permissions is told to work, and which no tool name reveals.
`retry` and `fumble` are lower bounds: the order means a retried edit counts as
an `edit` and a re-run gate as a `gate`. Failure is read from a result's text
(`usage:`, `command not found`, `No such file`) as well as its `is_error` flag,
since the loop's commands end in `2>&1` and fail with exit 0.

`analyse(replay(path), cost_for)` is the whole interface: it returns the turns,
their classes, their per-turn cost and one `metrics` dict — the per-session
figures [slice_cost.py](slice_cost.py) aggregates per role into a run's turn
table. Nothing here reads a slice directory or knows what a role is; the caller
supplies the transcript and the pricing function, so this module prices nothing
itself and duplicates no price.

Read by `slice_cost.py` (the `turns` table and the `turns` block it writes into
state.json) and by `docs/research/tools/context_profile.py`, which builds the
research-only analyses on top of the same replay. Stdlib-only, and not a
command: it has no `main()`.
"""

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

TTL_S = 300           # the loop forces the 5-minute cache TTL
BREAK_SLACK = 2_000   # tokens of cache_read shortfall tolerated before we call a break
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TURN_CLASSES = ("dispatch", "edit", "gate", "commit", "record", "retry",
                "fumble", "wait", "git-inspect", "orient-read", "work-read",
                "think", "other")


# ---------------------------------------------------------------------------
# Tool-call classification — one call at a time, Bash by what it runs.
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
READ_SUFFIXES = ("py", "go", "md", "ts", "yaml", "json")
BASH_READ_RE = re.compile(r"\bcat\b|\bsed -n\b")
BASH_PATH_RE = re.compile(r"[\w./@~+-]+\.(?:" + "|".join(READ_SUFFIXES) + r")\b")


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


# ---------------------------------------------------------------------------
# Per-turn classification. A turn is one op-set: every tool call it made, and —
# because a headless session is told to work through Bash — every `;`/`&&`/`||`
# -separated step inside each Bash command. Heredoc bodies are data, not shell,
# so they are stripped before a command is split (a python script that rewrites
# a file is one edit, not five steps).
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


# ---------------------------------------------------------------------------
# Transcript replay. The stream-json file logs each assistant message several
# times; a turn is one message id, with the tool results that followed it.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Per-session metrics — what a caller aggregates.
# ---------------------------------------------------------------------------


def first_write_turn(turns: list[dict]) -> int | None:
    """The turn of the session's first write *tool* call."""
    for t in turns:
        if any(rec["name"] in WRITE_TOOLS for rec in t["tools"]):
            return t["i"]
    return None


def first_edit_turn(turns: list[dict]) -> int | None:
    """The turn of the session's first edit — where orientation ends. Wider
    than first_write_turn: it also sees the edits done through the shell, which
    for some roles is most of them, and it ignores a turn that only wrote a
    record (a done-record, a verdict, a close-out entry)."""
    for t in turns:
        ops, targets, _ = turn_ops(t)
        if "edit" in ops and not (targets and all(_is_record_path(x) for x in targets)):
            return t["i"]
    return None


def turn_tier_cost(t: dict, cost_for) -> dict[str, float]:
    """One turn's cost, split by the tier each token was billed at. `cost_for`
    is slice_cost.cost_for — prices live there, and only there."""
    return {
        "input": cost_for(t["model"], {"input": t["input"]}),
        "cache_read": cost_for(t["model"], {"cache_read": t["cr"]}),
        "cache_write": cost_for(t["model"], {"cache_write": t["cw"]}),
        "output": cost_for(t["model"], {"output": t["out"]}),
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
            breaks.append({
                "turn": cur["i"], "shortfall": shortfall, "gap_s": round(gap),
                "extra_cost": (cost_for(cur["model"], {"cache_write": shortfall})
                               - cost_for(cur["model"], {"cache_read": shortfall})),
            })
    return breaks, gaps_over_ttl


def analyse(rep: dict, cost_for) -> dict:
    """One replayed transcript -> {turns, classes, turn_cost, breaks, metrics}.

    `classes` and `turn_cost` are per turn and index-aligned with `turns`;
    `metrics` is the per-session block a caller aggregates (and the research
    profiler extends). An empty transcript returns {}.
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
    fe = first_edit_turn(turns)
    classes = classify_turns(turns, fe)
    cls_turns: Counter = Counter(r["cls"] for r in classes)
    cls_cost: dict[str, float] = defaultdict(float)
    for r, c in zip(classes, turn_cost, strict=True):
        cls_cost[r["cls"]] += c
    reads = [r["reads"] for r in classes]
    batchable = sum(1 for r in classes if r.get("batchable"))
    batchable_strict = sum(1 for r in classes if r.get("batchable_strict"))
    avoidable = cls_turns["retry"] + cls_turns["fumble"] + batchable_strict

    orient_turns = (fw - 1) if fw else n
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
