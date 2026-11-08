#!/usr/bin/env python3
"""Long run — a command started detached, and waited on in chunks.

A dispatched session runs on a five-minute prompt cache: a tool call that
blocks longer than that makes its next call pay to write the whole context
again. So a command that may run long is started here, detached from the
caller, and waited on in calls of at most CHUNK seconds, each return a cheap
cache read (run_loop.HEADLESS_WAIT_LINE says this to every role).

`start` runs the command under a supervisor of its own — double fork, a new
session, stdin and stdout on /dev/null, nothing of the caller's held open —
so the Bash tool call that started it returns at once, and the command
outlives it and the caller's process group. The job directory holds the
record: `run.lock`, which the supervisor holds flocked while the command
runs (liveness is the lock, never a pid, as run_loop.lock_held probes it);
`job.json`, what runs where; `output.log`, the command's stdout and stderr;
`exit.json`, written last — its code, whether the timeout killed it, its
times; `supervisor.log`, where a supervisor that crashed left its traceback;
and a `.gitignore` of `*`, since a job directory may sit inside a repo. At
`--timeout` the command's process group is sent SIGTERM, then SIGKILL, and
its code is 124, as timeout(1) records it; a command that cannot be run at
all is 127, the reason in its output. The parent returns once the
supervisor holds the lock, so a `wait` straight after never finds it free.

`wait` blocks while the lock is held, at most --for seconds, then prints a
signal: its state line first, since the Bash tool previews the head of a
long output — `running` with the `next:` line to run again, `ended` with
the command's exit and its whole output, or `gone` when the supervisor left
no exit record.

Usage:
    long_run.py start [--timeout SECONDS] [--dir DIR] -- COMMAND [ARG...]
    long_run.py wait DIR [--for SECONDS]

Exit codes of start: 0 started (it prints the `started:` and `next:`
lines) · 2 refused: no command, or a job still running in DIR · 1 the
supervisor died before it started (DIR/supervisor.log says why).
Exit codes of wait, its own and not the command's: 0 the command ended (its
code is in the output) · 5 still running at --for · 6 gone, no exit record ·
2 DIR holds no job.
"""

import argparse
import contextlib
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

LONG_RUN = Path(__file__).resolve()

CHUNK = 240                 # wait's default: under the cache's five minutes
DEFAULT_TIMEOUT = 3600      # start's default, in seconds
KILL_GRACE = 10             # seconds between SIGTERM and SIGKILL at timeout
POLL = 1.0                  # seconds between lock probes
LOCK_TRIES = 20             # the supervisor's tries at the lock, LOCK_PAUSE apart:
LOCK_PAUSE = 0.05           # a wait's probe holds it for an instant
TIMED_OUT = 124             # timeout(1)'s codes
CANNOT_RUN = 127

WAIT_RUNNING = 5            # wait's own exit codes, as run_loop.py wait's
WAIT_GONE = 6

LOCK = "run.lock"
JOB = "job.json"
OUTPUT = "output.log"
EXIT = "exit.json"
SUPERVISOR_LOG = "supervisor.log"

# The supervisor's word to the parent on the handshake pipe: started, or
# refused because another holds the lock.
STARTED = b"started"
REFUSED = b"refused"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _read_json(path: Path) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, data: dict) -> None:
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


def lock_held(lock_path: Path) -> bool:
    """Whether a supervisor holds `lock_path` now — taken non-blocking and
    let go at once, as run_loop.lock_held takes it."""
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


def span(seconds: float) -> str:
    """A duration as a reader takes it in: `45s`, `6m12s`, `60m`."""
    whole = max(0, round(seconds))
    if whole < 60:
        return f"{whole}s"
    minutes, rest = divmod(whole, 60)
    return f"{minutes}m{rest:02d}s" if rest else f"{minutes}m"


def _secs(seconds: float) -> str:
    return f"{seconds:g}"


def wait_line(job_dir: Path) -> str:
    return f"next: python3 {LONG_RUN} wait {job_dir}"


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def start_job(argv: list[str], job_dir: Path | str | None = None,
              cwd: Path | str | None = None,
              timeout: float = DEFAULT_TIMEOUT,
              next_line: str | None = None) -> tuple[int, str]:
    """Start `argv` detached in `cwd` (None: ours), its record in `job_dir`
    (None: a fresh temp dir; created if missing), killed at `timeout`
    seconds. Returns once the supervisor holds the job's lock: (0, the
    `started:` and `next:` lines, for stdout), or (2, the refusal) or (1,
    the supervisor's death), for stderr. `next_line` stands in for the
    `next:` line naming this module's `wait` — a caller with a wait of its
    own over the same job dir names that."""
    if not argv:
        return 2, ("long_run: no command to run — give it after `--`: "
                   f"python3 {LONG_RUN} start --timeout <seconds> -- "
                   "<command> [arg...]")
    if job_dir is None:
        job_dir = tempfile.mkdtemp(prefix="long_run-")
    job_dir = Path(os.path.abspath(job_dir))
    cwd = os.path.abspath(cwd) if cwd is not None else os.getcwd()
    next_line = next_line or wait_line(job_dir)
    refusal = (f"long_run: a job is already running in {job_dir} — wait on "
               f"it:\n{next_line}")
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / ".gitignore").write_text("*\n")
    except OSError as e:
        return 2, f"long_run: cannot use {job_dir} as a job dir: {e}"
    if lock_held(job_dir / LOCK):
        return 2, refusal
    request = {"argv": list(argv), "cwd": cwd, "timeout": timeout}
    word = _spawn_supervisor(job_dir, request)
    if word == STARTED:
        return 0, (f"started: {shlex.join(argv)} in {cwd}, at most "
                   f"{_secs(timeout)}s\n{next_line}")
    if word == REFUSED:
        return 2, refusal
    return 1, ("long_run: the supervisor died before it started — "
               f"{job_dir / SUPERVISOR_LOG} says why")


