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
import re
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

# The other README shape in the field (AnsibleSpecs): Pending bullets carry the
# id as a link, and Completed is a four-column table. Assembled from parts
# because the real lines run well past this repo's 100-column limit — the text
# is verbatim, the wrapping is ours.
_PENDING_010 = (
    "- **[010](slices/backlog/010_kubecoder_deploy_repo/slice.md)** — "
    "KubeCoderDeploy repo and image pinning: the pilot's chart, rebuilt "
    "Terraform and stage config, plus the seven `Build-Main` pins "
    "(phases.md B.1+B.2; #124)."
)
_PENDING_014 = (
    "- **[014](slices/backlog/014_pam_credentials/plan.md)** — PAM "
    "credentials: the `pam | ansible` split (#131),\n"
    "  with the vault rotation folded in."
)
_ROW_013 = (
    "| [013 iac-pipeline-restructure]"
    "(slices/completed/013_iac_pipeline_restructure/plan.md) "
    "| `iac-pipeline-restructure.md` (P1 superseded by tf-provider-registry) "
    "| tf-provider-registry "
    "| gated the `iac-image` rebuild on its real image inputs and folded the "
    "`IaCAgent` tree into `support/iac-agent/` with its 28 commits preserved "
    "— shipped 2026-08-13 (#70) |"
)

README_TABLE = f"""\
# AnsibleSpecs — specs

Source of truth.

## Pending

These live in `slices/backlog/` or, once planned, directly in `slices/`.

{_PENDING_010}
{_PENDING_014}

## Completed

| Slice | Was | Depends on | Consumed by |
|---|---|---|---|
{_ROW_013}
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
                   location="slices", files=("slice.md", "state.json")):
    spec = ws / "specs"
    (spec / "slices" / "completed").mkdir(parents=True)
    (spec / "README.md").write_text(readme)
    slice_dir = spec / location / slice_name
    slice_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        (slice_dir / name).write_text("{}\n" if name.endswith(".json")
                                      else f"# {name}\n")
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
def test_link_wrapped_bullet_moves_with_rewritten_links(ws):
    """The entry travels as it reads, minus its links to the old location."""
    readme = README.replace(
        "- **116** — Toolchain home-overlay sweep: single-line entry (#251).",
        "- **[116](slices/backlog/116_toolchain_sweep/slice.md)** — Toolchain "
        "home-overlay sweep:\n"
        "  see `slices/116_toolchain_sweep/notes.md` (#251).")
    spec, slice_dir = make_spec_repo(ws, readme=readme,
                                     location="slices/backlog")
    assert run_cli(str(slice_dir))[0] == 0
    parts = sections((spec / "README.md").read_text())
    assert parts["## Completed"][-2:] == [
        "- **[116](slices/completed/116_toolchain_sweep/slice.md)** — "
        "Toolchain home-overlay sweep:",
        "  see `slices/completed/116_toolchain_sweep/notes.md` (#251).",
    ]
    assert not any("**[116]" in line for line in parts["## Pending"])
    assert (spec / "slices" / "completed" / "116_toolchain_sweep").is_dir()


# ---------------------------------------------------------------------------
# A table-shaped `## Completed` (the AnsibleSpecs shape)
# ---------------------------------------------------------------------------

def table_rows(text):
    """The rows of the README's Completed table, header and separator included."""
    return [line for line in sections(text)["## Completed"]
            if line.strip().startswith("|")]


def row_cells(line):
    """A row's cells — unlike the tool's own naive split, this one honours the
    `\\|` a description may carry, which is exactly what the tests check."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    return [part.strip() for part in parts[1:-1]]


@with_workspace
def test_table_completed_gets_a_synthesized_row(ws):
    spec, slice_dir = make_spec_repo(ws, readme=README_TABLE,
                                     slice_name="014_pam_credentials",
                                     location="slices/backlog",
                                     files=("plan.md", "slice.md"))
    code, out, _ = run_cli(str(slice_dir))
    assert code == 0

    text = (spec / "README.md").read_text()
    rows = table_rows(text)
    assert len(rows) == 4  # header, separator, 013, the new one
    cells = row_cells(rows[-1])
    assert len(cells) == len(row_cells(rows[0])) == 4
    # plan.md wins over slice.md; the slug is the folder minus its number
    assert cells[0] == ("[014 pam-credentials]"
                        "(slices/completed/014_pam_credentials/plan.md)")
    assert cells[1:3] == ["—", "—"]
    # continuation folded in, the description's own pipe escaped
    assert cells[3] == (r"PAM credentials: the `pam \| ansible` split (#131), "
                        "with the vault rotation folded in.")
    # the existing row is untouched and still last-but-one
    assert rows[2] == _ROW_013

    parts = sections(text)
    assert not any("**[014]" in line for line in parts["## Pending"])
    assert _PENDING_010 in parts["## Pending"]
    assert (spec / "slices" / "completed" / "014_pam_credentials"
            / "plan.md").is_file()
    assert not slice_dir.exists()
    assert "README.md" in staged(spec)
    assert "synthesized table row" in out


@with_workspace
def test_table_row_links_the_brief_when_there_is_no_plan(ws):
    spec, slice_dir = make_spec_repo(ws, readme=README_TABLE,
                                     slice_name="010_kubecoder_deploy_repo",
                                     location="slices/backlog",
                                     files=("slice.md",))
    assert run_cli(str(slice_dir))[0] == 0
    cells = row_cells(table_rows((spec / "README.md").read_text())[-1])
    assert cells[0] == ("[010 kubecoder-deploy-repo]"
                        "(slices/completed/010_kubecoder_deploy_repo/slice.md)")
    assert cells[3].startswith("KubeCoderDeploy repo and image pinning:")
    assert cells[3].endswith("(phases.md B.1+B.2; #124).")


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
def test_entry_already_in_completed_table_exits_two(ws):
    spec, slice_dir = make_spec_repo(
        ws, readme=README_TABLE, slice_name="013_iac_pipeline_restructure")
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "already listed under `## Completed`" in err
    assert slice_dir.is_dir()
    assert_untouched(spec, before, before_status)


@with_workspace
def test_letter_suffixed_slice_folder_exits_two(ws):
    """`182b_…` is not slice 182 — that prefix match moved the wrong entry."""
    spec, slice_dir = make_spec_repo(ws, slice_name="182b_x")
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "letter-suffixed slice ids are not supported" in err
    assert "whole numbers" in err
    assert slice_dir.is_dir()
    assert_untouched(spec, before, before_status)


@with_workspace
def test_suffixed_bullet_is_not_matched_for_the_plain_number(ws):
    """`- **063b** — …` must not answer for slice 063, in either direction."""
    readme = README.replace("- **063** —", "- **063b** —")
    spec, slice_dir = make_spec_repo(ws, readme=readme,
                                     slice_name="063_store_hardening")
    before, before_status = (spec / "README.md").read_text(), status(spec)
    code, _, err = run_cli(str(slice_dir))
    assert code == 2
    assert "no `- **063**" in err
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
