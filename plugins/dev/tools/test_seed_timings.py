"""Tests for seed_timings — a repo's old slices read into Pilot's step timings.

The project repo and its spec repo are invented under a temp dir: an
`.aiworkflowrc` naming the spec repo, and state files in the old shapes with
invented rows. HTTP is faked at the opener seam, as test_pilot_progress.py
fakes it: no test reaches a network. Stdlib only; runs standalone and under
pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_seed_timings.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from email.message import Message
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "seed_timings", Path(__file__).resolve().parent / "seed_timings.py"
)
st = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(st)
pp = st.pilot_progress

URL = "http://pilot.invalid/mcp"
TOKEN = "tok-s3cret"
ENV = {"PILOT_TOKEN": TOKEN, "PILOT_MCP_URL": URL}
SPEC = "InventedSpecs"


# -- the invented repos --------------------------------------------------------

def row(role, ts, dur, phase=None, round_=1, **more):
    """A history row; `ts` as `DHHMM` (October's day D, at HH:MM, +02:00) or
    an ISO text given whole."""
    if len(ts) == 5:
        ts = f"2026-10-0{ts[0]}T{ts[1:3]}:{ts[3:]}:00+02:00"
    return {"ts": ts, "phase": phase, "role": role, "round": round_,
            "outcome": more.pop("outcome", "done"), "summary": "invented",
            "session": None, "duration_s": dur, **more}


# Slice 001: two phases it began with, one appended (`appended_phases`); a
# gate-fix round, a review consult, the merge's re-gate, two sweeps, a sweep's
# test-fixer, three consult rows (a session-limit wait among them), two test
# rounds, the doc phase, the wrap-up with its gates and the fixes pass.
ALPHA_RUN = {
    "slice": "001_alpha", "appended_phases": ["3"],
    "fixes": {"started_at": "2026-10-05T09:00:00+02:00"},
    "progress": [{"code": "P1.code", "label": "P1 · One", "state": "done"}],
    "history": [
        row("code-writer", "11000", 100, "1", kind="first"),
        row("gate", "11001", 20, "1", outcome="red"),
        row("test-fixer", "11002", 5, "1"),
        row("code-writer", "11003", 50, "1", 2, kind="gate-fix"),
        row("gate", "11004", 10, "1", 2, outcome="green"),
        row("code-reviewer", "11005", 30, "1", outcome="signoff"),
        row("consult", "11006", 7, "1", site="review-funding"),
        row("gate", "11007", 3, "1", 3, outcome="green"),
        row("code-writer", "11008", 0, "2"),
        row("gate", "11009", 0, "2", outcome="nothing_ran"),
        row("code-reviewer", "11010", 40, "2", outcome="signoff"),
        row("sweep", "21000", 60, outcome="red"),
        row("test-fixer", "21001", 15),
        row("consult", "21002", 12, None, 2, outcome="appended"),
        row("code-writer", "21003", 70, "3"),
        row("gate", "21004", 5, "3", outcome="green"),
        row("code-reviewer", "21005", 25, "3", outcome="signoff"),
        row("sweep", "21006", 40, None, 2, outcome="green"),
        row("consult", "21007", 4, None, 3, outcome="session_limit"),
        row("consult", "21008", 9, None, 4, outcome="complete"),
        row("test-agent", "31000", 300),
        row("test-agent", "31001", 100, None, 2),
        row("doc-writer", "41000", 200),
        row("wrap-up", "41001", 80, kind="first"),
        row("doc-gate", "41002", 30, outcome="green"),
        row("wrap-up-gate", "2026-10-04T12:00:00", 10, outcome="green"),
        row("wrap-up", "51000", 90, kind="fixes"),
        row("fixes-gate", "51001", 20, outcome="green"),
    ],
}
ALPHA_PLAN = {"slice": "001_alpha", "history": [
    row("plan-writer", "10900", 500),
    row("plan-reviewer", "10910", 200, outcome="issues"),
    row("plan-writer", "10920", 100, None, 2),
    row("plan-reviewer", "10930", 50, None, 2, outcome="go"),
]}
# Slice 002: a state from before `appended_phases` and the wrap-up: the phase
# whose first row follows the first sweep is the appended one, and the doc
# gate is the doc phase's.
BETA_RUN = {"slice": "002_beta", "history": [
    row("code-writer", "11000", 60, "1"),
    row("code-reviewer", "11001", 20, "1", outcome="signoff"),
    row("sweep", "11002", 30),
    row("consult", "11003", 6, outcome="appended"),
    row("code-writer", "11004", 40, "2"),
    row("code-reviewer", "11005", 15, "2", outcome="signoff"),
    row("doc-writer", "11006", 90),
    row("doc-gate", "11007", 12, outcome="green"),
]}
# Slice 003: a run published live — its steps carry a kind — beside a plan
# that was not.
LIVE_RUN = {"slice": "003_live", "progress": [
    {"code": "P1.code", "label": "P1 · One", "state": "done",
     "kind": "code-writer"}],
    "history": [row("code-writer", "11000", 60, "1")]}
LIVE_PLAN = {"slice": "003_live", "history": [row("plan-writer", "10900", 70)]}


def make_repos(tmp: Path, slices: dict | None = None) -> Path:
    """The project repo (returned) and its spec repo beside it, with
    `slices`: folder → {file name: an object, or text written as it is}."""
    project = tmp / "project"
    project.mkdir()
    (project / ".aiworkflowrc").write_text(f'spec_repo = "../{SPEC}"\n')
    if slices is None:
        slices = {"001_alpha": {"state.json": ALPHA_RUN,
                                "plan_state.json": ALPHA_PLAN},
                  "002_beta": {"state.json": BETA_RUN},
                  "003_live": {"state.json": LIVE_RUN,
                               "plan_state.json": LIVE_PLAN},
                  "004_broken": {"state.json": "{not json",
                                 "plan_state.json": [1, 2]}}
    for folder, files in slices.items():
        where = tmp / SPEC / "slices" / "completed" / folder
        where.mkdir(parents=True)
        for name, body in files.items():
            (where / name).write_text(body if isinstance(body, str)
                                      else json.dumps(body))
    (tmp / SPEC / "slices" / "backlog" / "009_later").mkdir(parents=True)
    return project


# -- the fake Pilot ------------------------------------------------------------

class FakeResponse:
    def __init__(self, message: dict):
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self._body = json.dumps(message).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePilot:
    """An opener answering `tools/list` with its tools and each seed call
    with the count it took, or with `refuse`; it records every call."""

    def __init__(self, seed=True, refuse=None):
        self.seed, self.refuse = seed, refuse
        self.calls = []    # (method, params, timeout)

    def __call__(self, request, timeout=None):
        body = json.loads(request.data)
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
        self.calls.append((body["method"], body["params"], timeout))
        if body["method"] == "tools/list":
            tools = [{"name": "set_progress", "inputSchema": {}}]
            if self.seed:
                tools.append({"name": "seed_step_timings", "inputSchema": {}})
            result = {"tools": tools}
        elif self.refuse is not None:
            result = {"isError": True,
                      "content": [{"type": "text", "text": self.refuse}]}
        else:
            n = len(body["params"]["arguments"]["timings"])
            result = {"structuredContent": {"timings": n},
                      "content": [{"type": "text",
                                   "text": json.dumps({"timings": n})}]}
        return FakeResponse({"jsonrpc": "2.0", "id": 1, "result": result})

    def seeds(self):
        return [p["arguments"]["timings"] for m, p, _ in self.calls
                if m == "tools/call"]


def run(project: Path, *args, env=None, opener=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = st.main([str(project), *args], environ=ENV if env is None
                       else env, opener=opener)
    return code, out.getvalue(), err.getvalue()


def dry(project: Path) -> tuple[dict, str]:
    code, out, err = run(project, "--dry-run", env={})
    assert code == 0, err
    timings = [json.loads(line) for line in out.splitlines()]
    keys = [t["key"] for t in timings]
    assert len(keys) == len(set(keys))
    return {t["key"]: t for t in timings}, err


def alpha() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return dry(make_repos(Path(tmp)))[0]


def key(slice_name, loop, code):
    return f"{SPEC}/{slice_name}/{loop}/{code}"


# -- the timings ---------------------------------------------------------------

def test_each_step_round_is_one_timing_keyed_by_repo_slice_loop_and_code():
    timings = alpha()
    a = {k.split("/", 2)[2] for k in timings if "/001_alpha/" in k}
    assert a == {"run/P1.code", "run/P1.code-2", "run/P1.review",
                 "run/P2.review", "run/P3.code", "run/P3.review",
                 "run/sweep", "run/sweep-2", "run/consult", "run/consult-2",
                 "run/test", "run/test-2", "run/docs", "run/wrap-up",
                 "run/fixes", "plan/write", "plan/review", "plan/write-2",
                 "plan/review-2"}
    assert not any("ground" in k or "close-out" in k for k in timings)
    assert all(k.startswith(f"{SPEC}/") and len(k) <= st.KEY_MAX
               for k in timings)


def test_a_round_with_no_positive_duration_gives_no_timing():
    timings = alpha()
    assert key("001_alpha", "run", "P2.code") not in timings
    assert key("001_alpha", "run", "P2.review") in timings


def test_the_kind_comes_from_the_one_map_the_plans_review_apart():
    timings = alpha()
    kinds = {k.split("/", 3)[3] if "/run/" in k else "plan:" + k.split("/")[-1]:
             t["kind"] for k, t in timings.items() if "/001_alpha/" in k}
    assert kinds["P1.code-2"] == "code-writer"
    assert kinds["P1.review"] == "review"
    assert kinds["plan:review"] == kinds["plan:review-2"] == "plan-review"
    assert kinds["plan:write"] == "plan-writer"
    assert (kinds["sweep"], kinds["consult-2"], kinds["test-2"],
            kinds["docs"], kinds["wrap-up"], kinds["fixes"]) == (
        "sweep", "consult", "test", "docs", "wrap-up", "fixes")
    for k, t in timings.items():
        loop, code = k.split("/")[2], k.split("/")[3]
        assert t["kind"] == pp.kind_of(code, loop)


def test_the_duration_is_the_sum_of_the_rounds_rows_gates_and_fixers_folded():
    timings = alpha()

    def d(loop, code):
        return timings[key("001_alpha", loop, code)]["duration"]

    assert d("run", "P1.code") == 100 + 20 + 5      # its gate and gate fixer
    assert d("run", "P1.code-2") == 50 + 10
    assert d("run", "P1.review") == 30 + 7 + 3      # its consult, the re-gate
    assert d("run", "P3.code") == 70 + 5
    assert d("run", "sweep") == 60 + 15             # the sweep's test-fixer
    assert d("run", "consult") == 12
    assert d("run", "consult-2") == 4 + 9           # a session-limit wait
    assert d("run", "test-2") == 100
    assert d("run", "docs") == 200
    assert d("run", "wrap-up") == 80 + 30 + 10      # the doc gate, its gate
    assert d("run", "fixes") == 90 + 20
    assert (d("plan", "write"), d("plan", "review-2")) == (500, 50)
    assert all(isinstance(t["duration"], int) for t in timings.values())


def test_ended_at_is_the_last_rows_ts_with_its_offset_naive_taken_as_utc():
    timings = alpha()
    assert timings[key("001_alpha", "run", "P1.review")]["ended_at"] == \
        "2026-10-01T10:07:00+02:00"
    assert timings[key("001_alpha", "run", "wrap-up")]["ended_at"] == \
        "2026-10-04T12:00:00+00:00"
    assert all(isinstance(t["ended_at"], str) and t["ended_at"][-6] in "+-"
               for t in timings.values())


def test_listed_ahead_for_the_seeded_list_not_a_repeat_or_an_appended_phase():
    timings = alpha()

    def ahead(loop, code, slice_name="001_alpha"):
        return timings[key(slice_name, loop, code)]["listed_ahead"]

    for code in ("P1.code", "P1.review", "P2.review", "sweep", "consult",
                 "test", "docs", "wrap-up", "fixes"):
        assert ahead("run", code) is True, code
    for code in ("P1.code-2", "P3.code", "P3.review", "sweep-2", "consult-2",
                 "test-2"):
        assert ahead("run", code) is False, code
    assert ahead("plan", "write") and ahead("plan", "review")
    assert not ahead("plan", "write-2") and not ahead("plan", "review-2")
    # A state with no `appended_phases`: the phase begun after the first
    # sweep is the appended one; the doc gate there is the doc phase's.
    assert ahead("run", "P1.code", "002_beta") is True
    assert ahead("run", "P2.code", "002_beta") is False
    assert ahead("run", "P2.review", "002_beta") is False
    assert timings[key("002_beta", "run", "docs")]["duration"] == 90 + 12
    assert key("002_beta", "run", "wrap-up") not in timings


def test_a_file_published_live_is_skipped_and_a_broken_one_reported():
    with tempfile.TemporaryDirectory() as tmp:
        timings, err = dry(make_repos(Path(tmp)))
    assert not any("/003_live/run/" in k for k in timings)
    assert key("003_live", "plan", "write") in timings
    assert "004_broken/state.json skipped: not JSON" in err
    assert "004_broken/plan_state.json skipped: not a JSON object" in err
    assert "slices read 4 (7 state files), skipped 1 published live and " \
        "2 unreadable" in err
    assert not any("009_later" in k for k in timings)


def test_a_long_key_is_cut_to_the_limit_and_stays_unique():
    long_name = "005_" + "x" * 220
    a = st.make_key(SPEC, long_name, "run", "P1.code")
    b = st.make_key(SPEC, long_name, "run", "P1.code-2")
    assert len(a) == len(b) == st.KEY_MAX and a != b


# -- the command ---------------------------------------------------------------

def test_dry_run_prints_the_timings_and_sends_nothing_without_credentials():
    with tempfile.TemporaryDirectory() as tmp:
        project = make_repos(Path(tmp))
        pilot = FakePilot()
        code, out, err = run(project, "--dry-run", env={}, opener=pilot)
        assert code == 0 and pilot.calls == []
        lines = [json.loads(line) for line in out.splitlines()]
        assert lines and set(lines[0]) == {"key", "kind", "ended_at",
                                           "duration", "listed_ahead"}
        assert "dry run, nothing sent" in err
        code, _, err = run(project, "--dry-run", "--json", env={})
        summary = json.loads(err.strip().splitlines()[-1])
        assert summary["timings"] == len(lines) and summary["sent"] is None


def test_it_sends_once_the_tool_is_listed_and_prints_what_pilot_wrote():
    with tempfile.TemporaryDirectory() as tmp:
        project = make_repos(Path(tmp))
        expected, _ = dry(project)
        pilot = FakePilot()
        code, out, err = run(project, "--json", opener=pilot)
    assert code == 0, err
    assert [m for m, _, _ in pilot.calls] == ["tools/list", "tools/call"]
    assert all(t == pp.SEED_TIMEOUT for _, _, t in pilot.calls)
    [sent] = pilot.seeds()
    assert {t["key"]: t for t in sent} == expected
    summary = json.loads(out)
    assert summary["sent"] == summary["written"] == len(expected)
    assert TOKEN not in out + err


def test_more_than_a_thousand_timings_go_in_calls_of_at_most_a_thousand():
    phases = [str(i) for i in range(1, 602)]
    big = {"slice": "006_big", "history": [
        r for p in phases for r in (row("code-writer", "11000", 10, p),
                                    row("code-reviewer", "11001", 5, p))]}
    with tempfile.TemporaryDirectory() as tmp:
        project = make_repos(Path(tmp), {"006_big": {"state.json": big}})
        pilot = FakePilot()
        code, out, err = run(project, opener=pilot)
    assert code == 0, err
    assert [len(b) for b in pilot.seeds()] == [1000, 202]
    assert "sent 1202, Pilot wrote 1202" in out
    assert st.batches(list(range(2000))) == [list(range(1000)),
                                             list(range(1000, 2000))]


def test_a_refusal_exits_non_zero_with_the_reason_and_never_the_token():
    with tempfile.TemporaryDirectory() as tmp:
        project = make_repos(Path(tmp))
        pilot = FakePilot(refuse=f"work item has no repo ({TOKEN})")
        code, out, err = run(project, opener=pilot)
    assert code == 1
    assert "refused timings 1-" in err and "work item has no repo" in err
    assert TOKEN not in out + err


def test_no_answer_exits_non_zero():
    def down(request, timeout=None):
        raise OSError("connection refused")

    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = run(make_repos(Path(tmp)), opener=down)
    assert code == 1 and "could not be listed (no_answer)" in err


def test_a_pilot_without_the_tool_exits_2_and_sends_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        pilot = FakePilot(seed=False)
        code, _, err = run(make_repos(Path(tmp)), opener=pilot)
    assert code == 2 and "does not list seed_step_timings" in err
    assert [m for m, _, _ in pilot.calls] == ["tools/list"]


def test_no_credentials_or_no_config_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        project = make_repos(Path(tmp))
        code, _, err = run(project, env={}, opener=FakePilot())
        assert code == 2 and "PILOT_MCP_URL and PILOT_TOKEN" in err
        (project / ".aiworkflowrc").unlink()
        code, _, _ = run(project, "--dry-run", env={})
        assert code == 2


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
