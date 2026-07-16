#!/usr/bin/env python3
"""Task runner — drives a slice's tasks through the bounded dev loop.

The runner is a state machine, not a judge (see
${CLAUDE_PLUGIN_ROOT}/docs/task-workflow.md — the canonical contract). Per task, in
order: branch → code-writer → gate + test-fixer loop (cap 3) → code-reviewer
loop (cap 3, extendable to 5) → ff-merge → checkpoint. The test gate is
deterministic and the runner runs it itself — detecting green needs no model,
only fixing red does. Judgment calls go to fresh consult sessions;
anything neither can resolve becomes a bail-out (bailout.json + exit 3) for
the /run-slice session to handle.

Every spawned agent must end by writing the verdict JSON file named in its
dispatch prompt and leave the worktree committed; a session that misses either
gets one resume-nudge, after which a missing verdict counts as `blocked` and
an uncommitted tree bails. The runner's own execution state lives in <slice>/state.json
(written atomically; the runner is its only writer) and doubles as the resume
point and the consult sessions' decision substrate.

All runner and session output goes to <slice>/log.txt (tail -f to watch);
stdout stays silent — one line naming the log file — unless -v/--verbose
echoes the log there too. The orchestrator reads outcomes from the exit code,
state.json, and bailout.json, never from the stream.

Usage:
    task_runner.py run <slice-dir> [--resume] [--verbose] [--dry-run]
    task_runner.py status <slice-dir>

Exit codes: 0 slice complete · 3 bailed (bailout.json written) ·
2 usage/precondition error · 1 unexpected error.
"""

import argparse
import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#
# This runner is kc-native (the `dev` plugin). The three project-specific seams
# that used to be hardcoded here are now kc calls:
#   - the valid project set + each project's effective cwd  → `kc project list
#     --output=json` (load_project_dirs), read from the target repo's
#     `.kubecoder/project.yaml`;
#   - per-round session drive  → `kc session create-headless|send|status|end`
#     (run_kc_session), replacing the retired claude_session.py;
#   - the repo root for git operations  → `git rev-parse --show-toplevel`
#     (the runner no longer lives inside the target repo, so it cannot derive
#     the root from its own path).
# The plugin's agents install as `dev:<role>`; the runner spawns them by that
# namespaced name (AGENT_NAMESPACE); consults spawn bare (no --agent).
# ---------------------------------------------------------------------------

AGENT_NAMESPACE = "dev"  # plugin name; installed agents resolve as dev:<role>

MODELS = {"test-fixer": "sonnet", "test-agent": "sonnet", "consult": "opus"}

TIMEOUTS = {
    "code-writer": 7200,
    "test-fixer": 3600,
    "code-reviewer": 3600,
    "test-agent": 7200,
    "consult": 1800,
}

# The deterministic per-task test gate: `kc project test --project <name>`,
# exit 0 = green. The runner runs it as a subprocess — no session is ever
# spawned just to learn the gate's color; the test-fixer exists only to make a
# red gate green again. What "test" means for a component is the operator's
# call, declared in the manifest's statements: a component that declares none
# (a docs-only project, say) is green by definition, and that is a valid
# answer, not a gap for the runner to second-guess.
GATE_TIMEOUT = 3600

TEST_ROUND_CAP = 3  # caps test-fixer rounds (state key: test_rounds)
# 3, not 2: at 2, a Major found in the final review round can only ever ship
# unreviewed — the writer's fix has no round left to land in, and the cap consult
# has no "one more round" option (slice 082: 4 of 11 tasks, every one a real
# defect whose fix a consult then had to hand-verify in the reviewer's place).
REVIEW_ROUND_CAP = 3
# The cap is a budget the consult may extend, not a wall: at the cap it can spend
# a round to CONFIRM a fix it judges close (mirroring the fix-round cap's valve).
# Bounds the extension so a writer/reviewer that never converges still terminates.
REVIEW_GRANT_CAP = 2
VERIFICATION_ROUND_CAP = 3
NUDGE_TIMEOUT = 900

# Ephemeral sessions must not pay the 1-hour cache-write premium.
SPAWN_ENV = {"FORCE_PROMPT_CACHING_5M": "1"}

VERDICTS = {
    "code-writer": {"done", "blocked", "missing-task"},
    "test-fixer": {"clean", "issues", "blocked"},
    "code-reviewer": {"signoff", "issues", "critical"},
    "test-agent": {"clean", "findings", "blocked"},
}


class Bailout(Exception):
    def __init__(self, reason: str, task: str | None = None,
                 details: str = "", consult: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.task = task
        self.details = details
        self.consult = consult


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _transcript_path(cwd: Path | str, session_id: str | None) -> str | None:
    """The Claude Code transcript file for a session spawned with this cwd:
    ~/.claude/projects/<munged-cwd>/<session-id>.jsonl (a session's sub-agents
    live next to it under <session-id>/subagents/). The munge mirrors Claude
    Code's project-dir encoding: every non-alphanumeric path character becomes
    '-'. Recorded in state.json so a later session can research any agent's
    conversation without reverse-engineering this mapping."""
    if not session_id:
        return None
    munged = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(cwd).resolve()))
    return str(Path.home() / ".claude" / "projects" / munged
               / f"{session_id}.jsonl")


# ---------------------------------------------------------------------------
# kc integration — project discovery, session drive, repo root
# ---------------------------------------------------------------------------


def _git_toplevel() -> Path:
    """The target repo's root, from `git rev-parse --show-toplevel` in the
    process cwd. The plugin's runner lives under ~/.claude, not inside the
    target repo, so the root can no longer be derived from __file__ — it is the
    git repo the runner was invoked in (run-slice runs it from the code repo)."""
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
    """The valid project set + each project's *effective* cwd, from the target
    repo's `.kubecoder/project.yaml` via `kc project list --output=json` (§6a).

    Replaces the old hardcoded PROJECT_DIRS: the cwd-resolution rule lives once,
    in kc (ResolveCwd), so the runner needs no YAML parser. The JSON is a bare
    array of {name, cwd, description} in manifest order; `cwd` is absolute and
    already resolved. An absent/malformed manifest is a loud non-zero from kc."""
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


