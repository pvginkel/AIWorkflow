"""The labeller end to end: the replay check over an invented home, and every verb run as the
collector runs it (docs/labeller.md § The replay check).

The home is invented: transcripts written by the engine suite's `Script` (a dispatch with a
sub-agent, a stage's own session, an old session adopted by what its first prompt names, a
session nobody knows) and run records built by the run records' suite (a slice's plan and run,
its gates and sweeps, `slice.json`, a groups file, a project's file rules). Nothing is read from
or written to the real home. The engine's own suite (`test_labeller_engine.py`) holds the parts
against the whole on its corpus with stand-ins for the records and the tool rules; here the same
comparison runs on real modules throughout, through `labeller.py check` and through JSON on a
subprocess's stdin and stdout.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_labeller_check.py` or via pytest.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_check_{name}", _HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


labeller = _load("labeller")
eng = _load("test_labeller_engine")        # the fixture builder: Script and its corpus
recs = _load("test_labeller_records")      # the run records' builders
import labeller_check  # noqa: E402

SCRIPT = str(_HERE / "labeller.py")
SPEC, K = recs.SPEC, recs.K
GROUP = K


# -- the invented home ---------------------------------------------------------

def _rebased(script, start: str):
    """The script with its times moved to begin at `start`."""
    t0 = datetime.fromisoformat("2026-11-15T10:00:00+00:00")
    shift = datetime.fromisoformat(start) - t0
    for line in script.lines + script.deferred:
        if "timestamp" in line:
            at = datetime.fromisoformat(line["timestamp"].replace("Z", "+00:00")) + shift
            line["timestamp"] = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return script


# `track_build.py`'s summary as it prints it, a build and the pipeline it triggered.
TRACK_SUMMARY = """\
=== Build tracking summary ===
Foo/Build         #7  SUCCESS     4m02s  https://jenkins.example/job/Foo/job/Build/7/
                      \u21b3 queued 2026-11-01T09:04:40Z  started 2026-11-01T09:04:41Z  \
ended 2026-11-01T09:04:50Z
Foo/Build-deploy  #3  SUCCESS     0m40s  https://jenkins.example/job/Foo/job/Build-deploy/3/

Result: all 2 tracked build(s) succeeded.
"""


def _dispatch():
    """P1's first code-writer round, `cw-1`, whose row ends at 09:05 (10:05+01:00): reads, an
    edit, a test suite red and green, a background CI wait read through TaskOutput, a commit."""
    s = eng.Script()
    s.prompt("Run the phase.\n\n# Orientation digest — P1\n## Plan (p)\nx\n## Files\ny\n")
    s.turn(eng.read("/work/Foo/plan.md"))
    s.turn(eng.tool("Agent", {"subagent_type": "Explore", "description": "find"}, "found"))
    s.turn(eng.tool("Edit", {"file_path": "/work/Foo/app.py"}, "ok"))
    s.turn(eng.bash("cd /work/Foo && pytest -q", "Exit code 1\n1 failed, 2 passed in 0.5s",
                    err=True))
    s.turn(eng.bash("cd /work/Foo && pytest -q", "3 passed in 0.5s"))
    (a,) = s.turn(eng.bash("track_build.py Foo/Build --hash c0ffee1", eng.bg_started("ta"),
                           bg=True))
    s.turn(eng.bash("git -C /work/Foo status", "clean"))
    s.note("ta", a, "/tmp/tasks/ta.output")
    s.turn(eng.tool("TaskOutput", {"task_id": "ta"},
                    TRACK_SUMMARY))
    s.turn(eng.bash("while true; do curl -s x && break; sleep 5; done", ""))
    s.turn(eng.bash("git commit -m x -- app.py", "1 file changed"))
    s.turn(text="Done.")
    return _rebased(s, "2026-11-01T09:04:05+00:00")


def _subagent():
    s = eng.s_subagent()
    return _rebased(s, "2026-11-01T09:04:20+00:00")


def _orchestrator():
    """The run stage's own session, `orch-run`: the loop launched and waited on in chunks."""
    s = eng.Script()
    s.prompt("/dev:run-slice 001_one")
    s.turn(eng.bash("python3 /x/tools/run_loop.py run /work/FooSpecs/slices/001_one --detach",
                    "started"))
    for _ in range(3):
        s.turn(eng.bash("python3 /x/tools/run_loop.py wait --slice 001_one", "still running"))
    s.turn(text="The run is done.")
    return _rebased(s, "2026-11-01T09:00:30+00:00")


