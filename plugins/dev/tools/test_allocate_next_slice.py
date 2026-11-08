"""Tests for allocate-next-slice.sh — the spec repo's slice-number allocator.

A throwaway spec tree is built per test (`<ws>/spec/slices/` with the folders
a test needs under backlog/, completed/ and the top level), and the script runs
against it through bash, so the counter file, the disk-max floor and the
`--number` grant or refusal are exercised exactly as /dev:triage meets them.
Every refusal test asserts stdout is empty and `.next-slice` is untouched.

Stdlib only, like the workflow's other suites — `@with_workspace` stands in for
the fixture, so each test still takes `ws` and still collects under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_allocate_next_slice.py` or via pytest.
"""

import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "allocate-next-slice.sh"


def with_workspace(fn):
    """A throwaway directory per test, handed in as `ws`.

    The wrapper takes no arguments, so pytest collects it as a plain test —
    hence no functools.wraps, which would expose the wrapped signature and
    have pytest demand a `ws` fixture this suite does not define.
    """
    def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            fn(Path(tmp))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def make_spec(ws, *folders, counter=None):
    """A spec repo with `slices/<folder>` for each folder, and the counter if given."""
    spec = ws / "spec"
    slices = spec / "slices"
    for sub in ("backlog", "completed", "deferred", "cancelled"):
        (slices / sub).mkdir(parents=True)
    for folder in folders:
        (slices / folder).mkdir(parents=True)
    if counter is not None:
        (slices / ".next-slice").write_text(counter)
    return spec


def run(*args):
    proc = subprocess.run(
        ["bash", str(SCRIPT), *map(str, args)], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout, proc.stderr


def counter(spec):
    path = spec / "slices" / ".next-slice"
    return path.read_text() if path.exists() else None


# --- the plain path ----------------------------------------------------------


@with_workspace
def test_plain_empty_slices_starts_at_001(ws):
    spec = make_spec(ws)
    assert run(spec) == (0, "001\n", "")
    assert counter(spec) == "002\n"
    assert run(spec)[1] == "002\n"
    assert counter(spec) == "003\n"


@with_workspace
def test_plain_floors_at_highest_folder_across_backlog_and_completed(ws):
    spec = make_spec(ws, "backlog/014_later", "completed/021_done", "009_active",
                     counter="004\n")
    assert run(spec) == (0, "022\n", "")
    assert counter(spec) == "023\n"


@with_workspace
def test_plain_skips_a_number_taken_on_disk(ws):
    spec = make_spec(ws, "deferred/007_parked", counter="007\n")
    assert run(spec)[1] == "008\n"
    assert counter(spec) == "009\n"


# --- --number granted --------------------------------------------------------


@with_workspace
def test_number_above_counter_moves_counter_past_it(ws):
    spec = make_spec(ws, counter="005\n")
    assert run(spec, "--number", "010") == (0, "010\n", "")
    assert counter(spec) == "011\n"
    assert run(spec)[1] == "011\n"


@with_workspace
def test_number_below_counter_leaves_counter(ws):
    spec = make_spec(ws, "completed/011_done", counter="012\n")
    assert run(spec, "--number", "3") == (0, "003\n", "")
    assert counter(spec) == "012\n"
    assert run(spec)[1] == "012\n"


@with_workspace
def test_number_without_counter_file_seeds_it(ws):
    spec = make_spec(ws)
    assert run(spec, "--number", "4") == (0, "004\n", "")
    assert counter(spec) == "005\n"


@with_workspace
def test_number_flag_before_or_after_positional(ws):
    spec = make_spec(ws)
    assert run("--number", "20", spec) == (0, "020\n", "")
    assert run(spec, "--number", "30") == (0, "030\n", "")
    assert counter(spec) == "031\n"


@with_workspace
def test_number_leading_zeros_are_decimal(ws):
    spec = make_spec(ws)
    assert run(spec, "--number", "008")[1] == "008\n"
    assert run(spec, "--number", "034")[1] == "034\n"
    assert run(spec, "--number", "09")[1] == "009\n"
    assert counter(spec) == "035\n"


# --- --number refused --------------------------------------------------------


@with_workspace
def test_number_taken_is_refused_wherever_the_folder_lives(ws):
    for i, (folder, seed) in enumerate([
        ("034_active", "040\n"),
        ("backlog/034_queued", "007\n"),
        ("completed/034_shipped", None),
        ("cancelled/034_dropped", "035\n"),
    ]):
        spec = make_spec(ws / str(i), folder, counter=seed)
        code, out, err = run(spec, "--number", "34")
        assert (code, out) == (1, ""), (folder, code, out, err)
        assert "slice 034 is taken" in err and f"slices/{folder}" in err, err
        assert counter(spec) == seed, folder


# --- bad arguments -----------------------------------------------------------


@with_workspace
def test_bad_number_or_argument_is_a_usage_error(ws):
    spec = make_spec(ws)
    for args in (
        ["--number", "abc"],
        ["--number", "0"],
        ["--number", "000"],
        ["--number", "1000"],
        ["--number", "-5"],
        ["--number", ""],
        ["--number"],
        ["--number", "5", "--number", "6"],
        ["--force"],
        ["extra"],
    ):
        code, out, err = run(spec, *args)
        assert (code, out) == (2, ""), (args, code, out, err)
        assert "usage:" in err, (args, err)
        assert counter(spec) is None, args


@with_workspace
def test_missing_spec_repo_or_slices_is_a_usage_error(ws):
    code, out, err = run()
    assert (code, out) == (2, "") and "usage:" in err
    (ws / "notspec").mkdir()
    for target in (ws / "notspec", ws / "absent"):
        code, out, err = run(target)
        assert (code, out) == (2, ""), target
        assert "no slices/" in err
        code, out, _ = run(target, "--number", "5")
        assert (code, out) == (2, ""), target
    assert not (ws / "notspec" / "slices").exists()


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
