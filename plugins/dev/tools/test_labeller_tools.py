"""labeller_tools.py — the labeller's rules of one Tool Call (labeller.md, Part 3).

Every fixture is invented: the project `Orchard`, its deploy repo, its jobs and its tests exist
nowhere. Their shapes are the real ones: `track_build.py`'s summary before and after DI-42 (the
times under each row and each Application), the test runners' summaries as pytest (plain and
xdist, with the detect-flakes mode's section), Playwright's list reporter, vitest, `go test`,
`node --test` and `kc project test`'s own per-component lines print them.
"""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "labeller_tools", Path(__file__).resolve().parent / "labeller_tools.py")
lt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lt)

REPO = "/work/Orchard"
T0, T1 = "2026-11-15T10:00:00.000Z", "2026-11-15T10:04:30.000Z"


def _ctx(**kw):
    return lt.ToolCtx(**{"cwd": REPO, "requested_at": T0, "result_at": T1, **kw})


def _bash(cmd, result="", **kw):
    inp = {"command": cmd}
    if kw.pop("background", False):
        inp["run_in_background"] = True
    return lt.tool_labels("Bash", inp, result, _ctx(**kw))


def _cls(cmd):
    return lt.command_class(cmd, REPO)


# -- command class ------------------------------------------------------------

def test_each_rule_of_the_command_class_list():
    cases = {
        "timeout 3600 track_build.py Orchard/Build-Main --hash 1a2b3c4": "ci_wait",
        "python3 ~/.local/bin/track_build.py Orchard --buildnr 12": "ci_wait",
        "python3 /x/plugins/dev/tools/run_loop.py wait --slice 7": "chunked_wait",
        '"/x/tools/plan_loop.py" wait': "chunked_wait",
        "python3 /x/tools/long_run.py wait --id 3": "chunked_wait",
        "python3 /x/tools/run_loop.py gate P2": "gate",
        "python3 /x/tools/spec_check.py --slice 7": "gate",
        "kc project test --project backend": "test_suite",
        "pytest -q tests/": "test_suite",
        "python3 -m pytest -x": "test_suite",
        "cd sidecar && go test ./...": "test_suite",
        "npx playwright test tests/a.spec.ts": "test_suite",
        "pnpm -C frontend exec playwright test": "test_suite",
        "npm test": "test_suite",
        "npm run test -- --watch=false": "test_suite",
        "pnpm --dir frontend test": "test_suite",
        "uv run --with pytest python3 tools/test_a.py": "test_suite",
        "vitest run": "test_suite",
        "npx vitest --run src/": "test_suite",
        "pnpm -C frontend exec vitest run": "test_suite",
        "node --test tests/": "test_suite",
        "node --experimental-strip-types --test": "test_suite",
        "yarn test": "test_suite",
        "yarn --cwd web run test:unit": "test_suite",
        "yarn workspace web test": "test_suite",
        "node scripts/build.js --test": None,
        "kc project lint": "gate",
        "kc project build --project frontend": "gate",
        "uv run ruff check .": "gate",
        "mypy app": "gate",
        "pnpm exec tsc --noEmit": "gate",
        "golangci-lint run": "gate",
        "ansible-lint site.yml": "gate",
        "sleep 30": "sleep_poll",
        "until curl -s localhost:8080; do sleep 2; done": "sleep_poll",
        "git -C /work/Orchard status": "git",
        "ls -la": None,
        "python3 tools/test_a.py": None,
    }
    for cmd, want in cases.items():
        assert _cls(cmd) == want, (cmd, _cls(cmd))


def test_the_first_rule_that_holds_decides():
    assert _cls("git pull && kc project test; sleep 5") == "test_suite"
    assert _cls("kc project lint && kc project test") == "test_suite"
    assert _cls("sleep 60; track_build.py Orchard --hash abcd123") == "ci_wait"
    assert _cls("git add x && python3 /x/run_loop.py gate P1") == "gate"
    assert _cls("ruff check . && uv run --with pytest pytest") == "test_suite"


def test_wrappers_hide_no_program():
    assert _cls("cexec python uv run --with pytest pytest plugins -q") == "test_suite"
    assert _cls("cexec go sh -c 'cd /work/Orchard/sidecar && go test ./...'") == "test_suite"
    assert _cls("FOO=1 timeout -k 5 600 env BAR=2 pytest") == "test_suite"
    assert _cls("cd /tmp && timeout 1500 track_build.py Orchard --hash abcd123 > /tmp/t.log 2>&1"
                ) == "ci_wait"


def test_a_program_named_in_quoted_text_or_a_heredoc_does_not_count():
    assert _cls("echo 'run pytest and go test later'") is None
    assert _cls('git commit -m "run kc project test before sleep 5"') == "git"
    assert _cls("cat > /tmp/notes.md <<'EOF'\npytest -q\nsleep 30\ntrack_build.py X\nEOF") is None
    assert _cls("grep -n 'track_build.py' docs/x.md") is None


# -- effects --------------------------------------------------------------------

def _mcp(name, inp, result, **kw):
    return lt.tool_labels(name, inp, result, _ctx(**kw))


