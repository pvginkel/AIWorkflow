#!/usr/bin/env python3
"""Run loop — drives a slice's phased plan through the dev loop.

The Markdown plan is the queue; this driver is its bookkeeper (see
${CLAUDE_PLUGIN_ROOT}/docs/run-loop.md — the canonical contract). The plan
(<slice>/plan.md) holds phases as `### P<id> — <title>` headings, each opening
with a `Target:` line naming a `kc project list` component, a sibling repo, or
a GitHub repo the driver clones into the scratch root (`github:<owner>/<repo>`).
Document order is authoritative; ids are labels. Per unfinished phase, in
order: fetch the target repo (nothing else in a run refreshes a
remote-tracking ref, so an unfetched clone dates an agent's read of
`origin/<base>` to the day it was cloned) and fast-forward a base with no
commits of its own → branch → executor session (fresh code-writer) →
deterministic gate (red spawns a fresh executor fix round, capped; the
writer's own green run of it, through `gate`, stands in for it on the tree it
ran on) → code-reviewer loop (round 1's fix is automatic; from round 2 a
consult funds each further round against a bar that rises per round;
backstop cap) → gate-checked merge → the driver stamps `✅ DONE <date>` on
the phase heading. Only the driver stamps.

After the last phase the driver runs the loop-tail gate sweep — `kc project
lint` + `build` + `test`, per component, across every touched repo with a kc
manifest — and the commit-stamped report rides the loop-tail dispatches as
deterministic fact, under one principle: a branch whose gates are red is not
pushed, so a red tree is decided on at the consult (fixing phase or bail),
never discovered at push time. Then a completion consult (may append phases
— the loop picks them up), then the test phase ("read the
slice-testing-strategy doc and execute" — the driver holds the devlock;
under that hold pushing and rolling dev for verification is pre-authorized,
and a clean pass that left any repo the slice touched behind its origin is
nudged, capped, then bails), then the doc phase ("read the slice-doc-plan
doc and execute", diff-based, single writer, gated by the driver's own
lint+build+test sweep) — and between its writer and that sweep the wrap-up:
one `dev:wrap-up` session on what the close-out report's table gave it, its
commits on branches of its own, gated and landed with the doc phase or left
out whole, never a reason to stop the run (a project with no doc phase runs
it all the same). Phases appended by the consult or the test phase
re-enter the loop through a generation bar: the first generation appends
only work the plan owes and no phase delivered, the second blocking work
only, a third pending generation bails to the operator.

The driver's part in the slice's close-out report (<slice>/close-out.json,
the store, and the close-out.md rendered from it —
${CLAUDE_PLUGIN_ROOT}/docs/close-out.md): create it if the plan loop did
not, name it and close_out.py (the only way to write to it) in every
dispatch, enter refuted findings and funding-consult merges through that
tool, hand the completion consult the live entries owed before the push
(close_out.owed_before_push) and, where a test phase runs, those to fix
before it (close_out.owed_before_test), dispatch the wrap-up, render it
before the doc phase, after the wrap-up, at every bail and at completion,
stamp the run header at completion, and commit the store before every
dispatch that finds it changed, so a role's commit of it holds only its own
entries. A close-out.md edited by hand where a render would drop the edit
stops the run with an operator question (`report_edited`) — checked before
every dispatch, and met by any driver write mid-run; at a bail, in the
wrap-up and at completion a refused write is logged.

The plan doc is writable by every agent in the loop — deliberately. The
driver's job is keeping the shared doc parseable: a parse error, a vanished
phase, or a missing/unknown Target is nudged back to the session that
produced it ("fix the plan doc"), never treated as fatal while a session can
fix it. Bails are errors (exit 3) and operator questions (exit 4) only.

Every spawned agent must end by writing the verdict JSON file named in its
dispatch prompt and leave the worktree committed; a session that misses
either gets one resume-nudge, after which a missing verdict counts as
`blocked` and an uncommitted tree bails. A session the account's
session-limit window killed is not an agent outcome at all: the driver waits
out the stated reset and redispatches the same round.

Execution state lives in <slice>/state.json (written atomically; the driver
is its only writer): known phase ids, per-phase rounds, the bail-out and
appended-phase records, per-session transcript paths. Session outputs land
in <slice>/phases/P<id>/ (review docs, gate logs, verdicts); executor inputs
come from plan.md, never from copies. A phase whose Target is a repo kc
marks `shared` — the specs repo, which holds that whole record, is one —
works in a linked worktree of its own under the scratch root, and the shared
checkout never leaves its base (`_ensure_worktree`, `_merge_shared`).

All driver and session output goes to <slice>/log.txt (tail -f to watch);
stdout carries the log-file line plus one terse timestamped line per major
transition (each job start, each phase merged, the close-out summary) so a
watching caller can follow progress cheaply; -v/--verbose echoes the full
log there too.

`run --detach` takes the driver out of the launching shell — double fork,
new session — because a caller's background task is killed at its own cap
and a slice outlives it. The parent returns once the driver holds run.lock
and is past its refusals (a refusal comes back as the parent's own exit 2,
with the message), printing the driver's pid and the `wait` command that
follows it; from then on the driver's stdout is gone and its stderr goes to
log.txt. Its exit code goes to disk instead: every run that got that far
records `exit: {code, ts}` in state.json as its last write, and a --resume
clears it — so a run with no `exit` and no live driver was killed from
outside. `wait` blocks on the run.lock flock (liveness is the lock, never
the pid) for at most --for seconds and reports the run's state with the
driver's log lines since --from; `stop` SIGINTs the driver — its
KeyboardInterrupt path, the same as Ctrl-C on an attached run. run.lock's
note names the driver's KubeCoder environment, host and pid, with a
heartbeat rewritten every minute while it holds the lock; state.json's
`driver` records the same, and `status` prints it beside the lock's
liveness — a pod's `ps` cannot see a driver in another environment.

Usage:
    run_loop.py run <slice-dir> [--resume] [--detach] [--verbose] [--dry-run]
    run_loop.py wait <slice-dir> [--for SECONDS] [--from OFFSET]
    run_loop.py stop <slice-dir>
    run_loop.py status <slice-dir>
    run_loop.py gate <phase-outputs>/gate_spec.json

`gate` is the code-writer's, not the operator's: it runs the phase gate the
driver would run, from the spec the driver wrote at the dispatch, and records
the run beside it; a green the driver can prove was on the tree it is handed
is its gate, not run again. It exits 0 green · 1 red · 3 nothing ran · 2 no
run (an unreadable spec, a tree git cannot hash).

Exit codes of run: 0 slice complete · 3 bailed on an error (bailout.json
written) · 4 bailed with an operator question (bailout.json written) ·
2 usage/precondition error · 130 interrupted · 1 unexpected error.
`run --detach` exits 0 once the driver started, else with its refusal's code.

Exit codes of wait, its own and not the run's: 0 the run ended (its code is
in the output) · 5 still running at --for · 6 the driver is gone and left no
exit record · 2 no run to wait on. Of stop: 0 stopped · 1 no driver running,
or still running after the wait · 2 the driver is on another host.
"""

import argparse
import contextlib
import copy
import fcntl
import json
import os
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import github_target  # noqa: E402
import project_config  # noqa: E402
from close_out import (  # noqa: E402
    ReportEdited,
    ReportError,
    add_note,
    append_entry,
    counts_line,
    dispatch_line,
    edited_report,
    entry_counts,
    find_by_headline,
    init_report,
    live_entries,
    owed_before_push,
    owed_before_test,
    render_report,
    report_path,
    stamp_header,
    store_path,
    verb_usage,
    worklist,
    worklist_view,
)
from redact_secrets import RedactionError, is_examined, redact  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration — the one place models and efforts are set. Every outer
# dispatch passes its model/effort explicitly (`kc session create-headless
# --model M --reasoning-effort E`); sub-agents inherit from the dispatching
# session, which is the intended mechanism. The always-Sonnet agents
# (test-agent, test-fixer, rebase-agent) additionally pin `model:` in their
# own definitions, so they stay Sonnet even when dispatched as sub-agents.
# ---------------------------------------------------------------------------

MODELS: dict[str, tuple[str, str | None]] = {
    "code-writer": ("opus", "xhigh"),
    "code-reviewer": ("opus", "xhigh"),
    "doc-writer": ("opus", "xhigh"),
    "wrap-up": ("opus", "xhigh"),
    "consult": ("opus", "xhigh"),
    "test-agent": ("sonnet", None),
}

# The plugin name. Installed agents resolve as `dev:<role>`; the driver
# dispatches by the namespaced name so the lookup cannot land on a
# same-named agent the target repo happens to ship.
AGENT_NAMESPACE = "dev"

# Roles the driver dispatches with --agent, plus the sub-agents the procedure
# docs route to. `kc session create-headless --agent` does not validate the
# name — an unknown agent spawns a plain SDK session that answers anyway — so
# the driver asserts these definitions exist before any dispatch.
REQUIRED_AGENTS = ("code-writer", "code-reviewer", "doc-writer", "wrap-up",
                   "test-agent", "test-fixer", "rebase-agent")

# Where those definitions live: this script is <plugin>/tools/run_loop.py, so
# the agents ship one level up. Resolved from __file__, not the target repo —
# the workflow is plugin-shipped and a run can target any repo.
AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"

TIMEOUTS = {
    "code-writer": 7200,
    "code-reviewer": 3600,
    "consult": 1800,
    "test-agent": 14400,   # includes a CI build wait and live checks
    "doc-writer": 7200,
    "wrap-up": 7200,
}

GATE_TIMEOUT = 3600
NUDGE_TIMEOUT = 900

# A run-start `kc project setup`, per repo (`_setup_targets`): an install
# still going after 15 minutes is hung, and the run goes on without it.
SETUP_TIMEOUT = 900

# How often a running send is asked for its session id. The engine reports it
# from the turn's first stream event, so the id is knowable seconds in — and a
# round whose send hangs after the turn is reattachable only if the driver
# heard it (#957).
SESSION_ID_POLL = 5

# The loop-tail sweep and the doc gate run all three verbs; the per-phase
# gate stays test-only (lint/build breakage there surfaces at loop tail,
# where fixing it costs one phase instead of a per-phase tax).
SWEEP_VERBS = ("lint", "build", "test")

# kc's exit code for "nothing ran in the requested scope" (KC-81): `kc
# project test|build|lint` exits 3 when its selection holds no statement for
# the verb — `--project X` where X has none, or no `--project` and no
# component with any. Beside it, 0 is green, 1 red and 2 a usage error. It is
# neither green nor red: there is nothing to fix, and nothing was proved.
KC_NOTHING_RAN = 3

# Every dispatch that names a `kc project … --project <component>` gate says
# what exit 3 means there, so a session never spends turns fixing a "failure"
# that is a component with no statement for the verb. No closing period: the
# executor templates close the sentence `{gate_hint}` ends.
NOTHING_RAN_HINT = ("Exit 3 is kc's \"nothing ran\" — not red, nothing to "
                    "fix: the component declares no statement for the verb; "
                    "say what you checked instead")

# Closes every gate hint that names the wrapper: what a green run of it buys.
GATE_REUSE_HINT = ("When its last run is green on the tree you hand back — "
                   "unchanged since that run began; committing changes "
                   "nothing, any edit does — the driver takes that run as "
                   "its gate and runs no suite again")

# The writer runs the phase gate through the driver's own wrapper (`run_loop.py
# gate <spec>`, `run_writer_gate`): the spec, written into the phase's outputs
# dir at every code-writer dispatch, says what the gate is; each run records
# what it ran and on what tree beside it, one record per round, so only the
# latest round's can stand in for the driver's gate (`_reusable_writer_gate`).
GATE_SPEC_NAME = "gate_spec.json"


def writer_gate_record_name(round_: int) -> str:
    return f"writer_gate_r{round_}.json"


# The component `Target: root` names — the repo as a whole to a plan's
# authors — and the gate it falls back to when root declares no tests.
ROOT_COMPONENT = "root"
REPO_GATE_ARGV = ["kc", "project", "test"]

GATE_FIX_CAP = 3       # executor fix rounds against a red gate, per phase
# Nudges at the test session over a repo it committed to but never pushed.
# The driver checks rather than pushes: a slice touching several repos may
# need an order only the agent running the verification knows.
PUSH_NUDGE_CAP = 2
# A verdict nudge the harness swallows says the session was cut mid-wait,
# and is answered by resuming it to recover what it was waiting on.
LOST_WAIT_CAP = 2   # mid-wait recoveries per round: the doc-writer yields twice
# The review loop's runaway backstop, not its working budget. Round 1's fix
# is automatic; from round 2 on a funding consult judges every `issues`
# verdict against a bar that rises each round (_review_bar) BEFORE an
# executor round is spent.
REVIEW_ROUND_CAP = 5
# Append-phase generations (completion consult + test phase): the first
# absorbs in-scope touch-ups, the second appends blocking work only, a third
# pending generation bails to the operator.
GENERATION_CAP = 2
# A bail's details as its `bailouts` row keeps them for the close-out report's
# event entry: enough for the git error or the agent's summary,
# short of a whole log. bailout.json keeps them whole.
BAIL_DETAILS_CAP = 600
# Where a stop no phase owns happened, by the `run_phase` it left: the
# entry's headline. `phases` with no phase is between them, or before any.
BAIL_STAGES = {"consult": "at the completion consult",
               "test": "in the test phase", "docs": "in the doc phase"}
# An action entry the operator must settle before a run can
# work — the plan-writer heads it `Before /dev:run-slice: …`. After-run ones
# (the plan loop's push-hold and settle-V entries) never match.
PRERUN_HEADLINE_RE = re.compile(r"^before\s+`?/dev:run-slice\b`?", re.IGNORECASE)

# The spawn environment of every dispatched session (plan_loop imports it).
# Ephemeral sessions must not pay the 1-hour cache-write premium; and the
# prefix they carry on every turn is trimmed of what no headless role uses —
# the operator's auto-memory (per-user, per-cwd, never read or written by a
# dispatched role) and Claude Code's bundled skills (code-review, dataviz,
# … — never invoked by one). Measured 2026-08-23 at ctx1 −3.3 k tokens per
# session (≈ 10 % of the 32 k prefix), identical across roles. The plugin's
# own agents and skills still register.
SPAWN_ENV = {
    "FORCE_PROMPT_CACHING_5M": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
}

# The claude flags `create-headless` passes through to the spawned claude
# (kc's own pass-through, under claude's flag names), finishing the prefix
# trim SPAWN_ENV starts — agent-dispatch.md § Spawning has the why and the
# numbers. `--disable-slash-commands` for every role (the plugin's agents
# are not skills and still register); `--strict-mcp-config` for every role
# but the test-agent, which keeps the operator's MCP servers because it
# drives CI through Jenkins. Sub-agents inherit the parent's trim.
SPAWN_FLAGS = ("--disable-slash-commands",)
MCP_ROLES = frozenset({"test-agent"})

# The operator's MCP servers every dispatched role keeps, named one by one and
# copied verbatim out of the user-level `~/.claude.json` (`mcpServers`) into a
# config of the loop's own, which `--mcp-config` names beside
# `--strict-mcp-config`. Everything else in that file stays out of a role's
# session, so the trim above and its reason — no tracker reach, no tool
# schemas a role never calls — still hold. Fieldnotes is where a role posts
# the friction it hit while working, which is why every role needs it.
# Gitblit is the read-only mirror of the operator's GitHub repos, so a role can
# search the code of repos the environment does not check out (a slice ruling
# may point it at gitblit's `find_files`); it needs no token. The KubeCoder
# worker carries `notification`, so a ruling that asks a role to keep the
# operator posted works as written; Jenkins stays the test-agent's. Naming the
# servers here is fine: AIWorkflow is bespoke to this host.
PROMOTED_MCP_SERVERS = ("fieldnotes", "gitblit", "kubecoder-worker")

# The two sides of that copy. A promoted entry may carry a bearer token, so the
# copy lives under the user's home, which no repo contains — never a command
# line, a log line, state.json or a slice folder. The path is stable and the
# content identical from every writer (one home serves the environments
# running loops concurrently) and the write is atomic, so a concurrent reader
# sees one version or the other, never half a file.
USER_CLAUDE_JSON = ".claude.json"
PROMOTED_MCP_FILE = ".claude/aiworkflow-promoted-mcp.json"


def _user_home() -> Path:
    """The home both sides of the promoted-MCP copy live under — one seam, so
    a test never reads or writes the operator's own files."""
    return Path.home()


def promoted_mcp_config(source: Path | None = None) -> tuple[dict, list[str]]:
    """PROMOTED_MCP_SERVERS as an `--mcp-config` payload, copied verbatim out
    of the user-level `~/.claude.json`, plus the promoted names that file did
    not hold. A missing file, unreadable JSON or a missing `mcpServers`
    promotes nothing and is not an error — the role spawns without the server
    rather than the run failing. Only user-level `mcpServers` is read; the
    per-project sections of that file are not."""
    src = Path(source) if source is not None else _user_home() / USER_CLAUDE_JSON
    try:
        data = json.loads(src.read_text())
    except (OSError, ValueError):
        data = {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        servers = {}
    promoted = {name: servers[name]
                for name in PROMOTED_MCP_SERVERS if name in servers}
    missing = [name for name in PROMOTED_MCP_SERVERS if name not in promoted]
    return {"mcpServers": promoted}, missing


def write_promoted_mcp_config(source: Path | None = None,
                              dest: Path | None = None
                              ) -> tuple[Path | None, list[str]]:
    """Write the promoted config to `dest` — mode 0600, atomically (temp file
    in the same directory, then os.replace) — and return (its path, the lines
    to log). The path is None when nothing was promoted or the write failed;
    neither stops a run."""
    config, missing = promoted_mcp_config(source)
    notes = [f"promoted MCP server {name!r} is not in ~/{USER_CLAUDE_JSON} — "
             "dispatched roles spawn without it" for name in missing]
    if not config["mcpServers"]:
        return None, notes
    target = Path(dest) if dest is not None else _user_home() / PROMOTED_MCP_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent),
                                   prefix=".promoted-mcp-", suffix=".json")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(config, handle, indent=2)
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except OSError as exc:
        notes.append(f"could not write the promoted MCP config: {exc}")
        return None, notes
    return target, notes


# The promoted flags, computed once per process: a nudge resumes the session a
# dispatch created and must carry the same prefix, so the answer cannot move
# mid-run. Rewritten at the first dispatch, which is what picks up a changed
# `~/.claude.json` on the next run.
_PROMOTED_MCP: list[list[str]] = []


def _silent(_msg: str) -> None:
    """The default log sink — a caller that passes none hears nothing."""


def _promoted_mcp_flags(log=None) -> list[str]:
    """`--mcp-config <path>` for the promoted servers, or nothing at all when
    none of them was found."""
    if not _PROMOTED_MCP:
        path, notes = write_promoted_mcp_config()
        for note in notes:
            (log or _silent)(note)
        _PROMOTED_MCP.append(["--mcp-config", str(path)] if path else [])
    return list(_PROMOTED_MCP[0])


def spawn_flags(role: str | None, log=None) -> list[str]:
    """The pass-through flags for one dispatch — or for the nudge of one,
    which resumes the same session and must carry the same prefix."""
    flags = list(SPAWN_FLAGS)
    if role not in MCP_ROLES:
        flags.append("--strict-mcp-config")
        flags += _promoted_mcp_flags(log)
    return flags

# The devlock wait: poll the flock nonblocking so the wait is loggable and
# bounded (a session crash releases the lease via fd close, so a very long
# hold is a stuck holder, not a working one).
DEVLOCK_POLL = 15
DEVLOCK_MAX_WAIT = 4 * 3600

# The account's session-limit window: a session killed by it surfaces the
# API's notice ("You've hit your session limit · resets 10:10pm
# (Europe/Amsterdam)") as its whole output instead of doing any work. That is
# an account state, not an agent outcome — the driver waits it out and
# redispatches the same round.
SESSION_LIMIT_RE = re.compile(r"you[’']ve hit your session limit", re.IGNORECASE)
SESSION_LIMIT_RESET_RE = re.compile(
    r"resets\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)"
    r"(?:\s*\((?P<zone>[^)]+)\))?", re.IGNORECASE)
SESSION_LIMIT_GRACE = 300         # the stated reset is approximate: wait past it
SESSION_LIMIT_FALLBACK = 1800     # no parseable reset: retry in half an hour
SESSION_LIMIT_MAX_SLEEP = 12 * 3600   # no single wait may exceed this

VERDICTS = {
    "code-writer": {"done", "question", "blocked"},
    "code-reviewer": {"signoff", "issues", "critical"},
    "test-agent": {"clean", "findings", "blocked"},
    "doc-writer": {"done", "question", "blocked"},
    "wrap-up": {"done", "blocked"},
}
# The wrap-up's verdict beside its outcome: lists of entry ids, each optional,
# carried onto its history row as the agent reported them. A key the driver
# does not know is ignored, never a protocol failure — nothing about the
# wrap-up's verdict stops a run.
WRAP_UP_LISTS = ("fixed", "folded", "cards", "left", "relabelled")


class Bailout(Exception):
    """A terminal stop. `question=True` marks an operator question (exit 4);
    everything else is an error (exit 3)."""

    def __init__(self, reason: str, phase: str | None = None,
                 details: str = "", consult: str | None = None,
                 question: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.phase = phase
        self.details = details
        self.consult = consult
        self.question = question


class WrapUpLeftOut(Exception):
    """A soft failure of the wrap-up (`RunLoop._wrap_up`): never a stop, the
    reason it was left out of the landing. `without` is the doc gate's run
    on the doc branch without its commits, when that run is what decided it
    — the doc phase goes on from it (`gate_last`)."""

    def __init__(self, reason: str, without: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.without = without


# Every timestamp the loops write or print is the operator's local wall clock
# (the process's TZ, UTC if unset) — these are read by the human watching the
# run, never compared across hosts. The ISO stamps stay offset-aware, so they
# remain unambiguous for anything that parses them back.
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _write_state(path: Path, state: dict) -> None:
    """state.json, written atomically: a reader — `wait`, `status`, a
    resume — never sees it half-written."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _write_json_atomic(path: Path, data: dict) -> None:
    """`data` as JSON at `path`, through a temp file of its own in the same
    directory: a reader never sees it half-written, and two writers never
    share a temp file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _exit_status(exc: BaseException) -> int:
    """The process exit code an exception leaving `run` turns into."""
    if isinstance(exc, SystemExit):
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1
    if isinstance(exc, KeyboardInterrupt):
        return 130
    return 1


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# The plugin manifest beside this tools/ directory — the installed clone has
# the same layout as the repo.
PLUGIN_MANIFEST = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


def plugin_version() -> str | None:
    """The version of the plugin this loop runs from, for the state file —
    so a slice's record says which plugin produced it and runs can be read
    before/after a change. None when the manifest is unreadable (a loop is
    never held up by its own bookkeeping)."""
    manifest = _read_json(PLUGIN_MANIFEST) or {}
    return manifest.get("version") or None


# Claude Code's record of what is installed — the plugin every agent a loop
# dispatches loads. The loop itself runs from wherever it was launched, and
# the plugin cache keeps old versions, so the two can differ. A module
# constant so the suites point it away from the operator's own file.
INSTALLED_PLUGINS = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
TOOLS_DIR = Path(__file__).resolve().parent


def installed_plugin(tools_dir: Path | None = None) -> tuple[str, str] | None:
    """(version, installPath) of this plugin as installed_plugins.json has it,
    or None when that cannot be told. The entry is `<name>@<marketplace>`:
    the marketplace is read off the cache layout this file runs from
    (`.../plugins/cache/<marketplace>/<name>/<version>/tools/`), else the
    file's sole `<name>@*` key is taken; several or none is None. Within the
    entry the user-scope install wins, else a lone one."""
    manifest = _read_json(PLUGIN_MANIFEST)
    name = manifest.get("name") if isinstance(manifest, dict) else None
    data = _read_json(INSTALLED_PLUGINS)
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not name or not isinstance(plugins, dict):
        return None
    parts = (tools_dir or TOOLS_DIR).parts
    if (len(parts) >= 6 and parts[-1] == "tools" and parts[-3] == name
            and parts[-5] == "cache" and parts[-6] == "plugins"):
        key = f"{name}@{parts[-4]}"
    else:
        keys = [k for k in plugins if k.split("@", 1)[0] == name]
        if len(keys) != 1:
            return None
        key = keys[0]
    entry = _install_entry(plugins.get(key))
    version = entry.get("version") if entry else None
    if not isinstance(version, str) or not version:
        return None
    path = entry.get("installPath")
    return version, path if isinstance(path, str) else ""


def _install_entry(entries) -> dict | None:
    """The install an installed_plugins.json key stands for: its user-scope
    entry, else a lone one; several and none of them the user's is None."""
    if not isinstance(entries, list):
        return None
    entries = [e for e in entries if isinstance(e, dict)]
    user = [e for e in entries if e.get("scope") == "user"]
    return user[0] if user else entries[0] if len(entries) == 1 else None


# A skill a plan names for its work, as `/dev:plan-slice` writes it: the
# backticked `<plugin>:<skill>`. Every role is spawned without the Skill tool
# (SPAWN_FLAGS), so the driver hands the role the skill's file instead.
SKILL_REF_RE = re.compile(r"`([a-z0-9][a-z0-9-]*):([a-z0-9][a-z0-9-]*)`")


def resolve_skills(text: str) -> list[tuple[str, Path | None]]:
    """The skills `text` names, in order of first mention, each once:
    (`<plugin>:<skill>`, its installed SKILL.md), the path None when the
    installed plugin has no such skill. A name whose plugin is not installed
    is no skill reference (`origin:main` in backticks), and this plugin's own
    are its roles' already. The install is the one an interactive session
    loads: a `<plugin>@*` key's user-scope entry, else its lone one, the
    first such key in file order when several qualify. Nothing installed on
    record is no skills at all."""
    data = _read_json(INSTALLED_PLUGINS)
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return []
    manifest = _read_json(PLUGIN_MANIFEST)
    own = manifest.get("name") if isinstance(manifest, dict) else None
    found: list[tuple[str, Path | None]] = []
    for match in SKILL_REF_RE.finditer(text):
        plugin, skill = match.groups()
        name = f"{plugin}:{skill}"
        if plugin == own or any(n == name for n, _ in found):
            continue
        keys = [k for k in plugins if k.split("@", 1)[0] == plugin]
        if not keys:
            continue
        installs = [e for e in (_install_entry(plugins[k]) for k in keys) if e]
        entry = next((e for e in installs if e.get("scope") == "user"),
                     next(iter(installs), None))
        root = entry.get("installPath") if entry else None
        path = (Path(root) / "skills" / skill / "SKILL.md"
                if isinstance(root, str) and root else None)
        found.append((name, path if path and path.is_file() else None))
    return found


def stale_plugin(script: str) -> tuple[str, str, str] | None:
    """(this plugin's version, the installed one's, where the installed copy
    of `script` is) when the two versions differ, else None. Fail open — an
    unknown version on either side is no evidence of a mismatch. Shared by
    the loops' guard and preflight, which names the path before a launch."""
    ours = plugin_version()
    installed = installed_plugin()
    if not ours or installed is None or installed[0] == ours:
        return None
    version, path = installed
    loop = (str(Path(path) / "tools" / script) if path
            else f"the installed plugin's tools/{script}")
    return ours, version, loop


def assert_plugin_current(script: str, rerun: str) -> None:
    """Bail (`plugin_version`, an error) when this loop runs another plugin
    version than the one its agents load: a newer agent writes what this
    driver ignores, an older one misses what it expects. `script` is the
    launching loop's filename, `rerun` how a relaunch picks the run up."""
    stale = stale_plugin(script)
    if stale is None:
        return
    ours, version, relaunch = stale
    raise Bailout(
        "plugin_version",
        details=f"this loop runs plugin {ours} from {TOOLS_DIR}; the "
                f"installed plugin is {version}, which the agents it "
                "dispatches load, so driver and agents disagree on what they "
                f"hand each other. Relaunch from {relaunch} with the same "
                f"arguments{rerun}.")


# verification.json's item schema (docs/plan-template.md § verification.json).
# A key outside it is one this driver does not act on — the agent that wrote
# it loads a plugin that does.
VERIFICATION_ITEM_KEYS = frozenset({
    "id", "area", "description", "owed_after", "verdict", "rationale",
    "evidence"})


def open_prerun_actions(slice_dir: Path) -> list[tuple[str, str]]:
    """(id, headline) of every live action entry in the slice's
    close-out report whose headline opens `Before /dev:run-slice` (the
    command in backticks or not, any case). A missing report, or one without
    the section, has none."""
    try:
        entries = live_entries(slice_dir, "Outstanding actions")
    except ReportError:
        return []
    return [(eid, headline) for eid, headline in entries
            if PRERUN_HEADLINE_RE.match(headline)]


def assert_no_prerun_actions(slice_dir: Path) -> None:
    """Bail (`prerun_action`, an operator question) while the report holds an
    open pre-run action: a phase dispatched before it is taken fails on what
    it was meant to provide, and only the operator can take it."""
    open_ = open_prerun_actions(slice_dir)
    if not open_:
        return
    tool = TOOLS_DIR / "close_out.py"
    raise Bailout(
        "prerun_action", question=True,
        details=f"{report_path(slice_dir)} holds {len(open_)} open pre-run "
                "action(s), to be taken before this run can work:\n"
                + "\n".join(f"- {eid} — {headline}" for eid, headline in open_)
                + "\nTake each action (or have it taken on your word), strike "
                f"its entry with `python3 {tool} strike {slice_dir} <id> "
                "--reason \"<what was done>\" --by <who>`, commit the report, "
                "then relaunch with --resume.")


def assert_verification_keys(slice_dir: Path) -> None:
    """Bail (`protocol_failure`) when a verification.json item carries a key
    outside VERIFICATION_ITEM_KEYS, rather than silently ignore what it says.
    A missing or unparseable file is not this check's business."""
    data = _read_json(Path(slice_dir) / "verification.json")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    unknown = [f"{item.get('id') or f'item {i}'} `{key}`"
               for i, item in enumerate(items, 1) if isinstance(item, dict)
               for key in sorted(set(item) - VERIFICATION_ITEM_KEYS)]
    if unknown:
        raise Bailout(
            "protocol_failure",
            details="verification.json carries item key(s) this driver "
                    f"(plugin {plugin_version() or 'unknown'}) does not know: "
                    + ", ".join(unknown) + " — typically written by an agent "
                    "loading a newer plugin. Relaunch from the installed "
                    "plugin, or remove the key.")


def _protocol_failure_detail(role: str, returncode: int, verdict: dict | None,
                             verdict_name: str, valid: bool,
                             nudged: bool, recoveries: int = 0) -> str:
    """Explain why a dispatch is treated as a protocol failure.

    The return code and the verdict's validity are independent axes: a session
    can be killed (rc != 0) *after* it committed and wrote a perfectly good
    verdict — e.g. a SIGTERM'd worker exits 143 — so the two are reported
    separately. `recoveries` is how often the round was resumed to recover a
    report lost mid-wait before it came to this."""
    if verdict is None:
        vstate = "missing/unparseable"
    elif not valid:
        vstate = f"invalid outcome {verdict.get('outcome')!r}"
    else:
        vstate = f"valid outcome {verdict.get('outcome')!r}"
    tail = ""
    if nudged:
        tail = " (after one nudge"
        if recoveries:
            tail += (f" and {recoveries} mid-wait "
                     + ("recovery" if recoveries == 1 else "recoveries"))
        tail += ")"
    return (
        f"{role} session ended rc={returncode}; verdict file "
        f"{verdict_name}: {vstate}" + tail
    )


def _verdict_valid(role: str, verdict: dict | None) -> bool:
    """Whether a verdict file is one this role is allowed to have written.
    A role with no vocabulary in VERDICTS is held to parseable JSON only."""
    return verdict is not None and (
        role not in VERDICTS or verdict.get("outcome") in VERDICTS[role])


def session_limit_notice(result) -> str | None:
    """The API's session-limit notice in a session's final text, or None."""
    text = getattr(result, "result_text", "") or ""
    return text.strip() if SESSION_LIMIT_RE.search(text) else None


def swallowed_nudge(result) -> bool:
    """Whether a resume send came back as the CLI's stopped-task bookkeeping
    instead of a model turn. A background task or sub-agent whose completion
    landed mid-turn dies with the session's process, and the first send that
    resumes the session is spent clearing it ("Continue from where you left
    off." → "No response requested.", or no assistant turn at all) — so the
    prompt never reached the model and has to be sent again."""
    text = (getattr(result, "result_text", "") or "").strip()
    return text in ("", "No response requested.")


def parse_session_limit_reset(text: str,
                              now: datetime | None = None) -> datetime | None:
    """The moment the limit window reopens, from the notice's stated reset
    ("resets 10:10pm (Europe/Amsterdam)").

    A 12-hour clock with no date, so a reset that already passed today is
    tomorrow's. Returns None when the text states no parseable time, or names
    a zone this host does not know — the caller then falls back to a short
    fixed wait rather than guessing a wall-clock offset."""
    match = SESSION_LIMIT_RESET_RE.search(text)
    if not match:
        return None
    zone = match.group("zone")
    if zone:
        try:
            tz = ZoneInfo(zone.strip())
        except (KeyError, ValueError):
            return None
    else:
        tz = datetime.now().astimezone().tzinfo
    minute = int(match.group("minute") or 0)
    if minute > 59:
        return None
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower().startswith("p"):
        hour += 12
    now = now.astimezone(tz) if now else datetime.now(tz)
    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return reset


def _transcript_path(cwd: Path | str, session_id: str | None) -> str | None:
    """The Claude Code transcript file for a session spawned with this cwd:
    ~/.claude/projects/<munged-cwd>/<session-id>.jsonl. The munge mirrors
    Claude Code's project-dir encoding: every non-alphanumeric path character
    becomes '-'. Recorded in state.json so a later session can research any
    agent's conversation without reverse-engineering this mapping."""
    if not session_id:
        return None
    munged = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(cwd).resolve()))
    return str(Path.home() / ".claude" / "projects" / munged
               / f"{session_id}.jsonl")


def _orchestrator_record() -> dict | None:
    """The interactive session that launched this run (Claude Code exports
    its id to Bash children), so cost attribution can count the orchestrator.
    None when run by hand."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    return {"session": sid, "transcript": _transcript_path(Path.cwd(), sid)}


def spec_root_for(slice_dir: Path) -> Path | None:
    """The spec repo root: the parent of the `slices/` tree the slice sits in
    (`slices/NNN_slug`, `slices/backlog/NNN_slug`, … all resolve the same)."""
    for parent in slice_dir.parents:
        if parent.name == "slices":
            return parent.parent
    return None


# ---------------------------------------------------------------------------
# Plan parsing — `### P<id> — <title>` headings, ids [A-Za-z0-9]+, document
# order authoritative. Every ### heading in the plan is a phase heading;
# done-records live under the heading without introducing new ###s.
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^###\s+(.*)$")
PHASE_RE = re.compile(r"^###\s+P([A-Za-z0-9]+)\s+—\s+(.+?)\s*$")
DONE_STAMP_RE = re.compile(r"✅\s*DONE\b")
TARGET_RE = re.compile(r"^\s*\**Target\**\s*:\**\s*`?([^`]+?)`?\s*$")
CREATES_RE = re.compile(r"^\s*\**Creates\**\s*:\**\s*`?([^`]+?)`?\s*$")
REVIEW_RE = re.compile(r"^\s*\**Review\**\s*:\**\s*`?([^`]+?)`?\s*$")
# Several paths, each perhaps in backticks or quotes: they are split out of
# the whole value (`Phase.resolve_target`), not captured one by one.
NEVER_PRINT_RE = re.compile(r"^\s*\**Never print\**\s*:\**\s*(.+?)\s*$")
PUSH_HOLDS_RE = re.compile(r"^##\s+Push holds\s*$", re.IGNORECASE)
HOLD_RE = re.compile(r"^\s*[-*]\s+\**`?(\S+?)`?\**\s+—\s+(\S.*?)\s*$")
DRIVER_RULINGS_RE = re.compile(r"^##\s+Driver rulings\s*$", re.IGNORECASE)
RULING_BULLET_RE = re.compile(r"^\s*[-*]\s+(\S+)\s+(.*?)\s*$")
RULING_TARGET_RE = re.compile(r"^\**`?(\S+?)`?\**$")
RULING_ACCEPT_RE = re.compile(r"^\**`?(\S+?)`?\**\s+`?(\S+?)`?$")
RULING_SEP_RE = re.compile(r"\s+—\s+")


class Phase:
    def __init__(self, id_: str, title: str, line_no: int):
        self.id = id_
        self.title = title       # includes any ✅ DONE stamp text
        self.line_no = line_no   # 0-based index of the heading line
        self.body: list[str] = []
        self.done = bool(DONE_STAMP_RE.search(title))
        self.target: str | None = None
        self.creates: str | None = None
        self.review: str | None = None
        self.never_print: list[str] | None = None

    def resolve_target(self) -> None:
        """`Target:` and the optional `Creates:`, `Review:` and `Never
        print:` — first line of each kind wins, in the same styles a plan
        writes them. `Creates:` declares that this phase REGISTERS that
        component in the manifest: the name cannot be in `kc project list`
        until the phase has run, so resolution and validation are told to
        expect it rather than calling it a typo. `Review:` names a file in
        the slice folder listing work the phase commits outside its Target —
        clones it commits into and leaves unpushed — which the reviewer is
        pointed at (`review_set_pairs`). `Never print:` lists paths, relative
        to the Target's root, whose content must never reach a transcript:
        the driver's review diffs hold them out and the reviewer is given
        the commands that print none of it (`_review_secrets`)."""
        for line in self.body:
            if self.target is None:
                match = TARGET_RE.match(line)
                if match:
                    self.target = match.group(1).strip()
                    continue
            if self.creates is None:
                match = CREATES_RE.match(line)
                if match:
                    self.creates = match.group(1).strip()
                    continue
            if self.review is None:
                match = REVIEW_RE.match(line)
                if match:
                    self.review = match.group(1).strip()
                    continue
            if self.never_print is None:
                match = NEVER_PRINT_RE.match(line)
                if match:
                    paths = [p.strip("`'\"")
                             for p in re.split(r"[,\s]+", match.group(1))]
                    self.never_print = [p for p in paths if p] or None


# A review-set file's clone/commit pairs (AIWF-37). Ansible slice 036 did its
# work as unpushed commits in thirteen /work/scratch clones, listed in a
# ledger beside the plan, and the reviewer was handed the Target's empty
# range. The file's shape is its writer's: any line carrying an absolute path
# and a commit sha is a pair, so a table row and a bullet both read, and a
# header, separator or prose line carries at most one of the two. A sha is
# 7–40 lowercase hex with a digit in it — a hex-spelled word is not one. A
# line naming two commits is not guessed at: Ansible slice 055's rows named
# each bump's parent after it, and the last-sha rule handed the reviewer the
# parents (AIWF-62).
REVIEW_SHA_RE = re.compile(r"(?=[a-f]*\d)[0-9a-f]{7,40}")


def _review_set_lines(text: str) -> list[tuple[str, list[str]]]:
    """Each line of a `Review:` file carrying a clone and a commit: its
    first absolute path and its distinct shas, in line order. Two shas are
    one commit when one is a prefix of the other — a short and a full form —
    and the longer is kept."""
    lines: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        tokens = [token.lstrip("`'\"(<[").rstrip("`'\")>],.;:")
                  for token in re.split(r"[\s|]+", line)]
        clone = next((t for t in tokens
                      if t.startswith("/") and len(t) > 1), None)
        shas: list[str] = []
        for token in tokens:
            if not REVIEW_SHA_RE.fullmatch(token):
                continue
            same = next((i for i, sha in enumerate(shas)
                         if sha.startswith(token) or token.startswith(sha)),
                        None)
            if same is None:
                shas.append(token)
            elif len(token) > len(shas[same]):
                shas[same] = token
        if clone and shas:
            lines.append((clone, shas))
    return lines


def review_set_pairs(text: str) -> list[tuple[str, str]]:
    """The (clone, sha) pairs in a `Review:` file, in order, each once: a
    line's first absolute path with the one commit it names. Several rows
    sharing one clone and commit are one pair; a clone whose commit was
    amended, listed with its new sha, is a new one. A line naming two or
    more distinct commits is no pair (`review_set_ambiguous`)."""
    pairs: list[tuple[str, str]] = []
    for clone, shas in _review_set_lines(text):
        if len(shas) == 1 and (clone, shas[0]) not in pairs:
            pairs.append((clone, shas[0]))
    return pairs


def review_set_ambiguous(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """The lines of a `Review:` file naming two or more distinct commits —
    (clone, the line's shas in line order) — in order, each once."""
    lines: list[tuple[str, tuple[str, ...]]] = []
    for clone, shas in _review_set_lines(text):
        if len(shas) > 1 and (clone, tuple(shas)) not in lines:
            lines.append((clone, tuple(shas)))
    return lines


def parse_plan(text: str) -> tuple[list[Phase], list[str]]:
    """(phases in document order, structure errors). Errors name what a
    fixing session needs: the offending heading or phase and what is wrong.
    A DONE phase is not required to still carry a Target — only work the
    driver may yet dispatch needs one."""
    phases: list[Phase] = []
    errors: list[str] = []
    current: Phase | None = None
    for line_no, line in enumerate(text.splitlines()):
        heading = HEADING_RE.match(line)
        if heading:
            match = PHASE_RE.match(line)
            if not match:
                errors.append(
                    f"line {line_no + 1}: `### {heading.group(1)}` is not a "
                    "phase heading (`### P<id> — <title>`, id [A-Za-z0-9]+)")
                current = None
                continue
            current = Phase(match.group(1), match.group(2), line_no)
            phases.append(current)
        elif current is not None:
            current.body.append(line)
    seen: set[str] = set()
    for phase in phases:
        if phase.id in seen:
            errors.append(f"phase id P{phase.id} appears more than once "
                          "(ids are labels, but they must be unique)")
        seen.add(phase.id)
        phase.resolve_target()
        if not phase.done and not phase.target:
            errors.append(f"phase P{phase.id} has no `Target:` line")
    return phases, errors


# The headings that end a phase's section: any `#`–`###`. A `####` inside a
# phase is its own, as parse_plan reads it.
SECTION_HEADING_RE = re.compile(r"^#{1,3}\s")


def phase_scope(plan_text: str, phase_id: str) -> str:
    """The plan as phase `phase_id`'s own: its section, plus everything no
    phase's section holds — the title, requirements/rulings, `## Driver
    rulings`, a not-in-scope after the phases — with every other phase cut.
    A section runs from its `###` heading to the next heading at `###` or
    above, so a `##` after the last phase is the plan's again (parse_plan
    carries it in that phase's body; it reads phases, not prose)."""
    kept: list[str] = []
    owner: str | None = None
    for line in plan_text.splitlines():
        if SECTION_HEADING_RE.match(line):
            match = PHASE_RE.match(line)
            owner = match.group(1) if match else None
        if owner is None or owner == phase_id:
            kept.append(line)
    return "\n".join(kept)


def is_repo_path(target: str) -> bool:
    """A Target naming a whole repo — a sibling path (`../Repo`, absolute)
    or a GitHub repo the driver clones (`github:<owner>/<repo>`) — rather
    than a `kc project list` component."""
    return target.startswith(("../", "/")) or github_target.is_github(target)


def creation_claim(phases: list[Phase],
                   index: int) -> tuple[Phase | None, str | None]:
    """For a phase whose `Target:` did not resolve: (the phase that still
    has to create it, an error). A phase creates its own target, or an
    EARLIER one does — a later phase runs too late to help. While that
    claimer is pending the unknown name is expected, not wrong; once it is
    stamped DONE and `kc project list` still does not know the name, the
    claim was false and both phases are named. (None, None) means nothing in
    the plan claims the name — the caller's own error stands."""
    target = phases[index].target
    if not target or is_repo_path(target):
        # `Creates:` only ever names a component; a repo path either exists
        # (or clones) or it doesn't, and no declaration changes that.
        return None, None
    claimers = [p for p in phases[:index + 1] if p.creates
                and p.creates == target]
    pending = [p for p in claimers if not p.done]
    if pending:
        return pending[0], None
    if claimers:
        return None, (
            f"Target `{target}` is declared `Creates:` by phase "
            f"P{claimers[-1].id}, which is stamped ✅ DONE — but `kc project "
            "list` does not know that component (the component set was just "
            "re-read). Register it in the manifest, or fix the name.")
    return None, None


def manifest_claimer(phases: list[Phase], index: int,
                     root_of: Callable[[str], Path | None]) -> Phase | None:
    """For a phase whose whole-repo Target has no manifest yet: the phase
    that will add it, None when none will. `Creates:` on a phase of a repo
    without a manifest can only mean the phase writes that manifest, and
    the gate is read at gate time, so from then on the repo is gated. The
    claimer is the earliest pending phase at or before this one — a later
    one runs too late, a DONE one would have left the manifest there by now
    — that declares `Creates:` on a Target resolving to the same repo.
    `root_of` is a Target's resolved repo root, None when it does not
    resolve; a claimer that does not resolve is no claimer."""
    root = root_of(phases[index].target or "")
    if root is None:
        return None
    for phase in phases[:index + 1]:
        if phase.done or phase.creates is None or not phase.target:
            continue
        if root_of(phase.target) == root:
            return phase
    return None


def parse_push_holds(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(held target → why, structure errors) from `## Push holds` — the one
    `##` section the driver reads. A repo listed there is one this slice must
    not push: the push check reports it held instead of nudging the test
    session and bailing. Prose and comments in the section are ignored; a
    bullet that is not a hold is a structure error, because a hold the driver
    silently missed is a repo it would push."""
    holds: list[tuple[str, str]] = []
    errors: list[str] = []
    in_section = in_comment = False
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines()):
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if line.startswith("#"):
            in_section = bool(PUSH_HOLDS_RE.match(line))
            continue
        if not in_section or not line.lstrip().startswith(("-", "*")):
            continue
        match = HOLD_RE.match(line)
        if not match:
            errors.append(
                f"line {line_no + 1}: `{line.strip()}` is not a push hold "
                "(`- <target> — <why>`, em dash, target written as a phase "
                "writes its `Target:`)")
            continue
        target, why = match.group(1).strip(), match.group(2).strip()
        if target in seen:
            errors.append(f"line {line_no + 1}: `{target}` is held twice")
            continue
        seen.add(target)
        holds.append((target, why))
    return holds, errors


class Ruling:
    """One `## Driver rulings` bullet: the operator overriding a fixed rule
    of the loop for one target. `gate` waives the phase gate and the sweep's
    `test` row (`substitute` names what proves it instead, None for none);
    `accept` lets a red sweep/doc-gate row through for one verb; `prd`
    authorizes the test phase to run the promotion pipeline for the target
    (a push needs no ruling, production included)."""

    def __init__(self, kind: str, target: str, why: str,
                 verb: str | None = None, substitute: str | None = None,
                 text: str = ""):
        self.kind = kind
        self.target = target
        self.why = why
        # the verb the ruling governs: a gate ruling is the `test` gate
        self.verb = "test" if kind == "gate" else verb
        self.substitute = substitute
        self.text = text

    @property
    def key(self) -> str:
        """Identity for duplicates and the close-out's once-per-run record."""
        return " ".join(p for p in (self.kind, self.target,
                                    self.verb if self.kind == "accept"
                                    else None) if p)

    @property
    def substitute_text(self) -> str:
        return self.substitute or "no substitute"


RULING_GRAMMAR = (
    "`- gate <target> — <substitute or none> — <why>`, "
    f"`- accept <target> <{'|'.join(SWEEP_VERBS)}> — <why>` or "
    "`- prd <target> — <why>`; em dashes, target written as a phase writes "
    "its `Target:`")


def parse_rulings(text: str) -> tuple[list[Ruling], list[str]]:
    """(rulings, structure errors) from `## Driver rulings`. Read like
    `## Push holds`: prose and comments ignored, and every bullet that is not
    a ruling is an error — a ruling the driver silently missed is a gate it
    runs anyway, and the run deadlocks on a red the operator already
    ruled on."""
    rulings: list[Ruling] = []
    errors: list[str] = []
    in_section = in_comment = False
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines()):
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if line.startswith("#"):
            in_section = bool(DRIVER_RULINGS_RE.match(line))
            continue
        if not in_section or not line.lstrip().startswith(("-", "*")):
            continue
        ruling = _parse_ruling(line)
        if ruling is None:
            errors.append(f"line {line_no + 1}: `{line.strip()}` is not a "
                          f"driver ruling ({RULING_GRAMMAR})")
            continue
        if ruling.key in seen:
            errors.append(f"line {line_no + 1}: `{ruling.key}` is ruled "
                          "twice")
            continue
        seen.add(ruling.key)
        rulings.append(ruling)
    return rulings, errors


def _parse_ruling(line: str) -> Ruling | None:
    """One bullet as a Ruling, None when it does not parse. The why is the
    last field and may carry em dashes of its own."""
    bullet = RULING_BULLET_RE.match(line)
    if not bullet:
        return None
    kind, rest = bullet.group(1).strip("*`").lower(), bullet.group(2)
    fields = {"gate": 3, "accept": 2, "prd": 2}.get(kind)
    if fields is None:
        return None
    parts = [p.strip() for p in RULING_SEP_RE.split(rest, fields - 1)]
    if len(parts) != fields or not all(parts):
        return None
    head, why = parts[0], parts[-1]
    if kind == "accept":
        match = RULING_ACCEPT_RE.match(head)
        if not match or match.group(2) not in SWEEP_VERBS:
            return None
        return Ruling(kind, match.group(1), why, verb=match.group(2),
                      text=line.strip())
    match = RULING_TARGET_RE.match(head)
    if not match:
        return None
    substitute = None
    if kind == "gate" and parts[1].strip("`").lower() != "none":
        substitute = parts[1]
    return Ruling(kind, match.group(1), why, substitute=substitute,
                  text=line.strip())


# ---------------------------------------------------------------------------
# The phase digest — the writer's orientation, rendered into its dispatch
# from what the driver already holds: the plan as it stands (rulings land
# mid-run, so it is rebuilt per round), verification.json, the slice's
# intent paragraph, and git. The plan stays the writer's to edit; the digest
# is what it reads instead of the whole file.
# ---------------------------------------------------------------------------

# The done-record's opener — `**Done (P<id>).**` (`**Done (r1).**`, `**Done
# (<date>).**`: the parenthesis is free). Universal before it was written
# down (296 of 296 done phases across both spec repos, 2026-08-23); the digest
# reads a done phase's record from that line to the end of its section. A
# done phase without one contributes its whole section — bounded by the
# ~a-page contract, never skipped.
DONE_RECORD_RE = re.compile(r"^\s*\*\*Done\b")
# The record's second marker: the `Later phases:` line that opens the list a
# following phase's writer needs. Accepted plain or bold, colon optional.
LATER_PHASES_RE = re.compile(r"^\s*\**Later phases\**:?\**\s*$", re.I)
# The plan's prose sections the digest carries verbatim, by `##` heading
# prefix (case-insensitive): the requirements/rulings (authoritative on
# intent) and what the slice leaves out.
DIGEST_SECTIONS = ("requirements", "not in scope")
# `git diff --stat` rows kept per repo before the digest elides the middle.
DIGEST_STAT_LINES = 40


def plan_sections(text: str) -> tuple[str, dict[str, list[str]]]:
    """(the plan's title line without its `# `, `##` section heading → its
    lines including the heading). A section runs to the next `##` heading
    or to the first phase heading (`###`) — the phases are not prose."""
    title = ""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif HEADING_RE.match(line):
            current = None
        elif current is not None:
            sections[current].append(line)
    return title, sections


def slice_intent(slice_text: str) -> str:
    """The first paragraph of slice.md after its frontmatter and title — the
    slice's intent in the triage session's words. Empty when the file has
    none."""
    lines = slice_text.splitlines()
    start = 0
    if lines and lines[0] == "---":
        # A frontmatter block (the tracker id triage filed the slice under).
        # An opener with no closer is not frontmatter at all — a document that
        # starts on a horizontal rule — so it is read from the top as before.
        close = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if close is not None:
            start = close + 1
            while start < len(lines) and not lines[start].strip():
                start += 1
    if start < len(lines) and lines[start].startswith("# "):
        start += 1
    para: list[str] = []
    for line in lines[start:]:
        if line.strip():
            para.append(line)
        elif para:
            break
    return "\n".join(para)


def done_record(phase: Phase) -> list[str]:
    """A done phase's record: from its `**Done` opener to the end of the
    section, or the whole section when no opener is there."""
    body = phase.body
    for i, line in enumerate(body):
        if DONE_RECORD_RE.match(line):
            body = body[i:]
            break
    return _strip_blank(body)


def done_record_summary(phase: Phase) -> list[str] | None:
    """A done phase's record reduced to its two summary parts: the opener
    paragraph (what landed and the gate result) and the `Later phases:`
    list right after it (what is settled, what a later phase may use or is
    owed). None when the record has no opener, or no `Later phases:` block
    behind the opener — there is nothing to reduce, so the caller carries
    the record whole.

    The record is the phase's own story: rounds, witnessed reds, the gate
    line. A later phase's writer needs none of that, only the outcome and
    what it inherits — so the summary is what its digest receives. The whole
    record stays in the plan for the reviewer and the doc phase."""
    record = done_record(phase)
    if not record or not DONE_RECORD_RE.match(record[0]):
        return None
    i = 0
    opener: list[str] = []
    while i < len(record) and record[i].strip():
        opener.append(record[i])
        i += 1
    while i < len(record) and not record[i].strip():
        i += 1
    if i >= len(record) or not LATER_PHASES_RE.match(record[i]):
        return None
    block: list[str] = []
    while i < len(record) and record[i].strip():
        block.append(record[i])
        i += 1
    return opener + [""] + _strip_blank(block)


def records_without_summary(plan_text: str, phase_id: str) -> list[str]:
    """The ids of the done phases before `phase_id` whose record has no
    summary to carry — the digest gives their writer the whole thing. The
    driver logs one line per id and acts no further: a record off-shape is a
    finding for the readout, never a bail."""
    phases, _ = parse_plan(plan_text)
    idx = next((i for i, p in enumerate(phases) if p.id == phase_id), None)
    if idx is None:
        return []
    return [p.id for p in phases[:idx]
            if p.done and done_record_summary(p) is None]


def _strip_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _trim_stat(stat: str) -> str:
    lines = stat.splitlines()
    if len(lines) <= DIGEST_STAT_LINES:
        return stat
    kept = lines[:DIGEST_STAT_LINES - 1]
    return "\n".join(kept + [f" … {len(lines) - DIGEST_STAT_LINES} more files",
                             lines[-1]])


def build_phase_digest(plan_text: str, phase_id: str, intent: str,
                       criteria: list[dict], touched: list[tuple[str, str]],
                       ) -> str:
    """The digest for phase `phase_id`, rendered as Markdown for the
    dispatch. `intent` is the slice's intent paragraph (`slice_intent`),
    `criteria` verification.json's items, `touched` one (label, `git diff
    --stat` text) pair per merged phase, the label naming the phase and the
    repo it landed in. Empty parts are left out; a phase the plan does not
    carry digests to the slice parts only (the driver has already parsed the
    plan, so that is a race with an edit, not a structure error)."""
    title, sections = plan_sections(plan_text)
    phases, _ = parse_plan(plan_text)
    out: list[str] = ["---", "", f"# Orientation digest — phase P{phase_id}", ""]
    if title:
        out += [f"**Slice.** {title}", ""]
    if intent:
        out += [intent, ""]
    out += _digest_sections(sections)

    idx = next((i for i, p in enumerate(phases) if p.id == phase_id), None)
    if idx is not None:
        phase = phases[idx]
        out += ["## Your phase", "", f"### P{phase.id} — {phase.title}", ""]
        out += _strip_blank(phase.body) + [""]
        earlier, later = phases[:idx], phases[idx + 1:]
        if earlier:
            out += ["## Settled by earlier phases (their done-record "
                    "summaries)", ""]
            out += _done_records(earlier, summary=True)
        if later:
            out += ["## Later phases (edit them in the plan if your work "
                    "changes them)", ""]
            out += [f"- P{p.id} — {p.title} (Target: {p.target})"
                    for p in later] + [""]
    if criteria:
        out += ["## Acceptance criteria (verification.json — the test phase "
                "checks them off, not you)", ""]
        for item in criteria:
            area = item.get("area")
            tag = f" ({area})" if area else ""
            out.append(f"- {item.get('id', '?')}{tag} — "
                       f"{item.get('description', '')}")
        out.append("")
    if touched:
        out += ["## Files earlier phases touched", ""]
        for repo, stat in touched:
            out += [f"{repo}:", "", "```", _trim_stat(stat), "```", ""]
    return "\n".join(out).rstrip() + "\n"


def _digest_sections(sections: dict[str, list[str]]) -> list[str]:
    """The plan's prose sections a digest carries verbatim (DIGEST_SECTIONS)."""
    out: list[str] = []
    for name, lines in sections.items():
        if name.lower().startswith(DIGEST_SECTIONS):
            out += _strip_blank(lines) + [""]
    return out


def _done_records(phases: list[Phase], summary: bool = False) -> list[str]:
    """Each phase's heading and its done-record — never its phase text,
    the near-miss distractor; a phase not done yet says so. With `summary`,
    a record that carries one gives its summary instead of the whole thing
    (`done_record_summary`) — what the writer's per-phase digest takes; the
    doc phase's whole-plan digest takes the records entire."""
    out: list[str] = []
    for p in phases:
        out += [f"### P{p.id} — {p.title}", ""]
        if not p.done:
            body = [f"Target: {p.target}", "(not done yet)"]
        elif summary:
            body = done_record_summary(p) or done_record(p)
        else:
            body = done_record(p)
        out += body + [""]
    return out


def build_slice_digest(plan_text: str) -> str:
    """The doc phase's digest of the whole plan: its title, the rulings
    sections, and every phase's done-record. That is all the doc steering
    the plan holds — the diff is the work list — so the writer reads this
    instead of the plan whole (8–18 k tokens read once and carried on every
    later turn, never referenced after the diff walk in the sessions
    read). The plan stays the file it opens for what a record points at."""
    title, sections = plan_sections(plan_text)
    phases, _ = parse_plan(plan_text)
    out: list[str] = ["---", "", "# Orientation digest — the whole slice", ""]
    if title:
        out += [f"**Slice.** {title}", ""]
    out += _digest_sections(sections)
    if phases:
        out += ["## What each phase settled (their done-records)", ""]
        out += _done_records(phases)
    return "\n".join(out).rstrip() + "\n"


def stamp_phase(plan_path: Path, phase_id: str, date: str) -> bool:
    """Append `✅ DONE <date>` to the phase's heading line — the driver's
    mechanical stamp, applied after review passed and the merge landed.
    Returns False when the heading is not there (the caller re-parses and
    routes that as a vanished phase)."""
    lines = plan_path.read_text().splitlines(keepends=True)
    pattern = re.compile(r"^###\s+P" + re.escape(phase_id) + r"\s+—\s+")
    for i, line in enumerate(lines):
        if pattern.match(line) and not DONE_STAMP_RE.search(line):
            lines[i] = line.rstrip("\n") + f" ✅ DONE {date}\n"
            plan_path.write_text("".join(lines))
            return True
    return False


# ---------------------------------------------------------------------------
# kc integration — project discovery, session drive, repo root
# ---------------------------------------------------------------------------


def _git_toplevel() -> Path:
    """The target repo's root, from `git rev-parse --show-toplevel` in the
    process cwd — not from __file__, which locates the plugin the driver
    ships in, never the repo being run."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: not inside a git repository (run the slice from the "
              "target repo).", file=sys.stderr)
        sys.exit(2)
    return Path(result.stdout.strip())


def load_project_dirs(cwd: Path) -> dict[str, Path]:
    """The valid component set + each component's *effective* cwd, from the
    target repo's `.kubecoder/project.yaml` via `kc project list
    --output=json`. The JSON is a bare array of {name, cwd, description} in
    manifest order; `cwd` is absolute and already resolved."""
    result = subprocess.run(
        ["kc", "project", "list", "--output=json"],
        cwd=str(cwd), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise Bailout(
            "protocol_failure",
            details="`kc project list --output=json` failed "
                    f"(rc={result.returncode}): "
                    f"{(result.stderr or result.stdout).strip()}",
        )
    try:
        entries = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        raise Bailout(
            "protocol_failure",
            details=f"`kc project list --output=json` emitted invalid JSON: {e}",
        ) from None
    return {e["name"]: Path(e["cwd"]) for e in entries}


# A gate command's outcome, as the phase gate, the sweep and the doc gate
# record it — and as a sweep row renders it.
GATE_OUTCOME_LABELS = {"green": "GREEN", "red": "RED",
                       "nothing_ran": "nothing ran",
                       # a sweep `test` row a gate ruling covers: not run
                       "waived": "WAIVED",
                       # red only because a `cexec` tool container is not in
                       # this pod (CEXEC_MISSING_RE): no suite ran, nothing
                       # for a session to fix — neither green nor red
                       "unrunnable": "UNRUNNABLE (tool missing)"}


def kc_outcome(returncode: int) -> str:
    """A `kc project <verb>` exit code as a gate outcome. rc 2, kc's usage
    error, reads as red here; the phase gate and the sweep, which name a
    component kc listed, bail on it first as a driver bug."""
    if returncode == 0:
        return "green"
    return "nothing_ran" if returncode == KC_NOTHING_RAN else "red"


def component_gate_argv(name: str) -> list[str]:
    """The test gate of one `kc project list` component."""
    return ["kc", "project", "test", "--project", name]


def touched_components(components: dict[str, Path], work_root: Path,
                       changed_names: str,
                       target_name: str) -> tuple[list[str], bool]:
    """The components other than `target_name` that a `git diff
    --name-only` listing (`changed_names`, paths relative to `work_root`)
    touches, in manifest order — and whether it touches a file no gate
    holds. A file is the component's whose cwd is the deepest directory
    holding it, `root` aside (components sharing that cwd all have it); a
    file outside every other component is root's, and where `components`
    lists no root, no gate holds it."""
    work = Path(work_root).resolve()
    dirs = {name: Path(cwd).resolve() for name, cwd in components.items()
            if name != ROOT_COMPONENT}
    touched: set[str] = set()
    for name in changed_names.splitlines():
        # a name git C-quoted (core.quotePath) keeps its directories
        name = name.strip().strip('"')
        if not name:
            continue
        path = work / name
        owners = [(len(d.parts), c) for c, d in dirs.items()
                  if path.is_relative_to(d)]
        if not owners:
            touched.add(ROOT_COMPONENT)
            continue
        deepest = max(depth for depth, _ in owners)
        touched.update(c for depth, c in owners if depth == deepest)
    uncovered = ROOT_COMPONENT in touched and ROOT_COMPONENT not in components
    return ([name for name in components
             if name in touched and name != target_name], uncovered)


def _git_in(root: Path, *args: str, env: dict | None = None) -> str:
    """`git <args>` in `root`, its stdout stripped; ValueError carrying git's
    own message when it fails. For callers outside the driver — and one
    inside it that needs an environment of its own — where `RunLoop.git`
    and its Bailout do not fit."""
    try:
        result = subprocess.run(["git", *args], cwd=str(root), env=env,
                                capture_output=True, text=True)
    except OSError as e:   # no such directory, no git
        raise ValueError(f"`git {' '.join(args)}` failed in {root}: "
                         f"{e}") from None
    if result.returncode != 0:
        raise ValueError(f"`git {' '.join(args)}` failed in {root}: "
                         f"{(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def content_tree(root: Path) -> str:
    """git's tree id of what the working tree at `root` holds now: tracked
    files as they are on disk, and untracked files git does not ignore —
    the tree `git add -A` and a commit would make. So it equals
    `HEAD^{tree}` on a clean tree, committing what is there leaves it as it
    was, and ignored files and timestamps are no part of it: it changes
    exactly when the content a gate would run on does.

    Hashed through a copy of the index, never the index itself — the
    writer's own gate runs this mid-session, and staging behind its back
    would change what it commits. A linked worktree's index is its own,
    which `--git-path` names. No index yet is an empty one. ValueError,
    with git's message, when git cannot say."""
    root = Path(root)
    index = Path(_git_in(root, "rev-parse", "--git-path", "index"))
    if not index.is_absolute():
        index = root / index
    try:
        with tempfile.TemporaryDirectory(prefix="content-tree-") as tmp:
            scratch = Path(tmp) / "index"
            if index.is_file():
                shutil.copyfile(index, scratch)
            env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
            _git_in(root, "add", "-A", env=env)
            return _git_in(root, "write-tree", env=env)
    except OSError as e:
        raise ValueError(f"the index of {root} could not be copied: "
                         f"{e}") from None


def _is_argv(value) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(isinstance(a, str) for a in value))


def _shape_problem(data, keys: dict[str, type]) -> str | None:
    """What keeps `data` from being an object with `keys`, each of its
    type — None when nothing does."""
    if not isinstance(data, dict):
        return "not a JSON object"
    for key, kind in keys.items():
        if not isinstance(data.get(key), kind) \
                or (kind is int and isinstance(data[key], bool)):
            return f"no `{key}` of type {kind.__name__}"
    return None


def gate_spec_problem(spec) -> str | None:
    """What makes `spec` no gate spec (`RunLoop._write_gate_spec`), None
    when it is one."""
    problem = _shape_problem(spec, {"phase": str, "round": int,
                                    "work_root": str, "gate_cwd": str})
    if problem:
        return problem
    if not _is_argv(spec.get("argv")):
        return "`argv` is not a command"
    if spec.get("fallback") is not None and not _is_argv(spec["fallback"]):
        return "`fallback` is not a command"
    touched = spec.get("touched")
    if touched is not None:
        problem = _shape_problem(touched, {"merge_base": str, "target": str,
                                           "waived": list})
        if problem or not all(isinstance(c, str) for c in touched["waived"]):
            return f"`touched` is off-shape: {problem or 'waived'}"
    return None


def writer_gate_record_problem(record) -> str | None:
    """What makes `record` no record of the `gate` wrapper's run
    (`run_writer_gate`), None when it is one."""
    problem = _shape_problem(record, {
        "phase": str, "round": int, "work_root": str, "gate_cwd": str,
        "start_tree": str, "end_tree": str, "started": str, "finished": str,
        "commands": list, "outcome": str})
    if problem:
        return problem
    if not record["commands"]:
        return "`commands` is empty"
    for command in record["commands"]:
        if _shape_problem(command, {"rc": int, "output": str}) \
                or not _is_argv(command.get("argv")):
            return "a command is off-shape"
    return None


def sweep_row_outcome(row: dict) -> str:
    """A sweep row's outcome — read off its `green` for a row recorded
    before rows carried one (a resume over an older plugin's sweep)."""
    return row.get("outcome") or ("green" if row.get("green") else "red")


class SessionResult:
    """The bits of a driven turn the driver consumes downstream: the claude
    sessionId (for --resume across rounds and the transcript locator) and the
    turn's final response text (read ONLY by session_limit_notice — outcomes
    always come from verdict files)."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.result_text: str = ""
        self.is_error: bool = False


def _kc_session_id(name: str, cwd: Path) -> str | None:
    """The claude sessionId from the headless status snapshot. `sessionId` is
    empty until the turn's first stream event (the engine captures it from
    `system/init`), so it is polled *during* the send as well as read after
    it — a send that hangs once the turn is over still leaves a resumable
    conversation behind."""
    try:
        result = subprocess.run(
            ["kc", "session", "status", name, "--output=json"],
            cwd=str(cwd), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        snapshot = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return snapshot.get("sessionId") or None


def _kc_send(name: str, prompt: str, cwd: Path, timeout: int,
             progress, tick=None) -> tuple[int, str]:
    """POST one turn to a headless session and consume its response to the
    terminal result (`kc session send` owns SSE reconnect). The condensed log
    (send's stderr under -v) streams to `progress`; the response text is
    returned so the caller can recognize the account's session-limit notice.
    `tick` is called once per loop iteration — at most a second apart — for
    whatever the caller wants to do while the turn runs; it never delays the
    deadline, which is re-checked immediately after it.

    Enforces `timeout`: on expiry it SIGINTs `kc session send`, which POSTs a
    worker interrupt so the turn is never stranded, then raises
    subprocess.TimeoutExpired (the caller's policy turns that into a bail)."""
    prompt_fd, prompt_path = tempfile.mkstemp(suffix=".prompt")
    resp_path = prompt_path + ".resp"
    try:
        with os.fdopen(prompt_fd, "w") as f:
            f.write(prompt)
        args = ["kc", "session", "send", name,
                "--prompt-file", prompt_path,
                "--response-file", resp_path, "-v"]
        proc = subprocess.Popen(
            args, cwd=str(cwd), text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                ready, _, _ = select.select(
                    [proc.stderr], [], [], min(remaining, 1.0))
                if ready:
                    line = proc.stderr.readline()
                    if not line:
                        break  # stderr EOF — the send is finishing
                    if progress:
                        progress(line.rstrip("\n"))
                elif proc.poll() is not None:
                    break
                if tick:
                    tick()
            proc.wait(timeout=30)
            try:
                response_text = Path(resp_path).read_text()
            except OSError:
                response_text = ""
            return proc.returncode, response_text
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)  # send POSTs an interrupt on SIGINT
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
    finally:
        for p in (prompt_path, resp_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def run_kc_session(
    prompt: str,
    cwd: str,
    timeout: int,
    agent: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    resume_session: str | None = None,
    extra_env: dict[str, str] | None = None,
    flags: Sequence[str] | None = None,
    progress=None,
    on_session=None,
) -> tuple[int, SessionResult]:
    """Drive one headless kc session to completion; return (returncode,
    result). Maps each seam onto a kc verb:
      create-headless [--resume ID] [--agent ROLE] [--model M]
                      [--reasoning-effort E] --cwd CWD [-e NAME=VALUE ...]
                      [FLAG ...]                 → the assigned session name
      send NAME --prompt-file P --response-file R -v   (synchronous; SSE)
      status NAME --output=json                  → the claude sessionId
      end NAME                                    (idempotent; always)

    `agent` is the bare role (e.g. "code-writer"); it is dispatched namespaced
    (`dev:code-writer`) and resolves to the plugin's own definition wherever
    `cwd` sits. A falsy `agent` spawns with no agent at all (consults).
    `flags` are claude flags kc passes through verbatim (`spawn_flags`).
    Raises subprocess.TimeoutExpired on timeout — the turn is interrupted
    and the session torn down before it propagates."""
    result = SessionResult()

    create_args = ["session", "create-headless", "--cwd", str(cwd)]
    if resume_session:
        create_args += ["--resume", resume_session]
    if agent:
        create_args += ["--agent", f"{AGENT_NAMESPACE}:{agent}"]
    if model:
        create_args += ["--model", model]
    if effort:
        create_args += ["--reasoning-effort", effort]
    for name, value in (extra_env or {}).items():
        create_args += ["-e", f"{name}={value}"]
    create_args += list(flags or ())

    created = subprocess.run(
        ["kc", *create_args], cwd=str(cwd), capture_output=True, text=True)
    if created.returncode != 0:
        result.result_text = (created.stderr or created.stdout).strip()
        result.is_error = True
        return created.returncode or 1, result
    session_name = (created.stdout.strip().splitlines() or [""])[-1].strip()
    if not session_name:
        result.result_text = "kc session create-headless printed no session name"
        result.is_error = True
        return 1, result

    # The session id is learned while the turn runs, not after it: a send
    # that hangs once the model is done still has to leave a resumable
    # conversation on record, and `on_session` is what records it.
    reported: list[str] = []
    next_poll = [0.0]

    def poll_session_id() -> None:
        if reported or time.monotonic() < next_poll[0]:
            return
        next_poll[0] = time.monotonic() + SESSION_ID_POLL
        sid = _kc_session_id(session_name, Path(cwd))
        if not sid:
            return
        reported.append(sid)
        result.session_id = sid
        if on_session:
            on_session(sid)

    try:
        returncode, response_text = _kc_send(
            session_name, prompt, Path(cwd), timeout, progress,
            tick=poll_session_id)
        result.result_text = response_text
        # The post-send read is the final word — an engine that re-minted the
        # conversation mid-turn ends on an id nobody has been told about yet.
        final = _kc_session_id(session_name, Path(cwd))
        if final:
            result.session_id = final
        if on_session and result.session_id \
                and result.session_id not in reported:
            on_session(result.session_id)
        result.is_error = returncode != 0
        return returncode, result
    finally:
        # Best-effort teardown: never let cleanup hang the driver or mask the
        # exception that is propagating (e.g. a timeout).
        try:
            subprocess.run(
                ["kc", "session", "end", session_name],
                cwd=str(cwd), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# The devlock — the cooperative occupancy lease over the single dev instance,
# a flock on the inode `devlock.lease` names (the spec repo is the shared
# mount every contending code repo can see, and devlock.sh flocks the same
# file). The driver holds it for the test phase — taken before it, released
# once the phase is clean and the push check has passed — and again for the
# doc landing's push; the doc phase's writing and gating, the slow part, run
# without it. Under a hold pushing and rolling dev is pre-authorized — the
# lock IS the coordination. Held in-process so a driver crash releases it via
# fd close.
# ---------------------------------------------------------------------------

class DevLock:
    def __init__(self, lease: Path | None):
        self.lock_path = lease
        # devlock.sh's own convention: a human-readable note beside the lock.
        self.holder_path = lease.parent / "dev-holder" if lease else None
        self._fd = None

    @property
    def configured(self) -> bool:
        """A project that names no lease has nothing to coordinate — one dev
        instance is a fact about a deployed project, not about every repo the
        pipeline drives. The lock degrades to a no-op."""
        return self.lock_path is not None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def holder_note(self) -> str:
        try:
            return self.holder_path.read_text().strip()
        except (OSError, AttributeError):
            return "(no holder note)"

    def acquire(self, purpose: str, log, sleep) -> None:
        if not self.configured or self._fd is not None:
            return
        self._fd = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o644)
        deadline = time.monotonic() + DEVLOCK_MAX_WAIT
        logged = False
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not logged:
                    log("devlock held — waiting; holder:\n"
                        + self.holder_note())
                    logged = True
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise Bailout(
                        "devlock_timeout",
                        details="the dev occupancy lease stayed held for "
                                f"{DEVLOCK_MAX_WAIT}s; holder:\n"
                                + self.holder_note(),
                    ) from None
                sleep(DEVLOCK_POLL)
        session = os.environ.get("DEVLOCK_SESSION",
                                 f"run_loop[{os.getpid()}]")
        self.holder_path.write_text(
            f"session: {session}\npurpose: {purpose}\n"
            f"acquired: {_now_iso()}\npid: {os.getpid()}\n")
        log(f"devlock ACQUIRED ({purpose})")

    def release(self, log) -> None:
        if self._fd is None:
            return
        try:
            self.holder_path.unlink(missing_ok=True)
        except OSError:
            pass
        os.close(self._fd)
        self._fd = None
        log("devlock released")


# ---------------------------------------------------------------------------
# The slice lock — one driver per slice folder. A slice's run record lives in
# the spec repo, which is the mount every environment shares; the code repo it
# branches is not. Two drivers on one folder therefore write one log.txt, one
# state.json and one phases/** while branching two different repositories, and
# the second finds no phase branch where the record says work is committed —
# so it rebuilds the branch from base and the first driver's commit is gone
# with no trace in the record. flock, so a driver that dies releases it by
# construction and a --resume walks straight in; taken non-blocking, because a
# second driver is a mistake to report, not a queue to join.
#
# The note names the holder for whoever finds the lock taken: the KubeCoder
# environment, host and pid, and a heartbeat. The environments of one project
# share the spec repo's mount — the flock reaches across them — but not their
# process tables, so `ps` in one pod cannot see a driver in another; the note
# says which environment to look in, and the beat that its driver still runs.
# ---------------------------------------------------------------------------

# How often a held lock's note is rewritten with a fresh `heartbeat:` stamp.
HEARTBEAT_S = 60


def _heartbeat_stamp() -> str:
    """The note's `heartbeat:` value: the local wall clock to the second —
    the same length at every beat, so a reader caught between a rewrite's
    write and its cut still reads one whole note."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_note(fd: int, data: bytes) -> None:
    """The whole note, overwritten in place: written over from byte 0, then
    cut to its length — never truncated to nothing first, so a reader never
    meets an empty note on a held lock."""
    os.pwrite(fd, data, 0)
    os.ftruncate(fd, len(data))


class SliceLock:
    def __init__(self, lock_path: Path, heartbeat_s: float = HEARTBEAT_S):
        self.lock_path = lock_path
        self.heartbeat_s = heartbeat_s
        self._fd = None
        # The note the lock file held when this driver took it. A clean
        # release truncates the note, so one left on a free lock is a driver
        # that died holding it — what the resume logs as a kill.
        self.previous_note = ""
        # The holder this lock's note names, set when it is taken — for the
        # loop's state file to record: environment (None outside KubeCoder;
        # the note says `(unset)`), host, pid, started.
        self.driver: dict | None = None
        self._stop: threading.Event | None = None
        self._beat: threading.Thread | None = None

    def acquire(self) -> str | None:
        """None when the lock is ours, the holder's note when it is not."""
        if self._fd is not None:
            return None
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            note = ""
            try:
                note = os.read(fd, 4096).decode(errors="replace").strip()
            except OSError:
                pass
            os.close(fd)
            return note or "(no holder note)"
        try:
            self.previous_note = os.read(fd, 4096).decode(
                errors="replace").strip()
        except OSError:
            self.previous_note = ""
        self.driver = {
            "environment": os.environ.get("KUBECODER_ENVIRONMENT_ID") or None,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "started": _now_iso(),
        }
        _write_note(fd, self._note())
        self._fd = fd
        self._stop = threading.Event()
        self._beat = threading.Thread(
            target=self._heartbeat, args=(fd, self._stop),
            name=f"heartbeat {self.lock_path.name}", daemon=True)
        self._beat.start()
        return None

    def _note(self) -> bytes:
        d = self.driver
        return (f"environment: {d['environment'] or '(unset)'}\n"
                f"host: {d['host']}\npid: {d['pid']}\n"
                f"started: {d['started']}\n"
                f"heartbeat: {_heartbeat_stamp()}\n").encode()

    def _heartbeat(self, fd: int, stop: threading.Event) -> None:
        """Rewrite the note with a fresh beat until `release` stops it — the
        note's only writer while the lock is held, through the lock's own
        fd. A write that fails is skipped and the next beat tries again: the
        driver's work never hangs on its note, and a mount that hiccups once
        must not silence the beat for the rest of the run."""
        while not stop.wait(self.heartbeat_s):
            with contextlib.suppress(OSError):
                _write_note(fd, self._note())

    def release(self) -> None:
        if self._fd is None:
            return
        # The beat stops before the note is cut: one it rewrote after that
        # would read, on a free lock, as a driver that died holding it.
        self._stop.set()
        self._beat.join()
        os.ftruncate(self._fd, 0)
        os.close(self._fd)
        self._fd = None


def lock_held(lock_path: Path) -> bool:
    """Whether a driver holds `lock_path` now — taken non-blocking and let go
    at once. The flock is the liveness test, not the note's pid: the kernel
    drops it with the process, and no other process inherits it the way a
    pid is reused."""
    try:
        fd = os.open(lock_path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def holder_note(lock_path: Path) -> str:
    try:
        return lock_path.read_text(errors="replace").strip()
    except OSError:
        return ""


def note_fields(note: str) -> dict[str, str]:
    """A holder note's `key: value` lines (environment, host, pid, started,
    heartbeat)."""
    fields = {}
    for line in note.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def driver_line(record: dict | None, lock_path: Path) -> str:
    """A loop's `status` line for its driver: who the state file says runs
    it (`SliceLock.driver`, recorded at the run's start), and whether
    `lock_path` is held now — with the heartbeat the live note carries, the
    one sign of life a reader in another environment gets. A lock held by
    someone the record does not name (a driver that has not recorded itself
    yet, or one of a plugin that never did) is named from its note."""
    rec = record if isinstance(record, dict) else {}
    named = (f"env {rec.get('environment') or '(unset)'}  "
             f"host {rec.get('host') or '?'}  pid {rec.get('pid') or '?'}  "
             f"started {rec.get('started') or '?'}") if rec else "(not recorded)"
    if not lock_held(lock_path):
        return f"driver: {named} — not running"
    note = note_fields(holder_note(lock_path))
    beat = note.get("heartbeat") or "(none)"
    if rec and (note.get("host"), note.get("pid")) == (rec.get("host"),
                                                       str(rec.get("pid"))):
        return f"driver: {named} — running, heartbeat {beat}"
    return (f"driver: {named} — {lock_path.name} is held by env "
            f"{note.get('environment') or '?'}  host {note.get('host') or '?'}"
            f"  pid {note.get('pid') or '?'}, heartbeat {beat}")


# ---------------------------------------------------------------------------
# Dispatch prompts. Role contracts live in the agent definitions; prompts
# carry only instance data. Consults run bare, so their prompt is the
# protocol.
# ---------------------------------------------------------------------------

EXECUTOR_PROMPT = """\
Execute phase P{phase_id} of slice {slice_name}: implement exactly that
phase. Its Target is {target}; work on branch {branch}, which is checked
out{where}. The repo is truth for current state, the plan for intent.

The plan is digested below — your phase whole and everything settled
around it, from the plan as it stands. The plan itself is {plan_path}: edit
it there (your done-record, later phases your work changes) and open it for
what the digest points at — an attachment, a later phase's text — rather
than re-reading it whole.

Run the phase's test gate yourself before handing back{gate_hint}.

When done:
- Append the phase's done-record in the plan, under the phase's own heading
  (never a new `###` heading), in the plan template's two-part shape: the
  `**Done (P{phase_id}).**` paragraph and its `Later phases:` list first,
  then the record. Edit later phases your work changes, in place.
- Commit everything: code on the branch; the plan edit in the specs repo,
  staged by name (shared working tree).
- Write your verdict to {verdict_path}.
{pointers}"""

# Carried by every dispatch that writes or reviews code. The project's
# change-discipline doc lives at a path only the config knows, and
# code-writer's "delete, don't tombstone" rule defers to it by name.
PHILOSOPHY_LINE = """
This project's change-discipline doc is {philosophy} — its rules bind this
work.
"""

# Carried by every dispatch: where the slice's close-out report is and that
# close_out.py is the only way to write to it (close_out.dispatch_line — one
# sentence, shared with the plan loop). The agent registers hold the rule
# (out-of-scope observations go there, append only), the tool mints the
# shape — the prompt carries the path and the tool, once.
CLOSE_OUT_LINE = """
{dispatch_line}
"""

# Carried by a dispatch whose plan text names a skill (resolve_skills): the
# role has no Skill tool, so it is pointed at the installed file — the
# version an interactive session would load, never a search of the cache.
# The plan loop's dispatches carry it for the slice, the run loop's for the
# phase: its executor, fix rounds and reviewer.
SKILL_LINE = """
Skills {whose} names. This session has no Skill tool: each skill is the
file named here — read it before the work it governs.
{rows}
"""


def skill_line(skills: list[tuple[str, Path | None]], whose: str) -> str:
    """SKILL_LINE over resolve_skills' answer — empty when it named none, so
    a dispatch with no skill is the prompt it always was."""
    if not skills:
        return ""
    rows = [f"- `{name}`: {path}" if path else
            f"- `{name}`: the installed {name.split(':', 1)[0]} plugin has "
            "no such skill — work without it, and do not search for it."
            for name, path in skills]
    return SKILL_LINE.format(whose=whose, rows="\n".join(rows))


def skills_named(skills: list[tuple[str, Path | None]]) -> str:
    """The driver's log line for the skills a dispatch was pointed at."""
    return "skills named — " + ", ".join(
        name if path else f"{name} (not installed)" for name, path in skills)


# Carried by every executor dispatch whose target a gate ruling covers: the
# driver runs no gate there, and the writer's own `kc project test` may be
# red for the reason the operator ruled on.
GATE_WAIVED_NOTE = """
The driver's test gate for {target} is waived by the operator's ruling in
plan.md's `## Driver rulings` (substitute: {substitute} — {why}): a red
`kc project test` there is not this phase's to fix. Cite the substitute's
result in your done-record where you can reach it; where it needs a push,
the test phase owns it.
"""

# Carried by a phase's first code-writer dispatch after a resume set a dead
# round's uncommitted work aside (`_set_aside`, AIWF-58), one sentence per
# record. The round may have written its done-record and died before its
# commit, so the plan can describe work the tree no longer holds.
SET_ASIDE_LINE = """
{records} Take what you can use from what was set aside; none of it is in
the tree's tracked files now. A dead round's done-record in plan.md, if it
wrote one, may describe the patch rather than the tree.
"""


def set_aside_line(records: list[dict]) -> str:
    """SET_ASIDE_LINE over a phase's `set_aside` records."""
    sentences = []
    for rec in records:
        n = rec["files"]
        untracked = (f", and `{rec['untracked']}` holds copies of its {n} "
                     f"untracked file{'' if n == 1 else 's'} — those files "
                     "are still in the tree" if rec["untracked"] else "")
        sentences.append(
            f"Code-writer round {rec['round']} of this phase died with "
            "uncommitted work, and the resume set it aside before resetting "
            f"the branch to its last commit: `{rec['patch']}` is its `git "
            f"diff HEAD`{untracked}.")
    return SET_ASIDE_LINE.format(records=" ".join(sentences))


# Carried by every code-writer dispatch of a phase whose target's
# `origin/<base>` holds commits the local base lacks once the driver has
# fetched it and, on a fresh phase, fast-forwarded what it could
# (`_sync_base`): the bases diverged, the fast-forward was skipped, or a
# resume finds origin moved since the cut. The driver merges and rebases
# nothing for the phase; the writer is told.
ORIGIN_AHEAD_LINE = """
origin/{base} is {ahead} commit(s) ahead of the local {base} this phase's
branch was cut from{own}; {touches}. The driver has neither merged nor
rebased.
"""

# `{red_cmds}` is every gate command that went red, each in backticks: a
# component Target's gate also runs each component its diff touches (AIWF-91),
# and the red may be one of those rather than the Target's own.
EXECUTOR_GATE_FIX_PROMPT = """\
The test gate for phase P{phase_id} of slice {slice_name} is red (branch
{branch}, fix round {round}). The plan: {plan_path}, digested below.

The gate went red on {red_cmds}; its output is in {gate_log}. The gate is
fail-fast and terse, so the log ends at the FIRST failing statement — there
may be more behind it. The phase's work so far is git diff
{merge_base}..HEAD{where}. Make the gate green without weakening what it
checks; run the gate yourself before handing back{gate_hint}. Commit your
fixes, update the phase's done-record if what landed changed, then write your
verdict to {verdict_path}.
{pointers}"""

EXECUTOR_REVIEW_FIX_PROMPT = """\
You are resolving review findings for phase P{phase_id} of slice
{slice_name}. The plan: {plan_path}, digested below.

The code-reviewer found issues with the phase's branch (the work under review
is git diff {merge_base}..HEAD on {branch}{where}). Read {review_path} and
resolve every finding tagged blocking — the reviewer describes problems; the
fix design is yours.
Resolve each blocking finding failure-first. If its anchor is executable — a
failing test, a repro trace, analyzer output — witness the failure before
changing code: write the failing test or run the claimed repro. Witnessed,
fix it; the witnessing test rides your commit as the regression test. If you
cannot make it fail, the finding is refuted: change no code for it and report
it in your verdict's `refuted` list — its id plus one line of evidence, what
you ran or wrote and why it cannot fail. The loop records the refutation; do
not argue it in prose. Findings anchored by inspection — a requirement
contradiction, a coverage gap — have no failure to witness: check the cited
requirement and resolve them directly.
Findings tagged advisory are NOT yours to fix: they stay in the review file
and the close-out report, and the residue rider mops up the mechanical ones.
An advisory fixed here widens the next round's re-review to everything the
fix touched and breeds its own findings — comment fixes especially. Leave
them. The phase's section in the plan carries its intent; earlier rounds'
reviews sit next to this one — check them before re-deciding anything.
For a finding about prose the default fix is deleting or narrowing the claim,
not rewording it — a fix that grows the section is suspect. Run the gate
yourself before handing back{gate_hint}. Commit your fixes, update the
phase's done-record if what landed changed, then write your verdict to
{verdict_path}.
{pointers}"""

# Appended by the driver to a round's review file when the fix round refuted
# findings, so the next round's reviewer reads the refutation where it reads
# the findings — one record, never relitigated.
REFUTATION_TAG = """

## Refuted findings (fix round after review round {round})

The fix round witnessed each of these findings' claimed failures and could
not make them fail. They are refuted — settled by that evidence and
recorded in the close-out report with the refutation attached; they fund no
further work:

{entries}
"""

OPERATOR_RULING_TAG = """

## Operator ruling (post-round-{round} question)

The fix round's executor bailed with a question:

> {question}

The operator has ruled. The ruling is in the plan doc's requirements/rulings
section — living text, authoritative. Read it there and implement it as part
of resolving this review.
"""

REVIEWER_PROMPT = """\
Review the complete branch diff for phase P{phase_id} of slice {slice_name}
(review round {round}): git diff {merge_base}..HEAD on branch
{branch}{where}.

The requirements are the phase's section in {plan_path} — its outcome and
constraints; read the whole plan for context, and treat its
requirements/rulings section as authoritative on intent — plus the slice's
acceptance criteria in {verification_path} and this repo's conventions.
Judge outcomes, not approach. The slice spans multiple phases — only this
phase's scope is under review; end-to-end testing and prose docs have their
own later phases, so their absence here is not a finding.

{secrets}{review_set}{gate_line}
{philosophy_line}{skill_line}{close_out_line}
Write your review to {review_path} and your verdict to {verdict_path}.
"""

REVIEWER_DELTA_PROMPT = """\
Re-review phase P{phase_id} of slice {slice_name} (review round {round}) on
branch {branch}{where}. Round {prev_round} reviewed the full branch diff and
found issues: {prev_review}. The executor's response since then is git diff
{fix_range} — that range is this round's subject; the rest of the branch
(git diff {merge_base}..HEAD) was reviewed last round and is context, not
re-review scope.

Verify that every round-{prev_round} finding tagged blocking is actually
resolved — re-open the code, do not take the executor's word — and review
the fix commits themselves for new problems, including interactions with the
branch code they touch. Advisory findings left unfixed are the protocol
working, not a gap — they are in the review file and the close-out report;
do not re-report them. A finding the fix round refuted — witnessed as
unable to fail, per the refutation record appended to the prior review — is
settled by that evidence: do not re-raise it unless a fix commit
invalidates the refutation. Ground the prior round already proved stays proved: re-derive a
premise (live system state, another repo's behavior) only where a fix commit
touches it. The requirements are unchanged: the phase's section in
{plan_path} and the acceptance criteria in {verification_path}.

{secrets}{review_set}{gate_line}
{philosophy_line}{skill_line}{close_out_line}
Write your review to {review_path} and your verdict to {verdict_path}.
"""

# The review set (AIWF-37), between the requirements and the gate paragraph
# of a reviewer dispatch, built by _review_set_paragraph. A phase may commit
# its work outside its Target — slice 036 left it as unpushed commits in
# thirteen /work/scratch clones — and plan.md's `Review:` line names the
# slice-folder file listing those clones and commits. The reviewer is pointed
# at the pairs the phase added or changed; a declared set with none, and an
# empty Target range with no set declared, are stated for the reviewer to
# report — handed an empty diff in silence, a review reads nothing and signs
# it off.
REVIEW_SET_NOTE = """\
This phase's review set lies outside its Target: plan.md's `Review:` line
for this phase names `{path}`, and these are the clone and commit pairs it
added or changed since the phase began — review each as part of this
phase's diff:

{bullets}\
"""

# A range that changes `kind: Secret` data (AIWF-51), handed to the reviewer
# as a file the driver wrote with that data stubbed. Dispatched as a bare
# `git diff`, slice 050's range printed every removed CA key and password
# into the reviewer's transcript before it knew what the diff held.
REVIEW_SECRETS_NOTE = """\
This range changes `kind: Secret` data, so the driver wrote it out with
that data stubbed: {path} holds `git diff --stat` and then the diff for
{ranges}, every line inside a Secret's `data:` or `stringData:` replaced by
a `[Secret <name>: N data lines]` stub{held_out}. Read the diff from that
file instead of running `git diff`, and do not open those Secrets' blocks
in the files themselves (`cat`, `sed -n`, `git show`): their values never
reach a transcript. A hunk's wider context comes through the redactor:
`git -C {root} diff -U<n> <range> -- <path> | python3 {tool} --root {root} <range>`.

"""

# A phase's `Never print:` line (AIWF-51): paths the plan says never reach a
# transcript, and the review commands' safe shape over them.
NEVER_PRINT_NOTE = """\
plan.md marks {paths} never to print for this phase. Run
`git -C {root} diff --stat <range>` first; then read the diff only filtered,
those paths held out and the rest piped through the redactor:
`git -C {root} diff <range> -- . {excludes} | python3 {tool} --root {root} <range>`,
where `<range>` is {ranges}. What the review needs of those paths comes
from commands that print none of their content: the stat, counts, names.

"""

REVIEW_SET_EMPTY_RANGE = """\
The Target's own range, `git diff {merge_base}..HEAD` in {root}, is empty:
these pairs are the phase's work.\
"""

# The review set's lines naming more than one commit for a clone (AIWF-62,
# slice 055), handed on as no pair: the reviewer finds the phase's commit on
# each and says which it took.
REVIEW_SET_AMBIGUOUS_NOTE = """\
plan.md's `Review:` line for this phase names `{path}`, and these lines the
phase added or changed there each name more than one commit for one clone.
A ledger line holds one sha; the driver cannot tell which is the phase's
commit and which a parent or a base, so it hands none of them on as a range:

{bullets}

Find the phase's commit on each line (`git -C <clone> log`), review it as
part of this phase's diff, and say in your review which commit you took
for each line.\
"""

REVIEW_SET_AMBIGUOUS_EMPTY_RANGE = """\
The Target's own range, `git diff {merge_base}..HEAD` in {root}, is empty:
the phase's work is what the lines above name.\
"""

REVIEW_SET_NONE_NOTE = """\
plan.md's `Review:` line for this phase declares a review set outside its
Target, `{path}`, and {state}; the Target's own range,
`git diff {merge_base}..HEAD` in {root}, is {range_state}. Report it in your
review: either the phase's work is somewhere else — find it and name where —
or the phase delivered nothing toward its outcome.\
"""

REVIEW_EMPTY_RANGE_NOTE = """\
`git diff {merge_base}..HEAD` in {root} is empty — the phase committed
nothing to its Target, and plan.md declares no review set outside it (no
`Review:` line on this phase). Report it in your review: either the phase's
work is somewhere else — find it and name where — or the phase delivered
nothing toward its outcome.\
"""

# Stated in every reviewer dispatch so the review does not spend turns
# re-running the suite the driver already ran. The green claim is only made
# when it is backed by this commit (see _gate_line) — a reviewer told "green"
# about a different commit would be worse than one told nothing. `{gate_cmds}`
# is the green commands, each in backticks; `{covers}` names the projects they
# cover (GATE_COVERS_SENTENCE) — a component Target's gate also runs every
# component its diff touches (AIWF-91: PilotApp's `Target: frontend` phase
# committed backend code and tests, and its reviewer was told GREEN about
# frontend's suite alone) — and is empty for a gate that recorded no projects
# (a whole-repo Target, or a phase begun on an older plugin).
GATE_GREEN_LINE = """\
The deterministic test gate ran GREEN on this exact commit ({green_at}):
{gate_cmds} in {gate_repo} — with full output in {gate_log}.{covers} The tests
pass; that is an established input to your review, not something to
re-derive. Do not re-run the suite to confirm it. Targeted runs remain
yours to make where they buy a finding: a single test you suspect is vacuous,
a case the diff leaves uncovered, a mutation that proves a test actually
catches the behavior it claims. The green says the tests pass, never that
they are adequate.\
"""

GATE_COVERS_SENTENCE = """ It covers
{covered}: the phase's Target and every project its diff touches."""

# Closes the GREEN paragraph when a project the gate took in is not green: one
# that ran nothing, or one a gate ruling waived (AIWF-91). A red one never
# reaches a reviewer — a red gate is a fix round.
GATE_UNCOVERED_LINE = """\
The gate does not cover {uncovered}: their test state is unverified by
the driver — say so in your review where it bears on a finding, and probe
it with targeted runs.\
"""

# Why a project in GATE_UNCOVERED_LINE is not covered, by its gate outcome.
GATE_UNCOVERED_WHY = {
    "nothing_ran": "defines no tests",
    "waived": "waived by plan.md's `## Driver rulings`",
}

GATE_UNVERIFIED_LINE = """\
No deterministic test gate is recorded green against this commit — the
branch's test state is unverified: say so in your review where it bears on
a finding, and probe it with targeted runs; the suite is still not yours to
run.\
"""

# The unverified line's reason, when kc itself said why: the gate ran on this
# commit and found nothing to run (KC_NOTHING_RAN). `{gate_cmd}` is every
# command that ran nothing, each in backticks — the Target's and those of the
# components its diff touches (AIWF-91).
GATE_NOTHING_RAN_LINE = """\
{gate_cmd} in {gate_repo} ran nothing on this exact commit ({ran_at}):
the target defines no tests, so the branch's test state is unverified — say
so in your review where it bears on a finding, and probe it with targeted
runs.\
"""

# The unverified line's reason, when the operator gave it: plan.md's
# `## Driver rulings` waives this target's gate, so the driver ran nothing.
GATE_WAIVED_LINE = """\
The driver did not run the test gate on this commit: plan.md's `## Driver
rulings` waives it for {target}, naming {substitute} as the gate — {why}.
The branch's test state is unverified by the driver: say so in your review
where it bears on a finding, and probe it with targeted runs; the suite is
still not yours to run.\
"""

# Closes whichever gate paragraph a reviewer dispatch carries when the phase
# has a review set outside its Target (AIWF-37): the gate ran in the Target's
# repo alone. Slice 036's reviewer was told GREEN about Ansible's root suite,
# which its phase never touched, and nothing about the thirteen clones it had
# committed into. The driver runs no suite in a review set's clones — it only
# says that it did not.
GATE_REVIEW_SET_LINE = """\
That gate is {gate_repo}'s suite alone: the driver ran no suite in the
review set's repos ({clones}), so their test state is unverified by the
driver — say so in your review where it bears on a finding, and probe it
with targeted runs.\
"""

# The review-funding bar: stated by the driver (which knows the round number
# and what the fix range touched), judged by the consult (which reads the
# findings). Discrete steps — each admits roughly an order of magnitude fewer
# findings: round cost is flat while the marginal value of review rounds
# decays hard.
REVIEW_BAR_BLOCKING = """\
Fund a fix round only for findings the review shows to be blocking — merging
them would harm the product (data corruption, a broken flow, a wire-contract
claim a consumer would implement against). Advisory, Minor-only, or
prose-only findings go to the close-out report, not a fix round here.\
"""
REVIEW_BAR_BLOCKER = """\
Only Blocker-grade harm funds another round — data corruption, a broken core
flow, a wire-contract falsity a consumer would implement against. Ordinary
Majors, and anything prose, merge and go to the close-out report.\
"""
REVIEW_BAR_CRITICAL = """\
Only a `critical` verdict — the phase's premise or the slice itself in
question — funds another round. Everything else merges (recorded in the
close-out report) or bails.\
"""

REVIEW_PROSE_FACT = """\
Deterministic fact from the driver: the fix commits this round reviewed
({fix_range}) touched no production code — only tests and docs — so the bar
below is already one step above this round's default.

"""

REVIEW_FUNDING_SITUATION = """\
Review round {round} for phase P{phase_id} reported `{outcome}`: the findings
are in {review_path}, each tagged blocking or advisory. The executor has not
yet acted on them. Decide whether they fund another executor fix round, or
the phase merges now — findings never vanish: on merge, every unresolved
finding stays in the review file and the driver records the merge in the
close-out report for the operator.

{prose_fact}This is review round {round} of at most {cap} for this phase; the
funding bar rises every round, and at this round it is:

{bar}

Judge the findings against that bar on the review's own evidence. A red gate
cannot merge regardless of your choice.\
"""

REVIEW_BUDGET_SITUATION = """\
Review round {round} for phase P{phase_id} reported `{outcome}`
({review_path}) and this phase's review budget ({cap} rounds) is exhausted —
no further fix round can be funded. Decide whether the phase merges with its
unresolved findings recorded in the close-out report for the operator, or the
slice stops.\
"""


def _review_bar(round_: int, prose_only: bool) -> str:
    """The funding bar for a consulted review round. A prose-only fix range
    (no production code touched) applies the next round's bar a step early."""
    effective = round_ + (1 if prose_only else 0)
    if effective <= 2:
        return REVIEW_BAR_BLOCKING
    if effective == 3:
        return REVIEW_BAR_BLOCKER
    return REVIEW_BAR_CRITICAL


# The generation bar on appended work (completion consult + test phase).
GENERATION_BARS = {
    1: """\
This is the loop's first follow-up generation: append a phase only for work
the plan owes and no phase delivered — a requirement or ruling nothing
carried out, an acceptance criterion with no implementing work to point at.
Price it: a phase costs an executor round, a review round and the consult
this generation forces; a close-out entry costs the operator one word.
Everything else — out of scope, advisory, in scope but not owed — goes in
the close-out report, never a phase.\
""",
    2: """\
This is the loop's second follow-up generation: append BLOCKING work only —
work without which the slice's acceptance criteria are not met or the product
is harmed. Everything else goes in the close-out report. A generation after
this one bails to the operator, so append nothing you would not stop the
slice over.\
""",
}

# The rider holds at every generation: run-created mechanical residue is
# fixed on the spot — a fix is not a report.
GENERATION_RIDER = """\
Exception, at every generation: mechanical residue — comment or formatting
fixes with no behaviour change, in files this slice's diff already touched —
is neither reported nor appended. Fix it in this session: make the edit, keep
gofmt honest where the change is Go, and commit to the checked-out branch.
The driver's lint+build+test sweep re-runs on any commit it has not seen, so
the fix is gated before the loop closes — but never before a push your own
procedure doc orders, so keep the tree green as you commit.\
"""

COMPLETION_CONSULT_SITUATION = """\
Every phase of the plan is stamped done. Judge honestly, against both the
plan and the repo: does the plan describe outstanding work? Signals worth
checking: an acceptance criterion in {verification_path} whose implementing
work you cannot point at; a done-record that admits a leftover; a
requirement or ruling in the plan not delivered by any phase; a later phase
edited to depend on something nothing produced.

{sweep_block}

{push_owed_block}{test_owed_block}{generation_bar}

If outstanding work clears that bar, append new phases to {plan_path}
(`### P<id> — <title>` with a `Target:` line; a suffix like P3a inserts
between P3 and P4 — document order is authoritative) and answer `appended`.
Record everything that does not clear the bar as entries in the close-out
report — and you are the one pass that reconciles that report, through
close_out.py (its path and its verbs' arguments are in this prompt) and
never by editing the file: strike, `--by "consult <n>"`, what you absorbed
into an appended phase (`--reason "absorbed by P<x> (<commit>)"`),
duplicates you are sure of (`--reason "duplicate of B3"`), and what a phase
resolved (`--reason "resolved by P<x> (<commit>): <what was re-run>"`);
record any other observation about an entry with `note`. If nothing is
outstanding, answer `complete`.\
"""

# The close-out entries close_out.owed_before_push picks, as they ride the
# completion consult: the report is worked after the push, and nothing reads
# it before (DHCPApp slice 001's B3 — production IPs in public tests).
PUSH_OWED_BLOCK = """\
Owed before the push. The push that follows this consult — the test
phase's, or the driver's where the project runs none — publishes what this
slice committed, and nothing reads the close-out report before it. These
live entries may describe something that push must not carry:

{rows}

For each, judge what the push would carry. Where it carries what the entry
describes — a secret, production data, anything a push exposes — that is
outstanding work on this consult's table, as a RED row is: append a phase
that removes it, or answer `bail` with the question; where a phase already
removed it, strike the entry naming the commit. Where it carries none of it
— the content is on origin already, or nothing in it is exposed by a push —
say why in a `note` on the entry and leave it.\
"""

# The close-out entries close_out.owed_before_test picks, as they ride the
# completion consult where the project runs a test phase: that phase checks
# every criterion as worded, and the report is worked after it (AnsibleSpecs
# slice 058's P3 — V15 worded against ruling D2, reworded only because the
# consult happened to read the entry).
TEST_OWED_BLOCK = """\
Fix before the test phase. The test phase that follows this consult checks
every criterion in {verification_path} as it is worded and marks one the
slice has not earned `fail`, and nothing reads the close-out report before
it. These live entries say a criterion of this slice is worded wrong:

{rows}

For each, judge the criterion against the plan and its rulings. Where they
show the wording wrong, reword it to what they require and no further — a
reword never asks less than the plan does — commit it, and strike the entry
naming the commit. Where the wording is right and the slice falls short of
it, that is outstanding work on this consult's table: append a phase, or
answer `bail` with the question. Where neither holds, say why in a `note`
on the entry and leave it.\
"""

# The loop-tail sweep's report, as it rides the completion-consult and
# test-phase dispatches. Same contract as _gate_line's green claim: stated
# only about the exact commits it ran on (the driver re-sweeps whenever a
# swept HEAD moves, so the report a dispatch carries always describes the
# tree that dispatch sees).
SWEEP_BLOCK = """\
Deterministic fact from the driver — the loop-tail gate sweep: `kc project
lint` + `build` + `test`, run per component so every red is visible, on
exactly these commits:

{rows}

{stance}\
"""

SWEEP_STANCE_CONSULT_GREEN = """\
{every_row} is GREEN: those commands pass on the merged tree — an
established input to your judgment, not something to re-derive or re-run.
A `nothing ran` row found nothing to run for its verb and proves nothing
about it.\
"""

SWEEP_STANCE_CONSULT_RED = """\
One principle, no special cases: a branch whose gates are red is not
pushed — and the test phase, which runs next, is where this slice is
pushed. A RED row above is therefore outstanding work on this consult's
table: append a phase that fixes it, or answer `bail` with the question.
Either is acceptable; what `complete` asserts is that the tree is pushable
exactly as it stands.\
"""

SWEEP_STANCE_TEST_GREEN = """\
{every_row} is GREEN: those suites pass, as an established input — do
not re-run them to confirm it. A `nothing ran` row found nothing to run and
proves nothing. Targeted runs remain yours where they buy a
finding, and the re-validation your procedure doc orders after a rebase
still applies: a rebase produces a tree nothing has run against. One
principle, no special cases: a branch whose gates are red is not pushed —
a red you find after the rebase routes as a finding, without pushing.\
"""

SWEEP_STANCE_TEST_RED = """\
One principle, no special cases: a branch whose gates are red is not
pushed. A RED row above means this tree does not leave the machine as it
stands: route the red as a finding (append the fixing phase — a red gate
is blocking by definition), and push nothing until every gate is green.
The same holds for any red you find after the rebase.\
"""

# The green stances' subject — which rows the GREEN claim covers. A row a
# ruling covers is not green (an accepted row ran red), so with any the
# claim narrows.
SWEEP_EVERY_ROW = "Every row that ran"
SWEEP_EVERY_UNRULED_ROW = "Every row that ran and no ruling covers"

# Appended to the stance when a row renders WAIVED or accepted, so the
# consult and the test phase read those rows as rulings, not reds.
SWEEP_RULINGS_NOTE = """\
A WAIVED or accepted row is the operator's ruling in plan.md's `## Driver
rulings`, not a gate this tree failed: it does not block the push. A waived
test gate's substitute is the evidence the test phase cites for it — the
driver never verified those tests.\
"""

# Appended to the stance when a row is UNRUNNABLE, so the consult and the
# test phase neither read it as a red to fix nor try to add the tool.
SWEEP_UNRUNNABLE_NOTE = """\
An UNRUNNABLE row did not run: its statement calls a `cexec` tool container
this environment does not run. That gate is unverified, not red, and adding
the tool (a `.kubecoder/config.yaml` line and `kc env restart`, which ends
every session here) is the operator's — never this session's.\
"""

SWEEP_STANCE_NONE = """\
Nothing ran — no swept repo carries a kc manifest, or no swept component
defines a lint, build or test statement — so treat the tree's
lint/build/test state as unverified.\
"""

TEST_PHASE_PROMPT = """\
The phases of slice {slice_name} are all merged on {base_branch}. Run the
slice's test phase: read {test_plan_doc} and execute it for this slice — the
procedure, the gate semantics, and how findings route all live in that doc,
not in this prompt.

Deterministic facts from the driver:
- The driver holds the devlock. Under that hold, pushing and rolling dev for
  this slice's verification is pre-authorized — do not ask for permission.
{prd_line}
- The slice folder is {slice_dir}; the plan is {plan_path}. Check off
  {verification_path} as you verify (verdict + evidence per item).
- {close_out_line}
{hold_block}{rulings_block}
{sweep_block}

Findings route through a generation bar, stated for this pass:

{generation_bar}

A finding that clears the bar becomes a new phase appended to the plan
(`### P<id> — <title>` + `Target:` line); report `findings` so the loop
re-enters. A finding that does not clear it goes in the close-out report. A
clean pass reports `clean`. Commit what you write (specs files staged
by name), then write your verdict to {verdict_path}.
"""

DOC_PHASE_PROMPT = """\
The phases of slice {slice_name} are merged and the test phase is complete.
Run the slice's doc phase: read {doc_plan_doc} and execute it for this slice
— the procedure lives in that doc, not in this prompt.

Deterministic facts from the driver:
- The slice's shipped work is on disk, one file per repo, a section per
  merged phase and one per commit a phase's `Review:` ledger lists outside
  its Target — `git diff --stat` at the top of each, then that phase's or
  that commit's own diff. The files carry exactly what this slice's phases
  merged and committed: nothing another slice landed on the base branch
  meanwhile, nothing under the spec repo's `slices/` tree, and never your
  own doc commits. Write
  docs from that diff with the whole shipped behavior in view; read its
  hunks by path from the file (`grep -n`, `sed -n`) rather than re-running
  `git diff` — a diff past the tool's output limit round-trips through a
  persisted-output file and back, and this file already is that. Every
  line inside a `kind: Secret`'s `data:` or `stringData:` is a
  `[Secret <name>: N data lines]` stub there: a doc needs no more of it,
  so never read it back from git or the files themselves.
{diff_rows}
- The plan is {plan_path}, digested below: the rulings and every phase's
  done-record, which is all the doc steering the plan holds. Open the plan
  only for what the digest points at (an attachment a record names) — never
  read it whole. slice.md is not your input: the diff and the rulings are
  the steering.
- The slice folder is {slice_dir}.
- {close_out_line}
- Work on branch {branch}, which is checked out in {root} — the one repo
  that branch exists in. A doc edit in another code repo this slice touched
  (a diff row above names it, and does not say the driver pushes no doc
  edit there) is committed on the base branch checked out there,
  never on a new branch; the driver pushes it after the landing.
  Never push — any repo, any branch. After your hand-back the driver runs
  the full gate sweep —
  `kc project lint` + `build` + `test` (a red comes back to this session) —
  rebase-merges the branch onto {base_branch} and pushes; the dev roll that
  push triggers is left to land on its own.

Run the doc gates the doc names yourself as you work, commit, then write
your verdict to {verdict_path}.
"""

DOC_GATE_NUDGE_PROMPT = """\
The driver's full gate sweep is red after your doc-phase commits:
`kc project lint` + `build` + `test`, output in {gate_log}. The sweep is
fail-fast, so the log ends at the FIRST failing statement — there may be more
behind it. Fix what broke on branch {branch}
without weakening any gate — mechanical suite breakage may go to the
`dev:test-fixer` sub-agent — commit, and do not push. Do not start other work.
"""

HOLD_BLOCK = """\
- The plan holds these repos — pushing them is NOT part of this phase, and
  the driver's push check reports them held rather than asking you for them:
{rows}
  Everything else this slice committed is yours to push, per your procedure
  doc.
"""

WRAP_UP_PROMPT = """\
Slice {slice_name} is built: its phases are merged and tested, and what
is left of the run is its landing. Work through what the slice's close-out
report gives the wrap-up.

Deterministic facts from the driver:
- {close_out_line}
  The other verbs the wrap-up uses, with their arguments:
{close_out_verbs}
- What waits for you, as `worklist` prints it now:
{worklist}
- The repositories this slice touched, the branch your commits go on in
  each, and the gate you run on a fix there. A repository that is not in
  this list is not yours to change:
{repo_rows}
- The spec repo is {spec_root}. What you commit there — the report's store,
  a fold into another slice{spec_prose} — goes on the branch that is checked
  out, staged by name: other sessions share that tree.
{hold_block}- The plan is {plan_path}; the slice folder is {slice_dir}.
- Never push — any repo, any branch. After your hand-back the driver gates
  what you committed and lands it with the doc phase, or leaves all of it
  out.

Write your verdict to {verdict_path}.
"""

# The held repos as the wrap-up's dispatch names them — the rows HOLD_BLOCK
# carries, not its words: those tell the test phase that everything else is
# its to push, and the wrap-up pushes nothing.
WRAP_UP_HOLD_BLOCK = """\
- The plan holds these repos (`## Push holds`): they are not yours to
  change, and the driver cut no branch in them:
{rows}
"""

# The event a soft failure of the wrap-up enters. Its Consequence opens with
# "none", so the tool labels it closed and it sits in the record — never on
# the wrap-up's own work list, which a close-out session then reads.
WRAP_UP_LEFT_OUT_HEADLINE = "The wrap-up was left out of the landing: {reason}"
WRAP_UP_LEFT_OUT_CONSEQUENCE = (
    "none in this run — what the table gave the wrap-up still waits, and the "
    "close-out session dispatches it")

# The test-phase dispatch's prd line: fixed, unless plan.md's `## Driver
# rulings` authorize prd for named targets.
PRD_LINE = """\
  Pushing is this phase's, production included, wherever the project's
  deploy path is a push. Running a promotion pipeline is operator-gated —
  assume one wherever the project has more than one stage, unless its
  deploy-operations doc says the stages are separate environments with
  nothing promoted between them; nothing here runs it.\
"""
PRD_RULINGS_LINE = """\
  Pushing is this phase's, production included, wherever the project's
  deploy path is a push. Running a promotion pipeline is operator-gated —
  assume one wherever the project has more than one stage, unless its
  deploy-operations doc says the stages are separate environments with
  nothing promoted between them — except for these targets, which plan.md's
  `## Driver rulings` authorize: running their promotion pipeline is part
  of this test phase:
{rows}\
"""

RULINGS_BLOCK = """\
- plan.md's `## Driver rulings` waive the driver's test gate for these
  targets — the substitute named is the evidence to cite for each, and
  where it needs a push, that push is this phase's:
{rows}
"""

PUSH_NUDGE_PROMPT = """\
The test phase is not done: work this slice committed is not on origin —

{repos}

A reviewed-but-unpushed commit never reaches the deploy it was meant for.
Push what is owed, in whatever order these repos need,
per your procedure doc's push step — wait for the CI build it names, and redo
any live check the push invalidates. Do not start other work.
"""

CONSULT_PROMPT = """\
You are the workflow consult for slice {slice_name}. The run loop hit a
decision point it does not decide itself.

Situation: {situation}
{phase_line}Slice folder: {slice_dir} (state.json holds the run history)
{close_out_line} Out-of-scope findings and sub-bar leftovers go there as
entries; `list` before you write, add if in doubt.

Investigate as needed — read the material below, the plan, git log/diff.
{material}

Choose exactly one action:
{actions}

Write {verdict_path} as JSON:
  {{"outcome": "<action>", "summary": "<your reasoning, 1-5 sentences>"}}
Optionally write a longer write-up next to it as {consult_md_name}.
"""

PLAN_DOC_NUDGE_PROMPT = """\
Your session's edit left the plan doc unparseable for the driver. Fix the
plan doc now — {plan_path} — and commit the fix (specs repo, staged by
name). Do not start other work. The problems:

{problems}

The rules: phases are `### P<id> — <title>` headings (id [A-Za-z0-9]+,
unique; every other heading level is fine, but `###` is reserved for
phases); every unfinished phase opens with a `Target:` line naming a
`kc project list` component, a sibling repo path or `github:<owner>/<repo>`;
done-records go under the phase's own heading without new `###`s; only the
driver writes `✅ DONE` stamps.
"""

VERDICT_NUDGE_PROMPT = """\
Your session ended without writing a valid verdict file. Do not start new
work: if any of your work is uncommitted, commit it, then write your verdict
now to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}{outcomes}).
"""

LOST_WAIT_PROMPT = """\
Your session ended while it was waiting on background work — a sub-agent or
a backgrounded command — and that work's report was lost with the process:
the harness reports the task stopped with no completion record. The task ran
to its end or near it, and its transcript is saved. Recover its result rather
than guessing at it: resume the sub-agent with SendMessage and ask for its
report, read a command's output file, check the tree for what already landed;
re-dispatch only what cannot be recovered. None of that is new work. Then
finish from where you were — complete the phase, commit, and write your
verdict to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}{outcomes}).
"""

COMMIT_NUDGE_PROMPT = """\
Your session ended leaving uncommitted changes in the working tree. Commit
the work that belongs to this phase now (stage deliberately; drop anything
that should not be kept). Do not start new work.
"""

REATTACH_PROMPT = """\
Your session was interrupted mid-run (the driver process died — host
restart, quota stop, or similar). The interruption came from outside and
is not an outcome of your work: what your transcript and the working tree
already hold stands — carry on from it, and never report `blocked` for
having been stopped. The working tree is exactly as you left it. Reassess
where you were (git status, git log, the plan), finish your work, commit
it, then write your verdict to {verdict_path}.
"""


# ---------------------------------------------------------------------------
# Target resolution — the `Target:` line names where a phase lands, from
# which the driver roots its git operations and picks the gate.
# ---------------------------------------------------------------------------

class ResolvedTarget:
    def __init__(self, name: str, kind: str, git_root: Path,
                 gate_argv: list[str] | None, gate_cwd: Path,
                 manifest_gate: bool = False):
        self.name = name
        # What the Target names, not where it lives: "project" is a `kc
        # project list` component, gated on its own — the invoking repo's, or
        # a sibling repo's (git_root says which); "sibling" is a whole repo,
        # named by its path.
        self.kind = kind            # "project" | "sibling"
        self.git_root = git_root    # the repo: its base, merges, pushes
        self._gate_argv = gate_argv
        # A whole repo's gate is its manifest's, looked for whenever the
        # gate is read (`gate_argv`), not fixed when the Target resolved.
        self.manifest_gate = manifest_gate
        self.gate_cwd = gate_cwd
        # The working tree the phase's branch is checked out in — the repo's
        # own, except for a shared repo's phase, which works in a linked
        # worktree of its own (`RunLoop._ensure_worktree`).
        self.work_root = git_root

    @property
    def gate_argv(self) -> list[str] | None:
        """The gate's command, None for no deterministic gate. A whole repo
        (`manifest_gate`) gates through kc from its root when the phase's
        tree carries a manifest — read now, in `gate_cwd`, so a phase that
        bootstraps the repo's `.kubecoder/project.yaml` is gated by the
        manifest it wrote: the Target resolves at phase start, before the
        writer has written anything (AIWF-77)."""
        if not self.manifest_gate:
            return self._gate_argv
        return (list(REPO_GATE_ARGV)
                if (self.gate_cwd / MANIFEST_REL).is_file() else None)

    def in_worktree(self, path: Path) -> "ResolvedTarget":
        """This target as its phase works it from the linked worktree at
        `path`: everything that reads or changes a working tree, the gate
        among them, runs there; `git_root` stays the shared repo the branch
        merges into."""
        moved = copy.copy(self)
        moved.work_root = moved.gate_cwd = Path(path)
        return moved


# ---------------------------------------------------------------------------
# Tool containers — a manifest's `cexec <tool>` against the pod's sidecars
# (AIWF-24). A Target repo's `kc project` statements run in the sidecars
# *this* environment declares, and a repo planned from another environment
# may call one it lacks: FieldnotesApp slice 001's P6 gated FieldnotesDeploy
# from the AIWorkflow environment, which has no `aac-tools`, and the
# code-writer spent ten minutes before it handed back `blocked` — on a fix
# (a config.yaml line and `kc env restart`) that ends the very session that
# would resume the run. So it is the operator's, asked before any dispatch.
# ---------------------------------------------------------------------------

# A `cexec <tool>` call in a manifest line. The tool name starts with a
# letter or digit, so a flag (`cexec --help`) is never read as one.
CEXEC_CALL_RE = re.compile(r"\bcexec\s+([A-Za-z0-9][A-Za-z0-9_.-]*)")
# The token before a `cexec` that makes it a guarded probe, not a call the
# statement needs: `! cexec <tool> true || …` and `if cexec <tool> …; then`
# are a manifest asking whether the tool is there, and fine without it. A
# YAML-quoted statement leaves the quote on the token (`'!`); it is stripped.
# The `cexec <tool>` after `||` in a statement that opened with
# `! cexec <tool>` runs only when the tool is there, so it is guarded too;
# another tool after the `||` is not.
CEXEC_GUARDS = ("!", "if", "elif")
# Where a statement on a manifest line ends, and a `! cexec` guard's reach.
STATEMENT_END_RE = re.compile(r";|&&")
# A `- use: <tool>` item of the environment config's `tools:` list.
TOOL_USE_RE = re.compile(r"(?:-\s*)?use:\s*[\"']?([A-Za-z0-9][A-Za-z0-9_.-]*)")
# What cexec prints when the sidecar it is asked for does not exist — the
# line a gate log carries when a statement met a missing tool mid-run.
CEXEC_MISSING_RE = re.compile(r'cexec: tool "([^"]+)" is not available')
# The line `kc project <verb>` ends on: it prints a status line and the last
# few lines per statement, and keeps the whole run in a file it names here.
KC_FULL_OUTPUT_RE = re.compile(r"^full output: (/\S+)\s*$", re.M)

MANIFEST_REL = Path(".kubecoder") / "project.yaml"
ENV_CONFIG_REL = Path(".kubecoder") / "config.yaml"
RUN_RELAUNCH = "relaunch with --resume once the environment runs them"


class MissingTool:
    """A tool a manifest calls and the pod does not run: who calls it (the
    manifests, repo-relative), and whether the host environment's config
    already declares it — then only the restart is owed."""

    def __init__(self, tool: str, callers: list[str], declared: bool):
        self.tool = tool
        self.callers = callers
        self.declared = declared


def manifest_tools(text: str) -> set[str]:
    """The tools a `.kubecoder/project.yaml` calls through `cexec`, from its
    text. A line scan, never a YAML parse: the plugin does not read a
    manifest's structure (only kc does), and a `cexec <tool>` token is a
    call wherever it sits in a statement. Comment lines are skipped, and so
    is a guarded call (CEXEC_GUARDS)."""
    tools: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for statement in STATEMENT_END_RE.split(line):
            probed: set[str] = set()
            for match in CEXEC_CALL_RE.finditer(statement):
                tool = match.group(1)
                before = statement[:match.start()].split()
                token = before[-1] if before else ""
                prev = token.lstrip(";&|('\"")
                if prev == "!":
                    probed.add(tool)
                elif prev not in CEXEC_GUARDS and not (
                        token.endswith("||") and tool in probed):
                    tools.add(tool)
    return tools


def declared_tools(text: str) -> set[str]:
    """The tools an environment's `.kubecoder/config.yaml` declares — its
    `tools:` list's `- use: <tool>` items, by the same kind of line scan:
    comments skipped, the list ending at the next top-level key."""
    declared: set[str] = set()
    in_tools = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace() and not stripped.startswith("-"):
            in_tools = stripped.split("#")[0].strip() == "tools:"
            continue
        match = TOOL_USE_RE.match(stripped) if in_tools else None
        if match:
            declared.add(match.group(1))
    return declared


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


ENV_DESCRIBE_ARGV = ["kc", "env", "describe", "--output=json"]


def _env_list(key: str) -> list:
    """`kc env describe --output=json`'s top-level `key` list — what the pod
    was composed with. ValueError with the cause when kc does not answer
    that."""
    cmd = " ".join(ENV_DESCRIBE_ARGV)
    try:
        result = subprocess.run(ENV_DESCRIBE_ARGV, capture_output=True,
                                text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"`{cmd}` did not run: {e}") from None
    if result.returncode != 0:
        raise ValueError(f"`{cmd}` failed (rc={result.returncode}): "
                         f"{(result.stderr or result.stdout).strip()[:200]}")
    try:
        data = json.loads(result.stdout)
    except ValueError as e:
        raise ValueError(f"`{cmd}` emitted invalid JSON: {e}") from None
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"`{cmd}` carries no `{key}` list")
    return items


def _env_described(key: str) -> set[str]:
    """The `name`s of `kc env describe`'s top-level `key` list
    (`_env_list`). ValueError with the cause when kc does not answer that —
    the caller passes its check with a warning, since a check never holds a
    loop up on its own bookkeeping."""
    return {i["name"] for i in _env_list(key)
            if isinstance(i, dict) and isinstance(i.get("name"), str)}


def shared_repo_dirs() -> set[Path]:
    """The checkouts kc marks `shared` — `kc env describe`'s `repos`, each
    `{url, dir, shared, ref}`, resolved by `dir`. A shared repo is one clone
    mounted into every environment of the project: whatever branch it is on
    is every session's, in every environment, so a phase never branches it
    in place (`RunLoop._ensure_worktree`). ValueError with the cause when kc
    does not answer that; unlike the tool and service checks the caller
    cannot go on without the answer, and bails."""
    return {Path(r["dir"]).resolve() for r in _env_list("repos")
            if isinstance(r, dict) and r.get("shared") is True
            and isinstance(r.get("dir"), str) and r["dir"]}


def declared_repo_dirs() -> dict[Path, str]:
    """Every checkout `.kubecoder/config.yaml` declares — `kc env
    describe`'s `repos`, resolved `dir` → `url` ("" when kc gives none).
    That list is the file as it stands now, not as the pod was composed: a
    repo added while the environment runs is listed before the pod has
    cloned it, which is how `not_cloned_message` tells such a Target from a
    wrong path. ValueError with the cause when kc does not answer that."""
    return {Path(r["dir"]).resolve():
            (r["url"] if isinstance(r.get("url"), str) else "")
            for r in _env_list("repos")
            if isinstance(r, dict) and isinstance(r.get("dir"), str)
            and r["dir"]}


class TargetNotCloned(ValueError):
    """A repo-path Target `.kubecoder/config.yaml` declares and the pod has
    not cloned (`not_cloned_message`). The plan is fine; the environment is
    a clone short, which the plan's author cannot fix and a nudge cannot
    either — `_load_plan` stops on it at once. A ValueError, so every
    caller that reports an unresolvable Target reports this one too, in its
    own words."""


def not_cloned_message(target: str, path: Path) -> str | None:
    """Why the repo a Target names at `path` is missing, when the reason is
    that the pod has not cloned it yet: a repo added to config.yaml while
    the environment runs is cloned at the next pod start, and until then
    the Target read as a wrong path — preflight passed, and the run loop
    nudged a session to fix a plan that was fine, then asked the operator.

    None when `path` is a checkout, when kc does not answer (the caller's
    own message stands, as before this existed), or when config.yaml does
    not declare it (then the path is the plan's to fix). Asked only for a
    Target that missed, so a Target on disk never waits on kc."""
    if (path / ".git").exists():
        return None
    try:
        declared = declared_repo_dirs()
    except ValueError:
        return None
    where = path.resolve()
    if where not in declared:
        return None
    url = declared[where] or "<its url>"
    return (f"Target `{target}` is declared but not cloned: "
            f"`.kubecoder/config.yaml` lists {url} at {where}, and the "
            "environment has not checked it out (a repo added while the pod "
            "runs is cloned at its next start). Restart the environment "
            f"(`kc env restart`) or clone it (`git clone {url} {where}`), "
            f"then run `kc project setup` in {where}")


def overwritten_paths(output: str) -> list[str]:
    """The paths a refused `git merge` names as standing in its way — local
    changes, staged or not, or untracked files it would overwrite: the
    indented lines under git's "… would be overwritten by merge:" (a tab
    before each, or two spaces from the ort strategy's own refusal)."""
    paths: list[str] = []
    taking = False
    for line in output.splitlines():
        if "would be overwritten by merge" in line:
            taking = True
            continue
        if taking and line[:1] in ("\t", " ") and line.strip():
            paths.append(line.strip())
            continue
        taking = False
    return list(dict.fromkeys(paths))


# Where a shared repo's phase works: `<root>/<repo name>/<NNN>-P<id>`, a
# linked worktree on its phase branch. Per environment, beside the scratch
# clones (whose sync walks them by their mark, so it never takes one of these
# for a clone), and on /work, so the cexec sidecars see it and a restart
# keeps it.
WORKTREE_ROOT = github_target.SCRATCH_ROOT / "worktrees"
# Attempts at a shared repo's merge (`RunLoop._merge_shared`): each sweep of
# another writer's edit in the way, or wait out a concurrent git's
# index.lock, costs one.
MERGE_ATTEMPTS = 5
# The wait before a merge retried over another git process's index.lock.
INDEX_LOCK_WAIT = 2


def running_tools() -> set[str]:
    """The tool containers this pod runs: `kc env describe`'s `sections`,
    one per sidecar, `name` the tool (`_env_described`)."""
    return _env_described("sections")


def missing_tools(roots: Sequence[Path], host_root: Path,
                  running: set[str]) -> list[MissingTool]:
    """Every tool the manifests of `roots` call (`manifest_tools`) that is
    not in `running`, with the manifests that call it and whether the host
    environment's config (`host_root`'s, the invoking repo's) declares it.
    A root without a manifest calls nothing."""
    callers: dict[str, list[str]] = {}
    for root in roots:
        root = Path(root)
        rel = f"{root.name}/{MANIFEST_REL}"
        for tool in sorted(manifest_tools(_read_text(root / MANIFEST_REL))
                           - running):
            if rel not in callers.setdefault(tool, []):
                callers[tool].append(rel)
    declared = declared_tools(_read_text(Path(host_root) / ENV_CONFIG_REL))
    return [MissingTool(tool, callers[tool], tool in declared)
            for tool in sorted(callers)]


def missing_tools_details(missing: list[MissingTool], host_root: Path,
                          relaunch: str = RUN_RELAUNCH) -> str:
    """The bail's `details`: one line per tool with what fixes it, then why
    the fix is the operator's."""
    config = Path(host_root) / ENV_CONFIG_REL
    lines = ["the run needs tool containers this environment does not run:"]
    for m in missing:
        fix = (f"declared in {config} but not running in this pod (it "
               "predates that commit) — `kc env restart` applies it"
               if m.declared else
               f"add `- use: {m.tool}` under `tools:` in {config}, then "
               "`kc env restart`")
        lines.append(f"- {m.tool} — called by {', '.join(m.callers)}; {fix}")
    lines.append("The restart ends every session in the environment, so this "
                 f"is the operator's; {relaunch}. To run without them "
                 "instead, waive the repo's gates in plan.md's `## Driver "
                 "rulings` (`gate`, and `accept` for lint and build).")
    return "\n".join(lines)


def tools_waived(root: Path,
                 rulings: list[tuple[Ruling, ResolvedTarget]]) -> bool:
    """Whether plan.md's `## Driver rulings` waive every sweep verb for all
    of the repo at `root` — a gate ruling (test) and accept rulings for lint
    and for build covering each component kc lists, a repo-level ruling
    counting for every component. Then nothing the run must pass needs the
    repo's tools. The repo is the unit, not the component: the scan reads a
    manifest file, not a component's statements, and the loop-tail sweep
    runs every component of a repo the run touched anyway. A repo kc cannot
    list is held to its tools."""
    if RunLoop._covering(rulings, root, None) is None:
        return False
    try:
        components = load_project_dirs(Path(root))
    except Bailout:
        return False

    def covered(kind: str, verb: str, component: str) -> bool:
        of_kind = [(r, t) for r, t in rulings
                   if r.kind == kind and r.verb == verb]
        return RunLoop._covering(of_kind, root, component) is not None

    return all(covered("gate", "test", c) and covered("accept", "lint", c)
               and covered("accept", "build", c) for c in components)


def tools_check(roots: Sequence[Path],
                rulings: list[tuple[Ruling, ResolvedTarget]],
                host_root: Path, log, relaunch: str = RUN_RELAUNCH
                ) -> str | None:
    """The missing-tools message for `roots` (a bail's `details`), None
    when the pod runs every tool their manifests call — or when it cannot
    say which it runs (logged as a warning, and the check passes). A repo
    the rulings waive whole (`tools_waived`) is not held to its tools."""
    seen: set[Path] = set()
    held = []
    for root in roots:
        key = Path(root).resolve()
        if key not in seen and (key / MANIFEST_REL).is_file():
            seen.add(key)
            held.append(key)
    if not held:
        return None
    try:
        running = running_tools()
    except ValueError as e:
        log(f"warning: tool check skipped — {e}")
        return None
    held = [root for root in held
            if not (missing_tools([root], host_root, running)
                    and tools_waived(root, rulings))]
    missing = missing_tools(held, host_root, running)
    return (missing_tools_details(missing, host_root, relaunch)
            if missing else None)


def unavailable_tool(log_path: Path, start: int = 0) -> str | None:
    """The tool a gate log says cexec could not find (CEXEC_MISSING_RE),
    reading from byte `start` on — a log shared by several commands is read
    from where this one began."""
    try:
        with open(log_path, "rb") as f:
            f.seek(start)
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    match = CEXEC_MISSING_RE.search(text)
    return match.group(1) if match else None


def kc_full_output(log_path: Path, start: int = 0) -> str | None:
    """The file kc's last `full output:` line in a gate log names
    (KC_FULL_OUTPUT_RE), reading from byte `start` on — the pointer of the
    command that began there, never one an earlier command printed. The
    last, because kc's pointer closes its output and a statement's own
    lines above it may quote another kc run's."""
    try:
        with open(log_path, "rb") as f:
            f.seek(start)
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    matches = KC_FULL_OUTPUT_RE.findall(text)
    return matches[-1] if matches else None


def _inline_kc_full_output(log_file, log_path: Path, start: int) -> None:
    """Append the file the command that began at byte `start` points at
    (`kc_full_output`) to its gate log: a blank line, a marker naming it,
    its text verbatim. No pointer, no block; a file kc has rotated out or
    a restart took is one line saying so, never a raise."""
    path = kc_full_output(log_path, start)
    if path is None:
        return
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        log_file.write(f"\n=== kc's full output ({path}) is gone — "
                       "not inlined ===\n")
    else:
        log_file.write(f"\n=== kc's full output ({path}) ===\n{text}")
    log_file.flush()


def _last_line(path: Path) -> str:
    """A log's last non-empty line, '' when it has none or cannot be
    read."""
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def _file_size(path: Path) -> int:
    """Where a gate log ends now — the offset its next command's output
    starts at, for `unavailable_tool` and `kc_full_output`."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _ticked(cmds: Sequence[str]) -> str:
    """Gate commands as a dispatch names them: each in backticks, joined
    ", "."""
    return ", ".join(f"`{cmd}`" for cmd in cmds)


# ---------------------------------------------------------------------------
# Services — a Target repo's `.kubecoder/config.yaml` `services:` against the
# pod's (AIWF-38). A repo's suites reach its backing services on localhost,
# and those run only where the environment declares them: Ansible slice
# 036's P14 targeted ElectronicsInventory from the Ansible environment, which
# runs no postgres or s3storage; setup and tests failed on :5432 and :9000,
# and the driver dispatched a fix round that could only hand back `blocked`.
# The fix is the tools' fix — a config.yaml line and `kc env restart` — so a
# gate gone red in a repo whose services the pod lacks bails for it, never a
# fix round (`RunLoop._unrun_services`). Before any dispatch only the host's
# own config is held, another Target repo's logged (AIWF-75, `services_check`
# says why).
# ---------------------------------------------------------------------------

# An item of the environment config's `services:` list: the bare name
# (`- postgres`, run it and expose nothing). The whole item is the name, so
# a mapping item's key (`- expose: [9000]`) is never read as one; the
# selector form (`- use: s3storage`) is TOOL_USE_RE's.
SERVICE_ITEM_RE = re.compile(
    r"-\s*[\"']?([A-Za-z0-9][A-Za-z0-9_.-]*)[\"']?\s*(?:#.*)?$")


class MissingService:
    """A service a repo's environment config declares and the pod does not
    run: who declares it (the configs, repo-relative), and whether the host
    environment's config already declares it — then only the restart is
    owed."""

    def __init__(self, service: str, callers: list[str], declared: bool):
        self.service = service
        self.callers = callers
        self.declared = declared


def config_services(text: str) -> set[str]:
    """The services an environment's `.kubecoder/config.yaml` declares — its
    `services:` list, a bare `- <name>` item or the selector form's
    `use: <name>` (whose `expose:` is ports, not a service), by the line
    scan `declared_tools` makes: comments skipped, the list ending at the
    next top-level key."""
    services: set[str] = set()
    in_services = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace() and not stripped.startswith("-"):
            in_services = stripped.split("#")[0].strip() == "services:"
            continue
        if not in_services:
            continue
        match = TOOL_USE_RE.match(stripped) or SERVICE_ITEM_RE.match(stripped)
        if match:
            services.add(match.group(1))
    return services


def running_services() -> set[str]:
    """The services this pod runs: `kc env describe`'s `services`, by
    `name` (`_env_described`). Their `state` is not read — the list is what
    the pod was composed with, and a service that is down is no config fix."""
    return _env_described("services")


def missing_services(roots: Sequence[Path], host_root: Path,
                     running: set[str]) -> list[MissingService]:
    """Every service the environment configs of `roots` declare
    (`config_services`) that is not in `running`, with the configs that
    declare it and whether the host environment's config (`host_root`'s, the
    invoking repo's) does. A root without a config declares nothing; the
    host's own is held like any other, its unrun services a restart owed."""
    callers: dict[str, list[str]] = {}
    for root in roots:
        root = Path(root)
        rel = f"{root.name}/{ENV_CONFIG_REL}"
        for service in sorted(config_services(
                _read_text(root / ENV_CONFIG_REL)) - running):
            if rel not in callers.setdefault(service, []):
                callers[service].append(rel)
    declared = config_services(_read_text(Path(host_root) / ENV_CONFIG_REL))
    return [MissingService(service, callers[service], service in declared)
            for service in sorted(callers)]


def missing_services_details(missing: list[MissingService], host_root: Path,
                             relaunch: str = RUN_RELAUNCH) -> str:
    """The bail's `details`: one line per service with what fixes it, then
    why the fix is the operator's."""
    config = Path(host_root) / ENV_CONFIG_REL
    lines = ["the run needs services this environment does not run:"]
    for m in missing:
        fix = (f"declared in {config} but not running in this pod (it "
               "predates that commit) — `kc env restart` applies it"
               if m.declared else
               f"add `- {m.service}` under `services:` in {config}, then "
               "`kc env restart`")
        lines.append(f"- {m.service} — declared by {', '.join(m.callers)}; "
                     f"{fix}")
    lines.append("The restart ends every session in the environment, so this "
                 f"is the operator's; {relaunch}. To run without them "
                 "instead, waive the repo's gates in plan.md's `## Driver "
                 "rulings` (`gate`, and `accept` for lint and build).")
    return "\n".join(lines)


def services_check(roots: Sequence[Path],
                   rulings: list[tuple[Ruling, ResolvedTarget]],
                   host_root: Path, log, relaunch: str = RUN_RELAUNCH
                   ) -> str | None:
    """The missing-services message for the host among `roots` (a bail's
    `details`), None when the pod runs every service the host's environment
    config declares — or when it cannot say which it runs (logged as a
    warning, and the check passes). Only the host is held (AIWF-75): its
    config is the pod's, while another Target repo's declares services for
    that repo's own workspace, and nothing in it says which its gates use —
    KubeCoder slice 244 stopped in planning over Ansible's
    terraform-backend-git for a phase editing one sentence of Ansible's
    docs, whose gates never touch it. Such a repo's unrun services are a
    logged warning, and a gate gone red there bails for them
    (`RunLoop._unrun_services`). kc is asked only when some root's config
    declares a service; a repo the rulings waive whole (`tools_waived`: no
    gate it must pass runs its suites) is neither held nor warned about."""
    host = Path(host_root).resolve()
    seen: set[Path] = set()
    declaring = []
    for root in roots:
        key = Path(root).resolve()
        if key not in seen and config_services(
                _read_text(key / ENV_CONFIG_REL)):
            seen.add(key)
            declaring.append(key)
    if not declaring:
        return None
    try:
        running = running_services()
    except ValueError as e:
        log(f"warning: service check skipped — {e}")
        return None
    held = []
    for root in declaring:
        unrun = missing_services([root], host_root, running)
        if not unrun or tools_waived(root, rulings):
            continue
        if root == host:
            held.append(root)
            continue
        log(f"warning: services not held — {root.name}/{ENV_CONFIG_REL} "
            f"declares {', '.join(m.service for m in unrun)}, which this pod "
            "does not run; only the host's own are held, and a gate that goes "
            f"red in {root.name} bails missing_services")
    missing = missing_services(held, host_root, running)
    return (missing_services_details(missing, host_root, relaunch)
            if missing else None)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class RunLoop:
    # True where a driver write close-out.md refuses for an edit is logged
    # rather than a stop (`_report_logged`).
    _report_quiet = False

    def __init__(self, slice_dir: Path, resume: bool, verbose: bool = False):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.slice_num = self.slice_name.split("_")[0]
        self.plan_path = self.slice_dir / "plan.md"
        self.verification_path = self.slice_dir / "verification.json"
        self.report_path = report_path(self.slice_dir)
        self.state_path = self.slice_dir / "state.json"
        self.log_path = self.slice_dir / "log.txt"
        self.resume = resume
        self.verbose = verbose
        self.state: dict = {}
        self._log_file = None
        self._reattach: dict | None = None
        self.repo_root = _git_toplevel()
        self._spec_root: Path | None = None
        self._cfg: project_config.ProjectConfig | None = None
        self._devlock: DevLock | None = None
        # The repos kc marks shared (`_shared_dirs`): None until first asked.
        self._shared: set[Path] | None = None
        self._slice_lock = SliceLock(self.slice_dir / "run.lock")
        # Called once the run is past its refusals (`_run`) — the detached
        # driver's word to the parent that it has started.
        self.on_start = None
        # Set once state.json is this run's: from then on every exit goes on
        # record in it (`_record_exit`).
        self._owns_state = False
        # name → effective cwd, from `kc project list --output=json`; loaded
        # in run() (both fresh and resume need it before any dispatch).
        self.project_dirs: dict[str, Path] = {}
        # The sibling repos' components (_sibling_owners): None until a
        # Target misses project_dirs, and again whenever project_dirs is
        # re-read.
        self._sibling_owners: dict[str, list[Path]] | None = None
        self._siblings_listed: list[str] = []
        self._siblings_unlisted: list[str] = []

    def reroot(self, root: Path) -> None:
        """Point the loop at another code repo — the dry run's, started from
        a repo that is not the one the slice's Targets live in. What was
        derived from the old root goes with it and is re-derived on use."""
        self.repo_root = root
        self._cfg = None
        self._devlock = None
        self.project_dirs = {}
        self._sibling_owners = None

    @property
    def cfg(self) -> project_config.ProjectConfig:
        """The project's own contract — which phases it runs, which procedure
        docs they execute, whether it has a dev instance to lease. Read from
        the repo rather than __init__'s argument list, so it resolves against
        whatever `repo_root` ends up being; `run()` forces it before any work.
        Preflight has already validated it for a run, so a config broken
        between then and now is an environment fault (exit 2), not a bail the
        loop could resume from."""
        if self._cfg is None:
            try:
                self._cfg = project_config.load(self.repo_root)
            except project_config.ConfigError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)
        return self._cfg

    def _push_on(self) -> bool:
        """`push.enabled`, read from the repo's `.aiworkflowrc` again at every
        push point — the push check after the test phase, the driver's own
        push without one, and the doc landing's in each repo — rather than
        taken from the cached `cfg`, as the plan's push holds and driver
        rulings are re-read at their points of use. A phase that switches
        push on (a project's first deploy slice does) takes effect in the
        same run; every other setting stays as `cfg` read it at the start.
        A config that no longer loads here is a resumable bail, not the
        exit 2 `cfg` gives at the run's start: the slice's own phase may be
        what broke it, and fixing the file and resuming is the way out."""
        try:
            return project_config.load(self.repo_root).push
        except project_config.ConfigError as e:
            raise Bailout(
                "protocol_failure",
                details=f"{e} — read again for `push.enabled` at the push "
                        "check, the driver's own push or the doc landing; "
                        "fix it, then resume",
            ) from None

    @property
    def devlock(self) -> DevLock:
        if self._devlock is None:
            self._devlock = DevLock(self.cfg.devlock_lease)
        return self._devlock

    # -- state ---------------------------------------------------------------

    def _save_state(self) -> None:
        self.state["updated_at"] = _now_iso()
        _write_state(self.state_path, self.state)

    def _record_exit(self, code: int) -> None:
        """The run's exit code, on disk — written last, after bailout.json,
        whatever the exit. A detached driver's code reaches nobody else.
        Added to state.json as the run last saved it rather than to memory:
        what the run never saved, a resume must not find either (an
        interrupted resume's cleared `in_flight` is the reattach it still
        owes). Nothing is written for a fresh run refused before it wrote a
        state.json — that would make the next attempt a --resume — and
        nothing here may mask the exit."""
        if not self._owns_state:
            return
        state = _read_json(self.state_path)
        if state is None:
            return
        state["exit"] = self.state["exit"] = {"code": code, "ts": _now_iso()}
        try:
            _write_state(self.state_path, state)
        except OSError as e:
            print(f"warning: the exit record was not written: {e}",
                  file=sys.stderr)

    def _phase_state(self, phase_id: str) -> dict:
        defaults = {
            "status": "pending", "stage": None, "branch": None,
            "target": None, "executor_rounds": 0, "gate_fix_rounds": 0,
            "review_rounds": 0, "gate_runs": 0,
            "gate_green_commit": None, "gate_green_log": None,
            "gate_nothing_ran_commit": None, "gate_cmd": None,
            "gate_projects": None,
            "reviewed_head": None, "landed": None, "review_set_start": None,
            "review_set_ambiguous_start": None,
        }
        ps = self.state["phases"].setdefault(phase_id, dict(defaults))
        for key, value in defaults.items():
            ps.setdefault(key, value)
        return ps

    def _record(self, phase: str | None, role: str, round_: int,
                outcome: str, summary: str, session: str | None,
                duration_s: int, transcript: str | None = None,
                extra: dict | None = None) -> None:
        self.state["history"].append({
            "ts": _now_iso(), "phase": phase, "role": role, "round": round_,
            "outcome": outcome, "summary": summary, "session": session,
            "transcript": transcript, "duration_s": duration_s,
            **(extra or {}),
        })
        self._save_state()

    def _emit(self, line: str) -> None:
        """All driver/session output lands in <slice>/log.txt; stdout echoes
        it only under --verbose (the log must never flood a caller's
        context)."""
        if self._log_file is None:
            self._log_file = open(self.log_path, "a", buffering=1)
        self._log_file.write(line + "\n")
        if self.verbose:
            print(line, flush=True)

    def log(self, msg: str) -> None:
        self._emit(f"[{_now_hms()}] {msg}")

    def announce(self, msg: str) -> None:
        """One terse timestamped stdout line per major transition — the
        caller's window into a run that otherwise reports only into
        log.txt. Every line lands in the watching session's context: job
        starts and landings only, never detail."""
        print(f"[{_now_hms()}] {msg}", flush=True)

    # -- git -----------------------------------------------------------------

    def git(self, *args: str, root: Path | None = None,
            check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root or self.repo_root,
            capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise Bailout(
                "protocol_failure", details=(
                    f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
                ),
            )
        return result.stdout.strip()

    def git_ok(self, *args: str, root: Path | None = None) -> bool:
        """A git query whose whole answer is its exit status — `merge-base
        --is-ancestor`, which prints nothing and says no by exiting 1 (and
        for an object this repo does not have at all, 128)."""
        return subprocess.run(
            ["git", *args], cwd=root or self.repo_root,
            capture_output=True, text=True,
        ).returncode == 0

    def git_raw(self, *args: str, root: Path | None = None,
                check: bool = True) -> str:
        """`git` with its stdout as git wrote it, for the redactor, which
        reads a blob and a diff line by line: `git`'s strip would shift a
        blob's line numbers by its leading blank lines and cut a diff's
        trailing blank context line, and a text-mode read would split a
        line at a lone `\\r`. Decoded per byte the same way on both sides; a
        failure bails as `git`'s check does."""
        result = subprocess.run(
            ["git", *args], cwd=root or self.repo_root, capture_output=True)
        if check and result.returncode != 0:
            raise Bailout(
                "protocol_failure", details=(
                    f"git {' '.join(args)} failed:\n"
                    f"{result.stderr.decode(errors='replace').strip()}"
                ),
            )
        return result.stdout.decode("utf-8", errors="replace")

    def _redact(self, diff: str, base: str, head: str, root: Path,
                phase_id: str | None = None) -> tuple[str, int]:
        """`diff` — taken over `base..head` in `root` — with its Secret data
        stubbed (`redact_secrets.redact`), and how many lines were; the
        blobs are read at both ends of that range. Fail-closed: a diff the
        redactor cannot redact, or a blob it cannot read, is a `redaction`
        stop, and no agent is handed the diff."""
        def blob(side: str, path: str) -> str:
            rev = base if side == "old" else head
            try:
                return self.git_raw("show", f"{rev}:{path}", root=root)
            except Bailout as e:
                raise RedactionError(
                    f"{path} ({side} side): the blob at {rev} could not be "
                    f"read — {e.details}") from None
        try:
            return redact(diff, blob)
        except RedactionError as e:
            raise Bailout(
                "redaction", phase=phase_id,
                details=f"{e} — in {base}..{head} of {root}; the driver "
                        "hands no agent a diff it could not redact") from None

    def specs_git(self, *args: str) -> str:
        """Git in the specs repo (the slice folder's repo) — used only for
        the driver's own plan.md edits (stamps), staged by name: the specs
        repo is one working tree shared by several parallel sessions."""
        return self.git("-C", str(self.slice_dir), *args)

    def _current_branch(self, root: Path) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD", root=root)

    @property
    def spec_root(self) -> Path:
        """The specs repo's root, asked of git once — the slice folder's own
        repo, whichever way the slice was addressed."""
        if self._spec_root is None:
            self._spec_root = Path(
                self.git("rev-parse", "--show-toplevel",
                         root=self.slice_dir)).resolve()
        return self._spec_root

    def _is_spec_root(self, root: Path) -> bool:
        return Path(root).resolve() == self.spec_root

    def _shared_dirs(self) -> set[Path]:
        """The repos kc marks shared (`shared_repo_dirs`), asked once per
        process and recorded in state.json's `shared_repos` — and a resume
        reads the record rather than asking again, so a phase that began in
        a worktree finishes in one. kc not answering is a stop: without the
        answer a phase could branch a shared tree in place."""
        if self._shared is None:
            recorded = self.state.get("shared_repos")
            if isinstance(recorded, list):
                self._shared = {Path(p) for p in recorded
                                if isinstance(p, str)}
            else:
                try:
                    dirs = shared_repo_dirs()
                except ValueError as e:
                    raise Bailout(
                        "protocol_failure",
                        details="which repos of this environment are shared "
                                f"could not be read: {e}") from None
                self._shared = dirs
                self.state["shared_repos"] = sorted(str(p) for p in dirs)
        return self._shared

    def _is_shared(self, root: Path) -> bool:
        return Path(root).resolve() in self._shared_dirs()

    def _works_in_worktree(self, root: Path) -> bool:
        """Whether a phase targeting `root` works in a linked worktree of its
        own rather than on a branch checked out in `root` itself: a repo kc
        marks shared, and the spec repo whether kc marks it or not — the tree
        holding the slice folder is never branched under the run, which
        writes its record there and asserts it on its base before every
        dispatch (`_assert_spec_on_base`)."""
        return self._is_shared(root) or self._is_spec_root(root)

    def _assert_spec_on_base(self) -> None:
        """The specs repo must be on its base branch before anything commits
        there and before any agent is pointed at it — the stamp, the
        driver's report commits, every dispatch. Whatever branch that tree
        sits on is where this run's stamps, plan edits and close-out entries
        land. The run itself never moves it (a phase on it works in a
        worktree), so a tree off its base is a hand checkout, or a run of a
        plugin before 0.9.93, which still branched it in place."""
        base = self._base_branch(self.spec_root)
        cur = self._current_branch(self.spec_root)
        if cur == base:
            return
        raise Bailout(
            "blocked",
            details=f"the spec repo {self.spec_root} is on {cur}, not {base} "
                    "— a hand checkout, or a run of a plugin before 0.9.93, "
                    f"left it there; check out {base} there and resume")

    def _bookkeeping_pathspec(self, root: Path) -> list[str]:
        """The pathspec holding the workflow's own bookkeeping outside a git
        query of the tree that holds the slice folder — empty for every
        other tree, a phase's worktree included.

        The spec repo's checkout carries the driver's live run record
        (log.txt, state.json, phases/**) and every parallel slice's folder
        beside it. None of that is a slice's deliverable — a slice's product
        is code, docs, or the wire contracts, never the workflow's own
        scratch — so the whole `slices/` tree stays out of these queries.
        Uncommitted work under `slices/` is therefore unchecked here too: an
        agent's plan.md edit rides the next stamp commit."""
        spec_root = spec_root_for(self.slice_dir)
        if spec_root is None:
            return []
        try:
            rel = (spec_root / "slices").relative_to(Path(root).resolve())
        except ValueError:
            return []
        return [".", f":(exclude){rel}"]

    def _worktree_dirty(self, root: Path) -> bool:
        pathspec = self._bookkeeping_pathspec(root)
        args = ("status", "--porcelain", *(["--", *pathspec] if pathspec
                                           else []))
        return bool(self.git(*args, root=root))

    def _set_aside(self, phase_id: str, ps: dict, root: Path) -> None:
        """Save what a dead round left uncommitted in `root` before the
        resume's `_reset_tracked` drops it (AIWF-58): SecretRotator slice
        051's P12 writer hit the session cap with its test edits uncommitted,
        the resume reset them away, and the next writer rebuilt them from
        the dead session's transcript.

        Under the phase's `set-aside/`, named for the phase's last
        code-writer round — the one whose work the tree holds — go its `git
        diff HEAD` as a patch `git apply` takes (an external diff driver,
        textconv and colour held off) and copies of its untracked files,
        which stay in the tree: `reset --hard` leaves them, and so does
        this. The folder ignores itself, as `doc_phase/` does: the patch is
        git's raw answer, Secret data and all. The record in `set_aside`
        reaches the phase's next code-writer (`set_aside_line`). A save
        that fails stops the resume before anything is reset."""
        if not self._worktree_dirty(root):
            return
        k = ps["executor_rounds"]
        out = self.slice_dir / "phases" / f"P{phase_id}" / "set-aside"
        pathspec = self._bookkeeping_pathspec(root)
        spec = ["--", *pathspec] if pathspec else []
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / ".gitignore").write_text("*\n")
            stem, n = f"r{k}", 1
            while ((out / f"{stem}.patch").exists()
                   or (out / f"{stem}-untracked").exists()):
                n += 1
                stem = f"r{k}-{n}"
            patch = out / f"{stem}.patch"
            self.git("diff", "--binary", "--no-ext-diff", "--no-textconv",
                     "--no-color", f"--output={patch}", "HEAD", *spec,
                     root=root)
            files = [f for f in self.git_raw(
                "ls-files", "--others", "--exclude-standard", "-z", *spec,
                root=root).split("\0") if f]
            untracked = out / f"{stem}-untracked" if files else None
            for rel in files:
                src, dst = Path(root) / rel, untracked / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir() and not src.is_symlink():
                    shutil.copytree(src, dst, symlinks=True)   # a nested repo
                else:
                    shutil.copy2(src, dst, follow_symlinks=False)
        except (Bailout, OSError) as e:
            why = e.details if isinstance(e, Bailout) else str(e)
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details="the resume could not set the dead round's "
                        f"uncommitted work in {root} aside under {out} "
                        f"({why}) — nothing was reset, and the work is still "
                        "in the tree") from None
        self.log(f"[P{phase_id}] the dead round's uncommitted work set aside "
                 f"before the reset: {patch}"
                 + (f"; {len(files)} untracked file(s) copied to {untracked} "
                    "(still in the tree)" if files else ""))
        ps.setdefault("set_aside", []).append({
            "round": k, "patch": str(patch),
            "untracked": str(untracked) if untracked else None,
            "files": len(files)})
        self._save_state()

    def _reset_tracked(self, root: Path) -> None:
        """Drop a dead round's uncommitted work before redispatching — a
        plain `reset --hard` in a phase's worktree, where nothing but the
        phase writes; a resume sets the work aside first (`_set_aside`).
        Scoped away from the bookkeeping tree where `root` holds it: `reset
        --hard` would take an agent's uncommitted plan.md edit with it (the
        live log and state are untracked, so neither form touches those)."""
        pathspec = self._bookkeeping_pathspec(root)
        if not pathspec:
            self.git("reset", "--hard", "HEAD", root=root)
            return
        self.git("restore", "--source=HEAD", "--staged", "--worktree", "--",
                 *pathspec, root=root)

    def _fetch_origin(self, root: Path) -> None:
        """Refresh a repo's remote-tracking refs — run before an agent is
        pointed at that repo, and before the driver reads `origin/<base>`
        itself.

        Nothing else in a run fetches: the driver branches off the LOCAL base
        branch and ff-merges back into it, so a repo cloned days ago keeps
        whatever `origin/<base>` came with the clone, and an agent reading
        that ref reads the day of the clone. One run's executor called a
        sibling-repo commit that had been on `origin/main` for a day "absent
        from origin" and raised a Blocker over it. Refs only: the one local
        branch a run moves to its origin is a fresh phase's base with no
        commits of its own (`_sync_base`); a base that has diverged from
        origin is never moved, save where the doc phase's landing rebases
        onto it (`_land_doc_branch`, `_rebase_doc_sibling`)."""
        self.git("fetch", "origin", root=root)

    def _sync_base(self, phase_id: str, root: Path, base: str) -> None:
        """Bring a fresh phase's local base up to `origin/<base>` before its
        branch is cut, when the base is a plain ancestor of it — no commit
        of its own, so none can be lost. Where the base is checked out in
        `root` (a shared repo's checkout included) it is `merge --ff-only`,
        which refuses rather than overwrite a dirty file the commits touch;
        checked out nowhere, `update-ref` against the sha it was read at;
        checked out in another worktree, it is left. A refusal, or a base
        left, is a log line and the branch is cut from the base as it
        stands — never a bail. A base with commits of its own is never
        moved: the bases have diverged, and the phase's writer is told
        (`_origin_ahead_line`). Ansible slice 049's P10 was cut from a
        `main` ten commits behind origin, where slice 052 had edited the
        same anchors, and its push needed a hand merge."""
        origin = f"refs/remotes/origin/{base}"
        tip = self.git("rev-parse", "--verify", "--quiet", origin, root=root,
                       check=False)
        if not tip or self.git_ok("merge-base", "--is-ancestor", origin, base,
                                  root=root):
            return
        behind = self.git("rev-list", "--count", f"{base}..{origin}",
                          root=root)
        if not self.git_ok("merge-base", "--is-ancestor", base, origin,
                           root=root):
            own = self.git("rev-list", "--count", f"{origin}..{base}",
                           root=root)
            self.log(f"[P{phase_id}] {base} and origin/{base} have diverged "
                     f"in {root.name} ({own} commit(s) local, {behind} on "
                     "origin) — not moved")
            return
        holder = next((Path(entry.get("worktree", ""))
                       for entry in self._worktrees(root)
                       if entry.get("branch") == f"refs/heads/{base}"), None)
        if holder is None:
            was = self.git("rev-parse", f"refs/heads/{base}", root=root)
            rc, out = self._git_attempt("update-ref", f"refs/heads/{base}",
                                        tip, was, root=root)
        elif holder.resolve() == Path(root).resolve():
            rc, out = self._git_attempt("merge", "--ff-only", tip, root=root)
        else:
            rc, out = 1, f"checked out in {holder}"
        if rc:
            # `merge` prints its `Updating a..b` before it refuses: the
            # reason is git's complaint, not that.
            lines = [line for line in out.splitlines() if line.strip()]
            reason = next((line for line in lines
                           if line.startswith(("error:", "fatal:"))),
                          lines[0] if lines else f"git exited {rc}")
            self.log(f"[P{phase_id}] {base} left {behind} commit(s) behind "
                     f"origin/{base} in {root.name}: {reason}")
            return
        self.log(f"[P{phase_id}] {base} fast-forwarded {behind} commit(s) to "
                 f"origin/{base} in {root.name}")

    def _origin_ahead_line(self, phase: Phase, root: Path, base: str) -> str:
        """ORIGIN_AHEAD_LINE when `origin/<base>` holds commits the local base
        lacks — diverged, a fast-forward skipped, or a resume after origin
        moved — else empty. Of what origin changed since the merge base, it
        names the paths the phase's own section of the plan names word for
        word."""
        origin = f"refs/remotes/origin/{base}"
        if not self.git("rev-parse", "--verify", "--quiet", origin, root=root,
                        check=False):
            return ""
        ahead = int(self.git("rev-list", "--count", f"{base}..{origin}",
                             root=root) or 0)
        if not ahead:
            return ""
        own = int(self.git("rev-list", "--count", f"{origin}..{base}",
                           root=root) or 0)
        text = "\n".join([phase.title, *phase.body])
        named = [path for path in self.git(
            "diff", "--name-only", f"{base}...{origin}",
            root=root).splitlines() if path and path in text]
        if named:
            shown = ", ".join(f"`{path}`" for path in named[:20])
            if len(named) > 20:
                shown += f" and {len(named) - 20} more"
            touches = f"they touch {shown}, which this phase names"
        else:
            touches = "none of the files they touch is named in this phase"
        return ORIGIN_AHEAD_LINE.format(
            base=base, ahead=ahead, touches=touches,
            own=(f", which has {own} commit(s) of its own origin lacks"
                 if own else ""))

    def _touched_roots(self) -> list[tuple[Path, str]]:
        """Every repo this slice has touched, with the base branch it was
        recorded at. `state["bases"]` is the run's own record of what the
        slice touched — better input than a re-parse of the plan's `Target:`
        lines. The spec repo is left out: its commits are the slice's own
        record, they land at close-out, and nothing deploys from them. It is
        in `bases` on every run, phase target or not — the branch check
        records it there."""
        return [(Path(key), base)
                for key, base in sorted(self.state["bases"].items())
                if not self._is_spec_root(Path(key))]

    def _push_holds(self, text: str) -> tuple[dict[str, str], list[str]]:
        """(repo root → why the plan holds its push, structure errors).
        Roots are keyed as `state["bases"]` keys them, so the push check and
        the doc phase can look a repo up directly."""
        holds, errors = parse_push_holds(text)
        resolved: dict[str, str] = {}
        for target, why in holds:
            try:
                root = self._resolve_target(target, held=True).git_root
            except ValueError as e:
                errors.append(f"push hold `{target}`: {e}")
                continue
            resolved[str(root)] = why
        return resolved, errors

    def _held_roots(self) -> dict[str, str]:
        """The holds as the plan stands right now — re-read per call, so a
        hold the operator adds while the run sits at a bail takes effect on
        resume. Unresolvable entries drop out here and come back as plan
        structure errors from `_load_plan`."""
        try:
            text = self.plan_path.read_text()
        except OSError:
            return {}
        return self._push_holds(text)[0]

    def _hold_block(self, template: str = HOLD_BLOCK) -> str:
        """The held repos as the test phase's dispatch carries them. The
        plan says it too, but the procedure doc that dispatch executes says
        `push`, and a deterministic fact outranks a section the agent has to
        find. The wrap-up's dispatch names the same rows in its own words
        (`WRAP_UP_HOLD_BLOCK`)."""
        try:
            holds, _ = parse_push_holds(self.plan_path.read_text())
        except OSError:
            return ""
        if not holds:
            return ""
        return template.format(
            rows="\n".join(f"  - {t} — {why}" for t, why in holds))

    # -- driver rulings --------------------------------------------------------
    # `## Driver rulings` is the operator overriding one of the loop's fixed
    # rules for one target — a gate the environment cannot run, a red that
    # predates the slice, prd for a repo the slice must roll. Read like the
    # push holds: re-read from the plan at every point of use, so a ruling
    # added while the run sits at a bail takes effect on resume.

    def _rulings(self, text: str
                 ) -> tuple[list[tuple[Ruling, ResolvedTarget]], list[str]]:
        """(each ruling with its resolved target, structure errors) — an
        unresolvable target is an error, as for a push hold."""
        rulings, errors = parse_rulings(text)
        resolved: list[tuple[Ruling, ResolvedTarget]] = []
        for ruling in rulings:
            try:
                resolved.append((ruling, self._resolve_target(ruling.target)))
            except ValueError as e:
                errors.append(f"driver ruling `{ruling.key}`: {e}")
        return resolved, errors

    def _current_rulings(self) -> list[tuple[Ruling, ResolvedTarget]]:
        """The rulings as the plan stands right now. Unresolvable entries
        drop out here and come back as plan structure errors from
        `_load_plan`."""
        try:
            text = self.plan_path.read_text()
        except OSError:
            return []
        return self._rulings(text)[0]

    @staticmethod
    def _covering(rulings: list[tuple[Ruling, ResolvedTarget]], root,
                  component: str | None) -> Ruling | None:
        """The ruling among `rulings` that covers `component` of the repo at
        `root` — one naming that component first, then a repo-level one. A
        None component is the whole repo, which any ruling in it covers: its
        gate runs every component's tests, so a component's waiver cannot be
        isolated from it, and running it anyway would redden on exactly the
        red the operator ruled on."""
        here = Path(root).resolve()
        matches = [(r, t) for r, t in rulings
                   if Path(t.git_root).resolve() == here
                   and (t.kind == "sibling" or component is None
                        or t.name == component)]
        named = [r for r, t in matches if t.kind == "project"]
        return (named or [r for r, _ in matches] or [None])[0]

    def _gate_ruling(self, target: ResolvedTarget) -> Ruling | None:
        """The gate ruling that waives this phase target's gate, if any."""
        gates = [(r, t) for r, t in self._current_rulings()
                 if r.kind == "gate"]
        return self._covering(
            gates, target.git_root,
            target.name if target.kind == "project" else None)

    def _gate_waived_note(self, target: ResolvedTarget) -> str:
        """The executor's line when its target's gate is waived — empty
        otherwise."""
        ruling = self._gate_ruling(target)
        if ruling is None:
            return ""
        return GATE_WAIVED_NOTE.format(target=target.name,
                                       substitute=ruling.substitute_text,
                                       why=ruling.why)

    def _rulings_block(self) -> str:
        """The gate rulings as the test phase's dispatch carries them: the
        substitute is the evidence it cites, and it is the one to find out
        whether that substitute ran."""
        gates = [r for r, _ in self._current_rulings() if r.kind == "gate"]
        if not gates:
            return ""
        return RULINGS_BLOCK.format(rows="\n".join(
            f"  - {r.target} — substitute: {r.substitute_text} — {r.why}"
            for r in gates))

    def _prd_line(self) -> tuple[str, list[Ruling]]:
        """The test phase's prd line, and the prd rulings it states."""
        prd = [r for r, _ in self._current_rulings() if r.kind == "prd"]
        if not prd:
            return PRD_LINE, []
        return PRD_RULINGS_LINE.format(rows="\n".join(
            f"  - {r.target} — {r.why}" for r in prd)), prd

    def _report_ruling(self, ruling: Ruling, where: str) -> None:
        """A ruling the run applied, entered in the close-out report once per
        run — the first time it changed what the driver did. Deduped across
        resumes in state.json, as `_report_hold` dedupes holds — marked once
        the write is over, so a write an operator's edit stopped is the
        resume's to make."""
        reported = self.state.setdefault("rulings_reported", [])
        if ruling.key in reported:
            return
        body = f"`plan.md`'s `## Driver rulings` section: `{ruling.text}`"
        if ruling.kind == "gate":
            headline = (f"Gate waived by ruling: {ruling.target} — "
                        f"{ruling.substitute_text}")
            consequence = (f"the driver never verified {ruling.target}'s "
                           "tests in this run; "
                           + ("the substitute's result is the only evidence."
                              if ruling.substitute else
                              "the ruling names no substitute, so nothing "
                              "did."))
        elif ruling.kind == "accept":
            headline = (f"Red row accepted by ruling: {ruling.target} "
                        f"{ruling.verb}")
            consequence = (f"`kc project {ruling.verb}` is red for "
                           f"{ruling.target} in the tree this slice leaves; "
                           "the driver let it through on the ruling.")
        else:
            headline = f"prd authorized by ruling: {ruling.target}"
            consequence = ("the test phase was told pushing and rolling prd "
                           f"for {ruling.target} is its own; what it did "
                           "there is in its verdict and verification.json.")
        self._report("Notable events", headline, body,
                      consequence=consequence,
                      provenance=f"witnessed — the driver's {where}, against "
                                 "`plan.md`'s `## Driver rulings`")
        reported.append(ruling.key)
        self._save_state()

    def _base_branch(self, root: Path) -> str:
        """The base branch of a target repo, recorded the first time the loop
        touches that repo (the invoking repo is recorded at init).

        A `phase/` branch is never a base. It is another run's, left checked
        out where that run bailed, and recording it would have this run cut
        its branches from that work and fast-forward its own into it — the
        two slices silently welded together."""
        key = str(root)
        if key not in self.state["bases"]:
            cur = self._current_branch(root)
            if cur.startswith("phase/"):
                raise Bailout(
                    "blocked",
                    details=f"{root} is on {cur}, a phase branch — another "
                            "run's, left there when it bailed; check out its "
                            "base branch there and resume")
            self.state["bases"][key] = cur
            self._save_state()
        return self.state["bases"][key]

    def _restore_bases(self) -> None:
        """Put every repo the run touched back on its base branch — run at a
        bail, before the bail record is written.

        A bail is decided after the session that caused it has ended, and
        every resume path checks the branch it needs out again itself, so the
        tree is simply left the way the run found it. A shared repo needs
        nothing here: its phase works in a worktree of its own, which the
        bail leaves for the resume, and the shared checkout never left its
        base. A repo with uncommitted work is left alone: a checkout would
        carry or drop it, and the resume sets it aside before it resets the
        branch (`_set_aside`). So is a branch this run did not create — the
        only branches it checks out are its own `phase/<slice>-…`, and
        anything else under it is a parallel session's business, not a tree
        state to undo. Nothing here may mask the bail, so a git failure is
        logged and swallowed — naming the branch the tree stays on, since
        that is then not its base."""
        mine = f"phase/{self.slice_num}-"
        for key, base in sorted(self.state.get("bases", {}).items()):
            root = Path(key)
            cur = None
            try:
                cur = self._current_branch(root)
                if cur == base:
                    continue
                if not cur.startswith(mine):
                    self.log(f"[bail] {root.name}: left on {cur}, which this "
                             "run did not check out — not touched")
                    continue
                if self._worktree_dirty(root):
                    self.log(f"[bail] {root.name}: left on {cur} with "
                             "uncommitted work — set aside at resume")
                    continue
                self.git("checkout", base, root=root)
                self.log(f"[bail] {root.name}: left on {cur}, checked {base} "
                         "back out")
            except Exception as e:
                why = e.details if isinstance(e, Bailout) else str(e)
                self.log(f"[bail] {root.name}: could not check {base} back "
                         f"out ({why})"
                         + (f" — the tree stays on {cur}; check {base} out "
                            "there by hand" if cur else ""))

    # -- plan ----------------------------------------------------------------

    def _load_plan(self) -> list[Phase]:
        """Parse the plan; on structure errors, nudge the session that
        produced them, then re-parse. A plan still broken after the nudge —
        or broken with no session to nudge (the operator's own edit) — is an
        operator question, not a crash. A pending phase's Target that the
        environment declares and has not cloned is neither: it bails
        `target_not_cloned` at once, an error the launching session can fix
        (clone, `kc project setup`, `--resume`) without touching the plan.

        The component set is re-read first, every load. A phase may register
        a NEW component in the manifest, and the run's opening snapshot would
        call that name invalid for the rest of the run — every re-parse
        re-resolves every `Target:` against it. Slice 181 stood up a second
        Node project and had to fake its phases onto an existing component
        with hand-run gates (#746). This method runs at every `_run_phases`
        iteration, i.e. after every phase merge, so resolution sees the
        manifest as it stands. A failing load bails exactly as run()'s
        opening one does. The sibling repos' sets are dropped with it and
        re-read on the first Target that needs them — a phase may register
        a component in a sibling just the same."""
        self.project_dirs = load_project_dirs(self.repo_root)
        self._sibling_owners = None
        for attempt in (1, 2):
            try:
                text = self.plan_path.read_text()
            except OSError as e:
                raise Bailout("plan_unreadable", details=str(e)) from None
            phases, errors = parse_plan(text)
            errors.extend(self._vanished_phases(phases))
            roots, target_errors, not_cloned = self._plan_targets(phases)
            if not_cloned:
                # Before the nudge, whatever else is wrong: no session can
                # clone the repo, and asked to fix the plan it would edit a
                # Target that was right.
                raise Bailout(
                    "target_not_cloned",
                    details="the plan is fine, but a Target names a repo "
                            "this environment declares and has not cloned:\n"
                            + "\n".join(f"- {e}" for e in not_cloned))
            errors.extend(target_errors)
            errors.extend(self._push_holds(text)[1])
            errors.extend(self._rulings(text)[1])
            if not errors:
                self._track_phases(phases)
                self._track_target_roots(roots)
                return phases
            session, role = self._last_session()
            if attempt == 1 and session:
                self.log("plan doc unparseable — nudging the session that "
                         f"last edited it ({session}): " + "; ".join(errors))
                self._nudge(
                    PLAN_DOC_NUDGE_PROMPT.format(
                        plan_path=self.plan_path,
                        problems="\n".join(f"- {e}" for e in errors)),
                    self.repo_root, session, "[plan-doc]", role)
                continue
            raise Bailout(
                "plan_doc", question=True,
                details="the plan doc needs a fix only you can make:\n"
                        + "\n".join(f"- {e}" for e in errors))
        raise AssertionError("unreachable")

    def _vanished_phases(self, phases: list[Phase]) -> list[str]:
        present = {p.id for p in phases}
        return [f"phase P{pid} vanished from the plan (it is tracked in "
                "state.json; restore it or its heading)"
                for pid in self.state.get("known_phases", [])
                if pid not in present]

    def _plan_targets(self, phases: list[Phase]
                      ) -> tuple[list[str], list[str], list[str]]:
        """(the repo roots the pending phases' Targets resolve to, sorted and
        unique, errors, not cloned). An error is a pending phase whose Target
        does not resolve — unless the plan says a phase creates it and that
        phase has not run yet, which is no error and no root. A Target the
        environment declares and has not cloned (TargetNotCloned) is no plan
        error either: it goes in the third list, in the same `phase P<id>:`
        form, for `_load_plan` to stop on."""
        roots: set[str] = set()
        errors = []
        not_cloned = []
        for index, phase in enumerate(phases):
            if phase.done or not phase.target:
                continue
            try:
                roots.add(str(self._resolve_target(
                    phase.target, creates=phase.creates).git_root))
                continue
            except ValueError as e:
                why, missing = str(e), isinstance(e, TargetNotCloned)
            creator, false_claim = creation_claim(phases, index)
            if creator is not None:
                continue
            (not_cloned if missing else errors).append(
                f"phase P{phase.id}: {false_claim or why}")
        return sorted(roots), errors, not_cloned

    def _tool_roots(self) -> list[Path]:
        """The repos whose tools the run needs: each pending phase's Target
        repo, resolved as `_plan_targets` resolves it (a target a phase
        still has to create, or one that does not resolve — a plan problem
        `_load_plan` reports — is skipped), plus the code repos of the run's
        `bases`, which the loop-tail sweep covers (a resume's are on disk).
        A dry run holds no state of its own and reads the run's."""
        try:
            phases, _ = parse_plan(self.plan_path.read_text())
        except OSError:
            phases = []
        roots: list[Path] = []
        for phase in phases:
            if phase.done or not phase.target:
                continue
            try:
                roots.append(self._resolve_target(
                    phase.target, creates=phase.creates).git_root)
            except ValueError:
                continue
        state = self.state or _read_json(self.state_path)
        bases = state.get("bases") if isinstance(state, dict) else None
        roots.extend(Path(key) for key in sorted(bases or {})
                     if not self._is_spec_root(Path(key)))
        return roots

    def _missing_tools(self) -> str | None:
        """The missing-tools message for this run's repos (`tools_check`),
        None when the pod runs every tool they call."""
        return tools_check(self._tool_roots(), self._current_rulings(),
                           self.repo_root, self.log)

    def _assert_tools(self) -> None:
        """Bail `missing_tools` (an operator question) while a repo the run
        needs calls a tool container this pod does not run. Asked here, not
        met at the gate: a code-writer handed a gate that cannot run spends
        its session finding that out, and the fix restarts the
        environment."""
        details = self._missing_tools()
        if details:
            raise Bailout("missing_tools", question=True, details=details)

    def _missing_services(self) -> str | None:
        """The missing-services message for this run's repos
        (`services_check`, over `_tool_roots`: the host held, another repo's
        unrun services logged), None when the pod runs every service the
        host's environment config declares."""
        return services_check(self._tool_roots(), self._current_rulings(),
                              self.repo_root, self.log)

    def _assert_services(self) -> None:
        """Bail `missing_services` (an operator question) while the host
        repo the run needs declares a service this pod does not run —
        `_assert_tools`' reason, for a suite that reaches postgres on
        localhost instead of a sidecar through cexec. Another repo's are
        asked when its gate goes red (`_unrun_services`)."""
        details = self._missing_services()
        if details:
            raise Bailout("missing_services", question=True, details=details)

    def _setup_targets(self) -> None:
        """`kc project setup` once in each repo the run needs
        (`_tool_roots`) that carries a kc manifest, before the first
        dispatch — fresh and resumed alike. A gate that fails on install
        state rather than the change sends an executor into fix rounds on
        code that is fine: Architecture slice 034 P11 met `No module named
        'click'` (a sibling Target never set up), KubeCoder slice 238 P1 `No
        module named 'croniter'` (a venv behind its lockfile), and `kc
        project setup` fixed both in about a minute. A red or timed-out
        setup warns and the run goes on — the phase gate decides; exit 3 is
        a repo that defines no setup. SETUP_TIMEOUT bounds a hung setup to
        15 minutes per repo."""
        seen: set[Path] = set()
        argv = ["kc", "project", "setup"]
        for root in [Path(r).resolve() for r in self._tool_roots()]:
            if root in seen or not (root / MANIFEST_REL).is_file():
                continue
            seen.add(root)
            log_path = self.slice_dir / "setup" / f"{root.name}.log"
            goes_on = "the run goes on; the gate decides"
            t0 = time.monotonic()
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "w") as log_file:
                    returncode = self._setup_exec(argv, root, log_file)
            except subprocess.TimeoutExpired:
                self.log(f"warning: [setup] {root.name} timed out after "
                         f"{SETUP_TIMEOUT}s (output in {log_path}) — "
                         f"{goes_on}")
                continue
            except OSError as e:
                self.log(f"warning: [setup] {root.name}: `{' '.join(argv)}` "
                         f"could not run ({e}) — {goes_on}")
                continue
            duration_s = int(time.monotonic() - t0)
            outcome = kc_outcome(returncode)
            if outcome == "red":
                self.log(f"warning: [setup] {root.name} → RED (exit "
                         f"{returncode}, {duration_s}s, output in "
                         f"{log_path}) — {goes_on}")
                continue
            self.log(f"[setup] {root.name} → {GATE_OUTCOME_LABELS[outcome]} "
                     f"({duration_s}s)"
                     + (" — the repo defines no setup"
                        if outcome == "nothing_ran" else ""))

    def _setup_exec(self, argv: list[str], cwd: Path, log_file) -> int:
        """One `kc project setup`'s exit code, its output into `log_file` —
        the subprocess seam of `_setup_targets`, isolated for tests."""
        return subprocess.run(
            argv, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT,
            timeout=SETUP_TIMEOUT).returncode

    def _track_phases(self, phases: list[Phase]) -> None:
        known = [p.id for p in phases]
        if known != self.state.get("known_phases"):
            fresh = [pid for pid in known
                     if pid not in self.state.get("known_phases", [])]
            if fresh and self.state.get("known_phases"):
                # Phases the plan gained after the run started — appended
                # by a consult, the test phase, or the operator; the
                # close-out header reads planned vs appended off this.
                self.log(f"new phase(s) in the plan: {', '.join(fresh)}")
                self.state.setdefault("appended_phases", []).extend(fresh)
            self.state["known_phases"] = known
            self._save_state()

    def _track_target_roots(self, roots: list[str]) -> None:
        """The repos the plan's pending phases target, as this load resolved
        them — replaced every load, never accumulated: a phase done since
        stands in `landed`, and one the plan dropped is no repo of the
        slice's. The close-out routes read them with the landed roots
        (`close_out.touched_repos`), so an entry naming the repo a phase
        still in its rounds targets is not elsewhere."""
        if roots != self.state.get("target_roots"):
            self.state["target_roots"] = roots
            self._save_state()

    def _last_session(self) -> tuple[str | None, str | None]:
        """The last recorded session and its role — the one that last
        edited the plan, for the plan-doc nudge."""
        for entry in reversed(self.state.get("history", [])):
            if entry.get("session"):
                return entry["session"], entry.get("role")
        return None, None

    def _sibling_repos(self) -> list[Path]:
        """The environment's other repos with a kc manifest: every git
        checkout beside the invoking repo (a `.git` file is a worktree, still
        a checkout) that carries `.kubecoder/project.yaml`. In a KubeCoder
        pod every repo of the environment is checked out side by side under
        /work — the layout preflight's sync walks and `../Repo` Targets
        already assume."""
        primary = self.repo_root.resolve()
        try:
            beside = sorted(self.repo_root.parent.iterdir())
        except OSError:
            return []
        return [d.resolve() for d in beside
                if d.is_dir() and d.resolve() != primary
                and (d / ".git").exists()
                and (d / ".kubecoder" / "project.yaml").is_file()]

    def _sibling_component_owners(self) -> dict[str, list[Path]]:
        """Component name → the sibling repos whose `kc project list` has it.

        Read only once a Target misses the invoking repo's own set, and kept
        until `_load_plan` re-reads the manifests. kc reads each manifest,
        from that repo's root, as it does the invoking one. A sibling kc
        cannot list is skipped with a log line and named in the not-found
        error, never a bail: the name the plan wants may live in another
        sibling, and one that does not stays a plan problem the plan's
        author can fix."""
        if self._sibling_owners is None:
            owners: dict[str, list[Path]] = {}
            self._siblings_listed, self._siblings_unlisted = [], []
            for sibling in self._sibling_repos():
                try:
                    components = load_project_dirs(sibling)
                except Bailout as e:
                    self._siblings_unlisted.append(sibling.name)
                    self.log(f"sibling components: {sibling.name} skipped — "
                             f"{e.details}")
                    continue
                self._siblings_listed.append(sibling.name)
                for name in components:
                    owners.setdefault(name, []).append(sibling)
            self._sibling_owners = owners
        return self._sibling_owners

    def _resolve_target(self, target: str, creates: str | None = None,
                        held: bool = False) -> ResolvedTarget:
        """A `kc project list` component, a sibling repo path, or a GitHub
        repo (`github:<owner>/<repo>`, cloned into the scratch root by
        `github_target.ensure_clone` and a sibling path from then on).
        Raises ValueError with a fix-it message for anything else.

        The invoking repo's components come first and shadow any sibling's
        (every repo has a `root`, and `Target: root` means this one's). A
        bare name that misses them is looked up in the sibling repos'
        components: found in exactly one, it is that repo's component —
        branched, merged and pushed there like a sibling path, gated per
        component from that repo's root; found in several, the plan has to
        say which repo.

        `creates` is the caller's phase's own `Creates:` declaration: a phase
        that registers its own target resolves optimistically, because the
        executor registers the component mid-phase and the gate runs after —
        by then the argv below is right. Only `_run_phase` passes it; every
        other caller (push holds, dry run, the plan check) stays strict. The
        optimism is the invoking repo's: a component a phase registers in a
        sibling is declared on that phase (`Target: ../Repo`, `Creates:`),
        and the later phases that target it resolve here once it is
        listed.

        `held` is a `## Push holds` entry's resolution (`_push_holds`, the
        dry run). A run commits to a held repo whether or not a phase
        targets it — a ledger phase's `/work/scratch` clones are targeted by
        none — so a held GitHub clone that exists is the run's own: checked,
        never synced, as `_owns_clone` makes a Target's. Synced, it is
        refused for the commits origin lacks once the run has committed
        there, and the hold becomes a plan structure error. A held clone
        that does not exist yet is cloned, as for a Target."""
        self_created = (creates is not None and creates == target
                        and not is_repo_path(target))
        if target in self.project_dirs or self_created:
            return ResolvedTarget(
                target, "project", self.repo_root,
                ["kc", "project", "test", "--project", target],
                self.repo_root)
        if github_target.is_github(target):
            # Cloned (or synced) once; from here it is a sibling path.
            owned = self._owns_clone(target) or (
                held and github_target.clone_path(target).exists())
            path = github_target.ensure_clone(target, owned=owned)
            return self._repo_path_target(target, path.resolve())
        if target.startswith(("../", "/")):
            path = (self.repo_root / target).resolve() \
                if not target.startswith("/") else Path(target)
            return self._repo_path_target(target, path)
        owners = self._sibling_component_owners().get(target, [])
        if len(owners) == 1:
            root = owners[0]
            return ResolvedTarget(
                target, "project", root,
                ["kc", "project", "test", "--project", target], root)
        if owners:
            raise ValueError(
                f"Target `{target}` is a component of several sibling repos "
                f"({', '.join(r.name for r in owners)}) — write the repo "
                f"path instead (`../{owners[0].name}`)")
        searched = ", ".join(self._siblings_listed) or "none"
        if self._siblings_unlisted:
            searched += ("; `kc project list` failed in "
                         + ", ".join(self._siblings_unlisted))
        raise ValueError(
            f"Target `{target}` is neither a `kc project list` component "
            f"({', '.join(sorted(self.project_dirs)) or 'none found'}) nor "
            "a sibling repo path (`../Repo`), and no sibling repo's "
            f"components have it (siblings searched: {searched})")

    @staticmethod
    def _repo_path_target(target: str, path: Path) -> ResolvedTarget:
        """A whole repo at `path` as a Target — a sibling path, or a GitHub
        target's clone. One that is missing because config.yaml declares it
        and the pod has not cloned it raises TargetNotCloned; kc is asked
        only then, and when it cannot answer the plain messages stand."""
        if not path.is_dir() or not (path / ".git").exists():
            message = not_cloned_message(target, path)
            if message:
                raise TargetNotCloned(message)
        if not path.is_dir():
            raise ValueError(f"Target `{target}` is not an existing "
                             "directory")
        if not (path / ".git").exists():
            raise ValueError(f"Target `{target}` is not a git repo")
        # A sibling with its own manifest gates through kc from its own
        # root; one without has no deterministic gate — the reviewer is
        # told the state is unverified. The manifest is looked for at gate
        # time, in the phase's tree (`ResolvedTarget.gate_argv`).
        return ResolvedTarget(target, "sibling", path, None, path,
                              manifest_gate=True)

    def _owns_clone(self, target: str) -> bool:
        """Is this GitHub target's clone one of this slice's run's repos
        (`state["bases"]`)? Then its base may carry the run's merged,
        unpushed phases, and resolution checks the clone without syncing
        it. A dry run holds no state of its own and reads the run's from
        disk, so one started mid-run leaves the live run's clone alone."""
        try:
            key = str(github_target.clone_path(target).resolve())
        except ValueError:
            return False
        state = self.state or _read_json(self.state_path)
        bases = state.get("bases") if isinstance(state, dict) else None
        return isinstance(bases, dict) and key in bases

    def _stamp_done(self, phase_id: str) -> None:
        """The driver's mechanical `✅ DONE` stamp, committed in the specs
        repo by name, on its base. Agents never stamp. Called after the phase
        merged — into that very base, when the specs repo is the target."""
        if not stamp_phase(self.plan_path, phase_id, _today()):
            raise Bailout(
                "plan_doc", question=True,
                details=f"phase P{phase_id} merged but its heading is gone "
                        "from the plan — restore it so the stamp can land")
        self._assert_spec_on_base()
        self.specs_git("add", str(self.plan_path))
        self.specs_git("commit", "-m",
                       f"slice {self.slice_num}: stamp P{phase_id} done")
        self.log(f"[P{phase_id}] stamped ✅ DONE")

    # -- session spawning ----------------------------------------------------

    def _assert_current(self) -> None:
        """Before the run and before every dispatch: the installed plugin —
        the one the agent about to run loads — is this loop's,
        verification.json holds no key this loop would ignore, and
        close-out.md holds no edit a write would drop. Each can change under
        a running loop (a marketplace update, a newer agent, the operator)."""
        assert_plugin_current(Path(__file__).name,
                              " plus --resume (a run loop resumes from "
                              "state.json)")
        assert_verification_keys(self.slice_dir)
        self._assert_report_unedited()

    def _assert_report_unedited(self) -> None:
        """Bail (`report_edited`, an operator question) while close-out.md
        carries an edit the next write to it would drop: the agent about to
        run writes to the report, and its write would be refused. A report
        that cannot be read is logged — its writers meet that themselves."""
        try:
            edited = edited_report(self.slice_dir)
        except ReportError as e:
            self.log(f"close-out not checked for an edit ({e})")
            return
        if edited is not None:
            raise Bailout("report_edited", question=True, details=str(edited))

    def _report_refused(self, e: ReportError) -> None:
        """A driver write close_out.py refused: mid-run, an edit the write
        would drop is an operator question (`report_edited`) — the run stops
        rather than write past it. Every other refusal, and this one where
        the run is stopping or done (`_report_logged`), is the caller's to
        log."""
        if isinstance(e, ReportEdited) and not self._report_quiet:
            raise Bailout("report_edited", question=True, details=str(e)) from None

    @contextlib.contextmanager
    def _report_logged(self):
        """Driver writes to the report inside log a refusal for an edit,
        never stop on it: at a bail (no second bail), in the wrap-up (never
        a stop) and at completion (the run's work is done; /dev:run-slice
        re-stamps and meets the refusal itself)."""
        prior = self._report_quiet
        self._report_quiet = True
        try:
            yield
        finally:
            self._report_quiet = prior

    def _commit_own_entries(self, before: str) -> None:
        """Before a dispatch, commit the store when it changed. The driver's
        own entries (`_report`, the hold notes, a resume's stops) are written
        mid-run, and the role about to run commits the store staged by name
        — a JSON store is not staged in part, so its commit would carry them
        too. Committed here, the role's commit holds only its own entries;
        whatever else the store held uncommitted (an earlier session's
        append) goes in with the driver's. close-out.md changed alone is an
        agent's render, left uncommitted by design: no commit. Never fatal —
        a commit that fails is logged, and the entries ride the role's
        commit instead."""
        store = store_path(self.slice_dir)
        try:
            if not store.exists() or not self.specs_git(
                    "status", "--porcelain", "--", str(store)):
                return
            self._commit_report(
                f"slice {self.slice_num}: close-out report before {before}",
                label="[close-out]")
        except Exception as e:
            why = (e.details if isinstance(e, Bailout)
                   else f"{type(e).__name__}: {e}")
            self.log(f"[close-out] report not committed before {before} "
                     f"({why}) — the driver's entries ride its commit")

    def _nudge(self, prompt: str, cwd: Path, session_id: str,
               label: str, role: str | None, retry: bool = True) -> bool:
        """One resume-shot at a session that missed part of its protocol;
        returns whether the FIRST send was swallowed. Failures fall through
        to the caller's re-check; a nudge never raises, save the
        `_assert_current` bail every dispatch takes. `role` is the
        resumed session's, so the resume carries the same spawn flags (a
        differing prefix would miss the cache).

        A send the harness swallows for its stopped-task recovery
        (`swallowed_nudge`) never reached the model. Under `retry` the same
        prompt goes in once more — exactly one retry, whatever that one
        comes back with — which is what the commit, push and doc-gate nudges
        want: their session's work was done, it just has to hear the ask.
        The verdict nudge's caller reads the swallowed signal itself instead:
        a session cut mid-wait is resumed with `LOST_WAIT_PROMPT` rather than
        asked the same question twice."""
        self.log(f"{label} nudging the session (resume)")

        def send():
            try:
                self._assert_current()
                self._commit_own_entries(f"the {role} nudge" if role
                                         else "the nudge")
                _, result = run_kc_session(
                    prompt=prompt, cwd=str(cwd), timeout=NUDGE_TIMEOUT,
                    resume_session=session_id, extra_env=SPAWN_ENV,
                    flags=spawn_flags(role, self.log),
                    progress=lambda line: self._emit(f"    {label} {line}"),
                )
            except subprocess.TimeoutExpired:
                self.log(f"{label} nudge timed out")
                return None
            return result

        result = send()
        if result is None or not swallowed_nudge(result):
            return False
        if not retry:
            return True
        self.log(f"{label} nudge swallowed by the harness's stopped-task "
                 "recovery — sending it once more")
        send()
        return True

    def _ensure_committed(self, phase_id: str | None, role: str,
                          session_id: str | None, root: Path,
                          verdict: dict | None = None,
                          verdict_path: Path | None = None
                          ) -> dict | None:
        """An agent must leave the worktree clean. Dirty → one resume-nudge
        asking it to commit; still dirty → bail (the driver never commits an
        agent's leftovers itself).

        The commit nudge is also the round's last word on its verdict: a
        session that ended without one routinely writes it while committing.
        Given the round's `verdict` and `verdict_path`, the (possibly
        salvaged) verdict is returned — see `_salvage_nudged_verdict`. A
        caller with no verdict to repair passes neither and ignores the
        return."""
        if not self._worktree_dirty(root):
            return verdict
        label = f"[P{phase_id}] [{role}]" if phase_id else f"[{role}]"
        if session_id:
            self._nudge(COMMIT_NUDGE_PROMPT, root, session_id, label, role)
            if not self._worktree_dirty(root):
                self.log(f"{label} committed its leftovers on the nudge")
                return self._salvage_nudged_verdict(
                    phase_id, role, label, verdict, verdict_path)
        raise Bailout(
            "protocol_failure", phase=phase_id,
            details=f"{role} left uncommitted changes in {root}"
                    + (" after a commit nudge" if session_id
                       else "; no session to nudge"),
        )

    def _salvage_nudged_verdict(self, phase_id: str | None, role: str,
                                label: str, verdict: dict | None,
                                verdict_path: Path | None) -> dict | None:
        """A verdict written during the commit nudge counts. `_spawn` rules
        a round with no valid verdict a protocol failure and calls it
        `blocked`; when the commit nudge then leaves a verdict on disk that
        is valid for the role, that verdict is the round's — here, in the
        history row `_spawn` already wrote, and in what the caller acts on.
        A nudge that leaves no valid verdict changes nothing: `blocked`
        stands. This is the only place the ruling is revised."""
        if not (verdict_path and verdict
                and verdict.get("_protocol_failure")):
            return verdict
        fresh = _read_json(verdict_path)
        if not _verdict_valid(role, fresh):
            return verdict
        outcome, summary = fresh.get("outcome"), fresh.get("summary", "")
        self.log(f"{label} wrote its verdict on the commit nudge — salvaged")
        self.log(f"{label} → {outcome}: {summary[:160]}")
        row = (self.state.get("history") or [{}])[-1]
        if (row.get("role"), row.get("phase"), row.get("outcome")) \
                == (role, phase_id, "blocked"):
            row["outcome"] = outcome
            row["summary"] = summary
            row.update({k: fresh[k] for k in ("findings", "refuted")
                        if isinstance(fresh.get(k), list) and fresh[k]})
            self._save_state()
        return fresh

    def _spawn(self, role: str, prompt: str, cwd: Path, verdict_path: Path,
               phase_id: str | None, round_: int,
               agent: str | None = None,
               display: str | None = None) -> tuple[dict, str | None]:
        """Run one round; return (verdict, session_id). `_dispatch_rounds`
        does the running — this is the ruling on what came back, and the
        round's one history row.

        A round interrupted after it wrote its verdict is never re-run: the
        file on disk is that round's (every dispatch unlinks it first), so
        `_salvage_reattach` takes it and no session is dispatched at all.

        Every dispatch enters the stops a resume has not reported yet
        (`_report_bailouts`) before anything else: this is the first moment
        the report exists and the stop is known to be over."""
        self._report_bailouts()
        shown = display or role
        label = f"[P{phase_id}] [{shown}]" if phase_id else f"[{shown}]"
        salvaged = self._salvage_reattach(role, phase_id, verdict_path, label)
        if salvaged is not None:
            verdict, session_id = salvaged
            returncode, duration_s, nudged, recoveries = 0, 0, False, 0
        else:
            (returncode, verdict, session_id, duration_s, nudged,
             recoveries) = self._dispatch_rounds(
                role, prompt, cwd, verdict_path, phase_id, round_, agent,
                shown, label)
        return self._rule_on_round(
            role, verdict, verdict_path, cwd, phase_id, round_, label,
            returncode, session_id, duration_s, nudged, recoveries)

    def _dispatch_rounds(self, role: str, prompt: str, cwd: Path,
                         verdict_path: Path, phase_id: str | None,
                         round_: int, agent: str | None, shown: str,
                         label: str) -> tuple:
        """Drive one round to something to rule on; return (returncode,
        verdict, session_id, duration_s, nudged, recoveries).

        Every spawn is a fresh session — the only resumed sessions are crash
        reattaches and protocol nudges. Model and effort come from the MODELS
        config, passed explicitly on every dispatch. Each dispatch asserts
        the spec tree on its base first: an agent dispatched while it sits on
        another branch commits its plan edits and close-out entries there.
        Then it commits the store when the driver's entries, or anything
        else, left it changed (`_commit_own_entries`), so the role's own
        commit of the store holds only its entries."""
        prompt, resume_session = self._resolve_reattach(
            role, phase_id, prompt, verdict_path, label)
        model, effort = MODELS[role]

        def _valid(v: dict | None) -> bool:
            return _verdict_valid(role, v)

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(cwd, sid)}")
            in_flight = self.state.get("in_flight")
            if in_flight and in_flight.get("session") != sid:
                in_flight["session"] = sid
                self._save_state()

        nudged = False
        recoveries = 0
        carried_s = 0        # the round's seconds before a recovery resume
        while True:
            self.log(f"{label} session starting"
                     + (" (resume)" if resume_session else ""))
            self.announce((f"P{phase_id} " if phase_id else "") + shown
                          + (f" r{round_}" if round_ else "")
                          + (" (resume)" if resume_session else ""))
            verdict_path.unlink(missing_ok=True)

            self.state["in_flight"] = {
                "phase": phase_id, "role": role, "round": round_,
                "verdict_path": str(verdict_path), "session": resume_session,
                "started_at": _now_iso(),
            }
            self._save_state()

            t0 = time.monotonic()
            try:
                self._assert_spec_on_base()
                self._assert_current()
                self._commit_own_entries(
                    (f"P{phase_id} " if phase_id else "") + shown)
                returncode, result = run_kc_session(
                    prompt=prompt,
                    cwd=str(cwd),
                    timeout=TIMEOUTS[role],
                    agent=agent,
                    model=model,
                    effort=effort,
                    resume_session=resume_session,
                    extra_env=SPAWN_ENV,
                    flags=spawn_flags(role, self.log),
                    progress=lambda line: self._emit(f"    {label} {line}"),
                    on_session=_note_session,
                )
            except subprocess.TimeoutExpired:
                # A timed-out session is stuck, not crashed — never reattach.
                # Its id was learned during the turn, so the salvaged round
                # still names the conversation its transcript is under.
                stuck = (self.state.get("in_flight") or {}).get("session")
                self.state["in_flight"] = None
                self._save_state()
                # The verdict file is unlinked at every dispatch, so one
                # present now was written by this round — the agent finished
                # its work and the turn wedged after. Salvage it; the round
                # is only lost when the verdict is missing or unparseable.
                verdict = _read_json(verdict_path)
                if not _valid(verdict):
                    raise Bailout(
                        "timeout", phase=phase_id,
                        details=f"{role} exceeded {TIMEOUTS[role]}s",
                    ) from None
                self.log(f"{label} timed out after {TIMEOUTS[role]}s, but had "
                         f"already written {verdict_path.name} — salvaged")
                duration_s = TIMEOUTS[role]
                session_id = stuck or resume_session
                returncode = 0
                break
            duration_s = int(time.monotonic() - t0)

            session_id = result.session_id
            verdict = _read_json(verdict_path)
            notice = None if _valid(verdict) else session_limit_notice(result)
            if notice is not None:
                # The account's window, not this agent's failure: record it,
                # wait it out, and dispatch the same round again.
                self.state["in_flight"] = None
                self._record(phase_id, role, round_, "session_limit",
                             notice.replace("\n", " ")[:200], session_id,
                             duration_s,
                             transcript=_transcript_path(cwd, session_id))
                self._wait_out_session_limit(notice, label)
                continue
            if _valid(verdict) or not session_id:
                break

            # The session ended without a verdict. One nudge — but a nudge
            # the harness swallows for its stopped-task bookkeeping is a
            # session cut mid-wait (a sub-agent's or a backgrounded
            # command's report died with the process), not one that forgot
            # its verdict, and the verdict nudge's "do not start new work"
            # leaves it no legal move. Such a session is resumed with the
            # recovery prompt under the role's own timeout, so it can
            # recover the lost report and finish; past LOST_WAIT_CAP the
            # nudge falls back to its same-prompt retry.
            outcomes = (f"; outcome must be one of {sorted(VERDICTS[role])}"
                        if role in VERDICTS else "")
            swallowed = self._nudge(
                VERDICT_NUDGE_PROMPT.format(verdict_path=verdict_path,
                                            outcomes=outcomes),
                cwd, session_id, label, role,
                retry=recoveries >= LOST_WAIT_CAP)
            if swallowed and recoveries < LOST_WAIT_CAP:
                recoveries += 1
                carried_s += duration_s
                self.log(f"{label} nudge swallowed by the harness's "
                         f"stopped-task recovery — the session was cut "
                         f"mid-wait; resuming it to recover the lost report "
                         f"and finish ({recoveries}/{LOST_WAIT_CAP})")
                prompt = LOST_WAIT_PROMPT.format(verdict_path=verdict_path,
                                                 outcomes=outcomes)
                resume_session = session_id
                continue
            nudged = True
            verdict = _read_json(verdict_path)
            if _valid(verdict):
                returncode = 0  # the nudge completed the protocol
            break

        # The round's duration covers its recovery resumes too.
        return (returncode, verdict, session_id, duration_s + carried_s,
                nudged, recoveries)

    def _rule_on_round(self, role: str, verdict: dict | None,
                       verdict_path: Path, cwd: Path, phase_id: str | None,
                       round_: int, label: str, returncode: int,
                       session_id: str | None, duration_s: int,
                       nudged: bool, recoveries: int) -> tuple[dict, str | None]:
        """The round's outcome and its one history row.

        Only an invalid verdict is a protocol failure. A session killed after
        it wrote a valid one (rc != 0 — a SIGTERM'd worker, a send the
        harness lost after the turn) counts for exactly the reason the
        timeout salvage counts: the file was unlinked at dispatch, so a valid
        one on disk is this round's, and writing it is the last step of every
        role's protocol."""
        if not _verdict_valid(role, verdict):
            detail = _protocol_failure_detail(
                role, returncode, verdict, verdict_path.name,
                False, nudged, recoveries=recoveries)
            verdict = {"outcome": "blocked", "summary": detail,
                       "_protocol_failure": True}
        elif returncode != 0:
            self.log(f"{label} session ended rc={returncode} but had written "
                     f"{verdict_path.name} — salvaged")
        outcome = verdict.get("outcome", "blocked")
        self.state["in_flight"] = None
        self.log(f"{label} → {outcome}: {verdict.get('summary', '')[:160]}")
        # Per-finding telemetry rides the history row: the reviewer's
        # `findings` (severity/impact/category/anchor per finding) and a fix
        # round's `refuted` list persist as the agent reported them.
        telemetry = {k: verdict[k] for k in ("findings", "refuted")
                     if isinstance(verdict.get(k), list) and verdict[k]}
        self._record(phase_id, role, round_, outcome,
                     verdict.get("summary", ""), session_id, duration_s,
                     transcript=_transcript_path(cwd, session_id),
                     extra=telemetry)
        if verdict.get("cards"):
            # A pre-0.5.0 register still on an installed clone: not a
            # protocol failure — the findings belong in close-out.md.
            self.log(f"{label} verdict carried a `cards` list — ignored; "
                     f"out-of-scope findings go in {self.report_path.name}")
        return verdict, session_id

    def _pending_reattach(self, role: str, phase_id: str | None) -> dict | None:
        """The in-flight record a crashed run left for this role and phase,
        or None."""
        r = self._reattach
        if r and role in VERDICTS and r.get("role") == role \
                and r.get("phase") == phase_id:
            return r
        return None

    def _reattach_round(self, role: str, phase_id: str | None) -> int | None:
        """The round number the interrupted round already banked, or None
        when this dispatch is a fresh round. A resume must not advance a
        counter the crashed round advanced: a second number means the round's
        verdict file is looked for under a name nothing wrote, so finished
        work is re-run (#957)."""
        r = self._pending_reattach(role, phase_id)
        return r.get("round") if r else None

    def _salvage_reattach(self, role: str, phase_id: str | None,
                          verdict_path: Path,
                          label: str) -> tuple[dict, str | None] | None:
        """The verdict the interrupted round had already written, with the
        session that wrote it — or None, leaving the reattach to
        `_resolve_reattach`.

        A send that hangs after the turn is over leaves a finished round
        behind: the work is committed and the verdict is on disk. Dispatching
        anything there is paying twice for one round. The file is only this
        round's when the record names the same path — an interrupted round
        whose dispatch now computes a different name proves nothing about
        what is lying there."""
        r = self._pending_reattach(role, phase_id)
        if r is None:
            return None
        recorded = r.get("verdict_path")
        if not recorded \
                or Path(recorded).resolve() != Path(verdict_path).resolve():
            if recorded:
                self.log(f"{label} the interrupted round wrote {recorded}, "
                         f"not {verdict_path} — nothing to salvage")
            return None
        verdict = _read_json(verdict_path)
        if not _verdict_valid(role, verdict):
            return None
        self._reattach = None
        self.log(f"{label} the interrupted round had already written "
                 f"{verdict_path.name} — salvaged, no session dispatched")
        return verdict, r.get("session")

    def _resolve_reattach(self, role: str, phase_id: str | None, prompt: str,
                          verdict_path: Path,
                          label: str) -> tuple[str, str | None]:
        """If this spawn matches the session a crashed run left in flight,
        resume that session with a recovery prompt instead of dispatching
        fresh. Consults never reattach (cheap, and their action vocabulary
        may have changed). The record is spent either way — a crash that
        never heard a session id leaves nothing to resume, and this round is
        the one it belonged to."""
        r = self._pending_reattach(role, phase_id)
        if r is None:
            return prompt, None
        self._reattach = None
        if not r.get("session"):
            return prompt, None
        self.log(f"{label} reattaching to the interrupted session "
                 f"{r['session']}")
        return REATTACH_PROMPT.format(verdict_path=verdict_path), r["session"]

    def _wait_out_session_limit(self, notice: str, label: str) -> None:
        reset = parse_session_limit_reset(notice)
        if reset is None:
            seconds = float(SESSION_LIMIT_FALLBACK)
            when = "no parseable reset time"
        else:
            seconds = (reset - datetime.now(reset.tzinfo)).total_seconds() \
                + SESSION_LIMIT_GRACE
            when = f"resets {reset.astimezone().isoformat(timespec='minutes')}"
        seconds = max(0.0, min(seconds, float(SESSION_LIMIT_MAX_SLEEP)))
        self.log(f"{label} account session limit — {when}; sleeping "
                 f"{int(seconds)}s, then redispatching the same round "
                 "(no round spent, no nudge, no consult)")
        self._sleep(seconds)

    def _sleep(self, seconds: float) -> None:
        """The driver's only wall-clock wait, isolated so tests can take it
        out."""
        time.sleep(seconds)

    def _consult(self, site: str, situation: str, actions: dict[str, str],
                 material: list[Path], phase_id: str | None) -> dict:
        """Spawn a fresh bare consult session; return its verdict
        (validated). `site` names the decision point in log lines."""
        n = self.state["consult_seq"] = self.state.get("consult_seq", 0) + 1
        self._save_state()
        base = (self.slice_dir / "phases" / f"P{phase_id}"
                if phase_id else self.slice_dir)
        base.mkdir(parents=True, exist_ok=True)
        verdict_path = base / f"consult_{n}.json"
        phase_line = f"Phase: P{phase_id}\n" if phase_id else ""
        prompt = CONSULT_PROMPT.format(
            slice_name=self.slice_name,
            situation=situation,
            phase_line=phase_line,
            slice_dir=self.slice_dir,
            close_out_line=dispatch_line(self.report_path),
            material="\n".join(f"- {p}" for p in material) or "- (state.json only)",
            actions="\n".join(f"- `{a}` — {why}" for a, why in actions.items()),
            verdict_path=verdict_path,
            consult_md_name=f"consult_{n}.md",
        )
        verdict, _ = self._spawn(
            "consult", prompt, self.repo_root, verdict_path, phase_id, n,
            display=f"consult: {site}",
        )
        if verdict.get("outcome") not in actions:
            raise Bailout(
                "protocol_failure", phase=phase_id, consult=str(verdict_path),
                details=f"consult chose {verdict.get('outcome')!r}, "
                        f"offered {sorted(actions)}",
            )
        if verdict["outcome"] == "bail":
            raise Bailout(
                "consult_bail", phase=phase_id, consult=str(verdict_path),
                details=verdict.get("summary", ""),
            )
        return verdict

    # -- the deterministic test gate -----------------------------------------

    def _phase_gate(self, phase_id: str, ps: dict, outputs: Path,
                    target: ResolvedTarget,
                    merge_base: str) -> tuple[bool, Path | None]:
        """The phase's gate as every caller takes it — the first gate, a fix
        round's re-gate, the merge's re-gate. A target plan.md's `## Driver
        rulings` waives passes unrun, like a target with no deterministic
        gate: no green commit is recorded, the reviewer is told why, and no
        fix round is spent on a red the operator already ruled on — nor are
        the components its diff touches run, which gate beside the Target's
        own and not instead of it.

        `merge_base` is the base of the range the review reads — the one
        `_run_phase` takes, re-taken by a rebase onto a moved base — so the
        components a component Target's gate takes in are those of the diff
        its reviewer is handed (`_touched_components`).

        A GitHub clone still without a manifest here is a phase that said
        (`Creates:`) it would add one and did not: nothing would verify it,
        so the run stops on the operator's question, as `_run_phase` does
        before the writer, rather than passing it unverified."""
        ruling = self._gate_ruling(target)
        if ruling is None:
            self._refuse_ungated_github(phase_id, target)
            return self._run_gate(phase_id, ps, outputs, target, merge_base)
        self.log(f"[P{phase_id}] test gate for {target.name} waived by "
                 f"plan.md's `## Driver rulings` (substitute: "
                 f"{ruling.substitute_text}) — not run, proceeding "
                 "(reviewer told unverified)")
        self._report_ruling(ruling, "phase gate")
        return True, None

    def _run_gate(self, phase_id: str, ps: dict, outputs: Path,
                  target: ResolvedTarget,
                  merge_base: str) -> tuple[bool, Path | None]:
        """Run the target's test gate as a subprocess: (passed, its log).
        The exit code decides; full output goes to gate_r<N>.log in the
        phase's outputs dir, kc's full-output file inlined after kc's own
        lines (`_gate_cmd_outcome`) — the log is the review's artifact and
        must stand on its own. A target with no deterministic gate (a sibling
        repo whose phase tree has no manifest now — looked for at gate time,
        so a manifest the phase itself added gates it) passes by definition
        — but records no green commit, so the reviewer is told the state is
        unverified.

        A gate kc says ran nothing (KC_NOTHING_RAN: the target defines no
        tests) passes the same way, and for the same reason: a fix round
        has nothing to fix, and a gate that can never go green would spend
        the fix cap and bail `gate_red` — at the gate stage and at the
        merge's re-gate alike. No green commit is recorded; the head it ran
        nothing on is, so the reviewer's line can say why the state is
        unverified. The history row says `nothing_ran`, never green.

        `Target: root` is the repo as a whole, and its gate is two steps:
        root's own `test:` first, the bare `kc project test` — every
        component once — only when that ran nothing. Root's own statement is
        what the manifest's author made the whole-repo gate (KubeCoder's is
        the uv workspace's one pytest run; bare there would also run every
        component's disjoint suite for a Python-only phase); where root
        declares none (FieldnotesApp, on purpose: its CI runner runs both
        component suites itself), the whole repo is the gate instead of an
        unverified pass. Either way no suite runs twice. The second run
        appends to the same log, and `gate_cmd` records the command whose
        outcome stands, for the reviewer's line and the fix round's.

        Any other component Target gates every component its diff touches
        as well (AIWF-91 — PilotApp's `Target: frontend` phase committed
        backend code and tests, and its reviewer was told GREEN about
        frontend's suite alone): each `kc project test --project <c>` after
        the Target's own, into the same log, every one run so every red is
        known; one a gate ruling covers is waived, not run. `gate_projects`
        records each project's command and outcome, the Target first, and
        the gate's outcome is theirs together: red on any red, else green on
        any green, else nothing ran. A whole-repo Target records none.

        The writer runs this same gate before it hands back, through the
        `gate` wrapper, and the driver used to run it again on the tree the
        writer had just seen green (AIWF-93 — on PilotApp, 75 % of driver
        gates re-ran such a green). So the latest code-writer round's record
        of that run, where it passes `_reusable_writer_gate` — the commands
        this gate would run, none red, on a tree unchanged since the run
        began — is replayed in place of running anything: the same code
        lays out the log, records the outcome and the green or empty head,
        and only the log's header, the narration and the history row's
        `reused` say it was the writer's run. A record that fails a check is
        logged with why, and the gate runs as it always did. A flaky suite
        green once on that tree is taken as green: an accepted risk."""
        if target.gate_argv is None:
            self.log(f"[P{phase_id}] no deterministic gate for "
                     f"{target.name} — proceeding (reviewer told unverified)")
            return True, None
        ps["gate_runs"] += 1
        n = ps["gate_runs"]
        ps["gate_projects"] = None
        self._save_state()
        log_path = outputs / f"gate_r{n}.log"
        argv = target.gate_argv
        touched = (self._touched_components(phase_id, target, merge_base)
                   if self._gates_touched(target) else None)
        gates = ([(r, t) for r, t in self._current_rulings()
                  if r.kind == "gate"] if touched is not None else [])
        record_path = outputs / writer_gate_record_name(ps["executor_rounds"])
        replay = tree = None
        if record_path.exists():
            record, found = self._reusable_writer_gate(record_path, target,
                                                       touched, gates)
            if record is None:
                self.log(f"[P{phase_id}] the writer's gate run "
                         f"({record_path.name}) not reused — {found}; "
                         "running the gate")
            else:
                tree = found
                replay = self._writer_gate_replay(phase_id, record_path,
                                                  record)
        also = (f", and for the components the phase's diff touches: "
                f"{', '.join(touched)}" if touched else "")
        if replay is None:
            self.log(f"[P{phase_id}] gate #{n} running ({' '.join(argv)})"
                     + also)
        else:
            self.log(f"[P{phase_id}] gate #{n} reusing the writer's run "
                     f"({record_path.name}) — tree {tree[:12]} unchanged "
                     "since it began" + also)
        t0 = time.monotonic()
        projects = None
        with open(log_path, "w") as log_file:
            if replay is not None:
                log_file.write(f"=== the writer's run of this gate, reused: "
                               f"{record_path} — the tree ({tree}) is the one "
                               "it ran on, unchanged since it began; its "
                               "output follows ===\n")
            outcome, tail = self._gate_cmd_outcome(phase_id, argv, target,
                                                   log_file, log_path, replay)
            if outcome == "nothing_ran" and self._is_root(target):
                self.log(f"[P{phase_id}] `{' '.join(argv)}` ran nothing — "
                         "root declares no tests, so the gate is the whole "
                         f"repo: `{' '.join(REPO_GATE_ARGV)}`")
                argv = REPO_GATE_ARGV
                log_file.write(f"\n=== `{' '.join(target.gate_argv)}` ran "
                               "nothing (exit 3) — the gate is the whole repo:"
                               f" `{' '.join(argv)}` ===\n")
                log_file.flush()
                outcome, tail = self._gate_cmd_outcome(phase_id, argv, target,
                                                       log_file, log_path,
                                                       replay)
            if touched is not None:
                projects = [{"project": target.name, "cmd": " ".join(argv),
                             "outcome": outcome}]
                tails = [tail]
                for component in touched:
                    entry, extra_tail = self._gate_touched_component(
                        phase_id, component, target, gates, log_file,
                        log_path, replay)
                    projects.append(entry)
                    tails.append(extra_tail)
        duration_s = int(time.monotonic() - t0)
        gate_cmd = " ".join(argv)
        ps["gate_cmd"] = gate_cmd
        ran = gate_cmd
        if projects is not None:
            ps["gate_projects"] = projects
            outcomes = [p["outcome"] for p in projects]
            outcome = ("red" if "red" in outcomes
                       else "green" if "green" in outcomes else "nothing_ran")
            # the first red command's tail, else the Target's
            tail = next((t for p, t in zip(projects, tails, strict=True)
                         if p["outcome"] == "red"), tails[0])
            if len(projects) > 1:
                ran = "; ".join(
                    f"{p['cmd']} {GATE_OUTCOME_LABELS[p['outcome']]}"
                    for p in projects if p["outcome"] != "waived")
        if outcome == "green":
            ps["gate_green_commit"] = self.git("rev-parse", "HEAD",
                                               root=target.work_root)
            ps["gate_green_log"] = str(log_path)
        elif outcome == "nothing_ran":
            ps["gate_nothing_ran_commit"] = self.git("rev-parse", "HEAD",
                                                     root=target.work_root)
        self._record(phase_id, "gate", n, outcome, tail, None, duration_s,
                     extra=({"reused": str(record_path)} if replay else None))
        self.log(f"[P{phase_id}] gate #{n} → "
                 f"{GATE_OUTCOME_LABELS[outcome]} ({duration_s}s, "
                 f"{ran}) {tail[:120]}")
        if outcome == "nothing_ran":
            what = ("the repo" if self._is_root(target) else
                    ", ".join(p["project"] for p in projects
                              if p["outcome"] == "nothing_ran")
                    if projects else target.name)
            self.log(f"[P{phase_id}] {what} defines no tests — "
                     "proceeding as with no gate (reviewer told unverified)")
        return outcome != "red", log_path

    def _reusable_writer_gate(self, path: Path, target: ResolvedTarget,
                              touched: list[str] | None,
                              gates: list) -> tuple[dict | None, str]:
        """(the record, the tree it ran on) when the writer's recorded gate
        run at `path` can stand for this gate, else (None, why not) — the
        checks cheapest first, the tree's hash last. It stands only where it
        ran in the phase's tree, ran exactly the commands this gate would
        run now — the Target's, the whole repo after an empty root, each
        touched component no gate ruling covers, in that order — none of
        them red, and on a tree that has not changed since it began: a
        change during the run, or after it, is a tree the run did not see."""
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            return None, f"unreadable: {e}"
        problem = writer_gate_record_problem(record)
        if problem:
            return None, f"unreadable: {problem}"
        for key, here in (("work_root", target.work_root),
                          ("gate_cwd", target.gate_cwd)):
            if record[key] != str(here):
                return None, f"it ran in {record[key]}, the gate runs in {here}"
        commands = record["commands"]
        expected = [list(target.gate_argv)]
        if self._is_root(target) and commands[0]["rc"] == KC_NOTHING_RAN:
            expected.append(list(REPO_GATE_ARGV))
        expected += [component_gate_argv(c) for c in touched or ()
                     if self._covering(gates, target.git_root, c) is None]
        ran = [c["argv"] for c in commands]
        if ran != expected:
            return None, (f"it ran {_ticked([' '.join(a) for a in ran])}, "
                          "the gate is "
                          f"{_ticked([' '.join(a) for a in expected])}")
        red = next((c for c in commands
                    if c["rc"] not in (0, KC_NOTHING_RAN)), None)
        if red is not None:
            return None, f"`{' '.join(red['argv'])}` went red"
        try:
            now = content_tree(target.work_root)
        except ValueError as e:
            return None, f"the tree could not be hashed: {e}"
        start, end = record["start_tree"], record["end_tree"]
        if not start == end == now:
            return None, (f"the tree changed after it began (began "
                          f"{start[:12]}, ended {end[:12]}, now {now[:12]})")
        return record, now

    @staticmethod
    def _writer_gate_replay(phase_id: str, path: Path,
                            record: dict) -> Callable:
        """`_gate_cmd_outcome`'s replay over a record `_reusable_writer_gate`
        passed: each call takes the next recorded command, writes its output
        into the log and answers its exit code. The check made the record's
        commands the gate's own, so a call out of step is a driver bug."""
        commands = list(record["commands"])

        def replay(argv: list[str], log_file) -> int:
            if not commands or commands[0]["argv"] != list(argv):
                raise Bailout(
                    "protocol_failure", phase=phase_id,
                    details=f"replaying the writer's gate run ({path}) went "
                            f"out of step at `{' '.join(argv)}` — a driver "
                            "bug: the record was checked against the gate's "
                            "commands before the replay began")
            command = commands.pop(0)
            log_file.write(command["output"])
            return command["rc"]

        return replay

    @staticmethod
    def _gates_touched(target: ResolvedTarget) -> bool:
        """Whether this Target's gate also runs the components its diff
        touches (AIWF-91): a component that is not `root` — in the invoking
        repo or a sibling's, worked in place or in a shared repo's worktree.
        A whole repo (`root`, a repo path, a GitHub clone) already gates the
        repo, all of it."""
        return target.kind == "project" and target.name != ROOT_COMPONENT

    def _touched_components(self, phase_id: str, target: ResolvedTarget,
                            merge_base: str) -> list[str]:
        """The components other than the Target that the phase's diff
        touches, in manifest order (`touched_components`, which the writer's
        `gate` wrapper shares). The diff is `<merge_base>..HEAD` in the
        phase's tree — the range its reviewer reads — and the components are
        kc's list there, so one the phase registered is seen. Where kc lists
        no root, no gate holds a file outside every component, and the log
        says so. `--no-renames` names both ends of a rename, so a file moved
        out of a component touches it."""
        components = load_project_dirs(target.gate_cwd)
        changed = self.git("diff", "--name-only", "--no-renames",
                           f"{merge_base}..HEAD", root=target.work_root)
        touched, uncovered = touched_components(
            components, target.work_root, changed, target.name)
        if uncovered:
            self.log(f"[P{phase_id}] the phase's diff touches files outside "
                     "every component and kc lists no root — no gate "
                     "covers them")
        return touched

    def _gate_touched_component(self, phase_id: str, component: str,
                                target: ResolvedTarget, gates: list,
                                log_file, log_path: Path,
                                replay: Callable | None = None
                                ) -> tuple[dict, str]:
        """One component the phase's diff touches, gated as the Target is —
        `kc project test --project <c>` from the Target's tree, into the
        same log under a header — or, where a gate ruling covers it, waived
        unrun as `_phase_gate` waives a Target: its `gate_projects` entry,
        and the log's last line for the history row's summary. `replay` is
        `_gate_cmd_outcome`'s."""
        argv = component_gate_argv(component)
        cmd = " ".join(argv)
        ruling = self._covering(gates, target.git_root, component)
        if ruling is not None:
            self.log(f"[P{phase_id}] test gate for {component} (the phase's "
                     "diff touches it) waived by plan.md's `## Driver "
                     f"rulings` (substitute: {ruling.substitute_text}) — not "
                     "run")
            self._report_ruling(ruling, "phase gate")
            log_file.write(f"\n=== the phase's diff touches {component}: "
                           f"`{cmd}` waived by plan.md's `## Driver rulings` "
                           f"(substitute: {ruling.substitute_text}) — not run "
                           "===\n")
            log_file.flush()
            return {"project": component, "cmd": cmd, "outcome": "waived"}, ""
        log_file.write(f"\n=== the phase's diff touches {component}: "
                       f"`{cmd}` ===\n")
        log_file.flush()
        outcome, tail = self._gate_cmd_outcome(phase_id, argv, target,
                                               log_file, log_path, replay)
        return {"project": component, "cmd": cmd, "outcome": outcome}, tail

    def _gate_cmd_outcome(self, phase_id: str, argv: list[str],
                          target: ResolvedTarget, log_file,
                          log_path: Path,
                          replay: Callable | None = None) -> tuple[str, str]:
        """One phase-gate command run into `log_file`: its gate outcome, and
        the log's last line as kc left it — the history row's summary. A
        timeout bails; so does rc 2, kc's usage error — an unknown
        --project, and the name came from kc's own project list, so that is
        a driver bug, not a red suite. A red whose output is cexec's
        missing-tool line bails `missing_tools` instead (an operator
        question): no fix round can add a tool container to the pod. So
        does a red in a repo whose environment config declares a service
        the pod does not run — `missing_services`, the gate and its log
        named. A refused connection on localhost:5432 has no fixed line to
        match, so it is the repo's declaration against `running_services`,
        asked on a red alone; kc not answering leaves the red as it was.

        kc prints only each statement's last lines and keeps the whole run
        in the file its closing `full output:` line names, under
        /tmp/kc/project — which holds 20 runs and does not survive a
        restart — so that file is appended to the log once the command is
        classified, on a bailout too. After, because the scans read kc's
        own lines alone: a failing test's output quoting cexec's line is
        not a missing tool.

        `replay(argv, log_file) → rc`, when given, stands in for running
        the command: the writer's recorded run of it, its output written
        into the log as the run would have (`_run_gate`), and everything
        after classifies it as it would a run."""
        log_file.flush()
        start = _file_size(log_path)
        try:
            returncode = (replay(argv, log_file) if replay is not None else
                          self._gate_exec(argv, target.gate_cwd, log_file))
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout", phase=phase_id,
                details=f"gate `{' '.join(argv)}` exceeded {GATE_TIMEOUT}s "
                        f"(output in {log_path})",
            ) from None
        log_file.flush()
        tail = _last_line(log_path)
        try:
            if returncode == 2:
                raise Bailout(
                    "protocol_failure", phase=phase_id,
                    details=f"`{' '.join(argv)}` rejected its arguments "
                            f"(output in {log_path})",
                )
            outcome = kc_outcome(returncode)
            if outcome == "red":
                tool = unavailable_tool(log_path, start)
                if tool is not None:
                    raise Bailout(
                        "missing_tools", phase=phase_id, question=True,
                        details=self._missing_tool_details(
                            tool, target.git_root, argv, log_path))
                services = self._unrun_services(target.git_root)
                if services:
                    raise Bailout(
                        "missing_services", phase=phase_id, question=True,
                        details=self._missing_service_details(
                            services, target.git_root, argv, log_path))
        finally:
            _inline_kc_full_output(log_file, log_path, start)
        return outcome, tail

    def _unrun_services(self, root: Path) -> list[MissingService]:
        """The services the repo at `root` declares and the pod does not
        run, for a gate gone red there. kc is asked only when the repo's
        config declares a service; when it cannot answer, a warning and
        none — the red stands as an ordinary red."""
        if not config_services(_read_text(Path(root) / ENV_CONFIG_REL)):
            return []
        try:
            running = running_services()
        except ValueError as e:
            self.log(f"warning: service check of a red gate skipped — {e}")
            return []
        return missing_services([root], self.repo_root, running)

    def _missing_service_details(self, missing: list[MissingService],
                                 root: Path, argv: list[str],
                                 log_path: Path) -> str:
        """The missing-services message for a gate gone red mid-run in a
        repo that declares services the pod does not run: the gate, its log,
        and why that red is not a fix round's."""
        return (f"`{' '.join(argv)}` in {Path(root).name} went red (output "
                f"in {log_path}), and the repo declares services this pod "
                "does not run — no fix round can start them.\n"
                + missing_services_details(missing, self.repo_root))

    def _missing_tool_details(self, tool: str, root: Path,
                              argv: list[str], log_path: Path) -> str:
        """The missing-tools message for one tool a gate log met mid-run —
        called by the repo's manifest where the scan finds it there, else
        by the command (a script the statement runs may make the call)."""
        manifest = Path(root) / MANIFEST_REL
        caller = (f"{Path(root).name}/{MANIFEST_REL}"
                  if tool in manifest_tools(_read_text(manifest)) else
                  f"`{' '.join(argv)}` in {Path(root).name} "
                  f"(output in {log_path})")
        declared = tool in declared_tools(
            _read_text(self.repo_root / ENV_CONFIG_REL))
        return missing_tools_details([MissingTool(tool, [caller], declared)],
                                     self.repo_root)

    @staticmethod
    def _is_root(target: ResolvedTarget) -> bool:
        """`Target: root` — the component the plan's authors mean as the
        repo as a whole, gated in two steps (`_run_gate`)."""
        return target.kind == "project" and target.name == ROOT_COMPONENT

    def _gate_exec(self, argv: list[str], cwd: Path, log_file) -> int:
        """One gate command's exit code, its output into `log_file` — the
        subprocess seam the phase gate, the sweep and the doc gate share,
        isolated for tests."""
        return subprocess.run(
            argv, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT,
            timeout=GATE_TIMEOUT).returncode

    def _gate_line(self, ps: dict, head: str, target: ResolvedTarget,
                   review_repos: list[str] | None = None) -> str:
        """The gate paragraph in a reviewer dispatch. The green claim is made
        ONLY when the recorded green commit is the commit under review; the
        waiver whenever plan.md's `## Driver rulings` waives the gate; the
        nothing-ran reason only when the gate ran nothing on it. Every other
        case — no gate, a green or an empty run on an earlier commit — is
        plainly unverified. A gate that ran names the repo it ran in; with a
        review set outside the Target (`review_repos`, its distinct clones)
        the paragraph closes on the gate being that repo's suite alone.

        A component Target's gate covers the components its diff touches
        too (AIWF-91): the green names every green command and the projects
        they cover, and closes on those the gate does not cover — ran
        nothing, or waived — by name; the nothing-ran reason names every
        command that ran nothing. No `gate_projects` on record (a whole-repo
        Target, a phase begun on an older plugin) is the Target's command
        alone, as before."""
        gate_cmd = ps.get("gate_cmd") or " ".join(target.gate_argv or [])
        projects = self._gate_projects(ps)
        green_at = ps.get("gate_green_commit")
        gate_log = ps.get("gate_green_log")
        if green_at and gate_log and green_at == head:
            green = [p for p in projects if p["outcome"] == "green"]
            covers = (GATE_COVERS_SENTENCE.format(
                covered=", ".join(p["project"] for p in green))
                if green else "")
            line = GATE_GREEN_LINE.format(
                green_at=green_at[:12],
                gate_cmds=_ticked([p["cmd"] for p in green] or [gate_cmd]),
                covers=covers, gate_repo=target.gate_cwd, gate_log=gate_log)
            uncovered = [f"{p['project']} ({GATE_UNCOVERED_WHY[p['outcome']]})"
                         for p in projects
                         if p["outcome"] in GATE_UNCOVERED_WHY]
            if green and uncovered:
                line += "\n" + GATE_UNCOVERED_LINE.format(
                    uncovered=", ".join(uncovered))
        elif (ruling := self._gate_ruling(target)) is not None:
            line = GATE_WAIVED_LINE.format(
                target=target.name, why=ruling.why,
                substitute=(f"`{ruling.substitute}`" if ruling.substitute
                            else "no substitute"))
        elif target.gate_argv and ps.get("gate_nothing_ran_commit") == head:
            empty = [p["cmd"] for p in projects
                     if p["outcome"] == "nothing_ran"]
            line = GATE_NOTHING_RAN_LINE.format(
                gate_cmd=_ticked(empty or [gate_cmd]),
                gate_repo=target.gate_cwd, ran_at=head[:12])
        else:
            line = GATE_UNVERIFIED_LINE
        if review_repos:
            line += "\n" + GATE_REVIEW_SET_LINE.format(
                gate_repo=target.gate_cwd, clones=", ".join(review_repos))
        return line

    @staticmethod
    def _gate_projects(ps: dict) -> list[dict]:
        """The projects the phase's last gate run took in (`gate_projects`),
        read leniently: none recorded — a whole-repo Target, a phase begun
        on a plugin before AIWF-91 — or a record off-shape is none, and
        every reader falls back to the Target's `gate_cmd` alone."""
        projects = ps.get("gate_projects")
        if not isinstance(projects, list) or not all(
                isinstance(p, dict) and isinstance(p.get("project"), str)
                and isinstance(p.get("cmd"), str)
                and p.get("outcome") in ("green", "red", "nothing_ran",
                                         "waived")
                for p in projects):
            return []
        return projects

    def _red_cmds(self, ps: dict, target: ResolvedTarget) -> str:
        """The gate commands that went red, each in backticks, for the fix
        round's prompt — the Target's command when no project is on record
        (`_gate_projects`)."""
        red = [p["cmd"] for p in self._gate_projects(ps)
               if p["outcome"] == "red"]
        return _ticked(red or [ps.get("gate_cmd")
                               or " ".join(target.gate_argv or [])])

    def _review_set_now(self, phase: Phase) -> tuple[
            list[tuple[str, str]], list[tuple[str, tuple[str, ...]]]] | None:
        """The pairs `phase`'s `Review:` file lists now and its lines naming
        more than one commit — None when the phase declares none or the
        file cannot be read (missing, mostly: the phase writes it)."""
        if phase.review is None:
            return None
        try:
            text = (self.slice_dir / phase.review).read_text()
        except (OSError, ValueError):
            return None
        return review_set_pairs(text), review_set_ambiguous(text)

    @staticmethod
    def _review_set_start(ps: dict) -> set[tuple[str, str]]:
        """The pairs the phase's `Review:` file held when the phase began.
        Read leniently: no snapshot (a phase begun on a plugin that took
        none) or an entry off-shape is an empty baseline — every pair then
        counts as the phase's, which over-reports rather than hides work."""
        start = ps.get("review_set_start")
        if not isinstance(start, list):
            return set()
        return {(p[0], p[1]) for p in start
                if isinstance(p, list) and len(p) == 2
                and all(isinstance(x, str) for x in p)}

    @staticmethod
    def _review_set_ambiguous_start(
            ps: dict) -> set[tuple[str, tuple[str, ...]]]:
        """The lines naming more than one commit the phase's `Review:` file
        held when the phase began, read as leniently as `_review_set_start`:
        no snapshot or an off-shape entry is skipped, and every such line
        then counts as the phase's."""
        start = ps.get("review_set_ambiguous_start")
        if not isinstance(start, list):
            return set()
        return {(e[0], tuple(e[1])) for e in start
                if isinstance(e, list) and len(e) == 2
                and isinstance(e[0], str) and isinstance(e[1], list)
                and all(isinstance(sha, str) for sha in e[1])}

    def _range_empty(self, merge_base: str, root: Path) -> bool:
        """Whether the phase's Target range changes nothing — trees compared,
        not commits, so a range whose commits net to nothing is empty too.
        A tree git cannot name reads as not empty: the flag is raised only
        on evidence."""
        base = self.git("rev-parse", f"{merge_base}^{{tree}}", root=root,
                        check=False)
        head = self.git("rev-parse", "HEAD^{tree}", root=root, check=False)
        return bool(base) and base == head

    def _review_set_paragraph(self, phase: Phase, ps: dict,
                              target: ResolvedTarget,
                              merge_base: str) -> tuple[str, list[str]]:
        """The review-set paragraph of a reviewer dispatch — ending in its
        blank line, or empty — and the review set's distinct clones, for the
        gate line. A phase declaring `Review:` is pointed at the pairs its
        file gained since the phase began (`review_set_start`); a declared
        set with none, and an undeclared phase whose Target range is empty,
        are stated for the reviewer to report. The lines it gained naming
        more than one commit for a clone are handed on as no pair: the
        reviewer is shown them to find the phase's commit, and their clones
        join the gate line's. An undeclared phase with work on its Target
        gets nothing: its dispatch is the one it always was. The range is
        the phase's working tree's — its worktree's, for a shared repo,
        whose own HEAD is the base."""
        root = target.work_root
        empty = self._range_empty(merge_base, root)
        if phase.review is None:
            if not empty:
                return "", []
            self.log(f"[P{phase.id}] reviewer told: Target range empty, no "
                     "review set declared")
            return REVIEW_EMPTY_RANGE_NOTE.format(
                merge_base=merge_base, root=root) + "\n\n", []
        path = self.slice_dir / phase.review
        listed, ambiguous = self._review_set_now(phase) or ([], [])
        start = self._review_set_start(ps)
        pairs = [pair for pair in listed if pair not in start]
        start_unclear = self._review_set_ambiguous_start(ps)
        unclear = [line for line in ambiguous if line not in start_unclear]
        range_note = ", Target range empty" if empty else ""
        if not pairs and not unclear:
            missing = not path.exists()
            self.log(f"[P{phase.id}] reviewer told: review set "
                     f"{phase.review} "
                     f"{'does not exist' if missing else 'has no new pair'}"
                     f"{range_note}")
            return REVIEW_SET_NONE_NOTE.format(
                path=path, merge_base=merge_base, root=root,
                state=("that file does not exist" if missing else
                       "it holds no clone and commit pair this phase added "
                       "or changed"),
                range_state="empty too" if empty else "not empty",
            ) + "\n\n", []
        paragraphs: list[str] = []
        if pairs:
            self.log(f"[P{phase.id}] reviewer told: review set of "
                     f"{len(pairs)} pair(s) from {phase.review}{range_note}")
            paragraphs.append(REVIEW_SET_NOTE.format(
                path=path, bullets="\n".join(
                    f"- `git -C {clone} show {sha}`"
                    for clone, sha in pairs)))
        if unclear:
            self.log(f"[P{phase.id}] reviewer told: {phase.review} has "
                     f"{len(unclear)} line(s) naming more than one commit: "
                     + "; ".join(f"{clone} ({', '.join(shas)})"
                                 for clone, shas in unclear)
                     + ("" if pairs else range_note))
            paragraphs.append(REVIEW_SET_AMBIGUOUS_NOTE.format(
                path=path, bullets="\n".join(
                    f"- `{clone}`: " + ", ".join(f"`{sha}`" for sha in shas)
                    for clone, shas in unclear)))
        if empty:
            paragraphs.append(
                (REVIEW_SET_AMBIGUOUS_EMPTY_RANGE if unclear
                 else REVIEW_SET_EMPTY_RANGE).format(
                    merge_base=merge_base, root=root))
        clones = [c for c, _ in pairs] + [c for c, _ in unclear]
        return "\n\n".join(paragraphs) + "\n\n", list(dict.fromkeys(clones))

    def _review_secrets(self, phase: Phase, outputs: Path, r: int,
                        root: Path, ranges: list[tuple[str, str]]) -> str:
        """The Secret and never-print paragraphs of a reviewer dispatch
        (AIWF-51) — each ending in its blank line — or empty. `ranges` are
        the ones the prompt names, in its order: the branch, or a delta
        round's fix range and then the branch.

        A range that changes Secret data is written out redacted, a section
        per range, to `review_r<N>.diff` beside the round's review, and the
        reviewer reads that instead of running `git diff` — which would
        print the values before it knew what the diff held. Telling costs a
        `--name-only` per range: only a range touching a file the redactor
        examines is diffed and redacted, so a range of code alone costs
        nothing more. `--no-renames` names both ends of a rename, so a
        manifest renamed to a suffix the redactor skips is still seen. The
        phase's never-print paths are held out of every diff the driver
        takes — not of the stats, whose names are fine to show — and the
        reviewer is given the commands that print none of their content. A
        range the redactor cannot redact stops the run here, before the
        reviewer is spawned."""
        never = phase.never_print or []
        excludes = [f":(exclude){p}" for p in never]
        spec = ["--", ".", *excludes] if excludes else []
        redacted: dict[tuple[str, str], str] = {}
        stubbed = 0
        for base, head in ranges:
            names = self.git("diff", "--name-only", "--no-renames",
                             f"{base}..{head}", *spec, root=root)
            # a name git C-quoted (core.quotePath) ends in its quote
            if any(is_examined(name.strip().strip('"'))
                   for name in names.splitlines()):
                redacted[(base, head)], count = self._redact(
                    self.git_raw("diff", f"{base}..{head}", *spec, root=root),
                    base, head, root, phase.id)
                stubbed += count
        if len(ranges) == 1:
            named = f"`{ranges[0][0]}..{ranges[0][1]}`"
        else:
            (fix_base, fix_head), (base, head) = ranges
            named = (f"the fix range `{fix_base}..{fix_head}` and then the "
                     f"whole branch `{base}..{head}`")
        tool = TOOLS_DIR / "redact_secrets.py"
        notes = ""
        if stubbed:
            sections = []
            for base, head in ranges:
                if (base, head) not in redacted:
                    redacted[(base, head)], _ = self._redact(
                        self.git_raw("diff", f"{base}..{head}", *spec,
                                     root=root),
                        base, head, root, phase.id)
                stat = self.git("diff", "--stat=100", f"{base}..{head}",
                                root=root)
                diff = redacted[(base, head)].rstrip("\n")
                sections.append(
                    f"{root} — git diff {base[:12]}..{head[:12]}"
                    f"\n\n{stat}\n\n{diff}\n")
            path = outputs / f"review_r{r}.diff"
            path.write_text("\n".join(sections))
            self.log(f"[P{phase.id}] reviewer handed {path}: {stubbed} "
                     "Secret data line(s) stubbed")
            notes += REVIEW_SECRETS_NOTE.format(
                path=path, ranges=named, root=root, tool=tool,
                held_out=(", the never-print paths below held out"
                          if never else ""))
        if never:
            notes += NEVER_PRINT_NOTE.format(
                paths=", ".join(f"`{p}`" for p in never), root=root,
                excludes=" ".join(shlex.quote(e) for e in excludes),
                tool=tool, ranges=named)
        return notes

    # -- the phase loop ------------------------------------------------------

    def _run_phases(self) -> None:
        """Work the plan front to back until no unfinished phase remains.
        The plan is re-parsed every iteration — phases appended mid-run are
        picked up in document order."""
        self.state["run_phase"] = "phases"
        self._save_state()
        while True:
            phases = self._load_plan()
            pending = next((p for p in phases if not p.done), None)
            if pending is None:
                return
            self._run_phase(pending)

    def _executor_where(self, target: ResolvedTarget) -> str:
        """The clause locating the phase's working tree when it is not the
        invoking repo's: a sibling path or a sibling repo's component, or a
        shared repo's worktree — the session itself spawns in the invoking
        repo, so the prompt must carry the pointer. The worktree's clause
        names the shared checkout too: the plan lives there, on its base, and
        the worktree's own copy of the slice tree is not the plan."""
        work, root = target.work_root, target.git_root
        if work != root:
            base = self._base_branch(root)
            return (f" in the worktree {work} — a linked checkout of {root}; "
                    f"{root}'s own tree stays on {base}, and the plan is "
                    f"edited there, never under {work}/slices")
        if target.kind == "project" and root == self.repo_root:
            return ""
        return f" in the sibling repo {root}"

    def _pointers(self, target: ResolvedTarget, phase_id: str) -> str:
        """What every executor dispatch carries at its tail: the close-out
        report's path and tool, the project's change-discipline doc, plus the
        gate waiver and the skills the phase names where they apply."""
        return (self._gate_waived_note(target) + self._philosophy_line()
                + self._skill_line(phase_id) + self._close_out_line())

    def _close_out_line(self) -> str:
        return CLOSE_OUT_LINE.format(
            dispatch_line=dispatch_line(self.report_path))

    def _skill_line(self, phase_id: str) -> str:
        """The skills the phase's executor, fix rounds and reviewer are
        pointed at (SKILL_LINE): those named in the phase's own section of
        the plan and in the plan's text outside every phase (phase_scope),
        read from the plan as it stands at this dispatch — a round may have
        edited it. Logged per dispatch that carries it."""
        try:
            plan_text = self.plan_path.read_text()
        except OSError:
            return ""
        skills = resolve_skills(phase_scope(plan_text, phase_id))
        if skills:
            self.log(f"[P{phase_id}] {skills_named(skills)}")
        return skill_line(skills, "this phase")

    def _phase_digest(self, phase_id: str) -> str:
        """The writer's orientation for this round (build_phase_digest): the
        plan and verification.json as they stand, slice.md's intent
        paragraph, and what earlier phases changed — one `--stat` per merged
        phase over that phase's own landed range in its own repo, never the
        base branch since the slice began (in parallel lanes that range
        carries the other lanes' merges). The spec repo's `slices/` tree is
        held out, so the driver's own run record and every other slice's
        folder stay out of it. A merged phase with no range on record
        contributes nothing here — those are reported in the doc phase's
        rows, not the digest. An earlier record the digest could not
        summarise gets a log line, so a run whose writers wrote records
        off-shape says so (`records_without_summary`)."""
        try:
            plan_text = self.plan_path.read_text()
        except OSError:
            plan_text = ""
        for pid in records_without_summary(plan_text, phase_id):
            self.log(f"[P{phase_id}] digest: P{pid}'s done-record has no "
                     "'Later phases:' block — carried whole")
        try:
            intent = slice_intent((self.slice_dir / "slice.md").read_text())
        except OSError:
            intent = ""
        try:
            criteria = json.loads(
                self.verification_path.read_text()).get("items", [])
        except (OSError, ValueError, AttributeError):
            criteria = []
        touched: list[tuple[str, str]] = []
        for pid, landed in self._landed()[0]:
            root = Path(landed["root"])
            pathspec = self._bookkeeping_pathspec(root)
            stat = self.git("diff", "--stat=100",
                            f"{landed['base']}..{landed['head']}",
                            *(["--", *pathspec] if pathspec else []),
                            root=root, check=False)
            if stat:
                touched.append((f"P{pid} in {landed['root']}", stat))
        return build_phase_digest(plan_text, phase_id, intent, criteria,
                                  touched)

    def _philosophy_line(self) -> str:
        """The run profile requires the doc, so the empty case is only a loop
        driven past a preflight that never checked for it."""
        if not self.cfg.design_philosophy:
            return ""
        return PHILOSOPHY_LINE.format(philosophy=self.cfg.design_philosophy)

    def _write_gate_spec(self, phase_id: str, round_: int, outputs: Path,
                         target: ResolvedTarget, merge_base: str) -> None:
        """The phase's gate as the `gate` wrapper runs it for code-writer
        round `round_` (`run_writer_gate`): where, which command, the whole
        repo after an empty root, and — for a component Target — what it
        needs to find the components the diff touches: the review's merge
        base, and those a gate ruling covers, which the driver's gate waives
        unrun. Rewritten at every dispatch, so it is the gate as it stands
        then; the driver checks a run against its gate as it stands at gate
        time anyway (`_reusable_writer_gate`)."""
        touched = None
        if self._gates_touched(target):
            gates = [(r, t) for r, t in self._current_rulings()
                     if r.kind == "gate"]
            waived = ([c for c in load_project_dirs(target.gate_cwd)
                       if self._covering(gates, target.git_root, c)
                       is not None] if gates else [])
            touched = {"merge_base": merge_base, "target": target.name,
                       "waived": waived}
        _write_json_atomic(outputs / GATE_SPEC_NAME, {
            "phase": phase_id, "round": round_,
            "work_root": str(target.work_root),
            "gate_cwd": str(target.gate_cwd), "argv": target.gate_argv,
            "fallback": list(REPO_GATE_ARGV) if self._is_root(target) else None,
            "touched": touched})

    def _gate_hint(self, target: ResolvedTarget, outputs: Path) -> str:
        """The gate the executor runs itself, from the phase's working tree —
        a shared repo's worktree, where it has one: kc's verbs are
        cwd-bound. Where the driver has a gate, the executor is pointed at
        the `gate` wrapper over the phase's spec (`_write_gate_spec`): it
        runs exactly what the driver's gate would, and the driver reuses its
        green rather than running the suite a second time."""
        work = target.work_root
        wrapper = f"`python3 {SCRIPT} gate {outputs / GATE_SPEC_NAME}`"
        if self._is_root(target):
            where = "" if work == self.repo_root else f" from {work}"
            return (f" — through {wrapper}, which runs the driver's own gate: "
                    f"`kc project test --project root`{where}, and bare `kc "
                    "project test`, every component once, when that runs "
                    f"nothing (exit 3). {GATE_REUSE_HINT}. {NOTHING_RAN_HINT}")
        if target.kind == "project":
            # The driver gates every component the diff touches beside the
            # Target's own (AIWF-91), and so does the wrapper.
            where = "" if work == self.repo_root else f" from {work}"
            return (f" — through {wrapper}, which runs the driver's own gate: "
                    f"`kc project test --project {target.name}`{where}, and "
                    "the same for every other component the phase's diff "
                    f"touches. {GATE_REUSE_HINT}. {NOTHING_RAN_HINT}")
        if target.gate_argv:
            return (f" — through {wrapper}, which runs the driver's own gate: "
                    f"`kc project test` from {work}. {GATE_REUSE_HINT}")
        return (f" ({work} has no kc manifest — gate per that repo's own "
                "conventions; if this phase adds `.kubecoder/project.yaml`, "
                f"the driver's gate is `kc project test` from {work})")

    @staticmethod
    def _recorded_commits(ps: dict) -> list[str]:
        """Every commit the driver itself vouched for on this phase's branch:
        the head the last review read and the gate's last green. A target with
        no deterministic gate records only the former, a phase with no review
        yet only the latter, and a fix round that has re-gated but not yet
        been re-reviewed carries both."""
        out: list[str] = []
        for sha in (ps.get("reviewed_head"), ps.get("gate_green_commit")):
            if sha and sha not in out:
                out.append(sha)
        return out

    def _landed(self) -> tuple[list[tuple[str, dict]], list[str]]:
        """Every merged phase's landed range — (id, {root, base, head}) in
        the order the phases merged (state order is first-run order) — and,
        apart, the ids of merged phases with no range on record: merged under
        a plugin before 0.9.16, or landed in the crash window between the
        ff-merge and the record (the reconcile path)."""
        ranged: list[tuple[str, dict]] = []
        unranged: list[str] = []
        for pid, ps in self.state["phases"].items():
            if ps.get("status") != "merged":
                continue
            landed = ps.get("landed")
            if isinstance(landed, dict) and landed.get("root") \
                    and landed.get("base") and landed.get("head"):
                ranged.append((pid, landed))
            else:
                unranged.append(pid)
        return ranged, unranged

    def _work_is_in(self, ref: str, sha: str, root: Path) -> bool:
        return self.git_ok("merge-base", "--is-ancestor", sha, ref, root=root)

    def _lost_work(self, phase_id: str, sha: str, branch: str,
                   root: Path) -> Bailout:
        return Bailout(
            "lost_work", phase=phase_id,
            details=f"commit {sha[:12]} is on P{phase_id}'s record as work "
                    f"the driver saw on the branch, and {branch} in {root} "
                    "does not carry it. Something rebuilt the branch or "
                    "replaced the checkout under the run; the loop will not "
                    "carry on over the top of a commit it cannot account "
                    "for. "
                    "Check that no second driver is on this slice (each "
                    "holds run.lock), then either restore the branch or "
                    "clear the phase's record in state.json (status, stage, "
                    "gate_green_commit, reviewed_head) to run it again from "
                    "the executor.")

    def _assert_record_still_on(self, phase_id: str, ps: dict, root: Path,
                                branch: str) -> None:
        """Every round hands back onto the branch its predecessors built. A
        session that rebuilt that branch — or a second driver that did —
        leaves the record pointing at a commit the tip no longer carries, and
        the next round would gate and review a tree missing the earlier
        rounds' work — unless the driver itself asked for the rewrite
        (`_take_requested_rebase`)."""
        missing = [sha for sha in self._recorded_commits(ps)
                   if not self._work_is_in(branch, sha, root)]
        if missing and not self._take_requested_rebase(
                phase_id, ps, root, self._base_branch(root), branch):
            raise self._lost_work(phase_id, missing[0], branch, root)

    def _take_requested_rebase(self, phase_id: str, ps: dict, root: Path,
                               base: str, branch: str) -> bool:
        """The record's commits are gone from the branch: was that the
        rebase the driver asked for? True when it was, and the record now
        follows the branch; False when the phase carries no such request.

        `_rebase_onto_moved_base` bails asking the operator to rebase the
        branch onto its moved base, and marks the phase `rebase_requested`.
        Doing as asked rewrites every commit on the record, so without the
        mark the resume would call the branch lost work — and both remedies
        that offers are lossy: restoring the branch undoes the rebase, and
        clearing the record throws away a finished review (one was a signoff
        four rounds in). With the mark, a branch that now carries the base's
        tip is the rebase: `reviewed_head` follows it and the gate's green is
        dropped, the move a clean rebase makes in `_rebase_onto_moved_base`
        (the merge stage re-gates). Which commits the rebase kept is not
        checked — the operator was asked to carry the phase across, and the
        re-run gate is the proof the driver has. A branch still short of the
        tip is the same request, again."""
        req = ps.get("rebase_requested")
        if not req:
            return False
        if not self.git_ok("merge-base", "--is-ancestor", base, branch,
                           root=root):
            raise Bailout(
                "blocked", phase=phase_id,
                details=f"P{phase_id} waits on the rebase the driver asked "
                        f"for: {base} in {root} moved under {branch}, and "
                        f"the branch still does not carry {base}'s tip. "
                        f"Rebase {branch} onto {base} (or merge {base} into "
                        "it), then resume — the review stands and the gate "
                        "re-runs.")
        new_head = self.git("rev-parse", branch, root=root)
        if ps.get("reviewed_head"):
            ps["reviewed_head"] = new_head
        ps["gate_green_commit"] = None
        ps.pop("rebase_requested", None)
        self._save_state()
        old = str(req.get("from") or "?") if isinstance(req, dict) else "?"
        self.log(f"[P{phase_id}] branch rebased by hand as the driver asked "
                 f"({old[:12]} → {new_head[:12]}); the review stands, the "
                 "gate re-runs")
        return True

    def _reconcile_branch(self, phase_id: str, ps: dict, root: Path,
                          base: str, branch: str, existing: str) -> bool:
        """Reality-check the phase's record against the repository before the
        branch below is reset or recreated. Returns True when the phase turns
        out to be finished already and the caller has nothing left to run.

        Two ways a branch and its record can disagree, and one of them has a
        benign explanation:

        - The record vouches for a commit the branch does not carry (or there
          is no branch left). If the base branch carries it the merge landed
          and the run died before the record caught up — a resume finishes
          the bookkeeping. If the driver itself asked for the branch to be
          rebased, the record follows the rebased branch
          (`_take_requested_rebase`). If nothing carries it, the work is
          gone: bail rather than silently rebuild the branch from base and
          spend a round redoing it.
        - The phase is `pending` — the loop knows of no work — but a branch
          of its name exists with commits the base has not got. `git branch
          -D` below would drop them without a word.

        A branch that carries the record and that the base already carries
        whole, at the merge stage, is a merge that landed: the driver's, in
        the window before its cleanup, or the operator's by hand after a
        conflict bail (`_merge_shared`). Its worktree and the branch go, and
        the phase is stamped.
        """
        recorded = self._recorded_commits(ps)
        if ps["status"] == "pending":
            ahead = self.git("rev-list", "--count", f"{base}..{branch}",
                             root=root) if existing else "0"
            if ahead not in ("", "0"):
                raise Bailout(
                    "lost_work", phase=phase_id,
                    details=f"{branch} exists in {root} with {ahead} "
                            f"commit(s) {base} has not got, and P{phase_id} "
                            "is `pending` — the run has no record of that "
                            "work, so deleting the branch for a fresh one "
                            "would drop it unseen. Inspect it, then delete "
                            "the branch yourself or resume the run that "
                            "made it.")
            return False
        if not recorded:
            # Rounds spent before the first gate or review leave no commit on
            # the record — nothing to check them against, and a writer that
            # bailed may well have committed nothing at all.
            return False
        on_branch = bool(existing) and all(
            self._work_is_in(branch, sha, root) for sha in recorded)
        landed = (on_branch and ps.get("stage") == "merging"
                  and self._work_is_in(base, branch, root))
        if on_branch and not landed:
            return False
        if not landed:
            if existing and self._take_requested_rebase(phase_id, ps, root,
                                                        base, branch):
                return False
            for sha in recorded:
                if not self._work_is_in(base, sha, root):
                    raise self._lost_work(phase_id, sha, branch, root)
        # The merge landed and the record did not: finish the bookkeeping.
        # No landed range is recorded: after the merge the base branch's
        # pre-merge sha is not the driver's to reconstruct, so this phase
        # reads as merged with no range on record (_landed's second list).
        if ps["status"] != "merged":
            ps.update(status="merged", stage=None)
            self._save_state()
        self._clear_merged_branch(phase_id, ps, root, base, branch)
        self.log(f"[P{phase_id}] already merged into {base} "
                 f"({recorded[0][:12]}) — stamping")
        self._stamp_done(phase_id)
        return True

    def _clear_merged_branch(self, phase_id: str, ps: dict, root: Path,
                             base: str, branch: str) -> None:
        """What a merged phase leaves behind once the reconcile finds it
        merged: the worktree its record names, and the branch — deleted
        only when the base carries it whole, so a same-named branch with
        work of its own is never dropped unseen."""
        path = ps.pop("worktree", None)
        if path:
            self._remove_worktree(root, Path(path))
            self._save_state()
        if not self.git("branch", "--list", branch, root=root):
            return
        if not self._work_is_in(base, branch, root):
            self.log(f"[P{phase_id}] {branch} left in {root.name}: it "
                     f"carries commits {base} has not got")
            return
        if self._current_branch(root) == branch:
            self.git("checkout", base, root=root)
        self.git("branch", "-D", branch, root=root)

    def _run_phase(self, phase: Phase) -> None:
        phase_id = phase.id
        ps = self._phase_state(phase_id)
        target = self._resolve_target(phase.target, creates=phase.creates)
        self._report_scratch_clone(target)
        self._refuse_ungated_github(phase_id, target,
                                    claimed=phase.creates is not None)
        root = target.git_root
        outputs = self.slice_dir / "phases" / f"P{phase_id}"
        outputs.mkdir(parents=True, exist_ok=True)
        branch = f"phase/{self.slice_num}-P{phase_id}"
        base = self._base_branch(root)

        self.log(f"[P{phase_id}] start (target={target.name}, "
                 f"branch={branch}, root={root})")
        self._fetch_origin(root)

        # Branch setup (fresh or resume) — over a branch reconciled against
        # what the record says is committed on it.
        existing = self.git("branch", "--list", branch, root=root)
        if self._reconcile_branch(phase_id, ps, root, base, branch, existing):
            return
        fresh = ps["status"] == "pending" or not existing
        if fresh:
            self._sync_base(phase_id, root, base)
        origin_line = self._origin_ahead_line(phase, root, base)
        if self._works_in_worktree(root):
            # A shared checkout never leaves its base: the phase works in a
            # linked worktree of its own, on its branch, and every working-
            # tree read and write below goes there.
            target = target.in_worktree(self._ensure_worktree(
                phase_id, ps, root, base, branch, existing))
        elif fresh:
            if existing:
                self.git("checkout", base, root=root)
                self.git("branch", "-D", branch, root=root)
            self.git("checkout", "-b", branch, base, root=root)
        else:
            self.git("checkout", branch, root=root)
            if self._reattaching(phase_id):
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']} "
                         "(worktree preserved for reattach)")
            else:
                self._set_aside(phase_id, ps, root)
                self._reset_tracked(root)
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']}")
        if fresh:
            ps.update(status="in_progress", stage="executor", branch=branch,
                      target=phase.target)
            # What the phase's review set held before the phase did anything:
            # the reviewer is pointed at the pairs, and the lines naming more
            # than one commit, the phase adds or changes.
            if phase.review is None:
                ps["review_set_start"] = None
                ps["review_set_ambiguous_start"] = None
            else:
                pairs, ambiguous = self._review_set_now(phase) or ([], [])
                ps["review_set_start"] = [list(pair) for pair in pairs]
                ps["review_set_ambiguous_start"] = [
                    [clone, list(shas)] for clone, shas in ambiguous]
        self._save_state()
        work = target.work_root
        where = self._executor_where(target)
        gate_hint = self._gate_hint(target, outputs)

        merge_base = self.git("merge-base", base, branch, root=root)

        def executor_verdict_path(r: int) -> Path:
            return outputs / f"executor_result_r{r}.json"

        def spawn_executor(build_prompt) -> dict:
            """build_prompt(verdict_path) → prompt, to which the phase digest
            is appended. Every round is a fresh session — fix rounds read
            their inputs from the digest, the plan and the durable outputs
            dir, never from the prior round's context. A round a crash
            interrupted keeps its number: the in-flight record banked it.
            What a resume set aside rides the first round after it, and is
            dropped from the state only once that round's session returns:
            a run that dies mid-dispatch hands it to the next one. The gate
            spec the round's `gate` wrapper reads is written first, carrying
            the round's number — the driver reuses a run of that round
            alone."""
            pending = self._reattach_round("code-writer", phase_id)
            if pending is None:
                ps["executor_rounds"] += 1
            r = ps["executor_rounds"] if pending is None else pending
            self._save_state()
            if target.gate_argv is not None:
                self._write_gate_spec(phase_id, r, outputs, target,
                                      merge_base)
            prompt = (build_prompt(executor_verdict_path(r)) + "\n"
                      + self._phase_digest(phase_id))
            if ps.get("set_aside"):
                prompt += set_aside_line(ps["set_aside"])
            prompt += origin_line
            verdict, session = self._spawn(
                "code-writer", prompt,
                self.repo_root, executor_verdict_path(r),
                phase_id, r, agent="code-writer",
            )
            if ps.pop("set_aside", None) is not None:
                self._save_state()
            verdict = self._ensure_committed(
                phase_id, "code-writer", session, work,
                verdict, executor_verdict_path(r))
            self._assert_record_still_on(phase_id, ps, root, branch)
            self._save_state()
            self._handle_executor_terminals(verdict, phase_id)
            return verdict

        # ---- executor stage ----
        if ps["stage"] == "executor":
            spawn_executor(lambda vp: EXECUTOR_PROMPT.format(
                phase_id=phase_id, plan_path=self.plan_path,
                slice_name=self.slice_name, target=phase.target,
                branch=branch, where=where, gate_hint=gate_hint,
                verdict_path=vp,
                pointers=self._pointers(target, phase_id)))
            self._after_session_plan_check()
            ps["stage"] = "gate"
            self._save_state()

        # ---- gate + executor-fix loop ----
        if ps["stage"] == "gate":
            self._gate_until_green(phase, ps, outputs, target, branch,
                                   merge_base, where, spawn_executor)
            ps["stage"] = "review"
            self._save_state()

        # ---- operator-answered writer question → writer-direct resume ----
        # A writer that bailed with a question mid-review resumes into a
        # writer round, not a review of the unchanged branch: job 3 wrote
        # the ruling into the plan's requirements/rulings, and the driver
        # tags the round's review report so the fix round carries both.
        if ps["stage"] == "review" and ps.get("operator_question"):
            question = ps.pop("operator_question")
            r = ps["review_rounds"]
            review_path = outputs / f"code_review_r{r}.md"
            self._save_state()
            if r and review_path.exists():
                review_path.write_text(
                    review_path.read_text()
                    + OPERATOR_RULING_TAG.format(round=r, question=question))
                self.log(f"[P{phase_id}] operator ruling tagged onto "
                         f"{review_path.name}; dispatching the writer")
                fix_verdict = spawn_executor(
                    lambda vp, _r=r: EXECUTOR_REVIEW_FIX_PROMPT.format(
                        phase_id=phase_id, slice_name=self.slice_name,
                        plan_path=self.plan_path, branch=branch,
                        merge_base=merge_base, where=where,
                        review_path=outputs / f"code_review_r{_r}.md",
                        gate_hint=gate_hint, verdict_path=vp,
                        pointers=self._pointers(target, phase_id)))
                self._after_session_plan_check()
                self._handle_refutations(outputs, phase_id, r, fix_verdict)
                self._gate_until_green(phase, ps, outputs, target, branch,
                                       merge_base, where, spawn_executor)

        # ---- review loop ----
        if ps["stage"] == "review":
            self._review_loop(phase, ps, outputs, target, branch, merge_base,
                              where, gate_hint, spawn_executor)
            ps["stage"] = "merging"
            self._save_state()

        # ---- merge + stamp ----
        if ps["stage"] == "merging":
            if work != root:
                head = self._merge_shared(phase_id, ps, outputs, target, base,
                                          branch, merge_base)
            else:
                if self._worktree_dirty(root):
                    raise Bailout(
                        "protocol_failure", phase=phase_id,
                        details="worktree dirty at merge — an agent left "
                                "changes outside its commit boundary",
                    )
                behind = self.git("rev-list", "--count", f"{branch}..{base}",
                                  root=root)
                if behind not in ("", "0"):
                    merge_base = self._rebase_onto_moved_base(
                        phase_id, ps, root, base, branch, behind)
                head = self.git("rev-parse", "HEAD", root=root)
                self._regate_for_merge(phase_id, ps, outputs, target, head,
                                       merge_base)
                self.git("checkout", base, root=root)
                self.git("merge", "--ff-only", branch, root=root)
                self.git("branch", "-D", branch, root=root)
            ps.pop("rebase_requested", None)
            ps.update(status="merged", stage=None,
                      landed={"root": str(root), "base": merge_base,
                              "head": head})
            self._save_state()
            self.log(f"[P{phase_id}] merged into {base}")
            self.announce(f"P{phase_id} merged")
            self._stamp_done(phase_id)

    def _reattaching(self, phase_id: str) -> bool:
        """Whether this resume reattaches to a session of this phase that a
        crash interrupted — which needs the tree as it left it, so nothing
        resets it."""
        r = self._reattach
        return bool(r and r.get("session") and r.get("phase") == phase_id)

    def _regate_for_merge(self, phase_id: str, ps: dict, outputs: Path,
                          target: ResolvedTarget, head: str,
                          merge_base: str) -> None:
        """The gate again, before the merge, when its recorded green no
        longer speaks for the head about to merge; red bails. `merge_base`
        is the review's, as a rebase onto a moved base re-took it."""
        if target.gate_argv is None or self._green_covers(ps, head):
            return
        green, gate_log = self._phase_gate(phase_id, ps, outputs, target,
                                           merge_base)
        if not green:
            raise Bailout(
                "gate_red", phase=phase_id,
                details=f"cannot merge a red test gate ({gate_log})",
            )

    @staticmethod
    def _green_covers(ps: dict, head: str) -> bool:
        """Whether the gate's recorded green still speaks for `head` at the
        merge — only when it is that very commit. A rebase onto a moved base
        drops the green, and the slice tree taken back out of a shared
        repo's branch moves the head, so either re-gates."""
        green = ps.get("gate_green_commit")
        return bool(green) and green == head

    # -- a shared repo's phase: the worktree and the merge ----------------------

    def _worktree_path(self, root: Path, phase_id: str) -> Path:
        return WORKTREE_ROOT / Path(root).name / f"{self.slice_num}-P{phase_id}"

    def _ensure_worktree(self, phase_id: str, ps: dict, root: Path, base: str,
                         branch: str, existing: str) -> Path:
        """The linked worktree a shared repo's phase works in, on its branch
        — `WORKTREE_ROOT/<repo>/<NNN>-P<id>`, recorded in the phase's
        `worktree`.

        A resume reuses the one standing there on the branch — reset to its
        last commit, as a code repo's tree is, unless this resume reattaches
        to the session that left it. Anything else at the path goes, and so
        does every other registration holding the branch (`_free_branch`),
        before the worktree is added: from the base on a fresh phase (a
        branch of its name, which the reconcile found holding nothing the
        base lacks, deleted first), from the branch on a resume — whose
        committed work is all in the shared git dir, while what a lost tree
        held uncommitted is lost, as it is in a code repo.

        The worktree is added locked, and the lock is load-bearing. Its
        registration lives in the shared git dir, where every other
        environment sees it pointing at a path that does not exist there,
        and `git worktree prune` — which any environment's `git gc` runs —
        deletes such a registration unless it is locked. The reason names
        the environment, host and pid that made it."""
        path = self._worktree_path(root, phase_id)
        fresh = ps["status"] == "pending" or not existing
        if not fresh and self._worktree_on(path, branch):
            if self._reattaching(phase_id):
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']} in "
                         f"{path} (worktree preserved for reattach)")
            else:
                self._set_aside(phase_id, ps, path)
                self._reset_tracked(path)
                self.log(f"[P{phase_id}] resuming at stage {ps['stage']} in "
                         f"{path}")
            ps["worktree"] = str(path)
            return path
        if path.exists() or path.is_symlink():
            self._remove_worktree(root, path)
        self._free_branch(root, base, branch)
        reason = (f"slice {self.slice_num} P{phase_id}: "
                  f"{os.environ.get('KUBECODER_ENVIRONMENT_ID') or '?'} "
                  f"{socket.gethostname()} pid {os.getpid()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if fresh:
            if existing:
                self.git("branch", "-D", branch, root=root)
            self.git("worktree", "add", "--lock", "--reason", reason,
                     str(path), "-b", branch, base, root=root)
            self.log(f"[P{phase_id}] worktree {path} added on {branch}, cut "
                     f"from {base} in {root.name}")
        else:
            self.git("worktree", "add", "--lock", "--reason", reason,
                     str(path), branch, root=root)
            self.log(f"[P{phase_id}] resuming at stage {ps['stage']} in "
                     f"{path} — re-added from {branch}; the tree it replaces "
                     "was gone, and whatever it held uncommitted with it")
        ps["worktree"] = str(path)
        return path

    def _worktree_on(self, path: Path, branch: str) -> bool:
        """Whether a working worktree stands at `path` on `branch`. A `.git`
        that points at a pruned registration answers nothing, and is not
        one."""
        if not (path / ".git").exists():
            return False
        return self.git("rev-parse", "--abbrev-ref", "HEAD", root=path,
                        check=False) == branch

    def _worktrees(self, root: Path) -> list[dict[str, str]]:
        """`git worktree list --porcelain` in `root`, one dict per worktree
        (`worktree`, `HEAD`, `branch`, `locked`, …) — the main one first."""
        entries: list[dict[str, str]] = []
        entry: dict[str, str] = {}
        for line in self.git("worktree", "list", "--porcelain",
                             root=root).splitlines():
            if not line.strip():
                if entry:
                    entries.append(entry)
                entry = {}
                continue
            key, _, value = line.partition(" ")
            entry[key] = value
        if entry:
            entries.append(entry)
        return entries

    def _free_branch(self, root: Path, base: str, branch: str) -> None:
        """Clear every registration holding `branch` so a worktree can be
        added on it. One whose path does not exist here — another
        environment's, or one a Reset wiped — is unlocked and pruned; one
        that stands here is this run's own leftover, and is removed. The
        shared checkout itself on the branch is a hand checkout, or a run
        of a plugin before 0.9.93 that branched it in place: never touched,
        and a stop."""
        ref = f"refs/heads/{branch}"
        main = Path(root).resolve()
        prune = False
        for index, entry in enumerate(self._worktrees(root)):
            if entry.get("branch") != ref:
                continue
            where = Path(entry.get("worktree", ""))
            if index == 0 or where.resolve() == main:
                raise Bailout(
                    "blocked",
                    details=f"{root} has {branch} checked out in place — a "
                            "hand checkout, or a run of a plugin before "
                            f"0.9.93; check out {base} there and resume (the "
                            "branch's commits are kept, and the phase goes "
                            "on in a worktree of its own)")
            if where.exists():
                self._remove_worktree(root, where)
            else:
                self.git("worktree", "unlock", str(where), root=root,
                         check=False)
                prune = True
        if prune:
            self.git("worktree", "prune", root=root)

    def _remove_worktree(self, root: Path, path: Path) -> None:
        """A phase's worktree gone, its registration with it. It is locked,
        so it is unlocked first; `git worktree remove` then refuses a tree
        with changes, `--force` takes it anyway, and a tree git no longer
        knows is deleted from disk — only ever under WORKTREE_ROOT."""
        path = Path(path)
        self.git("worktree", "unlock", str(path), root=root, check=False)
        if self.git_ok("worktree", "remove", str(path), root=root) or \
                self.git_ok("worktree", "remove", "--force", str(path),
                            root=root):
            return
        try:
            path.resolve().relative_to(WORKTREE_ROOT.resolve())
        except ValueError:
            self.log(f"{path} not removed: not a worktree git knows, and not "
                     f"under {WORKTREE_ROOT}")
            return
        shutil.rmtree(path, ignore_errors=True)
        self.git("worktree", "prune", root=root, check=False)

    def _git_attempt(self, *args: str, root: Path) -> tuple[int, str]:
        """A git command whose failure the caller reads rather than bails on
        — its exit code, and stdout and stderr together: `git merge` says
        CONFLICT on one and what stood in its way on the other."""
        result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                text=True)
        return result.returncode, (result.stdout + result.stderr).strip()

    def _merge_shared(self, phase_id: str, ps: dict, outputs: Path,
                      target: ResolvedTarget, base: str, branch: str,
                      merge_base: str) -> str:
        """Merge a shared repo's phase branch into its base, in the shared
        checkout, and clear its worktree; return the head that merged.

        The worktree clean, as at any merge. Then, where the shared repo
        holds the slice folder, the slice tree taken back out of the branch
        (`_revert_slice_tree`), and the gate run again where its green no
        longer covers the head. Then `git merge` on the base — a fast-forward
        when the base stood still, a merge commit when it moved, as it does
        with every session's commit there; never a rebase, which would
        rewrite what the review read. Bounded at MERGE_ATTEMPTS:

        - another writer's uncommitted edit in a file the merge would touch
          (staged, modified or untracked): swept — committed on the base by
          name — and the merge tried again;
        - another git's index.lock: waited out briefly, and tried again;
        - a conflict: the merge aborted, the shared tree as it was, and a
          `blocked` stop asking for the merge by hand — the resume then
          finds the branch in the base and stamps (`_reconcile_branch`);
        - anything else is git's own error, a protocol failure."""
        root, work = target.git_root, target.work_root
        if self._worktree_dirty(work):
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details="worktree dirty at merge — an agent left changes "
                        f"outside its commit boundary in {work}",
            )
        if self._is_spec_root(root):
            self._revert_slice_tree(phase_id, work, base, branch)
        head = self.git("rev-parse", "HEAD", root=work)
        self._regate_for_merge(phase_id, ps, outputs, target, head,
                               merge_base)
        message = f"slice {self.slice_num}: merge {branch} (P{phase_id})"
        last = ""
        for _ in range(MERGE_ATTEMPTS):
            code, out = self._git_attempt("merge", "-m", message, branch,
                                          root=root)
            if code == 0:
                how = ("fast-forward" if "Fast-forward" in out else
                       f"a merge commit — {base} had moved")
                self.log(f"[P{phase_id}] {branch} merged into {base} in "
                         f"{root.name} ({how})")
                break
            last = out
            in_the_way = overwritten_paths(out)
            if in_the_way:
                self._sweep_into_base(phase_id, root, base, in_the_way)
                continue
            if "index.lock" in out:
                self.log(f"[P{phase_id}] another git holds {root.name}'s "
                         f"index.lock — the merge waits {INDEX_LOCK_WAIT}s")
                self._sleep(INDEX_LOCK_WAIT)
                continue
            if "CONFLICT" in out or "Automatic merge failed" in out:
                self.git("merge", "--abort", root=root, check=False)
                conflicts = [ln.strip() for ln in out.splitlines()
                             if ln.startswith("CONFLICT")]
                raise Bailout(
                    "blocked", phase=phase_id,
                    details=f"{branch} does not merge cleanly into {base} in "
                            f"{root}: {base} moved under it with changes "
                            "that conflict with the phase's"
                            + (" (" + "; ".join(conflicts) + ")"
                               if conflicts else "")
                            + ". The merge was aborted, so the tree stands "
                              f"as it did. Merge {branch} into {base} in "
                              f"{root} by hand — resolve, commit — then "
                              "resume: the resume finds the branch in "
                              f"{base}, clears its worktree and stamps the "
                              "phase.")
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details=f"git merge {branch} into {base} failed in "
                        f"{root}:\n{out}")
        else:
            raise Bailout(
                "protocol_failure", phase=phase_id,
                details=f"{branch} did not merge into {base} in {root} in "
                        f"{MERGE_ATTEMPTS} attempts; the last failed:\n"
                        f"{last}")
        self._remove_worktree(root, work)
        self.git("branch", "-D", branch, root=root)
        ps.pop("worktree", None)
        self._save_state()
        return head

    def _revert_slice_tree(self, phase_id: str, work: Path, base: str,
                           branch: str) -> None:
        """Take the slice tree back out of a phase branch of the repo that
        holds it. The worktree carries `slices/**` as it stood at the fork,
        and a writer that greps for `plan.md` may edit that copy; the plan is
        the shared checkout's, and the slice tree is never a phase's
        deliverable. So whatever the branch changed there goes back to its
        state at the branch's merge base, in one commit on the branch, the
        files logged — back to the fork rather than to the base's tip, so
        the branch then changes nothing there and the merge cannot conflict
        with a parallel session's edit in the tree."""
        changed = self.git("diff", "--name-only", f"{base}...{branch}", "--",
                           "slices/", root=work)
        if not changed:
            return
        fork = self.git("merge-base", base, branch, root=work)
        self.git("restore", f"--source={fork}", "--staged", "--worktree",
                 "--", "slices/", root=work)
        self.git("commit", "-m",
                 f"slice {self.slice_num}: slices/** taken back out of "
                 f"{branch} — the slice tree is never a phase's deliverable",
                 root=work)
        self.log(f"[P{phase_id}] {branch} changed the slice tree — taken back "
                 "out, the slice tree is never a phase's deliverable: "
                 + ", ".join(changed.splitlines()))

    def _sweep_into_base(self, phase_id: str, root: Path, base: str,
                         paths: list[str]) -> None:
        """Another writer's uncommitted edits standing in a merge's way,
        committed on the shared repo's base by name, so the merge can go
        on: one commit, logged. Whoever left them finds them committed — a
        sweep, not a loss."""
        self.git("add", "-A", "--", *paths, root=root)
        self.git("commit", "-m",
                 f"slice {self.slice_num}: edits left uncommitted in "
                 f"{root.name}, swept at P{phase_id}'s merge", "--", *paths,
                 root=root)
        self.log(f"[P{phase_id}] uncommitted edits in {root.name} stood in "
                 f"the merge's way — swept into {base}: " + ", ".join(paths))

    def _rebase_onto_moved_base(self, phase_id: str, ps: dict, root: Path,
                                base: str, branch: str,
                                behind: str) -> str:
        """Rebase a reviewed phase branch onto a base that moved under it,
        and return the branch's new merge base.

        A repo of this environment's own merges by `checkout <base>` +
        `merge --ff-only` (a shared repo's phase merges instead —
        `_merge_shared`), so a parallel session landing on the base between
        the review and the merge makes the fast-forward impossible. Rebasing
        by hand afterwards is worse: `reviewed_head` and
        `gate_green_commit` then sit on neither branch nor base, which the
        resume reads as lost work and the operator resolves by editing
        state.json. Done here, the driver repoints its own record — after
        proving the deliverable survived, by diffing the phase's range before
        and after (the bookkeeping tree excluded, as everywhere else). The
        gate's green is dropped rather than moved: these commits were never
        gated in this order, so the merge stage below re-runs it.

        Either bail below hands the rebase to the operator, and records that
        it did (`rebase_requested`): the resume then takes the rewritten
        branch as the one it asked for (`_take_requested_rebase`) instead of
        reading its own request as lost work."""
        pathspec = self._bookkeeping_pathspec(root)

        def deliverable(frm: str, to: str) -> str:
            return self.git("diff", frm, to,
                            *(["--", *pathspec] if pathspec else []),
                            root=root)

        def request_rebase() -> None:
            ps["rebase_requested"] = {"base": base, "from": old_head,
                                      "ts": _now_iso()}
            self._save_state()

        old_head = self.git("rev-parse", branch, root=root)
        before = deliverable(
            self.git("merge-base", base, old_head, root=root), old_head)
        self.git("checkout", branch, root=root)
        try:
            self.git("rebase", base, root=root)
        except Bailout:
            self.git("rebase", "--abort", root=root, check=False)
            request_rebase()
            raise Bailout(
                "blocked", phase=phase_id,
                details=f"{base} in {root} moved by {behind} commit(s) under "
                        f"{branch}, and the branch does not rebase onto it "
                        "cleanly — rebase or merge it yourself, then "
                        "resume; the resume takes the rewritten branch as "
                        "reviewed and re-runs the gate") from None
        new_head = self.git("rev-parse", "HEAD", root=root)
        if deliverable(base, new_head) != before:
            request_rebase()
            raise Bailout(
                "blocked", phase=phase_id,
                details=f"rebasing {branch} onto the moved {base} changed "
                        "the phase's diff — the branch is left rebased on "
                        f"{new_head[:12]}; review it, then resume — the "
                        "resume takes the branch as it then stands as "
                        "reviewed and re-runs the gate")
        if ps.get("reviewed_head"):
            ps["reviewed_head"] = new_head
        ps["gate_green_commit"] = None
        merge_base = self.git("merge-base", base, branch, root=root)
        self._save_state()
        self.log(f"[P{phase_id}] {base} moved by {behind} commit(s) under "
                 f"{branch}; rebased {old_head[:12]} → {new_head[:12]}, "
                 "diff unchanged")
        return merge_base

    def _handle_executor_terminals(self, verdict: dict,
                                   phase_id: str) -> None:
        """`question` is the operator's (exit 4); `blocked` is an error the
        orchestrator diagnoses (exit 3). Anything else proceeds."""
        if verdict["outcome"] == "question":
            # A review-stage writer question marks the phase so the resume
            # goes straight back to a writer round with the ruling —
            # executor- and gate-stage resumes re-dispatch a writer anyway.
            ps = self.state["phases"].get(phase_id)
            if ps is not None and ps.get("stage") == "review":
                ps["operator_question"] = verdict.get("summary", "")
                self._save_state()
            raise Bailout("operator_question", phase=phase_id, question=True,
                          details=verdict.get("summary", ""))
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", phase=phase_id,
                          details=verdict.get("summary", ""))

    def _after_session_plan_check(self) -> None:
        """Re-parse the plan right after a session that may have edited it,
        so a malformed edit is nudged back to its author while that session
        is still resumable."""
        self._load_plan()

    def _gate_until_green(self, phase: Phase, ps: dict, outputs: Path,
                          target: ResolvedTarget, branch: str,
                          merge_base: str, where: str,
                          spawn_executor) -> None:
        """A red gate spawns a fresh executor fix round (the fix rounds are
        the executor's — there is no separate fixer in the phase loop),
        capped; still red at the cap bails. A gate that ran nothing passes
        (`_run_gate`): no round can make a target without tests go green.

        A resume at stage `gate` re-runs the gate before anything else, so a
        fix round a crash interrupted arrives here again — its number was
        banked before the crash, and re-banking it would spend the cap
        twice."""
        while True:
            passed, gate_log = self._phase_gate(phase.id, ps, outputs,
                                                target, merge_base)
            if passed:
                return
            if ps["gate_fix_rounds"] >= GATE_FIX_CAP:
                raise Bailout(
                    "gate_red", phase=phase.id,
                    details=f"gate still red after {GATE_FIX_CAP} executor "
                            f"fix rounds (latest output: {gate_log})",
                )
            if self._reattach_round("code-writer", phase.id) is None:
                ps["gate_fix_rounds"] += 1
            r = ps["gate_fix_rounds"]
            self._save_state()
            red_cmds = self._red_cmds(ps, target)
            spawn_executor(lambda vp, _r=r, _log=gate_log, _red=red_cmds:
                           EXECUTOR_GATE_FIX_PROMPT.format(
                               phase_id=phase.id, slice_name=self.slice_name,
                               branch=branch, round=_r,
                               plan_path=self.plan_path, red_cmds=_red,
                               gate_log=_log, merge_base=merge_base,
                               where=where,
                               gate_hint=self._gate_hint(target, outputs),
                               verdict_path=vp,
                               pointers=self._pointers(target, phase.id)))
            self._after_session_plan_check()

    def _review_loop(self, phase: Phase, ps: dict, outputs: Path,
                     target: ResolvedTarget, branch: str, merge_base: str,
                     where: str, gate_hint: str, spawn_executor) -> None:
        phase_id = phase.id
        root = target.work_root
        while True:
            # The round number is proposed here and only BANKED once the
            # round actually produced a review. A round that died — blocked,
            # protocol failure, a session-limit window — funds nothing and
            # reviewed nothing.
            pending = self._reattach_round("code-reviewer", phase_id)
            r = ps["review_rounds"] + 1 if pending is None else pending
            head = self.git("rev-parse", "HEAD", root=root)
            prev_head = ps.get("reviewed_head")
            review_set, review_repos = self._review_set_paragraph(
                phase, ps, target, merge_base)
            gate_line = self._gate_line(ps, head, target, review_repos)
            delta = bool(r > 1 and prev_head and prev_head != head)
            secrets = self._review_secrets(
                phase, outputs, r, root,
                [(prev_head, head), (merge_base, head)] if delta
                else [(merge_base, head)])
            review_path = outputs / f"code_review_r{r}.md"
            verdict_path = outputs / f"review_result_r{r}.json"
            if delta:
                prompt = REVIEWER_DELTA_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    round=r, prev_round=r - 1, branch=branch, where=where,
                    merge_base=merge_base, fix_range=f"{prev_head}..HEAD",
                    prev_review=outputs / f"code_review_r{r - 1}.md",
                    plan_path=self.plan_path,
                    verification_path=self.verification_path,
                    review_path=review_path, verdict_path=verdict_path,
                    secrets=secrets, review_set=review_set,
                    gate_line=gate_line,
                    philosophy_line=self._philosophy_line(),
                    skill_line=self._skill_line(phase_id),
                    close_out_line=self._close_out_line(),
                )
            else:
                prompt = REVIEWER_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    round=r, merge_base=merge_base, branch=branch,
                    where=where, plan_path=self.plan_path,
                    verification_path=self.verification_path,
                    review_path=review_path, verdict_path=verdict_path,
                    secrets=secrets, review_set=review_set,
                    gate_line=gate_line,
                    philosophy_line=self._philosophy_line(),
                    skill_line=self._skill_line(phase_id),
                    close_out_line=self._close_out_line(),
                )
            verdict, _ = self._spawn(
                "code-reviewer", prompt, self.repo_root, verdict_path,
                phase_id, r, agent="code-reviewer",
            )
            if verdict["outcome"] == "blocked" \
                    or verdict.get("_protocol_failure"):
                raise Bailout("blocked", phase=phase_id,
                              details=verdict.get("summary", ""))
            # A real verdict: this round is spent, and its HEAD is what the
            # next round's fix range is measured against.
            ps["review_rounds"] = r
            ps["reviewed_head"] = head
            self._save_state()
            if verdict["outcome"] == "signoff":
                return
            # issues / critical → the funding decision. Round 1's fix is
            # automatic; from round 2 on — and for any `critical` — a fresh
            # consult judges the findings against the rising bar BEFORE an
            # executor round is spent.
            if r >= 2 or verdict["outcome"] == "critical":
                fix_range = f"{prev_head}..{head}" if delta else None
                choice = self._review_funding_consult(
                    outputs, phase_id, r, verdict, fix_range, root)
                if choice == "merge":
                    return
            fix_verdict = spawn_executor(
                lambda vp, _r=r: EXECUTOR_REVIEW_FIX_PROMPT.format(
                    phase_id=phase_id, slice_name=self.slice_name,
                    plan_path=self.plan_path, branch=branch,
                    merge_base=merge_base, where=where,
                    review_path=outputs / f"code_review_r{_r}.md",
                    gate_hint=gate_hint, verdict_path=vp,
                    pointers=self._pointers(target, phase_id)))
            self._after_session_plan_check()
            refuted = self._handle_refutations(outputs, phase_id, r,
                                               fix_verdict)
            self._gate_until_green(phase, ps, outputs, target, branch,
                                   merge_base, where, spawn_executor)
            if self._refutation_settles_review(verdict, refuted, ps, root):
                self.log(f"[P{phase_id}] every blocking finding of round {r} "
                         "was refuted with no code change — review settled")
                return

    def _handle_refutations(self, outputs: Path, phase_id: str, r: int,
                            fix_verdict: dict) -> set[str]:
        """The refuted-verdict path: a blocking finding the fix round could
        not make fail is recorded onto the round's review file, where the
        next round's reviewer reads it, and entered in the close-out report
        with its refutation evidence for the operator. Returns the refuted
        finding ids."""
        entries = fix_verdict.get("refuted")
        if not isinstance(entries, list) or not entries:
            return set()
        review_path = outputs / f"code_review_r{r}.md"
        ids: set[str] = set()
        lines = []
        for e in entries:
            fid = str(e.get("id", "?")) if isinstance(e, dict) else str(e)
            evidence = str(e.get("evidence", "")) if isinstance(e, dict) \
                else ""
            ids.add(fid)
            lines.append(f"- {fid}: {evidence}" if evidence else f"- {fid}")
            claim = self._finding_summary(phase_id, r, fid)
            self._report(
                "Notable events",
                f"Fix round after review r{r} of P{phase_id} refuted {fid}",
                ("The fix round witnessed the claimed failure of the "
                 f"reviewer's finding {fid}"
                 + (f' — "{claim}" —' if claim else "")
                 + " and could not make it fail: no code changed for it, "
                 "and the finding funds no further work. The writer's "
                 "evidence: " + (evidence or "(none given)")
                 + f"\n\nThe full finding and the refutation record are in "
                 f"{review_path}."),
                consequence="none the loop acts on — the finding funds no "
                            "further work and no code changed for it; "
                            "recorded so the reviewer's claim is not "
                            "re-filed as open.",
                provenance=f"witnessed — code-writer P{phase_id}, fix round "
                           f"after review r{r}; the review verdict's "
                           "findings list in state.json")
        if review_path.exists():
            review_path.write_text(
                review_path.read_text()
                + REFUTATION_TAG.format(round=r, entries="\n".join(lines)))
        self.log(f"[P{phase_id}] fix round refuted "
                 f"{len(ids)} finding(s): {', '.join(sorted(ids))}")
        return ids

    def _finding_summary(self, phase_id: str, r: int,
                         fid: str) -> str | None:
        """The one-line summary the round-r reviewer reported for finding
        `fid`, from the history row that persisted its `findings` list."""
        for row in reversed(self.state.get("history", [])):
            if (row.get("phase") == phase_id and row.get("round") == r
                    and row.get("role") == "code-reviewer"):
                for f in row.get("findings") or []:
                    if isinstance(f, dict) and str(f.get("id")) == fid:
                        return str(f.get("summary") or "") or None
                return None
        return None

    def _report(self, section: str, headline: str, body: str,
                consequence: str, provenance: str | None = None,
                proposal: str | None = None) -> str | None:
        """The driver's own close-out entries — deterministic events the
        operator should see without reading the log, each with the stock
        consequence line its event carries. A report an agent removed is
        logged, never a bail: the run's outcome does not hang on its
        narrative — an operator's edit the write would drop is the one stop
        (`_report_refused`). Returns the entry's id, None when it was not
        written."""
        try:
            eid = append_entry(self.slice_dir, section, headline, body,
                               consequence=consequence, provenance=provenance,
                               proposal=proposal)
        except ReportError as e:
            self._report_refused(e)
            self.log(f"close-out entry not written ({e}): {headline}")
            return None
        self.log(f"close-out {eid}: {headline}")
        return eid

    def _refutation_settles_review(self, review_verdict: dict,
                                   refuted: set[str], ps: dict,
                                   root: Path) -> bool:
        """True when the fix round changed no code and refuted every
        blocking finding of the round it answered: re-reviewing the
        identical diff would be relitigation by construction. Requires the
        review verdict's machine-readable findings — without them the loop
        cannot know the blocking set and falls back to another round."""
        if not refuted:
            return False
        if self.git("rev-parse", "HEAD", root=root) != ps.get("reviewed_head"):
            return False
        findings = review_verdict.get("findings")
        if not isinstance(findings, list) or not findings:
            return False
        blocking = {str(f.get("id")) for f in findings
                    if isinstance(f, dict) and f.get("impact") == "blocking"}
        if not blocking or "None" in blocking:
            return False
        return blocking <= refuted

    def _production_paths(self, fix_range: str, root: Path) -> list[str]:
        """Paths in the range that are production code — not tests, not
        docs. Conservative by design — a docstring-only code edit still
        counts as production."""
        files = self.git("diff", "--name-only", fix_range,
                         root=root).splitlines()

        def _nonprod(path: str) -> bool:
            parts = path.split("/")
            return (path.endswith(".md") or path.endswith("_test.go")
                    or "tests" in parts or "docs" in parts
                    or "manual" in parts)

        return [f for f in files if f and not _nonprod(f)]

    def _review_funding_consult(self, outputs: Path, phase_id: str, r: int,
                                verdict: dict, fix_range: str | None,
                                root: Path) -> str:
        """Judge whether review round r's findings fund another executor
        round or the phase merges with them recorded in the close-out
        report. Returns 'fix_round' or 'merge' ('bail' raises inside
        _consult)."""
        review_path = outputs / f"code_review_r{r}.md"
        merge_note = ("merge now; the unresolved findings stay in the review "
                      "file and the merge is recorded in the close-out "
                      "report for the operator")
        if r >= REVIEW_ROUND_CAP:
            site = "review-budget"
            situation = REVIEW_BUDGET_SITUATION.format(
                round=r, phase_id=phase_id, outcome=verdict["outcome"],
                review_path=review_path, cap=REVIEW_ROUND_CAP)
            actions = {"merge": merge_note,
                       "bail": "stop the slice for the orchestrator"}
        else:
            site = "review-funding"
            prose_only = bool(fix_range) and \
                not self._production_paths(fix_range, root)
            situation = REVIEW_FUNDING_SITUATION.format(
                round=r, phase_id=phase_id, outcome=verdict["outcome"],
                review_path=review_path, cap=REVIEW_ROUND_CAP,
                prose_fact=(REVIEW_PROSE_FACT.format(fix_range=fix_range)
                            if prose_only else ""),
                bar=_review_bar(r, prose_only))
            actions = {
                "fix_round": "the findings clear the bar: spend an executor "
                             "fix round; the next review round verifies it",
                "merge": f"the findings do not clear the bar: {merge_note}",
                "bail": "stop the slice for the orchestrator",
            }
        choice = self._consult(
            site, situation, actions, [review_path], phase_id)
        if choice["outcome"] == "merge":
            findings = [f for f in verdict.get("findings") or []
                        if isinstance(f, dict)]
            listing = "\n".join(
                f"- {f.get('id', '?')} [{f.get('severity', '?')}/"
                f"{f.get('impact', '?')}]: {f.get('summary', '')}"
                for f in findings)
            self._report(
                "Notable events",
                f"P{phase_id} merged with unresolved review findings "
                f"after r{r}",
                (f"Review round {r} reported `{verdict.get('outcome')}` and "
                 f"the {site} consult chose to merge rather than fund another "
                 f"fix round. Its reasoning: {choice.get('summary', '')}"
                 + (f"\n\nThe unresolved findings, as the reviewer tagged "
                    f"them:\n{listing}" if listing else "")
                 + f"\n\nThe full review is {review_path}."),
                consequence="the findings listed above are in the merged "
                            "tree as the reviewer left them; nothing later "
                            "in the run acts on them.",
                provenance=f"witnessed — consult {self.state.get('consult_seq')} "
                           f"({site}, P{phase_id} r{r})")
        return choice["outcome"]

    # -- the loop-tail gate sweep ---------------------------------------------
    # Slice 152 reached the completion consult with the manual known-red
    # ("owed to the doc phase"); the consult answered `complete`, the test
    # phase pushed to confirm, and CI failed a build the tree could never
    # pass. The sweep makes the tree's whole gate state a driver-run fact
    # BEFORE the loop-tail dispatches, so the fix-or-bail decision is made
    # at the consult — where it costs nothing — never at push time.

    def _sweep_targets(self) -> list[Path]:
        """The repos the loop-tail sweep covers: every repo in the run's
        `bases` record (spec repo excluded — nothing deploys from it) that
        carries a kc manifest. A repo without one has no deterministic
        gates to run."""
        return [root for root, _ in self._touched_roots()
                if (root / ".kubecoder" / "project.yaml").is_file()]

    def _ensure_gate_sweep(self) -> dict:
        """The current sweep record, running the sweep if the recorded one
        no longer describes the tree. Commit-stamped like the per-phase
        gate's green: the record is reused only while every swept repo's
        HEAD is exactly the swept commit — any movement (a consult
        committing mechanical residue, an appended phase merging) re-runs
        the whole sweep, so the report a dispatch consumes always describes
        the tree that dispatch sees. Interrupted mid-sweep there is simply
        no record yet; the next call re-runs it."""
        targets = self._sweep_targets()
        heads = {str(root): self.git("rev-parse", "HEAD", root=root)
                 for root in targets}
        sweep = self.state.get("gate_sweep")
        if sweep and sweep.get("commits") == heads \
                and not self._unruled_waivers(sweep):
            return sweep
        return self._run_gate_sweep(targets, heads)

    def _unruled_waivers(self, sweep: dict) -> bool:
        """Whether the record holds a WAIVED row no gate ruling covers any
        more — the operator withdrew it, so that suite is owed a run."""
        gates = [(r, t) for r, t in self._current_rulings()
                 if r.kind == "gate"]
        return any(sweep_row_outcome(row) == "waived"
                   and self._covering(gates, row["repo"],
                                      row["component"]) is None
                   for row in sweep.get("results", []))

    def _run_gate_sweep(self, targets: list[Path], heads: dict) -> dict:
        n = self.state["sweep_runs"] = self.state.get("sweep_runs", 0) + 1
        self._save_state()
        out_dir = self.slice_dir / "sweeps" / f"r{n}"
        out_dir.mkdir(parents=True, exist_ok=True)
        self.announce(f"gate sweep r{n} (lint+build+test, "
                      f"{len(targets)} repo(s))")
        t0 = time.monotonic()
        results = []
        gates = [(r, t) for r, t in self._current_rulings()
                 if r.kind == "gate"]
        for root in targets:
            # Read every root's manifest here, the invoking repo included:
            # a phase may have registered a component since the run started,
            # and a sweep that skipped it would leave it untested (#746).
            components = load_project_dirs(root)
            for component in components:
                for verb in SWEEP_VERBS:
                    ruling = (self._covering(gates, root, component)
                              if verb == "test" else None)
                    results.append(
                        self._waived_row(root, component, ruling)
                        if ruling is not None else
                        self._run_sweep_cmd(root, component, verb, out_dir))
        duration_s = int(time.monotonic() - t0)
        # Red only on a red row: a row that ran nothing is not a failure,
        # and a sweep in which nothing ran at all proved nothing — it is not
        # green either.
        outcomes = [sweep_row_outcome(r) for r in results]
        outcome = ("red" if "red" in outcomes
                   else "green" if "green" in outcomes else "nothing_ran")
        self.state["gate_sweep"] = {
            "run": n, "commits": heads, "outcome": outcome,
            "green": outcome == "green", "ran_at": _now_iso(),
            "results": results,
        }
        reds = [f"{Path(r['repo']).name}/{r['component']} {r['verb']}"
                for r, o in zip(results, outcomes, strict=True) if o == "red"]
        empty = outcomes.count("nothing_ran")
        waived = outcomes.count("waived")
        unrunnable = outcomes.count("unrunnable")
        summary = "; ".join(reds) or (
            f"{len(results)} command(s)"
            + (f", {empty} of them ran nothing" if empty else ""))
        if waived:
            summary += f" ({waived} waived by ruling)"
        if unrunnable:
            summary += f" ({unrunnable} unrunnable — tool missing)"
        self._record(None, "sweep", n, outcome, summary, None, duration_s)
        self.announce(f"gate sweep r{n} → "
                      + ("RED (" + ", ".join(reds) + ")" if reds
                         else GATE_OUTCOME_LABELS[outcome].lower())
                      + f" ({duration_s}s)")
        return self.state["gate_sweep"]

    def _waived_row(self, root: Path, component: str,
                    ruling: Ruling) -> dict:
        """A sweep `test` row a gate ruling covers: not run, recorded with
        the substitute the ruling names — neither green nor red."""
        self.log(f"[sweep] {root.name}/{component} test → WAIVED by plan.md's "
                 f"`## Driver rulings` (substitute: {ruling.substitute_text})")
        self._report_ruling(ruling, "sweep")
        return {"repo": str(root), "component": component, "verb": "test",
                "outcome": "waived", "green": False,
                "substitute": ruling.substitute, "why": ruling.why,
                "log": None, "duration_s": 0}

    def _run_sweep_cmd(self, root: Path, component: str, verb: str,
                       out_dir: Path) -> dict:
        """One sweep command, per component so a red in one suite never
        hides a red in the next (the kc verbs are fail-fast across their
        selection). A component with no statement for the verb makes a
        `nothing_ran` row — neither green nor red. So does a red that is
        only cexec's missing-tool line: an `unrunnable` row, the tool on it,
        proving nothing and asking no session to fix it (the tool check at
        startup names it to the operator; this is a repo that slipped past
        it, or a call a script makes). `green` stays on the row beside
        `outcome`, true for a green row only."""
        argv = ["kc", "project", verb, "--project", component]
        log_path = out_dir / f"{root.name}_{component}_{verb}.log"
        t0 = time.monotonic()
        try:
            with open(log_path, "w") as log_file:
                returncode = self._gate_exec(argv, root, log_file)
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout",
                details=f"sweep `{' '.join(argv)}` in {root} exceeded "
                        f"{GATE_TIMEOUT}s (output in {log_path})",
            ) from None
        # rc 2 is kc's usage error — the component name came from kc's own
        # project list, so that is a driver bug, not a red suite.
        if returncode == 2:
            raise Bailout(
                "protocol_failure",
                details=f"sweep `{' '.join(argv)}` in {root} rejected its "
                        f"arguments (output in {log_path})")
        outcome = kc_outcome(returncode)
        tool = unavailable_tool(log_path) if outcome == "red" else None
        if tool is not None:
            outcome = "unrunnable"
        duration_s = int(time.monotonic() - t0)
        self.log(f"[sweep] {root.name}/{component} {verb} → "
                 f"{GATE_OUTCOME_LABELS[outcome]} ({duration_s}s)"
                 + (f" — cexec tool `{tool}` is not in this environment"
                    if tool else ""))
        row = {"repo": str(root), "component": component, "verb": verb,
               "outcome": outcome, "green": outcome == "green",
               "log": str(log_path), "duration_s": duration_s}
        if tool is not None:
            row["tool"] = tool
        return row

    def _ruled_rows(self, results: list[dict]
                    ) -> list[tuple[str, Ruling | None]]:
        """Each sweep row's effective outcome against the rulings as plan.md
        stands NOW, with the ruling behind it: a red `test` row a gate ruling
        covers is `waived`, any other red row an accept ruling covers is
        `accepted`. Judged at render time because the record outlives the
        rulings — it is reused while no head moves, and the operator may
        rule on a red after the sweep that found it."""
        rulings = self._current_rulings()
        gates = [(r, t) for r, t in rulings if r.kind == "gate"]
        out: list[tuple[str, Ruling | None]] = []
        for row in results:
            raw = sweep_row_outcome(row)
            if raw in ("red", "waived") and row["verb"] == "test":
                ruling = self._covering(gates, row["repo"], row["component"])
                if ruling is not None or raw == "waived":
                    out.append(("waived", ruling))
                    continue
            if raw == "red":
                accepts = [(r, t) for r, t in rulings
                           if r.kind == "accept" and r.verb == row["verb"]]
                ruling = self._covering(accepts, row["repo"],
                                        row["component"])
                if ruling is not None:
                    out.append(("accepted", ruling))
                    continue
            out.append((raw, None))
        return out

    @staticmethod
    def _row_label(row: dict, outcome: str, ruling: Ruling | None) -> str:
        if outcome == "accepted":
            return f"RED, accepted by ruling ({ruling.why})"
        if outcome == "unrunnable":
            return (f"{GATE_OUTCOME_LABELS[outcome]} — cexec tool "
                    f"`{row.get('tool')}` is not in this environment")
        if outcome != "waived":
            return GATE_OUTCOME_LABELS[outcome]
        substitute = (ruling.substitute_text if ruling is not None
                      else row.get("substitute") or "no substitute")
        why = ruling.why if ruling is not None else row.get("why", "")
        ran = " (ran RED)" if sweep_row_outcome(row) == "red" else ""
        return (f"WAIVED by ruling{ran} — substitute: {substitute}"
                + (f" ({why})" if why else ""))

    def _sweep_block(self, sweep: dict, green_stance: str,
                     red_stance: str) -> str:
        """The report as a dispatch carries it — every row with its log
        path, then the stance the caller's dispatch takes on it. A sweep in
        which nothing ran takes the unverified stance, rows or none. The
        stance follows the rows as the rulings leave them: red only on a red
        no ruling covers."""
        if not sweep["results"]:
            rows, stance = "- (nothing ran)", SWEEP_STANCE_NONE
        else:
            ruled = self._ruled_rows(sweep["results"])
            lines = []
            for repo, sha in sweep["commits"].items():
                lines.append(f"- {Path(repo).name} @ {sha[:12]}:")
                lines.extend(
                    f"  - {r['component']} {r['verb']} → "
                    f"{self._row_label(r, outcome, ruling)}"
                    + (f" — {r['log']}" if r.get("log") else "")
                    for r, (outcome, ruling)
                    in zip(sweep["results"], ruled, strict=True)
                    if r["repo"] == repo)
            rows = "\n".join(lines)
            outcomes = [outcome for outcome, _ in ruled]
            outcome = ("red" if "red" in outcomes
                       else "green" if "green" in outcomes else "nothing_ran")
            ruled_any = any(o in ("waived", "accepted") for o in outcomes)
            every_row = (SWEEP_EVERY_UNRULED_ROW if ruled_any
                         else SWEEP_EVERY_ROW)
            stance = {"green": green_stance.format(every_row=every_row),
                      "red": red_stance,
                      "nothing_ran": SWEEP_STANCE_NONE}[outcome]
            if ruled_any:
                stance += "\n\n" + SWEEP_RULINGS_NOTE
            if "unrunnable" in outcomes:
                stance += "\n\n" + SWEEP_UNRUNNABLE_NOTE
            for o, ruling in ruled:
                if ruling is not None and o in ("waived", "accepted"):
                    self._report_ruling(ruling, "sweep")
        return SWEEP_BLOCK.format(rows=rows, stance=stance)

    # -- follow-up generations ----------------------------------------------

    def _generation_bar(self) -> str:
        """The bar for the NEXT append generation; exhausting it is the
        caller's bail."""
        bar = GENERATION_BARS[min(self.state["generation"] + 1,
                                  GENERATION_CAP)]
        return f"{bar}\n\n{GENERATION_RIDER}"

    def _spend_generation(self, source: str) -> None:
        """A consult/test pass appended phases: spend a generation, or bail
        to the operator when a third one is pending."""
        self.state["generation"] += 1
        self._save_state()
        if self.state["generation"] > GENERATION_CAP:
            raise Bailout(
                "generation_exhausted", question=True,
                details=f"{source} appended more work after "
                        f"{GENERATION_CAP} follow-up generations — decide "
                        "what of it still runs in this slice (edit the plan, "
                        "then resume) and what goes in the close-out report.")
        self.log(f"follow-up generation {self.state['generation']} "
                 f"({source} appended phases)")

    def _has_unfinished_phase(self) -> bool:
        phases = self._load_plan()
        return any(not p.done for p in phases)

    def _push_owed_block(self) -> str:
        """The close-out entries that may describe what the push after the
        completion consult must not carry, as PUSH_OWED_BLOCK with its
        trailing blank line — empty when there are none, so the situation
        reads as it did without them. A report that cannot be read is
        logged and carries no block: the consult never stops over it."""
        try:
            owed = owed_before_push(self.slice_dir)
        except ReportError as e:
            self.log(f"close-out not read for what is owed before the push ({e})")
            return ""
        if not owed:
            return ""
        ids = [entry["id"] for entry, _ in owed]
        noun = "entry" if len(ids) == 1 else "entries"
        self.log(f"completion consult: {len(ids)} close-out {noun} owed before "
                 f"the push: {', '.join(ids)}")
        rows = "\n".join(f"- {entry['id']} — {entry.get('headline', '')} "
                         f"({'; '.join(reasons)})" for entry, reasons in owed)
        return PUSH_OWED_BLOCK.format(rows=rows) + "\n\n"

    def _test_owed_block(self) -> str:
        """The close-out entries that say a criterion of this slice is worded
        wrong, as TEST_OWED_BLOCK with its trailing blank line — empty when
        there are none, and where the project runs no test phase, which
        leaves them to the wrap-up. A report that cannot be read is logged
        and carries no block, as with _push_owed_block."""
        if not self.cfg.test_phase:
            return ""
        try:
            owed = owed_before_test(self.slice_dir)
        except ReportError as e:
            self.log(f"close-out not read for what to fix before the test phase ({e})")
            return ""
        if not owed:
            return ""
        ids = [entry["id"] for entry, _ in owed]
        noun = "entry" if len(ids) == 1 else "entries"
        self.log(f"completion consult: {len(ids)} close-out {noun} to fix before "
                 f"the test phase: {', '.join(ids)}")
        rows = "\n".join(f"- {entry['id']} — {entry.get('headline', '')} "
                         f"({', '.join(criteria)})" for entry, criteria in owed)
        return TEST_OWED_BLOCK.format(verification_path=self.verification_path,
                                      rows=rows) + "\n\n"

    def _completion_consult(self) -> bool:
        """After all phases are done: one fresh consult — 'does the plan
        describe outstanding work?' — carrying the loop-tail sweep and the
        close-out entries owed before the push and before the test phase.
        True → phases were appended, loop again."""
        self.state["run_phase"] = "consult"
        self._save_state()
        sweep = self._ensure_gate_sweep()
        choice = self._consult(
            "completion",
            COMPLETION_CONSULT_SITUATION.format(
                verification_path=self.verification_path,
                plan_path=self.plan_path,
                sweep_block=self._sweep_block(sweep,
                                              SWEEP_STANCE_CONSULT_GREEN,
                                              SWEEP_STANCE_CONSULT_RED),
                push_owed_block=self._push_owed_block(),
                test_owed_block=self._test_owed_block(),
                generation_bar=self._generation_bar()),
            {
                "complete": "the plan describes no outstanding work",
                "appended": "you appended phases for outstanding work that "
                            "clears the bar; the loop re-enters",
                "bail": "something is wrong enough to stop the slice",
            },
            [self.plan_path, self.verification_path], None,
        )
        if choice["outcome"] == "complete":
            return False
        self._after_session_plan_check()
        if not self._has_unfinished_phase():
            self.log("consult answered `appended` but no unfinished phase "
                     "exists — treating as complete")
            return False
        self._spend_generation("the completion consult")
        return True

    def _test_phase(self) -> bool:
        """The test phase, inside the loop: 'read the slice-testing-strategy
        doc and execute'. True → blocking findings were appended as phases,
        loop again. A round a crash interrupted keeps its number — a second
        one would look for its verdict under a name the finished round never
        wrote, and re-run the whole verification."""
        self.state["run_phase"] = "test"
        pending = self._reattach_round("test-agent", None)
        if pending is None:
            self.state["test_rounds"] = self.state.get("test_rounds", 0) + 1
        self._save_state()
        r = self.state["test_rounds"] if pending is None else pending
        test_plan_doc = self.cfg.test_strategy
        if not test_plan_doc:
            raise Bailout(
                "protocol_failure",
                details=f"{self.cfg.path} runs the test phase but names no "
                        "`test_phase.strategy` — it has no procedure doc to "
                        "execute")
        base = self._base_branch(self.repo_root)
        # The test session works across every repo the slice touched — it
        # pushes them and verifies what the push deployed — so all of them
        # are refreshed, not just the one it spawns in.
        for root, _ in self._touched_roots():
            self._fetch_origin(root)
        verdict_path = self.slice_dir / f"test_phase_result_r{r}.json"
        prd_line, prd_rulings = self._prd_line()
        for ruling in prd_rulings:
            self._report_ruling(ruling, "test-phase dispatch")
        verdict, session = self._spawn(
            "test-agent",
            TEST_PHASE_PROMPT.format(
                slice_name=self.slice_name, base_branch=base,
                test_plan_doc=test_plan_doc, slice_dir=self.slice_dir,
                plan_path=self.plan_path,
                verification_path=self.verification_path,
                close_out_line=dispatch_line(self.report_path),
                prd_line=prd_line,
                hold_block=self._hold_block(),
                rulings_block=self._rulings_block(),
                sweep_block=self._sweep_block(self.state["gate_sweep"],
                                              SWEEP_STANCE_TEST_GREEN,
                                              SWEEP_STANCE_TEST_RED),
                generation_bar=self._generation_bar(),
                verdict_path=verdict_path),
            self.repo_root, verdict_path, None, r, agent="test-agent",
            display="test-phase",
        )
        if verdict["outcome"] == "blocked":
            raise Bailout("blocked", details=verdict.get("summary", ""))
        if verdict["outcome"] == "clean":
            # the same re-parse the findings path gets: the push check reads
            # the plan's holds, so a malformed edit is nudged back while the
            # session that made it is still resumable
            self._after_session_plan_check()
            self._assert_pushed(session)
            return False
        # findings → blocking phases were appended
        self._after_session_plan_check()
        if not self._has_unfinished_phase():
            self.log("test phase reported `findings` but appended no phase "
                     "— its findings are in the close-out report; treating "
                     "as clean")
            self._assert_pushed(session)
            return False
        self._spend_generation("the test phase")
        return True

    def _push_check(self) -> tuple[list[str], list[tuple[Path, str]]]:
        """What the push check sees: one description per repo this slice
        touched whose base branch holds commits `origin` does not, and —
        separately, never in that list — the repos the plan holds that are
        ahead of their origin in exactly the same way, with its reason. A held repo's work
        is meant to stay local, so it is reported, never nudged.

        Re-fetched here rather than trusted from the test phase's dispatch:
        that session has been pushing since. A stale ref would report pushed
        work as missing."""
        held_why = self._held_roots()
        unpushed: list[str] = []
        held: list[tuple[Path, str]] = []
        for root, base in self._touched_roots():
            self._fetch_origin(root)
            if not self.git("rev-parse", "--verify", "--quiet",
                            f"origin/{base}", root=root, check=False):
                note = f"{root}: no origin/{base} at all"
            else:
                count = self.git("rev-list", "--count",
                                 f"origin/{base}..{base}", root=root)
                if count in ("", "0"):
                    continue
                note = (f"{root}: {count} commit(s) on {base} that "
                        f"origin/{base} does not have")
            why = held_why.get(str(root))
            if why is None:
                unpushed.append(note)
            else:
                held.append((root, why))
        return unpushed, held

    def _report_hold(self, root: Path, why: str) -> None:
        """A held repo, entered in the close-out report once per run: the
        slice's commits stay local, so the push is a keystroke only the
        operator can make. Marked in state.json once the write is over, so a
        write an operator's edit stopped is the resume's to make."""
        key = str(root)
        reported = self.state.setdefault("holds_reported", [])
        if key in reported:
            return
        self.log(f"[push-check] {root.name} is held by the plan ({why}) — "
                 "reported, not nudged")
        headline = f"Push {root.name} by hand when its hold lifts"
        where = (f"The slice's commits sit on `{self._base_branch(root)}` in "
                 "that repo and nowhere else; every repo the plan does not "
                 "hold was pushed as usual.")
        # The plan loop seeds this entry at planning's exit 0, under this
        # headline: the run confirms it with a note rather than a second one.
        try:
            eid = find_by_headline(self.slice_dir, "Outstanding actions",
                                   headline)
            if eid is not None:
                add_note(self.slice_dir, eid, "driver, push check",
                         f"held as planned. {where}")
                self.log(f"close-out {eid} noted: {headline}")
                reported.append(key)
                self._save_state()
                return
        except ReportError as e:
            self._report_refused(e)
            self.log(f"close-out not searched for the seeded hold ({e})")
        self._report(
            "Outstanding actions", headline,
            f"`plan.md`'s `## Push holds` section holds `{root}`: {why}\n\n"
            + where,
            consequence="none in this run — the driver took the hold as the "
                        "ruling it is; nothing this repo deploys carries the "
                        "slice until you push it.",
            provenance="witnessed — the driver's push check, against "
                       "`plan.md`'s `## Push holds` section",
            proposal="Push it when the hold lifts.")
        reported.append(key)
        self._save_state()

    def _github_gate_problem(self, target: ResolvedTarget,
                             claimed: bool = False) -> str | None:
        """Why a GitHub target cannot run as planned, None when it can. Its
        clone gates through kc when it carries a manifest; one without has
        no gate at all, and a phase nothing verifies runs only on the
        operator's word — a `## Driver rulings` gate line covering it. A
        plan problem: the dry run lists it, and `_run_phase` refuses the
        phase with it.

        `claimed` is a phase's `Creates:` saying the manifest is still to
        come — the phase's own (`_run_phase`), or a pending one's at or
        before it (the dry run, `manifest_claimer`). The phase will be gated
        by what it writes, so it runs; the gate itself holds it to that
        (`_phase_gate`), where the clone still lacking one is this problem
        again."""
        if claimed or not github_target.is_github(target.name) \
                or target.gate_argv is not None \
                or self._gate_ruling(target) is not None:
            return None
        return (f"Target `{target.name}` is cloned at {target.git_root}, "
                "which has no `.kubecoder/project.yaml` — no deterministic "
                "gate, and no driver ruling waives one. Add a gate ruling for "
                "it under plan.md's `## Driver rulings`: "
                f"`- gate {target.name} — <substitute or none> — <why>`")

    def _refuse_ungated_github(self, phase_id: str, target: ResolvedTarget,
                               claimed: bool = False) -> None:
        """Stop the run on `_github_gate_problem` as the operator's question
        — before the writer, and again at the gate."""
        problem = self._github_gate_problem(target, claimed=claimed)
        if problem:
            raise Bailout(
                "plan_doc", question=True, phase=phase_id,
                details="the plan doc needs a fix only you can make:\n"
                        f"- phase P{phase_id}: {problem}")

    def _report_scratch_clone(self, target: ResolvedTarget) -> None:
        """A GitHub target's clone, entered in the close-out report once per
        clone per run, as an event that describes no problem — the record:
        the driver made (or adopted) it, and the close-out session removes it
        once the slice's commits are on origin. Nothing is asked of the
        operator. Marked in state.json once the write is over, so a write an
        operator's edit stopped is the resume's to make."""
        if not github_target.is_github(target.name):
            return
        clone = target.git_root
        key = str(clone)
        reported = self.state.setdefault("scratch_clones_reported", [])
        if key in reported:
            return
        headline = (f"The driver left a scratch clone at {clone} "
                    f"(`Target: {target.name}`)")
        try:
            if find_by_headline(self.slice_dir, "Notable events",
                                headline) is not None:
                self.log(f"close-out already holds: {headline}")
                reported.append(key)
                self._save_state()
                return
        except ReportError as e:
            self.log(f"close-out not searched for the scratch clone ({e})")
        self._report(
            "Notable events", headline,
            f"The driver cloned (or adopted) `{clone}` for `Target: "
            f"{target.name}`; the slice's phases for that repo are branched, "
            "merged and pushed there.\n\n"
            "Deleting it is safe once the slice's commits are on origin — "
            "the push check before the doc phase confirms that. The close-out "
            "session removes it then and says so under this entry; nothing is "
            "asked of the operator. A clone left in place is synced by every "
            "later preflight in this environment and adopted by the next "
            "`github:` target naming that repo.",
            consequence="none — the clone is where the run works; left "
                        "behind, it takes disk space and a sync in every "
                        "later preflight, until the close-out session "
                        "removes it.",
            provenance="witnessed — the driver's target resolution")
        reported.append(key)
        self._save_state()

    def _assert_pushed(self, session: str | None) -> None:
        """Before the doc phase: every repo the slice touched is on its
        origin. Nothing in the driver pushes a code phase — `_run_phase`
        ff-merges locally, primary repo and siblings alike — so the push is
        the test phase's, per its procedure doc; this is the check that it
        happened. An unpushed repo nudges that session, capped, then bails
        (the same shape as the doc gate): the driver never pushes another
        repo's work itself, because a multi-repo slice may need an order only
        the agent running the verification knows. A repo the plan holds is
        neither nudged nor bailed on — `_report_hold` puts it in the
        close-out report and the run carries on.

        A hold is per-slice and exceptional; `push.enabled = false` is the
        project saying its runs never reach origin at all. That one is its
        standing mode, not an outstanding keystroke, so it returns here
        without reporting anything."""
        if not self._push_on():
            return
        nudges = 0
        while True:
            unpushed, held = self._push_check()
            if not unpushed:
                # reported only once the rest is pushed, so the entry's
                # "every repo the plan does not hold was pushed" holds
                for root, why in held:
                    self._report_hold(root, why)
                return
            self.log("[test-phase] unpushed work: " + "; ".join(unpushed))
            if nudges >= PUSH_NUDGE_CAP or not session:
                raise Bailout(
                    "unpushed",
                    details="the test phase left this slice's work unpushed"
                            + (f" after {nudges} nudge(s)" if nudges
                               else "; no session to nudge")
                            + " — " + "; ".join(unpushed)
                            + ". Push it (or resolve why it cannot be "
                              "pushed), then resume.")
            nudges += 1
            self._nudge(
                PUSH_NUDGE_PROMPT.format(
                    repos="\n".join(f"- {u}" for u in unpushed),
                    round=nudges, cap=PUSH_NUDGE_CAP),
                self.repo_root, session, "[test-phase]", "test-agent")

    def _doc_phase(self) -> None:
        """The doc phase, after test-complete: one writer, diff-based over
        the whole slice, on its own branch — the writer never pushes. The
        writer and the gate run outside the devlock; the landing takes it
        for the pushes and lets it go after the last. The driver gates the
        result with the full lint+build+test sweep (red is nudged back to
        the writer's session), then rebase-merges the branch onto the base
        branch and pushes, then pushes the doc commits the writer made in
        the slice's other repos (`_push_doc_siblings`). The dev roll that
        push triggers is deliberately not tracked: the sweep already proved
        the tree, and the roll lands on its own.

        Between the writer and the gate sweep sits the wrap-up (`_wrap_up`),
        so that one landing carries both: `writer` → `wrap-up` → `gate` →
        `landing` → `siblings` → `done`.

        A project that runs no doc phase has no writer, and the ladder starts
        at the wrap-up — the gate and the landing below are then the
        wrap-up's alone. When nothing waits for the wrap-up either, all of it
        is skipped: the slice's code is already merged and settled by the
        time this is reached. The ladder is the doc phase's own record
        (`doc_phase`, marked `writer: false`) rather than a second one, so a
        resume re-enters it through `run_phase` exactly as before."""
        writes = self.cfg.doc_phase
        if not writes and "doc_phase" not in self.state:
            if not self._wrap_up_waits():
                self.log(f"doc phase disabled in {self.cfg.path.name} — "
                         "skipped; nothing waits for the wrap-up")
                return
            self.log(f"doc phase disabled in {self.cfg.path.name} — the "
                     "ladder starts at the wrap-up")
        self.state["run_phase"] = "docs"
        if "doc_phase" not in self.state:
            ds = {"stage": "writer" if writes else "wrap-up", "gate_runs": 0,
                  "nudges": 0, "session": None}
            if not writes:
                ds["writer"] = False
            # Where each other repo's base stood as the ladder began — on
            # origin by now, since the test phase (or `_settle_push`) pushed
            # it — so that `_push_doc_siblings` can tell the run's own
            # commits there from a base origin moved under. Taken once: a
            # resume keeps the first record, and a record from before this
            # field has none.
            primary = self.repo_root.resolve()
            ds["sibling_heads"] = {
                str(root): self.git("rev-parse", base, root=root)
                for root, base in self._touched_roots()
                if root.resolve() != primary}
            self.state["doc_phase"] = ds
        ds = self.state["doc_phase"]
        self._save_state()
        doc_plan_doc = self.cfg.doc_plan
        if writes and not doc_plan_doc:
            raise Bailout(
                "protocol_failure",
                details=f"{self.cfg.path} runs the doc phase but names no "
                        "`doc_phase.plan` — it has no procedure doc to "
                        "execute")
        base = self._base_branch(self.repo_root)
        root = self.repo_root
        branch = f"phase/{self.slice_num}-docs"

        if ds["stage"] == "wrap-up":
            # A resume into the stage starts it again from a clean slate —
            # before the branch setup below, which checks the doc branch out
            # of whatever tree an interrupted attempt left.
            self._wrap_up_clean_slate(branch)

        # Branch setup (fresh or resume; a resume past the writer stage
        # keeps the branch and the work on it). A landing-stage resume with
        # no branch means the merge landed before the crash — only the push
        # is owed; past the landing, only the other repos' pushes are. With
        # no writer there is a doc branch only once a wrap-up landed on it,
        # and nothing here creates one.
        existing = self.git("branch", "--list", branch, root=root)
        if not writes:
            if existing:
                self.git("checkout", branch, root=root)
        elif ds["stage"] == "writer" and not (
                self._reattach and self._reattach.get("role") == "doc-writer"):
            if existing:
                self.git("checkout", base, root=root)
                self.git("branch", "-D", branch, root=root)
            self.git("checkout", "-b", branch, base, root=root)
        elif existing:
            self.git("checkout", branch, root=root)
        elif ds["stage"] not in ("landing", "siblings"):
            ds.update(stage="writer", session=None)
            self.git("checkout", "-b", branch, base, root=root)
        self._save_state()

        if ds["stage"] == "writer":
            diff_rows = self._write_doc_diffs()
            verdict_path = self.slice_dir / "doc_phase_result.json"
            try:
                plan_text = self.plan_path.read_text()
            except OSError:
                plan_text = ""
            # Rendered before the writer starts, so a run that stalls in the
            # doc phase leaves a report that can be read.
            self._render_report()
            verdict, session = self._spawn(
                "doc-writer",
                DOC_PHASE_PROMPT.format(
                    slice_name=self.slice_name, doc_plan_doc=doc_plan_doc,
                    diff_rows="\n".join(diff_rows) or "  (no merged phase on record)",
                    slice_dir=self.slice_dir, plan_path=self.plan_path,
                    close_out_line=dispatch_line(self.report_path),
                    branch=branch, root=root, base_branch=base,
                    verdict_path=verdict_path)
                + build_slice_digest(plan_text),
                self.repo_root, verdict_path, None, 1, agent="doc-writer",
                display="doc-phase",
            )
            verdict = self._ensure_committed(None, "doc-writer", session,
                                             root, verdict, verdict_path)
            self._handle_executor_terminals(verdict, None)
            ds.update(stage="wrap-up", session=session)
            self._save_state()

        if ds["stage"] == "wrap-up":
            # Asked before the stage, which turns any stop into a leave-out:
            # an operator's edit of the report is theirs to settle, and the
            # resume re-enters the stage with the wrap-up still to run.
            self._assert_report_unedited()
            # Never raises a Bailout: whatever goes wrong in it is left out
            # of the landing, and the stage moves on.
            with self._report_logged():
                self._wrap_up(ds, branch)

        if ds["stage"] == "gate":
            self._doc_gate_until_green(ds, branch)
            ds["stage"] = "landing"
            self._save_state()

        # Its own stage, so a bail or a crash after the primary landed
        # resumes into the other repos' pushes without landing it again.
        if ds["stage"] == "landing":
            self._land_doc_branch(branch, base)
            ds["stage"] = "siblings"
            self._save_state()

        if ds["stage"] == "siblings":
            self._push_doc_siblings()
            ds["stage"] = "done"
            self._save_state()
        self.devlock.release(self.log)

    def _push_doc_siblings(self) -> None:
        """Push the doc commits the writer made outside the primary repo.

        The doc branch exists in the primary repo only, so a doc edit in
        another repo the slice touched is committed on that repo's base
        branch — after the test phase (or `_settle_push`) pushed it. Nothing
        else sends it: it would sit local and unreported. So once the
        primary has landed, every other repo in `_touched_roots` (the spec
        repo is not one) whose base is ahead of its origin is pushed, by the
        rules the driver's own pushes follow: a plan hold is reported, not
        pushed; a project that never pushes sends nothing; the devlock is
        held over the pushes, as over the primary's. A base that diverged
        from its origin is rebased onto it, unre-gated as the primary's
        landing is, when every commit only it carries is the run's own: the
        ladder recorded each repo's base as it began
        (`doc_phase.sibling_heads`), and origin carrying that sha proves
        every commit only the base carries came after it. CI committing to a
        sibling meanwhile — an image-pin bot after the test phase pushed —
        is that case (AIWF-41). Any other divergence, a dirty tree, a base
        not checked out or a rebase that conflicts is the operator's to
        settle. A push that loses a race to the next such commit fails as
        git's own error with the stage unmoved, so a resume fetches,
        rebases and pushes again; a repo already on its origin owes
        nothing, so a resume just runs this again."""
        primary = self.repo_root.resolve()
        roots = [(root, base) for root, base in self._touched_roots()
                 if root.resolve() != primary]
        if not roots:
            return
        if not self._push_on():
            self.log("[doc-phase] the project does not push — doc commits in "
                     + ", ".join(root.name for root, _ in roots)
                     + " stay local")
            return
        held_why = self._held_roots()
        if any(str(root) not in held_why for root, _ in roots):
            # Before the fetch, as for the primary: nothing another driver
            # pushes lands between the fast-forward check and the push. Kept
            # if the primary's landing already holds it.
            self._acquire_devlock("doc landing")
        for root, base in roots:
            self._fetch_origin(root)
            ahead = self.git("rev-list", "--count", f"origin/{base}..{base}",
                             root=root)
            if ahead in ("", "0"):
                continue
            why = held_why.get(str(root))
            if why is not None:
                self._report_hold(root, why)
                continue
            behind = self.git("rev-list", "--count", f"{base}..origin/{base}",
                              root=root)
            if behind not in ("", "0"):
                self._rebase_doc_sibling(root, base, ahead, behind)
            self.git("push", "origin", base, root=root)
            self.log(f"[doc-phase] pushed {base} in {root} ({ahead} "
                     "commit(s) the doc phase left there)")

    def _rebase_doc_sibling(self, root: Path, base: str, ahead: str,
                            behind: str) -> None:
        """Rebase a sibling's diverged base onto its origin when every local
        commit there is the run's own (`_push_doc_siblings` has the rule),
        or bail `blocked` saying why the driver would not."""
        began = (self.state.get("doc_phase", {}).get("sibling_heads", {})
                 .get(str(root)))
        if began is None:
            why = "the run has no record of where the doc phase began there"
        elif not self.git_ok("merge-base", "--is-ancestor", began,
                             f"origin/{base}", root=root):
            why = ("origin does not carry the commit the doc phase began "
                   "from, so not every local commit is the run's own")
        elif self._current_branch(root) != base:
            why = f"{base} is not checked out there"
        elif self._worktree_dirty(root):
            why = "the worktree there is dirty"
        else:
            try:
                self.git("rebase", f"origin/{base}", root=root)
            except Bailout:
                self.git("rebase", "--abort", root=root, check=False)
                raise Bailout(
                    "blocked",
                    details=f"the doc phase's commits on {base} in {root} do "
                            f"not rebase cleanly onto origin/{base} — "
                            "resolve by hand, push, then resume") from None
            self.log(f"[doc-phase] rebased {ahead} commit(s) of {base} in "
                     f"{root} onto origin/{base} ({behind} commit(s) origin "
                     "gained meanwhile)")
            return
        raise Bailout(
            "blocked",
            details=f"{base} in {root} has diverged from origin/{base} "
                    f"({ahead} local commit(s) origin lacks, {behind} on "
                    f"origin that {base} lacks), so the doc phase's commits "
                    "there cannot go out as a fast-forward, and the driver "
                    f"did not rebase them — {why}. Bring {base} up to "
                    f"origin/{base} there and push it by hand, then resume")

    def _write_doc_diffs(self) -> list[str]:
        """The slice's shipped diff, one file per repo under
        `<slice>/doc_phase/`, a section per merged phase — `git diff --stat`
        at the top of each, then that phase's own diff.

        The ranges are the phases' own landed ranges, never the base branch
        since the slice began: in parallel lanes that range carries whatever
        the other lanes merged meanwhile. The spec repo's `slices/` tree is
        held out, so the driver's own run record and every other slice's
        folder stay out of the diff — and no range reaches the doc branch, so
        a redispatched writer's own commits never read as shipped work. A
        section per phase rather than one range per repo: once another lane's
        merges sit between this slice's commits, its phases' ranges are not
        contiguous.

        A phase's commits outside its Target are in too — the pairs its
        `Review:` file gained since it began, the reviewer's set
        (`_doc_ledger_commits`), each a section after its repo's landings:
        Ansible slice 057's two runbook corrections were on the doc branch
        and in no section (AIWF-67). A repo no phase targets gets a file and
        a row saying the driver pushes no doc edit there
        (`_push_doc_siblings`), so a doc it needs goes in the close-out
        report.

        Returns the dispatch rows — the file and each phase's stat summary
        line, one row per repo; a repo whose phases all came out empty gets a
        row and no file, and a merged phase with no range on record gets a
        row of its own, as does a ledger line the driver cannot diff. The
        writer reads hunks by path from the file: in the sessions read, a
        per-file `git diff` past the tool's output limit was persisted and
        read back in two turns, and one 26 k-char diff was sliced three
        times.

        Every section is redacted (`_redact`, AIWF-51): slice 050's file
        carried five removed Secrets' CA keys and passwords to the writer.
        A section the redactor cannot redact stops the run before that
        repo's file is written. The folder ignores itself (`.gitignore`),
        so no `git add -A` in the spec repo commits a diff."""
        out_dir = self.slice_dir / "doc_phase"
        out_dir.mkdir(exist_ok=True)
        (out_dir / ".gitignore").write_text("*\n")
        ranged, unranged = self._landed()
        # Per repo, each section's (header label, row label, base, head): the
        # landings in merge order, then the ledger commits.
        by_repo: dict[str, list[tuple[str, str, str, str]]] = {}
        for pid, landed in ranged:
            by_repo.setdefault(landed["root"], []).append(
                (f"P{pid}", f"P{pid}", landed["base"], landed["head"]))
        ledgered, unhandled = self._doc_ledger_commits(ranged)
        # A ledger commit joins the file of the repo a phase landed in,
        # matched resolved; a repo none landed in gets a file after theirs.
        named: dict[Path, str] = {}
        for repo in by_repo:
            named.setdefault(Path(repo).resolve(), repo)
        for key, top, pid, review, parent, sha in ledgered:
            by_repo.setdefault(named.setdefault(key, top), []).append(
                (f"P{pid}, ledger {review}", f"P{pid} ledger {sha[:12]}",
                 parent, sha))
        targets = {Path(key).resolve() for key in self.state.get("bases", {})}
        rows: list[str] = []
        used: set[str] = set()
        for repo, items in by_repo.items():
            pathspec = self._bookkeeping_pathspec(Path(repo))
            spec = ["--", *pathspec] if pathspec else []
            sections: list[str] = []
            summaries: list[str] = []
            stubbed = 0
            for label, tag, base, head in items:
                rng = f"{base}..{head}"
                stat = self.git("diff", "--stat=100", rng, *spec,
                                root=Path(repo), check=False)
                if not stat:
                    continue
                diff, count = self._redact(
                    self.git_raw("diff", rng, *spec, root=Path(repo),
                                 check=False),
                    base, head, Path(repo))
                stubbed += count
                diff = diff.rstrip("\n")
                sections.append(
                    f"{repo} — {label}: git diff {base[:12]}..{head[:12]}"
                    f"\n\n{stat}\n\n{diff}\n")
                summaries.append(f"{tag}: {stat.splitlines()[-1].strip()}")
            if not sections:
                ids = ", ".join(tag for _, tag, _, _ in items)
                rows.append(f"- {repo}: no changes ({ids})")
                continue
            name = Path(repo).name or "repo"
            n = 1
            while name in used:
                n += 1
                name = f"{Path(repo).name or 'repo'}-{n}"
            used.add(name)
            path = out_dir / f"{name}.diff"
            path.write_text("\n".join(sections))
            if stubbed:
                self.log(f"doc phase: {stubbed} Secret data line(s) stubbed "
                         f"in {path}")
            row = f"- {repo}: {path} ({'; '.join(summaries)})"
            if Path(repo).resolve() not in targets:
                row += (" — no phase's Target: the driver pushes no doc edit "
                        "there, so a doc this needs goes in the close-out "
                        "report")
            rows.append(row)
        for pid in unranged:
            rows.append(
                f"- P{pid}: merged with no range on record (an earlier "
                "plugin version, or a resume past a crash at its merge) — "
                "its changes are not in the files above")
            self.log(f"doc phase: P{pid} merged with no range on record — "
                     "its changes are not in the diff files")
        return rows + unhandled

    def _doc_ledger_commits(self, ranged: list[tuple[str, dict]]) -> tuple[
            list[tuple[Path, str, str, str, str, str]], list[str]]:
        """The commits merged phases made outside their Targets, for the doc
        diff files: per phase in state order, the pairs its `Review:` file
        gained since the phase began — the set its reviewer was handed
        (`_review_set_paragraph`) — as (resolved root, root, phase id,
        ledger, parent, sha), in ledger order. A commit one of `ranged`'s
        ranges in that repo carries is left to that range's section, and one
        an earlier line named is not repeated. Apart, the dispatch rows of
        the gained lines the driver cannot diff — no checkout, no such
        commit, a root commit, or more than one commit on the line — each
        logged. A plan that cannot be read holds no ledger."""
        try:
            phases, _ = parse_plan(self.plan_path.read_text())
        except OSError:
            return [], []
        by_id: dict[str, Phase] = {}
        for phase in phases:
            by_id.setdefault(phase.id, phase)
        commits: list[tuple[Path, str, str, str, str, str]] = []
        rows: list[str] = []
        seen: set[tuple[Path, str]] = set()
        for pid, ps in self.state["phases"].items():
            phase = by_id.get(pid)
            if ps.get("status") != "merged" or phase is None:
                continue
            listed, ambiguous = self._review_set_now(phase) or ([], [])
            start = self._review_set_start(ps)
            for clone, sha in listed:
                if (clone, sha) in start:
                    continue
                resolved = self._ledger_commit(clone, sha)
                if isinstance(resolved, str):
                    rows.append(f"- P{pid}: {clone} {sha} in {phase.review} — "
                                f"{resolved}, so its changes are not in the "
                                "files above")
                    self.log(f"doc phase: P{pid} ledger {phase.review}: "
                             f"{clone} {sha} — {resolved}; its changes are "
                             "not in the diff files")
                    continue
                top, parent, full = resolved
                key = Path(top).resolve()
                if (key, full) in seen:
                    continue
                seen.add((key, full))
                if any(Path(landed["root"]).resolve() == key
                       and self._work_is_in(landed["head"], full, Path(top))
                       and not self._work_is_in(landed["base"], full,
                                                Path(top))
                       for _, landed in ranged):
                    continue
                commits.append((key, top, pid, phase.review, parent, full))
            start_unclear = self._review_set_ambiguous_start(ps)
            for clone, shas in ambiguous:
                if (clone, shas) in start_unclear:
                    continue
                rows.append(
                    f"- P{pid}: {phase.review} names more than one commit "
                    f"for {clone} on one line ({', '.join(shas)}) — the "
                    "driver cannot tell which is the phase's, so none of "
                    "them is in the files above")
                self.log(f"doc phase: P{pid} ledger {phase.review} names more "
                         f"than one commit for {clone} on one line "
                         f"({', '.join(shas)}); none of them is in the diff "
                         "files")
        return commits, rows

    def _ledger_commit(self, clone: str,
                       sha: str) -> tuple[str, str, str] | str:
        """A ledger pair as the doc diff reads it — (the clone's git root,
        the commit's parent, the commit's full sha) — or why it cannot be:
        a path that is no checkout (a missing one included: git cannot run
        there at all), a sha the clone does not have, or a root commit."""
        if not Path(clone).is_dir():
            return "not a git checkout"
        top = self.git("rev-parse", "--show-toplevel", root=Path(clone),
                       check=False)
        if not top:
            return "not a git checkout"
        full = self.git("rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}",
                        root=Path(top), check=False)
        if not full:
            return "no such commit there"
        parent = self.git("rev-parse", "--verify", "--quiet", f"{full}^",
                          root=Path(top), check=False)
        if not parent:
            return "a root commit, with no parent to diff against"
        return top, parent, full

    def _doc_gate_until_green(self, ds: dict, branch: str) -> None:
        """The driver's own full-sweep gate on the doc branch. Red is
        nudged back to the writer's session (a fix in place, committed,
        never pushed), capped; still red at the cap bails.

        The wrap-up stage may already have run this gate on the very commit
        the doc branch now stands at (`gate_last`): green on its own
        commits, or on the doc branch without them. That run stands for the
        first one here — a full sweep is the slowest step of the phase, and
        running it twice on one commit proves nothing more. A red one is the
        doc phase's red, and goes straight to the writer's nudge. Taken once:
        the next round runs the gate as ever."""
        last = ds.pop("gate_last", None)
        if last is not None:
            self._save_state()
        while True:
            head = (self.git("rev-parse", "HEAD", root=self.repo_root)
                    if isinstance(last, dict) and last.get("head") else None)
            if head and head == last["head"]:
                green, log_path = bool(last.get("green")), Path(last["log"])
                self.log(f"[doc-phase] gate: the wrap-up stage's run on "
                         f"{head[:12]} stands — "
                         + ("GREEN" if green else "RED") + f" ({log_path})")
            else:
                green, log_path = self._run_doc_gate(ds)
            last = None
            if green:
                return
            session = ds.get("session")
            if ds["nudges"] >= GATE_FIX_CAP or not session:
                raise Bailout(
                    "gate_red",
                    details="the gate sweep (kc project lint+build+test) "
                            "still red after the doc phase"
                            + (f" and {ds['nudges']} nudge(s)"
                               if ds["nudges"] else "")
                            + f" (latest output: {log_path})")
            ds["nudges"] += 1
            self._save_state()
            self._nudge(
                DOC_GATE_NUDGE_PROMPT.format(
                    round=ds["nudges"], cap=GATE_FIX_CAP, gate_log=log_path,
                    branch=branch),
                self.repo_root, session, "[doc-phase]", "doc-writer")
            self._ensure_committed(None, "doc-writer", session,
                                   self.repo_root)

    def _run_doc_gate(self, ds: dict) -> tuple[bool, Path]:
        """The full cross-component sweep — `kc project lint` + `build` +
        `test`, fail-fast across the verbs — run by the driver as the doc
        phase's deterministic gate. Fail-fast rather than per-component:
        this gate exists to go green or hand ONE red log to the fixer, not
        to produce a report. Output goes to doc_gate_r<N>.log in the slice
        folder. A verb no component defines a statement for ran nothing
        (KC_NOTHING_RAN): not red, so never nudged back to the writer, and
        the gate goes on to the next verb.

        A verb plan.md's `## Driver rulings` rule on for a component of this
        repo (a gate ruling's `test`, an accept ruling's verb) runs per
        component instead, so the ruling can be honoured for its component
        alone: a waived `test` is skipped, an accepted red is not red. Still
        fail-fast, on the first red no ruling covers."""
        ds["gate_runs"] += 1
        n = ds["gate_runs"]
        self._save_state()
        log_path = self.slice_dir / f"doc_gate_r{n}.log"
        rulings = [(r, t) for r, t in self._current_rulings()
                   if r.kind in ("gate", "accept")
                   and self._covering([(r, t)], self.repo_root, None)]
        ruled_verbs = [v for v in SWEEP_VERBS
                       if any(r.verb == v for r, _ in rulings)]
        components = (list(load_project_dirs(self.repo_root))
                      if ruled_verbs else [])
        self.log(f"[doc-phase] gate #{n} running "
                 f"(kc project {' + '.join(SWEEP_VERBS)}"
                 + (f"; {', '.join(ruled_verbs)} per component, by ruling"
                    if ruled_verbs else "") + ")")
        t0 = time.monotonic()
        outcomes: dict[str, str] = {}
        with open(log_path, "w") as log_file:
            for verb in SWEEP_VERBS:
                if verb in ruled_verbs:
                    commands = [(f"{c} {verb}",
                                 ["kc", "project", verb, "--project", c], c)
                                for c in components]
                else:
                    commands = [(verb, ["kc", "project", verb], None)]
                for label, argv, component in commands:
                    outcomes[label] = self._doc_gate_cmd(
                        argv, verb, component, rulings, log_file, log_path)
                    if outcomes[label] == "red":
                        break
                if "red" in outcomes.values():
                    break
        seen = set(outcomes.values())
        outcome = ("red" if "red" in seen
                   else "green" if "green" in seen else "nothing_ran")
        duration_s = int(time.monotonic() - t0)
        tail = ""
        try:
            lines = [ln for ln in log_path.read_text().splitlines()
                     if ln.strip()]
            tail = lines[-1] if lines else ""
        except OSError:
            pass
        self._record(None, "doc-gate", n, outcome, tail, None, duration_s)
        empty = [verb for verb, o in outcomes.items() if o == "nothing_ran"]
        unrunnable = [verb for verb, o in outcomes.items()
                      if o == "unrunnable"]
        self.log(f"[doc-phase] gate #{n} → {GATE_OUTCOME_LABELS[outcome]} "
                 f"({duration_s}s) {tail[:120]}"
                 + (f" — {', '.join(empty)} ran nothing" if empty else "")
                 + (f" — {', '.join(unrunnable)} unrunnable (tool missing)"
                    if unrunnable else ""))
        return outcome != "red", log_path

    def _doc_gate_cmd(self, argv: list[str], verb: str,
                      component: str | None,
                      rulings: list[tuple[Ruling, ResolvedTarget]],
                      log_file, log_path: Path) -> str:
        """One doc-gate command's outcome, the rulings applied: `waived`
        (not run) or `accepted` (ran red) where a ruling covers it. A red
        that is cexec's missing-tool line is `unrunnable` — logged, not red,
        so the gate goes on: nothing a doc writer changed can fix it."""
        if component is not None and verb == "test":
            waiver = self._covering([(r, t) for r, t in rulings
                                     if r.kind == "gate"],
                                    self.repo_root, component)
            if waiver is not None:
                log_file.write(f"$ {' '.join(argv)} → waived by plan.md's "
                               "`## Driver rulings` (substitute: "
                               f"{waiver.substitute_text})\n")
                self._report_ruling(waiver, "doc gate")
                return "waived"
        log_file.write(f"$ {' '.join(argv)}\n")
        log_file.flush()
        start = _file_size(log_path)
        try:
            rc = self._doc_gate_exec(argv, log_file)
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout",
                details=f"doc-phase gate `{' '.join(argv)}` exceeded "
                        f"{GATE_TIMEOUT}s (output in {log_path})",
            ) from None
        outcome = kc_outcome(rc)
        if outcome == "red":
            log_file.flush()
            tool = unavailable_tool(log_path, start)
            if tool is not None:
                log_file.write(f"→ UNRUNNABLE: cexec tool `{tool}` is not in "
                               "this environment — unverified, not red\n")
                self.log(f"[doc-phase] `{' '.join(argv)}` unrunnable — cexec "
                         f"tool `{tool}` is not in this environment")
                return "unrunnable"
        if outcome == "nothing_ran":
            log_file.write("→ nothing ran: "
                           + (f"{component} defines no" if component
                              else "no component defines a")
                           + f" {verb} statement\n")
        if outcome == "red" and component is not None:
            accept = self._covering([(r, t) for r, t in rulings
                                     if r.kind == "accept" and r.verb == verb],
                                    self.repo_root, component)
            if accept is not None:
                log_file.write("→ RED, accepted by plan.md's `## Driver "
                               f"rulings` ({accept.why})\n")
                self._report_ruling(accept, "doc gate")
                return "accepted"
        return outcome

    def _doc_gate_exec(self, argv: list[str], log_file) -> int:
        """One doc-gate command, in the invoking repo — the seam the doc
        gate's tests replace."""
        return self._gate_exec(argv, self.repo_root, log_file)

    def _land_doc_branch(self, branch: str, base: str) -> None:
        """Rebase-merge the gated doc branch and push — no build tracking;
        the sweep proved the tree, and the resulting dev roll lands on its
        own. A plan holding this repo lands the merge locally and stops
        there: the same ruling the push check honours, where the driver
        pushes the docs. The devlock this takes for the push is released by
        `_doc_phase`, after the other repos' doc pushes."""
        root = self.repo_root
        held = self._held_roots().get(str(root))
        if self._worktree_dirty(root):
            raise Bailout(
                "protocol_failure",
                details="worktree dirty at doc landing — an agent left "
                        "changes outside its commit boundary")
        # Two ways this repo's push is off — the plan holds it for this slice,
        # or the project never pushes — and origin plays no part in either. A
        # repo whose push is off is ahead of its origin by everything the slice
        # landed and stays that way, so the branch rebases onto its own local
        # base and the check below has nothing left to protect.
        pushing = self._push_on() and not held
        onto = f"origin/{base}" if pushing else base
        if pushing:
            # Taken before the fetch, so nothing another driver pushes lands
            # between the rebase target and the push; released once the last
            # doc push is out — the dev roll it triggers is untracked, so
            # there is nothing to hold for.
            self._acquire_devlock("doc landing")
        if self.git("branch", "--list", branch, root=root):
            if pushing:
                self.git("fetch", "origin", root=root)
                # Before any branch mutation: local `base` must not outrun
                # origin. The rebase below targets `origin/{base}`, so a commit
                # that only local `base` carries (an out-of-band fix landed
                # while the run sat at a bail) leaves the two divergent and the
                # `--ff-only` merge dies with a raw "Diverging branches can't be
                # fast-forwarded". Origin moving ahead is the harmless direction
                # — the rebase picks those commits up and local `base` is still
                # an ancestor.
                ahead = self.git("rev-list", "--count",
                                 f"origin/{base}..{base}", root=root)
                if ahead not in ("", "0"):
                    raise Bailout(
                        "blocked",
                        details=f"local {base} has {ahead} commit(s) that "
                                f"origin/{base} lacks, so the doc branch "
                                f"cannot fast-forward onto it — push {base} "
                                "(or resolve why it diverged), then resume")
            self.git("checkout", branch, root=root)
            try:
                self.git("rebase", onto, root=root)
            except Bailout:
                self.git("rebase", "--abort", root=root, check=False)
                raise Bailout(
                    "blocked",
                    details=f"the doc branch {branch} does not rebase "
                            f"cleanly onto {onto} — resolve by hand, "
                            "then resume",
                ) from None
            self.git("checkout", base, root=root)
            self.git("merge", "--ff-only", branch, root=root)
            self.git("branch", "-D", branch, root=root)
        if not pushing:
            if held:
                self._report_hold(root, held)
                self.log(f"[doc-phase] merged into {base} — {root.name} is "
                         "held by the plan, so nothing was pushed")
            else:
                self.log(f"[doc-phase] merged into {base}; the project does "
                         "not push — nothing sent to origin")
            return
        self.git("push", "origin", base, root=root)
        self.log(f"[doc-phase] merged into {base} and pushed — the dev roll "
                 "is not tracked")

    # -- the wrap-up -----------------------------------------------------------

    def _wrap_up_waits(self) -> bool:
        """Whether anything waits for the wrap-up — asked by a project that
        runs no doc phase before it enters the ladder at all. A report that
        cannot be read counts as waiting: the stage then records that as its
        soft failure, rather than the run passing it by without a word."""
        try:
            return bool(worklist(self.slice_dir))
        except ReportError as e:
            self.log(f"[wrap-up] its work list could not be read ({e})")
            return True

    def _wrap_up_branch(self) -> str:
        return f"phase/{self.slice_num}-wrap-up"

    def _wrap_up(self, ds: dict, doc_branch: str) -> None:
        """The wrap-up stage: one `dev:wrap-up` session works on what the
        close-out report's table gave it, its commits on branches of its own
        (`phase/<NNN>-wrap-up`); the driver gates them and they land with the
        doc phase, or are left out whole. run-loop.md § After the last phase
        is the contract, and `_wrap_up_run` its steps.

        **The wrap-up is never a reason to stop a run.** A soft failure — the
        session timed out, wrote no verdict or an invalid one, answered
        `blocked`, left changes uncommitted or committed outside its
        branches, or a gate is red with its commits — and equally any error
        the driver meets on the way (a git call that fails, the spec tree
        off its base, a report that cannot be read, a bug here) ends the stage one
        way (`_wrap_up_leave_out`): no commit of it reaches a base or the doc
        branch, in any repo; the store goes back to where it stood; one event
        is entered; and the ladder goes on. No Bailout leaves this method and
        the exit code never changes. Only an interrupt goes past it, as it
        does anywhere — a resume into the stage starts it over from a clean
        slate (`_wrap_up_clean_slate`).

        Whatever the outcome, the stage ends by moving `doc_phase.stage` on
        (`_wrap_up_decide`), and — when it did anything — by rendering the
        report and committing it."""
        wu = self.state["wrap_up"] = {
            "outcome": None, "reason": None, "session": None, "entries": [],
            "store": None, "repos": {}}
        self._save_state()
        # What the leave-out needs to undo, filled in as the steps go: the
        # branch each tree must stand on after the session (`watch`), and
        # every ref no commit of the wrap-up may reach (`guard`).
        ctx: dict = {"watch": {}, "guard": {}}
        try:
            self._wrap_up_run(ds, doc_branch, wu, ctx)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if isinstance(e, WrapUpLeftOut):
                reason, without = e.reason, e.without
            else:
                reason = (e.details if isinstance(e, Bailout)
                          else f"{type(e).__name__}: {e}")
                without = None
            try:
                self._wrap_up_leave_out(ds, wu, ctx, reason, without)
            except KeyboardInterrupt:
                raise
            except Exception as e2:
                self.log(f"[wrap-up] the leave-out did not finish "
                         f"({type(e2).__name__}: {e2})")
                if wu.get("outcome") is None:
                    wu["reason"] = wu.get("reason") or reason
                    self._wrap_up_decide(ds, wu, "left_out")
        if wu["outcome"] == "skipped":
            return
        self._render_report()
        try:
            self._commit_report(f"slice {self.slice_num}: close-out report "
                                "after the wrap-up")
        except Exception as e:
            why = e.details if isinstance(e, Bailout) else str(e)
            self.log(f"[wrap-up] close-out report not committed ({why})")

    def _wrap_up_run(self, ds: dict, doc_branch: str, wu: dict,
                     ctx: dict) -> None:
        """The stage's steps, in order; a soft failure raises WrapUpLeftOut
        for `_wrap_up` to end the stage with."""
        writes = ds.get("writer", True)
        primary = self.repo_root
        label = "[wrap-up]"

        # 1. Anything to do?
        try:
            items = worklist(self.slice_dir)
        except ReportError as e:
            raise WrapUpLeftOut(f"its work list could not be read ({e})") from None
        if not items:
            self.log(f"{label} nothing waits for the wrap-up — skipped")
            self._wrap_up_decide(ds, wu, "skipped")
            return
        wu["entries"] = [entry["id"] for entry, _ in items]
        self._save_state()

        # 2. Where the store stood: whatever the report holds uncommitted is
        # committed first, so that one commit is what a soft failure takes
        # the store back to — with every entry the run's agents appended
        # before the wrap-up in it.
        wu["store"] = self._commit_report(
            f"slice {self.slice_num}: close-out report before the wrap-up")
        self._save_state()

        # 3. The branches. Every code repo's base and the doc branch are
        # guarded — held repos too, since the wrap-up may not touch them
        # either — and each tree's post-session branch noted; a repo the
        # wrap-up would branch while it holds uncommitted work is not
        # dispatched into at all, since the wrap-up would carry that work
        # into its commits or the driver discard it after.
        branch = self._wrap_up_branch()
        repos = self._wrap_up_repos(self._held_roots())
        has_doc = writes and bool(self.git("branch", "--list", doc_branch,
                                           root=primary))
        for root, base in self._touched_roots():
            ctx["guard"][(str(root), base)] = self.git("rev-parse", base,
                                                       root=root)
        # With no doc branch yet, the landing below makes one; until the
        # stage has decided, none may exist (a None guard).
        ctx["guard"][(str(primary), doc_branch)] = (
            self.git("rev-parse", doc_branch, root=primary) if has_doc
            else None)
        for root, base in repos:
            home = (doc_branch if has_doc and self._is_primary(root)
                    else base)
            ctx["watch"][str(root)] = {"root": root, "expected": home,
                                       "dirty": self._worktree_dirty(root)}
        for root, _ in self._touched_roots():
            ctx["watch"].setdefault(str(root), {
                "root": root, "expected": self._current_branch(root),
                "dirty": self._worktree_dirty(root)})
        dirty = [root.name for root, _ in repos
                 if ctx["watch"][str(root)]["dirty"]]
        if dirty:
            raise WrapUpLeftOut("uncommitted changes in " + ", ".join(dirty)
                                + " before its dispatch")
        for root, _ in repos:
            home = ctx["watch"][str(root)]["expected"]
            sha = self.git("rev-parse", home, root=root)
            if self.git("branch", "--list", branch, root=root):
                if self._current_branch(root) == branch:
                    self.git("checkout", home, root=root)
                self.git("branch", "-D", branch, root=root)
            self.git("checkout", "-b", branch, sha, root=root)
            wu["repos"][str(root)] = {"branch": branch, "base": sha,
                                      "head": None}
            self._save_state()
            self.log(f"{label} {branch} cut in {root.name} from {home} "
                     f"({sha[:12]})")

        # 4. The dispatch. The spec tree stands on its base, where the
        # session commits the store, as every agent does.
        verdict_path = self.slice_dir / "wrap_up_result.json"
        why = self._dispatch_wrap_up(
            self._wrap_up_prompt(repos, branch, verdict_path), verdict_path,
            wu)

        # 5. After the session, whatever its outcome.
        reasons = [r for r in (why, *self._wrap_up_settle(wu, ctx)) if r]
        if reasons:
            raise WrapUpLeftOut("; ".join(reasons))

        # 6–7. The gate: every other repo it committed to with the gate a
        # phase there gets, then the primary with the doc gate. Nothing has
        # moved a base or the doc branch yet, so a red anywhere leaves it all
        # out — the repos already green included.
        carried: dict[str, int] = {}
        for root, _ in repos:
            info = wu["repos"][str(root)]
            n = self.git("rev-list", "--count", f"{info['base']}..{branch}",
                         root=root)
            if n not in ("", "0"):
                carried[str(root)] = int(n)
        if not carried:
            self.log(f"{label} no commit on any wrap-up branch — nothing to "
                     "gate or land in a code repo")
        for root, base in repos:
            if self._is_primary(root) or str(root) not in carried:
                continue
            green, where = self._wrap_up_sibling_gate(root, branch, base)
            if not green:
                raise WrapUpLeftOut(f"the gate in {root.name} is red with its "
                                    f"commits (output in {where})")
        green_at = None
        if str(primary) in carried:
            green_at = self._wrap_up_primary_gate(ds, branch,
                                                  ctx["watch"][str(primary)])

        # 8. Green. The doc branch moves up to the wrap-up branch, so the
        # doc landing carries both; with no doc phase the doc branch is made
        # here, at the wrap-up branch, for the same landing to take. In every
        # other repo the base fast-forwards, and `_push_doc_siblings` pushes
        # it with the doc-writer's own commits there. Each tree stands on its
        # home branch since the settle; a failure halfway is put back by the
        # leave-out's guard.
        for root, _ in repos:
            if str(root) not in carried:
                continue
            if self._is_primary(root) and not has_doc:
                self.git("checkout", "-b", doc_branch, branch, root=root)
            else:
                self.git("merge", "--ff-only", branch, root=root)
            self.log(f"{label} {carried[str(root)]} commit(s) of {branch} "
                     f"taken into {self._current_branch(root)} in {root.name}")
        if green_at is not None:
            ds["gate_last"] = green_at
        self._wrap_up_decide(ds, wu, "landed")
        self.announce("wrap-up landed")

    def _is_primary(self, root: Path) -> bool:
        return Path(root).resolve() == self.repo_root.resolve()

    def _wrap_up_primary_gate(self, ds: dict, branch: str,
                              watch: dict) -> dict:
        """The doc gate on the wrap-up branch in the primary repo — the doc
        phase's own sweep, run on its commits. Green: that run, for the gate
        stage to take as its first (`gate_last`). Red: once more on the doc
        branch without them, to tell whose red it is — green there, the
        wrap-up is left out and the doc phase goes on from that green; red
        there too, the wrap-up is left out all the same and the red is the
        doc phase's, for the writer's nudge (with no writer nobody is
        nudged and nothing stops: `_wrap_up_decide`)."""
        primary = self.repo_root
        home = watch["expected"]
        self.log(f"[wrap-up] the doc gate on {branch}, with its commits")
        self.git("checkout", branch, root=primary)
        try:
            green, log_path = self._run_doc_gate(ds)
            head = self.git("rev-parse", "HEAD", root=primary)
        finally:
            self.git("checkout", home, root=primary)
        if green:
            return {"head": head, "green": True, "log": str(log_path)}
        self.log(f"[wrap-up] the doc gate is red with its commits — once more "
                 f"on {home} without them")
        green_without, log_without = self._run_doc_gate(ds)
        without = {"head": self.git("rev-parse", "HEAD", root=primary),
                   "green": green_without, "log": str(log_without)}
        if green_without:
            raise WrapUpLeftOut("the doc gate is red with its commits and "
                                f"green without them (output in {log_path})",
                                without)
        raise WrapUpLeftOut("the doc gate is red with its commits and without "
                            "them — that red is the doc phase's (output in "
                            f"{log_without})", without)

    def _wrap_up_decide(self, ds: dict, wu: dict, outcome: str) -> None:
        """The stage's outcome and the stage after it, saved together, so a
        crash leaves the ladder either before the decision — and a resume
        starts the stage over — or past it, never at a decided stage it
        would run again.

        The doc phase goes on to its gate whatever the wrap-up did. With no
        writer there is a gate only where there is something to land: a
        landing that ran the doc gate takes it to the gate stage, which
        finds that run on the commit it stands at; a landing in other repos
        alone goes straight to their pushes. Anything else ends the ladder —
        nothing of the wrap-up is there to land. That holds for a wrap-up
        left out on a red the base has without its commits too: this project
        runs no doc gate, so without the wrap-up the run would have
        completed over that red, and the wrap-up is never the reason it
        does not. The red is in the log and in the left-out event."""
        wu["outcome"] = outcome
        last = ds.get("gate_last")
        if ds.get("writer", True):
            ds["stage"] = "gate"
        elif outcome == "landed":
            ds["stage"] = "gate" if last else "siblings"
        else:
            ds.pop("gate_last", None)
            ds["stage"] = "done"
        self._save_state()

    def _phase_roots(self) -> list[Path]:
        """The repos the slice's merged phases landed in, each once, in the
        order the phases merged. A phase merged with no range on record
        names its repo through its Target."""
        ranged, unranged = self._landed()
        roots = [Path(landed["root"]) for _, landed in ranged]
        for pid in unranged:
            target = (self.state["phases"].get(pid) or {}).get("target")
            if not target:
                continue
            try:
                roots.append(self._resolve_target(target).git_root)
            except ValueError as e:
                self.log(f"[wrap-up] P{pid}'s repo not resolved ({e})")
        out: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            if root.resolve() not in seen:
                seen.add(root.resolve())
                out.append(root)
        return out

    def _wrap_up_repos(self, held: dict[str, str]) -> list[tuple[Path, str]]:
        """The code repos the wrap-up may change, primary first, each with
        the base branch the run recorded there: the roots of the slice's
        merged phases and the primary repo, less the repos the plan holds
        and less a shared repo — the spec repo among them — which it commits
        into on its base, as every agent does, and never branches: whatever
        branch a shared checkout stands on is every session's."""
        held_roots = {Path(key).resolve() for key in held}
        roots = [self.repo_root]
        roots += [r for r in self._phase_roots() if not self._is_primary(r)]
        out: list[tuple[Path, str]] = []
        for root in roots:
            if root.resolve() in held_roots:
                continue
            if self._works_in_worktree(root):
                continue
            out.append((root, self._base_branch(root)))
        return out

    def _wrap_up_gate_text(self, root: Path) -> str:
        """A repo row's gate, as the wrap-up runs it on a fix: the command
        the driver itself runs there afterwards, written for the component
        the fix changed."""
        if self._is_primary(root):
            return ("`kc project lint`, `kc project build` and `kc project "
                    f"test` from {root} (the doc phase's gate) — each with "
                    "`--project <component>` for the component you changed. "
                    f"{NOTHING_RAN_HINT}.")
        target = self._repo_path_target(str(root), root)
        ruling = self._gate_ruling(target)
        if ruling is not None:
            return ("none the driver runs — waived by plan.md's `## Driver "
                    f"rulings` (substitute: {ruling.substitute_text})")
        if target.gate_argv is None:
            return (f"none the driver runs — {root} has no kc manifest; gate "
                    "a fix there per that repo's own conventions")
        return (f"`kc project test` from {root} — with `--project "
                "<component>` for the component you changed. "
                f"{NOTHING_RAN_HINT}.")

    def _wrap_up_prompt(self, repos: list[tuple[Path, str]], branch: str,
                        verdict_path: Path) -> str:
        rows = [f"  - {root} — branch {branch} — gate: "
                f"{self._wrap_up_gate_text(root)}" for root, _ in repos]
        spec_prose = (", prose of the spec repo"
                      if any(self._is_spec_root(root)
                             for root in self._phase_roots()) else "")
        return WRAP_UP_PROMPT.format(
            slice_name=self.slice_name,
            close_out_line=dispatch_line(self.report_path),
            close_out_verbs=textwrap.indent(
                verb_usage("worklist", "show", "list", "relabel", "propose",
                           "request-card", "leave", "fold"), "  "),
            worklist=textwrap.indent(worklist_view(self.slice_dir), "  "),
            repo_rows="\n".join(rows) or "  (none — the plan holds every code "
                                         "repo this slice touched)",
            spec_root=self.spec_root, spec_prose=spec_prose,
            hold_block=self._hold_block(WRAP_UP_HOLD_BLOCK),
            plan_path=self.plan_path, slice_dir=self.slice_dir,
            verdict_path=verdict_path)

    def _dispatch_wrap_up(self, prompt: str, verdict_path: Path,
                          wu: dict) -> str | None:
        """The wrap-up's session, through a path of its own: `_spawn` ends
        in `_rule_on_round`, whose protocol failure bails the run, and the
        wrap-up's may not. Kept from the ordinary dispatch: the session
        mechanics (`run_kc_session`), the log lines, the in-flight record,
        the spec tree's base assertion, the account session-limit wait and
        redispatch, and one history row with
        the session and its transcript whatever the outcome — the row
        `slice_cost.py` prices the role from. Dropped: the verdict nudge, the
        lost-wait recovery, the commit nudge, every bail, the salvage of a
        verdict a timed-out session had written, and the reattach — a resume
        into the stage starts it over. Returns None for a verdict the
        landing may go on from, else the soft failure's reason."""
        role, label, cwd = "wrap-up", "[wrap-up]", self.repo_root
        model, effort = MODELS[role]

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(cwd, sid)}")
            wu["session"] = sid
            in_flight = self.state.get("in_flight")
            if in_flight and in_flight.get("session") != sid:
                in_flight["session"] = sid
            self._save_state()

        while True:
            self.log(f"{label} session starting")
            self.announce("wrap-up")
            verdict_path.unlink(missing_ok=True)
            self.state["in_flight"] = {
                "phase": None, "role": role, "round": 1,
                "verdict_path": str(verdict_path), "session": None,
                "started_at": _now_iso(),
            }
            self._save_state()
            t0 = time.monotonic()
            try:
                self._assert_spec_on_base()
                self._assert_current()
                returncode, result = run_kc_session(
                    prompt=prompt, cwd=str(cwd), timeout=TIMEOUTS[role],
                    agent=role, model=model, effort=effort,
                    extra_env=SPAWN_ENV,
                    flags=spawn_flags(role, self.log),
                    progress=lambda line: self._emit(f"    {label} {line}"),
                    on_session=_note_session,
                )
            except subprocess.TimeoutExpired:
                sid = (self.state.get("in_flight") or {}).get("session")
                self.state["in_flight"] = None
                why = f"the session timed out after {TIMEOUTS[role]}s"
                self._record(None, role, 1, "timeout", why, sid,
                             TIMEOUTS[role],
                             transcript=_transcript_path(cwd, sid))
                self.log(f"{label} → timeout: {why}")
                return why
            except Exception:
                # Never a session to reattach to: the resume starts over.
                self.state["in_flight"] = None
                self._save_state()
                raise
            duration_s = int(time.monotonic() - t0)
            session_id = result.session_id
            verdict = _read_json(verdict_path)
            valid = isinstance(verdict, dict) and _verdict_valid(role, verdict)
            notice = None if valid else session_limit_notice(result)
            if notice is None:
                break
            self.state["in_flight"] = None
            self._record(None, role, 1, "session_limit",
                         notice.replace("\n", " ")[:200], session_id,
                         duration_s, transcript=_transcript_path(cwd, session_id))
            self._wait_out_session_limit(notice, label)

        self.state["in_flight"] = None
        transcript = _transcript_path(cwd, session_id)
        if not valid:
            if verdict is None:
                why = "it wrote no verdict"
            else:
                outcome = verdict.get("outcome") if isinstance(verdict, dict) \
                    else type(verdict).__name__
                why = f"its verdict is invalid (outcome {outcome!r})"
            summary = f"{why}; the session ended rc={returncode}"
            self._record(None, role, 1, "invalid", summary, session_id,
                         duration_s, transcript=transcript)
            self.log(f"{label} → invalid: {summary}")
            return why
        if returncode != 0:
            self.log(f"{label} session ended rc={returncode} but had written "
                     f"{verdict_path.name} — taken")
        outcome = verdict["outcome"]
        summary = str(verdict.get("summary") or "")
        lists = {key: [str(x) for x in verdict[key]] for key in WRAP_UP_LISTS
                 if isinstance(verdict.get(key), list)}
        self._record(None, role, 1, outcome, summary, session_id, duration_s,
                     transcript=transcript, extra=lists)
        self.log(f"{label} → {outcome}: {summary[:160]}")
        if outcome == "blocked":
            return "it answered blocked" + (f": {_clip(summary, 200)}"
                                            if summary else "")
        return None

    def _wrap_up_settle(self, wu: dict, ctx: dict) -> list[str]:
        """After the session, whatever its outcome: what it left uncommitted
        discarded where it left it, the head of each wrap-up branch recorded,
        every tree back on the branch the ladder expects, and a base or the
        doc branch that moved put back where it stood. Returns what it found,
        each a soft failure. Idempotent — the leave-out runs it again, over
        whatever a later step left half done, and a second pass over a
        settled tree finds nothing.

        A tree that held uncommitted work before the dispatch (a held repo:
        the wrap-up is not dispatched into a dirty repo it branches) is left
        as it is — that work is not the wrap-up's to discard."""
        problems: list[str] = []
        branch = self._wrap_up_branch()
        for key, watch in ctx["watch"].items():
            root = watch["root"]
            if not watch["dirty"] and self._worktree_dirty(root):
                where = self._current_branch(root)
                self._wrap_up_discard(root)
                problems.append(f"it left uncommitted changes in {root.name} "
                                f"(discarded on {where})")
            info = wu["repos"].get(key)
            if info is not None and self.git("branch", "--list", branch,
                                             root=root):
                info["head"] = self.git("rev-parse", branch, root=root)
            if self._current_branch(root) != watch["expected"]:
                self.git("checkout", watch["expected"], root=root)
        for (key, ref), sha in ctx["guard"].items():
            root = Path(key)
            if sha is None:
                if self.git("branch", "--list", ref, root=root):
                    if self._current_branch(root) == ref:
                        self.git("checkout", self._base_branch(root),
                                 root=root)
                    self.git("branch", "-D", ref, root=root)
                    self.log(f"[wrap-up] {ref} in {root.name} deleted — it "
                             "did not exist before the stage")
                continue
            now = self.git("rev-parse", ref, root=root)
            if now == sha:
                continue
            if self._current_branch(root) == ref:
                self.git("reset", "--hard", sha, root=root)
            else:
                self.git("branch", "-f", ref, sha, root=root)
            self.log(f"[wrap-up] {ref} in {root.name} was at {now[:12]} — put "
                     f"back to {sha[:12]}")
            problems.append(f"it committed outside its branches ({ref} in "
                            f"{root.name} moved to {now[:12]})")
        self._save_state()
        return problems

    def _wrap_up_discard(self, root: Path) -> None:
        """Discard what the wrap-up left uncommitted in a tree — tracked and
        untracked alike, the slice folder's bookkeeping held out where the
        tree holds it."""
        self._reset_tracked(root)
        pathspec = self._bookkeeping_pathspec(root)
        self.git("clean", "-fd", *(["--", *pathspec] if pathspec else []),
                 root=root)

    def _wrap_up_sibling_gate(self, root: Path, branch: str,
                              base: str) -> tuple[bool, str]:
        """The gate a phase whose Target is this whole repo gets, run by the
        driver on the wrap-up branch: (passed, where its output is). A repo
        with no manifest, or one a gate ruling waives, passes unrun, as such
        a phase does. The run leaves a `wrap-up-gate` history row, and
        nothing in it bails: a gate that times out is red."""
        target = self._repo_path_target(str(root), root)
        ruling = self._gate_ruling(target)
        if ruling is not None:
            self.log(f"[wrap-up] the gate in {root.name} is waived by plan.md's "
                     f"`## Driver rulings` (substitute: "
                     f"{ruling.substitute_text}) — not run")
            self._report_ruling(ruling, "wrap-up gate")
            return True, "waived"
        if target.gate_argv is None:
            self.log(f"[wrap-up] no deterministic gate in {root.name} — its "
                     "commits pass unverified")
            return True, "no gate"
        n = 1 + sum(1 for row in self.state["history"]
                    if row.get("role") == "wrap-up-gate")
        log_path = self.slice_dir / f"wrap_up_gate_r{n}.log"
        argv = target.gate_argv
        self.log(f"[wrap-up] gate #{n} running in {root.name} on {branch} "
                 f"({' '.join(argv)})")
        self.git("checkout", branch, root=root)
        t0 = time.monotonic()
        try:
            with open(log_path, "w") as log_file:
                try:
                    returncode = self._wrap_up_gate_exec(argv, target.gate_cwd,
                                                         log_file)
                except subprocess.TimeoutExpired:
                    log_file.write(f"→ timed out after {GATE_TIMEOUT}s\n")
                    returncode = None
        finally:
            self.git("checkout", base, root=root)
        duration_s = int(time.monotonic() - t0)
        outcome = "red" if returncode is None else kc_outcome(returncode)
        try:
            lines = [ln for ln in log_path.read_text().splitlines()
                     if ln.strip()]
        except OSError:
            lines = []
        tail = lines[-1] if lines else ""
        self._record(None, "wrap-up-gate", n, outcome, tail, None, duration_s,
                     extra={"repo": str(root)})
        self.log(f"[wrap-up] gate #{n} → {GATE_OUTCOME_LABELS[outcome]} "
                 f"({duration_s}s) {tail[:120]}")
        return outcome != "red", str(log_path)

    def _wrap_up_gate_exec(self, argv: list[str], cwd: Path, log_file) -> int:
        """One wrap-up gate command — the seam the wrap-up's tests replace."""
        return self._gate_exec(argv, cwd, log_file)

    def _commit_report(self, message: str, label: str = "[wrap-up]") -> str:
        """Commit the report — the store and the close-out.md rendered from
        it — where either changed, staged and committed by name on the spec
        tree's base, as the driver's own report commit is; return the spec
        repo's commit it now stands at. `label` heads the log line."""
        paths = [str(p) for p in (store_path(self.slice_dir), self.report_path)
                 if p.exists()]
        self._assert_spec_on_base()
        if paths and self.specs_git("status", "--porcelain", "--", *paths):
            self.specs_git("add", "--", *paths)
            self.specs_git("commit", "-m", message, "--", *paths)
            self.log(f"{label} committed {self.report_path.name}: "
                     f"{message}")
        return self.specs_git("rev-parse", "HEAD")

    def _wrap_up_restore_store(self, sha: str) -> None:
        """The store as it is in the spec repo's commit `sha`, written over
        the current one, rendered and committed: the entries the run's
        agents appended before the wrap-up are in it, what the wrap-up wrote
        is not."""
        store = store_path(self.slice_dir)
        text = self.specs_git("show", f"{sha}:./{store.name}")
        # The hash of the close-out.md last written stays the current
        # store's: the report on disk is that one, not the commit's, and an
        # edit made to it since is still one.
        try:
            data = json.loads(text)
            data["rendered"] = json.loads(store.read_text()).get("rendered")
            text = json.dumps(data, indent=2, ensure_ascii=False)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        tmp = store.with_name(store.name + ".tmp")
        tmp.write_text(text if text.endswith("\n") else text + "\n")
        os.replace(tmp, store)
        with self._report_logged():
            self._render_report()
        self._commit_report(f"slice {self.slice_num}: close-out report back to "
                            f"where it stood before the wrap-up ({sha[:12]})")
        self.log(f"[wrap-up] the store is back to {sha[:12]}")

    def _wrap_up_leave_out(self, ds: dict, wu: dict, ctx: dict, reason: str,
                           without: dict | None) -> None:
        """A soft failure, every time the same: the trees put back and every
        guarded ref where it stood — so no commit of the wrap-up reaches a
        base or the doc branch in any repo, the repos whose gate was green
        included; the wrap-up branches stay, unmerged — the store taken
        back, one event entered through the driver's own `_report`, and the
        ladder moved on. Each step is best-effort: the leave-out is what
        stands between the wrap-up and a stopped run, so it cannot be a stop
        itself."""
        reason = " ".join(str(reason).split()) or "an unknown failure"
        self.log(f"[wrap-up] left out of the landing: {reason}")
        try:
            self._wrap_up_settle(wu, ctx)
        except Exception as e:
            why = e.details if isinstance(e, Bailout) else str(e)
            self.log(f"[wrap-up] the trees could not all be put back ({why})")
        if wu.get("store"):
            try:
                self._wrap_up_restore_store(wu["store"])
            except Exception as e:
                why = e.details if isinstance(e, Bailout) else str(e)
                self.log(f"[wrap-up] the store could not be taken back ({why})")
        ds.pop("gate_last", None)
        if without is not None:
            ds["gate_last"] = without
        wu["reason"] = reason
        try:
            self._report(
                "Notable events",
                WRAP_UP_LEFT_OUT_HEADLINE.format(reason=_clip(reason, 300)),
                self._wrap_up_event_body(wu),
                consequence=WRAP_UP_LEFT_OUT_CONSEQUENCE,
                provenance="witnessed — the driver's wrap-up stage")
        except Exception as e:
            self.log(f"[wrap-up] the event was not entered ({e})")
        self._wrap_up_decide(ds, wu, "left_out")
        self.announce("wrap-up left out")

    def _wrap_up_event_body(self, wu: dict) -> str:
        """The left-out event's body: where the wrap-up's work can be read."""
        paras: list[str] = []
        repos = wu.get("repos") or {}
        if repos:
            rows = []
            for key, info in repos.items():
                head = info.get("head") or info.get("base") or "?"
                rows.append(f"- `{key}`: `{info.get('branch')}` at "
                            f"`{head[:12]}`, cut from "
                            f"`{(info.get('base') or '?')[:12]}`")
            paras.append("What it committed stays on its branches, unmerged:\n"
                         + "\n".join(rows))
        else:
            paras.append("It was left out before any branch was cut.")
        sid = wu.get("session")
        if sid:
            paras.append(f"Its session: `{sid}`, transcript "
                         f"`{_transcript_path(self.repo_root, sid)}`.")
        if wu.get("store"):
            paras.append("The store is back to where it stood in the spec "
                         f"repo's `{wu['store'][:12]}`; what the wrap-up wrote "
                         "there is in the history after that commit.")
        return "\n\n".join(paras)

    def _wrap_up_clean_slate(self, doc_branch: str) -> None:
        """A resume into the wrap-up stage starts it again from nothing: each
        tree an interrupted attempt left on its branch put back where the
        ladder expects it (what it held uncommitted discarded), the wrap-up
        branches deleted, a doc branch the attempt had begun to make for a
        project with no doc phase deleted, and the store taken back to where
        it stood before that attempt. Never a failure: what cannot be undone
        is logged, and the stage's own steps meet it again."""
        if self._reattach and self._reattach.get("role") == "wrap-up":
            self._reattach = None
        wu = self.state.get("wrap_up")
        if not isinstance(wu, dict):
            return
        writes = (self.state.get("doc_phase") or {}).get("writer", True)
        branch = self._wrap_up_branch()
        self.log("[wrap-up] the stage starts again from a clean slate")
        for key, info in (wu.get("repos") or {}).items():
            root = Path(key)
            try:
                home = self._base_branch(root)
                if (self._is_primary(root) and writes
                        and self.git("branch", "--list", doc_branch, root=root)):
                    home = doc_branch
                if self._current_branch(root) == info.get("branch", branch):
                    if self._worktree_dirty(root):
                        self._wrap_up_discard(root)
                    self.git("checkout", home, root=root)
                if self.git("branch", "--list", branch, root=root):
                    self.git("branch", "-D", branch, root=root)
            except Exception as e:
                why = e.details if isinstance(e, Bailout) else str(e)
                self.log(f"[wrap-up] {root.name} not put back ({why})")
        if not writes:
            root = self.repo_root
            try:
                if self.git("branch", "--list", doc_branch, root=root):
                    if self._current_branch(root) == doc_branch:
                        self.git("checkout", self._base_branch(root), root=root)
                    self.git("branch", "-D", doc_branch, root=root)
            except Exception as e:
                why = e.details if isinstance(e, Bailout) else str(e)
                self.log(f"[wrap-up] {doc_branch} not deleted ({why})")
        if wu.get("store"):
            try:
                self._wrap_up_restore_store(wu["store"])
            except Exception as e:
                why = e.details if isinstance(e, Bailout) else str(e)
                self.log(f"[wrap-up] the store could not be taken back ({why})")

    # -- top level -----------------------------------------------------------

    def _assert_agents(self) -> None:
        """`kc session create-headless --agent` does not validate names — a
        typo'd role spawns a plain SDK session that answers anyway. Assert
        every required definition resolves before dispatching anything."""
        missing = [role for role in REQUIRED_AGENTS
                   if not (AGENTS_DIR / f"{role}.md").is_file()]
        if missing:
            print("Error: agent definition(s) not found: "
                  + ", ".join(missing)
                  + f" (searched {AGENTS_DIR}) — reinstall the dev plugin",
                  file=sys.stderr)
            sys.exit(2)

    def preflight(self) -> None:
        if not self.plan_path.is_file():
            print(f"Error: {self.plan_path} does not exist — run /dev:plan-slice "
                  "first.", file=sys.stderr)
            sys.exit(2)
        if not self.verification_path.is_file():
            print(f"Error: {self.verification_path} does not exist — the "
                  "plan loop seeds it at GO.", file=sys.stderr)
            sys.exit(2)
        phases, errors = parse_plan(self.plan_path.read_text())
        if errors:
            print("Error: the plan doc does not parse:\n"
                  + "\n".join(f"  - {e}" for e in errors), file=sys.stderr)
            sys.exit(2)
        if not phases:
            print(f"Error: {self.plan_path} has no `### P<id> — <title>` "
                  "phases.", file=sys.stderr)
            sys.exit(2)
        if self._worktree_dirty(self.repo_root):
            print("Error: the working tree has uncommitted changes; commit "
                  "or stash before running a slice.", file=sys.stderr)
            sys.exit(2)

    def run(self) -> None:
        """The slice's run record takes one driver at a time; everything the
        run does happens inside that hold."""
        holder = self._slice_lock.acquire()
        if holder is not None:
            print(f"Error: {self._slice_lock.lock_path} is held — another "
                  "driver is running this slice:\n"
                  + "\n".join(f"  {line}" for line in holder.splitlines())
                  + "\nThe run record is shared and the code repo is not, so "
                    "a second driver rebuilds phase branches the first one is "
                    "still working on. Stop that run, or wait for it.",
                  file=sys.stderr)
            sys.exit(2)
        try:
            self._run()
        except BaseException as e:
            self._record_exit(_exit_status(e))
            raise
        finally:
            self._slice_lock.release()

    def _run(self) -> None:
        if self.state_path.exists():
            if not self.resume:
                print(f"Error: {self.state_path} exists. Pass --resume to "
                      "continue, or delete state.json to restart.",
                      file=sys.stderr)
                sys.exit(2)
            self._owns_state = True
            self.state = _read_json(self.state_path) or {}
            previous = note_fields(self._slice_lock.previous_note)
            if self.state.get("exit") is None and previous:
                self.log(f"the previous driver (pid {previous.get('pid', '?')}"
                         f", started {previous.get('started', '?')}) left no "
                         "exit record: killed from outside")
            # Cleared on disk before anything else, `in_flight` still in it:
            # a stale exit under a live run would read as the run's end, and
            # this one may yet be killed before it reattaches. The same write
            # puts this driver's record over the previous one's — the run is
            # wherever this driver runs now.
            self.state.pop("exit", None)
            self.state["driver"] = dict(self._slice_lock.driver)
            self._save_state()
            self._reattach = self.state.get("in_flight") or None
            self.state["in_flight"] = None
        self._owns_state = True
        if not self.state:
            self.state = {
                "slice": self.slice_name,
                "created_at": _now_iso(),
                "plugin_version": plugin_version(),
                "orchestrator": _orchestrator_record(),
                # The driver as run.lock's note names it, on disk with the
                # state's first save — before the start is reported.
                "driver": dict(self._slice_lock.driver),
                "run_phase": "phases",
                "bases": {},
                "known_phases": [],
                "phases": {},
                "generation": 0,
                "test_rounds": 0,
                "sweep_runs": 0,
                "gate_sweep": None,
                "rulings_reported": [],
                "consult_seq": 0,
                "in_flight": None,
                "bailouts": [],
                "appended_phases": [],
                "history": [],
            }
        (self.slice_dir / "bailout.json").unlink(missing_ok=True)

        # A resume re-enters the stage the bail left off in rather than
        # replaying the consult→test ladder from the top.
        resume_at = self.state.get("run_phase") if self.resume else None

        try:
            # Forced here, inside the try: everything downstream reads it, and
            # a bail handler must never be the first thing to touch it.
            self.log(f"project config: {self.cfg.path}")
            self.project_dirs = load_project_dirs(self.repo_root)
            self._assert_agents()
            # Which repos are shared is asked here, before anything else
            # needs it, and recorded with the state. The primary repo may
            # not be one: its tree is where the gate, the dev services and
            # the doc phase's branch live, and those are this environment's.
            if self._is_shared(self.repo_root):
                raise Bailout(
                    "protocol_failure",
                    details=f"{self.repo_root} is a shared repo (`kc env "
                            "describe`), and a shared primary repo is not "
                            "supported: the gate, the dev services and the "
                            "doc phase's branch work in the primary's own "
                            "tree, which must be this environment's checkout "
                            "— run the slice from an unshared code repo")
            if not self.resume:
                self.preflight()
            # On disk before the start is reported: the `wait` that follows
            # a detached start at once must find the run.
            if not self.state_path.exists():
                self._save_state()
            # The start point: every refusal is behind it. A detached driver
            # reports here, and its parent hands the caller back the run.
            if self.on_start is not None:
                self.on_start()
            if not self.resume:
                self._base_branch(self.repo_root)
            # After preflight and the base, so the relaunch this bail asks
            # for is an ordinary --resume.
            self._assert_current()
            self._ensure_report()
            # The report exists from here, and nothing is dispatched yet —
            # on a fresh run and on every resume alike. A resume enters the
            # earlier stops at its first dispatch, not here, while the spec
            # tree still stands on its base (`_report_bailouts`).
            assert_no_prerun_actions(self.slice_dir)
            # Before the first dispatch, fresh and resumed alike: a repo
            # whose manifest calls a tool container this pod lacks, or a host
            # whose environment config declares a service it does not run, is
            # a restart only the operator can make.
            self._assert_tools()
            self._assert_services()
            # Then those repos' installs, so a gate fails on the change, not
            # on install state.
            self._setup_targets()

            if resume_at != "docs":
                while True:
                    self._run_phases()
                    if resume_at != "test" and self._completion_consult():
                        resume_at = None
                        continue
                    resume_at = None
                    if self._test_phase_under_lock():
                        continue
                    break
                # Test-complete: the verification is over and so is the hold.
                # The doc phase's writer and gate run without it; the landing
                # takes it again for the push.
                self.devlock.release(self.log)
                self._settle_push()
            self._doc_phase()
        except Bailout as bail:
            self.devlock.release(self.log)
            self._restore_bases()
            self._bail(bail)
        except KeyboardInterrupt:
            # No branch restoring here: the in-flight session may be
            # reattached on resume, and it needs the worktree it was left on.
            self.devlock.release(self.log)
            self.log("interrupted — state.json is current; resume with "
                     "--resume")
            print("Interrupted — resume with --resume (the in-flight session "
                  "will be reattached).", file=sys.stderr)
            sys.exit(130)

        self.state["run_phase"] = "done"
        self._save_state()
        # A resume that completed without dispatching anything enters its
        # stops here, with the tree on its base and the run over.
        with self._report_logged():
            self._report_bailouts()
            self._stamp_report()
        self._summary()
        sys.exit(0)

    def _ensure_report(self) -> None:
        """The report exists from here on — its store and the close-out.md
        rendered from it, created and committed by the driver when the plan
        loop left none (a slice planned before the report existed), or the
        store imported from a close-out.md written before the store existed
        and committed beside it. Idempotent, so a resume picks one up
        mid-run rather than running without."""
        # Asserted before the store is written, not before the commit: a
        # report created onto the wrong branch and bailed on would be found
        # by the resume and never committed at all.
        self._assert_spec_on_base()
        store = store_path(self.slice_dir)
        had_store = store.exists()
        try:
            created = init_report(self.slice_dir)
        except ReportError as e:
            raise Bailout("protocol_failure", details=str(e)) from None
        if created or (not had_store and store.exists()):
            self.specs_git("add", str(store), str(self.report_path))
            self.specs_git("commit", "-m",
                           f"slice {self.slice_num}: close-out report")
            self.log(f"{'created' if created else 'imported'} "
                     f"{store.name} beside {self.report_path.name}")

    def _report_bailouts(self) -> None:
        """Every stop of this run becomes an event entry, written by the
        resume that follows it, at its first dispatch (`_spawn`) — the
        first moment the report exists and the stop is known to be over; it
        is committed before that dispatch (`_commit_own_entries`). A resume
        that dispatches nothing writes it at completion.

        A stop the report did not carry left its Events saying the run
        recorded no bail-out beneath a header counting one. Each `bailouts`
        row is marked `reported` once its entry is in, so a stop is written
        exactly once across any number of resumes and every later call
        costs one list filter; a row whose entry could not be written is
        tried again next time."""
        rows = [row for row in self.state.get("bailouts") or []
                if isinstance(row, dict) and not row.get("reported")]
        for row in rows:
            phase = row.get("phase")
            where = (f"in P{phase}" if phase else
                     BAIL_STAGES.get(row.get("run_phase"), "outside any phase"))
            question = bool(row.get("question"))
            headline = (f"Run paused for an operator question {where}"
                        if question else
                        f"Run stopped ({row.get('reason')}) {where}")
            details = str(row.get("details") or "").strip()
            if details:
                quoted = "\n".join(f"> {line}" if line.strip() else ">"
                                   for line in details.splitlines())
                said = ("The question, as the driver recorded it:"
                        if question else
                        f"The driver's bail (`{row.get('reason')}`), as it "
                        "recorded it:") + "\n\n" + quoted
            else:
                said = ("The bail record predates the details it keeps now; "
                        "the stop is in full in log.txt.")
            stopped = str(row.get("ts") or "?")[:16].replace("T", " ")
            resumed = _now_iso()[:16].replace("T", " ")
            eid = self._report(
                "Notable events", headline,
                f"{said}\n\nStopped {stopped}; resumed {resumed}.",
                consequence=("none the loop acts on — the answer was in "
                             "before the run resumed where it paused; "
                             "recorded so the report accounts for every stop "
                             "the run header counts." if question else
                             "none the loop acts on — what the stop needed "
                             "was settled outside the run before it resumed "
                             "where it stopped; recorded so the report "
                             "accounts for every stop the run header "
                             "counts."),
                provenance="witnessed — the driver's bail record in "
                           "state.json")
            if eid is not None:
                row["reported"] = True
                self._save_state()

    def _render_report(self) -> None:
        """close-out.md rendered from the store — before the doc phase, at
        every bail and at completion. Idempotent, and never a failure: a
        report an agent broke is logged, the run goes on — save, mid-run,
        an operator's edit the render would drop (`_report_refused`)."""
        try:
            self.log("close-out rendered: " + render_report(self.slice_dir))
        except ReportError as e:
            self._report_refused(e)
            self.log(f"close-out not rendered: {e}")

    def _stamp_report(self) -> None:
        """Render, then the run header from the completed state;
        /dev:run-slice re-stamps once the cost block has landed. Never a
        failure — the run is done whatever the report's state."""
        self._render_report()
        try:
            self.log(stamp_header(self.slice_dir))
        except ReportError as e:
            self.log(f"close-out header not stamped: {e}")

    def _test_phase_under_lock(self) -> bool:
        """The test phase under the devlock, when the project runs one. The
        lock is NOT released between a findings-loop re-entry and the next
        test round — the slice keeps its occupancy while it converges."""
        if not self.cfg.test_phase:
            return False
        # Re-checked here, before the lock, so a consult's commits (the
        # mechanical-residue rider) never let the test phase read a report
        # about a tree that no longer exists — and the sweep's minute is
        # spent outside the hold.
        self._ensure_gate_sweep()
        self._acquire_devlock("test phase")
        return self._test_phase()

    def _acquire_devlock(self, purpose: str) -> None:
        """Idempotent — a caller that finds it held keeps it. The test phase
        takes it for the verification (`_test_phase_under_lock`) and the doc
        landing for its pushes (`_land_doc_branch`, `_push_doc_siblings`);
        each releases its own — the doc landing's once its last push is
        out."""
        if self.devlock.held:
            return
        self.announce(f"acquiring devlock ({purpose})")
        self.devlock.acquire(f"slice {self.slice_num} {purpose}",
                             self.log, self._sleep)

    def _settle_push(self) -> None:
        """The driver's push, for a project that runs no test phase.

        Nothing in the driver pushes a code phase — `_run_phase` ff-merges
        into the base locally, primary repo and siblings alike — so with a
        test phase the push is that phase's, per its procedure doc, and
        `_assert_pushed` is the check that it happened. A project with no
        test phase has no other pusher: without this its siblings never reach
        origin, and if it runs no doc phase either the slice ends with every
        commit still in the pod. The plan's `## Push holds` bind the driver
        exactly as they bind the test phase — a held repo is reported, not
        pushed."""
        if self.cfg.test_phase:
            return
        if not self._push_on():
            self.log("the project does not push — the slice's commits stay "
                     "local")
            return
        held_why = self._held_roots()
        for root, base in self._touched_roots():
            why = held_why.get(str(root))
            if why is not None:
                self._report_hold(root, why)
                continue
            self.git("push", "origin", base, root=root)
            self.log(f"pushed {base} in {root}")

    def _bail(self, bail: Bailout) -> None:
        # `run_phase` is left at the stage the run stopped in — that is what
        # `--resume` re-enters in `_run`, instead of replaying the phases →
        # consult → test ladder from the top. The stop itself is on record
        # in `bailouts` and in bailout.json.
        # bailout.json is unlinked on resume; the count lives here so the
        # close-out header can say how often the run stopped, and the details
        # with the stage so the resume can write the stop into the report
        # (`_report_bailouts`).
        self.state.setdefault("bailouts", []).append(
            {"reason": bail.reason, "phase": bail.phase,
             "question": bail.question, "ts": _now_iso(),
             "run_phase": self.state.get("run_phase"),
             "details": _clip(bail.details, BAIL_DETAILS_CAP)})
        self._save_state()
        payload = {
            "reason": bail.reason,
            "phase": bail.phase,
            "details": bail.details,
            "consult": bail.consult,
            "question": bail.question,
            "ts": _now_iso(),
        }
        with open(self.slice_dir / "bailout.json", "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        # After bailout.json, so the header names the stage the run stopped
        # in. The rendered files are left as they are — a bail commits
        # nothing — and nothing here may mask the bail or change its code.
        try:
            with self._report_logged():
                self._render_report()
        except Exception as e:
            why = e.details if isinstance(e, Bailout) else str(e)
            self.log(f"close-out not rendered: {why}")
        kind = "OPERATOR QUESTION" if bail.question else "BAIL-OUT"
        self.log(f"{kind} ({bail.reason}): {bail.details[:300]}")
        self.log(f"wrote {self.slice_dir / 'bailout.json'}; "
                 "resume with --resume after resolving")
        print(f"{kind} ({bail.reason}) — see "
              f"{self.slice_dir / 'bailout.json'}", file=sys.stderr)
        sys.exit(4 if bail.question else 3)

    def _summary(self) -> None:
        phases = self.state["phases"]
        try:
            report = "close-out report: " + counts_line(
                entry_counts(self.slice_dir))
        except ReportError:
            report = "close-out report missing"
        lines = [f"slice {self.slice_name} complete: "
                 f"{len(phases)} phase(s) merged, "
                 f"{self.state.get('test_rounds', 0)} test round(s), "
                 + report]
        for pid, ps in phases.items():
            lines.append(
                f"  P{pid}: executor×{ps['executor_rounds']} "
                f"gate×{ps.get('gate_runs', 0)} "
                f"review×{ps['review_rounds']}")
        for line in lines:
            self.log(line)
        self.announce(lines[0])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve()

# The detached driver's control records on the handshake pipe, after
# whatever it wrote to stderr: started (its pid) or the code it exited with
# before it got there. NUL-led, so no message a refusal prints can be one.
DETACH_MARK = b"\0run_loop: "


def detach(body, log_path: Path) -> tuple[int | None, int, str]:
    """Run `body(started)` in a detached grandchild — double fork, its own
    session, stdin and stdout on /dev/null — and return in the parent
    (pid, 0, text) once it has called `started()`, or (None, code, text)
    when it exited before that. `text` is what it wrote to stderr until
    then: until `started()` its stderr is the handshake pipe, so a refusal
    reaches the caller as it does an attached run; after it, stderr is
    log.txt, appended to, so no traceback is lost. The grandchild never
    returns into the caller's stack."""
    sys.stdout.flush()
    sys.stderr.flush()
    read_fd, write_fd = os.pipe()
    first = os.fork()
    if first == 0:
        try:
            os.close(read_fd)
            os.setsid()
            if os.fork() == 0:
                _detached_child(body, log_path, write_fd)
        finally:
            os._exit(0)
    os.close(write_fd)
    data = b""
    with os.fdopen(read_fd, "rb") as pipe:
        while True:
            chunk = pipe.read1(65536)
            if not chunk:
                break
            data += chunk
            mark = data.find(DETACH_MARK)
            if mark >= 0 and b"\n" in data[mark:]:
                break
    os.waitpid(first, 0)
    mark = data.find(DETACH_MARK)
    if mark < 0:
        return None, 1, (data.decode(errors="replace")
                         + "Error: the detached driver died before it "
                           "started\n")
    text = data[:mark].decode(errors="replace")
    verb, _, value = data[mark + len(DETACH_MARK):].decode(
        errors="replace").partition(" ")
    if verb == "started":
        return int(value), 0, text
    return None, int(value), text


def _detached_child(body, log_path: Path, pipe_fd: int) -> None:
    # A shell's background job may start with SIGINT ignored, and a driver
    # that ignores it is one `stop` cannot interrupt.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 1)
    os.dup2(pipe_fd, 2)
    os.close(null)
    # Fresh writers on fds 1 and 2: whatever sys.stdout and sys.stderr were
    # in the parent (a test runner's capture), the driver's are these.
    sys.stdout = open(1, "w", buffering=1, closefd=False)
    sys.stderr = open(2, "w", buffering=1, closefd=False,
                      errors="backslashreplace")
    started = False

    def start() -> None:
        nonlocal started
        sys.stderr.flush()
        os.write(pipe_fd, DETACH_MARK + f"started {os.getpid()}\n".encode())
        log = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log, 2)
        os.close(log)
        os.close(pipe_fd)
        started = True

    try:
        body(start)
        code = 0
    except SystemExit as e:
        if e.code is not None and not isinstance(e.code, int):
            print(e.code, file=sys.stderr)
        code = _exit_status(e)
    except BaseException as e:
        traceback.print_exc()
        code = _exit_status(e)
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    if not started:
        os.write(pipe_fd, DETACH_MARK + f"exit {code}\n".encode())
    os._exit(code)


def cmd_run(args) -> None:
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}",
              file=sys.stderr)
        sys.exit(2)
    if args.detach and args.dry_run:
        print("Error: --detach and --dry-run do not combine — a dry run "
              "dispatches nothing and is over in seconds.", file=sys.stderr)
        sys.exit(2)
    loop = RunLoop(slice_dir, resume=args.resume, verbose=args.verbose)
    if args.dry_run:
        cmd_dry_run(loop)
        return
    print(f"run loop log: {loop.log_path}", flush=True)
    if args.detach:
        run_detached(loop, Path(args.slice_dir))
        return
    loop.run()


def run_detached(loop: RunLoop, slice_arg: Path) -> None:
    """`run --detach`: the driver goes on in its own session, and this
    process says how to wait on it. `--from` is log.txt's end before the
    driver wrote to it, so the first `wait` reports the run from its first
    line."""
    offset = _file_size(loop.log_path)

    def body(started) -> None:
        loop.on_start = started
        loop.run()

    pid, code, text = detach(body, loop.log_path)
    if text:
        sys.stderr.write(text)
        sys.stderr.flush()
    if pid is None:
        sys.exit(code)
    print(f"driver detached: pid {pid} — it outlives this shell; "
          f"`{SCRIPT.name} stop` interrupts it", flush=True)
    print(f"next: python3 {SCRIPT} wait {os.path.abspath(slice_arg)} "
          f"--from {offset}", flush=True)


# `wait` — what the launching session re-arms on. Its cadence sits under the
# harness's 3 600 000 ms timeout on the call, so it always exits by itself.
WAIT_DEFAULT = 3300
WAIT_POLL = 10              # seconds between lock probes
WAIT_RUNNING = 5            # wait's own exit codes, not the run's
WAIT_KILLED = 6
WAIT_LOG_LINES = 40         # the driver lines a check shows at most
WAIT_LINE_CHARS = 200
NARRATION_TAIL = 256 * 1024     # how far back to look for the agent's words
TRANSCRIPT_LINE_RE = re.compile(r"\] session \S+ — transcript ")
SESSION_START_RE = re.compile(r"\] session starting(?: \(resume\))?$")
NARRATION_MARK = "] [text] "
STOP_WAIT = 120
STOP_POLL = 1


def _span(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


def _age(iso: str | None) -> float | None:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.astimezone()
    return (datetime.now().astimezone() - then).total_seconds()


def log_digest(log_path: Path, offset: int) -> tuple[list[str], int]:
    """The driver's own lines in log.txt from byte `offset`, and the offset
    read up to. Agent activity (indented) and the transcript locators are
    left out, each line is clipped, and only the last WAIT_LOG_LINES are
    kept. Complete lines only: a line still being written is the next
    check's. An offset past the end means the log was rewritten under it,
    and reading starts over."""
    try:
        with open(log_path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if offset > size:
                offset = 0
            f.seek(offset)
            data = f.read(size - offset)
    except OSError:
        return [], 0
    end = data.rfind(b"\n") + 1
    lines = [_clip(line, WAIT_LINE_CHARS)
             for line in data[:end].decode(errors="replace").splitlines()
             if line.strip() and not line[0].isspace()
             and not TRANSCRIPT_LINE_RE.search(line)]
    if len(lines) > WAIT_LOG_LINES:
        omitted = len(lines) - WAIT_LOG_LINES
        lines = [f"({omitted} earlier lines omitted)"] + lines[-WAIT_LOG_LINES:]
    return lines, offset + end


def latest_narration(log_path: Path, upto: int) -> str | None:
    """The in-flight session's latest words — its last `[text]` activity
    line before `upto`, looking no further back than the session's start."""
    try:
        with open(log_path, "rb") as f:
            start = max(upto - NARRATION_TAIL, 0)
            f.seek(start)
            data = f.read(upto - start)
    except OSError:
        return None
    for line in reversed(data.decode(errors="replace").splitlines()):
        if line[:1].isspace():
            if NARRATION_MARK in line:
                return line.split(NARRATION_MARK, 1)[1]
        elif SESSION_START_RE.search(line):
            break
    return None


def _running_line(state: dict, log_path: Path) -> str:
    parts = [state.get("run_phase") or "?"]
    flight = state.get("in_flight") or {}
    where = []
    pid = flight.get("phase")
    if pid:
        where.append(f"P{pid}")
        stage = (state.get("phases", {}).get(pid) or {}).get("stage")
        if stage:
            where.append(stage)
    if flight.get("round"):
        where.append(f"r{flight['round']}")
    if where:
        parts.append(" ".join(where))
    role = flight.get("role")
    if role:
        seg = f"{role} in flight"
        age = _age(flight.get("started_at"))
        if age is not None:
            seg += f" {_span(age)}"
        if role in TIMEOUTS:
            seg += f" (cap {_span(TIMEOUTS[role])})"
        parts.append(seg)
    with contextlib.suppress(OSError):
        parts.append("last log line "
                     f"{_span(time.time() - log_path.stat().st_mtime)} ago")
    return "running: " + " · ".join(parts)


def _ended_lines(code: int, slice_dir: Path) -> list[str]:
    lines = [f"ended: exit {code}"]
    if code not in (3, 4):
        return lines
    bail = _read_json(slice_dir / "bailout.json") or {}
    lines.append(f"reason: {bail.get('reason')}"
                 + (f" (P{bail['phase']})" if bail.get("phase") else ""))
    if bail.get("question"):
        lines.append(f"question: {bail['question']}")
    if bail.get("details"):
        lines.append("details: " + "\n  ".join(
            str(bail["details"]).splitlines()))
    return lines


def cmd_wait(args) -> None:
    """Block until the run ends or `--for` seconds pass, then report it:
    a status line, the driver's log lines since `--from`, the in-flight
    session's latest words, and the next command."""
    slice_dir = Path(args.slice_dir)
    state_path = slice_dir / "state.json"
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}",
              file=sys.stderr)
        sys.exit(2)
    if not state_path.exists():
        print(f"Error: {state_path} does not exist — the run never started",
              file=sys.stderr)
        sys.exit(2)
    lock_path = slice_dir / "run.lock"
    log_path = slice_dir / "log.txt"
    offset = (args.from_offset if args.from_offset is not None
              else _file_size(log_path))
    deadline = time.monotonic() + args.for_seconds
    while lock_held(lock_path):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(WAIT_POLL, remaining))

    alive = lock_held(lock_path)
    state = _read_json(state_path) or {}
    record = state.get("exit")
    if alive:
        code, lines = WAIT_RUNNING, [_running_line(state, log_path)]
    elif record is not None:
        code, lines = 0, _ended_lines(record.get("code"), slice_dir)
    else:
        code = WAIT_KILLED
        lines = ["killed: the driver is gone and left no exit record"]
        note = holder_note(lock_path) or "(no holder note)"
        lines += [f"  {line}" for line in note.splitlines()]
    digest, read_to = log_digest(log_path, offset)
    lines += digest
    flight = state.get("in_flight") or {}
    if alive and flight.get("role"):
        words = latest_narration(log_path, read_to)
        if words:
            lines.append(_clip(f"latest from {flight['role']}: {words}",
                               WAIT_LINE_CHARS))
    where = os.path.abspath(slice_dir)
    if code == WAIT_RUNNING:
        lines.append(f"next: python3 {SCRIPT} wait {where} --from {read_to}")
    elif code == WAIT_KILLED:
        lines.append(f"next: python3 {SCRIPT} run {where} --resume --detach")
    print("\n".join(lines), flush=True)
    sys.exit(code)


def cmd_stop(args) -> None:
    """SIGINT the slice's driver — its KeyboardInterrupt path: leases given
    back, state current, the in-flight session left for the resume to
    reattach, exit 130 — and wait for it to let the lock go. Only the
    driver's own pid: the session it runs is the resume's to pick up."""
    slice_dir = Path(args.slice_dir)
    lock_path = slice_dir / "run.lock"
    if not lock_held(lock_path):
        print(f"no driver is running {slice_dir}: {lock_path.name} is free")
        sys.exit(1)
    fields = note_fields(holder_note(lock_path))
    here = socket.gethostname()
    if fields.get("host") != here:
        env = fields.get("environment")
        where = f" (environment {env})" if env and env != "(unset)" else ""
        print(f"Error: the driver holding {lock_path} runs on host "
              f"{fields.get('host') or '(unknown)'}{where}, not on {here} — "
              "its pid means nothing here.", file=sys.stderr)
        sys.exit(2)
    try:
        pid = int(fields.get("pid", ""))
    except ValueError:
        print(f"Error: {lock_path} names no driver pid.", file=sys.stderr)
        sys.exit(2)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        print(f"Error: pid {pid} from {lock_path} is not running, yet the "
              "lock is held.", file=sys.stderr)
        sys.exit(1)
    print(f"sent SIGINT to the driver (pid {pid}); waiting up to "
          f"{STOP_WAIT}s for it to stop", flush=True)
    deadline = time.monotonic() + STOP_WAIT
    while lock_held(lock_path):
        if time.monotonic() >= deadline:
            print(f"the driver (pid {pid}) still holds {lock_path.name} "
                  f"after {STOP_WAIT}s")
            sys.exit(1)
        time.sleep(STOP_POLL)
    record = (_read_json(slice_dir / "state.json") or {}).get("exit")
    if record is None:
        print("stopped, but it left no exit record")
    else:
        print(f"stopped: exit {record.get('code')}")
    sys.exit(0)


def code_repos_for(spec_root: Path) -> list[Path]:
    """The code repos a spec repo serves: the git checkouts beside it that
    carry a kc manifest and whose `.aiworkflowrc` names it as `spec_repo`.
    A repo whose config does not load is not one — preflight would refuse
    to drive it anyway."""
    spec = spec_root.resolve()
    found = []
    for d in sorted(spec.parent.iterdir()):
        if not d.is_dir() or d.resolve() == spec \
                or not (d / ".git").exists() \
                or not (d / ".kubecoder" / "project.yaml").is_file():
            continue
        try:
            cfg = project_config.load(d)
        except project_config.ConfigError:
            continue
        if cfg.spec_repo is not None and cfg.spec_repo.resolve() == spec:
            found.append(d)
    return found


def _dry_run_code_repo(loop: RunLoop) -> None:
    """Re-root a dry run started outside the code repo — typically in the
    spec repo, where /dev:plan-slice leaves its session — on the code repo
    the slice belongs to, so its Targets resolve where the run will resolve
    them. Only the dry run does this: a run is started from the code repo,
    and preflight holds it to that. Where no code repo names the slice's
    spec repo, or several do, the dry run stops with that one instruction
    rather than reporting every component Target of a valid plan as a
    problem."""
    here = loop.repo_root
    if (here / ".kubecoder" / "project.yaml").is_file():
        return
    spec_root = spec_root_for(loop.slice_dir)
    found = code_repos_for(spec_root) if spec_root is not None else []
    if len(found) == 1:
        loop.reroot(found[0])
        print(f"targets resolve in {found[0]}: {here} holds no "
              f".kubecoder/project.yaml, and {found[0].name} is the one code "
              f"repo whose .aiworkflowrc names {spec_root} as spec_repo")
        return
    if found:
        why = (f"{len(found)} code repos name {spec_root} as their spec_repo "
               "(" + ", ".join(str(d) for d in found) + ")")
    elif spec_root is not None:
        why = (f"no code repo beside {spec_root} (a checkout with a kc "
               "manifest) names it as spec_repo in its .aiworkflowrc")
    else:
        why = f"{loop.slice_dir} is not inside a spec repo's slices/ tree"
    print(f"Error: {here} holds no .kubecoder/project.yaml, and {why} — run "
          "from the code repo that holds .kubecoder/project.yaml",
          file=sys.stderr)
    sys.exit(2)


def cmd_dry_run(loop: RunLoop) -> None:
    """Parse the plan and resolve every target — no sessions, no branches.
    Exit 0 when the plan is drivable, 2 with the problems otherwise."""
    if not loop.plan_path.is_file():
        print(f"Error: {loop.plan_path} does not exist.", file=sys.stderr)
        sys.exit(2)
    # A dry run keeps no log of its own: what resolution logs (a sibling kc
    # could not list) is a warning here, and never lands in log.txt; one
    # worded as a warning already keeps its one prefix.
    loop.log = lambda msg: print(f"warning: {msg.removeprefix('warning: ')}",
                                 file=sys.stderr)
    _dry_run_code_repo(loop)
    phases, errors = parse_plan(loop.plan_path.read_text())
    try:
        loop.project_dirs = load_project_dirs(loop.repo_root)
    except Bailout as e:
        print(f"warning: {e.details} — component targets unvalidated",
              file=sys.stderr)
    print(f"slice {loop.slice_name}: {len(phases)} phase(s)")
    # Each pending phase's resolved repo root, filled in document order — so
    # every pending phase at or before the one being printed is in it when
    # `manifest_claimer` looks, and nothing resolves (or clones) twice.
    roots: dict[str, Path | None] = {}
    for index, phase in enumerate(phases):
        line = f"  P{phase.id}  {'DONE ' if phase.done else ''}{phase.title}"
        if phase.done:
            print(line)
            continue
        roots[phase.target or ""] = None
        try:
            target = loop._resolve_target(phase.target or "")
            roots[phase.target or ""] = target.git_root
            claimer = None
            if target.gate_argv is None and is_repo_path(target.name):
                claimer = manifest_claimer(phases, index, roots.get)
            if target.gate_argv:
                gate = " ".join(target.gate_argv)
            elif claimer is not None:
                gate = (f"{' '.join(REPO_GATE_ARGV)} (gated once "
                        f"P{claimer.id} adds the manifest)")
            else:
                gate = "(no deterministic gate)"
            if loop._is_root(target):
                gate += f" (else {' '.join(REPO_GATE_ARGV)} when it runs nothing)"
            print(f"{line}\n        target={target.name} [{target.kind}]  "
                  f"root={target.git_root}  gate: {gate}")
            problem = loop._github_gate_problem(
                target, claimed=claimer is not None)
            if problem:
                errors.append(f"phase P{phase.id}: {problem}")
        except ValueError as e:
            # A name the plan says a phase still has to create is not a bad
            # Target — the dry run reads the plan before anything has run, so
            # `kc project list` cannot know it yet. Resolution stays strict
            # (no root, no gate to print); the note says who creates it.
            creator, false_claim = creation_claim(phases, index)
            if creator is not None:
                print(f"{line}\n        target={phase.target} [project]  "
                      f"(created by P{creator.id})")
                continue
            errors.append(f"phase P{phase.id}: {false_claim or e}")
            print(f"{line}\n        target=INVALID")
    holds, hold_errors = parse_push_holds(loop.plan_path.read_text())
    errors.extend(hold_errors)
    for target, why in holds:
        try:
            root = loop._resolve_target(target, held=True).git_root
            print(f"  hold  {target}  root={root}  not pushed: {why}")
        except ValueError as e:
            errors.append(f"push hold `{target}`: {e}")
            print(f"  hold  {target}  INVALID")
    # Reported, not a plan problem: a born-planned slice has no report, and
    # the dry run's verdict is on the plan alone.
    for eid, headline in open_prerun_actions(loop.slice_dir):
        print(f"  pre-run  {eid}  open — a real run stops on it until struck: "
              f"{headline}")
    rulings, ruling_errors = parse_rulings(loop.plan_path.read_text())
    errors.extend(ruling_errors)
    for ruling in rulings:
        detail = {"gate": f"gate waived, substitute: {ruling.substitute_text}",
                  "accept": f"red {ruling.verb} accepted",
                  "prd": "prd authorized"}[ruling.kind]
        try:
            root = loop._resolve_target(ruling.target).git_root
            print(f"  ruling  {ruling.key}  root={root}  {detail}: "
                  f"{ruling.why}")
        except ValueError as e:
            errors.append(f"driver ruling `{ruling.key}`: {e}")
            print(f"  ruling  {ruling.key}  INVALID: {e}")
    for missing in (loop._missing_tools(), loop._missing_services()):
        if missing:
            errors.append(missing.replace("\n", "\n    "))
    if errors:
        print("\nplan problems:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "state.json")
    if not state:
        print("no state.json — the run loop has not started this slice")
        return
    # bailout.json is unlinked at the start of every run, so one present
    # means this run stopped in the stage run_phase names.
    bailed = " (bailed)" if (slice_dir / "bailout.json").exists() else ""
    print(f"slice {state['slice']}  run_phase={state['run_phase']}{bailed}  "
          f"generation={state.get('generation', 0)}  "
          f"bail-outs={len(state.get('bailouts', []))}")
    print(f"  {driver_line(state.get('driver'), slice_dir / 'run.lock')}")
    for pid in state.get("known_phases", []):
        ps = state.get("phases", {}).get(pid)
        if not ps:
            print(f"  P{pid}: pending")
            continue
        print(f"  P{pid}: {ps['status']}"
              + (f" (stage {ps['stage']})" if ps.get("stage") else "")
              + f"  executor×{ps['executor_rounds']} "
                f"gate×{ps.get('gate_runs', 0)} "
                f"review×{ps['review_rounds']}")
    for h in state.get("history", [])[-8:]:
        print(f"  {h['ts']}  {('P' + h['phase']) if h.get('phase') else '-'}"
              f"  {h['role']} r{h['round']} → {h['outcome']}")


def _tee_exec(argv: list[str], cwd: Path) -> tuple[int, str]:
    """One gate command run from `cwd`, its stdout and stderr passed
    through to ours as they come and kept: (its exit code, its output) —
    the seam the `gate` wrapper runs its commands through, isolated for
    tests. No timeout: the session running the wrapper owns its clock."""
    sys.stdout.flush()
    out = sys.stdout.buffer
    kept = bytearray()
    with subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as proc:
        while chunk := proc.stdout.read1(65536):
            out.write(chunk)
            out.flush()
            kept += chunk
        returncode = proc.wait()
    return returncode, kept.decode(errors="replace")


def run_writer_gate(spec_path: Path) -> int:
    """The `gate` subcommand: the phase gate as the driver runs it
    (`RunLoop._run_gate`), from the spec the driver wrote for this
    code-writer round (`RunLoop._write_gate_spec`) — the Target's command,
    the whole repo when an empty root ran nothing, then each component the
    phase's diff touches that no gate ruling waives — its output passed
    through as it runs, and the run recorded beside the spec for the driver
    to reuse (`RunLoop._reusable_writer_gate`). The exit code is the gate's:
    0 green, 1 red, 3 nothing ran; 2 is no run at all.

    The touched components are the diff from the review's merge base to the
    tree as it is when the run begins — committed or not, as the gate sees
    it, where `<merge_base>..HEAD` would miss what the writer has yet to
    commit. The tree is hashed (`content_tree`) before the first command and
    after the last, so the record says whether it changed while the run
    went on. A later run in the same round replaces the record: the driver
    takes the last one or none."""
    try:
        spec = json.loads(Path(spec_path).read_text())
    except (OSError, ValueError) as e:
        print(f"gate: cannot read the gate spec {spec_path}: {e}",
              file=sys.stderr)
        return 2
    problem = gate_spec_problem(spec)
    if problem:
        print(f"gate: {spec_path} is not a gate spec: {problem}",
              file=sys.stderr)
        return 2
    work_root, gate_cwd = Path(spec["work_root"]), Path(spec["gate_cwd"])
    touched = spec.get("touched")
    started = _now_iso()
    try:
        start = content_tree(work_root)
        components: list[str] = []
        uncovered = False
        if touched is not None:
            changed = _git_in(work_root, "diff", "--name-only",
                              "--no-renames", touched["merge_base"], start)
            components, uncovered = touched_components(
                load_project_dirs(gate_cwd), work_root, changed,
                touched["target"])
    except ValueError as e:
        print(f"gate: {e}", file=sys.stderr)
        return 2
    except Bailout as e:
        print(f"gate: {e.details}", file=sys.stderr)
        return 2

    commands: list[dict] = []
    outcomes: list[tuple[str, str]] = []   # (command, outcome)

    def run(argv: list[str], header: str) -> str:
        print(header, flush=True)
        returncode, output = _tee_exec(argv, gate_cwd)
        commands.append({"argv": list(argv), "rc": returncode,
                         "output": output})
        return kc_outcome(returncode)

    argv = spec["argv"]
    own, outcome = argv, run(argv, f"=== `{' '.join(argv)}` from "
                                   f"{gate_cwd} ===")
    if spec.get("fallback") and outcome == "nothing_ran":
        own = spec["fallback"]
        outcome = run(own, f"\n=== `{' '.join(argv)}` ran nothing (exit 3) — "
                           f"the gate is the whole repo: `{' '.join(own)}` "
                           "===")
    outcomes.append((" ".join(own), outcome))
    for component in components:
        component_argv = component_gate_argv(component)
        cmd = " ".join(component_argv)
        if component in touched["waived"]:
            print(f"\n=== the phase's diff touches {component}: `{cmd}` "
                  "waived by plan.md's `## Driver rulings` — not run ===",
                  flush=True)
            continue
        outcomes.append((cmd, run(component_argv, "\n=== the phase's diff "
                                  f"touches {component}: `{cmd}` ===")))
    if uncovered:
        print("\n=== the phase's diff touches files outside every component "
              "and kc lists no root — no gate covers them ===", flush=True)
    try:
        end = content_tree(work_root)
    except ValueError as e:
        # no tree to vouch for: the record stands, and the driver gates
        print(f"gate: {e}", file=sys.stderr)
        end = ""
    labels = [o for _, o in outcomes]
    outcome = ("red" if "red" in labels
               else "green" if "green" in labels else "nothing_ran")
    record = Path(spec_path).parent / writer_gate_record_name(spec["round"])
    _write_json_atomic(record, {
        "phase": spec["phase"], "round": spec["round"],
        "work_root": spec["work_root"], "gate_cwd": spec["gate_cwd"],
        "start_tree": start, "end_tree": end,
        "started": started, "finished": _now_iso(),
        "commands": commands, "outcome": outcome})
    print(flush=True)
    if outcome == "green" and start == end:
        print(f"=== gate GREEN on tree {start[:12]}, recorded in {record}. "
              "Hand back this tree — committing it changes nothing — and the "
              "driver takes this run as its gate; edit anything first and it "
              "runs the gate again. ===")
    elif outcome == "green":
        print(f"=== gate GREEN, but the tree changed while it ran "
              f"({start[:12]} → {end[:12]}): the driver will run the gate "
              "again. Run this once more on the finished tree to spare it "
              "that. ===")
    elif outcome == "red":
        print("=== gate RED: "
              + _ticked([c for c, o in outcomes if o == "red"]) + " ===")
    else:
        print("=== gate: nothing ran (exit 3) — not red, nothing to fix ===")
    return {"green": 0, "red": 1}.get(outcome, KC_NOTHING_RAN)


def cmd_gate(args) -> None:
    sys.exit(run_writer_gate(Path(args.spec)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or resume) a slice")
    run_p.add_argument("slice_dir", help="path to slices/NNN_slug/")
    run_p.add_argument("--resume", action="store_true",
                       help="continue from state.json")
    run_p.add_argument("-v", "--verbose", action="store_true",
                       help="echo the log to stdout as well as log.txt")
    run_p.add_argument("--dry-run", action="store_true",
                       help="parse the plan, resolve targets, and exit")
    run_p.add_argument("--detach", action="store_true",
                       help="run the driver in its own session, outliving "
                            "this shell; exits once it started and prints "
                            "the `wait` command to follow it with")
    run_p.set_defaults(func=cmd_run)

    wait_p = sub.add_parser(
        "wait", help="wait on a slice's driver; exit 0 when the run ended, "
                     "5 still running at --for, 6 killed (no exit record)")
    wait_p.add_argument("slice_dir")
    wait_p.add_argument("--for", dest="for_seconds", type=float,
                        default=WAIT_DEFAULT, metavar="SECONDS",
                        help=f"give up waiting after this long "
                             f"(default {WAIT_DEFAULT})")
    wait_p.add_argument("--from", dest="from_offset", type=int,
                        metavar="OFFSET",
                        help="report log.txt from this byte (default: its "
                             "end when the wait starts)")
    wait_p.set_defaults(func=cmd_wait)

    stop_p = sub.add_parser(
        "stop", help="interrupt a slice's driver (SIGINT) and wait for it")
    stop_p.add_argument("slice_dir")
    stop_p.set_defaults(func=cmd_stop)

    status_p = sub.add_parser("status", help="print a slice's run state")
    status_p.add_argument("slice_dir")
    status_p.set_defaults(func=cmd_status)

    gate_p = sub.add_parser(
        "gate", help="run a phase's test gate as the driver does and record "
                     "the run for the driver; exit 0 green, 1 red, 3 nothing "
                     "ran, 2 no run")
    gate_p.add_argument("spec", help="the phase's gate_spec.json, as its "
                                     "code-writer dispatch names it")
    gate_p.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
