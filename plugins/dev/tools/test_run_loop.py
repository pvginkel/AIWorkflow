"""Tests for run_loop.RunLoop — the phased-plan loop as a state machine.

Sessions, git, kc's project list, and the deterministic test gate are faked:
each test scripts the sequence of (role, outcome) verdicts it expects the
driver to request — plus the gate's green/red sequence — and asserts on
transitions, caps, plan stamps, state.json, and bail-outs. No kc session is
created, no claude process is spawned, and no real suite runs.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_run_loop.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location(
    "run_loop", Path(__file__).resolve().parent / "run_loop.py"
)
run_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_loop)
RunLoop = run_loop.RunLoop
Bailout = run_loop.Bailout
parse_plan = run_loop.parse_plan
parse_push_holds = run_loop.parse_push_holds
stamp_phase = run_loop.stamp_phase

# The driver reads the component set from `kc project list` in run(). The
# suite has no kc, so that seam is stubbed with a single component whose cwd
# is the repo root — every session the loop would spawn is faked anyway.
PROJECT = "app"
run_loop.load_project_dirs = lambda cwd: {PROJECT: Path(cwd)}


class FakeGit:
    """Answers the git queries the driver makes; records mutations. The
    driver roots calls per target repo via the `root=` kwarg; the fake
    records it so cross-repo tests can assert where a mutation landed."""

    def __init__(self):
        self.calls = []          # (root, args)
        self.branches = set()
        self.head = "abc123"
        self.diff_files = ""     # what `diff --name-only` reports
        self.stat = ""           # what `diff --stat` reports
        self.diff = ""           # what a plain `diff <range>` reports
        self.dirty = ""          # what `status --porcelain` reports
        self.dirty_roots = {}    # str(root) → porcelain, overriding `dirty`
        self.branch_files = ""   # what `log --name-only` reports
        self.unpushed = {}       # str(root) → `rev-list --count` answer
        self.no_origin = set()   # roots where `origin/<base>` does not exist
        self.ahead = {}          # "<base>..<branch>" → commits it is ahead by
        self.lost = set()        # shas no ref in this repo reaches any more
        self.merged = set()      # shas the base branch carries

    def __call__(self, *args, root=None, check=True):
        self.calls.append((root, args))
        if args[:3] == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        if args[0] == "diff" and "--name-only" in args:
            return self.diff_files
        if args[0] == "diff" and any(a.startswith("--stat") for a in args):
            return self.stat
        if args[0] == "diff":
            return self.diff
        if args[0] == "rev-list":
            if args[-1].startswith("origin/"):
                return self.unpushed.get(str(root), "0")
            return self.ahead.get(args[-1], "0")
        if args[:2] == ("rev-parse", "--verify"):
            return "" if str(root) in self.no_origin else self.head
        if args[0] == "rev-parse":
            return self.head
        if args[0] == "merge-base":
            return "base123"
        if args[0] == "log":
            return self.branch_files
        if args[0] == "status":
            return self._status(args, root)
        if args[0] == "branch" and args[1] == "--list":
            return args[2] if args[2] in self.branches else ""
        if args[0] == "checkout" and args[1] == "-b":
            self.branches.add(args[2])
            return ""
        if args[0] == "branch" and args[1] == "-D":
            self.branches.discard(args[2])
            return ""
        return ""

    def _status(self, args, root):
        """Porcelain, honouring `:(exclude)<dir>` — the pathspec the driver
        holds its own bookkeeping out with when the target repo holds the
        slice folder."""
        text = self.dirty_roots.get(str(root), self.dirty)
        excluded = [a[len(":(exclude)"):] for a in args
                    if a.startswith(":(exclude)")]
        return "\n".join(
            line for line in text.splitlines()
            if not any(line[3:] == x or line[3:].startswith(x + "/")
                       for x in excluded))

    def ok(self, *args, root=None):
        """`git_ok` — the queries answered by an exit status. A recorded
        commit is on its phase branch unless the test says it was lost, and
        in the base branch only when the test says it merged."""
        self.calls.append((root, args))
        if args[:2] == ("merge-base", "--is-ancestor"):
            sha, ref = args[2], args[3]
            if ref.startswith("phase/"):
                return sha not in self.lost
            return sha in self.merged
        return True

    def mutations(self, verb):
        return [(root, c) for root, c in self.calls if c[0] == verb]

    def specs_ops(self):
        """The `git -C <specs>` calls (the driver's own stamp commits)."""
        return [c for _, c in self.calls if c and c[0] == "-C"]


class ScriptedLoop(RunLoop):
    """RunLoop with _spawn replaced by a script of (role, verdict[, effect])
    steps and the test gate replaced by a scripted green/red sequence
    (default green once the sequence is exhausted). `effect` is called with
    the loop and stands in for what the session would have done on disk."""

    def __init__(self, slice_dir, script, resume=False, gates=None,
                 doc_gates=None, repo_root=None, sweep_reds=None):
        super().__init__(Path(slice_dir), resume=resume)
        if repo_root is not None:
            self.repo_root = Path(repo_root)
        self.script = list(script)
        self.spawned = []    # (role, phase, round, outcome)
        self.prompts = []    # (role, prompt)
        self.gates = list(gates or [])
        self.gate_calls = []
        self.doc_gates = list(doc_gates or [])
        self.doc_gate_calls = []
        self.sweep_reds = set(sweep_reds or [])   # (component, verb) → red
        self.sweep_calls = []                     # (root, component, verb)
        self.fake_git = FakeGit()
        self.git = self.fake_git
        self.git_ok = self.fake_git.ok
        self.sleeps = []

    def _sleep(self, seconds):
        self.sleeps.append(seconds)

    def _assert_agents(self):
        pass  # the real assertion has its own unit test

    def _run_gate(self, phase_id, ps, outputs, target):
        if target.gate_argv is None:
            return True, None
        ps["gate_runs"] += 1
        green = self.gates.pop(0) if self.gates else True
        self.gate_calls.append((phase_id, green))
        log_path = outputs / f"gate_r{ps['gate_runs']}.log"
        log_path.write_text("gate output\n")
        if green:
            ps["gate_green_commit"] = self.git("rev-parse", "HEAD")
            ps["gate_green_log"] = str(log_path)
        self._record(phase_id, "gate", ps["gate_runs"],
                     "green" if green else "red", "", None, 0)
        return green, log_path

    def _run_doc_gate(self, ds):
        ds["gate_runs"] += 1
        green = self.doc_gates.pop(0) if self.doc_gates else True
        self.doc_gate_calls.append(green)
        log_path = self.slice_dir / f"doc_gate_r{ds['gate_runs']}.log"
        log_path.write_text("doc gate output\n")
        self._record(None, "doc-gate", ds["gate_runs"],
                     "green" if green else "red", "", None, 0)
        return green, log_path

    def _run_sweep_cmd(self, root, component, verb, out_dir):
        green = (component, verb) not in self.sweep_reds
        self.sweep_calls.append((str(root), component, verb))
        log_path = out_dir / f"{root.name}_{component}_{verb}.log"
        log_path.write_text("sweep output\n")
        return {"repo": str(root), "component": component, "verb": verb,
                "green": green, "log": str(log_path), "duration_s": 0}

    def _spawn(self, role, prompt, cwd, verdict_path, phase_id, round_,
               agent=None, display=None):
        prompt, resume_session = self._resolve_reattach(
            role, phase_id, prompt, Path(verdict_path), "[t]")
        assert self.script, f"unexpected extra spawn: {role} (P{phase_id})"
        step = self.script.pop(0)
        want_role, verdict = step[0], step[1]
        self.prompts.append((role, prompt))
        assert role == want_role, (
            f"expected spawn of {want_role}, driver asked for {role} "
            f"(P{phase_id}, round {round_})"
        )
        self.spawned.append((role, phase_id, round_, verdict["outcome"],
                             resume_session))
        self._record(phase_id, role, round_, verdict["outcome"],
                     verdict.get("summary", ""), "sess-test", 1,
                     extra={k: verdict[k] for k in ("findings", "refuted")
                            if verdict.get(k)})
        if len(step) > 2:
            step[2](self)
        return verdict, "sess-test"


class SpawningLoop(ScriptedLoop):
    """ScriptedLoop with the REAL _spawn — `run_kc_session` is faked instead,
    so everything inside _spawn (verdict reading, nudges, the session-limit
    wait) is exercised. A script step is the usual (role, verdict dict), or
    (role, text) for a session that produced only that text and no
    verdict."""

    def __init__(self, slice_dir, script, **kw):
        super().__init__(slice_dir, script, **kw)
        self.sessions = []
        self.session_prompts = []
        self.session_flags = []
        self._pending = None

    def _spawn(self, role, prompt, cwd, verdict_path, phase_id, round_,
               agent=None, display=None):
        self._pending = (role, Path(verdict_path))
        verdict, session = RunLoop._spawn(
            self, role, prompt, cwd, Path(verdict_path), phase_id, round_,
            agent=agent, display=display)
        self.prompts.append((role, prompt))
        self.spawned.append((role, phase_id, round_, verdict["outcome"],
                             None))
        return verdict, session

    def run_kc_session(self, prompt, cwd, timeout, agent=None, model=None,
                       effort=None, resume_session=None, extra_env=None,
                       flags=None, progress=None, on_session=None):
        role, verdict_path = self._pending
        assert self.script, f"unexpected extra session: {role}"
        step = self.script.pop(0)
        want_role, payload = step[0], step[1]
        assert role == want_role, (
            f"expected a {want_role} session, driver ran {role}")
        self.sessions.append((role, payload, model, effort))
        self.session_prompts.append((role, prompt))
        self.session_flags.append((role, list(flags or ())))
        result = run_loop.SessionResult()
        result.session_id = f"sess-{len(self.sessions)}"
        if on_session:
            on_session(result.session_id)
        if payload is TIMED_OUT:
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, tuple) and payload[0] is TIMED_OUT:
            verdict_path.write_text(json.dumps(payload[1]))
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, str):
            result.result_text = payload
            return 1, result
        verdict_path.write_text(json.dumps(payload))
        result.result_text = payload.get("summary", "")
        if len(step) > 2:
            step[2](self)
        return 0, result


SESSION_LIMIT_TEXT = ("You've hit your session limit · resets 10:10pm "
                      "(Europe/Amsterdam)")
TIMED_OUT = object()   # a script step whose session never returns


def timed_out_after(verdict):
    """A script step whose session wrote its verdict and *then* wedged: the
    turn never returns, but the work and the verdict are already on disk."""
    return (TIMED_OUT, verdict)


def phase_section(pid, title, target=PROJECT, done=False, body=""):
    stamp = " ✅ DONE 2026-07-30" if done else ""
    return (f"### P{pid} — {title}{stamp}\n\n"
            f"Target: {target}\n\n{body}")


def rc(test=True, doc=True, push=True, devlock=False):
    """What a fake target repo says about itself: the `.aiworkflowrc` the
    driver reads. The default is a project that runs everything and leases no
    dev instance; `make_slice(rc=rc(...))` builds the rest."""
    parts = ['spec_repo = "../specs"',
             'design_philosophy = "philosophy.md"', "",
             "[test_phase]",
             'strategy = "test-plan.md"' if test else "enabled = false", "",
             "[doc_phase]",
             'plan = "doc-plan.md"' if doc else "enabled = false", ""]
    if devlock:
        parts += ["[devlock]", 'lease = "scripts/.devlock.lock"', ""]
    if not push:
        parts += ["[push]", "enabled = false", ""]
    return "\n".join(parts)


def make_slice(tmp, phases=None, repo=True, config=None):
    """A slice folder inside a specs-shaped tree, plus a fake target repo
    carrying the `.aiworkflowrc` the driver reads."""
    root = Path(tmp)
    slice_dir = root / "specs" / "slices" / "074_test_slice"
    slice_dir.mkdir(parents=True)
    if phases is None:
        phases = [("1", "First phase")]
    sections = [phase_section(*p) if isinstance(p, tuple) else p
                for p in phases]
    (slice_dir / "plan.md").write_text(
        "# Test slice — plan\n\n## Phases\n\n" + "\n".join(sections))
    (slice_dir / "verification.json").write_text('{"items": []}\n')
    if repo:
        repo_root = root / "repo"
        repo_root.mkdir()
        (repo_root / "test-plan.md").write_text("test procedure\n")
        (repo_root / "doc-plan.md").write_text("doc procedure\n")
        (repo_root / "philosophy.md").write_text("change discipline\n")
        (repo_root / ".aiworkflowrc").write_text(
            rc() if config is None else config)
        # The manifest makes the repo a loop-tail sweep target, as the real
        # invoking repo always is.
        (repo_root / ".kubecoder").mkdir()
        (repo_root / ".kubecoder" / "project.yaml").write_text(
            "projects: {}\n")
        return slice_dir, repo_root
    return slice_dir, None


def append_phase(pid, title, target=PROJECT):
    def effect(loop):
        with open(loop.plan_path, "a") as f:
            f.write("\n" + phase_section(pid, title, target))
    return effect


def run_to_exit(loop):
    try:
        loop.run()
    except SystemExit as e:
        return e.code
    raise AssertionError("run() did not exit")


def load_state(slice_dir):
    return json.loads((slice_dir / "state.json").read_text())


def load_report(slice_dir):
    return (slice_dir / "close-out.md").read_text()