def test_a_created_card_takes_its_id_from_the_result():
    out = _mcp("mcp__youtrack__create_issue", {"project": "OR", "summary": "x"},
               [{"type": "text", "text": '{"id":"OR-41"}'}])
    assert (out["effect_kind"], out["effect_subject"]) == ("card_created", "OR-41")
    out = _mcp("mcp__tracker__create_issue", {}, '{"id":"OR-42"}')       # any server's name
    assert (out["effect_kind"], out["effect_subject"]) == ("card_created", "OR-42")


def test_an_updated_or_commented_card_takes_its_id_from_the_input():
    for tool in ("mcp__youtrack__update_issue", "mcp__youtrack__add_comment"):
        out = _mcp(tool, {"id": "OR-7", "text": "x"}, '{"id":"OR-7","comment_id":"7-1"}')
        assert (out["effect_kind"], out["effect_subject"]) == ("card_updated", "OR-7")


def test_a_fieldnote_is_posted_only_where_the_result_names_a_new_one():
    out = _mcp("mcp__fieldnotes__post", {"text": "x"}, '{"id":"01ABC"}')
    assert (out["effect_kind"], out["effect_subject"]) == ("fieldnote_posted", "01ABC")
    matched = _mcp("mcp__fieldnotes__post", {"text": "x"},
                   '{"id":null,"candidates":[{"id":"01OLD"}]}')
    assert matched["effect_kind"] is None


def test_a_registered_document_takes_its_path():
    path = "/work/OrchardSpecs/slices/backlog/003_x/asks/1-requirements.md"
    out = _mcp("mcp__pilot__register_document", {"path": path}, '{"id":"d-1"}')
    assert (out["effect_kind"], out["effect_subject"]) == ("document_registered", path)


def test_a_failed_call_has_no_effect():
    out = _mcp("mcp__youtrack__create_issue", {}, "Error: project not found", is_error=True)
    assert out["effect_kind"] is None
    out = _mcp("mcp__youtrack__update_issue", {"id": "OR-1"}, '{"error":"no such issue"}')
    assert out["effect_kind"] is None


def test_a_push_that_exited_zero_is_a_push():
    out = _bash("git push origin main", "To github.com:x/Orchard.git\n   1a2b..3c4d  main -> main")
    assert (out["effect_kind"], out["effect_subject"]) == ("push", None)
    assert out["command_class"] == "git"
    assert _bash("git push", "Exit code 1\n! [rejected] main -> main (fetch first)",
                 is_error=True)["effect_kind"] is None
    assert _bash("git push --dry-run", "")["effect_kind"] is None
    assert _bash("git push; echo done", " ! [rejected]        main -> main (non-fast-forward)\n"
                 "error: failed to push some refs\ndone")["effect_kind"] is None
    assert _bash("echo 'git push later'", "git push later")["effect_kind"] is None


# -- rules --------------------------------------------------------------------

def test_a_poll_loop_breaches_no_sleep_poll_and_a_settle_sleep_does_not():
    for cmd in ("while true; do kc env describe; sleep 20; done",
                "until curl -s localhost:8080; do sleep 2; done",
                "for i in 1 2 3; do curl -s x && break; sleep 5; done",
                "timeout 60 bash -c 'while ! curl -s x; do sleep 1; done'"):
        assert _bash(cmd)["rules"] == ["no_sleep_poll"], cmd
    for cmd in ("kc project test; sleep 5", "sleep 30", "sleep 3 && curl -s localhost:8080",
                "for f in a b; do sleep 1; done", "for f in a b; do echo $f; done; sleep 2",
                "cat <<'EOF'\nwhile true; do sleep 1; x; done\nEOF"):
        assert _bash(cmd)["rules"] == [], cmd
    assert _cls("sleep 3 && curl -s localhost:8080") == "sleep_poll"


def test_staging_everything_breaches_no_git_add_all():
    for cmd in ("git add -A", "git add --all", "git add .", "git -C /work/Orchard add -A",
                "git commit -am 'x'", "git commit -a -m x", "git commit --all -m x",
                "cd /work/OrchardSpecs && git add -A && git commit -m x"):
        assert "no_git_add_all" in _bash(cmd)["rules"], cmd
    for cmd in ("git add a.py b.py", "git commit -m 'a.' -- a.py", "git commit --amend",
                "git commit -m add", "echo 'git add -A'"):
        assert "no_git_add_all" not in _bash(cmd)["rules"], cmd


def test_o9_is_one_switch():
    """Until O9 is ruled any tree counts; ruled the other way, only a spec repo's."""
    cmd = "cd /work/Orchard && git add -A"
    spec = "cd /work/OrchardSpecs && git add -A"
    saved = lt.ADD_ALL_ONLY_IN_SPEC_REPO
    try:
        lt.ADD_ALL_ONLY_IN_SPEC_REPO = True
        repos = frozenset({"OrchardSpecs"})
        assert _bash(cmd, spec_repos=repos)["rules"] == []
        assert _bash(spec, spec_repos=repos)["rules"] == ["no_git_add_all"]
    finally:
        lt.ADD_ALL_ONLY_IN_SPEC_REPO = saved
    assert _bash(cmd)["rules"] == ["no_git_add_all"]