class SessionResult:
    """The bit of a driven turn the runner consumes downstream: the claude
    sessionId (for --resume across rounds and the transcript locator). Mirrors
    the surface of the retired claude_session.StreamResult that callers read."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.result_text: str = ""
        self.is_error: bool = False


def _kc_session_id(name: str, cwd: Path) -> str | None:
    """The claude sessionId from the headless status snapshot. `sessionId` is
    empty until the first turn has run, so this is read *after* send."""
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


def _kc_send(name: str, prompt: str, cwd: Path, timeout: int, progress) -> int:
    """POST one turn to a headless session and consume its response to the
    terminal result (`kc session send` owns SSE reconnect). The condensed log
    (send's stderr under -v) streams to `progress`; the response text is
    discarded (the runner reads verdict files, never the turn text).

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
            proc.wait(timeout=30)
            return proc.returncode
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
    resume_session: str | None = None,
    extra_env: dict[str, str] | None = None,
    progress=None,
    on_session=None,
) -> tuple[int, SessionResult]:
    """Drive one headless kc session to completion; return (returncode, result).

    The kc-native replacement for the retired claude_session.run_claude, mapping
    each seam onto a kc verb:
      create-headless [--resume ID] [--agent dev:ROLE] [--model M] --cwd CWD
                      [-e NAME=VALUE ...]        → the assigned session name
      send NAME --prompt-file P --response-file R -v   (synchronous; SSE)
      status NAME --output=json                  → the claude sessionId
      end NAME                                    (idempotent; always)

    `agent` is the bare role (e.g. "code-writer"); it is namespaced to
    dev:<role> here. A falsy `agent` spawns bare (consults). `extra_env` is
    threaded as repeatable `-e NAME=VALUE` (prompt-caching parity). Raises
    subprocess.TimeoutExpired on timeout — the turn is interrupted and the
    session torn down before it propagates."""
    result = SessionResult()

    create_args = ["session", "create-headless", "--cwd", str(cwd)]
    if resume_session:
        create_args += ["--resume", resume_session]
    if agent:
        create_args += ["--agent", f"{AGENT_NAMESPACE}:{agent}"]
    if model:
        create_args += ["--model", model]
    for name, value in (extra_env or {}).items():
        create_args += ["-e", f"{name}={value}"]

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

    try:
        returncode = _kc_send(session_name, prompt, Path(cwd), timeout, progress)
        result.session_id = _kc_session_id(session_name, Path(cwd))
        if on_session and result.session_id:
            on_session(result.session_id)
        result.is_error = returncode != 0
        return returncode, result
    finally:
        # Best-effort teardown: never let cleanup hang the runner or mask the
        # exception that is propagating (e.g. a timeout).
        try:
            subprocess.run(
                ["kc", "session", "end", session_name],
                cwd=str(cwd), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# Dispatch prompts. Role contracts live in the agent definitions; prompts
# carry only instance data. Consults run bare, so their prompt is the protocol.
# ---------------------------------------------------------------------------

WRITER_PROMPT = """\
You are implementing task {task_id} of slice {slice_name}.
Task folder: {task_dir}

Read task.json and plan.md there, then implement the task in this project.
When done: commit all your work (code in this repo; task-folder artifacts in
the specs repo, staged by name). If the task produced prose that describes
system behavior, {task_dir}/grounding.md must be current (your contract has
the rule). Then write your verdict to {verdict_path}.
"""

WRITER_RETRY_NOTE = """\
A previous attempt at this task hit the fix-round limit. {prior_state}
Complete the task, and test your own work thoroughly before handing back —
the deterministic gate and the code-reviewer are the only checks after you.
"""

WRITER_FIX_PROMPT = """\
The test-fixer escalated gate failures it must not fix itself. Read
{results_path} and fix them. Commit your fixes, update grounding.md if any
behavioral claims changed, then write your verdict to {verdict_path}.
"""

WRITER_REVIEW_FIX_PROMPT = """\
The code-reviewer found issues with the task's branch. Read {review_path} and
resolve every finding (the reviewer describes problems; the fix design is
yours). Update the grounding.md entries your fixes touch — re-open the source
for each. Commit your fixes, then write your verdict to {verdict_path}.
"""

FIXER_PROMPT = """\
The test gate for task {task_id} of slice {slice_name} is red (branch
{branch}, fix round {round}). Task folder: {task_dir}

The gate command was `kc project test --project {project}`; its output is in
{gate_log}. The gate is fail-fast and terse, so the log ends at the FIRST
failing statement — there may be more behind it. Make the gate green: fix and
commit what is mechanical; escalate what is not by writing
{task_dir}/test_results_r{round}.md and reporting `issues`. The change under
test is git diff {merge_base}..HEAD.

Then write your verdict to {verdict_path}.
"""

REVIEWER_PROMPT = """\
Review the complete branch diff for task {task_id} of slice {slice_name}
(review round {round}): git diff {merge_base}..HEAD on branch {branch}.

The requirements are {slice_dir}/slice.md (the authoritative ask — a silent
substitution against it is a finding), {task_dir}/task.json,
{task_dir}/plan.md (the task's requirement decomposition and pinned
cross-task interfaces), and the relevant acceptance criteria in
{slice_dir}/acceptance_criteria.json. Judge outcomes, not approach: deviating
from the plan's approach while meeting the requirements is not a finding; a
missed planned edge behavior or a broken pinned interface is. The slice spans
multiple tasks — only this task's scope is under review.

When the task produced behavior-describing prose, {task_dir}/grounding.md is
the writer's claim→source ledger: verify the citations rather than re-deriving
every claim from scratch (your contract has the rule).

Write your review to {task_dir}/code_review_r{round}.md and your verdict to
{verdict_path}.
"""

TEST_AGENT_PROMPT = """\
Final verification for slice {slice_name} (round {round}). All tasks are merged
on {base_branch}.

Read {slice_dir}/acceptance_criteria.json and {slice_dir}/verification.json,
then run every affected project's full test suite (each project's CLAUDE.md and
docs state its commands). Verify what the criteria let you verify from the
sandbox — live-deploy checks are out of scope.

Write non-trivial findings to {slice_dir}/test_findings.md (state the owning
project per finding). Then write your verdict to {verdict_path}.
"""

CONSULT_PROMPT = """\
You are the workflow consult for slice {slice_name}. The task runner hit a
decision point it does not decide itself.

Situation: {situation}
{task_line}Slice folder: {slice_dir} (state.json holds the run history)

Investigate as needed — read the material below, the task folder, git log/diff.
{material}

Choose exactly one action:
{actions}

Write {verdict_path} as JSON:
  {{"outcome": "<action>", "summary": "<your reasoning, 1-5 sentences>"}}
Optionally write a longer write-up next to it as {consult_md_name}.
"""

CHECKPOINT_SITUATION = """\
Task {task_id} just merged. The merge touched:
{merge_stat}

Do an honest check of where the slice stands: does the remaining task breakdown
still match reality after this merge? Judge in two tiers. TIER 1: the agents'
outcome summaries in state.json's history, the latest review verdict, and the
file stat above — when those establish the breakdown holds (or clearly
doesn't), answer from them without opening code. TIER 2: only where tier 1
leaves genuine uncertainty — above all when a file above is one a remaining
task's plan.md grounds itself in — read the specific diff hunks or plan
sections that settle it, never the whole diff by default. If upcoming
tasks need adjusting (premises changed by the merged work, a gap appeared, work
became unnecessary), edit or add task folders directly under {tasks_dir}
(follow the tasks/NN_slug layout with task.json — a letter suffix like 04a
inserts between 04 and 05; commit specs-repo changes by name) and answer
`amend`. If everything holds, answer `proceed`.\
"""

VERDICT_NUDGE_PROMPT = """\
Your session ended without writing a valid verdict file. Do not start new
work: if any of your work is uncommitted, commit it, then write your verdict
now to {verdict_path} as JSON ({{"outcome": "...", "summary": "..."}}{outcomes}).
"""

COMMIT_NUDGE_PROMPT = """\
Your session ended leaving uncommitted changes in the working tree. Commit the
work that belongs to this task now (stage deliberately; drop anything that
should not be kept). Do not start new work.
"""

REATTACH_PROMPT = """\
Your session was interrupted mid-run (the runner process died — host restart,
quota stop, or similar). The working tree is exactly as you left it. Reassess
where you were (git status, git log, your task-folder artifacts), finish your
work, commit it, then write your verdict to {verdict_path}.
"""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class Runner:
    def __init__(self, slice_dir: Path, resume: bool, verbose: bool = False):
        self.slice_dir = slice_dir.resolve()
        self.slice_name = self.slice_dir.name
        self.tasks_dir = self.slice_dir / "tasks"
        self.state_path = self.slice_dir / "state.json"
        self.log_path = self.slice_dir / "log.txt"
        self.resume = resume
        self.verbose = verbose
        self.state: dict = {}
        self._log_file = None
        self._reattach: dict | None = None
        self.repo_root = _git_toplevel()
        # name → effective cwd, from `kc project list --output=json`; loaded in
        # run() (both fresh and resume need it before any task dispatch).
        self.project_dirs: dict[str, Path] = {}

    # -- state ---------------------------------------------------------------

    def _save_state(self) -> None:
        self.state["updated_at"] = _now_iso()
        tmp = self.state_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
            f.write("\n")
        os.replace(tmp, self.state_path)

    def _task_state(self, task_id: str) -> dict:
        defaults = {
            "status": "pending", "stage": None, "branch": None,
            "writer_session": None, "writer_rounds": 0, "test_rounds": 0,
            "review_rounds": 0, "review_grants": 0, "last_writer_commit": None,
            "gate_runs": 0, "gate_green_commit": None,
        }
        ts = self.state["tasks"].setdefault(task_id, dict(defaults))
        for key, value in defaults.items():
            ts.setdefault(key, value)  # states written before a key existed
        return ts

    def _record(self, task: str | None, role: str, round_: int,
                outcome: str, summary: str, session: str | None,
                duration_s: int, transcript: str | None = None) -> None:
        self.state["history"].append({
            "ts": _now_iso(), "task": task, "role": role, "round": round_,
            "outcome": outcome, "summary": summary, "session": session,
            "transcript": transcript, "duration_s": duration_s,
        })
        self._save_state()

    def _emit(self, line: str) -> None:
        """All runner/session output lands in <slice>/log.txt; stdout echoes
        it only under --verbose (the log must never flood a caller's context)."""
        if self._log_file is None:
            self._log_file = open(self.log_path, "a", buffering=1)
        self._log_file.write(line + "\n")
        if self.verbose:
            print(line, flush=True)

    def log(self, msg: str) -> None:
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        self._emit(f"[{ts}] {msg}")

    # -- git -----------------------------------------------------------------

    def git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.repo_root, capture_output=True, text=True,
        )
        if check and result.returncode != 0:
            raise Bailout(
                "protocol_failure", details=(
                    f"git {' '.join(args)} failed:\n{result.stderr.strip()}"
                ),
            )
        return result.stdout.strip()

    def _current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD")

    def _worktree_dirty(self) -> bool:
        return bool(self.git("status", "--porcelain"))

    def _nudge(self, prompt: str, cwd: Path, session_id: str,
               label: str) -> None:
        """One resume-shot at a session that missed part of its protocol
        (uncommitted work, missing verdict). Failures fall through to the
        caller's re-check; a nudge never raises."""
        self.log(f"{label} nudging the session (resume)")
        try:
            run_kc_session(
                prompt=prompt, cwd=str(cwd), timeout=NUDGE_TIMEOUT,
                resume_session=session_id, extra_env=SPAWN_ENV,
                progress=lambda line: self._emit(f"    {label} {line}"),
            )
        except subprocess.TimeoutExpired:
            self.log(f"{label} nudge timed out")

    def _ensure_committed(self, task_id: str, role: str,
                          session_id: str | None, cwd: Path) -> None:
        """An agent must leave the worktree clean. Dirty → one resume-nudge
        asking it to commit; still dirty → bail (the runner never commits an
        agent's leftovers itself)."""
        if not self._worktree_dirty():
            return
        label = f"[task {task_id}] [{role}]"
        if session_id:
            self._nudge(COMMIT_NUDGE_PROMPT, cwd, session_id, label)
            if not self._worktree_dirty():
                self.log(f"{label} committed its leftovers on the nudge")
                return
        raise Bailout(
            "protocol_failure", task=task_id,
            details=f"{role} left uncommitted changes"
                    + (" after a commit nudge" if session_id
                       else "; no session to nudge"),
        )

    # -- the deterministic test gate -------------------------------------------

    def _gate_argv(self, project: str) -> list[str]:
        """The gate command for a component. A seam: the suite overrides this
        to point at a stub instead of putting a fake `kc` on PATH."""
        return ["kc", "project", "test", "--project", project]

    def _run_gate(self, task_id: str, ts: dict, task_dir: Path,
                  project: str) -> tuple[bool, Path]:
        """Run the component's test gate (`kc project test`) as a subprocess.
        Green/red is the exit code; full output goes to gate_r<N>.log in the
        task folder. The runner never parses suite output and never spawns a
        session to learn the gate's color.

        Runs from the repo root, not the component dir: kc resolves
        .kubecoder/project.yaml relative to its own cwd with no upward
        tree-walk, and resolves the component's cwd itself from --project."""
        argv = self._gate_argv(project)
        ts["gate_runs"] += 1
        n = ts["gate_runs"]
        self._save_state()
        log_path = task_dir / f"gate_r{n}.log"
        self.log(f"[task {task_id}] gate #{n} running ({' '.join(argv)})")
        t0 = time.monotonic()
        try:
            with open(log_path, "w") as log_file:
                result = subprocess.run(
                    argv, cwd=self.repo_root,
                    stdout=log_file, stderr=subprocess.STDOUT,
                    timeout=GATE_TIMEOUT,
                )
        except subprocess.TimeoutExpired:
            raise Bailout(
                "timeout", task=task_id,
                details=f"gate `{' '.join(argv)}` exceeded {GATE_TIMEOUT}s "
                        f"(output in {log_path})",
            ) from None
        duration_s = int(time.monotonic() - t0)
        # rc 2 is kc's usage error — an unknown --project. The name came from
        # kc's own project list, so that is a runner bug, not a red suite.
        if result.returncode == 2:
            raise Bailout(
                "protocol_failure", task=task_id,
                details=f"`{' '.join(argv)}` rejected the project name "
                        f"(output in {log_path})",
            )
        green = result.returncode == 0
        tail = ""
        try:
            lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
            tail = lines[-1] if lines else ""
        except OSError:
            pass
        if green:
            ts["gate_green_commit"] = self.git("rev-parse", "HEAD")
        self._record(task_id, "gate", n, "green" if green else "red",
                     tail, None, duration_s)
        self.log(f"[task {task_id}] gate #{n} → "
                 f"{'green' if green else 'RED'} ({duration_s}s) {tail[:120]}")
        return green, log_path

    # -- task discovery --------------------------------------------------------

    def discover_tasks(self) -> list[Path]:
        if not self.tasks_dir.is_dir():
            return []
        # NN_slug, with an optional letter suffix (04a_slug) to insert a task
        # between existing numbers; lexicographic sort gives 04 < 04a < 05.
        dirs = sorted(
            d for d in self.tasks_dir.iterdir()
            if d.is_dir() and re.match(r"^\d{2}[a-z]?_", d.name)
        )
        return dirs

    def _load_task_meta(self, task_dir: Path) -> dict:
        meta = _read_json(task_dir / "task.json")
        if not meta or meta.get("project") not in self.project_dirs:
            raise Bailout(
                "protocol_failure", task=task_dir.name,
                details=f"{task_dir}/task.json missing or has an invalid project",
            )
        return meta

    # -- session spawning ------------------------------------------------------

    def _spawn(self, role: str, prompt: str, cwd: Path, verdict_path: Path,
               task_id: str | None, round_: int,
               agent: str | None = None,
               resume_session: str | None = None) -> tuple[dict, str | None]:
        """Run one session; return (verdict, session_id).

        A session failure, timeout, or missing/invalid verdict raises Bailout
        via the caller's policy — here it returns outcome="blocked" with the
        failure described, which callers route to a consult.
        """
        label = f"[task {task_id}] [{role}]" if task_id else f"[{role}]"
        prompt, resume_session = self._resolve_reattach(
            role, task_id, prompt, verdict_path, resume_session, label)
        self.log(f"{label} session starting"
                 + (" (resume)" if resume_session else ""))
        verdict_path.unlink(missing_ok=True)

        # Track the in-flight session so a crashed run can reattach on --resume.
        self.state["in_flight"] = {
            "task": task_id, "role": role, "round": round_,
            "verdict_path": str(verdict_path), "session": resume_session,
            "started_at": _now_iso(),
        }
        self._save_state()

        def _note_session(sid: str) -> None:
            self.log(f"{label} session {sid} — transcript "
                     f"{_transcript_path(cwd, sid)}")
            in_flight = self.state.get("in_flight")
            if in_flight and not in_flight.get("session"):
                in_flight["session"] = sid
                self._save_state()

        t0 = time.monotonic()
        try:
            returncode, result = run_kc_session(
                prompt=prompt,
                cwd=str(cwd),
                timeout=TIMEOUTS[role],
                agent=agent,
                model=MODELS.get(role),
                resume_session=resume_session,
                extra_env=SPAWN_ENV,
                progress=lambda line: self._emit(f"    {label} {line}"),
                on_session=_note_session,
            )
        except subprocess.TimeoutExpired:
            # A timed-out session is stuck, not crashed — never reattach to it.
            self.state["in_flight"] = None
            self._save_state()
            raise Bailout(
                "timeout", task=task_id,
                details=f"{role} exceeded {TIMEOUTS[role]}s",
            ) from None
        duration_s = int(time.monotonic() - t0)

        session_id = result.session_id

        def _valid(v: dict | None) -> bool:
            return v is not None and (
                role not in VERDICTS or v.get("outcome") in VERDICTS[role])

        verdict = _read_json(verdict_path)
        nudged = False
        if not _valid(verdict) and session_id:
            outcomes = (f"; outcome must be one of {sorted(VERDICTS[role])}"
                        if role in VERDICTS else "")
            self._nudge(
                VERDICT_NUDGE_PROMPT.format(verdict_path=verdict_path,
                                            outcomes=outcomes),
                cwd, session_id, label)
            nudged = True
            verdict = _read_json(verdict_path)
            if _valid(verdict):
                returncode = 0  # the nudge completed the protocol
        if returncode != 0 or not _valid(verdict):
            detail = (
                f"{role} session ended rc={returncode}; verdict file "
                f"{verdict_path.name} "
                + ("missing/unparseable" if verdict is None
                   else f"invalid outcome {verdict.get('outcome')!r}")
                + (" (after one nudge)" if nudged else "")
            )
            verdict = {"outcome": "blocked", "summary": detail,
                       "_protocol_failure": True}
        outcome = verdict.get("outcome", "blocked")
        self.state["in_flight"] = None
        self.log(f"{label} → {outcome}: {verdict.get('summary', '')[:160]}")
        self._record(task_id, role, round_, outcome,
                     verdict.get("summary", ""), session_id, duration_s,
                     transcript=_transcript_path(cwd, session_id))
        return verdict, session_id

    def _resolve_reattach(self, role: str, task_id: str | None, prompt: str,
                          verdict_path: Path, resume_session: str | None,
                          label: str) -> tuple[str, str | None]:
        """If this spawn matches the session a crashed run left in flight,
        resume that session with a recovery prompt instead of dispatching
        fresh. Consults never reattach (cheap, and their action vocabulary
        may have changed); an intentional resume is never overridden."""
        r = self._reattach
        if not (r and r.get("session") and resume_session is None
                and role in VERDICTS
                and r.get("role") == role and r.get("task") == task_id):
            return prompt, resume_session
        self._reattach = None
        self.log(f"{label} reattaching to the interrupted session "
                 f"{r['session']}")
        return REATTACH_PROMPT.format(verdict_path=verdict_path), r["session"]

    def _consult(self, situation: str, actions: dict[str, str],
                 material: list[Path], task_id: str | None) -> dict:
        """Spawn a fresh consult session; return its verdict (validated)."""
        n = self.state["consult_seq"] = self.state.get("consult_seq", 0) + 1
        self._save_state()
        base = (self.tasks_dir / task_id) if task_id else self.slice_dir
        verdict_path = base / f"consult_{n}.json"
        task_line = (
            f"Task: {task_id} — folder {self.tasks_dir / task_id}\n"
            if task_id else ""
        )
        prompt = CONSULT_PROMPT.format(
            slice_name=self.slice_name,
            situation=situation,
            task_line=task_line,
            slice_dir=self.slice_dir,
            material="\n".join(f"- {p}" for p in material) or "- (state.json only)",
            actions="\n".join(f"- `{a}` — {why}" for a, why in actions.items()),
            verdict_path=verdict_path,
            consult_md_name=f"consult_{n}.md",
        )
        verdict, _ = self._spawn(
            "consult", prompt, self.repo_root, verdict_path, task_id, n,
        )
        if verdict.get("outcome") not in actions:
            raise Bailout(
                "protocol_failure", task=task_id, consult=str(verdict_path),
                details=f"consult chose {verdict.get('outcome')!r}, "
                        f"offered {sorted(actions)}",
            )
        if verdict["outcome"] == "bail":
            raise Bailout(
                "consult_bail", task=task_id, consult=str(verdict_path),
                details=verdict.get("summary", ""),
            )
        return verdict

    # -- the task loop ---------------------------------------------------------

    def run_task(self, task_dir: Path) -> None:
        task_id = task_dir.name
        meta = self._load_task_meta(task_dir)
        ts = self._task_state(task_id)
        project_dir = self.project_dirs[meta["project"]]
        branch = (f"task/{self.slice_name.split('_')[0]}-"
                  f"{meta.get('id', task_id.split('_')[0])}")
        base = self.state["base_branch"]

        self.log(f"[task {task_id}] start (project={meta['project']}, "
                 f"branch={branch})")

        # Branch setup (fresh or resume).
        existing = self.git("branch", "--list", branch)
        if ts["status"] == "pending" or not existing:
            if existing:
                self.git("checkout", base)
                self.git("branch", "-D", branch)
            self.git("checkout", "-b", branch, base)
            ts.update(status="in_progress", stage="writer", branch=branch)
        else:
            self.git("checkout", branch)
            if self._reattach and self._reattach.get("session") \
                    and self._reattach.get("task") == task_id:
                # An interrupted session will be reattached — its uncommitted
                # work must survive exactly as the crash left it.
                self.log(f"[task {task_id}] resuming at stage {ts['stage']} "
                         "(worktree preserved for reattach)")
            else:
                self.git("reset", "--hard", "HEAD")
                self.log(f"[task {task_id}] resuming at stage {ts['stage']}")
        self._save_state()

        merge_base = self.git("merge-base", base, branch)

        def writer_verdict_path(r: int) -> Path:
            return task_dir / f"writer_result_r{r}.json"

        def initial_writer_prompt(verdict_path: Path) -> str:
            return WRITER_PROMPT.format(
                task_id=task_id, slice_name=self.slice_name,
                task_dir=task_dir, verdict_path=verdict_path,
            )

        def spawn_writer(build_prompt, fresh: bool) -> dict:
            """build_prompt(verdict_path) → prompt; the round number is
            allocated here so prompt and expected verdict file always agree."""
            ts["writer_rounds"] += 1
            r = ts["writer_rounds"]
            self._save_state()
            verdict, session = self._spawn(
                "code-writer", build_prompt(writer_verdict_path(r)),
                project_dir, writer_verdict_path(r),
                task_id, r, agent="code-writer",
                resume_session=None if fresh else ts["writer_session"],
            )
            if fresh and session:
                ts["writer_session"] = session
            self._ensure_committed(task_id, "code-writer",
                                   ts["writer_session"], project_dir)
            ts["last_writer_commit"] = self.git("rev-parse", "HEAD")
            self._save_state()
            return verdict

        def handle_blocked(verdict: dict, role: str) -> str:
            """Route a blocked/protocol verdict through a consult. Returns
            'retry' (allowed once per role+task) or raises Bailout."""
            key = f"_retried_{role}"
            actions = {"bail": "stop the slice and hand this to the orchestrator"}
            if not ts.get(key):
                actions["retry"] = "run the same agent once more, fresh"
            choice = self._consult(
                f"The {role} reported `blocked`: {verdict.get('summary', '')}",
                actions,
                [task_dir], task_id,
            )
            ts[key] = True
            self._save_state()
            return choice["outcome"]

        # ---- write stage ----
        if ts["stage"] == "writer":
            verdict = spawn_writer(initial_writer_prompt, fresh=True)
            while verdict["outcome"] == "blocked":
                handle_blocked(verdict, "code-writer")  # returns retry or raises
                verdict = spawn_writer(initial_writer_prompt, fresh=True)
            if verdict["outcome"] == "missing-task":
                raise Bailout("missing-task", task=task_id,
                              details=verdict.get("summary", ""))
            ts["stage"] = "testing"
            self._save_state()

        def reattach_pending(role: str) -> bool:
            """A crashed run left this role's session in flight for this task:
            its round is already counted, so caps must not re-fire and counters
            must not advance again — the spawn below reattaches it."""
            return bool(self._reattach and self._reattach.get("session")
                        and self._reattach.get("role") == role
                        and self._reattach.get("task") == task_id)

        def spawn_fixer(r: int, gate_log: Path) -> dict:
            verdict, fixer_session = self._spawn(
                "test-fixer",
                FIXER_PROMPT.format(
                    task_id=task_id, slice_name=self.slice_name,
                    branch=branch, round=r, task_dir=task_dir,
                    gate_log=gate_log, merge_base=merge_base,
                    project=meta["project"],
                    verdict_path=task_dir / f"fixer_result_r{r}.json",
                ),
                project_dir, task_dir / f"fixer_result_r{r}.json",
                task_id, r, agent="test-fixer",
            )
            self._ensure_committed(task_id, "test-fixer",
                                   fixer_session, project_dir)
            return verdict

        # ---- gate + fix loop ----
        # The runner runs the deterministic gate itself; a test-fixer session
        # exists only to make a red gate green. Green exits the loop — a
        # fixer's `clean` is confirmed by re-running the gate, never trusted.
        if ts["stage"] == "testing":
            while True:
                if reattach_pending("test-fixer"):
                    r = ts["test_rounds"]
                    gate_log = task_dir / f"gate_r{ts['gate_runs']}.log"
                else:
                    green, gate_log = self._run_gate(
                        task_id, ts, task_dir, meta["project"])
                    if green:
                        break
                    if ts["test_rounds"] >= TEST_ROUND_CAP:
                        self._tester_limit_consult(
                            task_dir, ts, task_id, branch, gate_log)
                        break
                    ts["test_rounds"] += 1
                    r = ts["test_rounds"]
                    self._save_state()
                verdict = spawn_fixer(r, gate_log)
                if verdict["outcome"] == "blocked":
                    if handle_blocked(verdict, "test-fixer") == "retry":
                        ts["test_rounds"] -= 1  # the retry re-runs this round
                        self._save_state()
                    continue
                if verdict["outcome"] == "issues":
                    # escalation → same writer fixes (unless at the cap: the
                    # gate re-runs and the loop top holds the limit consult)
                    if ts["test_rounds"] >= TEST_ROUND_CAP:
                        continue
                    fix = spawn_writer(lambda vp, _r=r: WRITER_FIX_PROMPT.format(
                        results_path=task_dir / f"test_results_r{_r}.md",
                        verdict_path=vp,
                    ), fresh=False)
                    if fix["outcome"] == "blocked":
                        handle_blocked(fix, "code-writer")
                        spawn_writer(initial_writer_prompt, fresh=True)
                # clean → the loop re-runs the gate to confirm
            ts["stage"] = "review"
            self._save_state()

        # ---- review loop ----
        if ts["stage"] == "review":
            while True:
                grants = ts.get("review_grants", 0)
                if not reattach_pending("code-reviewer") \
                        and ts["review_rounds"] >= REVIEW_ROUND_CAP + grants:
                    last_r = ts["review_rounds"]
                    actions = {
                        "merge_flagged": "merge the task; the findings are "
                                         "surfaced to the operator at slice "
                                         "end as issue-tracker items / rework",
                        "bail": "stop the slice for the orchestrator",
                    }
                    # A finding raised in the final round has had its fix written
                    # but never re-reviewed. Let the consult buy the confirming
                    # round rather than merge on its own say-so — verifying a
                    # writer's fix is the reviewer's job, not the consult's.
                    if grants < REVIEW_GRANT_CAP:
                        actions = {
                            "another_round": f"the round-{last_r} findings look "
                                             "FIXED but no reviewer has seen the "
                                             "fix; spend one more review round to "
                                             "confirm it",
                            **actions,
                        }
                    choice = self._consult(
                        f"Review round {last_r} did not sign off "
                        f"(see the latest code_review_r*.md).",
                        actions,
                        [task_dir / f"code_review_r{last_r}.md"],
                        task_id,
                    )
                    if choice["outcome"] == "another_round":
                        ts["review_grants"] = grants + 1
                        self._save_state()
                        continue
                    self.state["flagged_findings"].append({
                        "task": task_id,
                        "review": str(task_dir / f"code_review_r{last_r}.md"),
                        "consult_summary": choice.get("summary", ""),
                    })
                    self._save_state()
                    break
                if not reattach_pending("code-reviewer"):
                    ts["review_rounds"] += 1
                r = ts["review_rounds"]
                self._save_state()
                verdict, _ = self._spawn(
                    "code-reviewer",
                    REVIEWER_PROMPT.format(
                        task_id=task_id, slice_name=self.slice_name,
                        round=r, merge_base=merge_base, branch=branch,
                        task_dir=task_dir, slice_dir=self.slice_dir,
                        verdict_path=task_dir / f"review_result_r{r}.json",
                    ),
                    project_dir, task_dir / f"review_result_r{r}.json",
                    task_id, r, agent="code-reviewer",
                )
                if verdict["outcome"] == "signoff":
                    break
                if verdict["outcome"] == "blocked" or verdict.get("_protocol_failure"):
                    if handle_blocked(verdict, "code-reviewer") == "retry":
                        ts["review_rounds"] -= 1
                        self._save_state()
                    continue
                # issues / critical → writer fixes; the gate then re-checks
                fix = spawn_writer(lambda vp, _r=r: WRITER_REVIEW_FIX_PROMPT.format(
                    review_path=task_dir / f"code_review_r{_r}.md",
                    verdict_path=vp,
                ), fresh=False)
                if fix["outcome"] == "blocked":
                    handle_blocked(fix, "code-writer")
                # Red after a review fix gets one fixer round; still red →
                # the next review round proceeds anyway. Red can stall a task
                # but never ship: the merge below re-checks the gate.
                attempts = 0
                while True:
                    green, gate_log = self._run_gate(
                        task_id, ts, task_dir, meta["project"])
                    if green:
                        break
                    if attempts >= 1:
                        self.log(f"[task {task_id}] gate still red after the "
                                 "fix round — continuing to the next review "
                                 "round; a red gate cannot merge")
                        break
                    attempts += 1
                    fr = ts["test_rounds"] + 1
                    ts["test_rounds"] = fr
                    self._save_state()
                    fverdict = spawn_fixer(fr, gate_log)
                    if fverdict["outcome"] == "blocked":
                        if handle_blocked(fverdict, "test-fixer") == "retry":
                            attempts -= 1  # the retry re-runs this round
                    elif fverdict["outcome"] == "issues":
                        spawn_writer(lambda vp, _fr=fr: WRITER_FIX_PROMPT.format(
                            results_path=task_dir / f"test_results_r{_fr}.md",
                            verdict_path=vp,
                        ), fresh=False)
            ts["stage"] = "merging"
            self._save_state()

        # ---- merge ----
        if ts["stage"] == "merging":
            # Every agent boundary above ensures a clean tree; dirt here means
            # something bypassed its commit boundary (e.g. a reviewer wrote code).
            if self._worktree_dirty():
                raise Bailout(
                    "protocol_failure", task=task_id,
                    details="worktree dirty at merge — an agent left changes "
                            "outside its commit boundary",
                )
            # A red gate cannot merge. HEAD is usually the commit the gate
            # last verified green; when it is not (red tolerated above, or a
            # resume from an older state), the gate re-runs here.
            if ts["gate_green_commit"] != self.git("rev-parse", "HEAD"):
                green, gate_log = self._run_gate(
                    task_id, ts, task_dir, meta["project"])
                if not green:
                    raise Bailout(
                        "gate_red", task=task_id,
                        details=f"cannot merge a red test gate ({gate_log})",
                    )
            self.git("checkout", base)
            self.git("merge", "--ff-only", branch)
            self.git("branch", "-D", branch)
            ts.update(status="merged", stage=None)
            self._save_state()
            self.log(f"[task {task_id}] merged into {base}")

        # ---- checkpoint ----
        # The merge's file stat rides in the prompt so the consult's tier-1
        # judgment (summaries + stat) needs no git archaeology of its own.
        stat_lines = self.git(
            "diff", "--stat", f"{merge_base}..HEAD").splitlines()
        if len(stat_lines) > 30:
            stat_lines = stat_lines[:30] + [f"… (+{len(stat_lines) - 30} more)"]
        choice = self._consult(
            CHECKPOINT_SITUATION.format(
                task_id=task_id, tasks_dir=self.tasks_dir,
                merge_stat="\n".join(stat_lines) or "(no diff stat available)"),
            {
                "proceed": "the remaining breakdown holds",
                "amend": "you adjusted/added task folders; the runner "
                         "re-scans the task list",
                "bail": "something is wrong enough to stop the slice",
            },
            [self.slice_dir / "slice.md", self.state_path],
            task_id,
        )
        if choice["outcome"] == "amend":
            self.log(f"[task {task_id}] checkpoint amended the task list")

    def _tester_limit_consult(self, task_dir: Path, ts: dict, task_id: str,
                              branch: str, gate_log: Path) -> bool:
        """Consult when the fix-round cap is hit with the gate still red.
        Returns True when the loop should be skipped (a fresh writer
        self-tests → straight to review)."""
        r = ts["test_rounds"]
        choice = self._consult(
            f"The fix-round hard limit ({TEST_ROUND_CAP}) was reached and the "
            f"test gate is still red (latest output: {gate_log}; escalations "
            f"in test_results_r*.md). Judge whether the writer/fixer loop "
            f"went a bad direction (e.g. far too many changes) or is "
            f"genuinely close.",
            {
                "fresh_writer": "start a fresh code-writer with the original "
                                "task input, told to test its own work; then "
                                "proceed straight to review",
                "fresh_writer_reset": "same, but first drop every commit made "
                                      "after the writer's last round (the "
                                      "fixer's changes were bad)",
                "proceed_to_review": "continue to the code-reviewer despite "
                                     "the red gate — note a red gate cannot "
                                     "merge; something must still turn it "
                                     "green before merge",
                "bail": "stop the slice for the orchestrator",
            },
            [gate_log, task_dir / f"test_results_r{r}.md", task_dir],
            task_id,
        )
        if choice["outcome"] == "proceed_to_review":
            return True
        if choice["outcome"] == "fresh_writer_reset":
            self.git("reset", "--hard", ts["last_writer_commit"])
            prior = "Its work was dropped; the branch is at its last writer commit."
        else:
            prior = "Its work is committed on the branch."
        prompt = WRITER_PROMPT.format(
            task_id=task_id, slice_name=self.slice_name, task_dir=task_dir,
            verdict_path=task_dir / f"writer_result_r{ts['writer_rounds'] + 1}.json",
        ) + "\n" + WRITER_RETRY_NOTE.format(prior_state=prior)
        ts["writer_session"] = None
        ts["writer_rounds"] += 1
        self._save_state()
        project_dir = self.project_dirs[self._load_task_meta(task_dir)["project"]]
        verdict, session = self._spawn(
            "code-writer", prompt, project_dir,
            task_dir / f"writer_result_r{ts['writer_rounds']}.json",
            task_id, ts["writer_rounds"], agent="code-writer",
        )
        ts["writer_session"] = session
        self._ensure_committed(task_id, "code-writer", session, project_dir)
        ts["last_writer_commit"] = self.git("rev-parse", "HEAD")
        self._save_state()
        if verdict["outcome"] != "done":
            raise Bailout("tester_limit", task=task_id,
                          details="fresh writer after the tester limit did not "
                                  f"report done: {verdict.get('summary', '')}")
        return True

    # -- final verification ------------------------------------------------------

    def final_verification(self) -> None:
        if self.state["verification_rounds"] >= VERIFICATION_ROUND_CAP:
            raise Bailout(
                "verification_limit",
                details=f"{VERIFICATION_ROUND_CAP} verification rounds "
                        "exhausted with findings still open",
            )
        self.state["verification_rounds"] += 1
        r = self.state["verification_rounds"]
        self.state["phase"] = "final_verification"
        self._save_state()
        verdict_path = self.slice_dir / f"test_agent_result_r{r}.json"
        verdict, _ = self._spawn(
            "test-agent",
            TEST_AGENT_PROMPT.format(
                slice_name=self.slice_name, round=r,
                base_branch=self.state["base_branch"],
                slice_dir=self.slice_dir, verdict_path=verdict_path,
            ),
            self.repo_root, verdict_path, None, r, agent="test-agent",
        )
        if verdict["outcome"] == "clean":
            return
        if verdict["outcome"] == "findings":
            findings = self.slice_dir / "test_findings.md"
            if not findings.exists():
                findings.write_text(
                    f"# Test findings (round {r})\n\n"
                    f"{verdict.get('summary', '(no summary)')}\n")
            # The test-agent is a finder, not a judge: a consult decides whether
            # the findings block the slice, so a pre-existing / dormant residual
            # is flagged for the operator instead of hard-stopping the run
            # (slice 072 bailed on exactly that).
            choice = self._consult(
                "Final verification reported findings (test_findings.md). "
                "Judge whether they block the slice: a regression this slice "
                "introduced, or an acceptance criterion not actually met, "
                "blocks; a pre-existing, dormant, or out-of-scope residual "
                "does not.",
                {
                    "fix_tasks": "the findings block: stop the slice so the "
                                 "orchestrator turns them into fix task(s) and "
                                 "resumes",
                    "proceed_flagged": "the findings are non-blocking: record "
                                       "them as flagged findings for the "
                                       "operator (Trello cards at close-out) "
                                       "and complete the slice",
                    "bail": "something beyond the findings is wrong; stop the "
                            "slice for the orchestrator",
                },
                [findings, self.slice_dir / "slice.md"], None,
            )
            if choice["outcome"] == "proceed_flagged":
                self.state["flagged_findings"].append({
                    "task": None,
                    "review": str(findings),
                    "consult_summary": choice.get("summary", ""),
                })
                self._save_state()
                return
            raise Bailout("test_findings",
                          details=verdict.get("summary", ""))
        raise Bailout("blocked", details=verdict.get("summary", ""))

    # -- top level ----------------------------------------------------------------

    def preflight(self) -> None:
        if not (self.slice_dir / "slice.md").exists() and \
           not (self.slice_dir / "overview.md").exists():
            raise Bailout("protocol_failure",
                          details=f"{self.slice_dir} has no slice.md")
        if not self.discover_tasks():
            raise Bailout("protocol_failure",
                          details=f"{self.tasks_dir} has no NN_slug task folders")
        for task_dir in self.discover_tasks():
            self._load_task_meta(task_dir)
        if self._worktree_dirty():
            # Hard gate, not a bail-out: refuse to start on a dirty tree.
            print("Error: the working tree has uncommitted changes; commit "
                  "or stash before running a slice.", file=sys.stderr)
            sys.exit(2)

    def run(self) -> None:
        if self.state_path.exists():
            if not self.resume:
                print(f"Error: {self.state_path} exists. Pass --resume to "
                      "continue, or delete state.json to restart.",
                      file=sys.stderr)
                sys.exit(2)
            self.state = _read_json(self.state_path) or {}
            # A session left in flight by a crash is reattached at the next
            # matching spawn (see _resolve_reattach).
            self._reattach = self.state.get("in_flight") or None
            self.state["in_flight"] = None
        if not self.state:
            self.state = {
                "slice": self.slice_name,
                "created_at": _now_iso(),
                "phase": "tasks",
                "base_branch": self._current_branch(),
                "verification_rounds": 0,
                "consult_seq": 0,
                "in_flight": None,
                "flagged_findings": [],
                "tasks": {},
                "history": [],
            }
        (self.slice_dir / "bailout.json").unlink(missing_ok=True)

        try:
            # The valid project set + effective cwds, from the target repo's
            # manifest via kc. Needed by preflight (fresh) and every task
            # dispatch (fresh and resume), so load it before either.
            self.project_dirs = load_project_dirs(self.repo_root)
            if not self.resume:
                self.preflight()
                base = self.state["base_branch"]
                if self._current_branch() != base:
                    raise Bailout("protocol_failure",
                                  details=f"not on base branch {base}")
            while True:
                self.state["phase"] = "tasks"
                self._save_state()
                pending = [d for d in self.discover_tasks()
                           if self._task_state(d.name)["status"] != "merged"]
                if not pending:
                    break
                self.run_task(pending[0])
            self.final_verification()
        except Bailout as bail:
            self._bail(bail)
        except KeyboardInterrupt:
            self.log("interrupted — state.json is current; resume with --resume")
            print("Interrupted — resume with --resume (the in-flight session "
                  "will be reattached).", file=sys.stderr)
            sys.exit(130)

        self.state["phase"] = "done"
        self._save_state()
        self._summary()
        sys.exit(0)

    def _bail(self, bail: Bailout) -> None:
        self.state["phase"] = "bailed"
        self._save_state()
        payload = {
            "reason": bail.reason,
            "task": bail.task,
            "details": bail.details,
            "consult": bail.consult,
            "ts": _now_iso(),
        }
        with open(self.slice_dir / "bailout.json", "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        self.log(f"BAIL-OUT ({bail.reason}): {bail.details[:300]}")
        self.log(f"wrote {self.slice_dir / 'bailout.json'}; "
                 "resume with --resume after resolving")
        print(f"BAIL-OUT ({bail.reason}) — see "
              f"{self.slice_dir / 'bailout.json'}", file=sys.stderr)
        sys.exit(3)

    def _summary(self) -> None:
        tasks = self.state["tasks"]
        lines = [f"slice {self.slice_name} complete: "
                 f"{len(tasks)} task(s) merged, "
                 f"{self.state['verification_rounds']} verification round(s)"]
        for tid, ts in sorted(tasks.items()):
            lines.append(
                f"  {tid}: writer×{ts['writer_rounds']} "
                f"tester×{ts['test_rounds']} review×{ts['review_rounds']}")
        if self.state["flagged_findings"]:
            lines.append("FLAGGED FOR OPERATOR (merged with open review findings):")
            for f in self.state["flagged_findings"]:
                lines.append(f"  {f['task']}: {f['review']}")
        for line in lines:
            self.log(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    slice_dir = Path(args.slice_dir)
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}", file=sys.stderr)
        sys.exit(2)
    runner = Runner(slice_dir, resume=args.resume, verbose=args.verbose)
    if args.dry_run:
        tasks = runner.discover_tasks()
        print(f"slice {runner.slice_name}: {len(tasks)} task(s)")
        for d in tasks:
            meta = _read_json(d / "task.json") or {}
            print(f"  {d.name}  project={meta.get('project', '?')}  "
                  f"{meta.get('title', '')}")
        return
    print(f"runner log: {runner.log_path}", flush=True)
    runner.run()


def cmd_status(args) -> None:
    slice_dir = Path(args.slice_dir).resolve()
    state = _read_json(slice_dir / "state.json")
    if not state:
        print("no state.json — the runner has not started this slice")
        return
    print(f"slice {state['slice']}  phase={state['phase']}  "
          f"verification_rounds={state['verification_rounds']}")
    for tid, ts in sorted(state["tasks"].items()):
        print(f"  {tid}: {ts['status']}"
              + (f" (stage {ts['stage']})" if ts.get("stage") else "")
              + f"  writer×{ts['writer_rounds']} tester×{ts['test_rounds']} "
                f"review×{ts['review_rounds']}")
    for h in state["history"][-8:]:
        print(f"  {h['ts']}  {h['task'] or '-'}  {h['role']} r{h['round']} "
              f"→ {h['outcome']}")


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
                       help="list the tasks and exit")
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser("status", help="print a slice's runner state")
    status_p.add_argument("slice_dir")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