class patched:
    """Swap module attributes for the duration of a `with` block — the tests
    run under pytest and standalone, so no fixtures."""

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


V = {
    "exec_done": ("code-writer", {"outcome": "done", "summary": "built"}),
    "review_signoff": ("code-reviewer", {"outcome": "signoff",
                                         "summary": "ok"}),
    "review_issues": ("code-reviewer", {"outcome": "issues",
                                        "summary": "gaps"}),
    "consult_complete": ("consult", {"outcome": "complete",
                                     "summary": "nothing outstanding"}),
    "test_clean": ("test-agent", {"outcome": "clean",
                                  "summary": "all verified"}),
    "doc_done": ("doc-writer", {"outcome": "done", "summary": "docs done"}),
}

# The tail every completed slice runs: completion consult → test → docs.
TAIL = [V["consult_complete"], V["test_clean"], V["doc_done"]]


# -- plan parsing -------------------------------------------------------------

def test_parse_plan_phases_ids_and_order():
    text = (
        "# Plan\n\n## Rulings\n\ntext\n\n"
        "### P1 — First ✅ DONE 2026-07-29\n\nTarget: app\n\n"
        "### P2 — Second\n\nTarget: app\n\ndetail\n\n"
        "### P2a — Inserted\n\nTarget: ../Sibling\n\n"
        "### Pfix1 — Free-form id\n\nTarget: app\n"
    )
    phases, errors = parse_plan(text)
    assert errors == []
    assert [p.id for p in phases] == ["1", "2", "2a", "fix1"]
    assert [p.done for p in phases] == [True, False, False, False]
    assert phases[2].target == "../Sibling"


def test_parse_plan_reads_the_creates_declaration():
    """`Creates:` names a component the phase registers in the manifest —
    same style tolerance as `Target:`, first line of its kind wins, absent
    means None."""
    text = (
        "# Plan\n\n"
        "### P1 — Stand it up\n\nTarget: app\n\nCreates: newcomp\n\n"
        "second thoughts\n\nCreates: ignored\n\n"
        "### P2 — Decorated\n\nTarget: app\n\n**Creates:** `othercomp`\n\n"
        "### P3 — Plain\n\nTarget: app\n"
    )
    phases, errors = parse_plan(text)
    assert errors == []
    assert [p.creates for p in phases] == ["newcomp", "othercomp", None]


def test_creates_on_a_done_phase_parses_and_is_inert():
    text = ("# Plan\n\n### P1 — Stood it up ✅ DONE 2026-08-30\n\n"
            "Target: app\n\nCreates: newcomp\n")
    phases, errors = parse_plan(text)
    assert errors == []
    assert phases[0].done and phases[0].creates == "newcomp"


def test_parse_push_holds_reads_the_section_only():
    text = (
        "# Plan\n\n## Push holds\n\n"
        "<!-- Optional; usually absent.\n"
        "     `- ../Repo — why` — the driver reports it held. -->\n\n"
        "- ../HelmCharts — a push deploys dev and prd together\n"
        "- `../Other` — **bold and backticks are decoration**\n\n"
        "## Not in scope\n\n- ../NotHeld — this bullet is another section\n"
        "\n### P1 — First\n\nTarget: app\n"
    )
    holds, errors = parse_push_holds(text)
    assert errors == []
    assert holds == [
        ("../HelmCharts", "a push deploys dev and prd together"),
        ("../Other", "**bold and backticks are decoration**"),
    ]


def test_parse_push_holds_errors():
    """A bullet the parser cannot read is an error, never a skip: a hold it
    misses silently is a repo the driver pushes."""
    text = ("## Push holds\n\n"
            "prose about the holds is fine\n\n"
            "- ../HelmCharts because prd rolls\n"
            "- ../Chart —\n"
            "- ../Twice — first\n"
            "- ../Twice — again\n")
    holds, errors = parse_push_holds(text)
    assert [t for t, _ in holds] == ["../Twice"]
    joined = "\n".join(errors)
    assert "is not a push hold" in joined
    assert "../HelmCharts because prd rolls" in joined
    assert "`../Twice` is held twice" in joined


def test_parse_push_holds_absent_section():
    assert parse_push_holds("# Plan\n\n### P1 — X\n\nTarget: app\n") == (
        [], [])


def test_parse_plan_errors():
    text = (
        "### Not A Phase\n\nTarget: app\n\n"
        "### P3 — No target here\n\nbody only\n\n"
        "### P3 — Duplicate\n\nTarget: app\n"
    )
    _, errors = parse_plan(text)
    joined = "\n".join(errors)
    assert "not a phase heading" in joined
    assert "P3 has no `Target:` line" in joined
    assert "more than once" in joined


def test_parse_plan_done_needs_no_target():
    phases, errors = parse_plan("### P1 — Done phase ✅ DONE 2026-07-01\n\n"
                                "no target line\n")
    assert errors == []
    assert phases[0].done


def test_target_line_tolerates_markdown_decoration():
    phases, errors = parse_plan("### P1 — X\n\n**Target:** `app`\n")
    assert errors == []
    assert phases[0].target == "app"


def test_stamp_phase_appends_once():
    with tempfile.TemporaryDirectory() as tmp:
        plan = Path(tmp) / "plan.md"
        plan.write_text("### P1 — X\n\nTarget: app\n")
        assert stamp_phase(plan, "1", "2026-07-31")
        assert "### P1 — X ✅ DONE 2026-07-31" in plan.read_text()
        # already stamped → not stamped again
        assert not stamp_phase(plan, "1", "2026-08-01")
        assert plan.read_text().count("DONE") == 1
        assert not stamp_phase(plan, "9", "2026-07-31"), "unknown id"


# -- the phase loop -----------------------------------------------------------