def test_a_tail_of_a_file_a_running_background_task_writes():
    writing = frozenset({"/tmp/claude-1/tasks/b1.output", "/tmp/orchard-track.log"})
    for cmd in ("tail -20 /tmp/claude-1/tasks/b1.output", "tail -n 5 /tmp/orchard-track.log",
                "cd /tmp && tail -f orchard-track.log"):
        assert _bash(cmd, background_writes=writing)["rules"] == ["no_tail_on_background_log"]
    assert _bash("tail -20 /tmp/other.log", background_writes=writing)["rules"] == []
    assert _bash("cat /tmp/orchard-track.log", background_writes=writing)["rules"] == []
    assert _bash("tail -20 /tmp/orchard-track.log")["rules"] == []      # that task has ended


# -- background tasks and reads -----------------------------------------------

BG_RESULT = ("Command running in background with ID: b7q2x9k. Output is being written to: "
             "/tmp/claude-1000/-work-Orchard/s1/tasks/b7q2x9k.output. You will be notified when "
             "it completes.")


def test_a_background_call_names_its_task_and_what_it_writes():
    out = _bash("cd /tmp && timeout 1500 track_build.py Orchard --hash abcd123 > track.log 2>&1",
                BG_RESULT, background=True)
    assert out["background"] == {
        "task_id": "b7q2x9k",
        "output_file": "/tmp/claude-1000/-work-Orchard/s1/tasks/b7q2x9k.output",
        "writes": ["/tmp/claude-1000/-work-Orchard/s1/tasks/b7q2x9k.output", "/tmp/track.log"]}
    assert _bash("ls")["background"] is None


def test_what_a_call_read():
    assert _bash("cat /tmp/track.log | tail -40")["reads"] == {
        "paths": ["/tmp/track.log"], "task_ids": []}
    reads = _bash("tail -12 /tmp/track.log; date")["reads"]
    assert reads == {"paths": ["/tmp/track.log"], "task_ids": []}
    out = lt.tool_labels("TaskOutput", {"task_id": "b7q2x9k", "block": True}, "", _ctx())
    assert out["reads"] == {"paths": [], "task_ids": ["b7q2x9k"]}
    out = lt.tool_labels("BashOutput", {"bash_id": "b7q2x9k"}, "", _ctx())
    assert out["reads"]["task_ids"] == ["b7q2x9k"]
    out = lt.tool_labels("Read", {"file_path": "/tmp/x/tasks/b7q2x9k.output"}, "", _ctx())
    assert out["reads"]["paths"] == ["/tmp/x/tasks/b7q2x9k.output"]


# -- track_build.py's summary ---------------------------------------------------

SUMMARY_DI42 = """\
[10:01:02] Resolving Orchard/Build-Main build for commit 1a2b3c4…
[10:01:09] Orchard/Build-Main #212 SUCCESS (8m30s)
=== Build tracking summary ===
Orchard/Build-Main  #212  SUCCESS     8m30s  https://jenkins.example/job/Orchard/job/Build-Main/212/
                          ↳ queued 2026-11-15T10:00:40Z  started 2026-11-15T10:00:52Z\
  ended 2026-11-15T10:09:22Z

Result: all 1 tracked build(s) succeeded.

=== Argo CD follow ===
OrchardDeploy 9f8e7d6 pushed to main, pins config/dev/values.yaml, config/prd/values.yaml\
 (Orchard/Build-Main #212)
  orchard-dev  rolled  Synced at 9f8e7d6, health Healthy
               ↳ sync 2026-11-15T10:09:30Z–2026-11-15T10:09:51Z, roll ended 2026-11-15T10:10:14Z

Result: rolled — Argo CD runs the handed-off commit, or a later one, on orchard-dev.
"""

SUMMARY_OLD_TRIGGERED = """\
=== Build tracking summary ===
Orchard/Images  #3105  SUCCESS     2m34s  https://jenkins.example/job/Orchard/job/Images/3105/
Infra/Charts    #7710  SUCCESS     1m31s  https://jenkins.example/job/Infra/job/Charts/7710/

Events:
  - #3104 superseded by #3105

Result: all 2 tracked build(s) succeeded.
exit=0
"""

SUMMARY_FAILED = """\
=== Build tracking summary ===
Orchard/Build-Main  #213  FAILURE     3m31s  https://jenkins.example/job/Orchard/job/Build-Main/213/
                          ↳ queued 2026-11-15T11:00:00Z  started ?  ended ?
                          ↳ full log: /tmp/track_build/Orchard_Build-Main_213.log

Result: 1 of 1 tracked build(s) did NOT succeed.

=== Failure tail: Orchard/Build-Main #213 (FAILURE) ===
FAILED tests/test_a.py::test_b - assert 1 == 2
"""

SUMMARY_NOTHING_PUSHED = """\
=== Build tracking summary ===
Orchard/Build-Main  #214  SUCCESS     8m02s  https://jenkins.example/job/Orchard/job/Build-Main/214/
                          ↳ queued 2026-11-15T12:00:00Z  started 2026-11-15T12:00:05Z\
  ended 2026-11-15T12:08:07Z

Result: all 1 tracked build(s) succeeded.

=== Argo CD follow ===
OrchardDeploy already carries these pins, nothing pushed; main is at 9f8e7d6\
 (Orchard/Build-Main #214)
  orchard-dev  current  Synced at 9f8e7d6, health Healthy (at the commit)

Result: nothing to wait for — no handoff pushed a commit an Application follows.
"""


