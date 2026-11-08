"""Tests for long_run — a command started detached and waited on in chunks.

Real short commands under the real supervisor: each test starts its jobs in
a temp dir of its own and waits them out before it ends. Nothing reaches the
network.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_long_run.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "long_run", Path(__file__).resolve().parent / "long_run.py"
)
long_run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(long_run)
# The suite's waits probe often; the CLI's one second would make every test
# that waits for an end a second long.
long_run.POLL = 0.02


def start(job_dir, *argv, timeout=30):
    code, text = long_run.start_job(list(argv), job_dir, None, timeout)
    assert code == 0, text
    return text.splitlines()


def ended(job_dir, for_seconds=10):
    """The job's end, waited for: wait's lines."""
    code, text = long_run.wait_job(job_dir, for_seconds)
    assert code == 0, text
    return text.splitlines()


def alive(pid):
    """Whether `pid` runs — a zombie no init reaps is no longer running."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


def cli(*argv):
    """long_run's main over `argv`: (its code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = long_run.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_start_returns_while_the_command_runs_and_wait_brings_its_end():
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / "job"
        cmd = ["sh", "-c", "echo hi; sleep 0.5; echo done; exit 3"]
        lines = start(job, *cmd)
        # returned with the lock held and the command not done
        assert long_run.lock_held(job / long_run.LOCK)
        assert not (job / long_run.EXIT).exists()
        assert lines == [
            f"started: {shlex.join(cmd)} in {os.getcwd()}, at most 30s",
            f"next: python3 {long_run.LONG_RUN} wait {job}"]
        record = json.loads((job / long_run.JOB).read_text())
        assert (record["argv"], record["cwd"], record["timeout"]) \
            == (cmd, os.getcwd(), 30)
        assert record["pid"] != os.getpid() and record["started"]
        code, text = long_run.wait_job(job, 0)
        assert code == long_run.WAIT_RUNNING
        assert text.splitlines() == [
            "running: 0s of at most 30s",
            f"next: python3 {long_run.LONG_RUN} wait {job}"]
        lines = ended(job)
        assert lines[0].startswith("ended: exit 3 after "), lines
        assert lines[1:] == [f"output: {job / long_run.OUTPUT}", "", "hi",
                             "done"]
        record = json.loads((job / long_run.EXIT).read_text())
        assert (record["code"], record["timed_out"]) == (3, False)
        assert record["seconds"] >= 0.5 and record["started"] \
            and record["ended"]
        assert (job / long_run.SUPERVISOR_LOG).read_text() == ""


def test_a_timeout_kills_the_commands_process_group():
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        pid_file = job / "child.pid"
        start(job, "sh", "-c", f"sleep 30 & echo $! > {pid_file}; wait",
              timeout=0.5)
        lines = ended(job)
        assert lines[0] == "ended: exit 124, timed out after 0.5s", lines
        assert lines[-1] == ("long_run: timed out after 0.5s — the command's "
                             "process group was killed")
        assert json.loads((job / long_run.EXIT).read_text())["timed_out"]
        # the shell's background child went with it
        assert not alive(int(pid_file.read_text()))


def test_a_command_that_cannot_run_exits_127():
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "not-executable.sh"
        script.write_text("#!/bin/sh\necho never\n")
        for argv in (["/nonexistent/command"], [str(script)]):
            job = Path(tmp) / f"job-{Path(argv[0]).name}"
            start(job, *argv)
            lines = ended(job)
            assert lines[0].startswith("ended: exit 127 after "), lines
            assert lines[3].startswith(
                f"long_run: cannot run {argv[0]} in {os.getcwd()}: ")
            assert "never" not in lines


def test_a_second_start_in_a_running_dir_is_refused_and_a_later_one_starts_clean():
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        start(job, "sh", "-c", "echo first; sleep 0.4")
        code, text = long_run.start_job(["echo", "second"], job)
        assert code == 2
        assert text.splitlines() == [
            f"long_run: a job is already running in {job} — wait on it:",
            f"next: python3 {long_run.LONG_RUN} wait {job}"]
        assert ended(job)[3:] == ["first"]
        # ended: a fresh start clears the record and the output first
        start(job, "echo", "second")
        lines = ended(job)
        assert lines[3:] == ["second"]
        assert json.loads((job / long_run.JOB).read_text())["argv"] \
            == ["echo", "second"]


def test_no_command_and_a_dir_that_holds_no_job_are_refused():
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = cli("start", "--dir", tmp)
        assert (code, out) == (2, "")
        assert err.startswith("long_run: no command to run")
        assert cli("start", "--dir", tmp, "--")[0] == 2
        assert not (Path(tmp) / long_run.LOCK).exists()
        code, out, err = cli("wait", tmp, "--for", "0")
        assert (code, out) == (2, "")
        assert err == f"long_run: {Path(tmp)} holds no job — no readable " \
                      "job.json there\n"


def test_a_supervisor_killed_mid_run_leaves_a_job_that_is_gone():
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        pid_file = job / "cmd.pid"
        start(job, "sh", "-c", f"echo $$ > {pid_file}; exec sleep 5")
        deadline = time.monotonic() + 5
        while not (pid_file.exists() and pid_file.read_text().strip()):
            assert time.monotonic() < deadline, "the command never started"
            time.sleep(0.01)
        cmd_pid = int(pid_file.read_text())
        supervisor = json.loads((job / long_run.JOB).read_text())["pid"]
        os.kill(supervisor, signal.SIGKILL)
        try:
            code, text = long_run.wait_job(job, 5)
            assert code == long_run.WAIT_GONE, text
            assert text.splitlines() == [
                "gone: the runner left no exit record",
                f"output: {job / long_run.OUTPUT}"]
        finally:
            # the command is a session of its own, its pid its group's
            with contextlib.suppress(ProcessLookupError):
                os.killpg(cmd_pid, signal.SIGKILL)


def test_the_job_dir_is_ignored_and_a_fresh_one_is_made_when_none_is_given():
    code, text = long_run.start_job(["true"])
    assert code == 0, text
    job = Path(text.splitlines()[1].rpartition(" wait ")[2])
    try:
        assert job.parent == Path(tempfile.gettempdir()).resolve() \
            or job.parent == Path(tempfile.gettempdir())
        assert job.name.startswith("long_run-")
        assert (job / ".gitignore").read_text() == "*\n"
        assert ended(job)[0].startswith("ended: exit 0 after ")
    finally:
        shutil.rmtree(job)


def test_a_caller_names_its_own_next_line_and_what_the_exit_means():
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        code, text = long_run.start_job(
            ["sh", "-c", "sleep 0.3; exit 1"], job, tmp, 30,
            next_line="next: my wait")
        assert (code, text.splitlines()[1]) == (0, "next: my wait")
        assert f" in {Path(tmp)}, at most 30s" in text
        code, text = long_run.wait_job(job, 0, next_line="next: my wait")
        assert (code, text.splitlines()[1]) == (5, "next: my wait")
        code, text = long_run.wait_job(
            job, 10, meaning={1: "red"}.get)
        assert code == 0
        assert text.splitlines()[0].startswith("ended: exit 1 (red) after ")


def test_the_cli_starts_and_waits():
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = cli("start", "--timeout", "5", "--dir", tmp, "--",
                             "sh", "-c", "echo cli -n")
        assert code == 0, err
        assert out.splitlines()[0] == ("started: sh -c 'echo cli -n' in "
                                       f"{os.getcwd()}, at most 5s")
        code, out, err = cli("wait", tmp, "--for", "10")
        assert code == 0, err
        assert out.splitlines()[3:] == ["cli -n"]


def test_a_span_reads_as_minutes_and_seconds():
    assert [long_run.span(s) for s in (0, 45, 60, 372, 3600, 5405)] == [
        "0s", "45s", "1m", "6m12s", "60m", "90m05s"]


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