def test_happy_path_two_phases():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First"), ("2", "Second")])
        script = [V["exec_done"], V["review_signoff"],
                  V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script, "not every scripted verdict was consumed"
        state = load_state(slice_dir)
        assert state["run_phase"] == "done"
        assert state["phases"]["1"]["status"] == "merged"
        assert state["phases"]["2"]["status"] == "merged"
        # one gate run per phase, green, ff-merges, driver stamps
        assert r.gate_calls == [("1", True), ("2", True)]
        merges = r.fake_git.mutations("merge")
        phase_merges = [c for _, c in merges if any(
            f"phase/074-P{p}" in a for p in ("1", "2") for a in c)]
        assert len(phase_merges) == 2
        assert all("--ff-only" in c for _, c in merges)
        plan = (slice_dir / "plan.md").read_text()
        assert plan.count("✅ DONE") == 2
        # the stamp is committed in the specs repo, plan.md staged by name;
        # the only other driver commit there is the close-out report's
        # creation, also by name
        specs = r.fake_git.specs_ops()
        adds = [c for c in specs if c[2] == "add"]
        commits = [c for c in specs if c[2] == "commit"]
        assert [Path(c[3]).name for c in adds] == \
            ["close-out.md", "plan.md", "plan.md"]
        assert any("stamp P1 done" in " ".join(c) for c in commits)
        assert any("close-out report" in " ".join(c) for c in commits)
        assert not (slice_dir / "bailout.json").exists()


def test_executor_prompt_carries_phase_and_plan():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "Execute phase P1 of" in prompt
        assert "plan.md" in prompt
        assert "phase/074-P1" in prompt
        assert "done-record" in prompt
        assert "**Done (P1).**" in prompt
        assert f"kc project test --project {PROJECT}" in prompt
        # the digest rides the dispatch: the phase's own section, whole
        assert "# Orientation digest — phase P1" in prompt
        assert "### P1 — First phase" in prompt
        assert "Read the whole plan" not in prompt


def test_executor_digest_carries_the_slice_and_every_round_gets_it():
    """The digest is built per round from the files as they stand: the
    slice's intent paragraph, the plan's rulings, verification.json's items,
    earlier phases' done-records (not their text), later phases' headings,
    and what earlier phases changed — in the target repo up to the phase
    branch's merge base, in every other touched repo up to its base."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            phase_section("1", "Groundwork", done=True,
                          body="Lay the groundwork carefully.\n\n"
                               "**Done (P1).** Laid; the seam is `x.py`.\n"),
            ("2", "The feature"),
            ("3", "The cleanup"),
        ])
        plan = slice_dir / "plan.md"
        plan.write_text(plan.read_text().replace(
            "## Phases\n",
            "## Requirements / rulings\n\n- R1. Ship it.\n"
            "- Ruling (2026-08-23): narrow.\n\n## Phases\n")
            + "\n## Not in scope\n\n- The moon.\n")
        (slice_dir / "slice.md").write_text(
            "# Slice 074 — Test\n\n**Feature.** The slice's intent,\n"
            "two lines of it.\n\nFiled by triage.\n")
        (slice_dir / "verification.json").write_text(json.dumps({"items": [
            {"id": "V01", "area": "core", "description": "It ships."}]}))
        script = [V["exec_done"], V["exec_done"],   # P2: initial + gate fix
                  V["review_signoff"],
                  V["exec_done"], V["review_signoff"],   # P3
                  *TAIL]
        r = ScriptedLoop(slice_dir, script, gates=[False, True],
                         repo_root=repo)
        r.fake_git.stat = " x.py | 2 +-\n 1 file changed, 1 insertion(+)"
        # an earlier phase touched a sibling repo too (state is created by
        # run(), so the record is seeded at the first digest)
        orig = r._phase_digest

        def seeded(phase_id, root, merge_base):
            r.state["slice_base"].setdefault("/elsewhere/Sibling", "s1b")
            r.state["bases"].setdefault("/elsewhere/Sibling", "main")
            return orig(phase_id, root, merge_base)
        r._phase_digest = seeded
        assert run_to_exit(r) == 0
        first, fix = r.prompts[0][1], r.prompts[1][1]
        for prompt in (first, fix):
            assert "# Orientation digest — phase P2" in prompt
            assert "**Feature.** The slice's intent,\ntwo lines of it." in prompt
            assert "Filed by triage" not in prompt
            assert "- Ruling (2026-08-23): narrow." in prompt
            assert "- The moon." in prompt
            assert "### P2 — The feature" in prompt
            # P1 contributes its done-record, not its text
            assert "**Done (P1).** Laid; the seam is `x.py`." in prompt
            assert "Lay the groundwork carefully" not in prompt
            assert f"- P3 — The cleanup (Target: {PROJECT})" in prompt
            assert "- V01 (core) — It ships." in prompt
            assert " x.py | 2 +-" in prompt
        assert "digested below" in fix
        stats = [c for root, c in r.fake_git.calls
                 if c[0] == "diff" and c[1].startswith("--stat")]
        assert ("s1b..main" in [c[2] for c in stats])
        assert any(c[2].endswith("..base123") for c in stats)


def test_phase_digest_shapes():
    """build_phase_digest and its readers, on a plan in the template's
    shape: sections run to the next `##` or the first phase heading; a done
    phase without a `**Done` opener contributes its whole section; long
    stats keep their head and their summary; slice_intent is the first
    paragraph after the title."""
    plan = "\n".join([
        "# Slice 9 — The one-liner", "",
        "## Requirements / rulings", "", "- R1. Yes.", "",
        "## Task shape", "", "localized — because.", "",
        phase_section("1", "Old", done=True, body="Did it.\n"),
        phase_section("2", "Now", body="Do this.\n"),
        "## Not in scope", "", "- Nope.", ""])
    digest = run_loop.build_phase_digest(
        plan, "2", "", [], [("/r", "\n".join(
            [f" f{i} | 1 +" for i in range(60)] + [" 60 files changed"]))])
    assert "**Slice.** Slice 9 — The one-liner" in digest
    assert "- R1. Yes." in digest and "- Nope." in digest
    assert "localized — because." not in digest
    assert "### P1 — Old ✅ DONE" in digest and "Did it." in digest
    assert "### P2 — Now" in digest and "Do this." in digest
    assert "Later phases" not in digest
    assert " f0 | 1 +" in digest and " f59 | 1 +" not in digest
    assert " … 21 more files" in digest and " 60 files changed" in digest
    assert run_loop.slice_intent(
        "# T\n\n\nFirst para\ncontinues.\n\nSecond.\n") \
        == "First para\ncontinues."
    assert run_loop.slice_intent("") == ""
    # a phase id the plan does not carry digests the slice parts only
    assert "Your phase" not in run_loop.build_phase_digest(plan, "7", "", [], [])


def test_slice_digest_carries_rulings_and_every_done_record():
    """build_slice_digest, the doc phase's: the title, the rulings sections,
    each phase's done-record from its opener (a phase without one gives its
    whole section; one not done says so) — and no intent, no criteria, no
    phase text."""
    plan = "\n".join([
        "# Slice 9 — The one-liner", "",
        "## Requirements / rulings", "", "- R1. Yes.", "",
        "## Task shape", "", "localized — because.", "",
        phase_section("1", "Old", done=True,
                      body="Plan text.\n\n**Done (P1).** Landed X.\n"),
        phase_section("2", "Bare", done=True, body="Only text.\n"),
        phase_section("3", "Open", body="Do this.\n"),
        "## Not in scope", "", "- Nope.", ""])
    digest = run_loop.build_slice_digest(plan)
    assert digest.startswith("---\n\n# Orientation digest — the whole slice")
    assert "**Slice.** Slice 9 — The one-liner" in digest
    assert "- R1. Yes." in digest and "- Nope." in digest
    assert "localized — because." not in digest
    assert "## What each phase settled (their done-records)" in digest
    assert "### P1 — Old ✅ DONE" in digest and "**Done (P1).** Landed X." in digest
    assert "Plan text." not in digest
    assert "### P2 — Bare ✅ DONE" in digest and "Only text." in digest
    assert "### P3 — Open" in digest and "(not done yet)" in digest
    assert "Do this." not in digest
    assert "Acceptance criteria" not in digest
    # an unreadable or empty plan digests to the heading alone
    assert "settled" not in run_loop.build_slice_digest("")


def test_reviewer_dispatch_states_the_green_gate():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "code-reviewer")
        assert "ran GREEN on this exact commit" in prompt
        assert r.fake_git.head[:12] in prompt
        assert "gate_r1.log" in prompt
        assert "Do not re-run the suite or the linter" in prompt
        assert "vacuous" in prompt
        # the phase model is explicit: testing/docs live in later phases
        assert "own later phases" in prompt


def test_gate_line_never_claims_a_stale_green():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        target = run_loop.ResolvedTarget(PROJECT, "project", Path(repo),
                                         ["kc"], Path(repo))
        green = {"gate_green_commit": "deadbeefcafe0",
                 "gate_green_log": "/g/gate_r1.log"}
        assert "ran GREEN" in r._gate_line(green, "deadbeefcafe0", target)
        assert "unverified" in r._gate_line(green, "0ther000head0", target)
        assert "unverified" in r._gate_line({}, "abc123", target)


def test_red_gate_spawns_fresh_executor_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["exec_done"],   # initial + gate fix
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, gates=[False, True],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        assert r.gate_calls == [("1", False), ("1", True)]
        fix_prompt = r.prompts[1][1]
        assert "gate_r1.log" in fix_prompt and "red" in fix_prompt
        assert "without weakening" in fix_prompt
        state = load_state(slice_dir)
        assert state["phases"]["1"]["gate_fix_rounds"] == 1
        assert state["phases"]["1"]["executor_rounds"] == 2


def test_gate_fix_cap_bails_red():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        cap = run_loop.GATE_FIX_CAP
        script = [V["exec_done"]] + [V["exec_done"]] * cap
        r = ScriptedLoop(slice_dir, script, gates=[False] * (cap + 1),
                         repo_root=repo)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "gate_red"
        assert bail["phase"] == "1"
        assert not bail["question"]


def test_review_issues_round1_fix_is_automatic():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        # no consult was scripted: round 1's fix funds itself
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["review_rounds"] == 2 and ps["executor_rounds"] == 2


def test_review_funding_consult_merges_and_reports():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"],
            V["review_issues"], V["exec_done"],       # round 1 + auto fix
            ("code-reviewer", {"outcome": "issues", "summary": "gaps",
                               "findings": REVIEW_FINDINGS}),   # r2 → consult
            ("consult", {"outcome": "merge", "summary": "advisory only"}),
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["phases"]["1"]["status"] == "merged"
        assert "cards" not in state
        # The merge is a Notable event in the close-out report, standing on
        # its own: the consult's reasoning, the findings as tagged, the
        # review file.
        report = load_report(slice_dir)
        assert ("### N1 — P1 merged with unresolved review findings after r2"
                in report)
        assert "advisory only" in report
        assert "F1 [Major/blocking]: wrong branch on empty input" in report
        assert "F2 [Minor/advisory]: stale comment" in report
        assert "code_review_r2.md" in report
        assert "**Provenance:** witnessed — consult 1 (review-funding, P1 r2)" in report
        # The driver's stock consequence for a merge: the findings stand.
        assert ("**Consequence:** the findings listed above are in the merged "
                "tree as the reviewer left them") in report
        # One entry, one operator line (the head comment carries none).
        assert len(re.findall(r"^\*\*Disposition:\*\*\s*$", report, re.M)) == 1
        fund = next(p for role, p in r.prompts
                    if role == "consult" and "funding bar" in p)
        assert "Review round 2" in fund and "fix_round" in fund
        assert "harm the product" in fund
        assert "close-out report" in fund and "cards" not in fund


def test_review_funding_consult_can_fund_a_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"],
            V["review_issues"], V["exec_done"],
            V["review_issues"],
            ("consult", {"outcome": "fix_round", "summary": "real"}),
            V["exec_done"],
            V["review_signoff"], *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["status"] == "merged"
        assert ps["review_rounds"] == 3 and ps["executor_rounds"] == 3
        assert "### N" not in load_report(slice_dir)


def test_review_budget_cap_forces_merge_or_bail():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        cap = run_loop.REVIEW_ROUND_CAP
        script = [V["exec_done"], V["review_issues"], V["exec_done"]]
        for _ in range(2, cap):
            script += [V["review_issues"],
                       ("consult", {"outcome": "fix_round", "summary": "f"}),
                       V["exec_done"]]
        script += [V["review_issues"],
                   ("consult", {"outcome": "merge", "summary": "cap"}),
                   *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        budget_prompt = next(p for role, p in r.prompts
                             if role == "consult" and "exhausted" in p)
        assert f"at most {cap}" not in budget_prompt  # budget shape, not bar
        state = load_state(slice_dir)
        assert state["phases"]["1"]["review_rounds"] == cap


def test_prose_only_fix_range_bumps_the_bar():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def move_head(loop):
            loop.fake_git.head = "head2fix00000"

        script = [
            V["exec_done"],
            V["review_issues"],
            ("code-writer", {"outcome": "done", "summary": "fixed"},
             move_head),
            V["review_issues"],          # delta round → prose-only fix range
            ("consult", {"outcome": "merge", "summary": "prose"}),
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.diff_files = "docs/notes.md\ncontroller/tests/test_x.py"
        assert run_to_exit(r) == 0
        fund = next(p for role, p in r.prompts
                    if role == "consult" and "funding bar" in p)
        assert "touched no production code" in fund
        assert "Blocker-grade harm" in fund  # round 2 + prose bump → round-3 bar


def test_production_paths_classification():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.diff_files = "\n".join([
            "controller/app/api.py", "docs/design.md", "manual/page.md",
            "worker/foo_test.go", "controller/tests/test_api.py",
            "worker/cmd/main.go",
        ])
        prod = r._production_paths("a..b", Path(repo))
        assert prod == ["controller/app/api.py", "worker/cmd/main.go"]


# The reviewer's machine-readable findings (id/severity/impact/category/
# anchor) and the fix round's refuted-verdict path.

REVIEW_FINDINGS = [
    {"id": "F1", "severity": "Major", "impact": "blocking",
     "category": "functional", "anchor": "repro-trace",
     "summary": "wrong branch on empty input"},
    {"id": "F2", "severity": "Minor", "impact": "advisory",
     "category": "comment-prose", "anchor": "none",
     "summary": "stale comment"},
]


def write_review_file(text="findings\n"):
    def effect(loop):
        outputs = loop.slice_dir / "phases" / "P1"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "code_review_r1.md").write_text(text)
    return effect


def test_review_fix_round_is_failure_first():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        fix_prompt = r.prompts[2][1]
        assert "witness the failure" in fix_prompt
        assert "`refuted` list" in fix_prompt
        assert "have no failure to witness" in fix_prompt


def test_all_blocking_refuted_without_code_change_settles_review():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"],
            ("code-reviewer", {"outcome": "issues", "summary": "gaps",
                               "findings": REVIEW_FINDINGS},
             write_review_file()),
            ("code-writer",
             {"outcome": "done", "summary": "refuted",
              "refuted": [{"id": "F1",
                           "evidence": "ran the repro; output correct"}]}),
            *TAIL,                       # no second review round is spawned
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["status"] == "merged"
        assert ps["review_rounds"] == 1
        review = (slice_dir / "phases" / "P1"
                  / "code_review_r1.md").read_text()
        assert "Refuted findings" in review
        assert "F1: ran the repro; output correct" in review
        # The refutation is a Notable event carrying the reviewer's claim,
        # the writer's evidence, and the review file — nothing to chase.
        report = load_report(slice_dir)
        assert "### N1 — Fix round after review r1 of P1 refuted F1" in report
        assert '"wrong branch on empty input"' in report
        assert "ran the repro; output correct" in report
        assert "code_review_r1.md" in report
        assert ("**Provenance:** witnessed — code-writer P1, fix round after review r1"
                in report)
        assert "**Consequence:** none the loop acts on" in report


def test_partial_refutation_funds_the_next_review_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        two_blocking = [
            REVIEW_FINDINGS[0],
            {"id": "F2", "severity": "Major", "impact": "blocking",
             "category": "functional", "anchor": "contradiction",
             "summary": "contract drift"},
        ]

        def fix_moves_head(loop):
            loop.fake_git.head = "head2fix00000"

        script = [
            V["exec_done"],
            ("code-reviewer", {"outcome": "issues", "summary": "gaps",
                               "findings": two_blocking},
             write_review_file()),
            ("code-writer",
             {"outcome": "done", "summary": "fixed F2",
              "refuted": [{"id": "F1", "evidence": "cannot fail"}]},
             fix_moves_head),
            V["review_signoff"],         # round 2 verifies the fix
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["phases"]["1"]["review_rounds"] == 2
        delta_prompt = r.prompts[3][1]
        assert "refutation record" in delta_prompt
        review = (slice_dir / "phases" / "P1"
                  / "code_review_r1.md").read_text()
        assert "- F1: cannot fail" in review


def test_finding_telemetry_persists_to_history():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", {"outcome": "done", "summary": "built"}),
            ("code-reviewer", {"outcome": "issues", "summary": "gaps",
                               "findings": REVIEW_FINDINGS}),
            ("code-writer",
             {"outcome": "done", "summary": "refuted",
              "refuted": [{"id": "F1", "evidence": "cannot fail"}]}),
            ("consult", {"outcome": "complete", "summary": "done"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "docs"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        reviewer_rows = [h for h in state["history"]
                         if h["role"] == "code-reviewer"]
        assert reviewer_rows[0]["findings"] == REVIEW_FINDINGS
        fix_row = next(h for h in state["history"]
                       if h["role"] == "code-writer" and h["round"] == 2)
        assert fix_row["refuted"] == [{"id": "F1", "evidence": "cannot fail"}]
        # rows without telemetry stay exactly as before — no empty keys
        first = next(h for h in state["history"]
                     if h["role"] == "code-writer" and h["round"] == 1)
        assert "findings" not in first and "refuted" not in first


def test_executor_question_bails_as_operator_question():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "question",
                                   "summary": "which auth scheme?"})]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "operator_question"
        assert bail["question"] is True
        assert "which auth scheme?" in bail["details"]


# -- the close-out report -----------------------------------------------------
#
# Every out-of-scope observation goes in <slice>/close-out.md; the driver
# creates it (idempotently), points every dispatch at it and at close_out.py
# (the only way to write to it), appends its own deterministic entries,
# records what the header needs (bail-outs, appended phases), renders it
# before the doc phase and at completion, and stamps the header when the
# run completes.

CLOSE_OUT_TOOL = str(Path(__file__).resolve().parent / "close_out.py")

def test_run_start_creates_and_commits_the_report_once():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        report = load_report(slice_dir)
        assert report.startswith("# Close-out — slice 074 test_slice\n")
        specs = r.fake_git.specs_ops()
        creates = [c for c in specs if c[2] == "commit"
                   and "close-out report" in c[4]]
        assert len(creates) == 1
        # A run started with the plan loop's report in place leaves it be.
        (slice_dir / "state.json").unlink()
        (slice_dir / "close-out.md").write_text(
            "# Close-out — slice 074 test_slice\n\nRun: <not yet stamped>\n\n"
            "## Summary\n\n## Outstanding actions\n\n## Notable events\n\n"
            "### N1 — planning saw something\n\nbody\n\nDisposition:\n\n"
            "## Bugs\n\n## Open questions and rulings\n\n## Suggestions\n")
        plan = (slice_dir / "plan.md").read_text()
        (slice_dir / "plan.md").write_text(re.sub(r" ✅ DONE \S+", "", plan))
        r2 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], repo_root=repo)
        assert run_to_exit(r2) == 0
        assert "### N1 — planning saw something" in load_report(slice_dir)
        assert not [c for c in r2.fake_git.specs_ops()
                    if c[2] == "commit" and "close-out report" in c[4]]


def test_resume_creates_the_report_when_the_run_predates_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        assert (slice_dir / "close-out.md").exists()
        assert any(c[2] == "commit" and "close-out report" in c[4]
                   for c in r.fake_git.specs_ops())


def test_every_dispatch_carries_the_report_path():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First")])
        script = [
            V["exec_done"], V["exec_done"],           # executor, gate-fix
            V["review_issues"], V["exec_done"],       # round 1 + review-fix
            V["review_signoff"],
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, gates=[False, True],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        pointer = f"close-out report is {slice_dir / 'close-out.md'}"
        by_role = {}
        for role, prompt in r.prompts:
            by_role.setdefault(role, []).append(prompt)
        # initial executor, gate-fix round, review-fix round
        assert len(by_role["code-writer"]) == 3
        assert all(pointer in p for p in by_role["code-writer"])
        # round 1 full review and the round 2 delta review
        assert len(by_role["code-reviewer"]) == 2
        assert all(pointer in p for p in by_role["code-reviewer"])
        assert all(pointer in p for p in by_role["test-agent"])
        assert all(pointer in p for p in by_role["doc-writer"])
        assert all(pointer in p for p in by_role["consult"])
        # …and the tool, once per dispatch — the installed close_out.py by
        # absolute path, the subcommands that write, and the ban on hand
        # edits — never restated within a prompt.
        report = slice_dir / "close-out.md"
        for _, prompt in r.prompts:
            assert prompt.count(CLOSE_OUT_TOOL) == 1, prompt
            assert f"`python3 {CLOSE_OUT_TOOL} append|note|strike {report} …`" in prompt
            assert "never edit the file by hand" in prompt
        # and no prompt still speaks of cards
        assert not any("card" in p for _, p in r.prompts)


def test_report_is_rendered_before_the_doc_phase_and_at_completion():
    """The doc-writer ranks its Focus lines over the report as the operator
    will read it, so the driver renders before dispatching it: live entries
    first, Bugs by severity, struck entries folded last. At completion it
    renders again (idempotent) and then stamps."""
    plant = {}

    def plant_entries(loop):
        # The test phase's session leaves a report in arrival order: a
        # struck nit ahead of a live major, a hand-typed struck heading.
        d = loop.slice_dir
        run_loop.append_entry(d, "Bugs", "a nit", "b1", consequence="c1",
                              provenance="read P1 r1", severity="nit")
        run_loop.append_entry(d, "Bugs", "the major one", "b2",
                              consequence="c2", provenance="witnessed P2",
                              severity="major")
        run_loop.append_entry(d, "Bugs", "a minor", "b3", consequence="c3",
                              provenance="read P1 r1", severity="minor")
        text = (d / "close-out.md").read_text().replace(
            "### B1 — a nit · nit", "### ~~B1 — a nit · nit~~ — dup of B3")
        (d / "close-out.md").write_text(text)

    def snapshot(loop):
        plant["at_doc_dispatch"] = load_report(loop.slice_dir)

    script = [
        V["exec_done"], V["review_signoff"], V["consult_complete"],
        ("test-agent", {"outcome": "clean", "summary": "ok"}, plant_entries),
        ("doc-writer", {"outcome": "done", "summary": "docs"}, snapshot),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        seen = plant["at_doc_dispatch"]
        bugs = seen[seen.index("\n## Bugs\n"):seen.index("\n## Open questions")]
        # Rendered when the doc-writer was dispatched: major, minor, then
        # the struck nit folded — its body kept, behind the live ones.
        assert (bugs.index("### B2 — the major one · major")
                < bugs.index("### B3 — a minor · minor")
                < bugs.index("### ~~B1 — a nit · nit~~ — dup of B3")
                < bugs.index("<details><summary>struck — body kept")
                < bugs.index("b1\n") < bugs.index("</details>"))
        # Completion rendered again and stamped: byte-identical entry
        # sections, header stamped, counts unchanged.
        final = load_report(slice_dir)
        assert final[final.index("\n## Bugs\n"):] == seen[seen.index("\n## Bugs\n"):]
        assert "<not yet stamped>" not in final
        assert "close-out report: A 0 · N 0 · B 2 · Q 0 · S 0" in \
            (slice_dir / "log.txt").read_text()
        log = (slice_dir / "log.txt").read_text()
        assert log.count("close-out rendered: ") == 2
        assert "Bugs: 2 live, 1 struck" in log


def test_bail_outs_and_appended_phases_are_recorded_for_the_header():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [("code-writer", {"outcome": "blocked",
                                                       "summary": "no creds"})],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        state = load_state(slice_dir)
        assert [b["reason"] for b in state["bailouts"]] == ["blocked"]
        assert state["bailouts"][0]["phase"] == "1"
        assert state["bailouts"][0]["question"] is False
        # The count survives the resume that unlinks bailout.json, and a
        # consult's appended phase is recorded as appended, not planned.
        script = [
            V["exec_done"], V["review_signoff"],
            ("consult", {"outcome": "appended", "summary": "one gap"},
             append_phase("2", "The gap")),
            V["exec_done"], V["review_signoff"],
            *TAIL,
        ]
        r2 = ScriptedLoop(slice_dir, script, resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        state = load_state(slice_dir)
        assert len(state["bailouts"]) == 1
        assert state["known_phases"] == ["1", "2"]
        assert state["appended_phases"] == ["2"]
        # The header is stamped from that state when the run completes.
        report = load_report(slice_dir)
        assert "<not yet stamped>" not in report
        header = report[report.index("Run:"):report.index("## Summary")]
        header = " ".join(header.split())
        assert "2 phases (1 planned, P2 appended)" in header
        assert "1 bail-out" in header
        assert "1 test round" in header
        assert "doc phase done" in header
        assert "$" not in header      # no cost block yet — omitted, not guessed
        log = (slice_dir / "log.txt").read_text()
        assert "close-out report: A 0 · N 0 · B 0 · Q 0 · S 0" in log


def test_writer_question_resume_dispatches_writer_with_tagged_ruling():
    """A writer `question` mid-review resumes into a writer fix round — the
    ruling pointer is tagged onto the round's review report — never into a
    review of the unchanged branch (operator ruling, post-125)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        outputs = slice_dir / "phases" / "P1"

        def write_review(loop):
            (outputs / "code_review_r1.md").write_text(
                "# Review r1\n\nfindings\n")

        script = [V["exec_done"],
                  ("code-reviewer", {"outcome": "issues", "summary": "gaps"},
                   write_review),
                  ("code-writer", {"outcome": "question",
                                   "summary": "which mount point?"})]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 4
        state = load_state(slice_dir)
        assert state["phases"]["1"]["operator_question"] \
            == "which mount point?"

        # Job 3 wrote the ruling into the plan and resumed. The first
        # dispatch is the writer, its input the tagged review report.
        script2 = [("code-writer", {"outcome": "done",
                                    "summary": "ruling applied"}),
                   V["review_signoff"], *TAIL]
        r2 = ScriptedLoop(slice_dir, script2, resume=True, repo_root=repo)
        r2.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r2) == 0
        assert r2.spawned[0][0] == "code-writer"
        review = (outputs / "code_review_r1.md").read_text()
        assert "Operator ruling (post-round-1 question)" in review
        assert "which mount point?" in review
        assert "code_review_r1.md" in r2.prompts[0][1]
        state = load_state(slice_dir)
        assert "operator_question" not in state["phases"]["1"]