def test_a_foreground_wait_with_di42_times_and_a_rolled_deploy():
    out = _bash("timeout 3600 track_build.py Orchard/Build-Main --hash 1a2b3c4", SUMMARY_DI42)
    assert out["command_class"] == "ci_wait"
    assert out["ci_wait"] == {"job": "Orchard/Build-Main", "background": False,
                              "named": [{"job": "Orchard/Build-Main", "commit": "1a2b3c4"}]}
    assert out["ci_builds"] == [{
        "job": "Orchard/Build-Main", "number": 212, "result": "SUCCESS",
        "queued_at": "2026-11-15T10:00:40Z", "started_at": "2026-11-15T10:00:52Z",
        "ended_at": "2026-11-15T10:09:22Z", "commit": "1a2b3c4", "deployed_at": T1}]
    (summary,) = out["ci_summaries"]
    (app,) = summary["follow"]["handoffs"][0]["apps"]
    assert app == {"app": "orchard-dev", "state": "rolled",
                   "sync_started_at": "2026-11-15T10:09:30Z",
                   "sync_ended_at": "2026-11-15T10:09:51Z",
                   "roll_ended_at": "2026-11-15T10:10:14Z"}         # parsed, unused (O5)


def test_an_older_summary_has_no_times_and_a_triggered_pipeline_is_a_build_of_its_own():
    out = _bash("track_build.py Orchard/Images --hash cafe123 --appear-timeout 900 "
                "> /tmp/t.log 2>&1; echo exit=$?; tail -40 /tmp/t.log", SUMMARY_OLD_TRIGGERED)
    assert [(b["job"], b["number"], b["commit"], b["queued_at"], b["deployed_at"])
            for b in out["ci_builds"]] == [("Orchard/Images", 3105, "cafe123", None, None),
                                           ("Infra/Charts", 7710, None, None, None)]
    assert out["ci_summaries"][0]["superseded"] == [{"job": None, "old": 3104, "new": 3105}]


def test_a_failed_build_and_a_question_mark_give_no_time():
    out = _bash("track_build.py Orchard/Build-Main --buildnr 213 --diagnose", SUMMARY_FAILED,
                is_error=True)
    (b,) = out["ci_builds"]
    assert (b["result"], b["commit"], b["queued_at"], b["started_at"], b["ended_at"]) == (
        "FAILURE", None, "2026-11-15T11:00:00Z", None, None)
    assert b["deployed_at"] is None
    assert out["events"] == []                    # a red build is no gate


def test_a_handoff_that_pushed_nothing_deploys_nothing():
    out = _bash("track_build.py Orchard/Build-Main --hash 5e6f7a8", SUMMARY_NOTHING_PUSHED)
    (b,) = out["ci_builds"]
    assert b["deployed_at"] is None and b["started_at"] == "2026-11-15T12:00:05Z"


def test_a_wait_whose_summary_never_came_keeps_its_class_and_makes_no_build():
    interrupted = "[10:01:02] Resolving Orchard/Build-Main build for commit 1a2b3c4…\n" \
                  "[10:31:02] Orchard/Build-Main #212 building…\nExit code 124"
    out = _bash("timeout 1800 track_build.py Orchard/Build-Main --hash 1a2b3c4", interrupted,
                is_error=True)
    assert out["command_class"] == "ci_wait" and out["ci_builds"] == []
    assert out["ci_wait"]["named"] == [{"job": "Orchard/Build-Main", "commit": "1a2b3c4"}]
    out = _bash("track_build.py --help", "usage: track_build.py [-h] [--hash SHA] …")
    assert out["command_class"] == "ci_wait" and out["ci_builds"] == []


def test_a_deploy_wait_names_no_job_and_no_commit():
    out = _bash("track_build.py --deploy OrchardDeploy main " + "a" * 40,
                "\n=== Argo CD follow ===\nOrchardDeploy aaaaaaa pushed to main (--deploy)\n")
    assert out["ci_wait"]["named"] == [{"job": None, "commit": None}]
    assert out["ci_builds"] == [] and out["ci_summaries"] == []


def test_a_hash_the_shell_computes_is_no_commit():
    out = _bash('track_build.py Orchard --hash "$(git rev-parse HEAD)"', "")
    assert out["ci_wait"]["named"] == [{"job": "Orchard", "commit": None}]
    out = _bash("SHA=1a2b3c4; track_build.py Orchard --hash=$SHA", "")
    assert out["ci_wait"]["named"] == [{"job": "Orchard", "commit": "1a2b3c4"}]


def test_a_background_wait_makes_its_builds_where_its_summary_is_read():
    wait = _bash("timeout 5400 track_build.py Orchard/Build-Main --hash 1a2b3c4", BG_RESULT,
                 background=True)
    assert wait["ci_wait"]["background"] and wait["ci_builds"] == []
    assert wait["background"]["task_id"] == "b7q2x9k"
    read = _bash(f"cat {wait['background']['output_file']}", SUMMARY_DI42)
    assert read["command_class"] is None and read["ci_builds"] == []
    assert read["reads"]["paths"] == [wait["background"]["output_file"]]
    (summary,) = read["ci_summaries"]
    assert summary["job"] == "Orchard/Build-Main"
    notified = "2026-11-15T10:10:20.000Z"
    (b,) = lt.ci_builds(wait["ci_wait"], summary, notified)
    assert (b["commit"], b["deployed_at"]) == ("1a2b3c4", notified)


