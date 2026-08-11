"""Tests for close_slice — the mechanical /dev:run-slice close-out step.

A throwaway spec repo is built per test (real `git init`, a README shaped like
the real one, a slice folder under `slices/`), so the README surgery and the
`git mv` are exercised against git itself. Every precondition test asserts the
tool changed NOTHING.

Stdlib only, like the workflow's other suites — `@with_workspace` stands in for
the fixture, so each test still takes `ws` and still collects under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_close_slice.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "close_slice", Path(__file__).resolve().parent / "close_slice.py"
)
close_slice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(close_slice)
Precondition = close_slice.Precondition


README = """\
# MyApp — specs

Source of truth.

## Folder layout

Slices live under `slices/`.

## Pending

These live in `slices/backlog/` or, once planned, directly in `slices/`.

- **063** — Store hardening: per-record read-modify-write lock + unique tmp,
  projection fault isolation; server only (R-006..R-010; D129).
- **116** — Toolchain home-overlay sweep: single-line entry (#251).
- **121** — `cli describe`: instruction fields + resource limits (#297).

## Deferred

- **auto-recreate** (#31) — arch-design chose a server-side reconcile.

## Completed

- **001** — Wire contracts → codegen: drift-gated generated contracts (D067).
- **002** — Worker port: the worker is a static binary (#28; D068).
"""


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

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


@contextlib.contextmanager
def raises(exc):
    try:
        yield
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def run_cli(*argv):
    """main() with its streams captured — (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = close_slice.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def make_spec_repo(ws, readme=README, slice_name="116_toolchain_sweep",
                   location="slices"):
    spec = ws / "specs"
    (spec / "slices" / "completed").mkdir(parents=True)
    (spec / "README.md").write_text(readme)
    slice_dir = spec / location / slice_name
    slice_dir.mkdir(parents=True, exist_ok=True)
    (slice_dir / "slice.md").write_text("# slice\n")
    (slice_dir / "state.json").write_text("{}\n")
    subprocess.run(["git", "init", "-q", "-b", "main", str(spec)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(spec), "config", key, value],
                       check=True)
    subprocess.run(["git", "-C", str(spec), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(spec), "commit", "-qm", "seed"],
                   check=True)
    return spec, slice_dir


def sections(text):
    """{heading: [lines]} for the README's two lifecycle sections."""
    out, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line.strip()
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def staged(spec):
    return subprocess.run(
        ["git", "-C", str(spec), "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True).stdout.split()


def status(spec):
    return subprocess.run(["git", "-C", str(spec), "status", "--porcelain"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@with_workspace
def test_happy_path_moves_entry_folder_and_stages_readme(ws):
    spec, slice_dir = make_spec_repo(ws)
    code, out, _ = run_cli(str(slice_dir))
    assert code == 0

    text = (spec / "README.md").read_text()
    parts = sections(text)
    assert not any("**116**" in line for line in parts["## Pending"])
    completed = [line for line in parts["## Completed"] if line.strip()]
    assert completed[-1] == (
        "- **116** — Toolchain home-overlay sweep: single-line entry (#251).")
    # the untouched neighbours keep their order and text
    assert "- **063** — Store hardening: per-record read-modify-write lock " \
           "+ unique tmp," in parts["## Pending"]
    assert "- **121** — `cli describe`: instruction fields + resource " \
           "limits (#297)." in parts["## Pending"]

    moved = spec / "slices" / "completed" / "116_toolchain_sweep"
    assert (moved / "slice.md").is_file() and (moved / "state.json").is_file()
    assert not slice_dir.exists()

    # README staged by name, the rename staged by `git mv`, nothing committed
    assert set(staged(spec)) == {
        "README.md",
        "slices/completed/116_toolchain_sweep/slice.md",
        "slices/completed/116_toolchain_sweep/state.json",
    }
    assert text.endswith("\n")

    assert "git mv slices/116_toolchain_sweep → " \
           "slices/completed/116_toolchain_sweep" in out
    assert "Pending → Completed" in out
    assert "staged README.md" in out


@with_workspace
def test_multiline_entry_moves_verbatim(ws):
    spec, slice_dir = make_spec_repo(ws, slice_name="063_store_hardening")
    assert run_cli(str(slice_dir))[0] == 0
    parts = sections((spec / "README.md").read_text())
    assert parts["## Completed"][-2:] == [
        "- **063** — Store hardening: per-record read-modify-write lock "
        "+ unique tmp,",
        "  projection fault isolation; server only (R-006..R-010; D129).",
    ]
    assert not any("**063**" in line for line in parts["## Pending"])
    assert (spec / "slices" / "completed" / "063_store_hardening").is_dir()


@with_workspace
def test_backlog_slice_closes_out_too(ws):
    spec, slice_dir = make_spec_repo(ws, location="slices/backlog")
    assert run_cli(str(slice_dir))[0] == 0
    assert (spec / "slices" / "completed" / "116_toolchain_sweep").is_dir()
    assert not any("**116**" in line for line
                   in sections((spec / "README.md").read_text())["## Pending"])


@with_workspace
def test_spec_root_resolution_is_robust(ws):
    spec, slice_dir = make_spec_repo(ws, location="slices/backlog")
    assert close_slice.spec_root_for(slice_dir.resolve()) == spec.resolve()
    with raises(Precondition):
        close_slice.spec_root_for(ws / "elsewhere" / "116_x")


# ---------------------------------------------------------------------------
# Preconditions — each must change nothing
# ---------------------------------------------------------------------------

def assert_untouched(spec, before_readme, before_status):
    assert (spec / "README.md").read_text() == before_readme
    assert status(spec) == before_status


@with_workspace
def test_missing_readme_entry_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws, slice_name="999_unlisted")
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "no `- **999**" in err
    assert slice_dir.is_dir()
    assert_untouched(spec, before, before_status)


@with_workspace
def test_missing_slice_folder_exits_two(ws):
    spec, _ = make_spec_repo(ws)
    before, before_status = (spec / "README.md").read_text(), status(spec)
    ghost = spec / "slices" / "121_absent"
    code, _, err = run_cli(str(ghost))
    assert code == 2
    assert "not found" in err
    assert_untouched(spec, before, before_status)


@with_workspace
def test_already_completed_folder_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws, location="slices/completed")
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "already under slices/completed/" in err
    assert slice_dir.is_dir()
    assert_untouched(spec, before, before_status)


@with_workspace
def test_entry_already_in_completed_exits_two(ws):
    readme = README.replace(
        "- **002** — Worker port",
        "- **116** — Toolchain home-overlay sweep: already listed.\n"
        "- **002** — Worker port")
    spec, slice_dir = make_spec_repo(ws, readme=readme)
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "already listed under `## Completed`" in err
    assert slice_dir.is_dir()
    assert_untouched(spec, before, before_status)


@with_workspace
def test_destination_already_exists_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws)
    (spec / "slices" / "completed" / "116_toolchain_sweep").mkdir()
    before = (spec / "README.md").read_text()
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "already exists" in err
    assert (slice_dir / "slice.md").is_file()
    assert (spec / "README.md").read_text() == before
    assert staged(spec) == []


@with_workspace
def test_missing_readme_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws)
    (spec / "README.md").unlink()
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "spec README not found" in err
    assert slice_dir.is_dir()


@with_workspace
def test_readme_without_the_sections_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws, readme="# specs\n\nno sections\n")
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "has no `## Pending` section" in err
    assert slice_dir.is_dir()


@with_workspace
def test_unnumbered_slice_folder_exits_two(ws):
    spec, slice_dir = make_spec_repo(ws, slice_name="scratch_notes")
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "does not start with a slice number" in err


@with_workspace
def test_slice_outside_a_slices_tree_exits_two(ws):
    stray = ws / "elsewhere" / "116_stray"
    stray.mkdir(parents=True)
    code, _, err = run_cli(str(stray))
    assert code == 2
    assert "not inside a slices/ tree" in err


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