def test_executor_blocked_bails_as_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "blocked",
                                   "summary": "harness broken"})]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked" and bail["question"] is False


def test_review_round2_gets_delta_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        heads = iter(["head1", "head1", "head1", "head2", "head2", "head2",
                      "head2", "head2", "head2", "head2"])

        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        real_git = r.fake_git

        def moving_git(*args, root=None, check=True):
            if args == ("rev-parse", "HEAD"):
                return next(heads, "head2")
            return real_git(*args, root=root, check=check)

        r.git = moving_git
        assert run_to_exit(r) == 0
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert "Review the complete branch diff" in reviews[0]
        assert "Re-review phase P1" in reviews[1]
        assert "head1..HEAD" in reviews[1]


def test_dead_review_round_advances_nothing():
    """A reviewer that reports blocked bails without banking the round —
    review_rounds stays where it was."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"],
                  ("code-reviewer", {"outcome": "blocked",
                                     "summary": "cannot review"})]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3
        state = load_state(slice_dir)
        assert state["phases"]["1"]["review_rounds"] == 0


# -- plan-doc bookkeeping -----------------------------------------------------

def test_appended_phase_is_picked_up_next_iteration():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        # the executor for P1 appends P2 mid-run (a settlement its work
        # surfaced); the driver picks it up before the consult
        script = [
            ("code-writer", {"outcome": "done", "summary": "built"},
             append_phase("2", "Appended by executor")),
            V["review_signoff"],
            V["exec_done"], V["review_signoff"],
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["known_phases"] == ["1", "2"]
        assert state["phases"]["2"]["status"] == "merged"
        # mid-run appends by the executor are not a follow-up generation
        assert state["generation"] == 0


def test_malformed_plan_edit_is_nudged_back_to_its_author():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def break_plan(loop):
            with open(loop.plan_path, "a") as f:
                f.write("\n### P2 broken heading\n")

        script = [
            ("code-writer", {"outcome": "done", "summary": "built"},
             break_plan),
            V["review_signoff"], *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        nudges = []

        def fake_nudge(prompt, cwd, session_id, label, role):
            nudges.append((session_id, prompt))
            # the nudged session repairs its edit
            text = r.plan_path.read_text().replace(
                "### P2 broken heading\n", "")
            r.plan_path.write_text(text)

        r._nudge = fake_nudge
        assert run_to_exit(r) == 0
        assert len(nudges) == 1
        session_id, prompt = nudges[0]
        assert session_id == "sess-test"
        assert "not a phase heading" in prompt
        assert "plan doc now" in prompt


def test_plan_still_broken_after_nudge_is_an_operator_question():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def break_plan(loop):
            with open(loop.plan_path, "a") as f:
                f.write("\n### P2 broken heading\n")

        script = [("code-writer", {"outcome": "done", "summary": "b"},
                   break_plan)]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r._nudge = lambda *a, **kw: None   # the nudge fixes nothing
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plan_doc" and bail["question"] is True


def test_broken_plan_on_fresh_start_is_a_precondition_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        with open(slice_dir / "plan.md", "a") as f:
            f.write("\n### P2 — No target phase\n\nbody\n")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 2


def test_operator_broken_plan_on_resume_is_an_operator_question():
    """Structure errors with no session in the history (the operator's own
    edit, found on resume — preflight does not re-run) go straight to the
    operator."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        with open(slice_dir / "plan.md", "a") as f:
            f.write("\n### P2 — No target phase\n\nbody\n")
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "phases",
            "bases": {}, "slice_base": {}, "known_phases": [],
            "phases": {}, "generation": 0, "test_rounds": 0,
            "consult_seq": 0, "in_flight": None, "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plan_doc"
        assert "P2 has no `Target:` line" in bail["details"]


def test_vanished_phase_is_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First"), ("2", "Second")])

        def drop_p2(loop):
            text = loop.plan_path.read_text()
            loop.plan_path.write_text(text.split("### P2")[0])

        script = [("code-writer", {"outcome": "done", "summary": "b"},
                   drop_p2)]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r._nudge = lambda *a, **kw: None
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert "P2 vanished" in bail["details"]


def test_unknown_target_is_a_plan_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "X", "nosuch")])
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert "neither a `kc project list` component" in bail["details"]


# -- components a phase creates -----------------------------------------------
#
# A phase may register a NEW `kc project list` component (slice 181 stood up a
# second Node project). The run's opening snapshot of the component set would
# call that name invalid for the whole run, so the set is re-read at every plan
# load and a `Creates:` declaration covers the window before the phase runs.

def creating_plan(*sections):
    return "# plan\n\n" + "\n".join(sections)


def test_self_creating_phase_resolves_optimistically():
    """The executor registers the component mid-phase and the gate runs
    after, so the argv is right by the time it is used."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.project_dirs = {PROJECT: Path(repo)}
        target = r._resolve_target("newcomp", creates="newcomp")
        assert target.kind == "project"
        assert target.gate_argv == ["kc", "project", "test",
                                    "--project", "newcomp"]
        assert target.git_root == Path(repo) and target.gate_cwd == Path(repo)
        for kwargs in ({}, {"creates": "othercomp"}):
            try:
                r._resolve_target("newcomp", **kwargs)
            except ValueError as e:
                assert "neither a `kc project list` component" in str(e)
            else:
                raise AssertionError(
                    f"undeclared unknown target must raise ({kwargs})")


def test_target_errors_wait_for_the_phase_that_creates_the_component():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.project_dirs = {PROJECT: Path(repo)}

        def errors_for(*sections):
            phases, structure = parse_plan(creating_plan(*sections))
            assert structure == []
            return r._target_errors(phases)

        # an earlier pending phase declares it — expected, not wrong
        assert errors_for(
            phase_section("1", "Stand it up", PROJECT,
                          body="Creates: newcomp\n"),
            phase_section("2", "Use it", "newcomp")) == []
        # the phase creates its own target
        assert errors_for(
            phase_section("1", "Stand it up", "newcomp",
                          body="Creates: newcomp\n")) == []
        # the declarer has run and the component still is not there: the
        # claim was false, and the error names both phases
        done = errors_for(
            phase_section("1", "Stood it up", PROJECT, done=True,
                          body="Creates: newcomp\n"),
            phase_section("2", "Use it", "newcomp"))
        assert len(done) == 1
        assert done[0].startswith("phase P2:")
        assert "P1" in done[0] and "✅ DONE" in done[0]
        # nobody claims the name
        plain = errors_for(phase_section("1", "Use it", "newcomp"))
        assert len(plain) == 1
        assert "neither a `kc project list` component" in plain[0]
        # a LATER phase's declaration is no help — this phase runs first
        late = errors_for(
            phase_section("1", "Use it", "newcomp"),
            phase_section("2", "Stand it up", PROJECT,
                          body="Creates: newcomp\n"))
        assert len(late) == 1
        assert "neither a `kc project list` component" in late[0]


def test_plan_load_re_reads_the_component_set():
    """Resolution sees the manifest as it stands, not the run's opening
    snapshot — _load_plan runs after every phase merge."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "Use the new one", "newcomp")])
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        components = {PROJECT: Path(repo)}
        with patched(run_loop,
                     load_project_dirs=lambda cwd: dict(components)):
            try:
                r._load_plan()
            except Bailout as e:
                assert e.reason == "plan_doc"
            else:
                raise AssertionError("an unknown component must not parse")
            assert set(r.project_dirs) == {PROJECT}
            components["newcomp"] = Path(repo)   # the phase registered it
            phases = r._load_plan()
        assert [p.id for p in phases] == ["1"]
        assert set(r.project_dirs) == {PROJECT, "newcomp"}