def test_a_summary_read_through_the_read_tool_loses_its_line_numbers():
    numbered = "\n".join(f"{n:>6}\t{ln}" for n, ln in enumerate(SUMMARY_DI42.splitlines(), 1))
    out = lt.tool_labels("Read", {"file_path": "/tmp/x.output"}, numbered, _ctx())
    (summary,) = out["ci_summaries"]
    assert summary["builds"][0]["ended_at"] == "2026-11-15T10:09:22Z"
    assert summary["follow"]["rolled"]
    arrow = "\n".join(f"{n:>6}→{ln}" for n, ln in enumerate(SUMMARY_DI42.splitlines(), 1))
    assert lt.parse_track_summary(arrow)[0]["builds"][0]["number"] == 212


def test_the_source_of_track_build_is_no_summary():
    code = ('    print("=== Build tracking summary ===")\n'
            "    for name, build, logfile in rows:\n")
    assert lt.parse_track_summary(code) == []


def test_deployed_at_is_the_wait_s_return_until_o5_is_ruled_otherwise():
    assert lt.deployed_at("2026-11-15T10:10:20Z", "2026-11-15T10:10:14Z") == "2026-11-15T10:10:20Z"


# -- test runner summaries ------------------------------------------------------

PYTEST_PASS = """\
........................................................................ [ 59%]
.................................................                        [100%]
121 passed in 4.11s
"""

PYTEST_FAIL = """\
=================================== FAILURES ===================================
____________________________ test_a_pear_is_ripe _____________________________
tests/test_fruit.py:12: in test_a_pear_is_ripe
    assert pear.ripe
E   assert False
=========================== short test summary info ============================
FAILED tests/test_fruit.py::test_a_pear_is_ripe - assert False
ERROR tests/test_basket.py::test_weight - fixture 'scale' not found
============ 1 failed, 40 passed, 2 skipped, 1 error, 3 warnings in 1.90s ============
"""

PYTEST_XDIST = """\
created: 8/8 workers
8 workers [300 items]

[gw3] [ 40%] PASSED tests/test_tree.py::test_grows
[gw1] [ 41%] FAILED tests/test_tree.py::test_sheds[autumn]
[gw0] [ 42%] PASSED tests/test_tree.py::test_roots
=========================== short test summary info ============================
FAILED tests/test_tree.py::test_sheds[autumn] - AssertionError
================== 1 failed, 297 passed, 2 xfailed in 35.21s (0:00:35) ===================
"""

PYTEST_FLAKES = """\
........R..R.R.R.F.......                                                [100%]
================================ detect-flakes =================================
FLAKY tests/test_fruit.py::test_an_apple_falls - passed only on a rerun
FAILED tests/test_fruit.py::test_a_plum_rots - failed every attempt
NOT RERUN tests/test_fruit.py::test_a_fig_dries - failed once, past the cap
🔁 The run is red: 1 test passed only on a rerun, named FLAKY above. A test named FAILED\
 failed every attempt.
=========================== short test summary info ============================
FAILED tests/test_fruit.py::test_a_plum_rots - assert False
FAILED tests/test_fruit.py::test_a_fig_dries - assert False
============= 2 failed, 120 passed, 4 rerun in 9.80s ==============
"""

PLAYWRIGHT_RED = """\
Running 132 tests using 4 workers

  ✓  1 [chromium] › tests/orchard/rows.spec.ts:10:3 › Rows › a new row is shown (1.2s)
  ✘  2 [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes (30.1s)
  ✘  3 [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes (retry #1) (30.2s)
  ✘  4 [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes (retry #2) (30.0s)
  ✘  5 [chromium] › tests/orchard/fruit.spec.ts:7:3 › Fruit › a ripe pear is picked (4.0s)
  ✓  6 [chromium] › tests/orchard/fruit.spec.ts:7:3 › Fruit › a ripe pear is picked\
 (retry #1) (3.9s)

  1) [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes ──────────────

    Error: expect(locator).toBeVisible() failed

  1 failed
    [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes
  1 flaky
    [chromium] › tests/orchard/fruit.spec.ts:7:3 › Fruit › a ripe pear is picked
  3 skipped
  127 passed (7.6m)

  🔁 The run is red: 1 test passed only on a rerun, named flaky above. A test named failed\
 failed every attempt.
 ELIFECYCLE  Command failed with exit code 1.
"""

PLAYWRIGHT_GREEN = """\
Running 12 tests using 2 workers
  12 passed (41.0s)
"""

VITEST_RED = """\
 ❯ tests/unit/basket.test.ts (12 tests | 1 failed) 40ms
   × Basket > weighs its fruit 3ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  tests/unit/basket.test.ts > Basket > weighs its fruit
AssertionError: expected 3 to be 4

 Test Files  1 failed | 4 passed (5)
      Tests  1 failed | 100 passed (101)
   Start at  10:24:45
   Duration  619ms
"""

