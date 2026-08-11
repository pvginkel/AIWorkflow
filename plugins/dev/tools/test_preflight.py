"""Tests for preflight's control-plane check and how it is wired into main.

The subject is `check_kc_status` and its profile membership: a broken control
plane is an *environment* fault (exit 2), it is checked before the repo is
resolved, and triage — which dispatches nothing — is deliberately exempt. The
rest of preflight's checks are not covered here.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_preflight.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import shutil
import subprocess
import types
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parent / "preflight.py"
)
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


class patched:
    """Swap module attributes for a `with` block (this file also runs
    standalone, so no fixtures)."""

    def __init__(self, module, **attrs):
        self.module = module
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        for name, value in self.attrs.items():
            self.saved[name] = getattr(self.module, name)
            setattr(self.module, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(self.module, name, value)
        return False


class fake_subprocess:
    """Stands in for the `subprocess` module: records argv, replays a result."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.result = (returncode, stdout, stderr)
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        code, out, err = self.result
        return subprocess.CompletedProcess(argv, code, out, err)


def run_main(profile, subproc):
    """main() for one profile with `kc` on PATH and a stubbed subprocess.
    Returns (exit_code, stderr) — exit_code None when it passed silently."""
    stderr = io.StringIO()
    kc_on_path = types.SimpleNamespace(which=lambda name: "/usr/local/bin/kc")
    argv = types.SimpleNamespace(profile=profile)
    parser = types.SimpleNamespace(
        add_argument=lambda *a, **k: None, parse_args=lambda: argv)
    fake_argparse = types.SimpleNamespace(ArgumentParser=lambda **k: parser)
    with patched(preflight, subprocess=subproc, shutil=kc_on_path,
                 argparse=fake_argparse):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.main()
            except SystemExit as exit_:
                return exit_.code, stderr.getvalue()
    return None, stderr.getvalue()


HEALTHY = ("worker daemon:  ok (reachable)\n"
           "controller:     ok (reachable, authenticated)\n"
           "environment:    MyApp-1 (running)\n")
DAEMON_DOWN = ("worker daemon:  FAILED (unreachable: connection refused)\n"
               "controller:     ok (reachable, authenticated)\n")


# -- check_kc_status ---------------------------------------------------------

def test_a_healthy_control_plane_passes_silently():
    subproc = fake_subprocess(0, HEALTHY)
    with patched(preflight, subprocess=subproc):
        preflight.check_kc_status()
    assert subproc.calls == [["kc", "status"]]


def test_a_broken_control_plane_is_an_environment_failure():
    """Exit 2, not 1: the project is not the one asked to fix it."""
    subproc = fake_subprocess(1, DAEMON_DOWN)
    stderr = io.StringIO()
    with patched(preflight, subprocess=subproc):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.check_kc_status()
                raise AssertionError("expected SystemExit")
            except SystemExit as exit_:
                assert exit_.code == 2
    assert "connection refused" in stderr.getvalue(), (
        "the report must be relayed — it says which half is down")


def test_a_precondition_failure_speaks_through_stderr():
    """`kc status` prints its health report to stdout but a broken/outdated pod
    (unset env token) to stderr; preflight relays whichever spoke."""
    subproc = fake_subprocess(
        1, "", "kc status is not configured for this pod: "
               "KUBECODER_ENV_TOKEN unset (broken or outdated pod)")
    stderr = io.StringIO()
    with patched(preflight, subprocess=subproc):
        with contextlib.redirect_stderr(stderr):
            try:
                preflight.check_kc_status()
                raise AssertionError("expected SystemExit")
            except SystemExit:
                pass
    assert "KUBECODER_ENV_TOKEN unset" in stderr.getvalue()


# -- profile membership ------------------------------------------------------

def test_plan_and_run_gate_on_the_control_plane_and_triage_does_not():
    """Triage dispatches nothing and touches no kc surface — gating intake on
    live controller reachability would fail work that needs none of it."""
    assert "kc_status" in preflight.PROFILES["plan"]
    assert "kc_status" in preflight.PROFILES["run"]
    assert "kc_status" not in preflight.PROFILES["triage"]


def test_run_gates_on_both_procedure_doc_pointers():
    """The run loop resolves its test and doc phases through these pointers;
    a missing one is caught here, before any session is spawned."""
    assert "testing_strategy" in preflight.PROFILES["run"]
    assert "doc_plan" in preflight.PROFILES["run"]
    assert "Slice doc plan" in preflight.ENTRIES


def test_triage_never_shells_out_to_kc_status():
    """A broken control plane cannot stop intake: triage goes straight from the
    PATH check to the repo (here a failing `git rev-parse`, its own exit 2)."""
    subproc = fake_subprocess(1, DAEMON_DOWN)
    code, message = run_main("triage", subproc)
    assert subproc.calls == [["git", "rev-parse", "--show-toplevel"]]
    assert code == 2 and "control plane" not in message


def test_the_control_plane_is_checked_before_the_repo_is_resolved():
    """Neither environment check needs the repo, and the whole run is doomed
    without a control plane — so it fails there, not on a later git/kc call."""
    for profile in ("plan", "run"):
        subproc = fake_subprocess(1, DAEMON_DOWN)
        code, message = run_main(profile, subproc)
        assert code == 2, f"{profile}: expected exit 2, got {code}"
        assert subproc.calls == [["kc", "status"]], (
            f"{profile}: nothing may run after the control plane fails")
        assert "control plane" in message


# -- one live call -----------------------------------------------------------

def test_against_the_real_kc_status():
    """Pins the invocation to the actual CLI rather than only to the stub: in a
    healthy pod the check passes silently. Skipped where `kc` is absent, or
    where the environment really is unhealthy (that is the check working)."""
    if shutil.which("kc") is None:
        return
    if subprocess.run(["kc", "status"], capture_output=True).returncode != 0:
        return
    preflight.check_kc_status()


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