def test_a_phase_creates_the_component_the_next_phase_targets():
    """End to end: P1 declares it and registers it, P2 targets it, and the
    loop-tail sweep sweeps it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Stand up the second project", PROJECT, False,
             "Creates: newcomp\n"),
            ("2", "Build it out", "newcomp"),
        ])
        components = {PROJECT: Path(repo)}

        def register(loop):
            components["newcomp"] = Path(repo)

        script = [
            ("code-writer", {"outcome": "done", "summary": "built"},
             register),
            V["review_signoff"], V["exec_done"], V["review_signoff"], *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop,
                     load_project_dirs=lambda cwd: dict(components)):
            assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["phases"]["2"]["status"] == "merged"
        assert state["phases"]["2"]["target"] == "newcomp"
        swept = {component for _, component, _ in r.sweep_calls}
        assert swept == {PROJECT, "newcomp"}


# -- sibling-repo targets -----------------------------------------------------

def make_sibling(tmp, name="Sibling", manifest=True):
    """A sibling repo next to the fake target repo (make_slice's tmp/repo),
    so a `../Sibling` Target resolves from it."""
    sib = Path(tmp) / name
    (sib / ".git").mkdir(parents=True)
    if manifest:
        (sib / ".kubecoder").mkdir()
        (sib / ".kubecoder" / "project.yaml").write_text("projects: []\n")
    return sib


def test_sibling_target_roots_git_and_gate_in_the_sibling():
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Chart change", "../Sibling"))
        assert run_to_exit(r) == 0
        # the phase's branch mutations landed in the sibling root (the doc
        # phase's branch lives in the invoking repo, by design)
        branch_ops = [(root, c) for root, c in r.fake_git.calls
                      if c[0] == "checkout"
                      and any("phase/074-P1" in a for a in c)]
        assert branch_ops and all(str(root) == str(sib)
                                  for root, c in branch_ops)
        # the executor is told where the work lands
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "sibling repo" in prompt and "Sibling" in prompt


def test_sibling_without_manifest_has_no_deterministic_gate():
    with tempfile.TemporaryDirectory() as tmp:
        make_sibling(tmp, manifest=False)
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "X", "../Sibling"))
        assert run_to_exit(r) == 0
        assert r.gate_calls == [], "no gate run for a manifest-less sibling"
        prompt = next(p for role, p in r.prompts if role == "code-reviewer")
        assert "unverified" in prompt


# -- the specs repo as a Target -----------------------------------------------
#
# A slice whose whole deliverable is in the spec repo (the wire contracts)
# names it as its `Target:` — and the driver's own run record, plus every
# parallel session's, lives inside that same tree. The `slices/` tree is
# therefore held out of the driver's git queries there.

def specs_as_target(tmp):
    """make_slice's specs tree, made resolvable as a sibling Target."""
    (Path(tmp) / "specs" / ".git").mkdir(parents=True, exist_ok=True)
    return "../specs"


def specs_phase(slice_dir, tmp, title="Contract slimming"):
    (slice_dir / "plan.md").write_text(
        "# plan\n\n" + phase_section("1", title, specs_as_target(tmp)))
    return (Path(tmp) / "specs").resolve()


def test_specs_target_holds_the_bookkeeping_tree_out_of_the_dirty_check():
    """The driver writes log.txt, state.json and phases/ into the tree it is
    about to dirty-check, and a parallel run leaves its own alongside. None
    of it may bail the run — but dirt outside `slices/` still must."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        specs = specs_phase(slice_dir, tmp)
        r.fake_git.dirty_roots[str(specs)] = (
            "?? slices/074_test_slice/log.txt\n"
            "?? slices/074_test_slice/state.json\n"
            "?? slices/074_test_slice/phases/\n"
            "?? slices/124_parallel_run/log.txt\n")
        assert run_to_exit(r) == 0
        specs_status = [c for root, c in r.fake_git.calls
                        if c[0] == "status" and str(root) == str(specs)]
        assert specs_status, "the phase never dirty-checked its target"
        assert all(":(exclude)slices" in c for c in specs_status)
        # the exclusion is scoped to the target that holds the slice folder:
        # the invoking repo's own checks are untouched
        assert all("--" not in c for root, c in r.fake_git.calls
                   if c[0] == "status" and str(root) == str(repo))


def test_specs_target_still_bails_on_dirt_outside_the_slices_tree():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"]], repo_root=repo)
        specs = specs_phase(slice_dir, tmp)
        r.fake_git.dirty_roots[str(specs)] = " M api/controller-api.md\n"
        r._nudge = lambda *a, **kw: None   # the nudge commits nothing
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "uncommitted" in bail["details"]


def test_executor_prompts_fence_off_the_run_record():
    """Every executor round is a fresh session, so the fence rides every
    executor prompt — and only when the target actually holds the record."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        specs_phase(slice_dir, tmp)
        assert run_to_exit(r) == 0
        writer_prompts = [p for role, p in r.prompts if role == "code-writer"]
        assert len(writer_prompts) == 2
        for prompt in writer_prompts:
            assert "git add -A" in prompt and str(slice_dir) in prompt

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "git add -A" not in prompt


def test_committed_run_record_bails_before_the_merge_checkout():
    """`git checkout <base>` would unlink the file the open log handle is
    writing to. An agent that swept the record into a commit is caught while
    the branch is still intact."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]],
                         repo_root=repo)
        specs = specs_phase(slice_dir, tmp)
        r.fake_git.branch_files = ("slices/074_test_slice/log.txt\n"
                                   "slices/074_test_slice/phases/P1/x.json\n")
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "log.txt" in bail["details"]
        assert not [c for root, c in r.fake_git.mutations("merge")
                    if str(root) == str(specs)]


def resume_state(target, stage="review"):
    return {
        "slice": "074_test_slice", "created_at": "t", "orchestrator": None,
        "run_phase": "phases", "bases": {}, "slice_base": {},
        "known_phases": ["1"],
        "phases": {"1": {"status": "in_progress", "stage": stage,
                         "branch": "phase/074-P1", "target": target,
                         "executor_rounds": 1, "gate_fix_rounds": 0,
                         "review_rounds": 0, "gate_runs": 0,
                         "gate_green_commit": None, "gate_green_log": None,
                         "reviewed_head": None}},
        "generation": 0, "test_rounds": 0, "consult_seq": 0,
        "in_flight": None, "history": [],
    }


def test_resume_reset_is_scoped_away_from_the_bookkeeping_tree():
    """A resume drops the dead round's uncommitted work — but `reset --hard`
    in the specs repo would take an agent's uncommitted plan.md edit with
    it. Elsewhere the reset is unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs_phase(slice_dir, tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state("../specs")))
        r = ScriptedLoop(slice_dir, [V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        assert not r.fake_git.mutations("reset")
        restores = [c for _, c in r.fake_git.mutations("restore")]
        assert restores and ":(exclude)slices" in restores[0]

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT)))
        r = ScriptedLoop(slice_dir, [V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        assert [c for _, c in r.fake_git.mutations("reset")] \
            == [("reset", "--hard", "HEAD")]
        assert not r.fake_git.mutations("restore")


# -- the branch under the record ----------------------------------------------

def test_a_second_driver_on_one_slice_is_refused():
    """The run record sits on the spec repo's shared mount and the code repo
    it branches does not, so two drivers on one slice folder rebuild each
    other's phase branches. The second one never gets that far."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        first = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert first._slice_lock.acquire() is None
        second = ScriptedLoop(slice_dir, [], repo_root=repo)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert run_to_exit(second) == 2
        assert "another driver is running this slice" in err.getvalue()
        assert f"pid: {os.getpid()}" in err.getvalue()
        assert not (slice_dir / "state.json").exists()
        # Released — by this driver's exit or by its death — the next one
        # walks straight in.
        first._slice_lock.release()
        assert second._slice_lock.acquire() is None
        second._slice_lock.release()


def test_a_recorded_commit_off_the_branch_bails_rather_than_rebuilding():
    """The branch is there but no longer carries the commit the driver saw
    green on it: something rebuilt it under the run."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = resume_state(PROJECT)
        state["phases"]["1"]["gate_green_commit"] = "abc123"
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        r.fake_git.lost.add("abc123")
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "lost_work" and bail["phase"] == "1"
        assert "abc123" in bail["details"]
        assert not r.spawned and not r.fake_git.mutations("checkout")


def test_a_fix_round_that_rebuilt_the_branch_stops_before_the_next_gate():
    """The same check after every executor round: the round hands back onto a
    branch that no longer carries what the review read."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_issues"],
                  ("code-writer", {"outcome": "done", "summary": "fixed"},
                   lambda loop: loop.fake_git.lost.add(loop.fake_git.head))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "lost_work"
        assert r.gate_calls == [("1", True)]   # no gate over the reduced tree


def test_a_branch_gone_with_its_work_merged_is_stamped_not_redone():
    """The crash window between the ff-merge and the state write. The work is
    in the base branch, so the resume finishes the bookkeeping instead of
    rebuilding the branch and spending a round redoing the phase."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = resume_state(PROJECT, stage="merging")
        state["phases"]["1"]["gate_green_commit"] = "abc123"
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, list(TAIL), resume=True, repo_root=repo)
        r.fake_git.merged.add("abc123")
        assert run_to_exit(r) == 0
        assert [s[0] for s in r.spawned] == ["consult", "test-agent",
                                             "doc-writer"]
        assert "✅ DONE" in (slice_dir / "plan.md").read_text()
        assert load_state(slice_dir)["phases"]["1"]["status"] == "merged"


def test_a_pending_phase_never_deletes_a_branch_the_run_cannot_account_for():
    """`git branch -D` on a name the record knows nothing about, carrying
    commits the base has not got, would drop them without a word."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        r.fake_git.ahead["main..phase/074-P1"] = "2"
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "lost_work"
        assert "2 commit(s)" in bail["details"]
        assert not [c for _, c in r.fake_git.mutations("branch")
                    if c[1] == "-D"]


# -- follow-up generations ----------------------------------------------------

def test_completion_consult_appends_phases_and_loops():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"],
            ("consult", {"outcome": "appended", "summary": "missing test"},
             append_phase("2", "Missing test")),
            V["exec_done"], V["review_signoff"],
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["generation"] == 1
        assert state["phases"]["2"]["status"] == "merged"
        consult_prompt = next(p for role, p in r.prompts
                              if role == "consult")
        assert "first follow-up generation" in consult_prompt


def test_generation_bar_carries_trivia_rider():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        consult_prompt = next(p for role, p in r.prompts
                              if role == "consult")
        test_prompt = next(p for role, p in r.prompts
                           if role == "test-agent")
        assert "mechanical residue" in consult_prompt
        assert "mechanical residue" in test_prompt
        # the rider states the sweep's limit rather than promising cover the
        # loop does not have: the test phase pushes before anything re-sweeps
        assert "never before a push your own\nprocedure doc orders" \
            in test_prompt


def test_consults_get_the_report_path_and_a_cards_list_is_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"],
            ("consult", {"outcome": "appended", "summary": "one gap",
                         "cards": ["byte-order sort in the picker"]},
             append_phase("2", "The gap")),
            V["exec_done"], V["review_signoff"],
            *TAIL,
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        for _, prompt in [(role, p) for role, p in r.prompts
                          if role == "consult"]:
            assert f"close-out report is {slice_dir / 'close-out.md'}" in prompt
            assert "Already carded" not in prompt
            assert '"cards"' not in prompt
        completion = next(p for role, p in r.prompts
                          if role == "consult" and "stamped done" in p)
        assert "one pass that reconciles" in completion
        # The reconcile goes through the tool — strike with a reason that
        # names the phase/commit, note for anything else — never a hand
        # edit of another agent's entry.
        flat = " ".join(completion.split())
        assert ('`strike <id> --reason "absorbed by P<x> (<commit>)" --by '
                '"consult <n>"`') in flat
        assert '"resolved by P<x> (<commit>): <what was re-run>"' in flat
        assert "observation about an entry with `note`" in flat
        assert "never by editing the file" in flat
        # A stale register's `cards` list is not state and never reaches
        # the report.
        state = load_state(slice_dir)
        assert "cards" not in state
        assert "byte-order sort" not in load_report(slice_dir)


def test_a_cards_list_in_a_verdict_is_logged_and_dropped():
    """A pre-0.5.0 register on an installed clone still emits `cards`; the
    real _spawn takes the verdict, notes the list once, and moves on — no
    protocol failure."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", {"outcome": "done", "summary": "built",
                             "cards": ["stale line pointer in D31"]}),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "done"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "docs"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        log = (slice_dir / "log.txt").read_text()
        assert "verdict carried a `cards` list — ignored" in log
        assert "cards" not in load_state(slice_dir)
        assert "stale line pointer" not in load_report(slice_dir)


def test_consult_appended_without_phases_treated_complete():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"],
            ("consult", {"outcome": "appended", "summary": "hm"}),
            V["test_clean"], V["doc_done"],
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["generation"] == 0