GO_PLAIN = """\
--- FAIL: TestPruneKeepsTheTrunk (0.05s)
    prune_test.go:139: trunk cut
FAIL
FAIL\texample.org/orchard/prune\t0.119s
ok  \texample.org/orchard/rows\t1.490s
ok  \texample.org/orchard/soil\t(cached)
?   \texample.org/orchard/cmd\t[no test files]
FAIL
"""

GO_VERBOSE = """\
=== RUN   TestRows
--- PASS: TestRows (0.00s)
=== RUN   TestSoil
=== RUN   TestSoil/clay
    --- FAIL: TestSoil/clay (0.00s)
--- FAIL: TestSoil (0.00s)
=== RUN   TestSun
--- SKIP: TestSun (0.00s)
FAIL
FAIL\texample.org/orchard/soil\t0.010s
"""

NODE = """\
ℹ tests 14
ℹ suites 3
ℹ pass 14
ℹ fail 0
ℹ cancelled 0
"""


def _runs(cmd, text, **kw):
    return _bash(cmd, text, **kw)["test_runs"]


def test_pytest_plain_passes():
    (run,) = _runs("cd /work/Orchard && uv run pytest -q", PYTEST_PASS)
    assert run == {"suite": "Orchard/pytest", "passed": True, "tests": 121,
                   "retries_allowed": None, "started_at": T0, "ended_at": T1, "failures": []}
    assert _bash("pytest -q", PYTEST_PASS)["test_suites"] == [
        {"code": "Orchard/pytest", "name": "Orchard pytest"}]


def test_pytest_names_its_failures_and_errors():
    (run,) = _runs("pytest", PYTEST_FAIL, is_error=True)
    assert (run["passed"], run["tests"]) == (False, 44)
    assert run["failures"] == [
        {"test": "tests/test_fruit.py::test_a_pear_is_ripe", "attempts": 1, "flaky": False},
        {"test": "tests/test_basket.py::test_weight", "attempts": 1, "flaky": False}]


def test_pytest_on_xdist():
    (run,) = _runs("pytest -n 8 -v", PYTEST_XDIST)
    assert (run["passed"], run["tests"]) == (False, 300)
    assert [f["test"] for f in run["failures"]] == ["tests/test_tree.py::test_sheds[autumn]"]


def test_pytest_in_the_detect_flakes_mode():
    (run,) = _runs("pytest", PYTEST_FLAKES, is_error=True)
    assert (run["passed"], run["tests"]) == (False, 122)
    got = {f["test"].rsplit("::", 1)[1]: (f["attempts"], f["flaky"]) for f in run["failures"]}
    assert got == {"test_a_plum_rots": (1, False), "test_a_fig_dries": (1, False),
                   "test_an_apple_falls": (2, True)}
    (run,) = _runs("pytest --reruns 2", PYTEST_FLAKES, is_error=True)
    assert run["retries_allowed"] == 2


def test_pytest_reruns_shown_give_the_retries_and_the_attempts():
    text = ("tests/test_a.py::test_x RERUN\ntests/test_a.py::test_x RERUN\n"
            "tests/test_a.py::test_x FAILED\n"
            "FAILED tests/test_a.py::test_x - failed every attempt\n"
            "1 failed, 9 passed, 2 rerun in 0.50s\n")
    (run,) = _runs("pytest -v", text)
    assert run["retries_allowed"] == 2
    assert run["failures"] == [{"test": "tests/test_a.py::test_x", "attempts": 3,
                                "flaky": False}]
    no_lines = "FAILED tests/test_a.py::test_x - failed every attempt\n" \
               "1 failed, 9 passed, 2 rerun in 0.50s\n"
    (run,) = _runs("pytest", no_lines)
    assert run["retries_allowed"] == 2 and run["failures"][0]["attempts"] == 3


def test_playwright_failed_flaky_and_the_run_red():
    (run,) = _runs("cd frontend && pnpm exec playwright test", PLAYWRIGHT_RED, is_error=True)
    assert (run["suite"], run["passed"], run["tests"]) == ("Orchard/playwright", False, 132)
    assert run["retries_allowed"] == 2
    assert run["failures"] == [
        {"test": "tests/orchard/trees.spec.ts › Trees › a felled tree goes", "attempts": 3,
         "flaky": False},
        {"test": "tests/orchard/fruit.spec.ts › Fruit › a ripe pear is picked", "attempts": 2,
         "flaky": True}]


def test_playwright_green_and_its_retries_flag():
    (run,) = _runs("npx playwright test --retries=1", PLAYWRIGHT_GREEN)
    assert (run["passed"], run["tests"], run["retries_allowed"]) == (True, 12, 1)
    flaky_only = PLAYWRIGHT_RED.replace("  1 failed\n    [chromium] › tests/orchard/trees.spec.ts"
                                        ":44:5 › Trees › a felled tree goes\n",
                                        "").replace("  🔁 The run is red", "  done")
    (run,) = _runs("npx playwright test", flaky_only)
    assert run["passed"]                        # a flake alone passes a run that is not red


def test_vitest():
    (run,) = _runs("npm test", VITEST_RED, is_error=True)
    assert (run["suite"], run["passed"], run["tests"]) == ("Orchard/vitest", False, 101)
    assert run["failures"] == [{"test": "tests/unit/basket.test.ts > Basket > weighs its fruit",
                                "attempts": 1, "flaky": False}]