def _spawn_supervisor(job_dir: Path, request: dict) -> bytes:
    """Double fork, a new session, and a fresh interpreter running
    `_supervise` in the grandchild — nothing of this process's state comes
    with it, and none of its descriptors but the handshake pipe. Returns
    the supervisor's word on the pipe: STARTED, REFUSED, or b"" when it
    died first."""
    sys.stdout.flush()
    sys.stderr.flush()
    read_fd, write_fd = os.pipe()
    first = os.fork()
    if first == 0:
        try:
            os.close(read_fd)
            os.setsid()
            if os.fork() == 0:
                _exec_supervisor(job_dir, request, write_fd)
        finally:
            os._exit(0)
    os.close(write_fd)
    data = b""
    try:
        while b"\n" not in data:
            chunk = os.read(read_fd, 4096)
            if not chunk:
                break
            data += chunk
    finally:
        os.close(read_fd)
        os.waitpid(first, 0)
    return data.split(b" ", 1)[0].strip()


def _exec_supervisor(job_dir: Path, request: dict, pipe_fd: int) -> None:
    """The grandchild: stdin and stdout on /dev/null, stderr on the job's
    supervisor.log, every other descriptor closed but the pipe — so no
    pipe of the caller's is held open — then the supervisor. Never
    returns."""
    try:
        # above the standard three, whatever the caller left closed
        pipe_fd = fcntl.fcntl(pipe_fd, fcntl.F_DUPFD, 3)
        null = os.open(os.devnull, os.O_RDWR)
        os.dup2(null, 0)
        os.dup2(null, 1)
        log = os.open(job_dir / SUPERVISOR_LOG,
                      os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log, 2)
        try:
            top = os.sysconf("SC_OPEN_MAX")
        except (OSError, ValueError):
            top = 4096
        os.closerange(3, pipe_fd)
        os.closerange(pipe_fd + 1, max(top, pipe_fd + 1))
        os.set_inheritable(pipe_fd, True)
        os.execv(sys.executable, [
            sys.executable, "-I", str(LONG_RUN), "_supervise", str(job_dir),
            str(pipe_fd), json.dumps(request)])
    except Exception as e:  # the exec failed: say so where the dir keeps it
        with contextlib.suppress(OSError):
            os.write(2, f"{_now_iso()} long_run: cannot start the supervisor: "
                        f"{e!r}\n".encode())
    finally:
        os._exit(1)


def _take_lock(lock_path: Path) -> int | None:
    """The job's lock, held for the supervisor's life — the descriptor, or
    None when another supervisor holds it."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    for _ in range(LOCK_TRIES):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            time.sleep(LOCK_PAUSE)
    os.close(fd)
    return None


def _supervise(job_dir: Path, pipe_fd: int, request: dict) -> int:
    """The supervisor: take the lock, clear an earlier job's record, write
    job.json, tell the parent, run the command to its end or its timeout,
    and write exit.json last. The lock goes with the process."""
    lock_fd = _take_lock(job_dir / LOCK)
    if lock_fd is None:
        os.write(pipe_fd, REFUSED + b"\n")
        return 2
    argv, cwd = request["argv"], request["cwd"]
    timeout = float(request["timeout"])
    (job_dir / EXIT).unlink(missing_ok=True)
    started = _now_iso()
    clock = time.monotonic()
    (job_dir / OUTPUT).write_bytes(b"")
    # appended to: the command's writes and ours share one offset
    with open(job_dir / OUTPUT, "ab") as out:
        _write_json_atomic(job_dir / JOB, {
            "argv": argv, "cwd": cwd, "timeout": timeout,
            "started": started, "pid": os.getpid()})
        os.write(pipe_fd, STARTED + f" {os.getpid()}\n".encode())
        os.close(pipe_fd)
        code, timed_out = _run(argv, cwd, timeout, out)
    _write_json_atomic(job_dir / EXIT, {
        "code": code, "timed_out": timed_out, "started": started,
        "ended": _now_iso(),
        "seconds": round(time.monotonic() - clock, 1)})
    os.close(lock_fd)
    return 0


def _run(argv: list[str], cwd: str, timeout: float, out) -> tuple[int, bool]:
    """The command, in a process group of its own, its output into `out`:
    (its code, whether the timeout killed it)."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True)
    except OSError as e:
        out.write(f"long_run: cannot run {shlex.join(argv)} in {cwd}: "
                  f"{e}\n".encode())
        return CANNOT_RUN, False
    try:
        return proc.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        pass
    _signal_group(proc.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=KILL_GRACE)
    # whatever of the group outlived the grace, and the leader if it did
    _signal_group(proc.pid, signal.SIGKILL)
    proc.wait()
    out.flush()
    lead = "\n" if os.fstat(out.fileno()).st_size else ""
    out.write(f"{lead}long_run: timed out after {_secs(timeout)}s — the "
              "command's process group was killed\n".encode())
    return TIMED_OUT, True