def test_test_phase_findings_loop_with_rising_bar_then_third_generation_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"],
            V["consult_complete"],
            ("test-agent", {"outcome": "findings", "summary": "broken flow"},
             append_phase("f1", "Fix the flow")),                # gen 1
            V["exec_done"], V["review_signoff"],
            V["consult_complete"],
            ("test-agent", {"outcome": "findings", "summary": "still off"},
             append_phase("f2", "Fix again")),                   # gen 2
            V["exec_done"], V["review_signoff"],
            V["consult_complete"],
            ("test-agent", {"outcome": "findings", "summary": "more"},
             append_phase("f3", "Never absorbed")),              # gen 3 → bail
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 4
        assert not r.script
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "generation_exhausted"
        assert bail["question"] is True
        test_prompts = [p for role, p in r.prompts if role == "test-agent"]
        assert "first follow-up generation" in test_prompts[0]
        assert "BLOCKING work only" in test_prompts[1]
        state = load_state(slice_dir)
        assert state["generation"] == 3


def test_test_phase_prompt_routes_sub_bar_findings_to_the_report():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("test-agent", {"outcome": "clean", "summary": "ok",
                            "cards": ["cosmetic: banner typo"]}),
            V["doc_done"],
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert f"close-out report is {slice_dir / 'close-out.md'}" in prompt
        assert "goes in the close-out report" in prompt
        assert "`cards`" not in prompt
        assert "cards" not in load_state(slice_dir)


def test_test_phase_prompt_states_devlock_and_procedure_doc():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert "test-plan.md" in prompt
        assert "devlock" in prompt and "pre-authorized" in prompt
        assert "prd stays operator-gated" in prompt
        assert "verification.json" in prompt


# -- the loop-tail gate sweep ---------------------------------------------------
#
# Slice 152 reached the completion consult with the manual known-red ("owed
# to the doc phase"); the consult answered `complete`, the test agent pushed
# "to confirm", and CI failed a build the tree could never pass. The driver
# now sweeps lint+build+test per component at loop-tail entry: the report
# rides the consult and test dispatches as deterministic fact, and a red
# tree is decided on at the consult — never discovered at push time.

def test_gate_sweep_runs_at_loop_tail_and_is_commit_stamped():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        # per component (the stub manifest has one), per verb, exactly once:
        # the record is reused for the test dispatch while HEAD is unmoved
        assert r.sweep_calls == [(str(repo), PROJECT, v)
                                 for v in ("lint", "build", "test")]
        state = load_state(slice_dir)
        assert state["sweep_runs"] == 1
        sweep = state["gate_sweep"]
        assert sweep["green"] is True
        assert sweep["commits"] == {str(repo): r.fake_git.head}
        assert len(sweep["results"]) == 3
        assert all(Path(res["log"]).is_file() for res in sweep["results"])


def test_gate_sweep_report_rides_the_consult_and_test_dispatches():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "loop-tail gate sweep" in consult
        assert f"{PROJECT} lint → GREEN" in consult
        assert str(slice_dir / "sweeps" / "r1") in consult
        assert "not something to re-derive or re-run" in consult
        test_prompt = next(p for role, p in r.prompts
                           if role == "test-agent")
        assert f"{PROJECT} test → GREEN" in test_prompt
        flat = test_prompt.replace("\n", " ")
        assert "do not re-run them to confirm it" in flat
        assert "a rebase produces a tree nothing has run against" in flat
        assert "a branch whose gates are red is not pushed" in flat


def test_gate_sweep_reruns_when_a_consult_moves_head():
    """A consult that commits (the mechanical-residue rider) invalidates
    the sweep: the test dispatch must describe the tree it actually sees."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"],
            ("consult", {"outcome": "complete", "summary": "done"},
             lambda lp: setattr(lp.fake_git, "head", "def456")),
            V["test_clean"], V["doc_done"],
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert len(r.sweep_calls) == 6, "one sweep per tree state"
        state = load_state(slice_dir)
        assert state["sweep_runs"] == 2
        assert state["gate_sweep"]["commits"] == {str(repo): "def456"}
        assert (slice_dir / "sweeps" / "r2").is_dir()


def test_gate_sweep_record_survives_a_resume_when_heads_match():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "blocked", "summary": "stuck"})]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r1) == 3
        assert len(r1.sweep_calls) == 3
        # a bail replays the consult on resume; the sweep record is not
        # replayed with it — same heads, same report
        r2 = ScriptedLoop(slice_dir,
                          [V["consult_complete"], V["test_clean"],
                           V["doc_done"]],
                          resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert r2.sweep_calls == [], \
            "an unmoved tree reuses the recorded sweep across a resume"


def test_red_sweep_states_the_principle_and_never_blocks_by_itself():
    """No driver enforcement, deliberately: the consult and the test agent
    get the red rows and the principle; the decision is theirs."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo,
                         sweep_reds={(PROJECT, "test")})
        assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        assert state["gate_sweep"]["green"] is False
        consult = next(p for role, p in r.prompts if role == "consult")
        flat = consult.replace("\n", " ")
        assert f"{PROJECT} test → RED" in consult
        assert "a branch whose gates are red is not pushed" in flat
        assert "append a phase that fixes it" in flat
        test_prompt = next(p for role, p in r.prompts
                           if role == "test-agent").replace("\n", " ")
        assert "does not leave the machine" in test_prompt


def test_sweep_targets_exclude_the_spec_repo_and_manifestless_repos():
    with tempfile.TemporaryDirectory() as tmp:
        sib_m = make_sibling(tmp, name="WithManifest")
        sib_n = make_sibling(tmp, name="NoManifest", manifest=False)
        slice_dir, repo = make_slice(tmp)
        specs = (Path(tmp) / "specs").resolve()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.state = {"bases": {str(repo): "main", str(sib_m): "main",
                             str(sib_n): "main", str(specs): "main"}}
        assert sorted(str(t) for t in r._sweep_targets()) \
            == sorted([str(repo), str(sib_m)])


def test_sweep_with_no_targets_reports_unverified():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (repo / ".kubecoder" / "project.yaml").unlink()
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert r.sweep_calls == []
        assert load_state(slice_dir)["gate_sweep"]["results"] == []
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "unverified" in consult


def test_doc_gate_sweeps_lint_build_test_fail_fast():
    """The doc gate carries the same three verbs, whole-repo and fail-fast:
    it exists to go green or hand one red log to the fixer, not to report."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = repo
        loop.state = {"history": []}
        calls = []

        def fake_exec(argv, log_file):
            calls.append(argv[2])
            log_file.write(f"{argv[2]} ran\n")
            return 1 if argv[2] == "build" else 0

        loop._doc_gate_exec = fake_exec
        ds = {"gate_runs": 0}
        green, log_path = loop._run_doc_gate(ds)
        assert not green
        assert calls == ["lint", "build"], "fail-fast: test never ran"
        text = log_path.read_text()
        assert "$ kc project lint" in text
        assert "$ kc project build" in text
        assert "$ kc project test" not in text

        calls.clear()
        loop._doc_gate_exec = lambda argv, log_file: calls.append(
            argv[2]) or 0
        green, _ = loop._run_doc_gate(ds)
        assert green and calls == ["lint", "build", "test"]


# -- the fetch: nobody reads a remote-tracking ref as old as the clone --------
#
# The driver branches off the LOCAL base and ff-merges back, so it never
# fetches on its own account; a sibling clone keeps the `origin/<base>` it was
# cloned with until something refreshes it. One executor read a ref a day
# stale and raised a Blocker over a sibling commit that was on origin/main
# all along.

def fetch_precedes_checkout(loop, root):
    """The fetch landed before anything was branched or dispatched in `root`
    — a later one (the push check's) would not prove the phase fetched."""
    calls = [c for r, c in loop.fake_git.calls if str(r) == str(root)]
    return calls.index(("fetch", "origin")) \
        < next(i for i, c in enumerate(calls) if c[0] == "checkout")


def test_phase_start_fetches_the_target_repo_before_branching():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert fetch_precedes_checkout(r, sib)


def test_a_component_phase_fetches_the_invoking_repo():
    """`Target: <component>` roots in the invoking repo — same rule, and the
    only repo a single-repo slice ever reads."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert fetch_precedes_checkout(r, repo)


def test_test_phase_fetches_every_touched_repo_before_dispatch():
    """The test session works across all of them — it pushes them and
    verifies what the push deployed — not just the repo it spawns in."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        at_dispatch = []
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "clean", "summary": "ok"},
                   lambda loop: at_dispatch.extend(
                       str(root) for root, c in loop.fake_git.calls
                       if c[:2] == ("fetch", "origin"))),
                  V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        # the sibling was the phase's target; the invoking repo was fetched by
        # nothing but this loop, so its presence is the proof
        assert str(repo) in at_dispatch and str(sib) in at_dispatch


# -- the push check: every repo the slice touched is on its origin ------------
#
# Nothing in the driver pushes a code phase — `_run_phase` ff-merges locally
# in whichever repo the phase targeted — so the push is the test phase's, per
# its procedure doc. A reviewed-but-unpushed sibling commit never reaches the
# deploy it was meant for (one run's dev roll crash-looped that way), so the
# driver checks before the doc phase.

def sibling_phase_slice(tmp):
    """A slice whose one phase targets a sibling repo, so `state["bases"]`
    carries two roots for the push check to walk."""
    sib = make_sibling(tmp)
    slice_dir, repo = make_slice(tmp)
    (slice_dir / "plan.md").write_text(
        "# plan\n\n" + phase_section("1", "Chart change", "../Sibling"))
    return slice_dir, repo, sib


def test_unpushed_sibling_is_nudged_back_to_the_test_session():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "1"
        nudges = []

        def fake_nudge(prompt, cwd, session_id, label, role):
            nudges.append((session_id, prompt))
            r.fake_git.unpushed.clear()   # the nudged session pushes

        r._nudge = fake_nudge
        assert run_to_exit(r) == 0
        assert len(nudges) == 1
        session_id, prompt = nudges[0]
        assert session_id == "sess-test", "the test agent's own session"
        assert str(sib) in prompt and "1 commit(s)" in prompt
        assert "Do not start other work" in prompt
        # the check probed the sibling, not just the invoking repo
        assert any(str(root) == str(sib) and c[0] == "rev-list"
                   for root, c in r.fake_git.calls)


def test_still_unpushed_past_the_cap_bails_before_the_doc_phase():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "3"
        nudges = []
        r._nudge = lambda *a, **kw: nudges.append(a)
        assert run_to_exit(r) == 3
        assert len(nudges) == run_loop.PUSH_NUDGE_CAP
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "unpushed" and bail["question"] is False
        assert str(sib) in bail["details"] and "3 commit(s)" in bail["details"]
        assert not any(role == "doc-writer" for role, *_ in r.spawned)
        assert not r.fake_git.mutations("push")


def test_a_repo_with_no_origin_branch_at_all_counts_as_unpushed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.no_origin.add(str(sib))
        prompts = []

        def fake_nudge(prompt, cwd, session_id, label, role):
            prompts.append(prompt)
            r.fake_git.no_origin.clear()

        r._nudge = fake_nudge
        assert run_to_exit(r) == 0
        assert len(prompts) == 1 and "no origin/main at all" in prompts[0]


def test_push_check_skips_the_spec_repo():
    """The spec repo's commits are the slice's own record — they land at
    close-out and nothing deploys from them."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        specs = specs_phase(slice_dir, tmp)
        r.fake_git.unpushed[str(specs)] = "4"
        r._nudge = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("the spec repo must not be push-checked"))
        assert run_to_exit(r) == 0
        # never probed against origin (it is still fetched at phase start,
        # like any target repo the driver points an agent at)
        assert not [c for root, c in r.fake_git.calls
                    if c[0] == "rev-list" and str(root) == str(specs)]


def test_clean_test_phase_checks_the_invoking_repo_too():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.unpushed[str(repo)] = "2"
        r._nudge = lambda *a, **kw: None
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "unpushed" and str(repo) in bail["details"]


# -- push holds: a repo the plan forbids this run to push ---------------------
#
# Slice 135's plan carried an operator ruling holding `../HelmCharts` (its
# push deploys dev and prd together). The test agent honoured it, the driver
# had no representation for it, and the run's only two exits were violate the
# ruling or bail — it bailed, and the push happened anyway 38s later.

def held_sibling_slice(tmp, why="a push deploys dev and prd together"):
    slice_dir, repo, sib = sibling_phase_slice(tmp)
    (slice_dir / "plan.md").write_text(
        f"# plan\n\n## Push holds\n\n- ../Sibling — {why}\n\n"
        + phase_section("1", "Chart change", "../Sibling"))
    return slice_dir, repo, sib


def _never_nudge(*a, **kw):
    raise AssertionError("a held repo must never be nudged")


def test_a_held_sibling_is_reported_not_nudged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "2"
        r._nudge = _never_nudge
        assert run_to_exit(r) == 0
        report = load_report(slice_dir)
        assert "Push Sibling by hand when its hold lifts" in report
        assert "a push deploys dev and prd together" in report
        assert load_state(slice_dir)["holds_reported"] == [str(sib)]
        # the invoking repo is not held, so the doc phase still pushes it
        pushes = r.fake_git.mutations("push")
        assert pushes and pushes[-1][0] == repo


def test_a_held_repo_already_on_origin_owes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r._nudge = _never_nudge
        assert run_to_exit(r) == 0
        assert load_state(slice_dir).get("holds_reported", []) == []
        assert "hold lifts" not in load_report(slice_dir)


def test_an_unheld_repo_is_still_nudged_beside_a_held_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "2"
        r.fake_git.unpushed[str(repo)] = "1"
        nudges = []

        def fake_nudge(prompt, cwd, session_id, label, role):
            nudges.append(prompt)
            r.fake_git.unpushed.pop(str(repo))

        r._nudge = fake_nudge
        assert run_to_exit(r) == 0
        assert len(nudges) == 1
        assert str(repo) in nudges[0]
        assert str(sib) not in nudges[0], "the held repo is not asked for"


def test_the_test_phase_dispatch_names_the_held_repos():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r._nudge = _never_nudge
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert "The plan holds these repos" in prompt
        assert "  - ../Sibling — a push deploys dev and prd together" in prompt


def test_no_holds_leaves_the_test_dispatch_as_it_was():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert "The plan holds these repos" not in prompt
        assert "\n\nDeterministic fact from the driver" in prompt


def test_a_held_primary_repo_lands_the_docs_locally_and_never_pushes():
    """The hold is repo-scoped, and the doc landing is the one place the
    driver itself pushes — so it merges and stops."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            f"# plan\n\n## Push holds\n\n- {PROJECT} — prd rolls on this "
            "push\n\n" + phase_section("1", "First phase"))
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.fake_git.unpushed[str(repo)] = "3"
        r._nudge = _never_nudge
        assert run_to_exit(r) == 0
        assert not r.fake_git.mutations("push")
        # rebased onto the LOCAL base: a held repo's origin is behind by
        # everything the slice landed, so `origin/main` is the wrong target
        rebases = r.fake_git.mutations("rebase")
        assert rebases and rebases[-1][1] == ("rebase", "main")
        assert "Push repo by hand when its hold lifts" in load_report(slice_dir)