def test_go_test_counts_its_packages_or_with_v_its_tests():
    (run,) = _runs("cd /work/Orchard/sidecar && go test ./...", GO_PLAIN, is_error=True)
    assert (run["suite"], run["passed"], run["tests"]) == ("Orchard/go", False, 3)
    assert run["failures"] == [{"test": "example.org/orchard/prune.TestPruneKeepsTheTrunk",
                                "attempts": 1, "flaky": False}]
    (run,) = _runs("go test -v ./soil", GO_VERBOSE)
    assert (run["passed"], run["tests"]) == (False, 3)
    assert [f["test"] for f in run["failures"]] == ["example.org/orchard/soil.TestSoil"]
    (run,) = _runs("go test ./...", "ok  \texample.org/orchard/rows\t1.490s\n")
    assert (run["passed"], run["tests"]) == (True, 1)


def test_node_test():
    (run,) = _runs("npm test", NODE)
    assert (run["suite"], run["passed"], run["tests"]) == ("Orchard/node", True, 14)


def test_a_grep_of_a_log_is_read_without_its_line_numbers():
    text = "".join(f"{n}:{ln}\n" for n, ln in enumerate(PYTEST_FAIL.splitlines(), 300))
    (run,) = _runs("pytest > /tmp/p.log 2>&1; grep -n 'FAILED\\|passed' /tmp/p.log", text)
    assert (run["tests"], len(run["failures"])) == (44, 2)


def test_a_coloured_summary_is_read_without_its_colours():
    text = ("\x1b[31mFAILED\x1b[0m tests/test_a.py::\x1b[1mtest_x\x1b[0m - assert 0\n"
            "\x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m14 passed\x1b[0m\x1b[31m in 0.21s\x1b[0m\n")
    (run,) = _runs("uv run pytest --color=yes", text)
    assert (run["passed"], run["tests"]) == (False, 15)
    assert run["failures"][0]["test"] == "tests/test_a.py::test_x"


def test_two_runners_in_one_call_are_two_runs_and_one_runner_twice_is_one():
    runs = _runs("pytest -q && go test ./...", PYTEST_PASS + GO_PLAIN, is_error=True)
    assert [(r["suite"], r["passed"]) for r in runs] == [("Orchard/pytest", True),
                                                        ("Orchard/go", False)]
    (run,) = _runs("pytest a && pytest b", PYTEST_PASS + PYTEST_FAIL)
    assert (run["tests"], run["passed"], len(run["failures"])) == (165, False, 2)


def test_no_summary_no_background_run_no_test_run():
    assert _runs("pytest", "ERROR: file or directory not found: tests/x\n", is_error=True) == []
    out = _bash("pytest > /tmp/p.log 2>&1", BG_RESULT, background=True)
    assert out["test_runs"] == [] and out["command_class"] == "test_suite"
    assert _runs("tail -5 /tmp/p.log", PYTEST_PASS) == []       # no test suite ran here


# -- kc project test ------------------------------------------------------------

KC_TWO = """\
backend: cexec toolbox uv run pytest -n 8    [  OK  ]
    ........................................................................ [ 96%]
    ...                                                                      [100%]
    =============== 75 passed, 2 warnings in 12.31s (0:00:12) ================
frontend: cexec toolbox pnpm test    [FAILED]

> orchard@0.0.0 test /work/Orchard/frontend
> playwright test

  1 failed
    [chromium] › tests/orchard/trees.spec.ts:44:5 › Trees › a felled tree goes
  40 passed (1.2m)
 ELIFECYCLE  Command failed with exit code 1.
sidecar: cexec go go test ./...    [  OK  ]
    ok  \texample.org/orchard/sync\t0.210s
    ok  \texample.org/orchard/store\t0.034s
full output: /tmp/kc/project/test-20261115T100000Z-4242.log
"""

KC_LINT_AND_TEST = """\
backend: cexec toolbox uv run ruff check .    [FAILED]
    E501 line too long
full output: /tmp/kc/project/lint-20261115T095900Z-4240.log
backend: cexec toolbox uv run pytest    [  OK  ]
    75 passed in 12.31s
backend: cexec toolbox uv run mypy .    [  OK  ]
full output: /tmp/kc/project/test-20261115T100000Z-4242.log
"""


def test_kc_project_test_is_one_run_per_component():
    runs = _runs("cd /work/Orchard && timeout 900 kc project test", KC_TWO, is_error=True)
    got = [(r["suite"], r["passed"], r["tests"]) for r in runs]
    assert got == [("Orchard/backend/test", True, 75), ("Orchard/frontend/test", False, 41),
                   ("Orchard/sidecar/test", True, 2)]
    assert runs[1]["failures"][0]["test"] == \
        "tests/orchard/trees.spec.ts › Trees › a felled tree goes"
    out = _bash("kc project test", KC_TWO, is_error=True)
    assert out["test_suites"][0] == {"code": "Orchard/backend/test", "name": "Orchard backend test"}
    assert out["events"] == [{"kind": "gate_red", "at": T1, "detail": "test"}]


def test_kc_a_lint_beside_the_test_is_no_test_run_and_no_red():
    (run,) = _runs("kc project lint --project backend; kc project test --project backend",
                   KC_LINT_AND_TEST)
    assert (run["suite"], run["passed"], run["tests"]) == ("Orchard/backend/test", True, 75)