def _signal_group(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


# ---------------------------------------------------------------------------
# wait
# ---------------------------------------------------------------------------

def wait_job(job_dir: Path | str, for_seconds: float = CHUNK,
             next_line: str | None = None,
             meaning: Callable[[int], str | None] | None = None
             ) -> tuple[int, str]:
    """Block while the job in `job_dir` runs, at most `for_seconds`, then
    (wait's own code, what to print): (5, `running` and the `next:` line),
    (0, `ended`, the output's path and the whole output), (6, `gone`), or
    (2, the error, for stderr) where `job_dir` holds no job. `next_line`
    stands in for the `next:` line naming this module's `wait`;
    `meaning(code)` puts what the command's exit means beside it on the
    ended line — `exit 1 (red)`."""
    job_dir = Path(os.path.abspath(job_dir))
    job = _read_json(job_dir / JOB)
    if job is None:
        return 2, (f"long_run: {job_dir} holds no job — no readable {JOB} "
                   "there")
    lock = job_dir / LOCK
    deadline = time.monotonic() + for_seconds
    while lock_held(lock):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(POLL, remaining))
    output = job_dir / OUTPUT
    if lock_held(lock):
        try:
            elapsed = time.time() - datetime.fromisoformat(
                job["started"]).timestamp()
        except (KeyError, TypeError, ValueError):
            elapsed = 0
        try:
            limit = f" of at most {span(float(job['timeout']))}"
        except (KeyError, TypeError, ValueError):
            limit = ""
        return WAIT_RUNNING, (f"running: {span(elapsed)}{limit}\n"
                              f"{next_line or wait_line(job_dir)}")
    record = _read_json(job_dir / EXIT)
    if record is None:
        return WAIT_GONE, ("gone: the runner left no exit record\n"
                           f"output: {output}")
    code = record.get("code")
    said = meaning(code) if meaning is not None else None
    line = f"ended: exit {code}" + (f" ({said})" if said else "")
    if record.get("timed_out"):
        line += f", timed out after {_secs(float(job.get('timeout', 0)))}s"
    else:
        line += f" after {span(float(record.get('seconds') or 0))}"
    try:
        text = output.read_bytes().decode(errors="replace")
    except OSError as e:
        text = f"(the output could not be read: {e})\n"
    return 0, f"{line}\noutput: {output}\n\n{text}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print(text: str, to_stderr: bool) -> None:
    stream = sys.stderr if to_stderr else sys.stdout
    stream.write(text if text.endswith("\n") else text + "\n")
    stream.flush()


def cmd_start(args) -> int:
    argv = list(args.command)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    code, text = start_job(argv, args.dir, None, args.timeout)
    _print(text, code != 0)
    return code


def cmd_wait(args) -> int:
    code, text = wait_job(args.dir, args.for_seconds)
    _print(text, code == 2)
    return code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_supervise"]:
        # the grandchild `_exec_supervisor` started: DIR, the pipe, the job
        return _supervise(Path(argv[1]), int(argv[2]), json.loads(argv[3]))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True)
    start_p = sub.add_parser(
        "start", help="run a command detached; exit 0 once it started, 2 "
                      "refused")
    start_p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                         metavar="SECONDS",
                         help="kill its process group after this long "
                              f"(default {DEFAULT_TIMEOUT}); its exit is then "
                              f"{TIMED_OUT}")
    start_p.add_argument("--dir", default=None,
                         help="the job dir (default: a fresh temp dir)")
    start_p.add_argument("command", nargs=argparse.REMAINDER,
                         help="the command, after `--`")
    start_p.set_defaults(func=cmd_start)
    wait_p = sub.add_parser(
        "wait", help="wait on a job; exit 0 ended, 5 still running at --for, "
                     "6 gone, 2 no job")
    wait_p.add_argument("dir", help="the job dir `start` named")
    wait_p.add_argument("--for", dest="for_seconds", type=float,
                        default=CHUNK, metavar="SECONDS",
                        help=f"give up waiting after this long (default "
                             f"{CHUNK})")
    wait_p.set_defaults(func=cmd_wait)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