def test_an_unresolvable_hold_is_a_plan_structure_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n## Push holds\n\n- ../Nope — held\n\n"
            + phase_section("1", "First phase"))
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plan_doc" and bail["question"] is True
        assert "push hold `../Nope`" in bail["details"]


def test_doc_phase_prompt_states_diff_files_digest_verbs_and_doc():
    """The doc-writer's dispatch carries the driver's deterministic facts:
    the diff on disk per repo (stat, then the diff, over slice base..base
    branch — never HEAD, which is the doc branch), the whole-plan digest
    with every done-record, the close-out verbs' argument shapes, and the
    branch it works on."""
    def done_record(loop):
        loop.plan_path.write_text(
            loop.plan_path.read_text().rstrip("\n")
            + "\n\n**Done (P1).** Shipped the thing; the flag is `--x`.\n")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "slice.md").write_text("# S\n\nnot the writer's\n")
        script = [(*V["exec_done"], done_record), V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.stat = (" a.py | 2 +-\n"
                           " 1 file changed, 1 insertion(+), 1 deletion(-)")
        r.fake_git.diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                           "@@ -1 +1 @@\n-x\n+y")
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert "doc-plan.md" in prompt
        assert "phase/074-docs" in prompt
        assert "Never push" in prompt
        # the diff file: stat on top, then the diff, over slice base..base
        diff_file = slice_dir / "doc_phase" / "repo.diff"
        text = diff_file.read_text()
        assert text.startswith(f"{repo} — git diff abc123..main\n")
        assert text.index(" a.py | 2 +-") < text.index("diff --git a/a.py")
        assert (f"- {repo}: {diff_file} (`git diff abc123..main`: "
                "1 file changed, 1 insertion(+), 1 deletion(-))") in prompt
        assert [c for _, c in r.fake_git.calls
                if c[:2] == ("diff", "abc123..main")]
        assert not [c for _, c in r.fake_git.calls
                    if c[0] == "diff" and "HEAD" in c[-1]]
        # the whole-plan digest, with the done-record and not the intent
        assert "# Orientation digest — the whole slice" in prompt
        assert "**Done (P1).** Shipped the thing" in prompt
        assert "not the writer's" not in prompt
        assert "slice.md is not your input" in prompt
        # the close-out verbs' argument shapes, from the tool's own parser
        assert "close_out.py append --section {" in prompt
        assert "--consequence: what an operator or user experiences" in prompt
        assert "close_out.py note --by BY" in prompt
        assert "close_out.py strike" not in prompt
        assert "Focus: <!-- doc-writer: … -->" in prompt


def test_doc_phase_diff_rows_name_unchanged_repos_without_a_file():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert f"- {repo}: no changes (`git diff abc123..main`)" in prompt
        assert not list((slice_dir / "doc_phase").iterdir())


def test_doc_phase_runs_on_branch_and_driver_lands_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        # the driver's sweep ran green once, then the branch was landed
        assert r.doc_gate_calls == [True]
        checkouts = r.fake_git.mutations("checkout")
        assert any("phase/074-docs" in c for _, c in checkouts)
        rebases = r.fake_git.mutations("rebase")
        assert any("origin/main" in c for _, c in rebases)
        merges = r.fake_git.mutations("merge")
        assert any("phase/074-docs" in c and "--ff-only" in c
                   for _, c in merges)
        pushes = r.fake_git.mutations("push")
        assert pushes and pushes[-1][1] == ("push", "origin", "main")
        state = load_state(slice_dir)
        assert state["doc_phase"]["stage"] == "done"


def test_red_doc_sweep_is_nudged_back_to_the_writer():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, doc_gates=[False, True],
                         repo_root=repo)
        nudges = []
        r._nudge = lambda prompt, cwd, sid, label, role: nudges.append(
            (sid, prompt))
        assert run_to_exit(r) == 0
        assert r.doc_gate_calls == [False, True]
        assert len(nudges) == 1
        sid, prompt = nudges[0]
        assert sid == "sess-test"
        assert "`kc project lint` + `build` + `test`" in prompt
        assert "doc_gate_r1.log" in prompt
        assert "do not push" in prompt
        # still landed after the nudge made it green
        assert r.fake_git.mutations("push")


def test_doc_sweep_red_past_cap_bails_without_pushing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        cap = run_loop.GATE_FIX_CAP
        r = ScriptedLoop(slice_dir, script, doc_gates=[False] * (cap + 1),
                         repo_root=repo)
        r._nudge = lambda *a, **kw: None
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "gate_red"
        assert not r.fake_git.mutations("push")


def test_doc_landing_bails_when_local_base_outruns_origin():
    """The doc branch rebases onto `origin/{base}` but ff-merges into local
    `base`. A commit only local `base` carries makes those two divergent, so
    the landing must bail with the diagnosis before it touches a branch —
    not die on git's raw "Diverging branches can't be fast-forwarded"."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.branches.add("phase/074-docs")
        r.fake_git.unpushed[str(repo)] = "1"
        try:
            r._land_doc_branch("phase/074-docs", "main")
        except Bailout as exc:
            assert exc.reason == "blocked"
            assert "1 commit(s)" in exc.details
            assert "origin/main" in exc.details
        else:
            raise AssertionError("a diverged local base must bail")
        # nothing was mutated: no checkout, no rebase, no merge, no push
        for verb in ("checkout", "rebase", "merge", "push"):
            assert not r.fake_git.mutations(verb), f"{verb} ran anyway"


def test_doc_landing_tolerates_origin_ahead_of_local_base():
    """The other direction is harmless and must still land: the rebase picks
    up whatever a parallel session pushed, and local `base` is an ancestor of
    the rebased branch, so the ff-merge is clean."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.branches.add("phase/074-docs")
        r._land_doc_branch("phase/074-docs", "main")
        assert any("origin/main" in c for _, c in r.fake_git.mutations("rebase"))
        pushes = r.fake_git.mutations("push")
        assert pushes and pushes[-1][1] == ("push", "origin", "main")