def test_kc_a_failed_command_without_a_summary_reds_its_component():
    text = ("backend: cexec toolbox uv run pytest    [  OK  ]\n    75 passed in 12.31s\n"
            "backend: cexec toolbox uv run vulture app    [FAILED]\n    app/x.py:3: unused\n"
            "full output: /tmp/kc/project/test-20261115T100000Z-1.log\n")
    (run,) = _runs("kc project test --project backend", text, is_error=True)
    assert (run["passed"], run["tests"]) == (False, 75)


def test_kc_a_tail_that_cut_the_component_line_takes_the_command_s_project():
    text = "    ============ 2743 passed, 2141 warnings in 282.37s (0:04:42) ============\n" \
           "full output: /tmp/kc/project/test-20261115T100000Z-87913.log\n"
    (run,) = _runs("kc project test --project backend 2>&1 | tail -2", text)
    assert (run["suite"], run["tests"]) == ("Orchard/backend/test", 2743)
    assert _runs("kc project test 2>&1 | tail -2", text) == []   # which component: unknown


def test_kc_a_component_with_no_summary_has_no_run():
    text = "manual: cexec toolbox mkdocs build --strict    [  OK  ]\n" \
           "full output: /tmp/kc/project/test-20261115T100000Z-2.log\n"
    assert _runs("kc project test --project manual", text) == []


def test_kc_test_counts_are_the_driver_s_reading_of_its_gate_log():
    """D7: the driver counts a gate's and a sweep's tests from its own log, per component."""
    assert lt.kc_test_counts(KC_TWO) == [
        {"component": "backend", "tests": 75, "passed": True},
        {"component": "frontend", "tests": 41, "passed": False},
        {"component": "sidecar", "tests": 2, "passed": True}]
    assert lt.kc_test_counts(KC_LINT_AND_TEST) == [
        {"component": "backend", "tests": 75, "passed": True}]
    cut = "    ===== 2743 passed in 282.37s =====\n" \
          "full output: /tmp/kc/project/test-20261115T100000Z-87913.log\n"
    assert lt.kc_test_counts(cut, "backend") == [
        {"component": "backend", "tests": 2743, "passed": True}]
    assert lt.kc_test_counts(cut) == []
    coloured = "\x1b[1mbackend: cexec toolbox uv run pytest    [  OK  ]\x1b[0m\n" \
               "    75 passed in 12.31s\n"
    assert lt.kc_test_counts(coloured) == [{"component": "backend", "tests": 75,
                                            "passed": True}]
    assert lt.kc_test_counts("nothing to see\n", "backend") == []


# -- gate_red ---------------------------------------------------------------------

def test_a_red_gate_or_suite_is_an_event():
    out = _bash("cd /work/Orchard && kc project test --project frontend 2>&1 | tail -30",
                "Exit code 1\n" + KC_TWO, is_error=True)
    assert out["events"] == [{"kind": "gate_red", "at": T1, "detail": "frontend test"}]
    assert _bash("uv run ruff check .", "Exit code 1\nE501", is_error=True)["events"] == [
        {"kind": "gate_red", "at": T1, "detail": "ruff"}]
    assert _bash("python3 /x/run_loop.py gate P1", "Exit code 2\nred",
                 is_error=True)["events"][0]["detail"] == "run_loop.py gate"
    assert _bash("pytest", "Exit code 1\n" + PYTEST_FAIL)["events"][0]["detail"] == "pytest"
    assert _bash("pytest", PYTEST_PASS)["events"] == []
    assert _bash("git status", "Exit code 128\nfatal", is_error=True)["events"] == []


# -- digest sections ----------------------------------------------------------------

DIGEST = """\
You are the code-writer for phase P2 of slice 003_rows.

---

# Orientation digest — phase P2

**Slice.** Rows in the orchard

The orchard shows its rows.

## Requirements

- R1 rows are listed.

## Your phase

### P2 — The row list

Target: frontend

```
## not a heading, a fenced line
```

## Settled by earlier phases (their done-record summaries)

### P1 — The rows' API

Done.
"""


def test_a_digest_gives_one_part_per_section():
    parts = lt.digest_sections(DIGEST)
    assert [p["name"] for p in parts] == ["Requirements", "Your phase",
                                          "Settled by earlier phases"]
    assert parts[0]["characters"] == len("## Requirements\n\n- R1 rows are listed.")
    block = DIGEST[DIGEST.index("## Your phase"):DIGEST.index("## Settled")].rstrip("\n")
    assert parts[1]["characters"] == len(block)
    assert parts[2]["characters"] == len(DIGEST[DIGEST.index("## Settled"):].rstrip("\n"))


def test_no_digest_no_parts():
    assert lt.digest_sections("## Requirements\n\nno digest here\n") == []
    assert lt.digest_sections("") == []


# -- the context ------------------------------------------------------------------

def test_the_context_may_come_as_a_mapping():
    out = lt.tool_labels("Bash", {"command": "tail -3 /tmp/a.log"}, "",
                         {"cwd": REPO, "background_writes": ["/tmp/a.log"]})
    assert out["rules"] == ["no_tail_on_background_log"]
    assert lt.tool_labels("Bash", {"command": "ls"}, None)["command_class"] is None


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