def _adopted():
    """An old interactive session that ran `/dev:run-slice 001` by hand: R2."""
    s = eng.s_work()
    s.lines.insert(0, {"type": "user", "timestamp": "2026-11-15T10:00:01Z", "cwd": "/work/Foo",
                       "entrypoint": "cli",
                       "message": {"content": "<command-message>dev:run-slice</command-message>"
                                              "\n<command-name>/dev:run-slice</command-name>\n"
                                              "<command-args>001</command-args>"}})
    return _rebased(s, "2026-11-01T12:00:00+00:00")


def _stranger():
    return _rebased(eng.s_waits(), "2026-11-02T08:00:00+00:00")


TRANSCRIPTS = {
    "-work-Foo/cw-1.jsonl": _dispatch,
    "-work-Foo/cw-1/subagents/agent-a1.jsonl": _subagent,
    "-work-Foo/orch-run.jsonl": _orchestrator,
    "-work-Foo/old-1.jsonl": _adopted,
    "-work-Bar/stranger.jsonl": _stranger,
}


@contextlib.contextmanager
def invented_home():
    """(base, the request's `home`): projects, plugins and data folders."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        projects, plugins, data = base / "projects", base / "plugins", base / "data"
        for rel, make in TRANSCRIPTS.items():
            path = projects / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(make().data())
        (projects / "-work-Foo/cw-1/subagents/agent-a1.meta.json").write_text(
            json.dumps({"agentType": "Explore"}))
        plugins.mkdir()
        data.mkdir()
        recs.build(data, run=recs.run_state(copy.deepcopy(recs.RUN_HISTORY)),
                   plan=recs.plan_state(copy.deepcopy(recs.PLAN_HISTORY)),
                   facts=recs.SLICE_JSON)
        recs.write(data / "groups" / f"{SPEC}.toml", recs.GROUPS)
        recs.write(data / "projects" / "Foo.json",
                   {"repo": "Foo", "file_classes": [{"class": "generated",
                                                     "paths": ["schema/*.sql"]}]})
        yield base, {"projects": str(projects), "plugins": str(plugins), "data": str(data)}


def _check(base, *extra):
    out = io.StringIO()
    code = labeller.main(["check", "--projects", str(base / "projects"),
                          "--plugins", str(base / "plugins"), "--data", str(base / "data"),
                          *extra], io.StringIO(""), out)
    return code, out.getvalue().splitlines()


# -- the replay check ----------------------------------------------------------

def test_check_agrees_on_every_transcript_of_the_invented_home():
    with invented_home() as (base, _):
        code, lines = _check(base, "--sample", "0", "--cuts", "4", "--seed", "3")
        rows = [ln for ln in lines if ln.startswith(("ok ", "differs ", "error ", "stamp "))]
        assert code == 0, "\n".join(lines)
        assert len(rows) == len(TRANSCRIPTS) and all(r.startswith("ok") for r in rows), rows
        assert f"{len(TRANSCRIPTS)} transcripts: {len(TRANSCRIPTS)} agree, 0 differ, 0 failed; "\
               "0 stamps not given back" in lines
        assert any(ln.startswith("whole labelling:") for ln in lines)
        assert any(ln.startswith("appended labelling:") for ln in lines)
        assert any(ln.startswith("stamps:") for ln in lines)


def test_check_cuts_before_every_call_under_every_and_at_random_otherwise():
    with invented_home() as (base, _):
        path = base / "projects" / "-work-Foo/cw-1.jsonl"
        calls = len(labeller_check.Facts(path).calls)
        _, lines = _check(base, "--cuts", "2", "--", "-work-Foo/cw-1.jsonl")
        assert f"calls {calls}, cuts {calls - 1 + 2}" in lines[0], lines[0]
        _, lines = _check(base, "--cuts", "2", "--every", "3", str(path))
        assert f"calls {calls}, cuts 4" in lines[0], lines[0]


def test_check_reports_the_first_label_that_differs_and_exits_1():
    """A merge that keeps the first part's Call classes stands for a labeller whose parts
    drift from the whole."""
    real = labeller_check.merge

    def stale(acc, labels, handed, owner):
        out = real(acc, labels, handed, owner)
        if acc is not None:
            was = {c["id"]: c["call_class"] for c in acc["calls"]}
            for c in out["calls"]:
                c["call_class"] = was.get(c["id"], "think")
        return out

    with invented_home() as (base, _):
        labeller_check.merge = stale
        try:
            code, lines = _check(base, "--cuts", "1", "--", "-work-Foo/cw-1.jsonl")
        finally:
            labeller_check.merge = real
        assert code == 1
        assert lines[0].startswith("differs -work-Foo/cw-1.jsonl") and "calls: whole" in lines[0]
        assert "1 transcripts: 0 agree, 1 differ, 0 failed" in "\n".join(lines)


def test_check_takes_paths_from_a_file_and_refuses_one_outside_projects():
    with invented_home() as (base, _):
        listing = base / "paths.txt"
        listing.write_text("-work-Foo/orch-run.jsonl\n\n-work-Bar/stranger.jsonl\n")
        code, lines = _check(base, "--paths", str(listing))
        assert code == 0 and [ln.split()[1] for ln in lines[:2]] == [
            "-work-Foo/orch-run.jsonl", "-work-Bar/stranger.jsonl"]
        code, lines = _check(base, "/etc/passwd")
        assert code == 2 and "is not under" in lines[0]


def test_check_reads_pilots_context_from_a_file():
    sessions = [{"id": "p1", "kind": "work", "created_at": "2026-11-01T09:00:00Z",
                 "brief": "/dev:run-slice 001_one", "repo": "Foo", "clarification": False}]
    with invented_home() as (base, _):
        ctx = base / "context.json"
        ctx.write_text(json.dumps({"pilot": {"conversations": ["orch-run"]},
                                   "conversations": [{"session_id": "orch-run",
                                                      "sessions": sessions, "documents": []}]}))
        code, lines = _check(base, "--context", str(ctx), "--", "-work-Foo/orch-run.jsonl")
        assert code == 0, lines
        code, lines = _check(base, "--context", str(base / "missing.json"))
        assert code == 2


# -- every verb, as the collector runs it --------------------------------------

def verb(name, request) -> tuple[int, list[dict]]:
    done = subprocess.run([sys.executable, "-B", SCRIPT, name], input=json.dumps(request),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode in (0, 2), done.stderr
    return done.returncode, [json.loads(ln) for ln in done.stdout.splitlines()]


def _conversations(base, home, mode="whole", sizes=None, prev=None):
    """The `label` request's conversations for every invented transcript: the Calls the file
    holds, and for `appended` the boundary and checkpoint `prev` handed back."""
    projects = Path(home["projects"])
    convs: dict[str, dict] = {}
    for rel in TRANSCRIPTS:
        ident = labeller_check.identify(projects / rel, projects)
        facts = labeller_check.Facts(projects / rel)
        last = (prev or {}).get((ident["session_id"], ident["agent_id"]))
        item = labeller_check._request_item(ident, facts, facts.size,
                                            last if mode == "appended" else None)
        item.pop("size")
        convs.setdefault(ident["session_id"], {"session_id": ident["session_id"],
                                               "sessions": [], "documents": [],
                                               "transcripts": []})["transcripts"].append(item)
    return list(convs.values())


def _by_transcript(lines):
    return {(ln["session_id"], ln["agent_id"]): ln for ln in lines if "session_id" in ln}


def test_every_verb_end_to_end_over_the_invented_home():
    with invented_home() as (base, home):
        req = {"contract": 1, "home": home}
        # info
        code, (info,) = verb("info", {})
        assert code == 0 and "check" in info["verbs"] and info["contract"] == 1
        # vocabularies: the lists, the nestings and the groups
        code, (vocab,) = verb("vocabularies", req)
        assert code == 0 and vocab["version"] == info["version"]
        assert [g["key"] for g in vocab["groups"]] == [GROUP]
        assert {"inner": "gate", "outer": "phase"} in vocab["nesting"]
        # stamps, never reading a transcript
        convs = _conversations(base, home)
        held = [{"session_id": c["session_id"], "sessions": [], "documents": [],
                 "transcripts": [{"agent_id": t["agent_id"], "held": None,
                                  **({"agent_type": t["agent_type"]} if "agent_type" in t
                                     else {})} for t in c["transcripts"]]} for c in convs]
        code, (st,) = verb("stamps", {**req, "conversations": held})
        assert code == 0 and len(st["stamps"]) == len(TRANSCRIPTS) and st["index"]
        assert all(s["stamp"].startswith("1:") for s in st["stamps"])
        # label whole, with the cut a growing file is met at
        projects = Path(home["projects"])
        full = {rel: (projects / rel).read_bytes() for rel in TRANSCRIPTS}
        for rel, data in full.items():
            starts = labeller_check.Facts(projects / rel).starts()
            cut = starts[len(starts) // 2] if len(starts) > 2 else len(data)
            (projects / rel).write_bytes(data[:cut])
        code, lines = verb("label", {**req, "index": st["index"],
                                     "conversations": _conversations(base, home)})
        assert code == 0 and lines[0] == {"contract": 1, "version": info["version"]}
        assert lines[-1]["done"] and lines[-1]["count"] == len(TRANSCRIPTS)
        first = _by_transcript(lines)
        assert all(ln["answer"] == "labels" for ln in first.values()), first
        # then appended, the boundary and checkpoint handed back
        for rel, data in full.items():
            (projects / rel).write_bytes(data)
        code, lines = verb("label", {**req, "conversations": _conversations(
            base, home, "appended", prev=first)})
        assert code == 0
        appended = _by_transcript(lines)
        code, lines = verb("label", {**req, "conversations": _conversations(base, home)})
        whole = _by_transcript(lines)
        for key, w in whole.items():
            a = appended[key]
            assert a["answer"] == "labels", (key, a)
            ids = {c["id"] for c in a["labels"]["calls"]}
            owner = labeller_check.Facts(projects / next(
                r for r in TRANSCRIPTS if labeller_check.identify(
                    projects / r, projects)["session_id"] == key[0]
                and labeller_check.identify(projects / r, projects)["agent_id"] == key[1])).owner
            merged = labeller_check.merge(first[key]["labels"], a["labels"], ids, owner)
            assert labeller_check.first_difference(w["labels"], merged) is None, key
        # what the labels say of the invented home
        cw = whole[("cw-1", None)]
        assert cw["labels"]["launches"] == [{"n": 1, "work_unit": f"{K}|run|P1|code-writer|1"}]
        assert cw["labels"]["transcript"] == [{"adopted_group": GROUP}]
        assert {u["key"] for u in cw["units"]} >= {K, f"{K}|run", f"{K}|run|P1"}
        assert [(b["job"], b["number"]) for b in cw["ci_builds"]] == [
            ("Foo/Build", 7), ("Foo/Build-deploy", 3)]
        rules = [r for t in cw["labels"]["tool_calls"] for r in t["rules"]]
        assert rules == ["no_sleep_poll"]
        assert [r["passed"] for r in cw["labels"]["test_runs"]] == [False, True]
        sub = whole[("cw-1", "a1")]
        assert sub["labels"]["launches"] == [] and sub["units"] == []
        orch = whole[("orch-run", None)]
        assert {u["kind"] for u in orch["units"]} >= {"stage", "phase", "dispatch", "sweep",
                                                      "gate"}
        old = whole[("old-1", None)]
        assert old["stamp"].endswith(f":{SPEC}/001@run")
        assert old["labels"]["launches"][0]["work_unit"] == f"{K}|run"
        stranger = whole[("stranger", None)]
        assert stranger["labels"]["launches"][0]["work_unit"] is None
        assert stranger["labels"]["transcript"] == [{"adopted_group": None}]
        # label and stamps agree on every stamp, `<named>` carried by the held one
        again = [{**c, "transcripts": [{**t, "held": whole[(c["session_id"],
                                                            t["agent_id"])]["stamp"]}
                                       for t in c["transcripts"]]} for c in held]
        code, (st2,) = verb("stamps", {**req, "conversations": again})
        assert [s["stamp"] for s in st2["stamps"]] == [
            whole[(s["session_id"], s["agent_id"])]["stamp"] for s in st2["stamps"]]
        # classes, the project's own rule first
        code, (cl,) = verb("classes", {**req, "files": [
            ["Foo", "schema/a.sql"], ["Foo", "app/x.py"], ["Foo", "tests/test_x.py"],
            ["FooSpecs", "slices/001_one/plan.md"], ["FooSpecs", "slices/001_one/state.json"],
            ["AIWorkflow", "plugins/dev/tools/test_x.py"], ["AIWorkflow", "plugins/dev/x.md"],
            ["Foo", "README.md"]]})
        assert cl["classes"] == ["generated", "code", "test", "spec", "record", "test", "code",
                                 "docs"]
        assert cl["file_rules"] == st["file_rules"]
        # check, as a script
        done = subprocess.run([sys.executable, "-B", SCRIPT, "check", "--projects",
                               home["projects"], "--plugins", home["plugins"], "--data",
                               home["data"], "--sample", "0", "--cuts", "1"],
                              capture_output=True, text=True, timeout=300)
        assert done.returncode == 0, done.stdout + done.stderr
        assert f"{len(TRANSCRIPTS)} agree" in done.stdout


def test_a_changed_record_changes_the_stamp_and_an_unchanged_one_does_not():
    with invented_home() as (base, home):
        req = {"contract": 1, "home": home}
        convs = [{"session_id": sid, "sessions": [], "documents": [],
                  "transcripts": [{"agent_id": None, "held": None}]}
                 for sid in ("cw-1", "cw-5", "orch-run", "stranger")]

        def stamps():
            code, (ans,) = verb("stamps", {**req, "conversations": convs})
            assert code == 0
            return {s["session_id"]: s["stamp"] for s in ans["stamps"]}

        before = stamps()
        state = Path(home["data"]) / "runs" / SPEC / "001_one" / "state.json"
        run = json.loads(state.read_text())
        run["updated_at"] = "2026-11-01T11:00:00+01:00"          # no derived fact
        run["driver"] = {"pid": 4242}
        for h in run["history"]:
            h["summary"] = "reworded"
        state.write_text(json.dumps(run))
        os.utime(state, ns=(3, 3))
        assert stamps() == before
        run["history"][0]["outcome"] = "blocked"                 # P1's code-writer 1
        state.write_text(json.dumps(run))
        after = stamps()
        assert after["cw-1"] != before["cw-1"] and after["orch-run"] != before["orch-run"]
        assert after["cw-5"] == before["cw-5"] and after["stranger"] == before["stranger"]


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