def test_doc_landing_resume_with_merged_branch_only_pushes():
    """A crash between the doc merge and the push resumes into a landing
    stage whose branch is gone — the driver must only push, never reset to
    the writer stage."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "docs",
            "bases": {str(repo): "main"}, "slice_base": {str(repo): "abc123"},
            "known_phases": ["1"],
            "phases": {"1": {"status": "merged", "stage": None,
                             "executor_rounds": 1, "review_rounds": 1,
                             "gate_runs": 1, "gate_fix_rounds": 0}},
            "generation": 0, "test_rounds": 1, "consult_seq": 1,
            "in_flight": None, "history": [],
            "doc_phase": {"stage": "landing", "gate_runs": 1, "nudges": 0,
                          "session": "sess-old"},
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.spawned, "no session may be spawned on this resume"
        pushes = r.fake_git.mutations("push")
        assert pushes and pushes[-1][1] == ("push", "origin", "main")
        assert not r.fake_git.mutations("rebase")


# -- optional phases (.aiworkflowrc) -----------------------------------------

def pushes(loop):
    """Every `git push` the driver made, as (root, branch)."""
    return [(str(root), args[2]) for root, args in loop.fake_git.calls
            if args and args[0] == "push"]


def test_a_project_with_no_test_phase_dispatches_none_and_pushes_itself():
    """Nothing in the driver pushes a code phase, and the test phase's
    procedure doc is what pushes when there is one — so with the phase off the
    driver owes the push itself, or the slice never leaves the pod."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False))
        script = [V["exec_done"], V["review_signoff"],
                  V["consult_complete"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not [role for role, *_ in r.spawned if role == "test-agent"]
        assert (str(repo), "main") in pushes(r)


def test_a_project_with_no_doc_phase_ends_when_the_test_phase_is_clean():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(doc=False))
        script = [V["exec_done"], V["review_signoff"],
                  V["consult_complete"], V["test_clean"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not [role for role, *_ in r.spawned if role == "doc-writer"]
        assert load_state(slice_dir)["run_phase"] == "done"


def test_a_project_that_runs_neither_phase_still_pushes_what_it_committed():
    """The Ansible shape: phases merge, the driver pushes, the run ends."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False, doc=False))
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert [role for role, *_ in r.spawned] == ["code-writer",
                                                    "code-reviewer", "consult"]
        assert (str(repo), "main") in pushes(r)


def test_the_drivers_own_push_honours_a_plan_hold():
    """With no test phase the driver is the pusher, so the plan's holds bind
    it exactly as they bind the test agent — reported, never pushed."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False, doc=False))
        (slice_dir / "plan.md").write_text(
            f"# plan\n\n## Push holds\n\n- {PROJECT} — prd rolls on this "
            "push\n\n" + phase_section("1", "First phase"))
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == []
        assert "Push repo by hand when its hold lifts" in load_report(slice_dir)


def test_a_project_that_never_pushes_reports_no_outstanding_keystroke():
    """A standing mode is not an outstanding action: `push.enabled = false`
    says every run stays local, so there is nothing for the operator to do
    later — unlike a plan hold, which is one slice's exception."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, config=rc(test=False, doc=False, push=False))
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert "hold lifts" not in load_report(slice_dir)


def test_push_disabled_leaves_every_commit_local():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, config=rc(test=False, doc=False, push=False))
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == []


def test_with_no_push_the_doc_branch_lands_on_the_local_base():
    """Origin is not part of a no-push run at all: rebasing the doc branch onto
    `origin/main` would sit the docs on a base missing every phase the slice
    merged, and the ahead-check would bail on it first."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False, push=False))
        script = [V["exec_done"], V["review_signoff"],
                  V["consult_complete"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.unpushed[str(repo)] = "3"   # would have bailed `blocked`
        assert run_to_exit(r) == 0
        assert ("rebase", "main") in [a for _, a in r.fake_git.calls
                                      if a and a[0] == "rebase"]
        assert pushes(r) == []


def test_the_doc_phase_takes_the_devlock_when_there_is_no_test_phase():
    """The lease is held by whichever phase runs first — the doc phase rolls
    dev too."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False, devlock=True))
        scripts_dir = slice_dir.parent.parent / "scripts"
        scripts_dir.mkdir()
        held = []
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("doc-writer", {"outcome": "done", "summary": "ok"},
             lambda loop: held.append((scripts_dir / "dev-holder").exists())),
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert held == [True]
        assert not (scripts_dir / "dev-holder").exists(), "released at end"


def test_a_repo_with_no_aiworkflowrc_cannot_be_driven():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (repo / ".aiworkflowrc").unlink()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 2


# -- the devlock --------------------------------------------------------------

def test_devlock_held_across_test_and_doc_phases():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(devlock=True))
        scripts_dir = slice_dir.parent.parent / "scripts"
        scripts_dir.mkdir()
        events = []
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("test-agent", {"outcome": "clean", "summary": "ok"},
             lambda loop: events.append(
                 ("test", (scripts_dir / "dev-holder").exists()))),
            ("doc-writer", {"outcome": "done", "summary": "ok"},
             lambda loop: events.append(
                 ("doc", (scripts_dir / "dev-holder").exists()))),
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert events == [("test", True), ("doc", True)]
        assert not (scripts_dir / "dev-holder").exists(), "released at end"
        note_free = not (scripts_dir / ".devlock.lock").exists() or True
        assert note_free


def test_devlock_released_on_bail():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(devlock=True))
        scripts_dir = slice_dir.parent.parent / "scripts"
        scripts_dir.mkdir()
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("test-agent", {"outcome": "blocked", "summary": "no cluster"}),
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3
        assert not (scripts_dir / "dev-holder").exists()


def test_devlock_unconfigured_is_a_noop():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)   # the default rc names no lease
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.devlock.configured


# -- protocol machinery (SpawningLoop: the real _spawn) -----------------------

def test_session_limit_waits_then_redispatches_the_same_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", SESSION_LIMIT_TEXT),   # killed by the window
            ("code-writer", {"outcome": "done", "summary": "built"}),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "done"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert len(r.sleeps) == 1 and 0 < r.sleeps[0] <= 12 * 3600
        state = load_state(slice_dir)
        assert state["phases"]["1"]["executor_rounds"] == 1, (
            "a session-limit kill spends no round")
        limits = [h for h in state["history"]
                  if h["outcome"] == "session_limit"]
        assert len(limits) == 1


def test_missing_verdict_gets_one_nudge_then_counts_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", "did some work, forgot the verdict")]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        nudges = []
        r._nudge = lambda prompt, cwd, sid, label, role: nudges.append(prompt)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        assert len(nudges) == 1
        assert "verdict" in nudges[0]
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "missing/unparseable" in bail["details"]


def test_dispatch_passes_model_and_effort_explicitly():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", {"outcome": "done", "summary": "b"}),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "d"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        by_role = {role: (model, effort)
                   for role, _, model, effort in r.sessions}
        assert by_role["code-writer"] == ("opus", "xhigh")
        assert by_role["code-reviewer"] == ("opus", "xhigh")
        assert by_role["consult"] == ("opus", "xhigh")
        assert by_role["doc-writer"] == ("opus", "xhigh")
        assert by_role["test-agent"] == ("sonnet", None)


def test_dispatch_trims_the_prefix_per_role():
    """Every dispatch passes `--disable-slash-commands`; every role but the
    test-agent — the one that drives CI through the operator's Jenkins MCP
    server — also passes `--strict-mcp-config`. Nudges carry the resumed
    role's flags: a prefix that differs from the original's misses the
    cache."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", {"outcome": "done", "summary": "b"}),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "d"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        by_role = dict(r.session_flags)
        for role in ("code-writer", "code-reviewer", "consult", "doc-writer"):
            assert by_role[role] == ["--disable-slash-commands",
                                     "--strict-mcp-config"], role
        assert by_role["test-agent"] == ["--disable-slash-commands"]
    assert run_loop.spawn_flags(None) == run_loop.spawn_flags("consult")
    assert "--strict-mcp-config" not in run_loop.spawn_flags("test-agent")


def test_announce_lines_mark_job_starts():
    """stdout carries one terse timestamped line per job start / phase
    merge / close-out — the watching caller's progress feed."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", {"outcome": "done", "summary": "b"}),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "d"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        out = io.StringIO()
        with patched(run_loop, run_kc_session=r.run_kc_session), \
                contextlib.redirect_stdout(out):
            assert run_to_exit(r) == 0
        lines = [ln for ln in out.getvalue().splitlines() if ln]
        assert lines, "the run announced nothing"
        assert all(re.match(r"^\[\d\d:\d\d:\d\d\] ", ln) for ln in lines)
        joined = "\n".join(lines)
        assert "P1 code-writer r1" in joined
        assert "P1 code-reviewer r1" in joined
        assert "P1 merged" in joined
        assert "test-phase" in joined
        assert "doc-phase" in joined
        assert "complete:" in joined


def test_timed_out_session_bails_without_reattach():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", TIMED_OUT)]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "timeout"
        state = load_state(slice_dir)
        assert state["in_flight"] is None, "a stuck session never reattaches"


def test_timed_out_session_keeps_a_verdict_it_had_already_written():
    """The turn wedged after the agent finished: the verdict on disk is this
    round's (every dispatch unlinks it first), so the round counts rather
    than throwing away work that is already committed."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", timed_out_after({"outcome": "done",
                                             "summary": "built, then wedged"})),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "done"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        nudges = []
        r._nudge = lambda prompt, cwd, sid, label, role: nudges.append(prompt)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script, "the salvaged round was re-dispatched"
        assert not nudges, "a complete verdict needs no nudge"
        assert not (slice_dir / "bailout.json").exists()
        state = load_state(slice_dir)
        assert state["in_flight"] is None, "a stuck session never reattaches"
        assert ("code-writer", "done") in [
            (h["role"], h["outcome"]) for h in state["history"]]


# -- resume / reattach --------------------------------------------------------

def test_resume_reattaches_the_in_flight_session():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        # simulate a crashed run: state.json with an in-flight executor
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "phases",
            "bases": {}, "slice_base": {}, "known_phases": ["1"],
            "phases": {"1": {"status": "in_progress", "stage": "executor",
                             "branch": "phase/074-P1", "target": PROJECT,
                             "executor_rounds": 1, "gate_fix_rounds": 0,
                             "review_rounds": 0, "gate_runs": 0,
                             "gate_green_commit": None,
                             "gate_green_log": None,
                             "reviewed_head": None}},
            "generation": 0, "test_rounds": 0, "consult_seq": 0,
            "in_flight": {"phase": "1", "role": "code-writer", "round": 1,
                          "verdict_path": "x", "session": "sess-crashed"},
            "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        role, phase, round_, outcome, resumed = r.spawned[0]
        assert role == "code-writer" and resumed == "sess-crashed"
        # the reattached round keeps its number: no new round was banked
        assert load_state(slice_dir)["phases"]["1"]["executor_rounds"] == 2


def test_resume_at_docs_skips_consult_and_test():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "docs",
            "bases": {str(repo): "main"}, "slice_base": {str(repo): "abc123"},
            "known_phases": ["1"],
            "phases": {"1": {"status": "merged", "stage": None,
                             "branch": None, "target": PROJECT,
                             "executor_rounds": 1, "gate_fix_rounds": 0,
                             "review_rounds": 1, "gate_runs": 1,
                             "gate_green_commit": "abc123",
                             "gate_green_log": "x",
                             "reviewed_head": "abc123"}},
            "generation": 0, "test_rounds": 1, "consult_seq": 1,
            "in_flight": None, "history": [],
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert [role for role, *_ in r.spawned] == ["doc-writer"]


# -- session-limit parsing ----------------------------------------------------

def test_session_limit_reset_parsing():
    parse = run_loop.parse_session_limit_reset
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 7, 20, 21, 0, tzinfo=tz)
    reset = parse("resets 10:10pm (Europe/Amsterdam)", now=now)
    assert reset == datetime(2026, 7, 20, 22, 10, tzinfo=tz)
    # a reset already past today is tomorrow's
    reset = parse("resets 8pm (Europe/Amsterdam)", now=now)
    assert reset == datetime(2026, 7, 21, 20, 0, tzinfo=tz)
    assert parse("resets sometime later") is None
    assert parse("resets 9:75pm (Europe/Amsterdam)", now=now) is None
    assert parse("resets 9pm (Mars/Olympus)", now=now) is None


def test_session_limit_notice_detection():
    class R:
        result_text = SESSION_LIMIT_TEXT
    assert run_loop.session_limit_notice(R()) == SESSION_LIMIT_TEXT

    class R2:
        result_text = "all done, verdict written"
    assert run_loop.session_limit_notice(R2()) is None


def test_protocol_failure_detail_reports_rc_and_verdict_separately():
    detail = run_loop._protocol_failure_detail
    ok = detail("code-writer", 143, {"outcome": "done"}, "v.json",
                valid=True, nudged=False)
    assert "rc=143" in ok and "valid outcome 'done'" in ok
    bad = detail("code-writer", 0, {"outcome": "banana"}, "v.json",
                 valid=False, nudged=True)
    assert "invalid outcome 'banana'" in bad and "after one nudge" in bad
    missing = detail("code-writer", 1, None, "v.json", valid=False,
                     nudged=False)
    assert "missing/unparseable" in missing


def test_orchestrator_session_recorded_from_env():
    old = os.environ.get("CLAUDE_CODE_SESSION_ID")
    os.environ["CLAUDE_CODE_SESSION_ID"] = "orch-123"
    try:
        record = run_loop._orchestrator_record()
        assert record["session"] == "orch-123"
        assert record["transcript"].endswith("orch-123.jsonl")
    finally:
        if old is None:
            del os.environ["CLAUDE_CODE_SESSION_ID"]
        else:
            os.environ["CLAUDE_CODE_SESSION_ID"] = old


def test_transcript_path_munges_cwd():
    path = run_loop._transcript_path("/work/My Repo", "sess-1")
    assert path.endswith("-work-My-Repo/sess-1.jsonl")
    assert run_loop._transcript_path("/work/x", None) is None


# -- preconditions ------------------------------------------------------------

def test_missing_plan_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").unlink()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 2


def test_dirty_worktree_fails_preflight():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.dirty = " M some/file.py"
        assert run_to_exit(r) == 2


def test_existing_state_requires_resume():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text("{}")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 2


def test_assert_agents_reports_missing_definitions():
    """The definitions ship with the plugin, so an incomplete agents/ dir means
    a broken install — not something the target repo can supply."""
    with tempfile.TemporaryDirectory() as tmp:
        agents = Path(tmp) / "agents"
        agents.mkdir(parents=True)
        for role in ("code-writer", "code-reviewer"):
            (agents / f"{role}.md").write_text("---\nname: x\n---\n")
        loop = RunLoop.__new__(RunLoop)
        with patched(run_loop, AGENTS_DIR=agents):
            try:
                loop._assert_agents()
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("missing agents must exit 2")


def test_every_required_agent_ships_with_the_plugin():
    """REQUIRED_AGENTS and the shipped agents/ dir must not drift apart — a
    role added to one without the other bails every run at dispatch time."""
    loop = RunLoop.__new__(RunLoop)
    loop._assert_agents()


def _create_args(**kwargs) -> list[str]:
    """Run run_kc_session far enough to capture the create-headless argv, then
    let the refused create short-circuit the rest."""
    seen = []

    class Refused:
        returncode, stdout, stderr = 1, "", "refused"

    class FakeSubprocess:
        @staticmethod
        def run(args, **_):
            seen.append(args)
            return Refused()

    with patched(run_loop, subprocess=FakeSubprocess):
        run_loop.run_kc_session("prompt", "/tmp", 60, **kwargs)
    return seen[0]


def test_dispatch_namespaces_the_agent_name():
    """Agents ship in the plugin and resolve as `dev:<role>`. kc does not
    validate the name, so a bare one would silently spawn a plain SDK session
    that answers anyway — the failure mode this assertion exists to catch."""
    args = _create_args(agent="code-writer")
    assert args[args.index("--agent") + 1] == "dev:code-writer"


def test_consults_dispatch_with_no_agent_at_all():
    """Consults are prompt-only: no definition, so no --agent to namespace."""
    assert "--agent" not in _create_args()


def test_spawn_flags_reach_create_headless_verbatim():
    """kc's pass-through options carry claude's own flag names, so the
    dispatch appends them as given — after the env vars, nothing in
    between."""
    args = _create_args(extra_env={"A": "1"},
                        flags=run_loop.spawn_flags("code-writer"))
    i = args.index("-e")
    assert args[i:] == ["-e", "A=1", "--disable-slash-commands",
                        "--strict-mcp-config"]
    assert "--strict-mcp-config" not in _create_args(
        flags=run_loop.spawn_flags("test-agent"))
    assert "--disable-slash-commands" not in _create_args()


# -- dry run ------------------------------------------------------------------

def test_dry_run_lists_phases_and_validates_targets(capsys=None):
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        root = Path(tmp) / "repo"
        root.mkdir(exist_ok=True)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Done already", PROJECT, done=True)
            + "\n" + phase_section("2", "Component work", PROJECT)
            + "\n" + phase_section("3", "Chart work", "../Sibling"))
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                raise AssertionError(
                    f"dry run must pass, exited {e.code}") from None
        text = out.getvalue()
        assert "3 phase(s)" in text
        assert "P1  DONE" in text
        assert f"target={PROJECT} [project]" in text
        assert "target=../Sibling [sibling]" in text
        assert str(sib) in text


def test_dry_run_flags_bad_targets():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "X", "nosuch"))
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("bad target must exit 2")
        assert "target=INVALID" in out.getvalue()
        assert "neither a `kc project list` component" in err.getvalue()


def test_dry_run_accepts_a_target_a_phase_creates():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Stand it up", PROJECT,
                            body="Creates: newcomp\n")
            + "\n" + phase_section("2", "Use it", "newcomp")
            + "\n" + phase_section("3", "Its own target", "othercomp",
                                   body="Creates: othercomp\n"))
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                raise AssertionError(
                    f"declared components must pass, exited {e.code}"
                ) from None
        text = out.getvalue()
        assert "target=newcomp [project]  (created by P1)" in text
        assert "target=othercomp [project]  (created by P3)" in text
        assert "INVALID" not in text


def test_dry_run_flags_a_component_a_done_phase_never_created():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Stood it up", PROJECT, done=True,
                            body="Creates: newcomp\n")
            + "\n" + phase_section("2", "Use it", "newcomp"))
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("a false `Creates:` claim must exit 2")
        assert "target=INVALID" in out.getvalue()
        assert "declared `Creates:` by phase P1" in err.getvalue()


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
            print(f"FAIL {_fn.__name__}: {e}")
    print(f"\n{len(_tests) - failures} passed, {failures} failed")
    if failures:
        sys.exit(1)
