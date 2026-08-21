"""Tests for sweep_slice — the residual-sweep slice generator.

A throwaway workspace is built per test: a spec repo (real `git init`, a
README shaped like the real one, a slices/ tree) plus a code repo whose
`.aiworkflowrc` points at it, so allocation, README surgery and staging run
git itself. `dry_run` is stubbed where a test doesn't own it — the real thing
shells out to run_loop.py and needs `kc`; the drivability property it guards
is asserted directly instead, via run_loop's own parse_plan.

Stdlib only, like the workflow's other suites — `@with_workspace` stands in
for the fixture, so each test still takes `ws` and still collects under
pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_sweep_slice.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sweep_slice", Path(__file__).resolve().parent / "sweep_slice.py"
)
sweep_slice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep_slice)
Precondition = sweep_slice.Precondition

from run_loop import parse_plan  # noqa: E402, I001  (sweep_slice put the dir on sys.path)


README = """\
# MyApp — specs

Source of truth.

## Pending

These live in `slices/backlog/` or, once planned, directly in `slices/`.

- **092** — Worker robustness residuals: notify delivered-count gating (#143),
  transcript-summary mtime cache (#144).
- **116** — Toolchain home-overlay sweep: single-line entry (#251).

## Deferred

- **auto-recreate** (#31) — arch-design chose a server-side reconcile.
"""


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

def with_workspace(fn):
    """A throwaway directory per test, handed in as `ws`."""
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


@contextlib.contextmanager
def stubbed_dry_run(stub=lambda slice_dir, code_root: None):
    original = sweep_slice.dry_run
    sweep_slice.dry_run = stub
    try:
        yield
    finally:
        sweep_slice.dry_run = original


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def make_workspace(ws, readme=README):
    """A spec repo (with one taken slice number, 116) and a code repo whose
    `.aiworkflowrc` points at it. Returns (spec, code_root)."""
    spec = ws / "specs"
    (spec / "slices" / "backlog").mkdir(parents=True)
    (spec / "slices" / "116_toolchain_sweep").mkdir()
    (spec / "slices" / "116_toolchain_sweep" / "slice.md").write_text("# s\n")
    (spec / "README.md").write_text(readme)
    subprocess.run(["git", "init", "-q", "-b", "main", str(spec)], check=True)
    for key, value in (("user.email", "t@t"), ("user.name", "t")):
        _git(spec, "config", key, value)
    _git(spec, "add", "-A")
    _git(spec, "commit", "-qm", "seed")

    code = ws / "code"
    code.mkdir()
    (code / ".aiworkflowrc").write_text(f'spec_repo = "{spec}"\n')
    return spec, code


def make_items(n=5):
    """n single-criterion items on n distinct cards. Bodies deliberately
    carry a `###` heading and a `Target:` line — hostile plan input."""
    return [{
        "card": 400 + k,
        "card_name": f"Card {400 + k} title",
        "card_url": f"https://trello.com/c/x{k}",
        "title": f"Fix thing {k}",
        "target": "root",
        "body": (f"Body of card {400 + k}.\n\n### Not a phase heading\n"
                 "Target: not-a-target\n"),
        "acceptance_criteria": [f"Outcome {k} holds."],
    } for k in range(n)]


def write_payload(ws, items, **extra):
    path = ws / "payload.json"
    path.write_text(json.dumps({"items": items, **extra}))
    return path


def run_sweep(payload, code_root, force=False):
    with contextlib.redirect_stdout(io.StringIO()):
        return sweep_slice.file_sweep(payload, code_root, force=force)


def staged(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True).stdout.split()


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

@with_workspace
def test_payload_rejects_missing_fields(ws):
    for key in ("card_name", "card_url", "title", "target", "body"):
        items = make_items(1)
        del items[0][key]
        with raises(Precondition):
            sweep_slice.load_payload(write_payload(ws, items))


@with_workspace
def test_payload_rejects_empty_or_missing_criteria(ws):
    for acs in ([], ["  "], None):
        items = make_items(1)
        items[0]["acceptance_criteria"] = acs
        with raises(Precondition):
            sweep_slice.load_payload(write_payload(ws, items))


@with_workspace
def test_payload_rejects_multiline_single_line_fields(ws):
    for key in ("card_name", "title", "target"):
        items = make_items(1)
        items[0][key] = "two\nlines"
        with raises(Precondition):
            sweep_slice.load_payload(write_payload(ws, items))


@with_workspace
def test_payload_rejects_bad_slug_and_bad_card(ws):
    with raises(Precondition):
        sweep_slice.load_payload(write_payload(ws, make_items(1), slug="Bad Slug"))
    items = make_items(1)
    items[0]["card"] = "449"
    with raises(Precondition):
        sweep_slice.load_payload(write_payload(ws, items))


# ---------------------------------------------------------------------------
# Artifact generation — the generated plan must be drivable
# ---------------------------------------------------------------------------

def test_generated_plan_parses_with_hostile_card_bodies():
    items = make_items(6)
    artifacts = sweep_slice.build_artifacts("137", items)
    phases, errors = parse_plan(artifacts["plan.md"])
    assert errors == [], errors
    assert [p.id for p in phases] == [str(k + 1) for k in range(6)]
    assert all(p.target == "root" for p in phases)
    assert not any(p.done for p in phases)


def test_verification_items_map_criteria_one_to_one():
    items = make_items(2)
    items[1]["acceptance_criteria"] = ["First outcome.", "Second outcome."]
    artifacts = sweep_slice.build_artifacts("137", items)
    verification = json.loads(artifacts["verification.json"])
    ids = [item["id"] for item in verification["items"]]
    assert ids == ["V01", "V02", "V03"]
    assert verification["items"][2]["area"] == "card #401 (P2)"
    assert verification["items"][2]["description"] == "Second outcome."
    assert all(item["verdict"] is None for item in verification["items"])
    # plan.md cites each phase's criteria range
    assert "criteria V02–V03" in artifacts["plan.md"]


def test_record_quotes_bodies_and_lists_cards():
    artifacts = sweep_slice.build_artifacts("137", make_items(2))
    assert "> Body of card 400." in artifacts["slice.md"]
    assert "> Body of card 400." in artifacts["plan.md"]
    assert "#400 #401" in artifacts["slice.md"]


# ---------------------------------------------------------------------------
# README surgery
# ---------------------------------------------------------------------------

def test_pending_bullet_appends_at_section_end():
    bullet = sweep_slice.pending_bullet("137", make_items(5))
    updated = sweep_slice.insert_pending(README, bullet)
    lines = updated.splitlines()
    at = lines.index(bullet[0])
    assert "single-line entry (#251)." in lines[at - 1]
    assert lines[at + len(bullet) :][:2] == ["", "## Deferred"]
    assert "#400 #401 #402 #403 #404" in " ".join(bullet)


def test_insert_pending_requires_the_section():
    with raises(Precondition):
        sweep_slice.insert_pending("# specs\n\n## Completed\n", ["- **1** — x."])


# ---------------------------------------------------------------------------
# Filing end-to-end (dry_run stubbed; its property is tested above)
# ---------------------------------------------------------------------------

@with_workspace
def test_file_sweep_files_a_run_ready_slice(ws):
    spec, code = make_workspace(ws)
    payload = write_payload(ws, make_items(5))
    with stubbed_dry_run():
        slice_dir = run_sweep(payload, code)
    assert slice_dir == spec / "slices" / "117_residual_sweep"
    for name in ("slice.md", "plan.md", "verification.json"):
        assert (slice_dir / name).is_file(), name
    phases, errors = parse_plan((slice_dir / "plan.md").read_text())
    assert errors == [] and len(phases) == 5
    assert "- **117** — Residual sweep: 5 Solution Known" \
        in (spec / "README.md").read_text()
    assert sorted(staged(spec)) == sorted([
        "README.md",
        "slices/117_residual_sweep/slice.md",
        "slices/117_residual_sweep/plan.md",
        "slices/117_residual_sweep/verification.json",
    ])


@with_workspace
def test_floor_counts_distinct_cards_and_force_overrides(ws):
    spec, code = make_workspace(ws)
    items = make_items(4) + [dict(make_items(1)[0], title="Second half")]
    payload = write_payload(ws, items)  # 5 items, 4 distinct cards
    with stubbed_dry_run():
        with raises(Precondition):
            run_sweep(payload, code)
        assert not (spec / "slices" / "117_residual_sweep").exists()
        run_sweep(payload, code, force=True)
    assert (spec / "slices" / "117_residual_sweep" / "plan.md").is_file()


@with_workspace
def test_ceiling_counts_phases_and_force_overrides(ws):
    spec, code = make_workspace(ws)
    payload = write_payload(ws, make_items(11))  # 11 items, 11 distinct cards
    with stubbed_dry_run():
        with raises(Precondition):
            run_sweep(payload, code)
        assert not (spec / "slices" / "117_residual_sweep").exists()
        run_sweep(payload, code, force=True)
        # Ten phases is the last size that files unforced — in a second
        # workspace, the forced filing above having taken 117 in the first.
        ten_spec, ten_code = make_workspace(ws / "ten")
        run_sweep(write_payload(ws / "ten", make_items(10)), ten_code)
    assert (spec / "slices" / "117_residual_sweep" / "plan.md").is_file()
    assert (ten_spec / "slices" / "117_residual_sweep" / "plan.md").is_file()


@with_workspace
def test_refuses_a_spec_repo_off_main(ws):
    spec, code = make_workspace(ws)
    _git(spec, "checkout", "-q", "-b", "phase/135-P2")
    with stubbed_dry_run(), raises(Precondition):
        run_sweep(write_payload(ws, make_items(5)), code)
    assert not (spec / "slices" / "117_residual_sweep").exists()


@with_workspace
def test_dry_run_failure_leaves_folder_but_stages_nothing(ws):
    spec, code = make_workspace(ws)

    def boom(slice_dir, code_root):
        raise Precondition("rejected")

    with stubbed_dry_run(boom), raises(Precondition):
        run_sweep(write_payload(ws, make_items(5)), code)
    assert (spec / "slices" / "117_residual_sweep" / "plan.md").is_file()
    assert staged(spec) == []
    assert "117" not in (spec / "README.md").read_text()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
